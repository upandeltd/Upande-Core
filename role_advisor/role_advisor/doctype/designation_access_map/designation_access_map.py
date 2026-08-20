# Copyright (c) 2026, Upande and contributors
# For license information, please see license.txt

"""The designation -> role profile mapping.

Rows are resolved most-specific-wins (see `role_advisor.mapping`), so the scope
fields are a key, not a filter. Uniqueness is enforced here rather than by a DB
unique index: `company` and `branch` are nullable, and MariaDB treats every NULL
as distinct, so an index would happily accept two identical "applies to all
companies" rows.
"""

import frappe
from frappe import _
from frappe.model.document import Document

CONFIDENCE_HIGH = "High"
CONFIDENCE_MEDIUM = "Medium"
CONFIDENCE_LOW = "Low"
CONFIDENCE_NONE = "None"

SCOPE_FIELDS = ("for_company", "for_branch", "for_department", "for_grade")


class DesignationAccessMap(Document):
	def validate(self):
		self.normalise_scope()
		self.validate_scope_hierarchy()
		self.validate_unique_scope()

	def normalise_scope(self):
		"""Collapse "" to None so blank and unset compare equal."""
		for field in SCOPE_FIELDS:
			if not self.get(field):
				self.set(field, None)

	def validate_scope_hierarchy(self):
		"""A narrower dimension cannot be set without its parent.

		A branch-scoped row with no company cannot be resolved unambiguously:
		branch names are not globally unique across companies, so the resolver
		would have no way to tell which company's branch was meant.
		"""
		if self.for_branch and not self.for_company:
			frappe.throw(
				_("Set a Company before setting a Branch."),
				title=_("Incomplete Scope"),
			)

	def validate_unique_scope(self):
		filters = {
			"designation": self.designation,
			"name": ("!=", self.name or ""),
		}
		for field in SCOPE_FIELDS:
			filters[field] = self.get(field) or ("is", "not set")

		existing = frappe.get_all(
			"Designation Access Map", filters=filters, pluck="name", limit=1
		)
		if existing:
			frappe.throw(
				_("A map row already exists for this designation and scope: {0}").format(
					frappe.utils.get_link_to_form("Designation Access Map", existing[0])
				),
				title=_("Duplicate Map Row"),
			)

	def scope_key(self) -> tuple:
		"""The row's scope as a comparable tuple, blanks normalised to None."""
		return tuple(self.get(field) or None for field in SCOPE_FIELDS)
