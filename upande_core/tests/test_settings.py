# Copyright (c) 2026, ghost-mann and contributors
# For license information, please see license.txt

import frappe
from frappe.tests import IntegrationTestCase

from upande_core import settings


class TestUserAccessSettings(IntegrationTestCase):
	def test_defaults_match_the_kaitet_frame(self):
		"""An unsaved Single must still answer every accessor."""
		self.assertEqual(settings.scope_dimensions(), ["company", "branch"])
		self.assertEqual(settings.tie_break_rule(), "Tightest by permission count")
		self.assertEqual(settings.min_peers_high_confidence(), 5)
		self.assertEqual(settings.seed_mode(), "Seed from existing users")
		self.assertEqual(settings.module_profile_strategy(), "Derive from Role Profile")
		self.assertEqual(settings.never_block_modules(), [])
		self.assertEqual(settings.naming_pattern(), "{role_profile}")
		self.assertEqual(settings.delegate_role(), "User Manager")
		self.assertFalse(settings.allow_multiple_profiles())
		self.assertTrue(settings.require_employee_link())

	def test_privileged_doctypes_defaults_cover_the_escalation_surface(self):
		"""Anything that can rewrite permissions must be on the list."""
		privileged = set(settings.privileged_doctypes())

		for doctype in (
			"User",
			"Role",
			"Role Profile",
			"Module Profile",
			"Custom DocPerm",
			"DocPerm",
			"Property Setter",
		):
			self.assertIn(doctype, privileged)

	def test_scope_dimensions_respects_saved_checkboxes(self):
		doc = frappe.get_single("User Access Settings")
		doc.use_company = 1
		doc.use_branch = 0
		doc.use_department = 1
		doc.use_grade = 0
		doc.save(ignore_permissions=True)
		frappe.clear_document_cache("User Access Settings")

		# Order is fixed most-general to most-specific, not checkbox order.
		self.assertEqual(settings.scope_dimensions(), ["company", "department"])

	def test_min_peers_falls_back_when_set_to_zero(self):
		"""A zero threshold would mark every unprecedented row High."""
		doc = frappe.get_single("User Access Settings")
		doc.min_peers_high_confidence = 0
		doc.save(ignore_permissions=True)
		frappe.clear_document_cache("User Access Settings")

		self.assertEqual(settings.min_peers_high_confidence(), 5)
