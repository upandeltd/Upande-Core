# Copyright (c) 2026, Upande and contributors
# For license information, please see license.txt

"""Install-time setup.

Seeding must happen here, never from a patch: `frappe.installer.install_app`
calls `set_all_patches_as_completed(app)` on a fresh install, marking every
patches.txt entry as run without executing it - so a seed patch never fires,
and `bench migrate` then skips it forever too.
"""

import json

import frappe

from upande_core.settings import PRIVILEGED_DOCTYPE_DEFAULTS


def after_install():
	seed_settings()
	frappe.db.commit()


def after_migrate():
	ensure_warehouse_field_order()
	# Idempotent, and needed on every site that had the access doctypes before
	# they were folded into this app - their install hook never ran here.
	seed_settings()


def seed_settings():
	"""Populate `User Access Settings` child tables. Idempotent."""
	doc = frappe.get_single("User Access Settings")

	existing = {row.document_type for row in doc.get("privileged_doctypes") or []}
	for doctype in PRIVILEGED_DOCTYPE_DEFAULTS:
		if doctype not in existing and frappe.db.exists("DocType", doctype):
			doc.append("privileged_doctypes", {"document_type": doctype})

	doc.save(ignore_permissions=True)


def ensure_warehouse_field_order():
	"""Keep warehouse_type right next to the Farm field on Warehouse.

	warehouse_type is a standard ERPNext field, so its position is controlled
	with a doctype-level field_order Property Setter, computed from the live
	meta so it stays correct across ERPNext upgrades."""
	meta = frappe.get_meta("Warehouse")
	order = [df.fieldname for df in meta.fields]
	if "warehouse_type" not in order or "custom_farm" not in order:
		return
	order.remove("warehouse_type")
	order.insert(order.index("custom_farm") + 1, "warehouse_type")

	frappe.make_property_setter(
		{
			"doctype": "Warehouse",
			"doctype_or_field": "DocType",
			"property": "field_order",
			"value": json.dumps(order),
			"property_type": "Data",
		},
		is_system_generated=False,
	)
	frappe.clear_cache(doctype="Warehouse")
