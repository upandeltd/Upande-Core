# Copyright (c) 2026, ghost-mann and contributors
# For license information, please see license.txt

"""Tests for the anomaly and discrepancy checks.

Each check is exercised against a fixture planted in the real site, because the
checks read the site and a mocked Estate would only prove the mock works. The
assertions look for the fixture row inside the result rather than for an exact
count - this site has real anomalies of its own and a count assertion would
break the first time somebody fixed one.
"""

import frappe
from frappe.tests import IntegrationTestCase

from upande_core import anomalies, capability, settings
from upande_core.tests.fixtures import (
	INNOCUOUS_DOCTYPE,
	clear_map,
	ensure_designation,
	ensure_employee,
	ensure_profile,
	ensure_role,
	ensure_user,
	grant,
)

EMPTY_PROFILE = "_RA Anom Empty"
TIGHT_PROFILE = "_RA Anom Tight"
TWIN_PROFILE = "_RA Anom Twin"
WIDE_PROFILE = "_RA Anom Wide"

TIGHT_ROLE = "_RA Anom Tight Role"
WIDE_ROLE = "_RA Anom Wide Role"
STRAY_ROLE = "_RA Anom Stray Role"

HOLDER = "_ra_anom_holder@example.com"
OUTLIER = "_ra_anom_outlier@example.com"
NORM_A = "_ra_anom_norm_a@example.com"
NORM_B = "_ra_anom_norm_b@example.com"
DESIGNATION = "_RA Anom Picker"


def _by_kind(found, kind):
	for row in found:
		if row["kind"] == kind:
			return row
	return None


