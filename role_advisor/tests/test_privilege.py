# Copyright (c) 2026, Upande and contributors
# For license information, please see license.txt

from frappe.tests import IntegrationTestCase

from role_advisor import capability, privilege
from role_advisor.tests.fixtures import (
	INNOCUOUS_DOCTYPE,
	ensure_profile,
	ensure_role,
	grant,
)

SAFE_ROLE = "_RA Safe Role"
UNSAFE_ROLE = "_RA Unsafe Role"
READER_ROLE = "_RA Reader Role"
SAFE_PROFILE = "_RA Safe Profile"
UNSAFE_PROFILE = "_RA Unsafe Profile"
READER_PROFILE = "_RA Reader Profile"


class TestPrivilegeCheck(IntegrationTestCase):
	def setUp(self):
		grant(ensure_role(SAFE_ROLE), INNOCUOUS_DOCTYPE, "read", "write")
		# Role Profile is on the privileged list, so write on it is escalation.
		grant(ensure_role(UNSAFE_ROLE), "Role Profile", "read", "write")
		grant(ensure_role(READER_ROLE), "Role Profile", "read")

		ensure_profile(SAFE_PROFILE, SAFE_ROLE)
		ensure_profile(UNSAFE_PROFILE, UNSAFE_ROLE)
		ensure_profile(READER_PROFILE, READER_ROLE)

		capability.clear_capability_index()

	def tearDown(self):
		capability.clear_capability_index()

	def test_a_profile_granting_only_todo_is_safe(self):
		self.assertEqual(privilege.privileged_grants(SAFE_PROFILE), {})
		self.assertFalse(privilege.is_privileged(SAFE_PROFILE))

	def test_a_profile_granting_write_on_role_profile_is_privileged(self):
		grants = privilege.privileged_grants(UNSAFE_PROFILE)

		self.assertIn("Role Profile", grants)
		self.assertIn("write", grants["Role Profile"])
		self.assertTrue(privilege.is_privileged(UNSAFE_PROFILE))

	def test_read_only_on_a_privileged_doctype_is_not_privileged(self):
		"""User Manager already holds read on Role Profile in production.

		Treating read as privileged would refuse every realistic allowlist.
		"""
		self.assertFalse(privilege.is_privileged(READER_PROFILE))

	def test_an_unknown_profile_is_treated_as_privileged(self):
		"""Fail closed: a profile absent from the index cannot be vouched for."""
		self.assertTrue(privilege.is_privileged("_RA No Such Profile"))

	def test_describe_renders_grants_readably(self):
		self.assertEqual(
			privilege.describe({"User": {"write", "delete"}, "Role": {"create"}}),
			"Role: create; User: delete, write",
		)
