# Copyright (c) 2026, Upande and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document

from upande_core.utils import validate_structure_level


class Bed(Document):
	def validate(self):
		if self.unit_type == "Row":
			validate_structure_level(self.greenhouse, "Has Rows", "Block")
		else:
			validate_structure_level(self.greenhouse, "Has Beds", "Greenhouse")
		self.bed_area = (self.bed_length or 0) * (self.bed_width or 0)
		self.assign_section()

	def assign_section(self):
		if self.unit_type == "Row":
			self.section = None
			return
		self.section = frappe.db.get_value(
			"Section",
			{
				"greenhouse": self.greenhouse,
				"from_bed": ("<=", self.bed),
				"to_bed": (">=", self.bed),
			},
			"name",
		)
