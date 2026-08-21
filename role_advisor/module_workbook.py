# Copyright (c) 2026, ghost-mann and contributors
# For license information, please see license.txt

"""Per-module authoring workbook for module owners.

One sheet per module. Inside each, one block per role profile that touches that
module, and inside each block two grouped areas: the ROLES composing the
profile, and the PERMISSIONS those roles grant on this module's doctypes.

A caveat the workbook surfaces rather than hides: a role profile spans a median
of 35 modules, so the same profile appears on many module sheets. The
`also_on_sheets` column on every PROFILE row names the others, so two owners
editing the same profile can see they are about to disagree. Reconciling those
is a human step before anything is applied.

Read-only. Nothing here writes to a role, profile or user.
"""

import os
import re
from collections import defaultdict

import frappe
from frappe.utils import nowdate

from role_advisor import capability

SECTION_PROFILE = "PROFILE"
SECTION_ROLE = "· ROLE"
SECTION_PERMISSION = "· · PERMISSION"
SECTION_ADD = "+ ADD"

KEEP_OPTIONS = ["Keep", "Remove", "Change", "New"]

HEAD_BG = "#37474F"
EDIT_BG = "#8D6E00"
PROFILE_BG = "#CFD8DC"
ROLE_BG = "#E8EAF6"
ADD_BG = "#FFF8E1"

COLUMNS = (
	("section", 16, 0),
	("role_profile", 46, 0),
	("role", 34, 0),
	("doctype", 34, 0),
	("read", 7, 0),
	("write", 7, 0),
	("create", 8, 0),
	("submit", 8, 0),
	("cancel", 8, 0),
	("delete", 8, 0),
	("report", 8, 0),
	("export", 8, 0),
	("profile_users", 13, 0),
	("spans_modules", 14, 0),
	("also_on_sheets", 44, 0),
	("keep", 11, 1),
	("notes", 40, 1),
)

RIGHTS = ("read", "write", "create", "submit", "cancel", "delete", "report", "export")

# Excel forbids these in a sheet name, and caps the name at 31 characters.
_UNSAFE_TAB = re.compile(r"[\[\]:*?/\\]")


def _tab_name(module: str, taken: set[str]) -> str:
	name = _UNSAFE_TAB.sub("-", module)[:31].strip() or "Module"
	if name not in taken:
		taken.add(name)
		return name

	# Suffix with a counter, trimming to stay inside the 31-char limit.
	for n in range(2, 100):
		suffix = f" ({n})"
		candidate = name[: 31 - len(suffix)] + suffix
		if candidate not in taken:
			taken.add(candidate)
			return candidate

	raise ValueError(f"cannot make a unique tab name for {module}")


def gather() -> dict:
	"""Everything the sheets need, in one pass over the permission data."""
	index = capability.build_capability_index()

	module_of = {
		row["name"]: row["module"]
		for row in frappe.get_all("DocType", fields=["name", "module"])
		if row["module"]
	}

	profile_roles = defaultdict(list)
	for row in frappe.get_all(
		"Has Role", filters={"parenttype": "Role Profile"}, fields=["parent", "role"]
	):
		profile_roles[row["parent"]].append(row["role"])

	users = defaultdict(int)
	for row in frappe.get_all(
		"User Role Profile", filters={"parenttype": "User"}, fields=["role_profile"]
	):
		users[row["role_profile"]] += 1

	all_roles = frappe.get_all("Role", pluck="name")
	role_caps = capability._capabilities_from_rows(
		capability._perm_rows_for_roles(all_roles)
	)
	role_modules = {
		role: {module_of[dt] for dt in caps if dt in module_of}
		for role, caps in role_caps.items()
	}

	# {module: {profile: {doctype: {perm}}}}
	by_module: dict[str, dict[str, dict[str, set[str]]]] = defaultdict(
		lambda: defaultdict(dict)
	)
	profile_modules = defaultdict(set)
	for profile, caps in index.items():
		for doctype, perms in caps.items():
			module = module_of.get(doctype)
			if not module:
				continue
			by_module[module][profile][doctype] = perms
			profile_modules[profile].add(module)

	return {
		"by_module": by_module,
		"profile_roles": profile_roles,
		"profile_modules": profile_modules,
		"role_modules": role_modules,
		"role_caps": role_caps,
		"module_of": module_of,
		"users": users,
	}


def module_rows(module: str, data: dict) -> list[dict]:
	"""The blocked rows for one module sheet: PROFILE, its ROLES, its PERMISSIONS."""
	rows = []
	profiles = data["by_module"].get(module, {})

	for profile in sorted(profiles):
		granted = profiles[profile]
		spans = sorted(data["profile_modules"].get(profile, set()) - {module})

		rows.append(
			{
				"section": SECTION_PROFILE,
				"role_profile": profile,
				"profile_users": data["users"].get(profile, 0),
				"spans_modules": len(spans) + 1,
				# The reconciliation flag: every other sheet this profile is on.
				"also_on_sheets": ", ".join(spans),
				"keep": "",
				"notes": "",
			}
		)

		# Area one: the roles composing this profile that reach this module.
		for role in sorted(data["profile_roles"].get(profile, [])):
			if module not in data["role_modules"].get(role, set()):
				continue
			role_here = data["role_caps"].get(role, {})
			union: set[str] = set()
			for doctype, perms in role_here.items():
				if data["module_of"].get(doctype) == module:
					union |= perms
			row = {
				"section": SECTION_ROLE,
				"role_profile": profile,
				"role": role,
				"spans_modules": len(data["role_modules"].get(role, set())),
			}
			row.update({right: int(right in union) for right in RIGHTS})
			rows.append(row)

		rows.append(
			{"section": SECTION_ADD, "role_profile": profile, "role": "", "keep": "New"}
		)

		# Area two: the resulting permissions on this module's doctypes.
		for doctype in sorted(granted):
			row = {
				"section": SECTION_PERMISSION,
				"role_profile": profile,
				"doctype": doctype,
			}
			row.update({right: int(right in granted[doctype]) for right in RIGHTS})
			rows.append(row)

		rows.append(
			{"section": SECTION_ADD, "role_profile": profile, "doctype": "", "keep": "New"}
		)

	return rows


