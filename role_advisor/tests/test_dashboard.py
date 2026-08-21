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

	def test_the_page_is_installed_with_both_admin_roles(self):
		self.assertTrue(frappe.db.exists("Page", "access-dashboard"))

		roles = frappe.get_all(
			"Has Role",
			filters={"parent": "access-dashboard", "parenttype": "Page"},
			pluck="role",
		)
		self.assertIn("System Manager", roles)
		self.assertIn("User Manager", roles)
