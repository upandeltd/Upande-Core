# Copyright (c) 2026, ghost-mann and contributors
# For license information, please see license.txt

"""Separate the roles Frappe ships from the ones this site invented.

The distinction matters because the two are governed differently. A shipped role
arrives with an app, is maintained upstream, and is safe to reuse. A local role
was created by somebody here, is maintained by nobody, and is where over-granting
accumulates.

Frappe ships **no Role Profiles at all** - not one, in any installed app. So a
"standard set" of profiles cannot be discovered, only authored. That is what the
Methodology sheet is for.

A role counts as shipped if any installed app declares it, either in a DocType's
`permissions` array (which is how core creates roles) or in a `fixtures/role.json`.
Everything else is local, and the sheet reports who made it and when.
"""

import glob
import json
import os
from collections import defaultdict

import frappe

from role_advisor import capability, taxonomy

HEAD_BG = "#37474F"
EDIT_BG = "#8D6E00"


def shipped_roles() -> dict[str, dict]:
	"""Roles declared by an installed app, with where they came from."""
	shipped: dict[str, dict] = defaultdict(lambda: {"apps": set(), "doctypes": 0, "via": set()})
	bench = os.path.abspath(os.path.join(frappe.get_app_path("frappe"), "..", ".."))

	for app in frappe.get_installed_apps():
		# Roles named in a DocType's permissions are auto-created by core.
		for path in glob.glob(f"{bench}/{app}/**/doctype/*/*.json", recursive=True):
			stem = os.path.basename(path)[:-5]
			if os.path.basename(os.path.dirname(path)) != stem:
				continue
			try:
				meta = json.load(open(path))
			except (ValueError, OSError):
				continue
			if meta.get("doctype") != "DocType":
				continue
			for perm in meta.get("permissions") or []:
				role = perm.get("role")
				if role:
					shipped[role]["apps"].add(app)
					shipped[role]["doctypes"] += 1
					shipped[role]["via"].add("doctype permissions")

		# Some apps ship roles as fixtures instead.
		for path in glob.glob(f"{bench}/{app}/**/fixtures/role.json", recursive=True):
			try:
				records = json.load(open(path))
			except (ValueError, OSError):
				continue
			for record in records if isinstance(records, list) else []:
				role = record.get("name") or record.get("role_name")
				if role:
					shipped[role]["apps"].add(app)
					shipped[role]["via"].add("fixture")

	return shipped


def _role_usage() -> tuple[dict, dict, dict]:
	users = defaultdict(int)
	for row in frappe.get_all("Has Role", filters={"parenttype": "User"}, fields=["role"]):
		users[row["role"]] += 1

	profiles = defaultdict(list)
	for row in frappe.get_all(
		"Has Role", filters={"parenttype": "Role Profile"}, fields=["parent", "role"]
	):
		profiles[row["role"]].append(row["parent"])

	all_roles = frappe.get_all("Role", pluck="name")
	caps = capability._capabilities_from_rows(capability._perm_rows_for_roles(all_roles))

	return users, profiles, caps


def role_rows() -> tuple[list[dict], list[dict]]:
	"""Return (standard, custom) role rows."""
	shipped = shipped_roles()
	users, profiles, caps = _role_usage()

	standard, custom = [], []
	for role in frappe.get_all(
		"Role", fields=["name", "owner", "creation", "disabled", "desk_access"]
	):
		name = role["name"]
		granted = caps.get(name, {})
		common = {
			"role": name,
			"disabled": role["disabled"],
			"desk_access": role["desk_access"],
			"doctypes_granted": len(granted),
			"grants": capability.total_perm_count(granted),
			"users_holding": users.get(name, 0),
			"profiles_using": len(profiles.get(name, [])),
			"used_here": int(bool(users.get(name) or profiles.get(name))),
		}

		if name in shipped:
			info = shipped[name]
			standard.append(
				{
					**common,
					"shipped_by": ", ".join(sorted(info["apps"])),
					"declared_via": ", ".join(sorted(info["via"])),
					"doctypes_declared": info["doctypes"],
					"decision": "",
					"notes": "",
				}
			)
		else:
			custom.append(
				{
					**common,
					"created_by": role["owner"],
					"created_on": str(role["creation"])[:10],
					# A local role nobody holds and no profile uses is dead weight.
					"orphan": int(not (users.get(name) or profiles.get(name))),
					"decision": "",
					"notes": "",
				}
			)

	standard.sort(key=lambda row: (-row["used_here"], -row["grants"], row["role"]))
	custom.sort(key=lambda row: (row["orphan"], -row["users_holding"], row["role"]))

	return standard, custom


