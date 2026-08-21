# Copyright (c) 2026, ghost-mann and contributors
# For license information, please see license.txt

import frappe
from frappe.tests import IntegrationTestCase

from role_advisor import dashboard, delegation
from role_advisor.tests.test_delegation import ADMIN, IN_SCOPE, build_fixture


class TestDashboard(IntegrationTestCase):
	def setUp(self):
		build_fixture(self)

	def tearDown(self):
		frappe.set_user("Administrator")
		delegation.clear_cache()

	def test_summary_counts_match_the_database(self):
		summary = dashboard.summary()

		self.assertEqual(summary["users"], frappe.db.count("User"))
		self.assertEqual(summary["enabled"], frappe.db.count("User", {"enabled": 1}))
		self.assertEqual(summary["profiles"], frappe.db.count("Role Profile"))
		self.assertEqual(summary["map_rows"], frappe.db.count("Designation Access Map"))

	def test_coverage_is_derived_not_invented(self):
		summary = dashboard.summary()
		expected = round(summary["profiled"] / summary["enabled"] * 100, 1)

		self.assertEqual(summary["coverage"], expected)
		self.assertEqual(summary["gap"], summary["enabled"] - summary["profiled"])

	def test_a_system_manager_sees_the_whole_estate(self):
		"""A delegate record bounds what they may grant, not what they may see."""
		summary = dashboard.summary()

		self.assertFalse(summary["scoped"])
		self.assertEqual(summary["users"], frappe.db.count("User"))

	def test_a_delegate_sees_only_their_scope(self):
		frappe.set_user(ADMIN)
		delegation.clear_cache()

		summary = dashboard.summary()

		self.assertTrue(summary["scoped"])
		self.assertLess(summary["users"], frappe.db.count("User"))
		self.assertIn(self.companies[0], summary["scope_companies"])

	def test_a_non_administrator_is_refused(self):
		frappe.set_user(IN_SCOPE)

		with self.assertRaises(frappe.PermissionError):
			dashboard.summary()

	def test_module_exposure_covers_every_module_with_doctypes(self):
		rows = dashboard.module_exposure()
		modules = {row["module"] for row in rows}
		with_doctypes = {
			row["module"]
			for row in frappe.get_all("DocType", fields=["module"])
			if row["module"]
		}

		self.assertEqual(modules, with_doctypes)
		for row in rows:
			self.assertLessEqual(row["doctypes_granted"], row["doctypes_total"])
			self.assertIn(row["severity"], ("high", "moderate", "low", "clear"))

	def test_severity_follows_share_not_raw_count(self):
		"""So a small site and a large one read the same way."""
		for row in dashboard.module_exposure():
			if row["share"] >= 75:
				self.assertEqual(row["severity"], "high")
			elif row["share"] >= 40:
				self.assertEqual(row["severity"], "moderate")
			elif row["share"] > 0:
				self.assertEqual(row["severity"], "low")
			else:
				self.assertEqual(row["severity"], "clear")

	def test_user_table_includes_disabled_users(self):
		rows = dashboard.user_table()

		self.assertEqual(len(rows), frappe.db.count("User"))
		self.assertIn(0, {row["enabled"] for row in rows})

	def test_findings_are_ordered_worst_first(self):
		order = {"high": 0, "moderate": 1, "low": 2}
		severities = [order[f["severity"]] for f in dashboard.findings()]

		self.assertEqual(severities, sorted(severities))

	def test_profile_leaderboard_flags_empty_and_privileged(self):
		rows = dashboard.profile_leaderboard(limit=500)

		self.assertEqual(len(rows), frappe.db.count("Role Profile"))
		for row in rows:
			self.assertIsInstance(row["privileged"], bool)
			self.assertEqual(row["empty"], row["doctypes"] == 0)

	def test_nothing_here_writes_to_the_site(self):
		before = (
			frappe.db.count("User"),
			frappe.db.count("Role Profile"),
			frappe.db.count("Access Assignment Log"),
		)

		dashboard.summary()
		dashboard.module_exposure()
		dashboard.user_table()
		dashboard.findings()
		dashboard.profile_leaderboard()
		dashboard.designation_coverage()
		dashboard.recent_assignments()

		self.assertEqual(
			before,
			(
				frappe.db.count("User"),
				frappe.db.count("Role Profile"),
				frappe.db.count("Access Assignment Log"),
			),
		)

	def test_user_detail_gathers_everything_a_desk_form_would_show(self):
		detail = dashboard.user_detail(IN_SCOPE)

		for key in ("user", "employee", "profiles", "roles", "grants", "permissions", "history"):
			self.assertIn(key, detail)
		self.assertEqual(detail["user"]["name"], IN_SCOPE)

	def test_user_detail_refuses_a_target_outside_a_delegate_scope(self):
		from role_advisor.tests.test_delegation import OUT_OF_SCOPE

		frappe.set_user(ADMIN)
		delegation.clear_cache()

		with self.assertRaises(frappe.PermissionError):
			dashboard.user_detail(OUT_OF_SCOPE)

	def test_profile_detail_reports_duplicates_and_the_matrix(self):
		profile = frappe.get_all("Role Profile", pluck="name", limit=1)[0]
		detail = dashboard.profile_detail(profile)

		self.assertEqual(detail["profile"], profile)
		self.assertEqual(len(detail["matrix"]), detail["doctypes"])
		self.assertIsInstance(detail["duplicate_of"], list)

	def test_module_detail_lists_the_profiles_that_reach_it(self):
		detail = dashboard.module_detail("Core")

		self.assertEqual(detail["module"], "Core")
		self.assertGreater(detail["doctypes_total"], 0)
		for row in detail["profiles"]:
			self.assertLessEqual(row["doctypes"], detail["doctypes_total"])

	def test_map_update_only_accepts_the_three_safe_fields(self):
		"""The dashboard must not become a document editor with no validation."""
		rows = dashboard.map_list()
		if not rows:
			self.skipTest("no map rows seeded")

		with self.assertRaises(frappe.ValidationError):
			dashboard.map_update(rows[0]["name"], "designation", "anything")

	def test_map_update_toggles_active(self):
		rows = dashboard.map_list()
		if not rows:
			self.skipTest("no map rows seeded")
		name = rows[0]["name"]
		before = frappe.db.get_value("Designation Access Map", name, "is_active")

		dashboard.map_update(name, "is_active", 0 if before else 1)
		self.assertNotEqual(
			frappe.db.get_value("Designation Access Map", name, "is_active"), before
		)
		dashboard.map_update(name, "is_active", before)

	def test_only_this_apps_reports_can_be_run(self):
		with self.assertRaises(frappe.ValidationError):
			dashboard.report("Permitted Documents For User")

	def test_a_report_returns_columns_and_rows(self):
		result = dashboard.report("Designation Gap")

		self.assertEqual(result["name"], "Designation Gap")
		self.assertTrue(result["columns"])
		self.assertIsInstance(result["rows"], list)

	def test_sweep_preview_writes_nothing(self):
		before = frappe.db.count("User Role Profile")

		preview = dashboard.sweep_preview()

		self.assertEqual(frappe.db.count("User Role Profile"), before)
		self.assertEqual(preview["total"], len(preview["ready"]) + len(preview["blocked"]))

	def test_sweep_and_policy_are_system_manager_only(self):
		frappe.set_user(ADMIN)
		delegation.clear_cache()

		for call in (
			lambda: dashboard.sweep_preview(),
			lambda: dashboard.sweep_apply(users=[IN_SCOPE]),
			lambda: dashboard.settings_write({"min_peers_high_confidence": 9}),
			lambda: dashboard.delegate_save(user=IN_SCOPE),
		):
			with self.assertRaises(frappe.PermissionError):
				call()

	def test_delegate_save_also_grants_the_role(self):
		"""A record with no role silently does nothing, so saving does both."""
		target = "_ra_new_delegate@example.com"
		if not frappe.db.exists("User", target):
			frappe.get_doc(
				{"doctype": "User", "email": target, "first_name": "New", "send_welcome_email": 0}
			).insert(ignore_permissions=True)

		result = dashboard.delegate_save(
			user=target, companies=[self.companies[0]], profiles=[]
		)

		self.assertEqual(result["user"], target)
		self.assertTrue(
			frappe.db.exists(
				"Has Role",
				{"parent": target, "parenttype": "User", "role": result["granted_role"]},
			)
		)
		frappe.delete_doc("Delegated User Admin", target, force=True)

	def test_settings_write_ignores_fields_it_does_not_expose(self):
		before = dashboard.settings_read()["delegate_role"]

		dashboard.settings_write({"delegate_role": "System Manager"})

		self.assertEqual(dashboard.settings_read()["delegate_role"], before)

	def test_the_page_is_installed_with_both_admin_roles(self):
		self.assertTrue(frappe.db.exists("Page", "access-dashboard"))

		roles = frappe.get_all(
			"Has Role",
			filters={"parent": "access-dashboard", "parenttype": "Page"},
			pluck="role",
		)
		self.assertIn("System Manager", roles)
		self.assertIn("User Manager", roles)
