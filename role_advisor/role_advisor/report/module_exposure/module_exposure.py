# Copyright (c) 2026, Upande and contributors
# For license information, please see license.txt

"""Who can see which modules - navigation hygiene, not containment.

`frappe/permissions.py` never consults modules. `block_modules` is read only in
`frappe/desk/desktop.py` (Workspace sidebar) and `frappe/utils/modules.py`
(Dashboards, Charts, Number Cards). A blocked module's doctypes stay reachable
by URL, awesome bar and REST API. So this report describes what users *see*,
never what they can *do*.

The one real hazard it surfaces: `User.validate_allowed_modules` clears
`block_modules` and repopulates it from the module profile, with nothing to
restore hand-set blocks. Assigning a profile to a hand-blocked user whose blocks
were tighter is a silent widening of access.
"""

import frappe

COLUMNS = [
	{"fieldname": "user", "label": "User", "fieldtype": "Link", "options": "User", "width": 220},
	{"fieldname": "full_name", "label": "Name", "fieldtype": "Data", "width": 160},
	{"fieldname": "company", "label": "Company", "fieldtype": "Link", "options": "Company", "width": 150},
	{"fieldname": "module_profile", "label": "Module Profile", "fieldtype": "Link",
	 "options": "Module Profile", "width": 200},
	{"fieldname": "blocked_now", "label": "Blocked Now", "fieldtype": "Int", "width": 110},
	{"fieldname": "visible_modules", "label": "Visible Modules", "fieldtype": "Int", "width": 130},
	{"fieldname": "status", "label": "Status", "fieldtype": "Data", "width": 180},
	{"fieldname": "note", "label": "Note", "fieldtype": "Small Text", "width": 380},
]

STATUS_UNRESTRICTED = "Unrestricted"
STATUS_HAND_SET = "Hand-set, no profile"
STATUS_PROFILED = "Profiled"


def exposure_rows() -> list[dict]:
	total_modules = frappe.db.count("Module Def")

	rows = frappe.db.sql(
		"""
		select u.name as user, u.full_name as full_name,
		       nullif(u.module_profile, '') as module_profile,
		       (select count(*) from `tabBlock Module` bm
		        where bm.parent = u.name and bm.parenttype = 'User') as blocked_now,
		       e.company as company
		from `tabUser` u
		left join `tabEmployee` e on e.user_id = u.name and e.status = 'Active'
		where u.enabled = 1 and u.user_type = 'System User'
		order by blocked_now asc, u.full_name asc
		""",
		as_dict=True,
	)

	for row in rows:
		row["visible_modules"] = total_modules - (row["blocked_now"] or 0)

		if row["module_profile"]:
			row["status"] = STATUS_PROFILED
			row["note"] = ""
		elif row["blocked_now"]:
			row["status"] = STATUS_HAND_SET
			row["note"] = (
				f"{row['blocked_now']} hand-set blocks and no module profile. Assigning "
				"a profile discards these wholesale - a silent widening if the profile "
				"blocks fewer modules than these do."
			)
		else:
			row["status"] = STATUS_UNRESTRICTED
			row["note"] = (
				f"Every one of the {total_modules} modules appears in this user's "
				"navigation. Doctype access is unaffected either way."
			)

	return rows


def execute(filters=None):
	return COLUMNS, exposure_rows()
