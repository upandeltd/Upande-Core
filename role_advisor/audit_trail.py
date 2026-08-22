# Copyright (c) 2026, ghost-mann and contributors
# For license information, please see license.txt

"""The audit trail: every real access change, whoever made it.

`Access Assignment Log` records what this app did. It holds 13 rows. `Version`
holds 75,768 access-relevant rows the app cannot see, so the trail worth having
is mostly of changes made outside it - which is exactly the thing worth knowing.

Derived, never stored. Nothing here writes, so the trail can never itself be
the thing that is wrong.
"""

import collections
import json

ACCESS_DOCTYPES = ("User", "Role", "Role Profile", "Module Profile", "Property Setter")

# Scalar fields on the parent doc that mean something for access. Everything
# else on User - birth_date, gender, user_image, last_active - is churn, and
# 75,226 version rows of it would bury the changes that matter.
INTEREST_FIELDS = frozenset(
	{"role_profile_name", "module_profile", "user_type", "enabled", "api_key", "api_secret"}
)

# Child table -> the key in its row payload holding the value we care about.
# Recording only that "the roles table changed" is the specific defect that
# makes the IT dashboard's version_flat useless for access auditing.
CHILD_VALUE_KEY = {"roles": "role", "role_profiles": "role_profile", "block_modules": "module"}


def _child_multisets(blob: dict) -> tuple[dict, dict]:
	"""Added and removed child rows as multisets of their meaningful value.

	Multisets rather than sets: a save can legitimately add two rows carrying
	the same value, and collapsing them would understate the change.
	"""
	out: dict[str, dict[str, collections.Counter]] = {"added": {}, "removed": {}}

	for kind in ("added", "removed"):
		for entry in blob.get(kind) or []:
			if not isinstance(entry, list) or len(entry) < 2:
				continue
			table, payload = entry[0], entry[1]
			key = CHILD_VALUE_KEY.get(table)
			if not key or not isinstance(payload, dict):
				continue
			value = payload.get(key)
			if not value:
				continue
			out[kind].setdefault(table, collections.Counter())[value] += 1

	return out["added"], out["removed"]


def _delta(data: str, ref_doctype: str) -> dict | None:
	"""One version row's `data` JSON reduced to what actually changed.

	Returns None when nothing access-relevant survives, which is the common
	case: most User versions are ordinary profile churn.
	"""
	try:
		blob = json.loads(data or "{}")
	except (ValueError, TypeError):
		return None
	if not isinstance(blob, dict):
		return None

	fields: list[tuple] = []
	profile_before = None
	profile_after = None

	for change in blob.get("changed") or []:
		if not isinstance(change, list) or not change:
			continue
		name = change[0]
		if name not in INTEREST_FIELDS:
			continue
		old = change[1] if len(change) > 1 else None
		new = change[2] if len(change) > 2 else None
		if name == "role_profile_name":
			# v15 kept the profile in a scalar field. Canonicalised here so a
			# v15 change and a v16 child-table change read identically.
			profile_before, profile_after = old, new
		else:
			fields.append((name, old, new))

	for entry in blob.get("row_changed") or []:
		if not isinstance(entry, list) or len(entry) < 4:
			continue
		table = entry[0]
		if table not in CHILD_VALUE_KEY:
			continue
		for change in entry[3] or []:
			if isinstance(change, list) and change:
				old = change[1] if len(change) > 1 else None
				new = change[2] if len(change) > 2 else None
				fields.append((f"{table}.{change[0]}", old, new))

	added, removed = _child_multisets(blob)

	def net(table: str) -> tuple[list, list]:
		gained = added.get(table, collections.Counter())
		lost = removed.get(table, collections.Counter())
		return sorted((gained - lost).elements()), sorted((lost - gained).elements())

	roles_gained, roles_lost = net("roles")
	modules_blocked, modules_unblocked = net("block_modules")
	profiles_gained, profiles_lost = net("role_profiles")

	# v16 keeps profiles in a child table. Fold it onto the same two fields the
	# v15 scalar produces, so the 439 old rows and the 52 new ones render alike.
	if profiles_lost:
		profile_before = ", ".join(profiles_lost)
	if profiles_gained:
		profile_after = ", ".join(profiles_gained)

	if not (
		fields
		or roles_gained
		or roles_lost
		or modules_blocked
		or modules_unblocked
		or profile_before
		or profile_after
	):
		return None

	return {
		"doctype": ref_doctype,
		"roles_gained": roles_gained,
		"roles_lost": roles_lost,
		"modules_blocked": modules_blocked,
		"modules_unblocked": modules_unblocked,
		"profile_before": profile_before,
		"profile_after": profile_after,
		"fields": fields,
		"updater_reference": blob.get("updater_reference"),
	}
