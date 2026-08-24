# Copyright (c) 2026, ghost-mann and contributors
# For license information, please see license.txt

import unittest

from upande_core import taxonomy


class TestTaxonomyParser(unittest.TestCase):
	"""Pure parser, so no site fixtures - just the awkward real names."""

	def test_place_and_authority_land_in_different_columns(self):
		"""The whole point: (Simotwo) is a place, (Restricted) is a variant."""
		place = taxonomy.parse("Agriculture Production Supervisor-Approver (Simotwo)")
		self.assertEqual(place["job_family"], "Agriculture Production Supervisor")
		self.assertEqual(place["variant"], "Approver")
		self.assertEqual(place["scope"], "Simotwo")

		level = taxonomy.parse("Agriculture Production Supervisor-Approver (Restricted)")
		self.assertEqual(level["job_family"], "Agriculture Production Supervisor")
		self.assertIn("Restricted", level["variant"])
		self.assertEqual(level["scope"], "")

	def test_seniority_words_stay_in_the_job_family(self):
		"""Supervisor and Manager are the job, not a modifier of it."""
		for name, family in (
			("Agriculture Supervisor", "Agriculture Supervisor"),
			("Payroll Manager Ravine", "Payroll Manager"),
			("Section Head", "Section Head"),
			("HR Clerk", "HR Clerk"),
		):
			self.assertEqual(taxonomy.parse(name)["job_family"], family, name)

	def test_word_order_survives_extraction(self):
		"""Removing a token from the middle must not reorder the remainder."""
		self.assertEqual(
			taxonomy.parse("Agriculture Production Supervisor That Can Purchase")["job_family"],
			"Agriculture Production Supervisor",
		)

	def test_case_is_normalised_without_mangling_acronyms(self):
		self.assertEqual(taxonomy.parse("WESTWOOD DAIRY STAFF")["job_family"], "Dairy Staff")
		self.assertEqual(taxonomy.parse("scout")["job_family"], "Scout")
		self.assertEqual(taxonomy.parse("KAITET ACCOUNTING USER - VERIFIER")["job_family"], "Accounting")
		self.assertEqual(taxonomy.parse("Intake QC (Restricted)")["job_family"], "Intake QC")
		# HOD is a variant marker, so `HOD HR` leaves HR as the family.
		self.assertEqual(taxonomy.parse("HOD HR")["job_family"], "HR")
		self.assertEqual(taxonomy.parse("HOD HR")["variant"], "HOD")

	def test_longest_scope_token_wins(self):
		self.assertEqual(taxonomy.parse("Security Head - Karen Roses")["scope"], "Karen Roses")
		self.assertEqual(taxonomy.parse("General Manager-Kaitet LTD")["scope"], "Kaitet LTD")

	def test_two_scope_levels_are_both_kept(self):
		"""Company and farm are both real; neither should be discarded."""
		self.assertEqual(taxonomy.parse("Farm Manager Kaitet (Valle)")["scope"], "Kaitet - Valle")

	def test_trailing_user_is_dropped_but_not_a_middle_one(self):
		self.assertEqual(taxonomy.parse("Accounts User")["job_family"], "Accounts")
		self.assertEqual(taxonomy.parse("Upande Team HR Users")["job_family"], "Upande Team HR")

	def test_canonical_name_joins_present_segments_only(self):
		self.assertEqual(
			taxonomy.canonical_name("Agriculture Production Supervisor-Approver (Simotwo)")[0],
			"Agriculture Production Supervisor | Approver | Simotwo",
		)
		self.assertEqual(taxonomy.canonical_name("Stores")[0], "Stores")
		self.assertEqual(taxonomy.canonical_name("Sales (Restricted)")[0], "Sales | Restricted")

	def test_naming_issues_are_flagged(self):
		self.assertIn("case_anomaly", taxonomy.parse("SCOUTING")["issues"])
		self.assertIn("inconsistent_separator", taxonomy.parse("Temporary -Mechanic")["issues"])
		self.assertIn("composite_name", taxonomy.parse("Stores/HR")["issues"])
		self.assertIn("conjunction_name", taxonomy.parse("General Manager + HR")["issues"])
		self.assertIn("multiple_variant", taxonomy.parse("X Approver Restricted")["issues"])

	def test_an_unparsable_name_yields_no_proposal(self):
		"""A blank cell asks for a human; a wrong string hides from one."""
		proposed, issues = taxonomy.canonical_name("Approver")

		self.assertEqual(proposed, "")
		self.assertIn("unparsed", issues)

	def test_temporary_is_a_variant_of_mechanic(self):
		parsed = taxonomy.parse("Temporary -Mechanic")

		self.assertEqual(parsed["job_family"], "Mechanic")
		self.assertEqual(parsed["variant"], "Temporary")
