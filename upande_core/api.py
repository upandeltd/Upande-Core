# Copyright (c) 2026, Upande and contributors
# For license information, please see license.txt

import frappe


@frappe.whitelist()
def get_farm_levels(farm):
	"""Return the structure levels (Farm Type names) selected on a Farm."""
	if not farm or not frappe.has_permission("Farm", doc=farm):
		return []
	return frappe.get_all(
		"Farm Type Item",
		filters={"parenttype": "Farm", "parent": farm},
		pluck="farm_type",
	)
