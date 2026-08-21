# Copyright (c) 2026, ghost-mann and contributors
# For license information, please see license.txt

import json

import frappe
from frappe.tests import IntegrationTestCase

from role_advisor import api, delegation, permissions
from role_advisor.tests.test_delegation import (
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

	def test_the_workspace_is_a_door_and_not_a_second_navigation(self):
		"""Everything the app does is in the app's own sidebar.

		Listing it again on the workspace gave two navigations that could
		disagree, and the desk one always won because it loads first. The
		workspace keeps exactly one entry: the way in.
		"""
		self.assertTrue(frappe.db.exists("Workspace", "User Access"))

		shortcuts = frappe.get_all(
			"Workspace Shortcut", filters={"parent": "User Access"}, pluck="link_to"
		)
		self.assertEqual(shortcuts, ["access-dashboard"])

		links = frappe.get_all(
			"Workspace Link", filters={"parent": "User Access"}, pluck="link_to"
		)
		self.assertEqual(links, [], "the workspace should carry no link cards")

	def test_the_app_appears_on_the_apps_screen_with_a_route_that_exists(self):
		entries = frappe.get_hooks("add_to_apps_screen", app_name="role_advisor")

		self.assertEqual(len(entries), 1)
		entry = entries[0]
		self.assertEqual(entry["title"], "Role Advisor")
		self.assertEqual(entry["route"], "/desk/access-dashboard")
		self.assertTrue(
			frappe.db.exists("Page", entry["route"].rsplit("/", 1)[-1]),
			"the apps screen points at a page that does not exist",
		)
		self.assertEqual(
			entry["has_permission"], "role_advisor.permissions.has_app_permission"
		)

	def test_the_desk_home_carries_an_icon_for_the_app(self):
		"""The apps screen is built from Desktop Icon records, not from the hook.

		Frappe generates them from `add_to_apps_screen` on install; a site that
		installed this app before the hook existed needs the patch, which is why
		this asserts on the record and not on the hook.
		"""
		icon = frappe.db.get_value(
			"Desktop Icon",
			{"icon_type": "App", "app": "role_advisor"},
			["label", "link", "logo_url", "hidden"],
			as_dict=True,
		)

		self.assertIsNotNone(icon, "Role Advisor has no desk icon")
		self.assertEqual(icon.label, "Role Advisor")
		self.assertEqual(icon.link, "/desk/access-dashboard")
		self.assertEqual(icon.logo_url, "/assets/role_advisor/images/role-advisor-logo.svg")
		self.assertFalse(icon.hidden)

	def test_a_saved_desk_arrangement_gains_the_icon(self):
		"""Frappe renders a stored Desktop Layout instead of the live icon list,
		so a new icon stays invisible to anyone who has ever arranged their home
		screen. The patch appends it; this asserts it landed."""
		layouts = frappe.get_all("Desktop Layout", pluck="name")
		if not layouts:
			self.skipTest("nobody on this site has arranged their desk home")

		for name in layouts:
			layout = json.loads(frappe.db.get_value("Desktop Layout", name, "layout") or "[]")
			self.assertTrue(
				any(row.get("name") == "Role Advisor" for row in layout),
				f"{name} would never see the app",
			)

	def test_the_short_url_lands_on_the_dashboard(self):
		"""`/role-advisor` is the address to give someone."""
		targets = {
			row["source"]: row["target"]
			for row in frappe.get_hooks("website_redirects", app_name="role_advisor")
		}

		self.assertEqual(targets["/role-advisor"], "/desk/access-dashboard")
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
