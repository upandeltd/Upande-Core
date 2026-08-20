# Copyright (c) 2026, Upande and contributors
# For license information, please see license.txt

"""Immutable record of one access assignment.

Written only by `role_advisor.audit.log_assignment`. No role holds write or
delete on this doctype - an editable audit log is not an audit log.
"""

import frappe
from frappe import _
from frappe.model.document import Document


class AccessAssignmentLog(Document):
	def validate(self):
		if not self.is_new():
			frappe.throw(
				_("Access Assignment Log rows cannot be modified after creation."),
				title=_("Immutable Record"),
			)
