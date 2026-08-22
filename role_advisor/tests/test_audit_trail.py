# Copyright (c) 2026, ghost-mann and contributors
# For license information, please see license.txt

import json

from frappe.tests import UnitTestCase

from role_advisor import audit_trail


class TestDeltaScalarFields(UnitTestCase):
	def test_v15_profile_change_becomes_before_and_after(self):
		data = json.dumps({"changed": [["role_profile_name", "Clerk", "Agriculture Supervisor"]]})

		delta = audit_trail._delta(data, "User")

		self.assertEqual(delta["profile_before"], "Clerk")
		self.assertEqual(delta["profile_after"], "Agriculture Supervisor")
		self.assertEqual(delta["fields"], [])

	def test_interesting_scalars_are_kept(self):
		data = json.dumps(
			{"changed": [["enabled", 1, 0], ["user_type", "System User", "Website User"]]}
		)

		delta = audit_trail._delta(data, "User")

		self.assertIn(("enabled", 1, 0), delta["fields"])
		self.assertIn(("user_type", "System User", "Website User"), delta["fields"])

	def test_ordinary_churn_is_dropped_entirely(self):
		data = json.dumps(
			{"changed": [["birth_date", "1990-01-01", "1990-01-02"], ["last_active", "a", "b"]]}
		)

		self.assertIsNone(audit_trail._delta(data, "User"))

	def test_malformed_json_is_none_not_an_exception(self):
		self.assertIsNone(audit_trail._delta("{not json", "User"))
		self.assertIsNone(audit_trail._delta("", "User"))
		self.assertIsNone(audit_trail._delta(None, "User"))

	def test_a_list_payload_is_rejected(self):
		self.assertIsNone(audit_trail._delta(json.dumps([1, 2, 3]), "User"))
