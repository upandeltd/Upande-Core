# Copyright (c) 2026, Upande and contributors
# For license information, please see license.txt

import json

import frappe


def after_migrate():
	ensure_warehouse_field_order()


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
