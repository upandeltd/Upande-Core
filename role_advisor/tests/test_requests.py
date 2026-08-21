# Copyright (c) 2026, ghost-mann and contributors
# For license information, please see license.txt

import frappe
from frappe.tests import IntegrationTestCase

from role_advisor import capability, delegation, requests
from role_advisor.tests import fixtures
from role_advisor.tests.fixtures import (
	INNOCUOUS_DOCTYPE,
	ensure_profile,
	ensure_role,
	grant,
)
from role_advisor.tests.test_delegation import (
	ADMIN,
	ALLOWED_PROFILE,
	IN_SCOPE,
	OUT_OF_SCOPE,
	build_fixture,
)

BUNDLE = "_RA Test Bundle"


class TestRequests(IntegrationTestCase):
	def setUp(self):
		build_fixture(self)
		# A tiny profile that grants exactly one thing, so "tightest fit" has an
		# unambiguous right answer.
		grant(ensure_role("_RA Req Role"), INNOCUOUS_DOCTYPE, "read")
		ensure_profile("_RA Req Profile", "_RA Req Role")
		capability.clear_capability_index()

		target = frappe.get_doc("User", IN_SCOPE)
		capability.set_user_role_profiles(target, [])
		target.save(ignore_permissions=True)

	def tearDown(self):
		frappe.set_user("Administrator")
		delegation.clear_cache()
		capability.clear_capability_index()

	# --------------------------------------------------------------- search

	def test_documents_are_searched_directly_with_no_catalogue(self):
		"""The unit is the doctype, so nothing has to be authored first."""
		rows = requests.search_documents("user", 20)

		self.assertTrue(rows)
		self.assertIn("User", [row["name"] for row in rows])

	def test_search_excludes_what_cannot_be_granted(self):
		for row in requests.search_documents("", 200):
			meta = frappe.db.get_value(
				"DocType", row["name"], ["istable", "issingle"], as_dict=True
			)
			self.assertFalse(meta.istable)
			self.assertFalse(meta.issingle)

	def test_an_exact_prefix_ranks_first(self):
		rows = requests.search_documents("Role Profile", 10)

		self.assertEqual(rows[0]["name"], "Role Profile")

	def test_submit_is_offered_only_on_submittable_documents(self):
		self.assertIn("submit", requests.rights_for("Leave Application"))
		self.assertNotIn("submit", requests.rights_for(INNOCUOUS_DOCTYPE))

	# ------------------------------------------------------------- resolving

	def test_a_covered_request_recommends_nothing(self):
		frappe.get_doc("User", IN_SCOPE)
		target = frappe.get_doc("User", IN_SCOPE)
		capability.set_user_role_profiles(target, [ALLOWED_PROFILE])
		target.save(ignore_permissions=True)

		verdict = requests.resolve(IN_SCOPE, [{"doctype": INNOCUOUS_DOCTYPE, "right": "read"}])

		self.assertEqual(verdict["resolution"], requests.COVERED)
		self.assertIsNone(verdict["profile"])

	def test_the_tightest_covering_profile_wins(self):
		"""Several profiles may cover the ask; the smallest grant should win."""
		verdict = requests.resolve(IN_SCOPE, [{"doctype": INNOCUOUS_DOCTYPE, "right": "read"}])

		self.assertEqual(verdict["resolution"], requests.FIT_FOUND)
		index = capability.build_capability_index()
		chosen = capability.total_perm_count(index[verdict["profile"]])
		for alternative in verdict["alternatives"]:
			self.assertLessEqual(chosen, capability.total_perm_count(index[alternative]))

	def test_over_grant_is_reported_so_the_cost_is_visible(self):
		verdict = requests.resolve(IN_SCOPE, [{"doctype": INNOCUOUS_DOCTYPE, "right": "read"}])

		self.assertIsInstance(verdict["over_grant"], list)
		for line in verdict["over_grant"]:
			self.assertNotIn(f"{INNOCUOUS_DOCTYPE}: read", line)

	def test_an_ungrantable_right_is_a_new_role_gap(self):
		"""Nobody may delete an audit log, so no profile can ever cover it."""
		verdict = requests.resolve(
			IN_SCOPE, [{"doctype": "Access Assignment Log", "right": "delete"}]
		)

		self.assertEqual(verdict["resolution"], requests.GAP_ROLE)
		self.assertTrue(verdict["unreachable"])

	def test_duplicate_lines_collapse(self):
		verdict = requests.resolve(
			IN_SCOPE,
			[
				{"doctype": INNOCUOUS_DOCTYPE, "right": "read"},
				{"doctype": INNOCUOUS_DOCTYPE, "right": "read"},
			],
		)

		self.assertEqual(len(verdict["requirements"]), 1)

	def test_a_child_table_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			requests.resolve(IN_SCOPE, [{"doctype": "Has Role", "right": "read"}])

	def test_an_unknown_right_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			requests.resolve(IN_SCOPE, [{"doctype": INNOCUOUS_DOCTYPE, "right": "approve"}])

	def test_an_empty_request_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			requests.resolve(IN_SCOPE, [])

	# ---------------------------------------------------------------- scope

	def test_anyone_may_resolve_for_themselves(self):
		frappe.set_user(IN_SCOPE)

		verdict = requests.resolve(IN_SCOPE, [{"doctype": INNOCUOUS_DOCTYPE, "right": "read"}])

		self.assertIn("resolution", verdict)

	def test_resolving_for_someone_else_needs_delegation(self):
		frappe.set_user(IN_SCOPE)

		with self.assertRaises(frappe.PermissionError):
			requests.resolve(OUT_OF_SCOPE, [{"doctype": INNOCUOUS_DOCTYPE, "right": "read"}])

	def test_a_delegate_may_resolve_within_scope_but_not_outside(self):
		frappe.set_user(ADMIN)
		delegation.clear_cache()

		requests.resolve(IN_SCOPE, [{"doctype": INNOCUOUS_DOCTYPE, "right": "read"}])

		with self.assertRaises(frappe.PermissionError):
			requests.resolve(OUT_OF_SCOPE, [{"doctype": INNOCUOUS_DOCTYPE, "right": "read"}])

	# -------------------------------------------------------------- request

	def test_a_request_records_the_requirement_not_a_catalogue_link(self):
		"""So rewording or deleting a bundle cannot change what was asked."""
		result = requests.submit_request(
			IN_SCOPE, [{"doctype": INNOCUOUS_DOCTYPE, "right": "read"}], reason="testing"
		)

		lines = frappe.get_all(
			"Access Request Line",
			filters={"parent": result["request"]},
			fields=["document_type", "right", "from_bundle"],
		)
		self.assertEqual(len(lines), 1)
		self.assertEqual(lines[0].document_type, INNOCUOUS_DOCTYPE)
		self.assertIsNone(lines[0].from_bundle)

	def test_fulfilling_goes_through_the_gated_assignment_path(self):
		"""The request flow gets no privileged shortcut of its own."""
		frappe.set_user(ADMIN)
		delegation.clear_cache()

		result = requests.submit_request(
			IN_SCOPE, [{"doctype": INNOCUOUS_DOCTYPE, "right": "read"}]
		)
		if result["resolution"] != requests.FIT_FOUND:
			self.skipTest("no covering profile on this site")

		# The recommendation may sit outside the delegate's allowlist, in which
		# case fulfilling must be refused - that is the gate working.
		frappe.db.set_value(
			"Access Request", result["request"], "recommended_profile", ALLOWED_PROFILE
		)
		outcome = requests.fulfil(result["request"])

		self.assertEqual(
			frappe.db.get_value("Access Request", result["request"], "status"), "Fulfilled"
		)
		self.assertTrue(outcome["log"])

	def test_fulfilling_a_profile_off_the_allowlist_is_refused(self):
		frappe.set_user(ADMIN)
		delegation.clear_cache()
		result = requests.submit_request(
			IN_SCOPE, [{"doctype": INNOCUOUS_DOCTYPE, "right": "read"}]
		)
		frappe.db.set_value(
			"Access Request", result["request"], "recommended_profile", "_RA Req Profile"
		)

		with self.assertRaises(frappe.PermissionError):
			requests.fulfil(result["request"])

	def test_raising_a_request_for_someone_else_needs_delegation(self):
		frappe.set_user(IN_SCOPE)

		with self.assertRaises(frappe.PermissionError):
			requests.submit_request(
				OUT_OF_SCOPE, [{"doctype": INNOCUOUS_DOCTYPE, "right": "read"}]
			)

	# ------------------------------------------------------------------ queue

	def test_the_queue_shows_open_and_resolved_requests(self):
		result = requests.submit_request(
			IN_SCOPE, [{"doctype": INNOCUOUS_DOCTYPE, "right": "write"}]
		)

		names = [row["name"] for row in requests.queue()]

		self.assertIn(result["request"], names)

	def test_a_system_manager_queue_is_not_narrowed_by_a_delegate_record(self):
		"""The record bounds a delegate; it must never hide requests from an
		administrator. This has been the same mistake three times: the guard,
		the request doctype, and the queue."""
		requests.submit_request(
			OUT_OF_SCOPE, [{"doctype": INNOCUOUS_DOCTYPE, "right": "write"}]
		)

		# Administrator holds a Delegated User Admin record in this fixture's
		# world; the out-of-scope request must still be visible.
		targets = [row["for_user"] for row in requests.queue()]

		self.assertIn(OUT_OF_SCOPE, targets)

	def test_a_delegate_queue_is_scoped(self):
		requests.submit_request(
			OUT_OF_SCOPE, [{"doctype": INNOCUOUS_DOCTYPE, "right": "write"}]
		)
		frappe.set_user(ADMIN)
		delegation.clear_cache()

		targets = [row["for_user"] for row in requests.queue()]

		self.assertNotIn(OUT_OF_SCOPE, targets)

	def test_the_queue_carries_what_was_asked_for(self):
		result = requests.submit_request(
			IN_SCOPE, [{"doctype": INNOCUOUS_DOCTYPE, "right": "write"}]
		)
		row = next(r for r in requests.queue() if r["name"] == result["request"])

		self.assertEqual(
			[(line["document_type"], line["right"]) for line in row["transactions"]],
			[(INNOCUOUS_DOCTYPE, "write")],
		)

	def test_refusing_records_a_reason(self):
		result = requests.submit_request(
			IN_SCOPE, [{"doctype": INNOCUOUS_DOCTYPE, "right": "write"}]
		)

		requests.refuse(result["request"], "not part of the job")

		doc = frappe.get_doc("Access Request", result["request"])
		self.assertEqual(doc.status, "Refused")
		self.assertIn("not part of the job", doc.resolution_notes)

	def test_a_refusal_with_no_note_still_says_so(self):
		result = requests.submit_request(
			IN_SCOPE, [{"doctype": INNOCUOUS_DOCTYPE, "right": "write"}]
		)

		requests.refuse(result["request"], "")

		self.assertIn(
			"without a note",
			frappe.db.get_value("Access Request", result["request"], "resolution_notes"),
		)

	def test_a_fulfilled_request_cannot_then_be_refused(self):
		result = requests.submit_request(
			IN_SCOPE, [{"doctype": INNOCUOUS_DOCTYPE, "right": "write"}]
		)
		frappe.db.set_value("Access Request", result["request"], "status", "Fulfilled")

		with self.assertRaises(frappe.ValidationError):
			requests.refuse(result["request"], "too late")

	def test_rechecking_answers_against_permissions_as_they_are_now(self):
		"""A request answered last week may answer differently today."""
		result = requests.submit_request(
			IN_SCOPE, [{"doctype": INNOCUOUS_DOCTYPE, "right": "write"}]
		)
		frappe.db.set_value(
			"Access Request", result["request"], "recommended_profile", None
		)

		again = requests.recheck(result["request"])

		self.assertEqual(
			frappe.db.get_value("Access Request", result["request"], "recommended_profile"),
			again.get("profile"),
		)

	def test_the_queue_is_administrators_only(self):
		frappe.set_user(IN_SCOPE)

		with self.assertRaises(frappe.PermissionError):
			requests.queue()

	# --------------------------------------------------------------- bundles

	def test_a_bundle_of_one_is_refused(self):
		"""A bundle restating a single document is pure indirection."""
		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc(
				{
					"doctype": "Access Transaction",
					"transaction_name": BUNDLE,
					"requirements": [{"document_type": INNOCUOUS_DOCTYPE, "right": "read"}],
				}
			).insert(ignore_permissions=True)

	def test_a_multi_document_bundle_expands_to_its_requirements(self):
		if frappe.db.exists("Access Transaction", BUNDLE):
			frappe.delete_doc("Access Transaction", BUNDLE, force=True)
		frappe.get_doc(
			{
				"doctype": "Access Transaction",
				"transaction_name": BUNDLE,
				"requirements": [
					{"document_type": INNOCUOUS_DOCTYPE, "right": "read"},
					{"document_type": "Note", "right": "create"},
				],
			}
		).insert(ignore_permissions=True)

		rows = requests.expand_bundle(BUNDLE)

		self.assertEqual(len(rows), 2)
		self.assertTrue(all(row["from_bundle"] == BUNDLE for row in rows))

	def test_the_bundle_catalogue_starts_empty(self):
		"""Bundles are authored by hand; nothing generates them."""
		generated = frappe.get_all(
			"Access Transaction", filters={"description": ("like", "%Drafted from%")}
		)

		self.assertFalse(generated)

	def test_the_covering_role_set_prefers_the_narrowest_role(self):
		"""A tie must not be broken by whatever the query returned first.

		A single missing permission is granted by dozens of roles, so ties are
		the normal case, and `System Manager` covers everything. Before the
		tie-break existed this function suggested it: 6,371 grants to satisfy an
		ask that one 21-grant role covered. The difference between a useful
		suggestion and a catastrophic one is entirely in the ordering.
		"""
		wide = fixtures.ensure_role("_RA Cover Wide Role")
		narrow = fixtures.ensure_role("_RA Cover Narrow Role")
		# Both cover the ask; the wide one also covers a great deal else.
		fixtures.grant(narrow, fixtures.INNOCUOUS_DOCTYPE, "read")
		fixtures.grant(wide, fixtures.INNOCUOUS_DOCTYPE, "read", "write", "create", "delete")
		capability.clear_capability_index()

		chosen = requests._roles_that_cover(
			[{"document_type": fixtures.INNOCUOUS_DOCTYPE, "right": "read"}]
		)

		self.assertEqual(chosen, [narrow], f"picked {chosen} over the narrower role")

	def test_the_covering_role_set_still_covers_everything_asked_for(self):
		"""Narrowest-first must not stop it being a cover."""
		role = fixtures.ensure_role("_RA Cover Both Role")
		fixtures.grant(role, fixtures.INNOCUOUS_DOCTYPE, "read", "write")
		capability.clear_capability_index()

		wanted = [
			{"document_type": fixtures.INNOCUOUS_DOCTYPE, "right": "read"},
			{"document_type": fixtures.INNOCUOUS_DOCTYPE, "right": "write"},
		]
		chosen = requests._roles_that_cover(wanted)

		covered = capability.capabilities_of_roles(chosen)
		self.assertFalse(
			requests._uncovered(covered, wanted), f"{chosen} does not cover the ask"
		)
