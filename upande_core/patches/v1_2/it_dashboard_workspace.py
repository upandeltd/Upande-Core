# Copyright (c) 2026, Upande and contributors
# For license information, please see license.txt

"""The IT Dashboard workspace, wearing the Upande mark.

The workspace used to be called IT Operations and pointed at the Role Advisor page. The page is now the IT dashboard
(updates, devices, crashes, support, apps, users, roles, permissions), so the workspace is renamed with it, and the
desk sidebar and the apps-screen tile follow.

A patch rather than a fixture, for the reason `merge_it_workspace` gives: `bench migrate` leaves an existing Workspace
alone, and `frappe.reload_doc` needs developer mode. It reconciles rather than appends, so running it again after the
page changes is the way to keep them in step. Safe on a site that never had the old workspace: it creates the new one.
"""

import json

import frappe

OLD = "IT Operations"
NEW = "IT Dashboard"
LOGO = "/assets/upande_core/images/upande-logo.png"

# label, url
SCREENS = [
	("Overview", "/it-dashboard#/overview"),
	("Updates", "/it-dashboard#/updates"),
	("Devices", "/it-dashboard#/devices"),
	("Crashlytics", "/it-dashboard#/crashlytics"),
	("Support", "/it-dashboard#/support"),
	("Apps", "/it-dashboard#/apps"),
	("User management", "/it-dashboard#/users"),
	("Role management", "/it-dashboard#/roles"),
	("Doctype permissions", "/it-dashboard#/permissions"),
	("User permissions", "/it-dashboard#/userperms"),
	("App store", "/app-store"),
]

# card, doctypes
CARDS = [
	("Mobile apps", ["Mobile App", "Mobile App Install", "Mobile Issue", "Mobile Event", "Mobile Report", "Mobile Reminder"]),
	("People and access", ["User", "Role", "Role Profile", "User Permission", "Custom DocPerm"]),
	("Support", ["Issue"]),
]


def execute():
	_workspace()
	_sidebar()
	_apps_screen_tile()


def _present(names):
	# A link to a doctype that is not installed renders as a dead entry.
	return [n for n in names if frappe.db.exists("DocType", n)]


def _rename(doctype):
	if frappe.db.exists(doctype, OLD) and not frappe.db.exists(doctype, NEW):
		frappe.rename_doc(doctype, OLD, NEW, force=True)


def _workspace():
	_rename("Workspace")
	if frappe.db.exists("Workspace", NEW):
		doc = frappe.get_doc("Workspace", NEW)
	else:
		doc = frappe.new_doc("Workspace")
		doc.name = NEW
		doc.public = 1
		doc.module = "Upande Core"
		doc.icon = "tool"
		doc.sequence_id = 1

	doc.label = NEW
	doc.title = NEW
	doc.is_hidden = 0
	doc.set("shortcuts", [{"label": label, "type": "URL", "url": url, "color": "Grey"} for label, url in SCREENS])

	links = []
	for card, members in CARDS:
		present = _present(members)
		if not present:
			continue
		links.append({"type": "Card Break", "label": card, "link_count": len(present)})
		links.extend({"type": "Link", "label": n, "link_to": n, "link_type": "DocType", "is_query_report": 0} for n in present)
	doc.set("links", links)

	blocks = [
		{
			"id": "itd_logo",
			"type": "paragraph",
			"data": {"text": f'<img src="{LOGO}" alt="Upande" height="56" style="height:56px;width:auto">', "col": 12},
		},
		{"id": "itd_h", "type": "header", "data": {"text": '<span class="h4"><b>IT Dashboard</b></span>', "col": 12}},
		{
			"id": "itd_p",
			"type": "paragraph",
			"data": {
				"text": (
					"Updates, devices, crashes and support for the mobile apps, and the people, roles and "
					"permissions of the IT team, are one page at <b>/it-dashboard</b>. The records behind it are below."
				),
				"col": 12,
			},
		},
	]
	blocks += [{"id": f"sc{n}", "type": "shortcut", "data": {"shortcut_name": label, "col": 3}} for n, (label, _u) in enumerate(SCREENS)]
	blocks.append({"id": "sp", "type": "spacer", "data": {"col": 12}})
	blocks.append({"id": "hdr2", "type": "header", "data": {"text": '<span class="h4"><b>Records</b></span>', "col": 12}})
	blocks += [{"id": f"c{n}", "type": "card", "data": {"card_name": card, "col": 4}} for n, (card, _m) in enumerate(CARDS) if _present(_m)]
	doc.content = json.dumps(blocks)

	doc.flags.ignore_permissions = True
	doc.save() if not doc.is_new() else doc.insert()


def _sidebar():
	_rename("Workspace Sidebar")
	if frappe.db.exists("Workspace Sidebar", NEW):
		doc = frappe.get_doc("Workspace Sidebar", NEW)
	else:
		doc = frappe.new_doc("Workspace Sidebar")
		doc.title = NEW
		doc.header_icon = "layout-dashboard"

	rows = [{"label": "Home", "type": "Link", "link_type": "Workspace", "link_to": NEW}]
	rows.append({"label": "Dashboard", "type": "Section Break", "link_type": "DocType"})
	rows += [
		{"label": label, "type": "Link", "link_type": "URL", "url": url, "child": 1}
		for label, url in SCREENS
	]
	rows.append({"label": "Records", "type": "Section Break", "link_type": "DocType"})
	for card, members in CARDS:
		for name in _present(members):
			rows.append({"label": name, "type": "Link", "link_type": "DocType", "link_to": name, "child": 1})
	doc.set("items", rows)
	doc.flags.ignore_permissions = True
	doc.save() if not doc.is_new() else doc.insert()


def _apps_screen_tile():
	# Reconciles the tile's label, route and logo from add_to_apps_screen, and every stored layout's copy of it.
	from upande_core.patches import it_operations_desktop_icon

	it_operations_desktop_icon.execute()