def profile_rows() -> list[dict]:
	index = capability.build_capability_index()
	users = defaultdict(int)
	for row in frappe.get_all(
		"User Role Profile", filters={"parenttype": "User"}, fields=["role_profile"]
	):
		users[row["role_profile"]] += 1

	roles = defaultdict(list)
	for row in frappe.get_all(
		"Has Role", filters={"parenttype": "Role Profile"}, fields=["parent", "role"]
	):
		roles[row["parent"]].append(row["role"])

	shipped = shipped_roles()
	rows = []
	for profile in sorted(index):
		members = roles.get(profile, [])
		proposed, issues = taxonomy.canonical_name(profile)
		granted = index[profile]
		rows.append(
			{
				"role_profile": profile,
				"origin": "Local - Frappe ships none",
				"users": users.get(profile, 0),
				"roles": len(members),
				"standard_roles_used": sum(1 for r in members if r in shipped),
				"custom_roles_used": sum(1 for r in members if r not in shipped),
				"doctypes_granted": len(granted),
				"grants": capability.total_perm_count(granted),
				"proposed_name": proposed,
				"naming_issues": ", ".join(issues),
				"decision": "",
				"notes": "",
			}
		)

	return sorted(rows, key=lambda row: -row["users"])


METHODOLOGY = [
	("h", "How to create roles and role profiles as a standard"),
	("p", "Frappe ships 91 roles across the installed apps and zero role profiles. "
	      "So roles are mostly a reuse problem, and profiles are entirely an authoring "
	      "problem. The two need different rules."),

	("h2", "The naming standard"),
	("p", "Job Family | Variant | Scope — omitting any part that does not apply."),
	("code", "Agriculture Production Supervisor | Approver | Simotwo\n"
	         "Sales | Restricted\n"
	         "Stores | | Endebess"),
	("p", "Job Family is the job. Variant is what makes this version of the job different "
	      "from its siblings — Approver, Restricted, Temporary. Scope is a place: a company, "
	      "farm or branch. The pipe is deliberate: the existing names already use ' - ' and "
	      "'-' inconsistently, so a fresh separator makes old and new instantly "
	      "distinguishable."),
	("p", "Seniority words — Supervisor, Manager, Clerk, Head — belong in the Job Family, not "
	      "the Variant. Production Supervisor and Farm Manager are different jobs, not "
	      "different authority levels of one job."),

	("h2", "Rules for creating a Role"),
	("n", "Reuse before you create. There are 91 shipped roles; check the Standard Roles "
	      "sheet first. A shipped role is maintained upstream, a local one is maintained by "
	      "nobody."),
	("n", "A role names a capability, never a person, a job title or a place. 'Harvest "
	      "Approver' is a role. 'Simotwo Supervisor' is not — that is a job in a place, which "
	      "is a profile."),
	("n", "A role belongs to one module wherever possible. Half the local roles already touch "
	      "only one module; that is the pattern to keep, because it gives the module owner "
	      "something they can actually own."),
	("n", "Never add a Custom DocPerm for one role on a doctype without listing every role on "
	      "that doctype. If any Custom DocPerm exists for a doctype, Frappe discards that "
	      "doctype's standard permissions for every role — so a partial edit silently removes "
	      "access from roles nobody was thinking about."),
	("n", "Set every right explicitly, including the ones you are denying. Custom DocPerm "
	      "defaults read and export to 1, so listing only what you want grants export too."),

	("h2", "Rules for creating a Role Profile"),
	("n", "One profile per job that genuinely differs in access. If two profiles grant the "
	      "same thing, they are one profile with two names — check the Role Profile Overgrant "
	      "report before adding another."),
	("n", "Build it from roles, never from raw permissions. Permissions attach to roles; a "
	      "profile is only a bundle."),
	("n", "Put place in User Permission, not in the profile, unless the permissions themselves "
	      "differ by place. A Store Clerk at Endebess and one at Ravine doing the same job "
	      "with different data need one profile and two User Permissions, not two profiles."),
	("n", "Every profile needs a named owner and a Designation Access Map row, so the next "
	      "person to hold that job gets it automatically and the reasoning is recorded."),
	("n", "Assign it through the User Access Console and read the preview. Assigning replaces "
	      "the previous profile rather than adding to it, so check the 'loses' list."),

	("h2", "The lifecycle"),
	("n", "Someone requests access that no existing profile covers."),
	("n", "Check Role Profile Overgrant for an existing profile that already fits."),
	("n", "If roles are missing, the relevant module owner defines them on their module's "
	      "doctypes."),
	("n", "Assemble the profile from those roles, named to the standard above."),
	("n", "Record it against the job title in Designation Access Map, with the reasoning."),
	("n", "Assign via the console. The Access Assignment Log records it permanently."),
	("n", "Re-run the reports. A new profile should not appear in the duplicate or privileged "
	      "columns."),

	("h2", "What to stop doing"),
	("b", "Creating a profile per farm when only the data differs, not the permissions."),
	("b", "Adding a suffix to an existing profile name instead of checking whether the access "
	      "actually differs — this produced three identical Upande Team profiles."),
	("b", "Giving System Manager because someone needs to manage users. That is what a "
	      "Delegated User Admin record is for."),
	("b", "Leaving a role with no permissions attached. Security Guard grants nothing and 16 "
	      "people hold it."),
]


