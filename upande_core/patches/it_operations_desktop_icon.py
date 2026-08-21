# Copyright (c) 2026, Upande and contributors
# For license information, please see license.txt

"""One tile for IT Operations, and none for the page it replaced.

Frappe builds the apps screen from `Desktop Icon` records, generated from
`add_to_apps_screen` by its own `after_app_install` hook - so a fresh install
needs nothing. A site that already has the old role_advisor tile does: it
points at a desk page that is no longer the UI, and two tiles onto one page is
the confusing part.

There is a second half. Once somebody has arranged their apps screen, Frappe
renders a stored `Desktop Layout` snapshot instead of the live icon list, so a
deleted icon keeps showing and a new one stays invisible. Both are handled here.
"""

import json

import frappe

OLD_APP = "role_advisor"
OLD_LABEL = "Role Advisor"

FIELDS = [
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
]


def execute():
	_drop_old()
	icon = _ensure_new()
	if icon:
		_fix_layouts(icon)


def _drop_old() -> None:
	for name in frappe.get_all(
		"Desktop Icon", filters={"icon_type": "App", "app": OLD_APP}, pluck="name"
	):
		frappe.delete_doc("Desktop Icon", name, force=True, ignore_permissions=True)


def _ensure_new() -> dict | None:
	entries = frappe.get_hooks("add_to_apps_screen", app_name="upande_core")
	if not entries:
		return None
	entry = entries[0]

	if not frappe.db.exists("Desktop Icon", {"icon_type": "App", "app": "upande_core"}):
		frappe.get_doc(
			{
				"doctype": "Desktop Icon",
				"label": entry["title"],
				"icon_type": "App",
				"link_type": "External",
				"app": "upande_core",
				"link": entry["route"],
				"logo_url": entry["logo"],
				"bg_color": "gray",
				# `standard` is deliberately unset: setting it makes Frappe write
				# the icon back out as an app fixture, which needs developer mode,
				# so the patch would fail on exactly the production sites it is for.
			}
		).insert(ignore_permissions=True, ignore_if_duplicate=True)

	return frappe.db.get_value(
		"Desktop Icon", {"icon_type": "App", "app": "upande_core"}, FIELDS, as_dict=True
	)


def _fix_layouts(icon: dict) -> None:
	"""Drop the old tile from every stored arrangement and add the new one."""
	entry = {**icon, "child_icons": []}

	for name in frappe.get_all("Desktop Layout", pluck="name"):
		doc = frappe.get_doc("Desktop Layout", name)
		try:
			layout = json.loads(doc.layout or "[]")
		except ValueError:
			continue
		if not isinstance(layout, list):
			continue

		kept = [
			row
			for row in layout
			if isinstance(row, dict)
			and row.get("app") != OLD_APP
			and row.get("name") != OLD_LABEL
		]
		if not any(row.get("app") == "upande_core" for row in kept):
			kept.append(entry)

		if kept != layout:
			doc.layout = json.dumps(kept)
			doc.save(ignore_permissions=True)
