# Copyright (c) 2026, ghost-mann and contributors
# For license information, please see license.txt

import frappe
from frappe.tests import IntegrationTestCase

from role_advisor import api, capability, delegation
from role_advisor.tests.test_delegation import (
	ADMIN,
	ALLOWED_PROFILE,
	IN_SCOPE,
	OTHER_PROFILE,
	OUT_OF_SCOPE,
	build_fixture,
)


class TestDelegateAPI(IntegrationTestCase):
	def setUp(self):
		build_fixture(self)
		# Reset the target so replace-vs-append is observable.
		target = frappe.get_doc("User", IN_SCOPE)
		capability.set_user_role_profiles(target, [])
		target.save(ignore_permissions=True)
		frappe.set_user(ADMIN)

	def tearDown(self):
		frappe.set_user("Administrator")
		delegation.clear_cache()
		capability.clear_capability_index()

	def test_get_manageable_users_returns_only_in_scope_users(self):
		names = [row["name"] for row in api.get_manageable_users(limit=500)]

		self.assertIn(IN_SCOPE, names)
		self.assertNotIn(OUT_OF_SCOPE, names)

	def test_get_grantable_profiles_returns_the_allowlist_with_a_summary(self):
		rows = api.get_grantable_profiles()

		self.assertEqual([row["role_profile"] for row in rows], [ALLOWED_PROFILE])
		self.assertIn("doctype_count", rows[0])
		self.assertIn("perm_count", rows[0])

	def test_preview_reports_the_delta_without_writing(self):
		preview = api.preview_assignment(IN_SCOPE, ALLOWED_PROFILE)

		self.assertEqual(preview["profiles_before"], [])
		self.assertEqual(preview["profiles_after"], [ALLOWED_PROFILE])
		self.assertIn("roles_gained", preview)
		self.assertEqual(capability.get_user_role_profiles(IN_SCOPE), [])

	def test_assign_access_writes_the_profile(self):
		api.assign_access(IN_SCOPE, ALLOWED_PROFILE)

		self.assertEqual(capability.get_user_role_profiles(IN_SCOPE), [ALLOWED_PROFILE])

	def test_assign_access_replaces_rather_than_appends(self):
		"""Appending would keep every grant the new profile was chosen to avoid."""
		api.assign_access(IN_SCOPE, ALLOWED_PROFILE)
		api.assign_access(IN_SCOPE, ALLOWED_PROFILE)

		self.assertEqual(capability.get_user_role_profiles(IN_SCOPE), [ALLOWED_PROFILE])

	def test_assign_access_logs_the_change(self):
		api.assign_access(IN_SCOPE, ALLOWED_PROFILE)

		logs = frappe.get_all(
			"Access Assignment Log",
			filters={"target_user": IN_SCOPE},
			fields=["actor", "trigger", "outcome", "profiles_after"],
			order_by="creation desc",
			limit=1,
		)

		self.assertTrue(logs)
		self.assertEqual(logs[0].actor, ADMIN)
		self.assertEqual(logs[0].profiles_after, ALLOWED_PROFILE)

	def test_assign_access_refuses_an_out_of_scope_target(self):
		with self.assertRaises(frappe.PermissionError):
			api.assign_access(OUT_OF_SCOPE, ALLOWED_PROFILE)

	def test_assign_access_refuses_a_profile_off_the_allowlist(self):
		with self.assertRaises(frappe.PermissionError):
			api.assign_access(IN_SCOPE, OTHER_PROFILE)

	def test_assign_access_never_changes_user_type(self):
		"""Website User -> System User is a privilege boundary."""
		before = frappe.db.get_value("User", IN_SCOPE, "user_type")

		api.assign_access(IN_SCOPE, ALLOWED_PROFILE)

		self.assertEqual(frappe.db.get_value("User", IN_SCOPE, "user_type"), before)

	def test_a_non_delegate_cannot_call_the_api(self):
		frappe.set_user(OUT_OF_SCOPE)

		with self.assertRaises(frappe.PermissionError):
			api.assign_access(IN_SCOPE, ALLOWED_PROFILE)

	def test_the_link_query_returns_only_users_in_scope(self):
		"""The picker must not suggest anyone assign_access would then refuse."""
		rows = api.manageable_user_query(
			doctype="User", txt="", searchfield="name", start=0, page_len=500, filters=None
		)
		names = [row[0] for row in rows]

		self.assertIn(IN_SCOPE, names)
		self.assertNotIn(OUT_OF_SCOPE, names)

	def test_the_link_query_matches_on_login_and_on_name(self):
		by_email = api.manageable_user_query(
			doctype="User", txt=IN_SCOPE.split("@")[0], searchfield="name",
			start=0, page_len=20, filters=None,
		)

		self.assertIn(IN_SCOPE, [row[0] for row in by_email])

	def test_the_link_query_refuses_a_non_delegate(self):
		frappe.set_user(OUT_OF_SCOPE)

		with self.assertRaises(frappe.PermissionError):
			api.manageable_user_query(
				doctype="User", txt="", searchfield="name", start=0, page_len=20, filters=None
			)

	def test_search_matches_an_email_not_just_a_display_name(self):
		"""A full_name-only filter silently returns nothing for an address."""
		rows = api.get_manageable_users(search=IN_SCOPE, limit=5)

		self.assertIn(IN_SCOPE, [row["name"] for row in rows])

	def test_assign_access_refuses_administrator_as_a_target(self):
		with self.assertRaises(frappe.PermissionError):
			api.assign_access("Administrator", ALLOWED_PROFILE)
