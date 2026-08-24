# Copyright (c) 2026, ghost-mann and contributors
# For license information, please see license.txt

import json

import frappe
from frappe.tests import IntegrationTestCase

from upande_core import api, delegation, permissions
from upande_core.tests.test_delegation import (
	ADMIN,
	ALLOWED_PROFILE,
	IN_SCOPE,
	build_fixture,
)


class TestConsolePage(IntegrationTestCase):
	"""The page is a thin client over four API methods; this covers the wiring
	it depends on - that the records exist and the calls a delegate makes work
	in the delegate's own session."""

	def setUp(self):
		build_fixture(self)

	def tearDown(self):
		frappe.set_user("Administrator")
		delegation.clear_cache()

	def test_the_page_is_installed_and_reachable_by_a_delegate(self):
		self.assertTrue(frappe.db.exists("Page", "assign-access"))

		roles = frappe.get_all(
			"Has Role",
			filters={"parent": "assign-access", "parenttype": "Page"},
			pluck="role",
		)

		self.assertIn("User Manager", roles)
		self.assertIn("System Manager", roles)

	def test_the_page_route_does_not_collide_with_the_workspace(self):
		"""The workspace is labelled "User Access", which Frappe slugifies to
		`user-access`. A workspace beats a page on a route collision, so a page
		named `user-access` silently never opens - which is exactly what
		happened. The page must therefore live on its own route."""
		workspace_route = frappe.scrub("User Access").replace("_", "-")

		self.assertNotEqual("assign-access", workspace_route)
		self.assertFalse(
			frappe.db.exists("Page", workspace_route),
			"a Page on the workspace's own route can never be reached",
		)

	def test_the_workspace_is_hidden_now_that_the_ui_moved(self):
		"""The workspace was the door to this app's own page; that page is retired.

		It is hidden rather than deleted, so a site that rolls the merge back still
		has it. It must carry no link cards: a second navigation that could
		disagree with the real one is the thing this avoids.
		"""
		self.assertTrue(frappe.db.exists("Workspace", "User Access"))
		self.assertTrue(
			frappe.db.get_value("Workspace", "User Access", "is_hidden"),
			"the workspace still advertises a page that is no longer the UI",
		)

		links = frappe.get_all(
			"Workspace Link", filters={"parent": "User Access"}, pluck="link_to"
		)
		self.assertEqual(links, [], "the workspace should carry no link cards")

	def test_the_short_url_lands_on_the_merged_page(self):
		"""`/role-advisor` is still the address to give someone.

		It no longer lands on this app's own desk page: the UI moved into the IT
		dashboard, and the redirect followed it. `/my-access` did not move - it is
		the one surface a non-administrator uses, and it is still a desk page.
		"""
		targets = {
			row["source"]: row["target"]
			for row in frappe.get_hooks("website_redirects", app_name="upande_core")
		}

		self.assertEqual(targets["/role-advisor"], "/it-dashboard")
		self.assertEqual(targets["/my-access"], "/desk/my-access")

	def test_the_apps_screen_shows_the_app_to_an_administrator(self):
		self.assertTrue(permissions.has_app_permission())

	def test_the_apps_screen_shows_the_app_to_a_delegate(self):
		frappe.set_user(ADMIN)
		self.assertTrue(permissions.has_app_permission())

	def test_the_apps_screen_hides_the_app_from_everyone_else(self):
		frappe.set_user(IN_SCOPE)
		self.assertFalse(permissions.has_app_permission())

	def test_the_console_boot_calls_succeed_for_a_delegate(self):
		"""Both calls the page makes on load, in the delegate's own session."""
		frappe.set_user(ADMIN)

		users = api.get_manageable_users(limit=500)
		profiles = api.get_grantable_profiles()

		self.assertIn(IN_SCOPE, [row["name"] for row in users])
		self.assertEqual([p["role_profile"] for p in profiles], [ALLOWED_PROFILE])
		# The page renders role_profiles per row, so it must be present.
		self.assertIn("role_profiles", users[0])

	def test_a_non_delegate_gets_a_permission_error_not_a_crash(self):
		"""The page is visible to every User Manager, so this is the common path."""
		frappe.set_user(IN_SCOPE)

		with self.assertRaises(frappe.PermissionError):
			api.get_manageable_users()

	def test_preview_then_assign_is_the_sequence_the_page_uses(self):
		frappe.set_user(ADMIN)

		preview = api.preview_assignment(IN_SCOPE, ALLOWED_PROFILE)
		self.assertEqual(preview["profiles_after"], [ALLOWED_PROFILE])

		result = api.assign_access(IN_SCOPE, ALLOWED_PROFILE)
		self.assertEqual(result["profiles"], [ALLOWED_PROFILE])
		# The page reads these three keys off the result to refresh its panel.
		for key in ("user", "profiles", "module_profile"):
			self.assertIn(key, result)
