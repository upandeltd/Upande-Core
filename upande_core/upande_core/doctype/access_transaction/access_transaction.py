# Copyright (c) 2026, ghost-mann and contributors
# For license information, please see license.txt

"""An optional named bundle of requirements.

Deliberately *not* the primary unit. A doctype plus a right already says what
someone needs, in vocabulary users see on every form, and it needs no authoring
and never goes stale when an app adds doctypes.

A bundle earns its place only where one ask genuinely spans several documents -
"Run payroll" needs Salary Slip, Payroll Entry and Journal Entry - or where a
local word differs from the doctype name. A bundle that restates a single
doctype and right is pure indirection and is refused.
"""

import frappe
from frappe import _
from frappe.model.document import Document


class AccessTransaction(Document):
	def validate(self):
		if not self.requirements:
			frappe.throw(_("A bundle needs at least one requirement."))

		seen = set()
		for row in self.requirements:
			if frappe.db.get_value("DocType", row.document_type, "istable"):
				frappe.throw(
					_("{0} is a child table and cannot be granted on its own.").format(
						row.document_type
					)
				)
			key = (row.document_type, row.right)
			if key in seen:
				frappe.throw(
					_("{0} · {1} is listed twice.").format(row.document_type, row.right)
				)
			seen.add(key)

		# One requirement is a doctype search, not a bundle.
		if len(self.requirements) == 1:
			frappe.throw(
				_(
					"A bundle of one is just a document search. Add the other documents this ask needs, or delete the bundle."
				)
			)
