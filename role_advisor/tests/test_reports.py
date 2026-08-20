# Copyright (c) 2026, Upande and contributors
# For license information, please see license.txt

import frappe
from frappe.tests import IntegrationTestCase

from role_advisor import capability
from role_advisor.role_advisor.report.designation_gap import designation_gap
from role_advisor.role_advisor.report.module_exposure import module_exposure
from role_advisor.role_advisor.report.role_drift import role_drift
from role_advisor.role_advisor.report.role_profile_overgrant import role_profile_overgrant
from role_advisor.role_advisor.report.system_manager_audit import system_manager_audit
from role_advisor.tests.fixtures import ensure_profile, ensure_role, grant

UNSAFE_ROLE = "_RA Overgrant Role"
UNSAFE_PROFILE = "_RA Overgrant Profile"


class TestDesignationGapReport(IntegrationTestCase):
	def test_execute_returns_columns_and_rows(self):
		columns, data = designation_gap.execute()

		fieldnames = {column["fieldname"] for column in columns}
		for expected in (
			"user", "designation", "company", "proposed_role_profile",
			"confidence", "peers", "evidence",
		):
			self.assertIn(expected, fieldnames)
		self.assertIsInstance(data, list)

	def test_only_unprofiled_enabled_system_users_appear(self):
		_columns, data = designation_gap.execute()

		for row in data:
			self.assertEqual(frappe.db.get_value("User", row["user"], "enabled"), 1)
			self.assertEqual(
				frappe.db.get_value("User", row["user"], "user_type"), "System User"
			)
			self.assertFalse(
				frappe.db.exists("User Role Profile", {"parent": row["user"]}),
				f"{row['user']} already holds a profile and should not be in the gap",
			)

	def test_a_user_with_no_designation_is_reported_with_no_proposal(self):
		"""Users with no Employee link must be visible but unproposed."""
		_columns, data = designation_gap.execute()

		for row in data:
			if not row["designation"]:
				self.assertIsNone(row["proposed_role_profile"])
				self.assertEqual(row["confidence"], "None")

	def test_the_report_writes_nothing(self):
		before = frappe.db.count("User Role Profile")

		designation_gap.execute()

		self.assertEqual(frappe.db.count("User Role Profile"), before)


class TestModuleExposureReport(IntegrationTestCase):
	def test_columns_cover_the_status_story(self):
		columns, _data = module_exposure.execute()
		fieldnames = {column["fieldname"] for column in columns}

		for expected in ("user", "module_profile", "blocked_now", "status"):
			self.assertIn(expected, fieldnames)

	def test_users_with_no_blocks_are_reported_as_unrestricted(self):
		rows = module_exposure.exposure_rows()

		unrestricted = [r for r in rows if r["status"] == module_exposure.STATUS_UNRESTRICTED]
		self.assertTrue(unrestricted, "the site has unrestricted users")
		for row in unrestricted:
			self.assertEqual(row["blocked_now"], 0)

	def test_hand_blocked_users_without_a_profile_are_flagged(self):
		rows = module_exposure.exposure_rows()

		for row in rows:
			if row["status"] == module_exposure.STATUS_HAND_SET:
				self.assertGreater(row["blocked_now"], 0)
				self.assertFalse(row["module_profile"])

	def test_the_report_writes_nothing(self):
		before = frappe.db.count("Block Module")

		module_exposure.execute()

		self.assertEqual(frappe.db.count("Block Module"), before)


class TestRoleDriftReport(IntegrationTestCase):
	def test_columns_name_the_role_and_its_healer(self):
		columns, _data = role_drift.execute()
		fieldnames = {column["fieldname"] for column in columns}

		for expected in ("user", "role", "self_healing", "note"):
			self.assertIn(expected, fieldnames)

	def test_approver_roles_are_marked_self_healing(self):
		"""HRMS re-adds Leave/Expense Approver after v16 prunes them."""
		for row in role_drift.drift_rows():
			if row["role"] in ("Leave Approver", "Expense Approver"):
				self.assertTrue(row["self_healing"])

	def test_every_row_belongs_to_a_user_holding_a_profile(self):
		"""Drift is only meaningful for users whose roles get pruned."""
		for row in role_drift.drift_rows():
			self.assertTrue(
				frappe.db.exists("User Role Profile", {"parent": row["user"]})
			)


class TestSystemManagerAudit(IntegrationTestCase):
	def test_every_row_actually_holds_system_manager(self):
		rows = system_manager_audit.audit_rows()

		self.assertTrue(rows, "the site has System Managers")
		for row in rows:
			self.assertTrue(
				frappe.db.exists(
					"Has Role",
					{"parent": row["user"], "parenttype": "User", "role": "System Manager"},
				)
			)

	def test_columns_expose_the_accountability_signals(self):
		columns, _data = system_manager_audit.execute()
		fieldnames = {column["fieldname"] for column in columns}

		for expected in ("user", "last_active", "role_profile", "has_employee", "flags"):
			self.assertIn(expected, fieldnames)

	def test_the_report_revokes_nothing(self):
		before = frappe.db.count("Has Role", {"role": "System Manager"})

		system_manager_audit.execute()

		self.assertEqual(frappe.db.count("Has Role", {"role": "System Manager"}), before)


class TestRoleProfileOvergrant(IntegrationTestCase):
	def setUp(self):
		grant(ensure_role(UNSAFE_ROLE), "Role Profile", "read", "write", "delete")
		ensure_profile(UNSAFE_PROFILE, UNSAFE_ROLE)
		capability.clear_capability_index()

	def tearDown(self):
		capability.clear_capability_index()

	def test_a_profile_touching_privileged_doctypes_is_flagged(self):
		rows = {r["role_profile"]: r for r in role_profile_overgrant.overgrant_rows()}

		self.assertIn(UNSAFE_PROFILE, rows)
		self.assertTrue(rows[UNSAFE_PROFILE]["privileged"])
		self.assertIn("Role Profile", rows[UNSAFE_PROFILE]["privileged_grants"])

	def test_every_profile_is_reported_with_its_size(self):
		rows = role_profile_overgrant.overgrant_rows()

		self.assertEqual(len(rows), frappe.db.count("Role Profile"))
		for row in rows:
			self.assertGreaterEqual(row["doctype_count"], 0)
			self.assertGreaterEqual(row["perm_count"], 0)

	def test_rows_are_ordered_widest_first(self):
		counts = [row["perm_count"] for row in role_profile_overgrant.overgrant_rows()]

		self.assertEqual(counts, sorted(counts, reverse=True))

	def test_broad_delete_is_counted(self):
		rows = {r["role_profile"]: r for r in role_profile_overgrant.overgrant_rows()}

		self.assertGreaterEqual(rows[UNSAFE_PROFILE]["delete_count"], 1)
