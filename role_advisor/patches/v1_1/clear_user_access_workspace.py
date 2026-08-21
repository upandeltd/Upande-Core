# Copyright (c) 2026, ghost-mann and contributors
# For license information, please see license.txt

"""Reduce the User Access workspace to a single door into the app.

`bench migrate` deliberately leaves an existing Workspace alone - it is a
user-editable document, and overwriting somebody's arrangement on every deploy
would be worse than the alternative. That protection also means the workspace
on an already-installed site keeps the six shortcuts and five link cards it
shipped with, duplicating the app's own sidebar with a second navigation that
can disagree with the first.

The edit is written out here rather than delegated to `frappe.reload_doc`:
reload_doc walks the app's fixtures and needs developer mode, which a
production site does not have, so the patch would fail exactly where it matters.
"""

import json

import frappe

WORKSPACE = "User Access"
ENTRY_PAGE = "access-dashboard"

CONTENT = [
	{
		"id": "ra_head",
		"type": "header",
		"data": {"text": '<span class="h4">Role Advisor</span>', "col": 12},
	},
	{
		"id": "ra_para",
		"type": "paragraph",
		"data": {
			"text": (
				"Users, role profiles, anomalies, requests and the audit trail all "
				"live inside the app. Open it below, or go straight to "
				"<b>/role-advisor</b>."
			),
			"col": 12,
		},
	},
	{"id": "ra_open", "type": "shortcut", "data": {"shortcut_name": "Role Advisor", "col": 4}},
]


def execute():
	if not frappe.db.exists("Workspace", WORKSPACE):
		return

	doc = frappe.get_doc("Workspace", WORKSPACE)
	doc.links = []
	doc.set(
		"shortcuts",
		[{"label": "Role Advisor", "link_to": ENTRY_PAGE, "type": "Page", "color": "Grey"}],
	)
	doc.content = json.dumps(CONTENT)
	doc.save(ignore_permissions=True)
