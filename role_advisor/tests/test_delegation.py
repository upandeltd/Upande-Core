# Copyright (c) 2026, ghost-mann and contributors
# For license information, please see license.txt

import frappe
from frappe.tests import IntegrationTestCase

from role_advisor import capability, delegation, settings
from role_advisor.tests.fixtures import (
	INNOCUOUS_DOCTYPE,
	clear_delegate,
	ensure_employee,
	ensure_profile,
	ensure_role,
	ensure_user,
	grant,
)

ADMIN = "_ra_gate_admin@example.com"
IN_SCOPE = "_ra_in_scope@example.com"
OUT_OF_SCOPE = "_ra_out_of_scope@example.com"
UNLINKED = "_ra_unlinked@example.com"

SAFE_ROLE = "_RA Gate Safe Role"
UNSAFE_ROLE = "_RA Gate Unsafe Role"
ALLOWED_PROFILE = "_RA Gate Allowed Profile"
OTHER_PROFILE = "_RA Gate Other Profile"
UNSAFE_PROFILE = "_RA Gate Unsafe Profile"


def build_fixture(case):
	"""Shared scaffolding: one delegate, one in-scope and one out-of-scope user.

	Exposed as a function so the permission-hook and API suites reuse exactly
	this world rather than drifting from it.
	"""
	case.companies = frappe.get_all("Company", pluck="name", limit=2)
	if len(case.companies) < 2:
		case.skipTest("site has fewer than two companies")

	grant(ensure_role(SAFE_ROLE), INNOCUOUS_DOCTYPE, "read")
	grant(ensure_role(UNSAFE_ROLE), "Role Profile", "read", "write")
	ensure_profile(ALLOWED_PROFILE, SAFE_ROLE)
	ensure_profile(OTHER_PROFILE, SAFE_ROLE)
	ensure_profile(UNSAFE_PROFILE, UNSAFE_ROLE)
	capability.clear_capability_index()

	ensure_user(ADMIN)
	# A delegate is a delegate-role holder *bounded* by a record - the record
	# alone grants nothing, which is why production delegates already hold
	# User Manager. The fixture must model both halves.
	admin_doc = frappe.get_doc("User", ADMIN)
	if settings.delegate_role() not in [r.role for r in admin_doc.roles]:
		admin_doc.append("roles", {"role": settings.delegate_role()})
		admin_doc.save(ignore_permissions=True)

	ensure_employee(ensure_user(IN_SCOPE), case.companies[0])
	ensure_employee(ensure_user(OUT_OF_SCOPE), case.companies[1])
	ensure_user(UNLINKED)

	clear_delegate(ADMIN)
	frappe.get_doc(
		{
			"doctype": "Delegated User Admin",
			"user": ADMIN,
			"enabled": 1,
			"companies": [{"company": case.companies[0]}],
			"allowed_role_profiles": [{"role_profile": ALLOWED_PROFILE}],
		}
	).insert(ignore_permissions=True)

	delegation.clear_cache()


class TestDelegationGates(IntegrationTestCase):
	def setUp(self):
		build_fixture(self)
		self.admin = delegation.current_admin(ADMIN)

	def tearDown(self):
		capability.clear_capability_index()
		delegation.clear_cache()

	def test_current_admin_resolves_an_enabled_record(self):
		self.assertIsNotNone(self.admin)
		self.assertEqual(self.admin.user, ADMIN)

	def test_a_disabled_record_is_not_a_delegate(self):
		doc = frappe.get_doc("Delegated User Admin", ADMIN)
		doc.enabled = 0
		doc.save(ignore_permissions=True)
		delegation.clear_cache()

		self.assertIsNone(delegation.current_admin(ADMIN))

	def test_a_user_with_no_record_is_not_a_delegate(self):
		self.assertIsNone(delegation.current_admin(OUT_OF_SCOPE))

		with self.assertRaises(frappe.PermissionError):
			delegation.assert_delegate(OUT_OF_SCOPE)

	def test_a_target_in_scope_is_manageable(self):
		self.assertTrue(delegation.can_manage(self.admin, IN_SCOPE))
		delegation.assert_can_manage(self.admin, IN_SCOPE)

	def test_a_target_in_another_company_is_refused(self):
		self.assertFalse(delegation.can_manage(self.admin, OUT_OF_SCOPE))

		with self.assertRaises(frappe.PermissionError):
			delegation.assert_can_manage(self.admin, OUT_OF_SCOPE)

	def test_a_target_with_no_employee_record_is_unreachable(self):
		"""The 109 unlinked users have no company, so no delegate can reach them."""
		self.assertFalse(delegation.can_manage(self.admin, UNLINKED))

	def test_administrator_is_never_manageable(self):
		self.assertFalse(delegation.can_manage(self.admin, "Administrator"))

	def test_an_allowlisted_profile_may_be_granted(self):
		delegation.assert_can_grant(self.admin, ALLOWED_PROFILE)

	def test_a_profile_off_the_allowlist_is_refused(self):
		with self.assertRaises(frappe.PermissionError):
			delegation.assert_can_grant(self.admin, OTHER_PROFILE)

	def test_a_privileged_profile_is_refused_even_if_allowlisted(self):
		"""Enforcement point two: the allowlist itself is not trusted.

		A profile's contents can change after it was allowlisted, so the check
		is repeated at grant time. The row is inserted with raw SQL because
		DelegatedUserAdmin.validate refuses it through the ORM - that is
		enforcement point one working, and bypassing it is the only way to
		construct the state point two exists to catch.
		"""
		frappe.db.sql(
			"""insert into `tabDelegated Role Profile`
			   (name, parent, parentfield, parenttype, role_profile, idx)
			   values (%s, %s, 'allowed_role_profiles', 'Delegated User Admin', %s, 2)""",
			(frappe.generate_hash(length=10), ADMIN, UNSAFE_PROFILE),
		)
		delegation.clear_cache()
		admin = delegation.current_admin(ADMIN)

		with self.assertRaises(frappe.PermissionError):
			delegation.assert_can_grant(admin, UNSAFE_PROFILE)
