# Copyright (c) 2026, ghost-mann and contributors
# For license information, please see license.txt

"""Who holds System Manager, and should they?

Report-only by decision: no role is revoked automatically. On Kaitet every one
of the 23 holders is Upande staff with no Employee record, which is the reason
delegation is being built - not a finding to act on directly.
"""

import frappe
from frappe.utils import add_months, now_datetime

COLUMNS = [
	{"fieldname": "user", "label": "User", "fieldtype": "Link", "options": "User", "width": 240},
	{"fieldname": "full_name", "label": "Name", "fieldtype": "Data", "width": 160},
	{"fieldname": "last_active", "label": "Last Active", "fieldtype": "Datetime", "width": 180},
	{"fieldname": "role_profile", "label": "Role Profile", "fieldtype": "Data", "width": 200},
	{"fieldname": "role_count", "label": "Roles", "fieldtype": "Int", "width": 80},
	{"fieldname": "has_employee", "label": "Has Employee", "fieldtype": "Check", "width": 120},
	{"fieldname": "flags", "label": "Flags", "fieldtype": "Small Text", "width": 380},
]

# A holder quieter than this has probably outlived the need for the role.
DORMANT_MONTHS = 6


# Local-parts and domains that mark a login as not belonging to a real person.
NON_PERSON_MARKERS = ("api", "service", "test", "demo", "temp", "dummy")


def _looks_like_non_person(user: str) -> bool:
	"""Flag logins that are unlikely to belong to an accountable human.

	Verified against live production, where `user@api.com`, `eric@test.com` and
	`test@upande.com` all hold System Manager. A service or test account cannot
	be held responsible for what System Manager can do, so each one is a finding
	regardless of how long ago it was created.
	"""
	local, _, domain = user.lower().partition("@")

	return any(
		marker in local or domain.split(".")[0] == marker
		for marker in NON_PERSON_MARKERS
	)


def audit_rows() -> list[dict]:
	rows = frappe.db.sql(
		"""
		select u.name as user, u.full_name as full_name, u.last_active as last_active,
		       (select count(*) from `tabHas Role` r
		        where r.parent = u.name and r.parenttype = 'User') as role_count,
		       (select group_concat(p.role_profile separator ', ')
		        from `tabUser Role Profile` p
		        where p.parent = u.name and p.parenttype = 'User') as role_profile,
		       exists(select 1 from `tabEmployee` e
		              where e.user_id = u.name and e.status = 'Active') as has_employee
		from `tabUser` u
		join `tabHas Role` hr
		     on hr.parent = u.name and hr.parenttype = 'User' and hr.role = 'System Manager'
		where u.enabled = 1
		order by u.last_active desc
		""",
		as_dict=True,
	)

	dormant_before = add_months(now_datetime(), -DORMANT_MONTHS)

	for row in rows:
		flags = []

		# A login that never belongs to a person cannot be held accountable for
		# what System Manager can do.
		if not row["has_employee"]:
			flags.append("no Employee record")
		if _looks_like_non_person(row["user"]):
			flags.append("service or test account")
		if not row["last_active"]:
			flags.append("never active")
		elif row["last_active"] < dormant_before:
			flags.append(f"dormant for over {DORMANT_MONTHS} months")
		if not row["role_profile"]:
			flags.append("holds no role profile")

		row["flags"] = "; ".join(flags)

	return rows


def execute(filters=None):
	return COLUMNS, audit_rows()
