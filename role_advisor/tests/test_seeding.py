# Copyright (c) 2026, ghost-mann and contributors
# For license information, please see license.txt

import frappe
from frappe.tests import IntegrationTestCase

from role_advisor import capability, seeding
from role_advisor.role_advisor.doctype.designation_access_map.designation_access_map import (
	CONFIDENCE_HIGH,
	CONFIDENCE_LOW,
	CONFIDENCE_MEDIUM,
)
from role_advisor.tests.fixtures import (
	INNOCUOUS_DOCTYPE,
	ensure_profile,
	ensure_role,
	grant,
)

BROAD_ROLE = "_RA Seed Broad Role"
TIGHT_ROLE = "_RA Seed Tight Role"
BROAD_PROFILE = "_RA Seed Broad Profile"
TIGHT_PROFILE = "_RA Seed Tight Profile"


class TestSeedClassification(IntegrationTestCase):
	"""`classify` is the whole judgement, so it is tested in isolation."""

	def setUp(self):
		grant(ensure_role(BROAD_ROLE), INNOCUOUS_DOCTYPE, "read", "write", "create", "delete")
		grant(ensure_role(TIGHT_ROLE), INNOCUOUS_DOCTYPE, "read")
		ensure_profile(BROAD_PROFILE, BROAD_ROLE)
		ensure_profile(TIGHT_PROFILE, TIGHT_ROLE)
		capability.clear_capability_index()

	def tearDown(self):
		capability.clear_capability_index()

	def test_unanimous_and_well_supported_is_high(self):
		result = seeding.classify({TIGHT_PROFILE: 29})

		self.assertEqual(result["confidence"], CONFIDENCE_HIGH)
		self.assertEqual(result["profile"], TIGHT_PROFILE)
		self.assertFalse(result["flagged"])

	def test_a_dominant_majority_is_still_high(self):
		"""29 of 31 is agreement, not a split."""
		result = seeding.classify({TIGHT_PROFILE: 29, BROAD_PROFILE: 2})

		self.assertEqual(result["confidence"], CONFIDENCE_HIGH)

	def test_a_single_peer_is_low(self):
		result = seeding.classify({TIGHT_PROFILE: 1})

		self.assertEqual(result["confidence"], CONFIDENCE_LOW)
		self.assertTrue(result["flagged"], "low confidence must never auto-apply")

	def test_an_even_split_is_medium(self):
		result = seeding.classify({TIGHT_PROFILE: 3, BROAD_PROFILE: 3})

		self.assertEqual(result["confidence"], CONFIDENCE_MEDIUM)
		self.assertTrue(result["flagged"])

	def test_a_lone_outlier_cannot_win_on_tightness(self):
		"""Tightest-wins must not let one stray assignment beat 29 peers."""
		result = seeding.classify({BROAD_PROFILE: 29, TIGHT_PROFILE: 1})

		self.assertEqual(result["profile"], BROAD_PROFILE)

	def test_disagreement_between_majority_and_tightest_is_flagged(self):
		"""The Grader case: majority picks the broader profile."""
		result = seeding.classify({BROAD_PROFILE: 4, TIGHT_PROFILE: 3})

		self.assertEqual(result["majority"], BROAD_PROFILE)
		self.assertEqual(result["tightest"], TIGHT_PROFILE)
		self.assertTrue(result["flagged"])

	def test_evidence_names_the_counts(self):
		result = seeding.classify({TIGHT_PROFILE: 29, BROAD_PROFILE: 2})

		self.assertIn("29", result["evidence"])
		self.assertIn(TIGHT_PROFILE, result["evidence"])

	def test_no_peers_yields_nothing(self):
		self.assertIsNone(seeding.classify({}))


class TestSeedRun(IntegrationTestCase):
	def tearDown(self):
		doc = frappe.get_single("User Access Settings")
		doc.seed_mode = "Seed from existing users"
		doc.save(ignore_permissions=True)
		frappe.clear_document_cache("User Access Settings")

	def test_dry_run_writes_nothing(self):
		before = frappe.db.count("Designation Access Map")

		rows = seeding.seed(dry_run=True)

		self.assertEqual(frappe.db.count("Designation Access Map"), before)
		self.assertIsInstance(rows, list)

	def test_observe_assignments_keys_on_designation_and_scope(self):
		observed = seeding.observe_assignments()

		self.assertTrue(observed, "the site has assignable users; expected rows")
		key = next(iter(observed))
		# (designation, company, branch) with the default two dimensions.
		self.assertEqual(len(key), 3)

	def test_author_from_intent_mode_seeds_nothing(self):
		doc = frappe.get_single("User Access Settings")
		doc.seed_mode = "Author from intent"
		doc.save(ignore_permissions=True)
		frappe.clear_document_cache("User Access Settings")

		self.assertEqual(seeding.seed(dry_run=True), [])
