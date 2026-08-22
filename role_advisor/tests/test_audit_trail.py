# Copyright (c) 2026, ghost-mann and contributors
# For license information, please see license.txt

import json

import frappe
from frappe.tests import IntegrationTestCase, UnitTestCase

from role_advisor import audit_trail
from role_advisor.tests.fixtures import ensure_user


class TestDeltaScalarFields(UnitTestCase):
	def test_v15_profile_change_becomes_before_and_after(self):
		data = json.dumps({"changed": [["role_profile_name", "Clerk", "Agriculture Supervisor"]]})

		delta = audit_trail._delta(data, "User")

		self.assertEqual(delta["profile_before"], "Clerk")
		self.assertEqual(delta["profile_after"], "Agriculture Supervisor")
		self.assertEqual(delta["fields"], [])

	def test_interesting_scalars_are_kept(self):
		data = json.dumps(
			{"changed": [["enabled", 1, 0], ["user_type", "System User", "Website User"]]}
		)

		delta = audit_trail._delta(data, "User")

		self.assertIn(("enabled", 1, 0), delta["fields"])
		self.assertIn(("user_type", "System User", "Website User"), delta["fields"])

	def test_ordinary_churn_is_dropped_entirely(self):
		data = json.dumps(
			{"changed": [["birth_date", "1990-01-01", "1990-01-02"], ["last_active", "a", "b"]]}
		)

		self.assertIsNone(audit_trail._delta(data, "User"))

	def test_malformed_json_is_none_not_an_exception(self):
		self.assertIsNone(audit_trail._delta("{not json", "User"))
		self.assertIsNone(audit_trail._delta("", "User"))
		self.assertIsNone(audit_trail._delta(None, "User"))

	def test_a_list_payload_is_rejected(self):
		self.assertIsNone(audit_trail._delta(json.dumps([1, 2, 3]), "User"))


class TestDeltaChildTables(UnitTestCase):
	def _roles(self, added, removed):
		def rows(names):
			return [["roles", {"doctype": "Has Role", "role": name}] for name in names]

		return json.dumps({"added": rows(added), "removed": rows(removed)})

	def test_a_full_rewrite_that_cancels_is_dropped(self):
		"""One save rewrites every role row. Netting to nothing means nothing happened."""
		data = self._roles(["Employee", "Stock User"], ["Employee", "Stock User"])

		self.assertIsNone(audit_trail._delta(data, "User"))

	def test_only_the_real_delta_survives(self):
		data = self._roles(
			["Employee", "Stock User", "Expense Approver"], ["Employee", "Stock User"]
		)

		delta = audit_trail._delta(data, "User")

		self.assertEqual(delta["roles_gained"], ["Expense Approver"])
		self.assertEqual(delta["roles_lost"], [])

	def test_a_loss_is_reported(self):
		data = self._roles(["Employee"], ["Employee", "Stock User"])

		delta = audit_trail._delta(data, "User")

		self.assertEqual(delta["roles_gained"], [])
		self.assertEqual(delta["roles_lost"], ["Stock User"])

	def test_blocked_modules_are_tracked_separately_from_roles(self):
		data = json.dumps(
			{
				"added": [["block_modules", {"module": "Selling"}]],
				"removed": [["block_modules", {"module": "Buying"}]],
			}
		)

		delta = audit_trail._delta(data, "User")

		self.assertEqual(delta["modules_blocked"], ["Selling"])
		self.assertEqual(delta["modules_unblocked"], ["Buying"])

	def test_v16_child_profile_change_reads_like_the_v15_scalar(self):
		"""439 rows use the v15 shape and 52 the v16 one. Both must render alike."""
		data = json.dumps(
			{
				"added": [["role_profiles", {"role_profile": "Agriculture Supervisor"}]],
				"removed": [["role_profiles", {"role_profile": "Clerk"}]],
			}
		)

		delta = audit_trail._delta(data, "User")

		self.assertEqual(delta["profile_before"], "Clerk")
		self.assertEqual(delta["profile_after"], "Agriculture Supervisor")

	def test_a_payload_missing_its_value_key_is_skipped_not_fatal(self):
		data = json.dumps({"added": [["roles", {"doctype": "Has Role"}]]})

		self.assertIsNone(audit_trail._delta(data, "User"))

	def test_uninteresting_child_tables_are_ignored(self):
		data = json.dumps({"added": [["user_emails", {"email_id": "x@y.z"}]]})

		self.assertIsNone(audit_trail._delta(data, "User"))

	def test_row_changed_inside_a_child_row_is_reported(self):
		data = json.dumps({"row_changed": [["roles", 1, "abc123", [["role", "Old", "New"]]]]})

		delta = audit_trail._delta(data, "User")

		self.assertIn(("roles.role", "Old", "New"), delta["fields"])


