# Copyright (c) 2026, Upande and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class Farm(Document):
	def validate(self):
		self.ensure_single_default()

	def ensure_single_default(self):
		if self.is_default:
			frappe.db.set_value(
				"Farm",
				{"company": self.company, "is_default": 1, "name": ("!=", self.name)},
				"is_default",
				0,
			)
		elif not frappe.db.exists(
			"Farm", {"company": self.company, "is_default": 1, "name": ("!=", self.name)}
		):
			# first / only farm of the company becomes the default
			self.is_default = 1
