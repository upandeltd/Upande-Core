# Copyright (c) 2026, Upande and contributors
# For license information, please see license.txt

"""Animated marks for the Packhouse, Production and Quality apps-screen tiles.

The tiles exist already (they are made from each app's workspace, as site data) and show a plain letter. This gives them
the same kind of mark as Upande CRM, Work Management and Irrigation: an animated SVG that rests as the Upande badge. It
only sets `logo_url` on a tile that is there, so a site without that app gets nothing, and it runs on every migrate so a
tile that was recreated gets its mark back.

A user who has rearranged their apps screen holds a snapshot of each tile's fields (`Desktop Layout`), so the snapshot is
brought in line too.
"""

import json

import frappe

MARKS = {
	"Packhouse": "/assets/upande_core/images/upande-packhouse-logo.svg",
	"Roses Production": "/assets/upande_core/images/upande-production-logo.svg",
	"Upande Quality": "/assets/upande_core/images/upande-quality-logo.svg",
}


def sync():
	if not frappe.db.exists("DocType", "Desktop Icon"):
		return
	changed = False
	for label, logo in MARKS.items():
		if frappe.db.exists("Desktop Icon", label) and frappe.db.get_value("Desktop Icon", label, "logo_url") != logo:
			frappe.db.set_value("Desktop Icon", label, "logo_url", logo, update_modified=False)
			changed = True
	if frappe.db.exists("DocType", "Desktop Layout"):
		for name in frappe.get_all("Desktop Layout", pluck="name"):
			layout = frappe.db.get_value("Desktop Layout", name, "layout")
			try:
				rows = json.loads(layout or "[]")
			except ValueError:
				continue
			if not isinstance(rows, list):
				continue
			touched = False
			for row in rows:
				if isinstance(row, dict) and row.get("name") in MARKS and row.get("logo_url") != MARKS[row["name"]]:
					row["logo_url"] = MARKS[row["name"]]
					touched = True
			if touched:
				frappe.db.set_value("Desktop Layout", name, "layout", json.dumps(rows), update_modified=False)
				changed = True
	if changed:
		frappe.cache.delete_value("desktop_icons")
		frappe.db.commit()
