# Copyright (c) 2026, Upande and contributors
# For license information, please see license.txt

import frappe
from frappe import _


def get_warehouse_farm(warehouse):
	"""Return (farm, warehouse_type) for a structure warehouse.

	Throws if the warehouse is not assigned to a farm.
	"""
	values = frappe.db.get_value(
		"Warehouse", warehouse, ["custom_farm", "warehouse_type"]
	)
	farm, role = values if values else (None, None)
	if not farm:
		frappe.throw(
			_("Warehouse {0} is not assigned to a Farm. Set the Farm field on the warehouse first.").format(
				warehouse
			)
		)
	return farm, role


def validate_structure_level(warehouse, level, expected_role=None):
	"""Validate that the farm of this warehouse includes the given structure
	level (a Farm Type record, e.g. "Has Beds") in its farm type multiselect."""
	farm, role = get_warehouse_farm(warehouse)
	if not frappe.db.exists(
		"Farm Type Item", {"parenttype": "Farm", "parent": farm, "farm_type": level}
	):
		frappe.throw(
			_("Farm {0} does not include {1} in its Farm Type.").format(farm, level)
		)
	if expected_role and role and role != expected_role:
		frappe.throw(
			_("Warehouse {0} has type {1}, expected {2}.").format(warehouse, role, expected_role)
		)
	return farm
