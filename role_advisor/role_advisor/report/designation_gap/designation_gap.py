# Copyright (c) 2026, Upande and contributors
# For license information, please see license.txt

"""Which enabled System Users hold no role profile, and what should they get?

Read-only. Proposals come from what same-designation, same-scope colleagues
already hold - which is evidence, not endorsement, because Kaitet's existing
assignments are known-inconsistent. Nothing here is auto-applied; the sweep
applies only rows a human has activated.
"""

import frappe

from role_advisor import mapping, seeding, settings

COLUMNS = [
	{"fieldname": "user", "label": "User", "fieldtype": "Link", "options": "User", "width": 220},
	{"fieldname": "full_name", "label": "Name", "fieldtype": "Data", "width": 160},
	{"fieldname": "designation", "label": "Designation", "fieldtype": "Link",
	 "options": "Designation", "width": 180},
	{"fieldname": "company", "label": "Company", "fieldtype": "Link",
	 "options": "Company", "width": 150},
	{"fieldname": "proposed_role_profile", "label": "Proposed Profile", "fieldtype": "Link",
	 "options": "Role Profile", "width": 220},
	{"fieldname": "confidence", "label": "Confidence", "fieldtype": "Data", "width": 100},
	{"fieldname": "peers", "label": "Peers", "fieldtype": "Int", "width": 70},
	{"fieldname": "from_map", "label": "From Map", "fieldtype": "Check", "width": 80},
	{"fieldname": "evidence", "label": "Evidence", "fieldtype": "Small Text", "width": 400},
]

CONFIDENCE_ORDER = {"High": 0, "Medium": 1, "Low": 2, "None": 3}


def unprofiled_users() -> list[dict]:
	"""Enabled System Users with no row in the role_profiles child table."""
	return frappe.db.sql(
		"""
		select u.name as user, u.full_name as full_name
		from `tabUser` u
		where u.enabled = 1
		  and u.user_type = 'System User'
		  and not exists (
		      select 1 from `tabUser Role Profile` p
		      where p.parent = u.name and p.parenttype = 'User'
		  )
		order by u.full_name
		""",
		as_dict=True,
	)


def gap_rows() -> list[dict]:
	observed = seeding.observe_assignments()
	dimensions = settings.scope_dimensions()

	rows = []
	for user in unprofiled_users():
		scope = mapping.employee_scope(user["user"])
		designation = frappe.db.get_value(
			"Employee", {"user_id": user["user"], "status": "Active"}, "designation"
		)

		row = {
			**user,
			"designation": designation or None,
			"company": scope.get("company"),
			"proposed_role_profile": None,
			"confidence": "None",
			"peers": 0,
			"from_map": 0,
			"evidence": "",
		}

		if not designation:
			row["evidence"] = "No active Employee record, so no designation to map from."
			rows.append(row)
			continue

		# An existing map row is authoritative and outranks peer evidence.
		map_row = mapping.resolve(designation, scope, active_only=False)
		if map_row:
			mapped = frappe.get_doc("Designation Access Map", map_row)
			row.update(
				proposed_role_profile=mapped.role_profile,
				confidence=mapped.confidence or "None",
				from_map=1,
				evidence=mapped.evidence or "From an existing map row.",
			)
			rows.append(row)
			continue

		key = (designation, *(scope.get(d) for d in dimensions))
		counts = observed.get(key, {})
		verdict = seeding.classify(counts)
		if verdict:
			row.update(
				proposed_role_profile=verdict["profile"],
				confidence=verdict["confidence"],
				peers=sum(counts.values()),
				evidence=verdict["evidence"],
			)
		else:
			row["evidence"] = (
				f"No colleague with designation '{designation}' in this scope holds a "
				"profile, so there is no precedent to derive one from."
			)

		rows.append(row)

	# Most actionable first: highest confidence, then most peers.
	return sorted(
		rows, key=lambda r: (CONFIDENCE_ORDER.get(r["confidence"], 9), -r["peers"])
	)


def execute(filters=None):
	return COLUMNS, gap_rows()
