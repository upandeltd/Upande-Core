# Copyright (c) 2026, ghost-mann and contributors
# For license information, please see license.txt

"""Export the whole access picture to a reviewable Excel workbook.

Four sheets: who holds what, what each profile grants, what each role grants,
and the full profile-by-doctype permission matrix. Columns marked EDITABLE are
inert - parked for a future importer so the workbook can become the source of
truth for a restructure rather than something decisions get transcribed from.

Read-only. Nothing here writes to a role, profile or user.
"""

import os
from collections import defaultdict

import frappe
from frappe.utils import cint, get_datetime, nowdate

from role_advisor import capability, module_workbook, privilege, settings, taxonomy

ACTIONS = "Keep,Rename,Merge,Delete,Investigate"
KEEP_OPTIONS = ["Keep", "Remove", "Change", "New"]

# Header colours: grey for observed facts, amber for anything you may edit.
FACT_BG = "#37474F"
EDIT_BG = "#8D6E00"
FLAG_BG = "#FFEBEE"


def _sig(caps: dict[str, set[str]]) -> frozenset:
	return frozenset((doctype, perm) for doctype, perms in caps.items() for perm in perms)


def _analysis() -> dict:
	"""Everything the sheets share: index, signatures, duplicates, subsets."""
	index = capability.build_capability_index()
	sigs = {profile: _sig(caps) for profile, caps in index.items()}

	users_per_profile: dict[str, int] = defaultdict(int)
	for row in frappe.get_all(
		"User Role Profile", filters={"parenttype": "User"}, fields=["role_profile"]
	):
		users_per_profile[row["role_profile"]] += 1

	by_sig = defaultdict(list)
	for profile, sig in sigs.items():
		if sig:
			by_sig[sig].append(profile)

	duplicates = {}
	for members in by_sig.values():
		if len(members) > 1:
			for member in members:
				duplicates[member] = sorted(set(members) - {member})

	# Smallest superset only. Listing all of them buries the useful one - the
	# next step up - under dozens of unrelated broader profiles.
	subset_of, superset_count = {}, defaultdict(int)
	for a, sig_a in sigs.items():
		if not sig_a:
			continue
		supersets = [(len(sigs[b]), b) for b, sig_b in sigs.items() if a != b and sig_a < sig_b]
		superset_count[a] = len(supersets)
		if supersets:
			subset_of[a] = min(supersets)[1]

	roles_per_profile = defaultdict(list)
	for row in frappe.get_all(
		"Has Role", filters={"parenttype": "Role Profile"}, fields=["parent", "role"]
	):
		roles_per_profile[row["parent"]].append(row["role"])

	return {
		"index": index,
		"sigs": sigs,
		"users_per_profile": users_per_profile,
		"duplicates": duplicates,
		"subset_of": subset_of,
		"superset_count": superset_count,
		"roles_per_profile": roles_per_profile,
	}


def users_rows() -> list[dict]:
	total_modules = frappe.db.count("Module Def")

	rows = frappe.db.sql(
		"""
		select u.name as user, u.full_name as full_name, u.enabled as enabled,
		       u.user_type as user_type, u.last_active as last_active,
		       nullif(u.module_profile, '') as module_profile,
		       e.name as employee, e.company as company, e.branch as branch,
		       e.department as department, e.designation as designation, e.grade as grade,
		       (select group_concat(p.role_profile separator ', ')
		        from `tabUser Role Profile` p
		        where p.parent = u.name and p.parenttype = 'User') as role_profile,
		       (select count(*) from `tabHas Role` r
		        where r.parent = u.name and r.parenttype = 'User') as role_count,
		       (select count(*) from `tabBlock Module` bm
		        where bm.parent = u.name and bm.parenttype = 'User') as blocked_modules,
		       (select count(*) from `tabUser Permission` up where up.user = u.name) as user_permissions
		from `tabUser` u
		left join `tabEmployee` e on e.user_id = u.name and e.status = 'Active'
		order by u.enabled desc, e.company, e.designation, u.full_name
		""",
		as_dict=True,
	)

	# Disabled users are included deliberately. Filtering them out is what
	# under-reported the user list; a disabled account still holds roles and a
	# profile, and re-enabling it restores every one of them silently.
	privileged_roles = {"System Manager", "User Manager"}
	held = defaultdict(set)
	for row in frappe.get_all(
		"Has Role",
		filters={"parenttype": "User", "role": ("in", list(privileged_roles))},
		fields=["parent", "role"],
	):
		held[row["parent"]].add(row["role"])

	delegates = set(frappe.get_all("Delegated User Admin", pluck="user"))

	for row in rows:
		row["visible_modules"] = total_modules - cint(row["blocked_modules"])
		row["is_system_manager"] = int("System Manager" in held.get(row["user"], ()))
		row["is_user_manager"] = int("User Manager" in held.get(row["user"], ()))
		row["is_delegate"] = int(row["user"] in delegates)
		row["has_employee"] = int(bool(row["employee"]))

	return rows


