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
