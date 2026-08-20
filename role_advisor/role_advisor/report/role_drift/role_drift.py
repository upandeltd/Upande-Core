# Copyright (c) 2026, Upande and contributors
# For license information, please see license.txt

"""Roles held outside any of the user's role profiles.

`User.populate_role_profile_roles` prunes roles to the union of the user's
profiles on every save. A role granted outside a profile is therefore lost the
next time that user is saved, by anyone, for any reason - unless something
re-adds it after the prune.

HRMS does exactly that: `compose(fn, *hooks)` runs the controller's `validate`
before `doc_events`, and HRMS hooks `update_approver_user_roles` onto
`User.validate`, re-adding Leave/Expense Approver from the Employee records
naming that user. Those roles are safe. Anything else in this report is not.
"""

import frappe

# Roles restored after the prune by a known doc_events hook.
SELF_HEALING = {
	"Leave Approver": "hrms.overrides.employee_master.update_approver_user_roles",
	"Expense Approver": "hrms.overrides.employee_master.update_approver_user_roles",
}

COLUMNS = [
	{"fieldname": "user", "label": "User", "fieldtype": "Link", "options": "User", "width": 220},
	{"fieldname": "role", "label": "Role", "fieldtype": "Link", "options": "Role", "width": 200},
	{"fieldname": "profiles", "label": "Profiles Held", "fieldtype": "Data", "width": 220},
	{"fieldname": "self_healing", "label": "Self Healing", "fieldtype": "Check", "width": 110},
	{"fieldname": "note", "label": "Note", "fieldtype": "Small Text", "width": 420},
]


def drift_rows() -> list[dict]:
	rows = frappe.db.sql(
		"""
		select hr.parent as user, hr.role as role
		from `tabHas Role` hr
		join `tabUser` u on u.name = hr.parent
		where hr.parenttype = 'User'
		  and u.enabled = 1
		  and u.user_type = 'System User'
		  and exists (
		      select 1 from `tabUser Role Profile` p
		      where p.parent = u.name and p.parenttype = 'User'
		  )
		  and not exists (
		      select 1
		      from `tabUser Role Profile` p
		      join `tabHas Role` pr
		           on pr.parent = p.role_profile and pr.parenttype = 'Role Profile'
		      where p.parent = hr.parent and pr.role = hr.role
		  )
		order by hr.parent, hr.role
		""",
		as_dict=True,
	)

	for row in rows:
		healer = SELF_HEALING.get(row["role"])
		row["self_healing"] = 1 if healer else 0
		row["profiles"] = ", ".join(
			frappe.get_all(
				"User Role Profile",
				filters={"parent": row["user"], "parenttype": "User"},
				pluck="role_profile",
			)
		)
		row["note"] = (
			f"Re-added after the prune by {healer}. Safe."
			if healer
			else (
				"Granted outside every profile this user holds, with no known hook to "
				"restore it. The next save of this User revokes it silently."
			)
		)

	# Genuine risks first.
	return sorted(rows, key=lambda r: (r["self_healing"], r["user"]))


def execute(filters=None):
	return COLUMNS, drift_rows()
