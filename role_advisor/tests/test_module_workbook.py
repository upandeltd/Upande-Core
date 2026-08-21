# Copyright (c) 2026, ghost-mann and contributors
# For license information, please see license.txt

import os

import frappe
import openpyxl
from frappe.tests import IntegrationTestCase

from role_advisor import capability, module_workbook


class TestModuleWorkbook(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		capability.clear_capability_index()
		cls.data = module_workbook.gather()
		cls.path = module_workbook.build(
			path=os.path.join(
				frappe.utils.get_site_path("private", "files"), "_ra_test_modwb.xlsx"
			)
		)
		cls.book = openpyxl.load_workbook(cls.path, read_only=True)

	@classmethod
	def tearDownClass(cls):
		cls.book.close()
		if os.path.exists(cls.path):
			os.remove(cls.path)
		super().tearDownClass()

	def test_there_is_a_sheet_for_every_module_with_grants(self):
		expected = len(self.data["by_module"])

		# Three cross-cutting tabs sit in front of the module tabs.
		self.assertEqual(len(self.book.sheetnames), expected + 3)
		self.assertEqual(
			self.book.sheetnames[:3], ["Overview", "Users by Module", "Profile Index"]
		)

	def test_tab_names_are_unique_and_within_the_excel_limit(self):
		for name in self.book.sheetnames:
			self.assertLessEqual(len(name), 31, name)
			for char in "[]:*?/\\":
				self.assertNotIn(char, name)
		self.assertEqual(len(self.book.sheetnames), len(set(self.book.sheetnames)))

	def test_every_module_sheet_groups_roles_and_permissions_under_a_profile(self):
		module = max(self.data["by_module"], key=lambda m: len(self.data["by_module"][m]))
		rows = module_workbook.module_rows(module, self.data)
		sections = [row["section"] for row in rows]

		self.assertIn(module_workbook.SECTION_PROFILE, sections)
		self.assertIn(module_workbook.SECTION_PERMISSION, sections)
		# A PROFILE header must come before the rows it groups.
		self.assertEqual(sections[0], module_workbook.SECTION_PROFILE)

	def test_permission_rows_match_the_capability_index(self):
		"""A sheet that under-reports grants would understate real access."""
		for module, profiles in list(self.data["by_module"].items())[:6]:
			rows = module_workbook.module_rows(module, self.data)
			counted = sum(
				1 for r in rows if r["section"] == module_workbook.SECTION_PERMISSION
			)
			expected = sum(len(doctypes) for doctypes in profiles.values())
			self.assertEqual(counted, expected, module)

	def test_a_cross_module_profile_names_its_other_sheets(self):
		"""The reconciliation flag: owners must see who else edits this profile."""
		spread = max(self.data["profile_modules"], key=lambda p: len(self.data["profile_modules"][p]))
		module = sorted(self.data["profile_modules"][spread])[0]

		rows = module_workbook.module_rows(module, self.data)
		header = next(
			r for r in rows
			if r["section"] == module_workbook.SECTION_PROFILE and r["role_profile"] == spread
		)

		self.assertTrue(header["also_on_sheets"], f"{spread} spans many modules")
		self.assertNotIn(module, header["also_on_sheets"].split(", "))

	def test_each_profile_block_lists_the_users_who_hold_it(self):
		"""A module owner's first question is who can reach their module."""
		module = next(
			m for m, profiles in self.data["by_module"].items()
			if any(self.data["holders"].get(p) for p in profiles)
		)
		rows = module_workbook.module_rows(module, self.data)
		users = [r for r in rows if r["section"] == module_workbook.SECTION_USER]

		self.assertTrue(users, f"{module} has profiles with holders")
		for row in users:
			self.assertTrue(row["user"])
			self.assertTrue(row["user_context"], "context must never be blank")

	def test_user_rows_come_before_the_roles_and_permissions(self):
		"""Block order is PROFILE -> USERS -> ROLES -> PERMISSIONS."""
		module = next(
			m for m, profiles in self.data["by_module"].items()
			if any(self.data["holders"].get(p) for p in profiles)
		)
		order = [r["section"] for r in module_workbook.module_rows(module, self.data)]
		first_user = order.index(module_workbook.SECTION_USER)
		first_perm = order.index(module_workbook.SECTION_PERMISSION)

		self.assertLess(first_user, first_perm)

	def test_overview_counts_distinct_users_per_module(self):
		rows = {r["module"]: r for r in module_workbook.overview_rows(self.data, {m: m for m in self.data["by_module"]})}
		module = max(rows, key=lambda m: rows[m]["users_with_access"])

		expected = len(
			{
				holder["user"]
				for profile in self.data["by_module"][module]
				for holder in self.data["holders"].get(profile, [])
			}
		)

		self.assertEqual(rows[module]["users_with_access"], expected)

	def test_users_by_module_sheet_has_a_row_per_module_user_profile(self):
		rows = module_workbook.users_by_module_rows(self.data)
		expected = sum(
			len(self.data["holders"].get(profile, []))
			for profiles in self.data["by_module"].values()
			for profile in profiles
		)

		self.assertEqual(len(rows), expected)
		self.assertTrue(all(r["module"] and r["user"] for r in rows))

	def test_add_rows_are_present_for_owner_input(self):
		module = sorted(self.data["by_module"])[0]
		rows = module_workbook.module_rows(module, self.data)

		self.assertIn(module_workbook.SECTION_ADD, [r["section"] for r in rows])

	def test_the_export_writes_nothing_to_the_site(self):
		before = (
			frappe.db.count("Role Profile"),
			frappe.db.count("Custom DocPerm"),
			frappe.db.count("Has Role"),
		)

		second = os.path.join(
			frappe.utils.get_site_path("private", "files"), "_ra_test_modwb2.xlsx"
		)
		module_workbook.build(path=second)
		os.remove(second)

		self.assertEqual(
			before,
			(
				frappe.db.count("Role Profile"),
				frappe.db.count("Custom DocPerm"),
				frappe.db.count("Has Role"),
			),
		)
