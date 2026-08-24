# Copyright (c) 2026, Upande and contributors
# For license information, please see license.txt

"""Rebuild the IT Operations desk sidebar around the one page.

The sidebar was generated when there were four portal pages, so it still lists
System Activity, Workforce and Monitor Config as separate destinations. Three of
those pages no longer exist - their routes redirect - so the entries work but
name things that are gone and duplicate the workspace's own shortcuts.

`Workspace Sidebar` is site data rather than an app fixture (standard = 0), so
this is a patch rather than a JSON file. It is written to be idempotent: it
reconciles the item list against what the page actually has, so running it again
after the page changes is the way to keep them in step.
"""

import frappe

SIDEBAR = "IT Operations"

# label, kind, target
ITEMS = [
	("Home", "workspace", "IT Operations"),
	("Dashboard", "url", "/it-dashboard"),
	("Anomalies", "url", "/it-dashboard#anomalies"),
	("Grant Access", "url", "/it-dashboard#assign"),
	("Incoming Requests", "url", "/it-dashboard#queue"),
	("Workforce", "url", "/it-dashboard#workforce"),
	("System Health", "url", "/it-dashboard#health"),
	("My Access", "url", "/my-access"),
	("Records", "section", None),
	("Issues", "doctype", "Issue"),
	("Assets", "doctype", "Asset"),
	("Users", "doctype", "User"),
	("Role Profiles", "doctype", "Role Profile"),
	("Access Requests", "doctype", "Access Request"),
	("Assignment Log", "doctype", "Access Assignment Log"),
	("Error Log", "doctype", "Error Log"),
	("Monitored Doctype", "doctype", "Monitored Doctype"),
]


def execute():
	if not frappe.db.exists("Workspace Sidebar", SIDEBAR):
		return

	doc = frappe.get_doc("Workspace Sidebar", SIDEBAR)
	rows = []

	for label, kind, target in ITEMS:
		if kind == "section":
			rows.append({"label": label, "type": "Section Break", "link_type": "DocType"})
		elif kind == "workspace":
			rows.append(
				{"label": label, "type": "Link", "link_type": "Workspace", "link_to": target}
			)
		elif kind == "url":
			rows.append({"label": label, "type": "Link", "link_type": "URL", "url": target})
		elif kind == "doctype":
			# A link to a doctype that is not installed renders as a dead entry.
			if not frappe.db.exists("DocType", target):
				continue
			rows.append(
				{"label": label, "type": "Link", "link_type": "DocType", "link_to": target}
			)

	doc.set("items", rows)
	doc.save(ignore_permissions=True)
