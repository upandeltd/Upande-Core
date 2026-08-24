# Copyright (c) 2026, ghost-mann and contributors
# For license information, please see license.txt

import frappe
from frappe.tests import IntegrationTestCase

from upande_core import audit
from upande_core.tests.fixtures import ensure_user

TARGET = "_ra_audit_target@example.com"


class TestAuditLog(IntegrationTestCase):
	def setUp(self):
		ensure_user(TARGET)

	def test_snapshot_reports_current_state(self):
		snap = audit.snapshot(TARGET)

		self.assertEqual(snap["profiles"], [])
		self.assertIsNone(snap["module_profile"])
		self.assertIsInstance(snap["roles"], set)

	def test_log_records_the_delta_in_both_directions(self):
		before = {"profiles": ["A"], "module_profile": None, "roles": {"X", "Y"}}
		after = {"profiles": ["B"], "module_profile": "MP", "roles": {"Y", "Z"}}

		name = audit.log_assignment(TARGET, before, after, audit.TRIGGER_MANUAL)
		row = frappe.get_doc("Access Assignment Log", name)

		self.assertEqual(row.target_user, TARGET)
		self.assertEqual(row.profiles_before, "A")
		self.assertEqual(row.profiles_after, "B")
		self.assertEqual(row.module_profile_after, "MP")
		self.assertEqual(row.roles_gained, "Z")
		self.assertEqual(row.roles_lost, "X")
		self.assertEqual(row.trigger, audit.TRIGGER_MANUAL)
		self.assertEqual(row.outcome, audit.OUTCOME_APPLIED)
		self.assertEqual(row.actor, frappe.session.user)

	def test_a_no_op_is_still_logged(self):
		"""The audit trail must have no holes, so nothing is skipped."""
		state = {"profiles": ["A"], "module_profile": None, "roles": {"X"}}

		name = audit.log_assignment(
			TARGET, state, state, audit.TRIGGER_SWEEP, outcome=audit.OUTCOME_NO_CHANGE
		)
		row = frappe.get_doc("Access Assignment Log", name)

		self.assertEqual(row.outcome, audit.OUTCOME_NO_CHANGE)
		self.assertFalse(row.roles_gained)
		self.assertFalse(row.roles_lost)

	def test_a_log_row_cannot_be_edited(self):
		name = audit.log_assignment(
			TARGET,
			{"profiles": [], "module_profile": None, "roles": set()},
			{"profiles": ["A"], "module_profile": None, "roles": set()},
			audit.TRIGGER_MANUAL,
		)

		row = frappe.get_doc("Access Assignment Log", name)
		row.outcome = audit.OUTCOME_REFUSED

		with self.assertRaises(frappe.ValidationError):
			row.save(ignore_permissions=True)

	def test_no_role_can_write_the_log(self):
		"""Immutability is belt and braces: no write perm, plus a validate guard."""
		perms = frappe.get_all(
			"DocPerm",
			filters={"parent": "Access Assignment Log"},
			fields=["role", "write", "delete"],
		)

		self.assertTrue(perms)
		for perm in perms:
			self.assertFalse(perm.write, f"{perm.role} has write")
			self.assertFalse(perm.delete, f"{perm.role} has delete")
