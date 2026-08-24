# Copyright (c) 2026, ghost-mann and contributors
# For license information, please see license.txt

"""Someone asking to be able to do something.

The request names *transactions*, not a profile. Which profile satisfies them is
computed, explained, and only then assigned - so the person asking never has to
know the permission model, and the person granting sees the consequence before
they act.
"""

import frappe
from frappe import _
from frappe.model.document import Document


class AccessRequest(Document):
	def before_insert(self):
		self.raised_by = frappe.session.user

		# Anyone may ask for themselves. Asking on someone else's behalf is a
		# delegate action, checked here rather than trusted from the client.
		#
		# System Manager is tested first, deliberately: a System Manager who also
		# holds a delegate record must not be narrowed by it. The record bounds
		# what a delegate may do, it does not shrink an administrator.
		if self.for_user == frappe.session.user:
			return
		if "System Manager" in frappe.get_roles():
			return

		from upande_core import delegation

		admin = delegation.current_admin()
		if not admin:
			frappe.throw(
				_("You may only raise a request for yourself."),
				frappe.PermissionError,
			)
		delegation.assert_can_manage(admin, self.for_user)

	def validate(self):
		if not self.transactions:
			frappe.throw(_("Name at least one thing they need to do."))

		self.company = frappe.db.get_value(
			"Employee", {"user_id": self.for_user, "status": "Active"}, "company"
		)

		# The line already carries the requirement. A bundle, where one was
		# used, is recorded as provenance only - so rewording or deleting a
		# bundle later cannot change what was actually asked for.
		for line in self.transactions:
			if not line.document_type or not line.right:
				frappe.throw(_("Each line needs a document and a right."))
