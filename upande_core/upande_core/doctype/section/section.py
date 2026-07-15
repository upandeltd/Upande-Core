# Copyright (c) 2026, Upande and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document

from upande_core.utils import validate_structure_level


class Section(Document):
	def validate(self):
		validate_structure_level(self.greenhouse, "Has Sections", "Greenhouse")
		if self.to_bed < self.from_bed:
			frappe.throw(_("To Bed must be greater than or equal to From Bed."))
		self.validate_no_overlap()

	def validate_no_overlap(self):
		overlapping = frappe.db.get_value(
			"Section",
			{
				"greenhouse": self.greenhouse,
				"name": ("!=", self.name),
				"from_bed": ("<=", self.to_bed),
				"to_bed": (">=", self.from_bed),
			},
			"name",
		)
		if overlapping:
			frappe.throw(
				_("Bed range {0}-{1} overlaps with Section {2}.").format(
					self.from_bed, self.to_bed, overlapping
				)
			)
