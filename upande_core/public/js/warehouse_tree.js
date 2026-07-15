// Copyright (c) 2026, Upande and contributors
// For license information, please see license.txt
//
// Extends ERPNext's Warehouse tree "New" dialog (which has its own hardcoded
// field list and ignores quick-entry settings) with Farm and Warehouse Type.

if (
	frappe.treeview_settings["Warehouse"] &&
	!frappe.treeview_settings["Warehouse"].__upande_core_extended
) {
	frappe.treeview_settings["Warehouse"].__upande_core_extended = true;
	frappe.treeview_settings["Warehouse"].fields.push(
		{
			fieldtype: "Link",
			fieldname: "custom_farm",
			label: __("Farm"),
			options: "Farm",
			reqd: 1,
		},
		{
			fieldtype: "Link",
			fieldname: "warehouse_type",
			label: __("Warehouse Type"),
			options: "Warehouse Type",
			description: __("Greenhouse or Block enables the farm structure"),
		}
	);
}
