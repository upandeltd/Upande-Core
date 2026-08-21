# Copyright (c) 2026, ghost-mann and contributors
# For license information, please see license.txt

import frappe
from frappe.tests import IntegrationTestCase

from role_advisor import capability, delegation, requests
from role_advisor.tests.fixtures import INNOCUOUS_DOCTYPE, ensure_user
from role_advisor.tests.test_delegation import ALLOWED_PROFILE, OUT_OF_SCOPE, build_fixture

PLAIN = "_ra_selfservice@example.com"


class TestSelfService(IntegrationTestCase):
	"""An ordinary employee with no administrative role at all."""

	def setUp(self):
		build_fixture(self)
		ensure_user(PLAIN)
		doc = frappe.get_doc("User", PLAIN)
		capability.set_user_role_profiles(doc, [ALLOWED_PROFILE])
		doc.save(ignore_permissions=True)
		frappe.set_user(PLAIN)

	def tearDown(self):
		frappe.set_user("Administrator")
		delegation.clear_cache()

	def test_a_plain_employee_holds_no_administrative_role(self):
		roles = set(frappe.get_roles(PLAIN))

		self.assertNotIn("System Manager", roles)
		self.assertNotIn("User Manager", roles)

	def test_they_can_see_their_own_access(self):
		me = requests.my_access()

		self.assertEqual(me["user"], PLAIN)
		self.assertEqual(me["profiles"], [ALLOWED_PROFILE])
		self.assertFalse(me["is_administrator"])

	def test_my_access_takes_no_user_argument(self):
		"""There is no parameter to point at somebody else."""
		import inspect

		signature = inspect.signature(requests.my_access)

		self.assertEqual(list(signature.parameters), [])

	def test_they_can_search_documents_and_rights(self):
		self.assertTrue(requests.search_documents("user", 5))
		self.assertIn("read", requests.rights_for(INNOCUOUS_DOCTYPE))

	def test_they_can_check_something_for_themselves(self):
		verdict = requests.check_for_me([{"doctype": INNOCUOUS_DOCTYPE, "right": "read"}])

		self.assertIn(verdict["resolution"], (requests.COVERED, requests.FIT_FOUND))
		self.assertEqual(verdict["user"], PLAIN)

	def test_they_can_raise_a_request_for_themselves(self):
		result = requests.request_for_me(
			[{"doctype": INNOCUOUS_DOCTYPE, "right": "write"}], reason="need to edit"
		)

		self.assertEqual(
			frappe.db.get_value("Access Request", result["request"], "for_user"), PLAIN
		)
		self.assertEqual(
			frappe.db.get_value("Access Request", result["request"], "raised_by"), PLAIN
		)

	def test_they_see_only_their_own_requests(self):
		requests.request_for_me([{"doctype": INNOCUOUS_DOCTYPE, "right": "write"}])

		for row in requests.my_requests():
			self.assertTrue(PLAIN in (row["for_user"], row["raised_by"]))

	def test_they_cannot_ask_on_behalf_of_anyone_else(self):
		with self.assertRaises(frappe.PermissionError):
			requests.submit_request(
				OUT_OF_SCOPE, [{"doctype": INNOCUOUS_DOCTYPE, "right": "read"}]
			)

	def test_every_administrative_endpoint_refuses_them(self):
		from role_advisor import api, dashboard

		for call in (
			dashboard.summary,
			dashboard.user_table,
			dashboard.module_exposure,
			dashboard.findings,
			dashboard.map_list,
			api.get_manageable_users,
			api.get_grantable_profiles,
			requests.queue,
		):
			with self.assertRaises(frappe.PermissionError, msg=call.__name__):
				call()

	def test_they_cannot_fulfil_their_own_request(self):
		"""Asking and granting must stay separate people."""
		# `write` rather than `read`: their own profile already grants read, so
		# the request would resolve as Covered and there would be nothing to
		# fulfil - the test has to bite on a real recommendation.
		result = requests.request_for_me([{"doctype": INNOCUOUS_DOCTYPE, "right": "write"}])
		self.assertEqual(result["resolution"], requests.FIT_FOUND)

		with self.assertRaises(frappe.PermissionError):
			requests.fulfil(result["request"])

	def test_the_page_is_open_to_any_desk_user(self):
		self.assertTrue(frappe.db.exists("Page", "my-access"))

		roles = frappe.get_all(
			"Has Role", filters={"parent": "my-access", "parenttype": "Page"}, pluck="role"
		)
		self.assertEqual(roles, [], "My Access must not be role-restricted")

	def test_the_admin_workspace_is_hidden_from_them(self):
		"""A workspace of links that all refuse is worse than no workspace."""
		roles = frappe.get_all(
			"Has Workspace Role" if frappe.db.exists("DocType", "Has Workspace Role") else "Has Role",
			filters={"parent": "User Access", "parenttype": "Workspace"},
			pluck="role",
		)

		self.assertTrue(roles, "the admin workspace should be role-restricted")
		self.assertNotIn("All", roles)
