# Copyright (c) 2026, ghost-mann and contributors
# For license information, please see license.txt

import frappe
from frappe.tests import IntegrationTestCase

from upande_core import capability, mapping
from upande_core.tests.fixtures import (
	INNOCUOUS_DOCTYPE,
	clear_map,
	ensure_designation,
	ensure_profile,
	ensure_role,
	grant,
)

DESIGNATION = "_RA Mapping Designation"
BROAD_ROLE = "_RA Broad Role"
TIGHT_ROLE = "_RA Tight Role"
BROAD_PROFILE = "_RA Broad Profile"
TIGHT_PROFILE = "_RA Tight Profile"
TWIN_PROFILE = "_RA Twin Profile"


class TestMapping(IntegrationTestCase):
	def setUp(self):
		ensure_designation(DESIGNATION)
		clear_map(DESIGNATION)

		# Broad grants four rights, tight grants one - so tightness is decided
		# by permission count, not by profile name or row order.
		grant(ensure_role(BROAD_ROLE), INNOCUOUS_DOCTYPE, "read", "write", "create", "delete")
		grant(ensure_role(TIGHT_ROLE), INNOCUOUS_DOCTYPE, "read")
		ensure_profile(BROAD_PROFILE, BROAD_ROLE)
		ensure_profile(TIGHT_PROFILE, TIGHT_ROLE)
		ensure_profile(TWIN_PROFILE, TIGHT_ROLE)

		capability.clear_capability_index()
		self.companies = frappe.get_all("Company", pluck="name", limit=2)

	def tearDown(self):
		capability.clear_capability_index()

	def _map_row(self, profile, **scope):
		return frappe.get_doc(
			{
				"doctype": "Designation Access Map",
				"designation": DESIGNATION,
				"role_profile": profile,
				"is_active": 1,
				**scope,
			}
		).insert(ignore_permissions=True)

	def test_candidate_scopes_are_ordered_most_specific_first(self):
		scopes = mapping.candidate_scopes(
			{"company": "C", "branch": "B", "department": "D", "grade": "G"}
		)

		# Default dimensions are company + branch, so three candidates.
		self.assertEqual(
			scopes,
			[
				{"company": "C", "branch": "B"},
				{"company": "C", "branch": None},
				{"company": None, "branch": None},
			],
		)

	def test_a_bare_designation_row_matches_any_scope(self):
		row = self._map_row(TIGHT_PROFILE)

		resolved = mapping.resolve(DESIGNATION, {"company": self.companies[0]})

		self.assertEqual(resolved, row.name)

	def test_a_company_row_beats_a_bare_row(self):
		self._map_row(BROAD_PROFILE)
		specific = self._map_row(TIGHT_PROFILE, for_company=self.companies[0])

		resolved = mapping.resolve(DESIGNATION, {"company": self.companies[0]})

		self.assertEqual(resolved, specific.name)

	def test_a_row_for_another_company_does_not_match(self):
		if len(self.companies) < 2:
			self.skipTest("site has fewer than two companies")
		self._map_row(TIGHT_PROFILE, for_company=self.companies[1])

		self.assertIsNone(mapping.resolve(DESIGNATION, {"company": self.companies[0]}))

	def test_inactive_rows_are_ignored_by_default(self):
		frappe.get_doc(
			{
				"doctype": "Designation Access Map",
				"designation": DESIGNATION,
				"role_profile": TIGHT_PROFILE,
				"is_active": 0,
			}
		).insert(ignore_permissions=True)

		self.assertIsNone(mapping.resolve(DESIGNATION, {"company": self.companies[0]}))

	def test_inactive_rows_are_visible_to_the_dry_run(self):
		row = frappe.get_doc(
			{
				"doctype": "Designation Access Map",
				"designation": DESIGNATION,
				"role_profile": TIGHT_PROFILE,
				"is_active": 0,
			}
		).insert(ignore_permissions=True)

		resolved = mapping.resolve(
			DESIGNATION, {"company": self.companies[0]}, active_only=False
		)

		self.assertEqual(resolved, row.name)

	def test_tie_break_picks_the_tightest_profile(self):
		"""Majority vote drifts toward over-granting; tightness does not."""
		self.assertEqual(
			mapping.tie_break([BROAD_PROFILE, TIGHT_PROFILE]), TIGHT_PROFILE
		)

	def test_tie_break_is_stable_on_equal_counts(self):
		"""Two profiles granting the same amount must resolve deterministically."""
		self.assertEqual(
			mapping.tie_break([TWIN_PROFILE, TIGHT_PROFILE]),
			sorted([TWIN_PROFILE, TIGHT_PROFILE])[0],
		)

	def test_tie_break_returns_none_for_an_empty_list(self):
		self.assertIsNone(mapping.tie_break([]))

	def test_employee_scope_is_all_none_for_an_unlinked_user(self):
		scope = mapping.employee_scope("_ra_no_such_user@example.com")

		self.assertEqual(set(scope.values()), {None})
