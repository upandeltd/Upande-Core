# Copyright (c) 2026, Upande and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document

from upande_core.utils import validate_structure_level


class OrchardTree(Document):
	def validate(self):
		row_unit_type, block = frappe.db.get_value(
			"Bed", self.row, ["unit_type", "greenhouse"]
		)
		if row_unit_type != "Row":
			frappe.throw(_("{0} is a bed, not a row. Trees can only be placed on rows.").format(self.row))
		self.block = block
		validate_structure_level(block, "Has Orchard Trees", "Block")
		self.validate_triad_block(block)

	def validate_triad_block(self, block):
		if self.triad:
			triad_block = frappe.db.get_value("Triad", self.triad, "block")
			if triad_block != block:
				frappe.throw(
					_("Triad {0} belongs to block {1}, but this tree is in block {2}.").format(
						self.triad, triad_block, block
					)
				)
