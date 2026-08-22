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


class TestDeltaChildTables(UnitTestCase):
	def _roles(self, added, removed):
		def rows(names):
			return [["roles", {"doctype": "Has Role", "role": name}] for name in names]

		return json.dumps({"added": rows(added), "removed": rows(removed)})

	def test_a_full_rewrite_that_cancels_is_dropped(self):
		"""One save rewrites every role row. Netting to nothing means nothing happened."""
		data = self._roles(["Employee", "Stock User"], ["Employee", "Stock User"])

		self.assertIsNone(audit_trail._delta(data, "User"))

	def test_only_the_real_delta_survives(self):
		data = self._roles(
			["Employee", "Stock User", "Expense Approver"], ["Employee", "Stock User"]
		)

		delta = audit_trail._delta(data, "User")

		self.assertEqual(delta["roles_gained"], ["Expense Approver"])
		self.assertEqual(delta["roles_lost"], [])

	def test_a_loss_is_reported(self):
		data = self._roles(["Employee"], ["Employee", "Stock User"])

		delta = audit_trail._delta(data, "User")

		self.assertEqual(delta["roles_gained"], [])
		self.assertEqual(delta["roles_lost"], ["Stock User"])

	def test_blocked_modules_are_tracked_separately_from_roles(self):
		data = json.dumps(
			{
				"added": [["block_modules", {"module": "Selling"}]],
				"removed": [["block_modules", {"module": "Buying"}]],
			}
		)

		delta = audit_trail._delta(data, "User")

		self.assertEqual(delta["modules_blocked"], ["Selling"])
		self.assertEqual(delta["modules_unblocked"], ["Buying"])

	def test_v16_child_profile_change_reads_like_the_v15_scalar(self):
		"""439 rows use the v15 shape and 52 the v16 one. Both must render alike."""
		data = json.dumps(
			{
				"added": [["role_profiles", {"role_profile": "Agriculture Supervisor"}]],
				"removed": [["role_profiles", {"role_profile": "Clerk"}]],
			}
		)

		delta = audit_trail._delta(data, "User")

		self.assertEqual(delta["profile_before"], "Clerk")
		self.assertEqual(delta["profile_after"], "Agriculture Supervisor")

	def test_a_payload_missing_its_value_key_is_skipped_not_fatal(self):
		data = json.dumps({"added": [["roles", {"doctype": "Has Role"}]]})

		self.assertIsNone(audit_trail._delta(data, "User"))

	def test_uninteresting_child_tables_are_ignored(self):
		data = json.dumps({"added": [["user_emails", {"email_id": "x@y.z"}]]})

		self.assertIsNone(audit_trail._delta(data, "User"))

	def test_row_changed_inside_a_child_row_is_reported(self):
		data = json.dumps({"row_changed": [["roles", 1, "abc123", [["role", "Old", "New"]]]]})

		delta = audit_trail._delta(data, "User")

		self.assertIn(("roles.role", "Old", "New"), delta["fields"])
