# Copyright (c) 2026, ghost-mann and contributors
# For license information, please see license.txt

"""Tests for adding access on top of what someone already has.

The two properties that matter, and that the rest of the app depends on:

  nothing is lost   - every role they held before is still held after
  nothing is spare  - the addition is the minimal covering role set, and an
                      identical profile is reused rather than duplicated
"""

import frappe
from frappe.tests import IntegrationTestCase

from role_advisor import capability, compose, delegation, settings
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

# Two innocuous doctypes so "held" and "asked for" can be kept apart.
HELD_DOCTYPE = INNOCUOUS_DOCTYPE
WANT_DOCTYPE = "ToDo"

READ_ROLE = "_RA Comp Read Role"
WRITE_ROLE = "_RA Comp Write Role"
BASE_PROFILE = "_RA Comp Base"
GRANTABLE_PROFILE = "_RA Comp Grantable"


class TestCompose(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		build_fixture(cls)

		# Two roles over the same doctype, so the ask needs exactly one of them
		# and the composition is predictable.
		grant(ensure_role(READ_ROLE), HELD_DOCTYPE, "read")
		grant(ensure_role(WRITE_ROLE), HELD_DOCTYPE, "read", "write")
		ensure_profile(BASE_PROFILE, READ_ROLE)
		capability.clear_capability_index()

	def setUp(self):
		frappe.set_user("Administrator")
		delegation.clear_cache()
		self._settings("allow_delegate_compose", 0)
		self._hold(IN_SCOPE, BASE_PROFILE)
		self._drop_composed()

	def tearDown(self):
		frappe.set_user("Administrator")
		delegation.clear_cache()
		self._drop_composed()

	# ------------------------------------------------------------- helpers

	def _settings(self, field, value):
		doc = frappe.get_single("User Access Settings")
		doc.set(field, value)
		doc.save(ignore_permissions=True)
		settings._settings.cache_clear() if hasattr(settings._settings, "cache_clear") else None

	def _hold(self, user, *profiles):
		doc = frappe.get_doc("User", user)
		capability.set_user_role_profiles(doc, list(profiles))
		doc.save(ignore_permissions=True)

	def _drop_composed(self):
		"""Remove the profiles this suite creates, wherever they are referenced.

		Per-class rollback is not enough here: `compose.apply` inserts a Role
		Profile, and a later class that rebuilds the capability index while that
		row is half-gone gets a cached index missing a profile it then reports as
		unknown - which fails closed and breaks an unrelated suite.
		"""
		composed = frappe.get_all(
			"Role Profile", filters={"name": ("like", f"{BASE_PROFILE}%+%")}, pluck="name"
		)
		for name in composed + [GRANTABLE_PROFILE, "_RA Comp Twin"]:
			if not frappe.db.exists("Role Profile", name):
				continue
			frappe.db.delete("User Role Profile", {"role_profile": name})
			frappe.db.delete("Delegated Role Profile", {"role_profile": name})
			frappe.db.delete("Has Role", {"parent": name, "parenttype": "Role Profile"})
			frappe.db.delete("Role Profile", {"name": name})
		capability.clear_capability_index()

	def _want_write(self):
		return [{"doctype": HELD_DOCTYPE, "right": "write"}]

	# -------------------------------------------------------------- preview

	def test_the_preview_keeps_everything_and_adds_the_covering_role(self):
		plan = compose.preview(IN_SCOPE, self._want_write())

		self.assertTrue(plan["allowed"], plan.get("refusal"))
		self.assertEqual(plan["holds"], [BASE_PROFILE])
		self.assertIn(READ_ROLE, plan["roles_after"])
		self.assertIn(WRITE_ROLE, plan["added_roles"])
		# The whole point: nothing is taken away.
		self.assertEqual(plan["roles_lost"], [])
		self.assertLessEqual(set(plan["held_roles"]), set(plan["roles_after"]))

	def test_the_preview_refuses_when_they_can_already_do_it(self):
		plan = compose.preview(IN_SCOPE, [{"doctype": HELD_DOCTYPE, "right": "read"}])

		self.assertFalse(plan["allowed"])
		self.assertIn("already covers", plan["refusal"])
		self.assertEqual(plan["added_roles"], [])

	def test_the_preview_names_the_profile_after_what_it_is(self):
		plan = compose.preview(IN_SCOPE, self._want_write())

		self.assertIn(BASE_PROFILE, plan["name"])
		self.assertIn(WRITE_ROLE, plan["name"])

	def test_the_proposed_name_is_stable_for_the_same_composition(self):
		first = compose.preview(IN_SCOPE, self._want_write())["name"]
		second = compose.preview(IN_SCOPE, self._want_write())["name"]

		self.assertEqual(first, second)

	def test_a_long_composition_counts_the_roles_rather_than_naming_them(self):
		many = [f"_RA Comp Bulk {n}" for n in range(12)]
		name = compose.propose_name(["A Very Long Base Profile Name Indeed"], many)

		self.assertIn("12 roles", name)
		self.assertLessEqual(len(name), compose.NAME_LIMIT)

	# ---------------------------------------------------------------- apply

	def test_applying_keeps_every_role_they_had(self):
		before = set(
			frappe.get_all(
				"Has Role", filters={"parent": IN_SCOPE, "parenttype": "User"}, pluck="role"
			)
		)

		result = compose.apply(IN_SCOPE, self._want_write())

		after = set(
			frappe.get_all(
				"Has Role", filters={"parent": IN_SCOPE, "parenttype": "User"}, pluck="role"
			)
		)
		self.assertTrue(result["created"])
		self.assertEqual(result["roles_lost"], [])
		self.assertTrue(before <= after, f"lost {sorted(before - after)}")
		self.assertIn(WRITE_ROLE, after)

	def test_applying_verifies_the_person_can_now_do_the_thing(self):
		result = compose.apply(IN_SCOPE, self._want_write())

		self.assertTrue(result["covered"])
		self.assertEqual(result["still_missing"], [])

	def test_the_composed_grant_lands_in_the_assignment_log(self):
		result = compose.apply(IN_SCOPE, self._want_write())

		row = frappe.get_doc("Access Assignment Log", result["log"])
		self.assertEqual(row.target_user, IN_SCOPE)
		self.assertEqual(row.profiles_after, result["composed"])
		self.assertIn(WRITE_ROLE, row.decision_notes)
		self.assertIn("Asked for", row.decision_notes)

	def test_a_note_is_kept_alongside_the_composition_trail(self):
		result = compose.apply(IN_SCOPE, self._want_write(), note="Covering month end.")

		notes = frappe.db.get_value("Access Assignment Log", result["log"], "decision_notes")
		self.assertIn("Covering month end.", notes)
		self.assertIn("Added", notes)

	def test_composing_the_same_thing_twice_reuses_the_profile(self):
		"""Otherwise the app would manufacture the duplicates it reports.

		Five people needing the same extra permission must not produce five
		byte-identical profiles - `identical_profiles` would flag them, and it
		would be right.
		"""
		first = compose.apply(IN_SCOPE, self._want_write())
		self.assertTrue(first["created"])

		self._hold(OUT_OF_SCOPE, BASE_PROFILE)
		second = compose.apply(OUT_OF_SCOPE, self._want_write())

		self.assertFalse(second["created"], "a second identical profile was created")
		self.assertEqual(second["composed"], first["composed"])

	def test_an_existing_profile_with_exactly_those_roles_is_reused(self):
		twin = ensure_profile("_RA Comp Twin", READ_ROLE, WRITE_ROLE)
		capability.clear_capability_index()
		try:
			plan = compose.preview(IN_SCOPE, self._want_write())
			self.assertEqual(plan["reuses"], twin)
			self.assertEqual(plan["name"], twin)
		finally:
			frappe.db.delete("Has Role", {"parent": twin, "parenttype": "Role Profile"})
			frappe.db.delete("Role Profile", {"name": twin})
			capability.clear_capability_index()

	def test_administrator_can_never_be_the_target(self):
		with self.assertRaises(frappe.PermissionError):
			compose.apply("Administrator", self._want_write())

	def test_an_ask_nothing_grants_is_refused_rather_than_half_applied(self):
		plan = compose.preview(
			IN_SCOPE, [{"doctype": HELD_DOCTYPE, "right": "read"}]
		)
		self.assertFalse(plan["allowed"])

		with self.assertRaises(frappe.PermissionError):
			compose.apply(IN_SCOPE, [{"doctype": HELD_DOCTYPE, "right": "read"}])

	# ------------------------------------------------------------- delegates

	def test_a_delegate_cannot_compose_while_the_setting_is_off(self):
		self._settings("allow_delegate_compose", 0)
		frappe.set_user(ADMIN)

		plan = compose.preview(IN_SCOPE, self._want_write())

		self.assertFalse(plan["allowed"])
		self.assertIn("switched off", plan["refusal"])
		with self.assertRaises(frappe.PermissionError):
			compose.apply(IN_SCOPE, self._want_write())

	def test_a_delegate_cannot_compose_from_a_role_outside_their_allowlist(self):
		"""The allowlist is the whole of a delegate's authority.

		If they could assemble a profile from any role on the site, the allowlist
		would be decorative.
		"""
		self._settings("allow_delegate_compose", 1)
		frappe.set_user(ADMIN)

		plan = compose.preview(IN_SCOPE, self._want_write())

		self.assertFalse(plan["allowed"])
		self.assertIn(WRITE_ROLE, plan["refusal"])
		with self.assertRaises(frappe.PermissionError):
			compose.apply(IN_SCOPE, self._want_write())

	def test_a_delegate_may_compose_from_roles_inside_their_allowlist(self):
		self._settings("allow_delegate_compose", 1)
		# Its own profile on the allowlist, rather than widening the shared
		# ALLOWED_PROFILE - four other suites assert against that one, and this
		# class's rollback does not undo a change another class already cached.
		extra = ensure_profile(GRANTABLE_PROFILE, WRITE_ROLE)
		record = frappe.get_doc("Delegated User Admin", ADMIN)
		record.append("allowed_role_profiles", {"role_profile": extra})
		record.save(ignore_permissions=True)
		capability.clear_capability_index()
		delegation.clear_cache()
		frappe.set_user(ADMIN)

		plan = compose.preview(IN_SCOPE, self._want_write())

		self.assertTrue(plan["allowed"], plan.get("refusal"))
		result = compose.apply(IN_SCOPE, self._want_write())
		self.assertIn(WRITE_ROLE, result["added_roles"])
		self.assertEqual(
			frappe.db.get_value("Access Assignment Log", result["log"], "actor"), ADMIN
		)

	def test_a_delegate_cannot_compose_for_someone_out_of_scope(self):
		self._settings("allow_delegate_compose", 1)
		frappe.set_user(ADMIN)

		with self.assertRaises(frappe.PermissionError):
			compose.preview(OUT_OF_SCOPE, self._want_write())

	def test_someone_with_neither_role_reaches_none_of_it(self):
		frappe.set_user(IN_SCOPE)

		with self.assertRaises(frappe.PermissionError):
			compose.preview(IN_SCOPE, self._want_write())
