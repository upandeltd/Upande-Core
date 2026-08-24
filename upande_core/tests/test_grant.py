# Copyright (c) 2026, ghost-mann and contributors
# For license information, please see license.txt

"""Tests for the grant workbench - module, document, action, profile.

The invariants that matter here are about what the picker is allowed to offer.
An interface that lets an administrator ask for something no role on the site
can grant, and only says so after they have built the whole request, is worse
than one that never offered it - so several of these are property tests over
the real catalogue rather than assertions about a fixture.
"""

import frappe
from frappe.tests import IntegrationTestCase

from upande_core import capability, delegation, grant, requests
from upande_core.tests.fixtures import INNOCUOUS_DOCTYPE, ensure_user
from upande_core.tests.test_delegation import (
	ADMIN,
	ALLOWED_PROFILE,
	IN_SCOPE,
	OUT_OF_SCOPE,
	UNSAFE_PROFILE,
	build_fixture,
)


class TestGrantCatalogue(IntegrationTestCase):
	"""What the picker offers. No writes."""

	def test_every_module_offered_contains_a_grantable_document(self):
		reachable = capability.site_wide_role_capabilities()

		for row in grant.modules():
			self.assertGreater(row["doctypes"], 0, f"{row['module']} offered nothing")

		# And a module whose documents nothing grants is absent entirely.
		offered = {row["module"] for row in grant.modules()}
		every = {
			row["module"]
			for row in frappe.get_all("DocType", fields=["module"], filters={"istable": 0})
			if row["module"]
		}
		for module in every - offered:
			docs = frappe.get_all(
				"DocType", filters={"module": module, "istable": 0, "issingle": 0}, pluck="name"
			)
			self.assertFalse(
				[doctype for doctype in docs if reachable.get(doctype)],
				f"{module} has a grantable document and was left out",
			)

	def test_no_offered_action_is_one_nothing_on_this_site_grants(self):
		"""The whole point of the catalogue: never offer the impossible."""
		reachable = capability.site_wide_role_capabilities()

		for row in grant.documents(txt="", limit=400):
			for right in row["rights"]:
				self.assertIn(
					right,
					reachable.get(row["doctype"], set()),
					f"{row['doctype']}: {right} is offered and nothing grants it",
				)

	def test_submit_is_never_offered_on_a_document_that_cannot_be_submitted(self):
		for row in grant.documents(txt="", limit=400):
			if row["submittable"]:
				continue
			for forbidden in ("submit", "cancel", "amend"):
				self.assertNotIn(
					forbidden,
					row["rights"],
					f"{row['doctype']} is not submittable and offered {forbidden}",
				)

	def test_the_implicit_rights_are_not_offered_as_choices(self):
		"""`export` and `report` ride along with every role; offering them is noise."""
		for row in grant.documents(module="Core", limit=100):
			self.assertFalse(
				set(row["rights"]) & grant.IMPLICIT_RIGHTS,
				f"{row['doctype']} offered an implicit right",
			)

	def test_filtering_by_module_returns_only_that_module(self):
		rows = grant.documents(module="Core", limit=100)
		self.assertTrue(rows)
		self.assertEqual({row["module"] for row in rows}, {"Core"})

	def test_searching_matches_a_document_by_name(self):
		rows = grant.documents(txt="ToDo", limit=20)
		self.assertIn(INNOCUOUS_DOCTYPE, [row["doctype"] for row in rows])


