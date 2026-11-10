# Copyright (c) 2026, Upande and contributors
# For license information, please see license.txt

"""The IT Dashboard workspace, in the Upande CRM design.

The same four pieces the Upande CRM app uses, so the two read as one family:

  * an animated apps-screen tile (`upande-it-logo.svg`: a monitor's pulse line, the Upande arrow rises out of the screen,
    then it rests as the plain Upande badge);
  * a tile that opens the workspace's *sidebar* rather than a page;
  * a desk sidebar of sections with icons, shipped as the `IT Dashboard` module's Sidebar
    (`it_dashboard/sidebar/it_dashboard/it_dashboard.json`; this frappe keeps navigation per module, and the old Workspace
    Sidebar is a read-only archive);
  * a workspace body that is a Custom HTML Block tile grid, with live counts on the record tiles.

All of it is site data (`standard = 0`), written from here on every migrate rather than shipped as fixtures: `bench migrate`
leaves an existing Workspace alone, `frappe.reload_doc` needs developer mode, and a standard Desktop Icon without a fixture
file is a candidate for deletion on the next sync. The files in this app are the source of truth, so anyone editing the
block or the sidebar in the UI should expect the next migrate to reset it.

Idempotent, and safe on a site that never had the old IT Operations workspace: it creates the new one.
"""

import json
import os

import frappe

APP = "upande_core"
OLD = "IT Operations"
NAME = "IT Dashboard"
LOGO = "/assets/upande_core/images/upande-it-logo.svg"
NAV_BLOCK = "IT Dashboard Navigation"
_BLOCK_SLUG = "it_dashboard_navigation"


def sync():
	_rename_old()
	_nav_block()
	_workspace()
	_desktop_icon()
	frappe.db.commit()


def _rename_old():
	if frappe.db.exists("Workspace", OLD) and not frappe.db.exists("Workspace", NAME):
		frappe.rename_doc("Workspace", OLD, NAME, force=True)


def _nav_block():
	base = os.path.join(os.path.dirname(__file__), "custom_html_block", _BLOCK_SLUG)
	src = {}
	for field, ext in (("html", "html"), ("style", "css"), ("script", "js")):
		with open(f"{base}.{ext}", encoding="utf-8") as fh:
			src[field] = fh.read()
	if frappe.db.exists("Custom HTML Block", NAV_BLOCK):
		doc = frappe.get_doc("Custom HTML Block", NAV_BLOCK)
	else:
		doc = frappe.new_doc("Custom HTML Block")
		doc.name = NAV_BLOCK
	doc.update(src)
	# Public: per-tile gating happens in the block's own script, and the dashboard page gates itself.
	doc.private = 0
	doc.set("roles", [])
	doc.save(ignore_permissions=True)


def _workspace():
	if frappe.db.exists("Workspace", NAME):
		doc = frappe.get_doc("Workspace", NAME)
	else:
		doc = frappe.new_doc("Workspace")
		doc.name = NAME
		doc.public = 1
		doc.sequence_id = 1
	# The module owns the sidebar (shipped in it_dashboard/sidebar/), so the workspace belongs to it.
	if frappe.db.exists("Module Def", NAME):
		doc.module = NAME
	elif not doc.module:
		doc.module = "Upande Core"
	doc.label = NAME
	doc.title = NAME
	doc.icon = "monitor"
	doc.is_hidden = 0
	doc.set("shortcuts", [])
	doc.set("links", [])
	doc.set("custom_blocks", [{"custom_block_name": NAV_BLOCK, "label": NAV_BLOCK}])
	doc.content = json.dumps(
		[{"id": "itnav", "type": "custom_block", "data": {"custom_block_name": NAV_BLOCK, "col": 12}}]
	)
	doc.save(ignore_permissions=True)


def _desktop_icon():
	"""The apps-screen tile: opens the sidebar in the same tab, wearing the animated mark. Reconciles the stored layouts
	too, which hold a copy of each icon's fields (see patches/it_operations_desktop_icon.py)."""
	if not frappe.db.exists("DocType", "Desktop Icon"):
		return
	name = frappe.db.get_value("Desktop Icon", {"icon_type": "App", "app": APP}, "name")
	# The label is the document's name and cannot be edited in place, so an icon still called after the app is renamed.
	if name and name != NAME and not frappe.db.exists("Desktop Icon", NAME):
		frappe.rename_doc("Desktop Icon", name, NAME, force=True)
		name = NAME
	doc = frappe.get_doc("Desktop Icon", name) if name else frappe.new_doc("Desktop Icon")
	wanted = {
		"label": NAME,
		"app": APP,
		"icon_type": "App",
		"bg_color": "gray",
		# Opens the sidebar's first link in the same tab. An External link is origin-prefixed, so the desk treats it as http
		# and opens a new tab.
		"link_type": "Workspace Sidebar",
		"link_to": NAME,
		# Not used for navigation (link_type wins), but Frappe builds icons from workspaces with .startswith() on an
		# App icon's `link`; None there aborts icon generation for later workspaces.
		"link": "/desk/it-dashboard",
		"logo_url": LOGO,
	}
	if not doc.is_new() and all(doc.get(k) == v for k, v in wanted.items()):
		icon = doc
	else:
		doc.update(wanted)
		doc.save(ignore_permissions=True)
		frappe.cache.delete_value("desktop_icons")
		icon = doc

	# The workspace-generated tile the rename left behind points at a workspace that is no longer called that.
	for stale in frappe.get_all("Desktop Icon", filters={"link_to": OLD, "icon_type": ["!=", "App"]}, pluck="name"):
		frappe.delete_doc("Desktop Icon", stale, force=True, ignore_permissions=True)

	from upande_core.patches import it_operations_desktop_icon as layouts

	row = frappe.db.get_value("Desktop Icon", icon.name, layouts.FIELDS, as_dict=True)
	if row:
		layouts._fix_layouts(row)
