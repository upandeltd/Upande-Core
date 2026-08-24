# Copyright (c) 2026, ghost-mann and contributors
# For license information, please see license.txt

"""Is this Role Profile too powerful to delegate?

The denylist is *computed* from the capability index, never matched on role
names. A name list (`{"System Manager", ...}`) rots the moment someone creates
`Site Admin Copy`; a capability check catches it whatever it is called.
"""

from upande_core import capability, settings

# Rights that let the holder change permissions or records of a privileged
# doctype. `read` is excluded deliberately: `User Manager` already holds read on
# Role Profile and Module Profile in production, and treating read as privileged
# would refuse every realistic allowlist.
WRITE_EQUIVALENT = frozenset({"write", "create", "delete", "submit", "cancel"})

UNKNOWN_PROFILE = "__unknown__"


def privileged_grants(role_profile: str) -> dict[str, set[str]]:
	"""Return {privileged doctype: {right}} that `role_profile` grants.

	An empty dict means the profile is safe to delegate. A profile absent from
	the index returns a sentinel grant rather than `{}` - failing closed, since
	an unknown profile cannot be vouched for.
	"""
	index = capability.build_capability_index()
	if role_profile not in index:
		return {UNKNOWN_PROFILE: {"write"}}

	granted = index[role_profile]
	privileged = set(settings.privileged_doctypes())

	found: dict[str, set[str]] = {}
	for doctype, perms in granted.items():
		if doctype not in privileged:
			continue
		offending = perms & WRITE_EQUIVALENT
		if offending:
			found[doctype] = offending

	return found


def is_privileged(role_profile: str) -> bool:
	return bool(privileged_grants(role_profile))


def describe(grants: dict[str, set[str]]) -> str:
	"""Render grants as 'DocType: write, delete; DocType: create'."""
	return "; ".join(
		f"{doctype}: {', '.join(sorted(grants[doctype]))}" for doctype in sorted(grants)
	)
