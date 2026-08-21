# Copyright (c) 2026, ghost-mann and contributors
# For license information, please see license.txt

"""Resolve a designation to a map row, and break ties between candidates."""

import frappe

from role_advisor import capability, settings


def employee_scope(user: str) -> dict:
	"""Return the scope dimensions for `user`, read from their Employee record.

	Users with no active Employee record return all-None. They are consequently
	unreachable by any scoped delegate - which is the intended outcome for the
	109 unlinked users on Kaitet, not an oversight.
	"""
	row = frappe.db.get_value(
		"Employee",
		{"user_id": user, "status": "Active"},
		["company", "branch", "department", "grade"],
		as_dict=True,
	)

	return {
		dimension: (row.get(dimension) if row else None) or None
		for dimension in settings.SCOPE_DIMENSIONS
	}


def candidate_scopes(scope: dict) -> list[dict]:
	"""Scope filters to try, most specific first.

	Specificity is dropped from the narrow end: (company, branch) then
	(company,) then (). `settings.SCOPE_DIMENSIONS` is ordered most-general
	first precisely so this walk is a suffix truncation.
	"""
	dimensions = settings.scope_dimensions()

	candidates = []
	for depth in range(len(dimensions), -1, -1):
		candidates.append(
			{
				dimension: (scope.get(dimension) if index < depth else None)
				for index, dimension in enumerate(dimensions)
			}
		)

	return candidates


def resolve(designation: str, scope: dict, active_only: bool = True) -> str | None:
	"""Return the name of the most specific matching map row, or None.

	`active_only=False` is for the dry-run and reports, which must show what
	*would* be applied once a human activates the row it depends on.
	"""
	if not designation:
		return None

	for candidate in candidate_scopes(scope):
		filters = {"designation": designation}
		if active_only:
			filters["is_active"] = 1

		# An unset dimension must match only rows that are also unset, so the
		# filter has to distinguish NULL from "any". `("is", "not set")` does
		# that; passing None would be read as "no filter".
		for dimension, value in candidate.items():
			filters[settings.map_fieldname(dimension)] = value or ("is", "not set")

		rows = frappe.get_all(
			"Designation Access Map", filters=filters, pluck="name", limit=1
		)
		if rows:
			return rows[0]

	return None


def tie_break(candidates: list[str]) -> str | None:
	"""Choose between role profiles that all satisfy the same requirement.

	Default rule is tightest-by-permission-count. Where several profiles cover
	the same need they differ only in what *else* they hand over, so the
	smallest total grant wins: least authority beyond the ask, smallest blast
	radius. Ties break on name so a rerun gives the same answer.
	"""
	if not candidates:
		return None

	unique = sorted(set(candidates))
	if len(unique) == 1:
		return unique[0]

	rule = settings.tie_break_rule()
	if rule == "Always flag":
		return None

	if rule == "Majority peer vote":
		# The caller supplies candidates in peer-frequency order for this rule,
		# so the first entry is already the majority pick.
		return candidates[0]

	index = capability.build_capability_index()

	return min(
		unique,
		key=lambda profile: (
			capability.total_perm_count(index.get(profile, {})),
			len(index.get(profile, {})),
			profile,
		),
	)
