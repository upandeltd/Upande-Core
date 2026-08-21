# Copyright (c) 2026, ghost-mann and contributors
# For license information, please see license.txt

"""Effective-permission index for Role Profiles.

`build_capability_index()` answers "what does this Role Profile actually grant,
per doctype?" - the question behind every report and every gate in this app.
"""

import frappe
from frappe.model.document import Document
from frappe.permissions import get_doctypes_with_custom_docperms
from frappe.utils import cint

# The rights a grant may carry. Deliberately excludes
# `email`, `print` and `share`: they are not transactions anyone requests here,
# and counting them would inflate every profile's tightness score equally
# without changing the ranking - only the noise in the over-grant diff.
TRACKED_PERMS = ("read", "write", "create", "submit", "cancel", "delete", "report", "export")

CAPABILITY_CACHE_KEY = "role_advisor:capability_index"
CACHE_TTL_SECONDS = 10 * 60



def _perm_rows_for_roles(roles: list[str]) -> list[dict]:
	"""Return effective permission rows for `roles`, honouring Custom DocPerm.

	This is a batched form of `frappe.permissions.get_all_perms`, which does the
	same three queries but for a single role at a time. On a site with a few
	hundred roles the per-role version costs hundreds of round trips every time
	the index is rebuilt, which is exactly the scan we are trying to keep cheap.

	The override rule is taken verbatim from core (see `get_all_perms` in
	frappe/permissions.py): Custom DocPerm overrides are applied **per doctype,
	not per role**. If any Custom DocPerm row exists for a doctype, the standard
	DocPerm rows for that doctype are discarded for every role. The parity of
	this function with core is asserted by a test, so a change in core surfaces
	as a test failure rather than as silently wrong advice.
	"""
	if not roles:
		return []

	standard = frappe.get_all("DocPerm", fields="*", filters={"role": ("in", roles)})
	custom = frappe.get_all("Custom DocPerm", fields="*", filters={"role": ("in", roles)})

	overridden = set(get_doctypes_with_custom_docperms())
	effective = list(custom)
	effective.extend(row for row in standard if row.parent not in overridden)

	return effective


def _capabilities_from_rows(rows: list[dict]) -> dict[str, dict[str, set[str]]]:
	"""Fold permission rows into {role: {doctype: {perm, ...}}}."""
	capabilities: dict[str, dict[str, set[str]]] = {}

	for row in rows:
		# Only permlevel 0 grants act on the document itself. A permlevel 1
		# `write` row grants access to a field group, not the ability to write
		# the document, so treating it as a grant would report false coverage.
		if cint(row.get("permlevel")):
			continue

		# `if_owner` restricts the grant to documents the user created. It cannot
		# be relied on to authorise a transaction against an arbitrary record, so
		# it is not counted. Erring this way suggests a profile the user may not
		# strictly need, rather than wrongly reporting them as already covered.
		if cint(row.get("if_owner")):
			continue

		granted = {perm for perm in TRACKED_PERMS if cint(row.get(perm))}
		if not granted:
			continue

		by_doctype = capabilities.setdefault(row.get("role"), {})
		by_doctype.setdefault(row.get("parent"), set()).update(granted)

	return capabilities


def _roles_by_role_profile() -> dict[str, list[str]]:
	"""Return {role_profile: [role, ...]} in one query."""
	rows = frappe.get_all(
		"Has Role",
		filters={"parenttype": "Role Profile"},
		fields=["parent", "role"],
	)

	profiles: dict[str, list[str]] = {
		name: [] for name in frappe.get_all("Role Profile", pluck="name")
	}
	for row in rows:
		# A profile row can outlive its profile in edge cases; ignore orphans.
		if row.parent in profiles:
			profiles[row.parent].append(row.role)

	return profiles


def _compute_capability_index() -> dict[str, dict[str, set[str]]]:
	profile_roles = _roles_by_role_profile()

	all_roles = sorted({role for roles in profile_roles.values() for role in roles})
	role_capabilities = _capabilities_from_rows(_perm_rows_for_roles(all_roles))

	index: dict[str, dict[str, set[str]]] = {}
	for profile, roles in profile_roles.items():
		merged: dict[str, set[str]] = {}
		for role in roles:
			for doctype, perms in role_capabilities.get(role, {}).items():
				merged.setdefault(doctype, set()).update(perms)
		index[profile] = merged

	return index