def profile_rows(analysis: dict) -> list[dict]:
	index = analysis["index"]
	rows = []

	for profile in sorted(index):
		caps = index[profile]
		grants = privilege.privileged_grants(profile)
		if privilege.UNKNOWN_PROFILE in grants:
			grants = {}

		proposed, issues = taxonomy.canonical_name(profile)
		parsed = taxonomy.parse(profile)
		users = analysis["users_per_profile"].get(profile, 0)

		if analysis["duplicates"].get(profile):
			issues = [*issues, "functional_duplicate"]
		if not caps:
			issues = [*issues, "grants_nothing"]
		if not users:
			issues = [*issues, "zero_users"]

		rows.append(
			{
				"role_profile": profile,
				"users": users,
				"roles": len(analysis["roles_per_profile"].get(profile, [])),
				"doctypes": len(caps),
				"grants": capability.total_perm_count(caps),
				"delete_rights": sum(1 for perms in caps.values() if "delete" in perms),
				"privileged": int(bool(grants)),
				"privileged_grants": privilege.describe(grants) if grants else "",
				"duplicate_of": ", ".join(analysis["duplicates"].get(profile, [])),
				"subset_of": analysis["subset_of"].get(profile, ""),
				"has_supersets": analysis["superset_count"].get(profile, 0),
				"detected_job_family": parsed["job_family"],
				"detected_variant": parsed["variant"],
				"detected_scope": parsed["scope"],
				"naming_issues": ", ".join(sorted(set(issues))),
				"proposed_name": proposed,
				"action": "",
				"merge_into": "",
				"notes": "",
			}
		)

	# Flag proposals that would collapse two profiles into one name. Usually a
	# genuine duplicate, occasionally a real distinction the old name expressed
	# badly - either way a human decides, so it must not pass silently.
	seen = defaultdict(list)
	for row in rows:
		if row["proposed_name"]:
			seen[row["proposed_name"]].append(row["role_profile"])
	for row in rows:
		if len(seen.get(row["proposed_name"], [])) > 1:
			row["naming_issues"] = ", ".join(
				sorted({*row["naming_issues"].split(", "), "name_collision"} - {""})
			)

	return rows


def role_rows(analysis: dict) -> list[dict]:
	all_roles = frappe.get_all("Role", fields=["name", "disabled"])
	role_caps = capability._capabilities_from_rows(
		capability._perm_rows_for_roles([r["name"] for r in all_roles])
	)

	profiles_using = defaultdict(list)
	for profile, roles in analysis["roles_per_profile"].items():
		for role in roles:
			profiles_using[role].append(profile)

	users_holding = defaultdict(int)
	for row in frappe.get_all(
		"Has Role", filters={"parenttype": "User"}, fields=["role"]
	):
		users_holding[row["role"]] += 1

	privileged = set(settings.privileged_doctypes())
	rows = []

	for role in sorted(all_roles, key=lambda r: r["name"]):
		name = role["name"]
		caps = role_caps.get(name, {})
		touches = sorted(
			doctype
			for doctype, perms in caps.items()
			if doctype in privileged and perms & privilege.WRITE_EQUIVALENT
		)

		rows.append(
			{
				"role": name,
				"disabled": cint(role["disabled"]),
				"profiles_using": len(profiles_using.get(name, [])),
				"profile_names": ", ".join(sorted(profiles_using.get(name, []))[:8]),
				"users_holding": users_holding.get(name, 0),
				"doctypes": len(caps),
				"grants": capability.total_perm_count(caps),
				"in_no_profile": int(not profiles_using.get(name)),
				"grants_on_privileged_doctypes": ", ".join(touches),
				"action": "",
				"notes": "",
			}
		)

	return rows


def permission_rows(analysis: dict) -> list[dict]:
	module_of = {
		row["name"]: row["module"]
		for row in frappe.get_all("DocType", fields=["name", "module"])
	}

	rows = []
	for profile in sorted(analysis["index"]):
		for doctype, perms in sorted(analysis["index"][profile].items()):
			row = {
				"role_profile": profile,
				"doctype": doctype,
				"module": module_of.get(doctype, ""),
				"grant_count": len(perms),
			}
			row.update({perm: int(perm in perms) for perm in capability.TRACKED_PERMS})
			rows.append(row)

	return rows


