# Copyright (c) 2026, Upande and contributors
# For license information, please see license.txt

import frappe
from frappe.permissions import get_all_perms
from frappe.tests import IntegrationTestCase

from role_advisor import capability

TEST_ROLE = "_RA Test Role"
TEST_PROFILE = "_RA Test Profile"


class TestCapabilityIndex(IntegrationTestCase):
	def setUp(self):
		capability.clear_capability_index()

		if not frappe.db.exists("Role", TEST_ROLE):
			frappe.get_doc({"doctype": "Role", "role_name": TEST_ROLE}).insert()

		# ToDo is a core doctype with standard DocPerms. Inserting a Custom
		# DocPerm against it discards ToDo's standard perms for every role for
		# the duration of this test - safe only because the test rolls back and
		# nothing in this app depends on ToDo.
		frappe.get_doc(
			{
				"doctype": "Custom DocPerm",
				"parent": "ToDo",
				"role": TEST_ROLE,
				"permlevel": 0,
				"read": 1,
				"write": 1,
				# Custom DocPerm defaults `export` (and `read`) to 1. Listing only
				# the rights you want silently grants export too, so every tracked
				# right is set explicitly here - including the denied ones.
				"export": 0,
			}
		).insert()

		if not frappe.db.exists("Role Profile", TEST_PROFILE):
			frappe.get_doc(
				{
					"doctype": "Role Profile",
					"role_profile": TEST_PROFILE,
					"roles": [{"role": TEST_ROLE}],
				}
			).insert()

		capability.clear_capability_index()

	def tearDown(self):
		capability.clear_capability_index()

	def test_batched_perm_query_matches_core_get_all_perms(self):
		"""_perm_rows_for_roles must agree with frappe.permissions.get_all_perms.

		The batched query exists only for speed. If core changes how Custom
		DocPerm overrides standard DocPerm, this fails rather than silently
		producing wrong output.
		"""
		batched = capability._capabilities_from_rows(
			capability._perm_rows_for_roles([TEST_ROLE])
		)
		core = capability._capabilities_from_rows(get_all_perms(TEST_ROLE))

		self.assertEqual(batched.get(TEST_ROLE, {}), core.get(TEST_ROLE, {}))

	def test_index_excludes_higher_permlevels_and_if_owner(self):
		"""permlevel > 0 and if_owner rows are field/ownership scoped, not grants."""
		rows = [
			{"role": "R", "parent": "DT", "permlevel": 1, "if_owner": 0, "write": 1},
			{"role": "R", "parent": "DT", "permlevel": 0, "if_owner": 1, "delete": 1},
			{"role": "R", "parent": "DT", "permlevel": 0, "if_owner": 0, "read": 1},
		]

		self.assertEqual(
			capability._capabilities_from_rows(rows), {"R": {"DT": {"read"}}}
		)

	def test_index_is_served_from_cache_on_the_second_call(self):
		first = capability.build_capability_index()

		# Make a recompute impossible, so a correct result can only have come
		# from the cache. Asserting on behaviour rather than query counts keeps
		# this independent of how many queries the scan happens to need.
		def _explode():
			raise AssertionError("recomputed a cached capability index")

		original = capability._compute_capability_index
		capability._compute_capability_index = _explode
		try:
			self.assertEqual(capability.build_capability_index(), first)
		finally:
			capability._compute_capability_index = original

	def test_force_rebuilds_the_index(self):
		capability.build_capability_index()

		rebuilt = capability.build_capability_index(force=True)

		self.assertIn(TEST_PROFILE, rebuilt)
		self.assertEqual(rebuilt[TEST_PROFILE].get("ToDo"), {"read", "write"})

	def test_total_perm_count_sums_granted_pairs(self):
		self.assertEqual(
			capability.total_perm_count({"A": {"read", "write"}, "B": {"read"}}), 3
		)
