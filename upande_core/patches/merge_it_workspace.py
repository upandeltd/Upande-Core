# Copyright (c) 2026, Upande and contributors
# For license information, please see license.txt

"""Point the IT Operations workspace at the one page, and fold Access in.

Two things make this a patch rather than a fixture change. `bench migrate`
deliberately leaves an existing Workspace alone - it is user-editable, and
overwriting somebody's arrangement on every deploy would be worse than the
alternative - so a site that already has this workspace keeps the four
shortcuts to the four portal pages that no longer exist. And `frappe.reload_doc`
is not an option: it walks the app's fixtures and needs developer mode, which a
production site does not have, so the patch would fail exactly where it matters.

The workspace is written out here from the same shape as the fixture, so the two
cannot drift.
"""

import json

import frappe

WORKSPACE = "IT Operations"

SHORTCUTS = [
	("IT Operations", "/it-dashboard"),
	("Anomalies", "/it-dashboard#anomalies"),
	("Grant Access", "/it-dashboard#assign"),
	("Incoming Requests", "/it-dashboard#queue"),
	("Helpdesk", "/it-dashboard#helpdesk"),
	("System Health", "/it-dashboard#health"),
	("My Access", "/my-access"),
]

CARDS = [
	("Helpdesk", ["Issue", "Issue Type", "Issue Priority"], False),
	(
		"Access",
		[
			"Designation Access Map",
			"Delegated User Admin",
			"Access Assignment Log",
			"Access Request",
			"User Access Settings",
		],
		False,
	),
	("Identity", ["User", "Role", "Role Profile", "Employee"], False),
	("Infrastructure", ["Asset", "Asset Category"], False),
	(
		"Monitoring",
		["Error Log", "Activity Log", "Access Log", "Monitored Doctype", "Monitored Category"],
		False,
	),
	(
		"Reports",
		[
			"Designation Gap",
			"Module Exposure",
			"Role Drift",
			"System Manager Audit",
			"Role Profile Overgrant",
		],
		True,
	),
]


def execute():
	if not frappe.db.exists("Workspace", WORKSPACE):
		return

	doc = frappe.get_doc("Workspace", WORKSPACE)

	doc.set(
		"shortcuts",
		[
			{"label": label, "type": "URL", "url": url, "color": "Grey"}
			for label, url in SHORTCUTS
		],
	)

	links = []
	for card, members, is_report in CARDS:
		# A link to a doctype or report that is not installed renders as a dead
		# entry, so each is checked rather than assumed.
		present = [
			name
			for name in members
			if frappe.db.exists("Report" if is_report else "DocType", name)
		]
		if not present:
			continue
		links.append({"type": "Card Break", "label": card, "link_count": len(present)})
		links.extend(
			{
				"type": "Link",
				"label": name,
				"link_to": name,
				"link_type": "Report" if is_report else "DocType",
				"is_query_report": 1 if is_report else 0,
			}
			for name in present
		)
	doc.set("links", links)

	blocks = [
		{"id": "it_hd", "type": "header", "data": {"text": '<span class="h4"><b>IT Operations</b></span>', "col": 12}},
		{
			"id": "it_p",
			"type": "paragraph",
			"data": {
				"text": (
					"Access, helpdesk, infrastructure, monitoring, attendance and "
					"configuration are all one page at <b>/it-dashboard</b>. The "
					"records behind it are below."
				),
				"col": 12,
			},
		},
	]
	blocks += [
		{"id": f"sc{n}", "type": "shortcut", "data": {"shortcut_name": label, "col": 3}}
		for n, (label, _url) in enumerate(SHORTCUTS)
	]
	blocks.append({"id": "sp", "type": "spacer", "data": {"col": 12}})
	blocks.append(
		{"id": "hdr2", "type": "header", "data": {"text": '<span class="h4"><b>Records</b></span>', "col": 12}}
	)
	blocks += [
		{"id": f"c{n}", "type": "card", "data": {"card_name": card, "col": 4}}
		for n, (card, _m, _r) in enumerate(CARDS)
	]

	doc.content = json.dumps(blocks)
	doc.save(ignore_permissions=True)