class TestAnomalies(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()

		cls.company = frappe.get_all("Company", pluck="name", limit=1)
		if not cls.company:
			raise cls.skipTest(cls, "site has no company")
		cls.company = cls.company[0]

		# An empty profile - no roles at all, so no grants at all.
		ensure_profile(EMPTY_PROFILE)

		# A tight profile and a byte-identical twin.
		grant(ensure_role(TIGHT_ROLE), INNOCUOUS_DOCTYPE, "read")
		ensure_profile(TIGHT_PROFILE, TIGHT_ROLE)
		ensure_profile(TWIN_PROFILE, TIGHT_ROLE)

		# A wide profile that strictly contains the tight one.
		grant(ensure_role(WIDE_ROLE), INNOCUOUS_DOCTYPE, "read", "write")
		ensure_profile(WIDE_PROFILE, TIGHT_ROLE, WIDE_ROLE)

		ensure_role(STRAY_ROLE)
		ensure_designation(DESIGNATION)
		capability.clear_capability_index()
		anomalies.clear_cache()

	def setUp(self):
		anomalies.clear_cache()
		clear_map(DESIGNATION)
		# The class rolls back once, not per test, so each test builds its own
		# world rather than inheriting the previous one's. Without this, a test
		# asserting "nobody holds the wide profile" passes or fails depending on
		# which test ran before it.
		for user in (HOLDER, OUTLIER, NORM_A, NORM_B):
			frappe.db.delete("Employee", {"user_id": user})
			if frappe.db.exists("User", user):
				doc = frappe.get_doc("User", user)
				doc.enabled = 1
				capability.set_user_role_profiles(doc, [])
				frappe.db.delete("Has Role", {"parent": user, "parenttype": "User"})
				doc.save(ignore_permissions=True)
		anomalies.clear_cache()

	def _hold(self, user: str, *profiles: str, enabled: int = 1):
		"""Put `user` on exactly `profiles`, bypassing the permission model."""
		ensure_user(user)
		doc = frappe.get_doc("User", user)
		doc.enabled = enabled
		capability.set_user_role_profiles(doc, list(profiles))
		doc.save(ignore_permissions=True)
		anomalies.clear_cache()
		return doc

	# ------------------------------------------------------------- anomalies

	def test_a_held_profile_that_grants_nothing_is_reported(self):
		self._hold(HOLDER, EMPTY_PROFILE)

		found = _by_kind(anomalies._run(), "empty_profile")

		self.assertIsNotNone(found)
		self.assertIn(EMPTY_PROFILE, [row["label"] for row in found["_all"]])

	def test_an_unheld_empty_profile_is_not_reported_as_empty(self):
		"""It is a dead profile, not an empty one - nobody is stuck."""
		self._hold(HOLDER, TIGHT_PROFILE)

		found = _by_kind(anomalies._run(), "empty_profile")

		labels = [row["label"] for row in (found or {"_all": []})["_all"]]
		self.assertNotIn(EMPTY_PROFILE, labels)

	def test_identical_profiles_are_reported_together(self):
		found = _by_kind(anomalies._run(), "identical_profiles")

		self.assertIsNotNone(found)
		pairs = [set(row["profiles"]) for row in found["_all"]]
		self.assertTrue(
			any({TIGHT_PROFILE, TWIN_PROFILE} <= pair for pair in pairs),
			f"{TIGHT_PROFILE} and {TWIN_PROFILE} grant the same and were not paired",
		)

	def test_a_nested_pair_is_reported_only_when_the_wider_one_is_held(self):
		self._hold(HOLDER, TIGHT_PROFILE)
		original = anomalies.MAX_PAIRS
		anomalies.MAX_PAIRS = 100_000
		try:
			before = _by_kind(anomalies._run(), "contained_profiles")
		finally:
			anomalies.MAX_PAIRS = original
		before_labels = [row["label"] for row in (before or {"_all": []})["_all"]]
		self.assertNotIn(f"{TIGHT_PROFILE} ⊂ {WIDE_PROFILE}", before_labels)

		self._hold(HOLDER, WIDE_PROFILE)
		# The check keeps only the pairs with the most holders, and a one-holder
		# fixture never places; lift the cap so the assertion is about the check
		# and not about how busy this site happens to be.
		original = anomalies.MAX_PAIRS
		anomalies.MAX_PAIRS = 100_000
		try:
			after = _by_kind(anomalies._run(), "contained_profiles")
		finally:
			anomalies.MAX_PAIRS = original

		self.assertIsNotNone(after)
		self.assertIn(
			f"{TIGHT_PROFILE} ⊂ {WIDE_PROFILE}",
			[row["label"] for row in after["_all"]],
		)

	def test_a_disabled_account_keeping_its_profile_is_reported(self):
		self._hold(HOLDER, TIGHT_PROFILE, enabled=0)

		found = _by_kind(anomalies._run(), "disabled_with_access")

		self.assertIsNotNone(found)
		self.assertIn(HOLDER, [row["users"][0] for row in found["_all"]])

	def test_an_enabled_account_with_no_profile_is_reported(self):
		# A role but no profile. Frappe demotes a user with no roles at all to
		# Website User, and a website user has no desk access to review, so the
		# check only looks at system users - which is what makes this fixture
		# the interesting case rather than the trivial one.
		self._hold(HOLDER)
		frappe.get_doc(
			{
				"doctype": "Has Role",
				"parent": HOLDER,
				"parenttype": "User",
				"parentfield": "roles",
				"role": STRAY_ROLE,
			}
		).insert(ignore_permissions=True)
		frappe.db.set_value("User", HOLDER, "user_type", "System User")
		anomalies.clear_cache()

		found = _by_kind(anomalies._run(), "no_profile")

		self.assertIsNotNone(found)
		self.assertIn(HOLDER, [row["users"][0] for row in found["_all"]])

	# ----------------------------------------------------------- discrepancies

	def test_one_designation_holding_two_different_profiles_is_a_discrepancy(self):
		for user in (NORM_A, NORM_B):
			self._hold(user, TIGHT_PROFILE)
			ensure_employee(user, self.company, DESIGNATION)
		self._hold(OUTLIER, WIDE_PROFILE)
		ensure_employee(OUTLIER, self.company, DESIGNATION)
		anomalies.clear_cache()

		found = _by_kind(anomalies._run(), "designation_split")

		self.assertIsNotNone(found)
		row = next(
			(r for r in found["_all"] if r["label"].startswith(DESIGNATION)), None
		)
		self.assertIsNotNone(row, "the split designation was not reported")
		self.assertTrue(found["discrepancy"])
		# The two agreeing accounts are the norm; the third is the exception.
		self.assertEqual(row["users"], [OUTLIER])
		self.assertIn("2 of 3", row["meta"])

	def test_a_group_of_two_is_not_evidence_of_a_norm(self):
		"""Two people doing the same job differently is a coin toss, not a finding."""
		self._hold(NORM_A, TIGHT_PROFILE)
		ensure_employee(NORM_A, self.company, DESIGNATION)
		self._hold(OUTLIER, WIDE_PROFILE)
		ensure_employee(OUTLIER, self.company, DESIGNATION)
		frappe.db.delete("Employee", {"user_id": NORM_B})
		anomalies.clear_cache()

		found = _by_kind(anomalies._run(), "designation_split")

		labels = [row["label"] for row in (found or {"_all": []})["_all"]]
		self.assertFalse(
			any(label.startswith(DESIGNATION) for label in labels),
			"a two-person group established a norm it cannot establish",
		)

	def test_a_role_no_held_profile_accounts_for_is_a_discrepancy(self):
		doc = self._hold(HOLDER, TIGHT_PROFILE)
		# Added after the profile prune, which is exactly how HRMS re-adds an
		# approver role in its User.validate doc_event.
		frappe.get_doc(
			{"doctype": "Has Role", "parent": HOLDER, "parenttype": "User", "parentfield": "roles", "role": STRAY_ROLE}
		).insert(ignore_permissions=True)
		anomalies.clear_cache()

		found = _by_kind(anomalies._run(), "role_drift")

		self.assertIsNotNone(found)
		row = next((r for r in found["_all"] if r["users"] == [HOLDER]), None)
		self.assertIsNotNone(row)
		self.assertIn(STRAY_ROLE, row["extra"])
		self.assertTrue(found["discrepancy"])

	def test_two_profiles_on_one_account_is_a_discrepancy(self):
		self._hold(HOLDER, TIGHT_PROFILE, WIDE_PROFILE)

		found = _by_kind(anomalies._run(), "multi_profile")

		self.assertIsNotNone(found)
		self.assertIn(HOLDER, [row["users"][0] for row in found["_all"]])
		self.assertTrue(found["discrepancy"])

	def test_an_account_contradicting_an_active_map_row_is_a_discrepancy(self):
		self._hold(HOLDER, TIGHT_PROFILE)
		ensure_employee(HOLDER, self.company, DESIGNATION)
		frappe.get_doc(
			{
				"doctype": "Designation Access Map",
				"designation": DESIGNATION,
				settings.map_fieldname("company"): self.company,
				"role_profile": WIDE_PROFILE,
				"is_active": 1,
			}
		).insert(ignore_permissions=True)
		anomalies.clear_cache()

		found = _by_kind(anomalies._run(), "map_conflict")

		self.assertIsNotNone(found)
		row = next((r for r in found["_all"] if r["users"] == [HOLDER]), None)
		self.assertIsNotNone(row, "policy and account disagreed and nothing said so")
		self.assertEqual(row["profile"], WIDE_PROFILE)

	def test_an_account_matching_the_map_is_not_a_conflict(self):
		self._hold(HOLDER, WIDE_PROFILE)
		ensure_employee(HOLDER, self.company, DESIGNATION)
		frappe.get_doc(
			{
				"doctype": "Designation Access Map",
				"designation": DESIGNATION,
				settings.map_fieldname("company"): self.company,
				"role_profile": WIDE_PROFILE,
				"is_active": 1,
			}
		).insert(ignore_permissions=True)
		anomalies.clear_cache()

		found = _by_kind(anomalies._run(), "map_conflict")

		users = [row["users"][0] for row in (found or {"_all": []})["_all"]]
		self.assertNotIn(HOLDER, users)

	def test_an_inactive_map_row_governs_nothing(self):
		self._hold(HOLDER, TIGHT_PROFILE)
		ensure_employee(HOLDER, self.company, DESIGNATION)
		frappe.get_doc(
			{
				"doctype": "Designation Access Map",
				"designation": DESIGNATION,
				settings.map_fieldname("company"): self.company,
				"role_profile": WIDE_PROFILE,
				"is_active": 0,
			}
		).insert(ignore_permissions=True)
		anomalies.clear_cache()

		found = _by_kind(anomalies._run(), "map_conflict")

		users = [row["users"][0] for row in (found or {"_all": []})["_all"]]
		self.assertNotIn(HOLDER, users)

	# -------------------------------------------------------------- machinery

	def test_discrepancies_outrank_anomalies_of_the_same_severity(self):
		found = anomalies._run()
		high = [row for row in found if row["severity"] == anomalies.SEVERITY_HIGH]
		if len({row["discrepancy"] for row in high}) < 2:
			self.skipTest("this site has no high-severity pair to order")

		last_discrepancy = max(
			index for index, row in enumerate(high) if row["discrepancy"]
		)
		first_anomaly = min(
			index for index, row in enumerate(high) if not row["discrepancy"]
		)
		self.assertLess(last_discrepancy, first_anomaly)

	def test_a_broken_check_does_not_blank_the_scan(self):
		def explode(estate):
			raise RuntimeError("deliberate")

		original = anomalies.CHECKS
		anomalies.CHECKS = (explode, *original)
		try:
			found = anomalies._run()
		finally:
			anomalies.CHECKS = original

		self.assertTrue(found, "one broken check emptied the whole scan")

	def test_the_scan_is_cached_and_the_cache_can_be_dropped(self):
		anomalies.clear_cache()
		first = anomalies.scan()
		self.assertIsNotNone(frappe.cache().get_value(anomalies.CACHE_KEY))

		# Same object shape returned without re-running: the marker survives.
		frappe.cache().set_value(anomalies.CACHE_KEY, [{"marker": True}])
		self.assertEqual(anomalies.scan(), [{"marker": True}])

		anomalies.clear_cache()
		self.assertIsNone(frappe.cache().get_value(anomalies.CACHE_KEY))
		self.assertNotEqual(anomalies.scan(), [{"marker": True}])
		self.assertTrue(first)

	def test_force_bypasses_the_cache(self):
		frappe.cache().set_value(anomalies.CACHE_KEY, [{"marker": True}])
		self.assertNotEqual(anomalies.scan(force=True), [{"marker": True}])

	def test_overview_does_not_ship_the_full_row_lists(self):
		self._hold(HOLDER, EMPTY_PROFILE)

		out = anomalies.overview()

		self.assertTrue(out["anomalies"])
		for row in out["anomalies"]:
			self.assertNotIn("_all", row)
			self.assertLessEqual(len(row["rows"]), anomalies.INLINE_ROWS)

	def test_detail_returns_every_row_not_just_the_sample(self):
		self._hold(HOLDER, EMPTY_PROFILE)
		card = _by_kind(anomalies._run(), "no_profile")
		if not card or not card["truncated"]:
			self.skipTest("no anomaly on this site is truncated")

		out = anomalies.detail("no_profile")

		self.assertEqual(len(out["rows"]), card["total_rows"])
		self.assertGreater(len(out["rows"]), anomalies.INLINE_ROWS)

	def test_a_capped_finding_reports_the_true_total(self):
		found = _by_kind(anomalies._run(), "contained_profiles")
		if not found:
			self.skipTest("this site has no nested profile pairs")

		self.assertGreaterEqual(found["count"], found["total_rows"])
		if found["count"] > anomalies.MAX_PAIRS:
			self.assertIn("Showing the", found["detail"])

	def test_detail_refuses_an_unknown_kind(self):
		with self.assertRaises(frappe.ValidationError):
			anomalies.detail("not_a_real_check")

	def test_every_finding_carries_what_the_card_needs(self):
		for row in anomalies._run():
			for key in ("kind", "severity", "title", "detail", "count", "rows", "discrepancy"):
				self.assertIn(key, row, f"{row.get('kind')} is missing {key}")
			self.assertIn(
				row["severity"],
				(anomalies.SEVERITY_HIGH, anomalies.SEVERITY_MODERATE, anomalies.SEVERITY_LOW),
			)
