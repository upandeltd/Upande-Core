# Copyright (c) 2026, ghost-mann and contributors
# For license information, please see license.txt

import csv
import os
import tempfile
import unittest

from upande_core import live_export

USERS = [
	{"name": "a@x.com", "full_name": "Ann", "enabled": 1, "user_type": "System User",
	 "role_profile_name": "Clerk", "module_profile": "", "last_login": "", "last_active": "",
	 "creation": ""},
	{"name": "b@x.com", "full_name": "Bob", "enabled": 0, "user_type": "System User",
	 "role_profile_name": "", "module_profile": "MP", "last_login": "", "last_active": "",
	 "creation": ""},
	{"name": "c@x.com", "full_name": "Cid", "enabled": 1, "user_type": "Website User",
	 "role_profile_name": None, "module_profile": None, "last_login": "", "last_active": "",
	 "creation": ""},
]

EMPLOYEES = [
	{"name": "E1", "user_id": "a@x.com", "company": "Karen Roses", "branch": "B",
	 "department": "D", "designation": "Clerk", "grade": "G", "status": "Active"},
	# Bob has a left record only - it should still supply company.
	{"name": "E2", "user_id": "b@x.com", "company": "Kaitet Ltd.", "branch": "",
	 "department": "", "designation": "Guard", "grade": "", "status": "Left"},
]

USER_ROLES = [
	{"parent": "a@x.com", "role": "Clerk Role"},
	{"parent": "a@x.com", "role": "Leave Approver"},
	{"parent": "b@x.com", "role": "System Manager"},
	{"parent": "b@x.com", "role": "User Manager"},
]

PROFILE_ROLES = [{"parent": "Clerk", "role": "Clerk Role"}]

PERMISSIONS = [
	{"user": "a@x.com", "allow": "Company", "for_value": "Karen Roses"},
	{"user": "a@x.com", "allow": "Employee", "for_value": "E1"},
]


class TestLiveExportTransform(unittest.TestCase):
	"""Pure join, so it runs with no site and no network."""

	def setUp(self):
		self.rows = {
			r["user"]: r
			for r in live_export.build_rows(
				USERS, EMPLOYEES, USER_ROLES, PROFILE_ROLES, PERMISSIONS
			)
		}

	def test_every_user_is_exported_including_disabled_ones(self):
		"""Filtering to enabled=1 is what under-reported the user list before."""
		self.assertEqual(set(self.rows), {"a@x.com", "b@x.com", "c@x.com"})
		self.assertEqual(self.rows["b@x.com"]["enabled"], 0)

	def test_roles_outside_the_profile_are_named(self):
		"""These are exactly the roles v16 prunes on the next save."""
		self.assertEqual(self.rows["a@x.com"]["roles_outside_profile"], "Leave Approver")

	def test_a_user_with_no_profile_reports_no_outside_roles(self):
		"""With no profile there is no prune, so nothing is at risk."""
		self.assertEqual(self.rows["b@x.com"]["roles_outside_profile"], "")

	def test_a_left_employee_still_supplies_context(self):
		self.assertEqual(self.rows["b@x.com"]["company"], "Kaitet Ltd.")
		self.assertEqual(self.rows["b@x.com"]["employee_status"], "Left")

	def test_a_user_with_no_employee_record_is_blank_not_missing(self):
		self.assertEqual(self.rows["c@x.com"]["company"], "")
		self.assertEqual(self.rows["c@x.com"]["employee"], "")

	def test_none_values_become_empty_strings(self):
		"""A None in a CSV cell writes the literal text 'None'."""
		self.assertEqual(self.rows["c@x.com"]["role_profile_name"], "")
		self.assertEqual(self.rows["c@x.com"]["module_profile"], "")

	def test_admin_role_flags_and_counts(self):
		self.assertEqual(self.rows["b@x.com"]["is_system_manager"], 1)
		self.assertEqual(self.rows["b@x.com"]["is_user_manager"], 1)
		self.assertEqual(self.rows["a@x.com"]["is_system_manager"], 0)
		self.assertEqual(self.rows["a@x.com"]["role_count"], 2)

	def test_permissions_are_counted_and_companies_listed(self):
		self.assertEqual(self.rows["a@x.com"]["user_permissions"], 2)
		self.assertEqual(self.rows["a@x.com"]["permitted_companies"], "Karen Roses")

	def test_enabled_users_sort_before_disabled(self):
		ordered = live_export.build_rows(
			USERS, EMPLOYEES, USER_ROLES, PROFILE_ROLES, PERMISSIONS
		)
		self.assertEqual(ordered[-1]["user"], "b@x.com")

	def test_csv_round_trips_with_every_column(self):
		path = os.path.join(tempfile.mkdtemp(), "u.csv")
		live_export.write_csv(list(self.rows.values()), path)

		with open(path, encoding="utf-8") as handle:
			read = list(csv.DictReader(handle))

		self.assertEqual(len(read), 3)
		self.assertEqual(list(read[0]), list(live_export.COLUMNS))
		os.remove(path)

	def test_missing_credentials_fail_loudly(self):
		saved = {k: os.environ.pop(k, None) for k in ("KAITET_HOST", "KAITET_TOKEN")}
		try:
			with self.assertRaises(RuntimeError):
				live_export.fetch("User", ["name"])
		finally:
			for key, value in saved.items():
				if value is not None:
					os.environ[key] = value
