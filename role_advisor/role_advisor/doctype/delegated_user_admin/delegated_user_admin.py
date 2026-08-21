# Copyright (c) 2026, ghost-mann and contributors
# For license information, please see license.txt

"""Per-admin delegation record: scope plus grantable allowlist.

The allowlist is deliberately not "the profiles this admin holds". A Farm
Manager must be able to grant `Guard` without holding `Guard`, so that
administering access does not inflate the administrator's own access.
"""

import frappe
from frappe import _
from frappe.model.document import Document

from role_advisor import privilege


class DelegatedUserAdmin(Document):
	def before_insert(self):
		self.default_companies_from_user_permissions()

	def validate(self):
		self.validate_scope_present()
		self.validate_no_privileged_profiles()

	def default_companies_from_user_permissions(self):
		"""Seed scope from the admin's existing Company User Permissions.

		244 users already carry Company permissions; re-entering them by hand
		invites transcription errors. The value is copied, not referenced, so a
		later edit to those permissions cannot widen this record's scope.
		"""
		if self.companies:
			return

		for company in frappe.get_all(
			"User Permission",
			filters={"user": self.user, "allow": "Company"},
			pluck="for_value",
		):
			self.append("companies", {"company": company})

	def validate_scope_present(self):
		if not self.companies:
			frappe.throw(
				_("Set at least one Company. An admin with no scope could reach every user."),
				title=_("Scope Required"),
			)

	def validate_no_privileged_profiles(self):
		"""Refuse an allowlist entry that could be used to escalate.

		The first of two checks. `assign_access` repeats it at write time,
		because a profile's contents can change after it was allowlisted.
		"""
		for row in self.allowed_role_profiles or []:
			grants = privilege.privileged_grants(row.role_profile)
			if grants:
				frappe.throw(
					_("{0} cannot be delegated: it grants {1}.").format(
						frappe.bold(row.role_profile), privilege.describe(grants)
					),
					title=_("Privileged Profile"),
				)
