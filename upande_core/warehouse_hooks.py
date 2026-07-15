# Copyright (c) 2026, Upande and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.rename_doc import rename_doc


def sync_farm_structure(doc, method=None):
	"""On Warehouse save: create/update Section records from the sections child
	table and auto-create the Beds in each range (or 1..number_of_beds for
	farms without sections)."""
	if not doc.custom_farm or doc.warehouse_type not in ("Greenhouse", "Block"):
		return

	levels = set(
		frappe.get_all(
			"Farm Type Item",
			filters={"parenttype": "Farm", "parent": doc.custom_farm},
			pluck="farm_type",
		)
	)
	created_beds = 0

	if doc.warehouse_type == "Block":
		if "Has Rows" in levels and doc.get("custom_number_of_rows"):
			created_rows = ensure_rows(doc.name, doc.custom_number_of_rows)
			if created_rows:
				frappe.msgprint(
					_("Created {0} Row(s) for {1}.").format(created_rows, doc.name),
					alert=True,
					indicator="green",
				)
		return

	if "Has Sections" in levels and doc.get("custom_sections"):
		ranges = {}
		for row in doc.custom_sections:
			section_name = ensure_section(doc.name, row)
			if row.section_doc != section_name:
				row.db_set("section_doc", section_name, update_modified=False)
			if "Has Beds" in levels and row.from_bed and row.to_bed:
				ranges[section_name] = (row.from_bed, row.to_bed)
				created_beds += ensure_beds(doc.name, row.from_bed, row.to_bed)
		reassign_bed_sections(doc.name, ranges)
	elif "Has Beds" in levels and doc.get("custom_number_of_beds"):
		created_beds += ensure_beds(doc.name, 1, doc.custom_number_of_beds)

	if created_beds:
		frappe.msgprint(
			_("Created {0} Bed(s) for {1}.").format(created_beds, doc.name),
			alert=True,
			indicator="green",
		)


def reassign_bed_sections(greenhouse, ranges):
	"""Point every bed of the greenhouse at the section whose range covers it,
	clearing beds that fall outside all ranges."""
	for bed in frappe.get_all("Bed", filters={"greenhouse": greenhouse}, fields=["name", "bed", "section"]):
		expected = next(
			(section for section, (lo, hi) in ranges.items() if lo <= bed.bed <= hi), None
		)
		if bed.section != expected:
			frappe.db.set_value("Bed", bed.name, "section", expected, update_modified=False)


def ensure_section(greenhouse, row):
	existing = frappe.db.get_value(
		"Section", {"greenhouse": greenhouse, "section": row.section}, "name"
	)
	if not existing and row.section_doc:
		# the row was renamed: rename its existing Section document instead of
		# creating a new one (which would collide on the bed range)
		if frappe.db.get_value("Section", row.section_doc, "greenhouse") == greenhouse:
			frappe.db.set_value(
				"Section", row.section_doc, "section", row.section, update_modified=False
			)
			existing = rename_doc(
				"Section",
				row.section_doc,
				f"{greenhouse} - {row.section}",
				ignore_permissions=True,
				show_alert=False,
			)
	if existing:
		# heal name drift (e.g. section label edited without renaming the doc)
		expected_name = f"{greenhouse} - {row.section}"
		if existing != expected_name:
			existing = rename_doc(
				"Section", existing, expected_name, ignore_permissions=True, show_alert=False
			)
		section = frappe.get_doc("Section", existing)
		if (section.from_bed, section.to_bed) != (row.from_bed, row.to_bed):
			section.from_bed = row.from_bed
			section.to_bed = row.to_bed
			section.save(ignore_permissions=True)
		return existing

	section = frappe.get_doc(
		{
			"doctype": "Section",
			"greenhouse": greenhouse,
			"section": row.section,
			"from_bed": row.from_bed,
			"to_bed": row.to_bed,
		}
	).insert(ignore_permissions=True)
	return section.name


def ensure_rows(block, number_of_rows):
	existing = set(
		frappe.get_all("Row", filters={"block": block}, pluck="row")
	)
	created = 0
	for n in range(1, number_of_rows + 1):
		if n in existing:
			continue
		frappe.get_doc({"doctype": "Row", "block": block, "row": n}).insert(
			ignore_permissions=True
		)
		created += 1
	return created


def ensure_beds(greenhouse, from_bed, to_bed):
	existing = set(
		frappe.get_all(
			"Bed",
			filters={"greenhouse": greenhouse, "bed": ("between", [from_bed, to_bed])},
			pluck="bed",
		)
	)
	created = 0
	for n in range(from_bed, to_bed + 1):
		if n in existing:
			continue
		frappe.get_doc({"doctype": "Bed", "greenhouse": greenhouse, "bed": n}).insert(
			ignore_permissions=True
		)
		created += 1
	return created