class TestTrailEndpoint(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")

	def test_it_returns_the_reporting_envelope(self):
		out = audit_trail.trail(page_size=5)

		for key in (
			"rows",
			"page",
			"page_size",
			"has_more",
			"scanned",
			"surfaced",
			"unparsed",
			"attribution",
			"limits",
		):
			self.assertIn(key, out)
		self.assertEqual(out["attribution"], "heuristic")

	def test_scanned_is_at_least_surfaced(self):
		"""Most version rows drop. A page of few rows from many scanned is correct."""
		out = audit_trail.trail(page_size=5)

		self.assertGreaterEqual(out["scanned"], out["surfaced"])
		self.assertEqual(out["surfaced"], len(out["rows"]))

	def test_page_size_is_clamped(self):
		out = audit_trail.trail(page_size=99999)

		self.assertEqual(out["page_size"], audit_trail.MAX_PAGE_SIZE)

	def test_an_untargeted_range_wider_than_the_cap_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			audit_trail.trail(start="2025-10-08", end="2026-08-22")

	def test_a_wide_range_is_allowed_when_targeted(self):
		out = audit_trail.trail(target="Administrator", start="2025-10-08", end="2026-08-22")

		self.assertIn("rows", out)

	def test_limits_are_always_declared(self):
		out = audit_trail.trail(page_size=1)

		self.assertEqual(out["limits"]["history_floor"], audit_trail.HISTORY_FLOOR)
		self.assertIn("Custom DocPerm", " ".join(out["limits"]["uncovered"]))

	def test_a_non_privileged_caller_is_refused(self):
		ensure_user("_ra_trail_nobody@example.com")
		frappe.set_user("_ra_trail_nobody@example.com")
		try:
			with self.assertRaises(frappe.PermissionError):
				audit_trail.trail()
		finally:
			frappe.set_user("Administrator")


class TestAttribution(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")

	def test_an_unmatched_human_change_is_external(self):
		rows = audit_trail._attribute(
			[
				{
					"document": "_ra_attr_nobody@example.com",
					"when": frappe.utils.now_datetime(),
					"updater_reference": None,
				}
			]
		)

		self.assertEqual(rows[0]["source"], "external")

	def test_a_change_matching_an_assignment_log_is_ours(self):
		from role_advisor import audit

		target = ensure_user("_ra_attr_target@example.com")
		name = audit.log_assignment(
			target,
			{"profiles": [], "module_profile": None, "roles": set()},
			{"profiles": ["X"], "module_profile": None, "roles": set()},
			audit.TRIGGER_MANUAL,
		)
		when = frappe.db.get_value("Access Assignment Log", name, "creation")

		rows = audit_trail._attribute(
			[{"document": target, "when": when, "updater_reference": None}]
		)

		self.assertEqual(rows[0]["source"], "role_advisor")
		self.assertEqual(rows[0]["assignment_log"], name)
		self.assertEqual(rows[0]["trigger"], audit.TRIGGER_MANUAL)

	def test_a_code_driven_change_is_system(self):
		rows = audit_trail._attribute(
			[
				{
					"document": "_ra_attr_nobody@example.com",
					"when": frappe.utils.now_datetime(),
					"updater_reference": {"doctype": "Patch Log", "label": "some.patch"},
				}
			]
		)

		self.assertEqual(rows[0]["source"], "system")

	def test_a_change_outside_the_window_is_not_claimed(self):
		from role_advisor import audit

		target = ensure_user("_ra_attr_far@example.com")
		audit.log_assignment(
			target,
			{"profiles": [], "module_profile": None, "roles": set()},
			{"profiles": ["X"], "module_profile": None, "roles": set()},
			audit.TRIGGER_MANUAL,
		)
		long_ago = frappe.utils.add_to_date(frappe.utils.now_datetime(), hours=-6)

		rows = audit_trail._attribute(
			[{"document": target, "when": long_ago, "updater_reference": None}]
		)

		self.assertEqual(rows[0]["source"], "external")


class TestEventAndSummary(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")

	def test_event_returns_the_raw_blob_behind_a_row(self):
		name = frappe.db.get_value(
			"Version", {"ref_doctype": "User"}, "name", order_by="creation desc"
		)
		if not name:
			self.skipTest("no User versions on this site")

		out = audit_trail.event(name)

		self.assertEqual(out["version"], name)
		self.assertIn("raw", out)
		self.assertIsInstance(out["raw"], dict)

	def test_event_refuses_a_doctype_outside_the_access_set(self):
		name = frappe.db.get_value(
			"Version", {"ref_doctype": ("not in", audit_trail.ACCESS_DOCTYPES)}, "name"
		)
		if not name:
			self.skipTest("no non-access versions on this site")

		with self.assertRaises(frappe.PermissionError):
			audit_trail.event(name)

	def test_summary_groups_by_actor_and_doctype(self):
		out = audit_trail.summary()

		self.assertIn("by_actor", out)
		self.assertIn("by_doctype", out)
		self.assertIn("window", out)
		self.assertIsInstance(out["by_actor"], list)

	def test_summary_is_guarded(self):
		ensure_user("_ra_summary_nobody@example.com")
		frappe.set_user("_ra_summary_nobody@example.com")
		try:
			with self.assertRaises(frappe.PermissionError):
				audit_trail.summary()
		finally:
			frappe.set_user("Administrator")


class TestReconstruction(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")

	def test_today_reconstructs_to_current_state(self):
		target = ensure_user("_ra_asof_target@example.com")

		out = audit_trail.as_of(target, frappe.utils.nowdate())

		self.assertEqual(out["user"], target)
		self.assertEqual(set(out["state"]["roles"]), set(audit_trail._current_roles(target)))

	def test_a_gained_role_is_removed_walking_backwards(self):
		"""Replaying a gain backwards must take the role away again."""
		state = {"roles": {"Employee", "Expense Approver"}, "profiles": [], "module_profile": None}
		chain = [{"roles_gained": ["Expense Approver"], "roles_lost": [], "profile_before": None}]

		audit_trail._rewind(state, chain)

		self.assertNotIn("Expense Approver", state["roles"])
		self.assertIn("Employee", state["roles"])

	def test_a_lost_role_is_restored_walking_backwards(self):
		state = {"roles": {"Employee"}, "profiles": [], "module_profile": None}
		chain = [{"roles_gained": [], "roles_lost": ["Stock User"], "profile_before": None}]

		audit_trail._rewind(state, chain)

		self.assertIn("Stock User", state["roles"])

	def test_the_profile_is_rolled_back_to_before(self):
		state = {"roles": set(), "profiles": ["Agriculture Supervisor"], "module_profile": None}
		chain = [{"roles_gained": [], "roles_lost": [], "profile_before": "Clerk"}]

		audit_trail._rewind(state, chain)

		self.assertEqual(state["profiles"], ["Clerk"])

	def test_a_date_before_the_floor_is_flagged_not_extrapolated(self):
		target = ensure_user("_ra_asof_floor@example.com")

		out = audit_trail.as_of(target, "2024-01-01")

		self.assertFalse(out["exact"])
		self.assertIn("floor", " ".join(out["limits"]["notes"]).lower())

	def test_reconstruction_is_guarded(self):
		ensure_user("_ra_asof_nobody@example.com")
		frappe.set_user("_ra_asof_nobody@example.com")
		try:
			with self.assertRaises(frappe.PermissionError):
				audit_trail.as_of("Administrator", frappe.utils.nowdate())
		finally:
			frappe.set_user("Administrator")

	def test_a_truncated_walk_says_so_rather_than_implying_completeness(self):
		"""The busiest user has 17,745 versions. A bounded walk must admit it stopped."""
		busiest = frappe.db.sql(
			"""
			select docname, count(*) c from `tabVersion`
			where ref_doctype='User' group by docname order by c desc limit 1
			""",
			as_dict=True,
		)
		if not busiest or busiest[0]["c"] <= audit_trail.MAX_REWIND_VERSIONS:
			self.skipTest("no user busy enough to truncate the walk")

		out = audit_trail.as_of(busiest[0]["docname"], audit_trail.HISTORY_FLOOR)

		self.assertFalse(out["exact"])
		self.assertLessEqual(out["scanned"], audit_trail.MAX_REWIND_VERSIONS)
		self.assertIn("stopped after reading", " ".join(out["limits"]["notes"]).lower())
