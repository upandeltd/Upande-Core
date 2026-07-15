# Copyright (c) 2026, Upande and contributors
# For license information, please see license.txt

from frappe.model.document import Document

from upande_core.utils import validate_structure_level


class Triad(Document):
	def validate(self):
		validate_structure_level(self.block, "Has Triads", "Block")
