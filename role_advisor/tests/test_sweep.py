# Copyright (c) 2026, Upande and contributors
# For license information, please see license.txt

import frappe
from frappe.tests import IntegrationTestCase

from role_advisor import capability, sweep
from role_advisor.tests.fixtures import (
	clear_map,
	ensure_designation,
	ensure_employee,
)
from role_advisor.tests.test_delegation import (
	ALLOWED_PROFILE,
	IN_SCOPE,
	SAFE_ROLE,
	build_fixture,
)

DESIGNATION = "_RA Sweep Designation"


class TestSweep(IntegrationTestCase):
	def setUp(self):
		build_fixture(self)

		ensure_designation(DESIGNATION)
		clear_map(DESIGNATION)
		ensure_employee(IN_SCOPE, self.companies[0], designation=DESIGNATION)

		# Start from no profile so the sweep has something to do - but keep a
		# direct role. Clearing profiles prunes roles, and User.set_system_user
		# then demotes a role-less user to Website User, which would drop them
		# out of unprofiled_users() entirely. The real gap users on this site
		# hold direct roles without a profile, so this matches them.
		target = frappe.get_doc("User", IN_SCOPE)
		capability.set_user_role_profiles(target, [])
		target.append("roles", {"role": SAFE_ROLE})
		target.save(ignore_permissions=True)

		self.map_row = frappe.get_doc(
			{
				"doctype": "Designation Access Map",
				"designation": DESIGNATION,
				"for_company": self.companies[0],
				"role_profile": ALLOWED_PROFILE,
				"is_active": 1,
			}
		).insert(ignore_permissions=True)

	def tearDown(self):
		frappe.set_user("Administrator")
		capability.clear_capability_index()

	def _row_for(self, rows, user):
		return next(r for r in rows if r["user"] == user)

	def test_dry_run_writes_nothing(self):
		before = frappe.db.count("User Role Profile")

		rows = sweep.dry_run()

		self.assertEqual(frappe.db.count("User Role Profile"), before)
		self.assertTrue(any(r["user"] == IN_SCOPE for r in rows))

	def test_dry_run_proposes_the_mapped_profile(self):
		row = self._row_for(sweep.dry_run(), IN_SCOPE)

		self.assertEqual(row["role_profile"], ALLOWED_PROFILE)
		self.assertIsNone(row["blocked_reason"])

	def test_an_inactive_map_row_blocks_the_sweep_for_that_user(self):
		self.map_row.is_active = 0
		self.map_row.save(ignore_permissions=True)

		row = self._row_for(sweep.dry_run(), IN_SCOPE)

		self.assertIsNotNone(row["blocked_reason"])
		self.assertIn("not active", row["blocked_reason"])

	def test_apply_only_touches_the_named_users(self):
		result = sweep.apply(users=[IN_SCOPE])

		self.assertEqual(result["applied"], 1)
		self.assertEqual(capability.get_user_role_profiles(IN_SCOPE), [ALLOWED_PROFILE])

	def test_apply_is_idempotent(self):
		sweep.apply(users=[IN_SCOPE])
		second = sweep.apply(users=[IN_SCOPE])

		self.assertEqual(second["applied"], 0)
		self.assertEqual(second["no_change"], 1)
		self.assertEqual(capability.get_user_role_profiles(IN_SCOPE), [ALLOWED_PROFILE])

	def test_apply_refuses_a_blocked_row(self):
		self.map_row.is_active = 0
		self.map_row.save(ignore_permissions=True)

		result = sweep.apply(users=[IN_SCOPE])

		self.assertEqual(result["applied"], 0)
		self.assertEqual(result["skipped"], 1)
		self.assertEqual(capability.get_user_role_profiles(IN_SCOPE), [])

	def test_apply_logs_every_user_it_considered(self):
		"""One log row per candidate, asserted on the returned names.

		A cumulative DB count would not work: `apply` commits, which defeats
		the per-class rollback, so sibling tests' rows are still present.
		"""
		result = sweep.apply(users=[IN_SCOPE])

		self.assertEqual(len(result["logs"]), 1)
		row = frappe.get_doc("Access Assignment Log", result["logs"][0])
		self.assertEqual(row.target_user, IN_SCOPE)
		self.assertEqual(row.trigger, "Bulk Sweep")
		self.assertEqual(row.profiles_after, ALLOWED_PROFILE)

	def test_a_delegate_cannot_run_the_sweep(self):
		"""The sweep is System-Manager-only; delegates assign one at a time."""
		frappe.set_user(IN_SCOPE)

		with self.assertRaises(frappe.PermissionError):
			sweep.apply(users=[IN_SCOPE])
