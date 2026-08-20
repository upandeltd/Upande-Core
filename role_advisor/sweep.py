# Copyright (c) 2026, Upande and contributors
# For license information, please see license.txt

"""Bulk assignment from the Designation Access Map.

Two passes. `dry_run` proposes and explains; `apply` writes only what it is told
to. Nothing is written on the strength of an inactive map row - the whole point
of the confidence tiers is that a human rules on the ambiguous ones first.

System-Manager-only. A delegate assigns one user at a time through
`role_advisor.api.assign_access`, which logs and gates per call.
"""

import frappe

from role_advisor import audit, capability, mapping
from role_advisor.role_advisor.report.designation_gap.designation_gap import (
	unprofiled_users,
)

# Commit every this many writes, so a failure halfway does not roll back an
# hour of work on a long run.
BATCH_SIZE = 50


def _candidate(user: str, full_name: str | None = None) -> dict:
	scope = mapping.employee_scope(user)
	designation = frappe.db.get_value(
		"Employee", {"user_id": user, "status": "Active"}, "designation"
	)

	row = {
		"user": user,
		"full_name": full_name,
		"designation": designation or None,
		"company": scope.get("company"),
		"role_profile": None,
		"module_profile": None,
		"map_row": None,
		"blocked_reason": None,
	}

	if not designation:
		row["blocked_reason"] = "No active Employee record, so no designation to map from."
		return row

	active = mapping.resolve(designation, scope, active_only=True)
	if active:
		mapped = frappe.get_doc("Designation Access Map", active)
		row.update(
			role_profile=mapped.role_profile,
			module_profile=mapped.module_profile,
			map_row=mapped.name,
		)
		return row

	# Distinguish "no row at all" from "a row exists but nobody has ruled on
	# it": the second is a decision waiting, the first is a mapping gap.
	inactive = mapping.resolve(designation, scope, active_only=False)
	if inactive:
		row["map_row"] = inactive
		row["blocked_reason"] = (
			f"Map row {inactive} is not active. Review its confidence and evidence, "
			"then activate it."
		)
	else:
		row["blocked_reason"] = f"No map row for designation '{designation}' in this scope."

	return row


def dry_run() -> list[dict]:
	"""Propose an assignment for every unprofiled user. Writes nothing."""
	return [_candidate(row["user"], row.get("full_name")) for row in unprofiled_users()]


def apply(users: list[str] | None = None) -> dict:
	"""Assign profiles to `users`, or to every unblocked candidate if None.

	Every user considered gets a log row, including the ones skipped - a trail
	that omits refusals cannot answer "was this attempted?".
	"""
	frappe.only_for("System Manager")

	if users is None:
		candidates = dry_run()
	else:
		# Named users are resolved directly rather than intersected with
		# `dry_run()`. A System Manager who names a user deserves an answer
		# about that user - including "they already hold it" - and the
		# unprofiled-users query would silently drop anyone already assigned.
		candidates = [_candidate(user) for user in users]

	result = {"applied": 0, "skipped": 0, "no_change": 0, "logs": []}

	for index, candidate in enumerate(candidates, start=1):
		target = candidate["user"]
		before = audit.snapshot(target)

		if candidate["blocked_reason"]:
			result["skipped"] += 1
			result["logs"].append(
				audit.log_assignment(
					target,
					before,
					before,
					audit.TRIGGER_SWEEP,
					outcome=audit.OUTCOME_REFUSED,
					notes=candidate["blocked_reason"],
				)
			)
			continue

		if candidate["role_profile"] in before["profiles"]:
			result["no_change"] += 1
			result["logs"].append(
				audit.log_assignment(
					target,
					before,
					before,
					audit.TRIGGER_SWEEP,
					outcome=audit.OUTCOME_NO_CHANGE,
					notes="Already holds the mapped profile.",
				)
			)
			continue

		doc = frappe.get_doc("User", target)
		capability.set_user_role_profiles(doc, [candidate["role_profile"]])
		if candidate["module_profile"]:
			doc.module_profile = candidate["module_profile"]
		# permlevel 1: no permitted route exists. Gated by only_for above.
		doc.save(ignore_permissions=True)

		after = audit.snapshot(target)
		result["applied"] += 1
		result["logs"].append(
			audit.log_assignment(
				target,
				before,
				after,
				audit.TRIGGER_SWEEP,
				notes=f"From map row {candidate['map_row']}.",
			)
		)

		if index % BATCH_SIZE == 0:
			frappe.db.commit()

	frappe.db.commit()

	return result