def build_capability_index(force: bool = False) -> dict[str, dict[str, set[str]]]:
	"""Return {role_profile: {doctype: {perm, ...}}} for every Role Profile.

	Cached for ten minutes. The index is derived state, never stored as a
	doctype, so a stale entry costs at most one over-broad suggestion that the
	admin still has to approve by hand.
	"""
	if not force:
		# `expires=True` is required for any key written with `expires_in_sec`:
		# without it the value is also copied into frappe.local.cache, which has
		# no TTL and would serve a stale index for the rest of the request.
		cached = frappe.cache().get_value(CAPABILITY_CACHE_KEY, expires=True)
		if cached is not None:
			# Sets survive the cache round trip via pickle, but rebuild them
			# defensively so a cache written by an older version cannot leak
			# lists into set arithmetic below.
			return {
				profile: {doctype: set(perms) for doctype, perms in caps.items()}
				for profile, caps in cached.items()
			}

	index = _compute_capability_index()
	frappe.cache().set_value(CAPABILITY_CACHE_KEY, index, expires_in_sec=CACHE_TTL_SECONDS)

	return index


def clear_capability_index() -> None:
	"""Drop the cached index."""
	frappe.cache().delete_value(CAPABILITY_CACHE_KEY)


def on_permission_source_change(doc=None, method=None) -> None:
	"""doc_events hook: invalidate the index when its inputs change.

	Wired in hooks.py for Role Profile, Custom DocPerm and DocPerm. Without this
	the index would serve up to ten minutes of stale advice after an admin edits
	a profile - long enough to suggest a profile that no longer fits.
	"""
	clear_capability_index()


def capabilities_of_roles(roles) -> dict[str, set[str]]:
	"""What holding all of `roles` at once permits: {doctype: {right}}.

	`_capabilities_from_rows` is keyed by *role*; this flattens that into the
	one shape the rest of the app reasons in. It exists because reading the
	nested form as though it were the flat one is a silent bug rather than a
	loud one - the keys become role names, every doctype comparison misses, and
	the caller concludes the roles grant nothing dangerous.
	"""
	by_role = _capabilities_from_rows(_perm_rows_for_roles(sorted(roles)))

	union: dict[str, set[str]] = {}
	for caps in by_role.values():
		for doctype, perms in caps.items():
			union.setdefault(doctype, set()).update(perms)

	return union


def site_wide_role_capabilities() -> dict[str, set[str]]:
	"""Union of what *every* role on the site can do, profile-bundled or not.

	Used only to tell the two Gap kinds apart, so it is computed on demand
	rather than cached with the index.
	"""
	return capabilities_of_roles(frappe.get_all("Role", pluck="name"))


def total_perm_count(capabilities: dict[str, set[str]]) -> int:
	return sum(len(perms) for perms in capabilities.values())


def get_user_role_profiles(user: str) -> list[str]:
	"""Return every Role Profile assigned to `user`, in child-table order.

	`User.role_profile_name` is deprecated in v16 - `User.populate_role_profile_roles`
	moves it into the `role_profiles` child table and nulls it, keeping it only as
	a mirror of `role_profiles[0]` for list-view display. A v16 user can hold
	several profiles, and their effective access is the union of all of them, so
	coverage has to be judged against the whole set.
	"""
	profiles = frappe.get_all(
		"User Role Profile",
		filters={"parent": user, "parenttype": "User"},
		fields=["role_profile"],
		order_by="idx asc",
		pluck="role_profile",
	)
	if profiles:
		return profiles

	# Fall back to the deprecated field for rows written before the migration.
	legacy = frappe.db.get_value("User", user, "role_profile_name")

	return [legacy] if legacy else []


def set_user_role_profiles(user: Document, profiles: list[str]) -> None:
	"""Replace a user's role profiles, defusing the deprecated mirror field.

	`User.sync_role_profile_name` persists `role_profile_name` as a mirror of
	`role_profiles[0]` on every save. On the *next* save, if that stale value is
	no longer among the new profiles, `User.move_role_profile_name_to_role_profiles`
	appends it back as an extra profile - silently turning a replace into an
	append, and emitting a deprecation warning as it does so.

	Clearing the mirror first is what makes a replacement actually replace. Any
	code writing `role_profiles` on an already-saved User needs this.
	"""
	user.set("role_profiles", [{"role_profile": profile} for profile in profiles])
	user.role_profile_name = None
