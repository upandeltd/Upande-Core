# Copyright (c) 2026, Upande and contributors
# For license information, please see license.txt

"""What each Role Profile actually grants.

The only report that describes what people can *do*, rather than what they can
see. Module profiles are navigation; DocPerms are the real boundary, and this is
the view onto them.
"""

import frappe

from role_advisor import capability, privilege

COLUMNS = [
	{"fieldname": "role_profile", "label": "Role Profile", "fieldtype": "Link",
	 "options": "Role Profile", "width": 260},
	{"fieldname": "users", "label": "Users", "fieldtype": "Int", "width": 80},
	{"fieldname": "role_count", "label": "Roles", "fieldtype": "Int", "width": 80},
	{"fieldname": "doctype_count", "label": "Doctypes", "fieldtype": "Int", "width": 100},
	{"fieldname": "perm_count", "label": "Grants", "fieldtype": "Int", "width": 90},
	{"fieldname": "delete_count", "label": "Delete Rights", "fieldtype": "Int", "width": 120},
	{"fieldname": "privileged", "label": "Privileged", "fieldtype": "Check", "width": 100},
	{"fieldname": "privileged_grants", "label": "Privileged Grants", "fieldtype": "Small Text", "width": 320},
	{"fieldname": "note", "label": "Note", "fieldtype": "Small Text", "width": 320},
]

# A profile granting delete on more doctypes than this is worth a second look.
BROAD_DELETE_THRESHOLD = 10


def overgrant_rows() -> list[dict]:
	index = capability.build_capability_index()

	user_counts = {
		row["role_profile"]: row["users"]
		for row in frappe.db.sql(
			"""select role_profile, count(distinct parent) as users
			   from `tabUser Role Profile` where parenttype = 'User'
			   group by role_profile""",
			as_dict=True,
		)
	}
	role_counts = {
		row["parent"]: row["roles"]
		for row in frappe.db.sql(
			"""select parent, count(*) as roles from `tabHas Role`
			   where parenttype = 'Role Profile' group by parent""",
			as_dict=True,
		)
	}

	rows = []
	for profile in frappe.get_all("Role Profile", pluck="name"):
		granted = index.get(profile, {})
		grants = privilege.privileged_grants(profile)
		# `privileged_grants` returns a sentinel for a profile missing from the
		# index; an empty profile is legitimately empty, not unknown.
		if privilege.UNKNOWN_PROFILE in grants:
			grants = {}

		delete_count = sum(1 for perms in granted.values() if "delete" in perms)

		notes = []
		if grants:
			notes.append(
				"Grants write-equivalent rights on permission-bearing doctypes. "
				"Cannot be delegated."
			)
		if delete_count >= BROAD_DELETE_THRESHOLD:
			notes.append(f"Delete on {delete_count} doctypes.")
		if not granted:
			notes.append("Grants nothing - either empty or all its rows are permlevel > 0.")

		rows.append(
			{
				"role_profile": profile,
				"users": user_counts.get(profile, 0),
				"role_count": role_counts.get(profile, 0),
				"doctype_count": len(granted),
				"perm_count": capability.total_perm_count(granted),
				"delete_count": delete_count,
				"privileged": 1 if grants else 0,
				"privileged_grants": privilege.describe(grants) if grants else "",
				"note": " ".join(notes),
			}
		)

	# Widest first: the biggest profiles are where over-granting hides.
	return sorted(rows, key=lambda row: -row["perm_count"])


def execute(filters=None):
	return COLUMNS, overgrant_rows()
