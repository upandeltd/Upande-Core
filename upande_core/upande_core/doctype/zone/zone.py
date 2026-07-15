# Copyright (c) 2026, Upande and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document

from upande_core.utils import validate_structure_level


class Zone(Document):
	def validate(self):
		greenhouse = frappe.db.get_value("Bed", self.bed, "greenhouse")
		validate_structure_level(greenhouse, "Has Zones", "Greenhouse")
