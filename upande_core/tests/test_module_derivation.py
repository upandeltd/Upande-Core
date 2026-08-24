# Copyright (c) 2026, ghost-mann and contributors
# For license information, please see license.txt

import frappe
from frappe.tests import IntegrationTestCase

from upande_core import capability, module_derivation
from upande_core.tests.fixtures import (
	INNOCUOUS_DOCTYPE,
	ensure_profile,
	ensure_role,
	grant,
)

ROLE = "_RA Module Role"
PROFILE = "_RA Module Profile"
EMPTY_PROFILE = "_RA Empty Profile"


class TestModuleDerivation(IntegrationTestCase):
	def setUp(self):
		grant(ensure_role(ROLE), INNOCUOUS_DOCTYPE, "read", "write")
		ensure_profile(PROFILE, ROLE)
		ensure_profile(EMPTY_PROFILE)
		capability.clear_capability_index()

		self.expected_module = frappe.db.get_value("DocType", INNOCUOUS_DOCTYPE, "module")

	def tearDown(self):
		capability.clear_capability_index()
		doc = frappe.get_single("User Access Settings")
		doc.module_profile_strategy = "Derive from Role Profile"
		doc.set("never_block_modules", [])
		doc.save(ignore_permissions=True)
		frappe.clear_document_cache("User Access Settings")

	def test_modules_are_derived_from_granted_doctypes(self):
		self.assertEqual(
			module_derivation.modules_for_profile(PROFILE), {self.expected_module}
		)

	def test_everything_else_is_blocked(self):
		blocked = module_derivation.blocked_for_profile(PROFILE)

		self.assertNotIn(self.expected_module, blocked)
		self.assertEqual(len(blocked), frappe.db.count("Module Def") - 1)

	def test_never_block_modules_are_honoured(self):
		doc = frappe.get_single("User Access Settings")
		doc.append("never_block_modules", {"module": "Core"})
		doc.save(ignore_permissions=True)
		frappe.clear_document_cache("User Access Settings")

		self.assertNotIn("Core", module_derivation.blocked_for_profile(PROFILE))

	def test_dry_run_writes_no_module_profiles(self):
		before = frappe.db.count("Module Profile")

		rows = module_derivation.derive(dry_run=True)

		self.assertEqual(frappe.db.count("Module Profile"), before)
		self.assertTrue(any(row["role_profile"] == PROFILE for row in rows))

	def test_drafts_are_name_prefixed(self):
		row = next(
			r
			for r in module_derivation.derive(dry_run=True)
			if r["role_profile"] == PROFILE
		)

		self.assertTrue(row["module_profile"].startswith(module_derivation.DRAFT_PREFIX))

	def test_manual_strategy_derives_nothing(self):
		doc = frappe.get_single("User Access Settings")
		doc.module_profile_strategy = "Manual"
		doc.save(ignore_permissions=True)
		frappe.clear_document_cache("User Access Settings")

		self.assertEqual(module_derivation.derive(dry_run=True), [])

	def test_a_profile_granting_nothing_is_skipped(self):
		"""Blocking all modules would leave an empty desk, not a tight one."""
		rows = {r["role_profile"] for r in module_derivation.derive(dry_run=True)}

		self.assertNotIn(EMPTY_PROFILE, rows)
