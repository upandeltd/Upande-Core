# Copyright (c) 2026, ghost-mann and contributors
# For license information, please see license.txt

"""Snapshot a user's access, and record what changed.

Every assignment is logged, including no-ops: a trail with gaps cannot answer
"was this change made, or never attempted?"
"""

import frappe

from role_advisor import capability

TRIGGER_MANUAL = "Manual"
TRIGGER_MAP = "Designation Map"
TRIGGER_SWEEP = "Bulk Sweep"

OUTCOME_APPLIED = "Applied"
OUTCOME_NO_CHANGE = "No Change"
OUTCOME_REFUSED = "Refused"


def snapshot(user: str) -> dict:
	"""Capture the access-relevant state of `user` before or after a write."""
	return {
		"profiles": capability.get_user_role_profiles(user),
		"module_profile": frappe.db.get_value("User", user, "module_profile") or None,
		"roles": set(
			frappe.get_all(
				"Has Role",
				filters={"parent": user, "parenttype": "User"},
				pluck="role",
			)
		),
	}


def log_assignment(
	target: str,
	before: dict,
	after: dict,
	trigger: str,
	outcome: str = OUTCOME_APPLIED,
	notes: str | None = None,
) -> str:
	"""Write one immutable log row and return its name."""
	row = frappe.get_doc(
		{
			"doctype": "Access Assignment Log",
			"actor": frappe.session.user,
			"target_user": target,
			"trigger": trigger,
			"outcome": outcome,
			"profiles_before": ", ".join(before["profiles"]),
			"profiles_after": ", ".join(after["profiles"]),
			"module_profile_before": before["module_profile"],
			"module_profile_after": after["module_profile"],
			"roles_gained": ", ".join(sorted(after["roles"] - before["roles"])),
			"roles_lost": ", ".join(sorted(before["roles"] - after["roles"])),
			"decision_notes": notes,
		}
	)
	row.insert(ignore_permissions=True)

	return row.name