SHEETS = (
	(
		"Users",
		[
			("user", 34, 0), ("full_name", 24, 0), ("enabled", 9, 0), ("user_type", 13, 0),
			("last_active", 19, 0), ("company", 20, 0), ("branch", 14, 0),
			("department", 22, 0), ("designation", 26, 0), ("grade", 12, 0),
			("has_employee", 13, 0), ("role_profile", 30, 0), ("module_profile", 24, 0),
			("visible_modules", 15, 0), ("role_count", 11, 0), ("user_permissions", 16, 0),
			("is_system_manager", 17, 0), ("is_user_manager", 15, 0), ("is_delegate", 12, 0),
			("proposed_role_profile", 30, 1), ("proposed_module_profile", 26, 1), ("notes", 40, 1),
		],
	),
	(
		"Role Profiles",
		[
			("role_profile", 46, 0), ("users", 8, 0), ("roles", 8, 0), ("doctypes", 10, 0),
			("grants", 9, 0), ("delete_rights", 13, 0), ("privileged", 11, 0),
			("privileged_grants", 34, 0), ("duplicate_of", 40, 0), ("subset_of", 40, 0),
			("has_supersets", 13, 0), ("detected_job_family", 30, 0),
			("detected_variant", 18, 0), ("detected_scope", 18, 0), ("naming_issues", 34, 0),
			("proposed_name", 48, 1), ("action", 14, 1), ("merge_into", 40, 1), ("notes", 40, 1),
		],
	),
	(
		"Roles",
		[
			("role", 40, 0), ("disabled", 9, 0), ("profiles_using", 14, 0),
			("profile_names", 50, 0), ("users_holding", 13, 0), ("doctypes", 10, 0),
			("grants", 9, 0), ("in_no_profile", 13, 0),
			("grants_on_privileged_doctypes", 34, 0), ("action", 14, 1), ("notes", 40, 1),
		],
	),
	(
		"Permissions",
		[
			("role_profile", 46, 0), ("doctype", 34, 0), ("module", 24, 0),
			("read", 7, 0), ("write", 7, 0), ("create", 8, 0), ("submit", 8, 0),
			("cancel", 8, 0), ("delete", 8, 0), ("report", 8, 0), ("export", 8, 0),
			("grant_count", 12, 0),
		],
	),
)


def _write_sheet(book, title, columns, rows, formats, section_formats=None):
	"""Write one sheet. Shared by every sheet in the workbook so the header
	styling, freeze panes, autofilter and dropdowns cannot drift apart."""
	sheet = book.add_worksheet(title)

	for position, (name, width, editable) in enumerate(columns):
		label = f"{name} (EDITABLE)" if editable else name
		sheet.write(0, position, label, formats["edit"] if editable else formats["fact"])
		sheet.set_column(position, position, width)

	for offset, row in enumerate(rows, start=1):
		fmt = (section_formats or {}).get(row.get("section"))
		for position, (name, _width, _editable) in enumerate(columns):
			value = row.get(name)
			if value is None or value == "":
				if fmt:
					sheet.write_blank(offset, position, None, fmt)
				continue
			if name == "last_active" and value:
				sheet.write_datetime(offset, position, get_datetime(value), formats["stamp"])
			elif fmt:
				sheet.write(offset, position, value, fmt)
			else:
				sheet.write(offset, position, value)

	sheet.freeze_panes(1, 1)
	if rows:
		sheet.autofilter(0, 0, len(rows), len(columns) - 1)
		names = [column[0] for column in columns]
		for target, options in (("action", ACTIONS.split(",")), ("keep", KEEP_OPTIONS), ("status", KEEP_OPTIONS)):
			if target in names:
				column = names.index(target)
				sheet.data_validation(
					1, column, len(rows), column,
					{"validate": "list", "source": options},
				)

	return sheet


