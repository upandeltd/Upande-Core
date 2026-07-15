// Copyright (c) 2026, Upande and contributors
// For license information, please see license.txt
//
// Renders the farm-structure fields on Warehouse according to the selected
// farm's levels (Farm Type multiselect) and the Warehouse Type
// (Greenhouse/Block). Shipped via doctype_js — no site Client Scripts.

frappe.ui.form.on("Warehouse", {
	refresh(frm) {
		render_farm_structure(frm);
	},
	custom_farm(frm) {
		render_farm_structure(frm);
	},
	warehouse_type(frm) {
		render_farm_structure(frm);
	},
});

async function render_farm_structure(frm) {
	let levels = [];
	if (frm.doc.custom_farm) {
		const r = await frappe.call({
			method: "upande_core.api.get_farm_levels",
			args: { farm: frm.doc.custom_farm },
		});
		levels = r.message || [];
	}

	// the warehouse type controls what renders; the farm's levels only refine
	// the greenhouse layout (sections table vs plain bed count, bed columns)
	const is_greenhouse = frm.doc.warehouse_type === "Greenhouse";
	const is_block = frm.doc.warehouse_type === "Block";
	const levels_known = levels.length > 0;
	const has_sections = is_greenhouse && (!levels_known || levels.includes("Has Sections"));
	const has_beds = !levels_known || levels.includes("Has Beds");

	frm.toggle_display("custom_sections", has_sections);
	frm.toggle_display(
		"custom_number_of_beds",
		is_greenhouse && !has_sections && has_beds
	);
	frm.toggle_display("custom_number_of_rows", is_block);

	if (has_sections && frm.fields_dict.custom_sections) {
		const grid = frm.fields_dict.custom_sections.grid;
		grid.update_docfield_property("from_bed", "hidden", has_beds ? 0 : 1);
		grid.update_docfield_property("to_bed", "hidden", has_beds ? 0 : 1);
	}
}
