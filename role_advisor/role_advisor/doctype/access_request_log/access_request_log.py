# Copyright (c) 2026, Upande and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import now_datetime


class AccessRequestLog(Document):
	def before_insert(self):
		if not self.requested_on:
			self.requested_on = now_datetime()

	def applied_suggestion(self) -> bool:
		"""True once an admin has acted on this log entry."""
		return bool(self.decided_by)

	def requirement_pairs(self) -> list[tuple[str, str]]:
		"""The (doctype, perm) pairs this request asked for, in catalogue order."""
		names = [row.transaction for row in self.requested_transactions]
		if not names:
			return []

		rows = frappe.get_all(
			"Transaction Catalog",
			filters={"name": ("in", names)},
			fields=["name", "reference_doctype", "required_perm"],
		)
		by_name = {row.name: row for row in rows}

		return [
			(by_name[name].reference_doctype, by_name[name].required_perm)
			for name in names
			if name in by_name
		]
