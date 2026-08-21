# Copyright (c) 2026, ghost-mann and contributors
# For license information, please see license.txt

import frappe
from frappe.tests import IntegrationTestCase

from role_advisor import delegation, permissions
from role_advisor.tests.test_delegation import (
	ADMIN,
	IN_SCOPE,
	OUT_OF_SCOPE,
	UNLINKED,
	build_fixture,
)


class TestUserPermissionHooks(IntegrationTestCase):
	def setUp(self):
		# Reuse the delegation fixture so the two suites cannot drift apart.
		build_fixture(self)

	def tearDown(self):
		delegation.clear_cache()

	def test_a_non_delegate_is_unrestricted(self):
		"""Opt-in enforcement: no record means stock behaviour."""
		self.assertEqual(permissions.user_query_conditions(OUT_OF_SCOPE), "")

	def test_administrator_is_never_restricted(self):
		self.assertEqual(permissions.user_query_conditions("Administrator"), "")

	def test_a_delegate_gets_a_scoping_condition(self):
		condition = permissions.user_query_conditions(ADMIN)

		self.assertIn("tabUser", condition)
		self.assertIn("tabEmployee", condition)

	def test_the_condition_selects_only_in_scope_users(self):
		condition = permissions.user_query_conditions(ADMIN)

		names = frappe.db.sql_list(f"select name from `tabUser` where {condition}")

		self.assertIn(IN_SCOPE, names)
		self.assertNotIn(OUT_OF_SCOPE, names)
		self.assertNotIn(UNLINKED, names)

	def test_a_delegate_can_always_see_themselves(self):
		"""Otherwise their own record vanishes and the desk breaks."""
		condition = permissions.user_query_conditions(ADMIN)

		names = frappe.db.sql_list(f"select name from `tabUser` where {condition}")

		self.assertIn(ADMIN, names)

	def test_has_permission_allows_an_in_scope_document(self):
		doc = frappe.get_doc("User", IN_SCOPE)

		self.assertTrue(permissions.user_has_permission(doc, "read", ADMIN))

	def test_has_permission_denies_an_out_of_scope_document(self):
		"""List filtering alone would not stop a typed URL."""
		doc = frappe.get_doc("User", OUT_OF_SCOPE)

		self.assertFalse(permissions.user_has_permission(doc, "read", ADMIN))

	def test_has_permission_does_not_restrict_a_non_delegate(self):
		doc = frappe.get_doc("User", OUT_OF_SCOPE)

		self.assertTrue(permissions.user_has_permission(doc, "read", "Administrator"))