def overview_rows(data: dict, tabs: dict[str, str]) -> list[dict]:
	rows = []
	doctypes_per_module = defaultdict(int)
	for module in data["module_of"].values():
		doctypes_per_module[module] += 1

	for module in sorted(data["by_module"]):
		profiles = data["by_module"][module]
		rows.append(
			{
				"module": module,
				"sheet": tabs[module],
				"doctypes_in_module": doctypes_per_module.get(module, 0),
				"profiles_touching": len(profiles),
				"permission_rows": sum(len(v) for v in profiles.values()),
				"owner": "",
				"status": "",
				"notes": "",
			}
		)

	return rows


OVERVIEW_COLUMNS = (
	("module", 34, 0),
	("sheet", 34, 0),
	("doctypes_in_module", 18, 0),
	("profiles_touching", 18, 0),
	("permission_rows", 16, 0),
	("owner", 26, 1),
	("status", 16, 1),
	("notes", 46, 1),
)

PROFILE_INDEX_COLUMNS = (
	("role_profile", 46, 0),
	("users", 8, 0),
	("roles", 8, 0),
	("modules_spanned", 16, 0),
	("module_sheets", 90, 0),
)


def profile_index_rows(data: dict) -> list[dict]:
	"""Which module sheets each profile appears on - the reconciliation list."""
	rows = []
	for profile in sorted(data["profile_modules"]):
		modules = sorted(data["profile_modules"][profile])
		rows.append(
			{
				"role_profile": profile,
				"users": data["users"].get(profile, 0),
				"roles": len(data["profile_roles"].get(profile, [])),
				"modules_spanned": len(modules),
				"module_sheets": ", ".join(modules),
			}
		)

	return sorted(rows, key=lambda row: -row["modules_spanned"])


def build(path: str | None = None) -> str:
	"""Write the module-owner workbook and return its path."""
	import xlsxwriter

	if not path:
		app_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
		docs = os.path.join(app_dir, "docs")
		os.makedirs(docs, exist_ok=True)
		path = os.path.join(docs, f"module-owner-workbook-{nowdate()}.xlsx")

	data = gather()
	taken: set[str] = set()
	tabs = {module: _tab_name(module, taken) for module in sorted(data["by_module"])}

	book = xlsxwriter.Workbook(path)
	head = book.add_format({"bold": True, "bg_color": HEAD_BG, "font_color": "white", "border": 1})
	edit_head = book.add_format({"bold": True, "bg_color": EDIT_BG, "font_color": "white", "border": 1})
	profile_fmt = book.add_format({"bold": True, "bg_color": PROFILE_BG})
	role_fmt = book.add_format({"bg_color": ROLE_BG})
	add_fmt = book.add_format({"bg_color": ADD_BG, "italic": True})

	def write_sheet(title, columns, rows, section_formats=None):
		sheet = book.add_worksheet(title)
		for position, (name, width, editable) in enumerate(columns):
			label = f"{name} (EDITABLE)" if editable else name
			sheet.write(0, position, label, edit_head if editable else head)
			sheet.set_column(position, position, width)

		for offset, row in enumerate(rows, start=1):
			fmt = (section_formats or {}).get(row.get("section"))
			for position, (name, _w, _e) in enumerate(columns):
				value = row.get(name)
				if value is None or value == "":
					if fmt:
						sheet.write_blank(offset, position, None, fmt)
					continue
				sheet.write(offset, position, value, fmt) if fmt else sheet.write(
					offset, position, value
				)

		sheet.freeze_panes(1, 2 if "role_profile" in [c[0] for c in columns] else 1)
		if rows:
			sheet.autofilter(0, 0, len(rows), len(columns) - 1)
			names = [c[0] for c in columns]
			for target in ("keep", "status"):
				if target in names:
					column = names.index(target)
					sheet.data_validation(
						1, column, len(rows), column,
						{"validate": "list", "source": KEEP_OPTIONS},
					)

		return sheet

	write_sheet("Overview", OVERVIEW_COLUMNS, overview_rows(data, tabs))
	write_sheet("Profile Index", PROFILE_INDEX_COLUMNS, profile_index_rows(data))

	formats = {
		SECTION_PROFILE: profile_fmt,
		SECTION_ROLE: role_fmt,
		SECTION_ADD: add_fmt,
	}
	for module in sorted(data["by_module"]):
		write_sheet(tabs[module], COLUMNS, module_rows(module, data), formats)

	book.close()

	return path
