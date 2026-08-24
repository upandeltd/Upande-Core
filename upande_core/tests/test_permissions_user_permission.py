# Copyright (c) 2026, ghost-mann and contributors
# For license information, please see license.txt

import frappe
from frappe.tests import IntegrationTestCase

from upande_core import delegation, permissions
from upande_core.tests.fixtures import ensure_user
from upande_core.tests.test_delegation import (
	ADMIN,
	IN_SCOPE,
	OUT_OF_SCOPE,
	build_fixture,
)

OTHER_DELEGATE = "_ra_other_delegate@example.com"


class TestUserPermissionDoctypeHooks(IntegrationTestCase):
	def setUp(self):
		build_fixture(self)
		self.company = self.companies[0]

		for user in (ADMIN, IN_SCOPE, OUT_OF_SCOPE):
			for name in frappe.get_all(
				"User Permission", filters={"user": user}, pluck="name"
			):
				frappe.delete_doc("User Permission", name, force=True)

	def tearDown(self):
		delegation.clear_cache()

	def _permission_for(self, user):
		return frappe.get_doc(
			{
				"doctype": "User Permission",
				"user": user,
				"allow": "Company",
				"for_value": self.company,
			}
		).insert(ignore_permissions=True)

	def test_a_delegate_cannot_touch_their_own_row(self):
		"""The escalation path: deleting your own scoping row unlocks the cage."""
		own = self._permission_for(ADMIN)

		self.assertFalse(permissions.user_permission_has_permission(own, "write", ADMIN))
		self.assertFalse(permissions.user_permission_has_permission(own, "delete", ADMIN))

	def test_a_delegate_cannot_even_read_their_own_row(self):
		"""Reading is harmless, but allowing it invites a UI that offers delete."""
		own = self._permission_for(ADMIN)

		self.assertFalse(permissions.user_permission_has_permission(own, "read", ADMIN))

	def test_a_delegate_may_manage_an_in_scope_users_row(self):
		row = self._permission_for(IN_SCOPE)

		self.assertTrue(permissions.user_permission_has_permission(row, "write", ADMIN))

	def test_a_delegate_may_not_manage_an_out_of_scope_users_row(self):
		row = self._permission_for(OUT_OF_SCOPE)

		self.assertFalse(permissions.user_permission_has_permission(row, "write", ADMIN))

	def test_the_query_condition_excludes_the_delegates_own_rows(self):
		self._permission_for(ADMIN)
		self._permission_for(IN_SCOPE)

		condition = permissions.user_permission_query_conditions(ADMIN)
		users = frappe.db.sql_list(
			f"select user from `tabUser Permission` where {condition}"
		)

		self.assertIn(IN_SCOPE, users)
		self.assertNotIn(ADMIN, users)

	def test_a_non_delegate_is_unrestricted(self):
		self.assertEqual(
			permissions.user_permission_query_conditions("Administrator"), ""
		)
		row = self._permission_for(ADMIN)
		self.assertTrue(
			permissions.user_permission_has_permission(row, "delete", "Administrator")
		)

	def test_a_delegate_may_read_their_own_admin_record(self):
		record = frappe.get_doc("Delegated User Admin", ADMIN)

		self.assertTrue(permissions.delegated_admin_has_permission(record, "read", ADMIN))

	def test_a_delegate_may_not_read_another_delegates_record(self):
		ensure_user(OTHER_DELEGATE)
		if not frappe.db.exists("Delegated User Admin", OTHER_DELEGATE):
			frappe.get_doc(
				{
					"doctype": "Delegated User Admin",
					"user": OTHER_DELEGATE,
					"enabled": 1,
					"companies": [{"company": self.company}],
				}
			).insert(ignore_permissions=True)

		record = frappe.get_doc("Delegated User Admin", OTHER_DELEGATE)

		self.assertFalse(
			permissions.delegated_admin_has_permission(record, "read", ADMIN)
		)

	def test_a_delegate_may_not_write_their_own_admin_record(self):
		"""Otherwise they widen their own allowlist."""
		record = frappe.get_doc("Delegated User Admin", ADMIN)

		self.assertFalse(permissions.delegated_admin_has_permission(record, "write", ADMIN))