def build(path: str | None = None) -> str:
	"""Write the standards workbook and return its path."""
	import xlsxwriter

	if not path:
		app_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
		docs = os.path.join(app_dir, "docs")
		os.makedirs(docs, exist_ok=True)
		path = os.path.join(docs, "Frappe v16 Roles and Profiles - Standard.xlsx")

	standard, custom = role_rows()
	profiles = profile_rows()

	book = xlsxwriter.Workbook(path)
	head = book.add_format({"bold": True, "bg_color": HEAD_BG, "font_color": "white", "border": 1})
	edit = book.add_format({"bold": True, "bg_color": EDIT_BG, "font_color": "white", "border": 1})
	h1 = book.add_format({"bold": True, "font_size": 15, "font_color": "#1F3346"})
	h2 = book.add_format({"bold": True, "font_size": 12, "font_color": "#1F3346"})
	body = book.add_format({"text_wrap": True, "valign": "top"})
	mono = book.add_format({"font_name": "Consolas", "font_size": 10, "text_wrap": True, "valign": "top"})

	def sheet(title, columns, rows):
		ws = book.add_worksheet(title)
		for i, (name, width, editable) in enumerate(columns):
			ws.write(0, i, f"{name} (EDITABLE)" if editable else name, edit if editable else head)
			ws.set_column(i, i, width)
		for r, row in enumerate(rows, start=1):
			for i, (name, _w, _e) in enumerate(columns):
				value = row.get(name)
				if value not in (None, ""):
					ws.write(r, i, value)
		ws.freeze_panes(1, 1)
		if rows:
			ws.autofilter(0, 0, len(rows), len(columns) - 1)
			names = [c[0] for c in columns]
			if "decision" in names:
				col = names.index("decision")
				ws.data_validation(1, col, len(rows), col,
				                   {"validate": "list",
				                    "source": ["Reuse", "Rename", "Retire", "Keep", "Investigate"]})
		return ws

	# Methodology first: it is the point of the workbook.
	ws = book.add_worksheet("Methodology")
	ws.set_column(0, 0, 110)
	row = 0
	for kind, text in METHODOLOGY:
		if kind == "h":
			ws.write(row, 0, text, h1)
		elif kind == "h2":
			row += 1
			ws.write(row, 0, text, h2)
		elif kind == "code":
			ws.write(row, 0, text, mono)
			ws.set_row(row, 46)
		elif kind == "n":
			ws.write(row, 0, "•  " + text, body)
			ws.set_row(row, 30)
		elif kind == "b":
			ws.write(row, 0, "✕  " + text, body)
			ws.set_row(row, 30)
		else:
			ws.write(row, 0, text, body)
			ws.set_row(row, 44)
		row += 1

	sheet("Standard Roles", (
		("role", 34, 0), ("shipped_by", 34, 0), ("declared_via", 20, 0),
		("doctypes_declared", 17, 0), ("doctypes_granted", 17, 0), ("grants", 9, 0),
		("users_holding", 14, 0), ("profiles_using", 14, 0), ("used_here", 11, 0),
		("disabled", 9, 0), ("desk_access", 12, 0), ("decision", 13, 1), ("notes", 40, 1),
	), standard)

	sheet("Custom Roles", (
		("role", 34, 0), ("created_by", 26, 0), ("created_on", 12, 0),
		("doctypes_granted", 17, 0), ("grants", 9, 0), ("users_holding", 14, 0),
		("profiles_using", 14, 0), ("orphan", 9, 0), ("disabled", 9, 0),
		("desk_access", 12, 0), ("decision", 13, 1), ("notes", 40, 1),
	), custom)

	sheet("Role Profiles", (
		("role_profile", 46, 0), ("origin", 26, 0), ("users", 8, 0), ("roles", 8, 0),
		("standard_roles_used", 19, 0), ("custom_roles_used", 18, 0),
		("doctypes_granted", 17, 0), ("grants", 9, 0), ("proposed_name", 48, 0),
		("naming_issues", 30, 0), ("decision", 13, 1), ("notes", 40, 1),
	), profiles)

	book.close()

	print(f"{len(standard)} standard roles, {len(custom)} custom roles, {len(profiles)} profiles")
	print(path)

	return path
