# Copyright (c) 2026, ghost-mann and contributors
# For license information, please see license.txt

"""Hide the User Access workspace; IT Operations covers it now.

The dashboard moved to upande_core's portal page, so two workspaces pointing at
the same work is one too many. This app still owns the doctypes and reports
behind it, so the workspace is hidden rather than deleted - and written out here
rather than reloaded, because `bench migrate` leaves an existing Workspace alone
and `reload_doc` needs developer mode.
"""

import json

import frappe

WORKSPACE = "User Access"
TARGET = "/it-dashboard"


def execute():
	if not frappe.db.exists("Workspace", WORKSPACE):
		return

	doc = frappe.get_doc("Workspace", WORKSPACE)
	doc.is_hidden = 1
	doc.set("links", [])
	doc.set(
		"shortcuts",
		[{"label": "IT Operations", "type": "URL", "url": TARGET, "color": "Grey"}],
	)
	doc.content = json.dumps(
		[
			{"id": "ra_head", "type": "header",
			 "data": {"text": '<span class="h4">Moved</span>', "col": 12}},
			{"id": "ra_p", "type": "paragraph",
			 "data": {"text": (
				 "Access management is part of <b>IT Operations</b> now, at "
				 "<b>/it-dashboard</b>."
			 ), "col": 12}},
			{"id": "ra_sc", "type": "shortcut",
			 "data": {"shortcut_name": "IT Operations", "col": 4}},
		]
	)
	doc.save(ignore_permissions=True)
