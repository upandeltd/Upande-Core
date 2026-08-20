# Copyright (c) 2026, Upande and contributors
# For license information, please see license.txt

"""Typed accessors for `User Access Settings`.

Every accessor falls back to a spec default, so no caller needs to handle an
unsaved Single or a field left blank.
"""

import frappe
from frappe.utils import cint, cstr

# Anything that can rewrite permissions. A profile granting write on any of
# these is refused to delegates even when allowlisted (see delegation.py).
PRIVILEGED_DOCTYPE_DEFAULTS = (
	"User",
	"Role",
	"Role Profile",
	"Module Profile",
	"Custom DocPerm",
	"DocPerm",
	"Property Setter",
)

# Fixed most-general to most-specific. Map resolution truncates this from the
# narrow end to implement most-specific-wins, so the order is load-bearing.
SCOPE_DIMENSIONS = ("company", "branch", "department", "grade")

# `Designation Access Map` prefixes its scope fields. Frappe stamps
# `frappe.defaults` onto any Link field named exactly `company`
# (frappe/model/create_new.py:87), before `validate` runs - which would make an
# "applies to every company" row impossible to create. The dimension names below
# still match `Employee`'s real fieldnames; only the map's own fields are
# prefixed.
MAP_FIELD_PREFIX = "for_"


def map_fieldname(dimension: str) -> str:
	"""The Designation Access Map field holding this scope dimension."""
	return f"{MAP_FIELD_PREFIX}{dimension}"


DEFAULTS = {
	"seed_mode": "Seed from existing users",
	"tie_break_rule": "Tightest by permission count",
	"min_peers_high_confidence": 5,
	"module_profile_strategy": "Derive from Role Profile",
	"naming_pattern": "{role_profile}",
	"delegate_role": "User Manager",
	"allow_multiple_profiles": 0,
	"require_employee_link": 1,
	"use_company": 1,
	"use_branch": 1,
	"use_department": 0,
	"use_grade": 0,
}


def _settings():
	return frappe.get_cached_doc("User Access Settings")


def _value(fieldname):
	value = _settings().get(fieldname)
	if value in (None, ""):
		return DEFAULTS.get(fieldname)
	return value


def scope_dimensions() -> list[str]:
	"""Dimensions forming the map key, most-general first."""
	enabled = [d for d in SCOPE_DIMENSIONS if cint(_value(f"use_{d}"))]

	# A map with no dimensions would collapse every designation to one global
	# row, silently discarding the farm splits.
	return enabled or ["company"]


def tie_break_rule() -> str:
	return cstr(_value("tie_break_rule"))


def min_peers_high_confidence() -> int:
	# A zero threshold would mark every unprecedented row High.
	return cint(_value("min_peers_high_confidence")) or DEFAULTS["min_peers_high_confidence"]


def seed_mode() -> str:
	return cstr(_value("seed_mode"))


def module_profile_strategy() -> str:
	return cstr(_value("module_profile_strategy"))


def naming_pattern() -> str:
	return cstr(_value("naming_pattern"))


def never_block_modules() -> list[str]:
	return [row.module for row in _settings().get("never_block_modules") or []]


def delegate_role() -> str:
	return cstr(_value("delegate_role"))


def allow_multiple_profiles() -> bool:
	return bool(cint(_value("allow_multiple_profiles")))


def require_employee_link() -> bool:
	return bool(cint(_value("require_employee_link")))


def privileged_doctypes() -> list[str]:
	configured = [row.document_type for row in _settings().get("privileged_doctypes") or []]

	return configured or list(PRIVILEGED_DOCTYPE_DEFAULTS)