def build_combined(path: str | None = None) -> str:
	"""One workbook holding every sheet, for both audiences.

	Order runs widest to narrowest: the module Overview first, then the people,
	then the profiles and roles that grant their access, then the full
	permission matrix, then one tab per module for its owner.

	All of it reads the local bench, which is the only place a v16 capability
	index exists. Production is v15 and has no `User Role Profile` doctype, so
	the *user list* there is fresher - see `live_export` for that.
	"""
	import xlsxwriter

	if not path:
		app_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
		docs = os.path.join(app_dir, "docs")
		os.makedirs(docs, exist_ok=True)
		path = os.path.join(docs, f"access-workbook-{nowdate()}.xlsx")

	analysis = _analysis()
	module_data = module_workbook.gather()

	taken: set[str] = {"Overview", "Users", "Users by Module", "Role Profiles", "Roles", "Profile Index", "Permissions"}
	tabs = {
		module: module_workbook._tab_name(module, taken)
		for module in sorted(module_data["by_module"])
	}

	book = xlsxwriter.Workbook(path)
	formats = {
		"fact": book.add_format({"bold": True, "bg_color": FACT_BG, "font_color": "white", "border": 1}),
		"edit": book.add_format({"bold": True, "bg_color": EDIT_BG, "font_color": "white", "border": 1}),
		"stamp": book.add_format({"num_format": "yyyy-mm-dd hh:mm"}),
	}
	sections = {
		module_workbook.SECTION_PROFILE: book.add_format({"bold": True, "bg_color": module_workbook.PROFILE_BG}),
		module_workbook.SECTION_USER: book.add_format({"bg_color": module_workbook.USER_BG}),
		module_workbook.SECTION_ROLE: book.add_format({"bg_color": module_workbook.ROLE_BG}),
		module_workbook.SECTION_ADD: book.add_format({"bg_color": module_workbook.ADD_BG, "italic": True}),
	}

	_write_sheet(book, "Overview", module_workbook.OVERVIEW_COLUMNS,
	             module_workbook.overview_rows(module_data, tabs), formats)
	_write_sheet(book, "Users", SHEETS[0][1], users_rows(), formats)
	_write_sheet(book, "Users by Module", module_workbook.USERS_BY_MODULE_COLUMNS,
	             module_workbook.users_by_module_rows(module_data), formats)
	_write_sheet(book, "Role Profiles", SHEETS[1][1], profile_rows(analysis), formats)
	_write_sheet(book, "Roles", SHEETS[2][1], role_rows(analysis), formats)
	_write_sheet(book, "Profile Index", module_workbook.PROFILE_INDEX_COLUMNS,
	             module_workbook.profile_index_rows(module_data), formats)
	_write_sheet(book, "Permissions", SHEETS[3][1], permission_rows(analysis), formats)

	for module in sorted(module_data["by_module"]):
		_write_sheet(book, tabs[module], module_workbook.COLUMNS,
		             module_workbook.module_rows(module, module_data), formats, sections)

	book.close()

	return path


def build(path: str | None = None) -> str:
	"""Write the workbook and return its path.

	Defaults into the app's own `docs/` directory so the export travels with the
	repository rather than sitting in a site's private files.
	"""
	import xlsxwriter

	if not path:
		app_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
		docs = os.path.join(app_dir, "docs")
		os.makedirs(docs, exist_ok=True)
		path = os.path.join(docs, f"user-access-workbook-{nowdate()}.xlsx")

	analysis = _analysis()
	data = {
		"Users": users_rows(),
		"Role Profiles": profile_rows(analysis),
		"Roles": role_rows(analysis),
		"Permissions": permission_rows(analysis),
	}

	book = xlsxwriter.Workbook(path, {"constant_memory": True, "default_date_format": "yyyy-mm-dd hh:mm"})
	fact = book.add_format({"bold": True, "bg_color": FACT_BG, "font_color": "white", "border": 1})
	edit = book.add_format({"bold": True, "bg_color": EDIT_BG, "font_color": "white", "border": 1})
	flag = book.add_format({"bg_color": FLAG_BG})
	stamp = book.add_format({"num_format": "yyyy-mm-dd hh:mm"})

	for title, columns in SHEETS:
		sheet = book.add_worksheet(title)
		rows = data[title]

		for position, (name, width, editable) in enumerate(columns):
			label = f"{name} (EDITABLE)" if editable else name
			sheet.write(0, position, label, edit if editable else fact)
			sheet.set_column(position, position, width)

		for index, row in enumerate(rows, start=1):
			for position, (name, _width, _editable) in enumerate(columns):
				value = row.get(name)
				if value is None:
					continue
				if name == "last_active" and value:
					sheet.write_datetime(index, position, get_datetime(value), stamp)
				else:
					sheet.write(index, position, value)

		sheet.freeze_panes(1, 1)
		if rows:
			sheet.autofilter(0, 0, len(rows), len(columns) - 1)

		# Highlight the rows that need a human, so the sheet leads with them.
		if title == "Role Profiles":
			issue_col = [c[0] for c in columns].index("naming_issues")
			sheet.conditional_format(
				1, 0, len(rows), len(columns) - 1,
				{
					"type": "formula",
					"criteria": f'=LEN(${chr(65 + issue_col)}2)>0',
					"format": flag,
				},
			)

		action_names = [c[0] for c in columns]
		if "action" in action_names and rows:
			column = action_names.index("action")
			sheet.data_validation(
				1, column, len(rows), column,
				{"validate": "list", "source": ACTIONS.split(","),
				 "error_message": f"Choose one of: {ACTIONS}"},
			)

	book.close()

	return path
