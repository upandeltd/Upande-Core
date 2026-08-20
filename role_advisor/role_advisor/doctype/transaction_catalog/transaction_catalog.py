# Copyright (c) 2026, Upande and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document

# The permissions a Transaction Catalog row is allowed to require. Kept in sync
# with the `required_perm` Select options and with api.TRACKED_PERMS.
ALLOWED_PERMS = ("read", "write", "create", "submit", "cancel", "delete", "report", "export")


class TransactionCatalog(Document):
	def validate(self):
		self.validate_perm_applies_to_doctype()
		self.normalise_keywords()

	def validate_perm_applies_to_doctype(self):
		"""Reject combinations the target doctype can never grant.

		`submit`/`cancel` only exist on submittable doctypes, so cataloguing them
		against a non-submittable doctype would create a requirement that no role
		profile can ever satisfy - a permanent phantom gap.
		"""
		if self.required_perm not in ("submit", "cancel"):
			return

		if not frappe.get_meta(self.reference_doctype).is_submittable:
			frappe.throw(
				_("{0} is not submittable, so it can never grant the {1} permission.").format(
					frappe.bold(self.reference_doctype), frappe.bold(self.required_perm)
				),
				title=_("Unsatisfiable Requirement"),
			)

	def normalise_keywords(self):
		if not self.keywords:
			return

		seen = []
		for keyword in self.keywords.split(","):
			keyword = keyword.strip().lower()
			if keyword and keyword not in seen:
				seen.append(keyword)

		self.keywords = ", ".join(seen)

	def on_update(self):
		self.clear_advisor_cache()

	def on_trash(self):
		self.clear_advisor_cache()

	def clear_advisor_cache(self):
		from role_advisor.api import clear_capability_index

		# The catalogue does not feed the capability index, but the console's
		# picker payload is cached alongside it.
		clear_capability_index()

	def requirement(self) -> tuple[str, str]:
		"""Return this transaction as a single (doctype, perm) requirement pair."""
		return (self.reference_doctype, self.required_perm)
