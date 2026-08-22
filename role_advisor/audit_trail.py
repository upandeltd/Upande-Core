# Copyright (c) 2026, ghost-mann and contributors
# For license information, please see license.txt

"""The audit trail: every real access change, whoever made it.

`Access Assignment Log` records what this app did. It holds 13 rows. `Version`
holds 75,768 access-relevant rows the app cannot see, so the trail worth having
is mostly of changes made outside it - which is exactly the thing worth knowing.

Derived, never stored. Nothing here writes, so the trail can never itself be
the thing that is wrong.
"""

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

	if not (fields or profile_before or profile_after):
		return None

	return {
		"doctype": ref_doctype,
		"roles_gained": [],
		"roles_lost": [],
		"modules_blocked": [],
		"modules_unblocked": [],
		"profile_before": profile_before,
		"profile_after": profile_after,
		"fields": fields,
	}
