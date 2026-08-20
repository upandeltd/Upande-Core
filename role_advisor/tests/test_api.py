# Copyright (c) 2026, Upande and contributors
# For license information, please see license.txt

"""Tests for the Role Advisor resolver.

The four scenarios from the brief, plus the two Gap kinds and a parity guard on
the batched permission query. All of them run against role_advisor.demo_data, so
the console shows exactly what these tests assert.
"""

import frappe
from frappe.permissions import get_all_perms
from frappe.tests import IntegrationTestCase

from role_advisor import api
from role_advisor.demo_data import DEMO_ROLES, DEMO_USERS, seed

CLERK = "ra.demo.clerk@example.com"
NEWJOINER = "ra.demo.newjoiner@example.com"


class TestRoleAdvisorAPI(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		seed()

	def setUp(self):
		# The index is cached for ten minutes; tests must never race a stale one.
		api.clear_capability_index()
		frappe.set_user("Administrator")
		self._reset_demo_users()

	def _reset_demo_users(self):
		"""Return the demo users to their seeded profiles before each test.

		IntegrationTestCase rolls back once at class cleanup, not per test, so
		profile changes made by one test leak into the next. Resetting here keeps
		every test independent of the order they happen to run in - without it,
		a test that applies a suggestion silently changes what "Covered" means
		for whichever test runs next.
		"""
		for email, profiles in DEMO_USERS.items():
			user = frappe.get_doc("User", email)
			api.set_user_role_profiles(user, list(profiles))
			user.save(ignore_permissions=True)

	def tearDown(self):
		frappe.set_user("Administrator")

	# -- Scenario 1 -------------------------------------------------------

	def test_already_covered_by_current_profile(self):
		"""RA Harvest Basic already grants create on RA Demo Harvest Entry."""
		result = api.resolve_transactions(CLERK, ["Record Harvest Entry"])

		self.assertEqual(result["status"], api.STATUS_COVERED)
		self.assertIsNone(result["suggested_profile"])
		self.assertEqual(result["extra_perms"], [])
		self.assertEqual(result["unmet_requirements"], [])
		self.assertEqual(result["current_profiles"], ["RA Harvest Basic"])

	# -- Scenario 2 -------------------------------------------------------

	def test_fit_found_switches_to_tighter_existing_profile(self):
		"""submit on Harvest Entry needs a profile the clerk does not hold."""
		result = api.resolve_transactions(CLERK, ["Submit Harvest Entry"])

		self.assertEqual(result["status"], api.STATUS_FIT_FOUND)
		self.assertEqual(result["suggested_profile"], "RA Harvest Supervisor")

		# RA Operations Broad also covers it; the tighter profile must win.
		self.assertNotEqual(result["suggested_profile"], "RA Operations Broad")

		# The over-grant diff is the tradeoff shown to the admin. RA Harvest
		# Supervisor holds 7 permissions and 1 was requested, so 6 are extra.
		self.assertEqual(len(result["extra_perms"]), 6)
		extra = {(perm["doctype"], perm["perm"]) for perm in result["extra_perms"]}
		self.assertIn(("RA Demo Pick List", "submit"), extra)
		self.assertNotIn(("RA Demo Harvest Entry", "submit"), extra)

	# -- Scenario 3 -------------------------------------------------------

	def test_genuine_gap_needs_a_new_role(self):
		"""No role on the site grants delete on RA Demo Pick List."""
		result = api.resolve_transactions(CLERK, ["Delete Order Pick List"])

		self.assertEqual(result["status"], api.STATUS_GAP_NEW_ROLE)
		self.assertIsNone(result["suggested_profile"])
		self.assertEqual(len(result["unmet_requirements"]), 1)

		unmet = result["unmet_requirements"][0]
		self.assertEqual(unmet["doctype"], "RA Demo Pick List")
		self.assertEqual(unmet["perm"], "delete")
		self.assertFalse(unmet["granted_by_any_role"])

	# -- Scenario 4 -------------------------------------------------------

	def test_tightest_fit_picks_the_smaller_of_two_candidates(self):
		"""RA Finance Only (4 perms) and RA Operations Broad (14) both qualify."""
		index = api.build_capability_index()

		# Guard the premise: if either profile stopped covering the request, the
		# assertion below would pass for the wrong reason.
		for profile in ("RA Finance Only", "RA Operations Broad"):
			self.assertIn("submit", index[profile]["RA Demo Payment Voucher"])

		self.assertLess(
			api._total_perm_count(index["RA Finance Only"]),
			api._total_perm_count(index["RA Operations Broad"]),
		)

		result = api.resolve_transactions(CLERK, ["Approve Payment Voucher"])

		self.assertEqual(result["status"], api.STATUS_FIT_FOUND)
		self.assertEqual(result["suggested_profile"], "RA Finance Only")

	# -- The other Gap kind ----------------------------------------------

	def test_gap_needing_only_a_new_profile(self):
		"""RA Payment Auditor grants cancel, but no profile bundles that role."""
		result = api.resolve_transactions(CLERK, ["Cancel Payment Voucher"])

		self.assertEqual(result["status"], api.STATUS_GAP_NEW_PROFILE)
		self.assertEqual(len(result["unmet_requirements"]), 1)

		unmet = result["unmet_requirements"][0]
		self.assertEqual(unmet["perm"], "cancel")
		# The distinction that separates the two Gap statuses.
		self.assertTrue(unmet["granted_by_any_role"])

	# -- Capability index -------------------------------------------------

	def test_batched_perm_query_matches_core_get_all_perms(self):
		"""_perm_rows_for_roles must agree with frappe.permissions.get_all_perms.

		The batched query exists only for speed. If core changes how Custom
		DocPerm overrides standard DocPerm, this fails rather than silently
		producing wrong advice.
		"""
		for role in DEMO_ROLES:
			with self.subTest(role=role):
				batched = api._capabilities_from_rows(api._perm_rows_for_roles([role]))
				core = api._capabilities_from_rows(get_all_perms(role))
				self.assertEqual(batched.get(role, {}), core.get(role, {}))

	def test_index_excludes_higher_permlevels_and_if_owner(self):
		"""permlevel > 0 and if_owner rows are field/ownership scoped, not grants."""
		rows = [
			{"role": "R", "parent": "DT", "permlevel": 1, "if_owner": 0, "write": 1},
			{"role": "R", "parent": "DT", "permlevel": 0, "if_owner": 1, "delete": 1},
			{"role": "R", "parent": "DT", "permlevel": 0, "if_owner": 0, "read": 1},
		]

		self.assertEqual(api._capabilities_from_rows(rows), {"R": {"DT": {"read"}}})

	def test_index_is_served_from_cache_on_the_second_call(self):
		first = api.build_capability_index()

		# Make a recompute impossible, so a correct result can only have come
		# from the cache. Asserting on behaviour rather than on query counts
		# keeps this independent of how many queries the scan happens to need.
		def _explode():
			raise AssertionError("recomputed a cached capability index")

		original = api._compute_capability_index
		api._compute_capability_index = _explode
		try:
			self.assertEqual(api.build_capability_index(), first)
		finally:
			api._compute_capability_index = original

	def test_force_rebuilds_the_index(self):
		api.build_capability_index()

		rebuilt = api.build_capability_index(force=True)
		self.assertIn("RA Harvest Basic", rebuilt)

	# -- Multiple profiles ------------------------------------------------

	def test_coverage_is_the_union_of_all_assigned_profiles(self):
		"""No single held profile covers both; together they do."""
		user = frappe.get_doc("User", NEWJOINER)
		api.set_user_role_profiles(user, ["RA Harvest Basic", "RA Finance Only"])
		user.save(ignore_permissions=True)

		result = api.resolve_transactions(
			NEWJOINER, ["Record Harvest Entry", "Approve Payment Voucher"]
		)

		self.assertEqual(result["status"], api.STATUS_COVERED)
		self.assertEqual(result["current_profiles"], ["RA Harvest Basic", "RA Finance Only"])

	# -- Audit trail ------------------------------------------------------

	def test_every_outcome_is_logged(self):
		cases = {
			"Record Harvest Entry": api.STATUS_COVERED,
			"Submit Harvest Entry": api.STATUS_FIT_FOUND,
			"Delete Order Pick List": api.STATUS_GAP_NEW_ROLE,
			"Cancel Payment Voucher": api.STATUS_GAP_NEW_PROFILE,
		}

		for transaction, expected_status in cases.items():
			with self.subTest(transaction=transaction):
				result = api.resolve_transactions(CLERK, [transaction])

				log = frappe.get_doc("Access Request Log", result["access_request_log"])
				self.assertEqual(log.resolution_status, expected_status)
				self.assertEqual(log.user, CLERK)
				self.assertEqual(log.current_role_profile, "RA Harvest Basic")
				self.assertEqual(
					[row.transaction for row in log.requested_transactions], [transaction]
				)
				self.assertTrue(log.requested_on)

	def test_log_records_the_over_grant_summary(self):
		result = api.resolve_transactions(CLERK, ["Submit Harvest Entry"])
		log = frappe.get_doc("Access Request Log", result["access_request_log"])

		self.assertIn("RA Demo Pick List", log.extra_perms_granted)
		self.assertFalse(log.unmet_requirements)

	# -- apply_suggestion -------------------------------------------------

	def test_apply_suggestion_replaces_existing_profiles(self):
		result = api.resolve_transactions(CLERK, ["Submit Harvest Entry"])

		applied = api.apply_suggestion(result["access_request_log"])

		self.assertTrue(applied["applied"])
		self.assertEqual(applied["role_profile"], "RA Harvest Supervisor")
		self.assertEqual(applied["replaced_profiles"], ["RA Harvest Basic"])

		# Replaced, not appended - the redundant broader profile must be gone.
		self.assertEqual(api.get_user_role_profiles(CLERK), ["RA Harvest Supervisor"])

		log = frappe.get_doc("Access Request Log", result["access_request_log"])
		self.assertEqual(log.decided_by, "Administrator")
		self.assertIn("RA Harvest Basic", log.decision_notes)

	def test_apply_suggestion_does_not_resurrect_the_replaced_profile(self):
		"""The deprecated role_profile_name mirror must not re-append it.

		User.sync_role_profile_name persists role_profiles[0] on every save. On
		the next save, User.move_role_profile_name_to_role_profiles appends that
		stale value back as an extra profile unless it has been cleared - which
		would quietly turn apply_suggestion's replace into an append.
		"""
		result = api.resolve_transactions(CLERK, ["Submit Harvest Entry"])
		api.apply_suggestion(result["access_request_log"])

		self.assertEqual(api.get_user_role_profiles(CLERK), ["RA Harvest Supervisor"])
		self.assertNotIn("RA Harvest Basic", api.get_user_role_profiles(CLERK))
		self.assertEqual(
			frappe.db.get_value("User", CLERK, "role_profile_name"), "RA Harvest Supervisor"
		)

	def test_apply_suggestion_requires_system_manager(self):
		result = api.resolve_transactions(CLERK, ["Submit Harvest Entry"])

		frappe.set_user(NEWJOINER)
		with self.assertRaises(frappe.PermissionError):
			api.apply_suggestion(result["access_request_log"])

	def test_apply_suggestion_refuses_a_gap(self):
		result = api.resolve_transactions(CLERK, ["Delete Order Pick List"])

		with self.assertRaises(frappe.ValidationError):
			api.apply_suggestion(result["access_request_log"])

	def test_apply_suggestion_is_not_repeatable(self):
		result = api.resolve_transactions(CLERK, ["Submit Harvest Entry"])
		api.apply_suggestion(result["access_request_log"])

		with self.assertRaises(frappe.ValidationError):
			api.apply_suggestion(result["access_request_log"])

	# -- Endpoints --------------------------------------------------------

	def test_get_transaction_catalog_returns_picker_payload(self):
		catalog = api.get_transaction_catalog()
		by_name = {row["name"]: row for row in catalog}

		self.assertIn("Submit Order Pick List", by_name)
		row = by_name["Submit Order Pick List"]
		self.assertEqual(row["reference_doctype"], "RA Demo Pick List")
		self.assertEqual(row["required_perm"], "submit")
		self.assertEqual(row["module"], "Warehouse")

	def test_resolve_access_accepts_a_json_encoded_list(self):
		"""frappe.call sends arrays as JSON strings."""
		result = api.resolve_access(CLERK, frappe.as_json(["Record Harvest Entry"]))

		self.assertEqual(result["status"], api.STATUS_COVERED)

	def test_unknown_transaction_is_rejected(self):
		with self.assertRaises(frappe.DoesNotExistError):
			api.resolve_transactions(CLERK, ["No Such Transaction"])

	def test_empty_request_is_rejected(self):
		with self.assertRaises(frappe.ValidationError):
			api.resolve_transactions(CLERK, [])
