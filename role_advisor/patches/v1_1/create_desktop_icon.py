# Copyright (c) 2026, ghost-mann and contributors
# For license information, please see license.txt

"""Put Role Advisor on the desk home of an already-installed site.

Frappe builds the desk home from `Desktop Icon` records, generated from the
`add_to_apps_screen` hook by its own `after_app_install` hook. A fresh install
therefore needs nothing - but a site that installed this app before the hook
existed has no icon and no way to get one, which is exactly the site this
patch is for.

There is a second half. Once a user has arranged their desk home, Frappe
stores that arrangement as a `Desktop Layout` snapshot and renders from the
snapshot instead of the live icon list, so a newly created icon stays
invisible to everyone who has ever touched their home screen. The icon is
therefore appended to each existing layout as well - at the end, so nobody's
arrangement moves.

Deliberately narrow throughout: one icon, for this app.
`create_desktop_icons_from_installed_apps` would walk every installed app, and
a role_advisor patch has no business creating icons for anybody else.
"""

import json

import frappe

APP = "role_advisor"
LABEL = "Role Advisor"


def execute():
	_create_icon()
	_add_to_saved_layouts()


def _create_icon():
	entries = frappe.get_hooks("add_to_apps_screen", app_name=APP)
	if not entries:
		return

	entry = entries[0]
	if frappe.db.exists("Desktop Icon", {"icon_type": "App", "app": APP}):
		return
	if frappe.db.exists("Desktop Icon", {"icon_type": "App", "label": entry["title"]}):
		return

	frappe.get_doc(
		{
			"doctype": "Desktop Icon",
			"label": entry["title"],
			"bg_color": "gray",
			"icon_type": "App",
			"link_type": "External",
			"app": APP,
			"link": entry["route"],
			"logo_url": entry["logo"],
			# `standard` is deliberately left unset. Setting it makes Frappe try
			# to write the icon back out as an app fixture, which needs developer
			# mode - so the patch would fail on exactly the production sites it
			# exists for.
		}
	).insert(ignore_permissions=True, ignore_if_duplicate=True)


def _add_to_saved_layouts() -> None:
	"""Append the icon to every stored desk arrangement that lacks it."""
	icon = frappe.db.get_value(
		"Desktop Icon",
		{"icon_type": "App", "app": APP},
		[
			"name",
			"label",
			"bg_color",
			"link",
			"link_type",
			"app",
			"icon_type",
			"parent_icon",
			"icon",
			"link_to",
			"idx",
			"standard",
			"logo_url",
			"hidden",
			"restrict_removal",
			"icon_image",
		],
		as_dict=True,
	)
	if not icon:
		return

	entry = {**icon, "child_icons": []}

	for name in frappe.get_all("Desktop Layout", pluck="name"):
		doc = frappe.get_doc("Desktop Layout", name)
		try:
			layout = json.loads(doc.layout or "[]")
		except ValueError:
			continue

		if not isinstance(layout, list):
			continue
		if any(row.get("name") == LABEL for row in layout if isinstance(row, dict)):
			continue

		layout.append(entry)
		doc.layout = json.dumps(layout)
		doc.save(ignore_permissions=True)