class TestGrantResolution(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		build_fixture(cls)

	def setUp(self):
		frappe.set_user("Administrator")
		delegation.clear_cache()

	def tearDown(self):
		frappe.set_user("Administrator")
		delegation.clear_cache()

	def _needs(self):
		return [{"doctype": INNOCUOUS_DOCTYPE, "right": "read"}]

	def test_the_recommended_profile_is_the_tightest_that_covers_the_ask(self):
		verdict = grant.resolve(OUT_OF_SCOPE, self._needs())

		if verdict["resolution"] != requests.FIT_FOUND:
			self.skipTest("nothing on this site covers the fixture ask")

		index = capability.build_capability_index()
		chosen = capability.total_perm_count(index[verdict["profile"]])
		for profile, caps in index.items():
			if not caps or "read" not in caps.get(INNOCUOUS_DOCTYPE, ()):
				continue
			self.assertLessEqual(
				chosen,
				capability.total_perm_count(caps),
				f"{profile} covers the same ask more tightly than {verdict['profile']}",
			)

	def test_a_system_manager_is_not_bounded_by_a_delegate_record(self):
		"""They hold write on User already; bounding them here buys nothing."""
		verdict = grant.resolve(OUT_OF_SCOPE, self._needs())

		self.assertNotIn("blocked_reason", verdict)
		if verdict.get("profile"):
			self.assertTrue(verdict["grantable"])

	def test_a_delegate_cannot_resolve_for_someone_out_of_scope(self):
		frappe.set_user(ADMIN)

		with self.assertRaises(frappe.PermissionError):
			grant.resolve(OUT_OF_SCOPE, self._needs())

	def test_a_fit_outside_a_delegates_allowlist_is_reported_as_not_grantable(self):
		"""The button has to be honest before the write, not after it.

		The ask is write on Role Profile, which the allowlisted profile cannot
		cover by construction - so whatever covers it is off the allowlist, and
		the verdict must say so rather than offering a Grant that would throw.
		"""
		frappe.set_user(ADMIN)

		verdict = grant.resolve(IN_SCOPE, [{"doctype": "Role Profile", "right": "write"}])

		if verdict["resolution"] != requests.FIT_FOUND:
			self.skipTest("nothing on this site grants write on Role Profile")

		self.assertNotEqual(verdict["profile"], ALLOWED_PROFILE)
		self.assertFalse(verdict["grantable"])
		self.assertIn(verdict["profile"], verdict["blocked_reason"])

	def test_nobody_can_be_resolved_for_administrator(self):
		with self.assertRaises(frappe.PermissionError):
			grant.resolve("Administrator", self._needs())

	def test_coverage_reports_nothing_for_an_account_with_no_profile(self):
		doc = frappe.get_doc("User", OUT_OF_SCOPE)
		capability.set_user_role_profiles(doc, [])
		doc.save(ignore_permissions=True)

		out = grant.coverage(OUT_OF_SCOPE)

		self.assertEqual(out["profiles"], [])
		self.assertEqual(out["doctypes"], 0)
		self.assertEqual(out["modules"], [])

	def test_coverage_groups_what_a_profile_grants_by_module(self):
		doc = frappe.get_doc("User", OUT_OF_SCOPE)
		capability.set_user_role_profiles(doc, [ALLOWED_PROFILE])
		doc.save(ignore_permissions=True)

		out = grant.coverage(OUT_OF_SCOPE)

		self.assertEqual(out["profiles"], [ALLOWED_PROFILE])
		self.assertGreater(out["doctypes"], 0)
		self.assertIn("Desk", [row["module"] for row in out["modules"]])


class TestGrantApply(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		build_fixture(cls)

	def setUp(self):
		frappe.set_user("Administrator")
		delegation.clear_cache()
		doc = frappe.get_doc("User", IN_SCOPE)
		capability.set_user_role_profiles(doc, [])
		doc.save(ignore_permissions=True)

	def tearDown(self):
		frappe.set_user("Administrator")
		delegation.clear_cache()

	def test_a_system_manager_can_grant_without_a_delegate_record(self):
		"""The gap that made the manage-access view unusable for its own owner.

		A System Manager could do this on the desk form all along; routing them
		through here is what gets the change into the assignment log.
		"""
		self.assertIsNone(delegation.acting_admin())

		result = grant.apply(IN_SCOPE, ALLOWED_PROFILE, needs=[
			{"doctype": INNOCUOUS_DOCTYPE, "right": "read"}
		])

		self.assertEqual(result["profiles"], [ALLOWED_PROFILE])
		self.assertTrue(result["covered"])
		self.assertEqual(result["still_missing"], [])
		self.assertTrue(frappe.db.exists("Access Assignment Log", result["log"]))

	def test_a_grant_that_does_not_cover_the_ask_says_so(self):
		result = grant.apply(IN_SCOPE, ALLOWED_PROFILE, needs=[
			{"doctype": INNOCUOUS_DOCTYPE, "right": "delete"}
		])

		self.assertFalse(result["covered"])
		self.assertIn(f"{INNOCUOUS_DOCTYPE}: delete", result["still_missing"])

	def test_a_grant_with_no_stated_need_is_not_reported_as_covered_or_not(self):
		result = grant.apply(IN_SCOPE, ALLOWED_PROFILE)

		self.assertIsNone(result["covered"])

	def test_a_note_lands_on_the_assignment_log(self):
		result = grant.apply(IN_SCOPE, ALLOWED_PROFILE, note="Standing in for the store keeper.")

		self.assertEqual(
			frappe.db.get_value("Access Assignment Log", result["log"], "decision_notes"),
			"Standing in for the store keeper.",
		)

	def test_administrator_can_never_be_the_target(self):
		with self.assertRaises(frappe.PermissionError):
			grant.apply("Administrator", ALLOWED_PROFILE)

	def test_a_delegate_cannot_grant_off_their_allowlist(self):
		frappe.set_user(ADMIN)

		with self.assertRaises(frappe.PermissionError):
			grant.apply(IN_SCOPE, UNSAFE_PROFILE)

	def test_a_delegate_cannot_grant_to_someone_out_of_scope(self):
		frappe.set_user(ADMIN)

		with self.assertRaises(frappe.PermissionError):
			grant.apply(OUT_OF_SCOPE, ALLOWED_PROFILE)

	def test_a_delegate_can_grant_inside_their_scope_and_allowlist(self):
		frappe.set_user(ADMIN)

		result = grant.apply(IN_SCOPE, ALLOWED_PROFILE)

		self.assertEqual(result["profiles"], [ALLOWED_PROFILE])
		self.assertEqual(
			frappe.db.get_value("Access Assignment Log", result["log"], "actor"), ADMIN
		)

	def test_someone_with_neither_role_reaches_none_of_it(self):
		user = ensure_user("_ra_grant_nobody@example.com")
		frappe.set_user(user)

		for call in (
			lambda: grant.modules(),
			lambda: grant.documents(module="Core"),
			lambda: grant.coverage(IN_SCOPE),
			lambda: grant.apply(IN_SCOPE, ALLOWED_PROFILE),
		):
			with self.assertRaises(frappe.PermissionError):
				call()
