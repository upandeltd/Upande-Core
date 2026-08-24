# Copyright (c) 2026, ghost-mann and contributors
# For license information, please see license.txt

import frappe
from frappe.tests import IntegrationTestCase

TEST_DESIGNATION = "_RA Test Designation"
TEST_PROFILE = "_RA Map Test Profile"


class TestDesignationAccessMap(IntegrationTestCase):
	def setUp(self):
		if not frappe.db.exists("Designation", TEST_DESIGNATION):
			frappe.get_doc(
				{"doctype": "Designation", "designation_name": TEST_DESIGNATION}
			).insert(ignore_permissions=True)
		if not frappe.db.exists("Role Profile", TEST_PROFILE):
			frappe.get_doc(
				{"doctype": "Role Profile", "role_profile": TEST_PROFILE}
			).insert(ignore_permissions=True)
		self.company = frappe.get_all("Company", pluck="name", limit=1)[0]

		# IntegrationTestCase rolls back once per class, not per test
		# (frappe/tests/classes/integration_test_case.py:72), so rows created by
		# one test are still there for the next. Clear them explicitly.
		for name in frappe.get_all(
			"Designation Access Map",
			filters={"designation": TEST_DESIGNATION},
			pluck="name",
		):
			frappe.delete_doc("Designation Access Map", name, force=True)

	def _row(self, **kwargs):
		defaults = {
			"doctype": "Designation Access Map",
			"designation": TEST_DESIGNATION,
			"role_profile": TEST_PROFILE,
		}
		return frappe.get_doc({**defaults, **kwargs})

	def test_a_bare_designation_row_is_accepted(self):
		doc = self._row().insert(ignore_permissions=True)

		self.assertEqual(doc.designation, TEST_DESIGNATION)
		self.assertFalse(doc.is_active, "seeded rows must not be active by default")

	def test_duplicate_triple_is_rejected(self):
		self._row(for_company=self.company).insert(ignore_permissions=True)

		with self.assertRaises(frappe.ValidationError):
			self._row(for_company=self.company).insert(ignore_permissions=True)

	def test_blank_company_collides_with_null_company(self):
		"""Two 'applies to all companies' rows are the same row.

		A DB unique index would accept both, because MariaDB treats each NULL as
		distinct. This is why uniqueness lives in validate.
		"""
		self._row(for_company=None).insert(ignore_permissions=True)

		with self.assertRaises(frappe.ValidationError):
			self._row(for_company="").insert(ignore_permissions=True)

	def test_same_designation_different_company_is_allowed(self):
		companies = frappe.get_all("Company", pluck="name", limit=2)
		if len(companies) < 2:
			self.skipTest("site has fewer than two companies")

		self._row(for_company=companies[0]).insert(ignore_permissions=True)
		second = self._row(for_company=companies[1]).insert(ignore_permissions=True)

		self.assertEqual(second.for_company, companies[1])

	def test_scope_key_normalises_blanks_to_none(self):
		doc = self._row(for_company=self.company, for_branch="")

		self.assertEqual(doc.scope_key(), (self.company, None, None, None))

	def test_branch_requires_a_company(self):
		"""A branch-scoped row with no company cannot be resolved unambiguously."""
		branch = frappe.get_all("Branch", pluck="name", limit=1)
		if not branch:
			self.skipTest("site has no Branch records")

		with self.assertRaises(frappe.ValidationError):
			self._row(for_branch=branch[0], for_company=None).insert(ignore_permissions=True)
