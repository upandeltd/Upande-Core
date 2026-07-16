# Copyright (c) 2026, Upande and contributors
# For license information, please see license.txt

import frappe


def execute():
	"""Rows are now Bed records with unit_type = Row.

	- Backfill unit_type on existing Beds.
	- Convert Row records into Beds named identically ("{block} - Row {n}")
	  so Link values (e.g. Orchard Tree.row) stay valid, then remove them.
	"""
	frappe.db.sql("UPDATE `tabBed` SET unit_type = 'Bed' WHERE IFNULL(unit_type, '') = ''")

	if not frappe.db.table_exists("Row"):
		return

	for row in frappe.get_all(
		"Row", fields=["name", "block", "row", "row_length", "geojson"]
	):
		if not frappe.db.exists(
			"Bed", {"greenhouse": row.block, "unit_type": "Row", "bed": row.row}
		):
			bed = frappe.get_doc(
				{
					"doctype": "Bed",
					"greenhouse": row.block,
					"unit_type": "Row",
					"bed": row.row,
					"bed_length": row.row_length,
				}
			)
			# keep migration resilient to incomplete farm-type setups
			bed.flags.ignore_validate = True
			bed.insert(ignore_permissions=True)
		frappe.delete_doc("Row", row.name, force=1, ignore_permissions=True)
