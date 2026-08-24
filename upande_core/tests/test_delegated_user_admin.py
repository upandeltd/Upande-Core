# Copyright (c) 2026, ghost-mann and contributors
# For license information, please see license.txt

import frappe
from frappe.tests import IntegrationTestCase

from upande_core import capability
from upande_core.tests.fixtures import (
	INNOCUOUS_DOCTYPE,
	clear_delegate,
	ensure_profile,
	ensure_role,
	ensure_user,
	grant,
)

ADMIN_USER = "_ra_delegate@example.com"
SAFE_ROLE = "_RA DUA Safe Role"
UNSAFE_ROLE = "_RA DUA Unsafe Role"
SAFE_PROFILE = "_RA DUA Safe Profile"
UNSAFE_PROFILE = "_RA DUA Unsafe Profile"


class TestDelegatedUserAdmin(IntegrationTestCase):
	def setUp(self):
		grant(ensure_role(SAFE_ROLE), INNOCUOUS_DOCTYPE, "read", "write")
		grant(ensure_role(UNSAFE_ROLE), "Role Profile", "read", "write")
		ensure_profile(SAFE_PROFILE, SAFE_ROLE)
		ensure_profile(UNSAFE_PROFILE, UNSAFE_ROLE)
		capability.clear_capability_index()

		ensure_user(ADMIN_USER)
		clear_delegate(ADMIN_USER)
		for name in frappe.get_all(
			"User Permission", filters={"user": ADMIN_USER}, pluck="name"
		):
			frappe.delete_doc("User Permission", name, force=True)

		self.companies = frappe.get_all("Company", pluck="name", limit=2)

	def tearDown(self):
		capability.clear_capability_index()

	def _admin(self, **kwargs):
		defaults = {
			"doctype": "Delegated User Admin",
			"user": ADMIN_USER,
			"enabled": 1,
			"companies": [{"company": self.companies[0]}],
			"allowed_role_profiles": [{"role_profile": SAFE_PROFILE}],
		}
		return frappe.get_doc({**defaults, **kwargs})

	def test_a_safe_allowlist_is_accepted(self):
		doc = self._admin().insert(ignore_permissions=True)

		self.assertEqual(doc.user, ADMIN_USER)
		self.assertEqual(len(doc.allowed_role_profiles), 1)

	def test_a_privileged_profile_is_refused_at_save(self):
		"""Enforcement point one: the System Manager sees it immediately."""
		doc = self._admin(allowed_role_profiles=[{"role_profile": UNSAFE_PROFILE}])

		with self.assertRaises(frappe.ValidationError):
			doc.insert(ignore_permissions=True)

	def test_scope_is_required(self):
		"""An admin with no company scope could reach every user."""
		doc = self._admin(companies=[])

		with self.assertRaises(frappe.ValidationError):
			doc.insert(ignore_permissions=True)

	def test_one_record_per_user(self):
		self._admin().insert(ignore_permissions=True)

		with self.assertRaises((frappe.ValidationError, frappe.DuplicateEntryError)):
			self._admin().insert(ignore_permissions=True)

	def test_companies_default_from_existing_user_permissions(self):
		"""Do not re-scope the 244 users who already have Company permissions."""
		frappe.get_doc(
			{
				"doctype": "User Permission",
				"user": ADMIN_USER,
				"allow": "Company",
				"for_value": self.companies[0],
			}
		).insert(ignore_permissions=True)

		doc = frappe.get_doc(
			{
				"doctype": "Delegated User Admin",
				"user": ADMIN_USER,
				"enabled": 1,
				"allowed_role_profiles": [{"role_profile": SAFE_PROFILE}],
			}
		).insert(ignore_permissions=True)

		self.assertEqual([r.company for r in doc.companies], [self.companies[0]])
