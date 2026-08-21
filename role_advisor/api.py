# Copyright (c) 2026, ghost-mann and contributors
# For license information, please see license.txt

"""Whitelisted API for delegated user administration.

Every field that matters on `User` - roles, role_profiles, block_modules,
user_type, api_key, api_secret - sits at permlevel 1, and permlevel is
all-or-nothing. There is no way to grant `role_profiles` while withholding
`api_secret` through permissions, so delegates get no permlevel-1 write at all
and come through here instead. `assign_access` accepts three arguments and can
therefore change exactly three things.
"""

import frappe
from frappe.utils import cint

from role_advisor import audit, capability, delegation, settings


def _profile_roles(profiles: list[str]) -> set[str]:
	if not profiles:
		return set()

	return set(
		frappe.get_all(
			"Has Role",
			filters={"parent": ("in", profiles), "parenttype": "Role Profile"},
			pluck="role",
		)
	)


def _target_profiles(before_profiles: list[str], role_profile: str) -> list[str]:
	if settings.allow_multiple_profiles():
		return sorted({*before_profiles, role_profile})

	# Replace, never append: appending would leave the broader profile in place,
	# keeping every grant the tighter one was chosen to avoid.
	return [role_profile]


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def manageable_user_query(
	doctype=None, txt="", searchfield=None, start=0, page_len=20, filters=None, **kwargs
):
	"""Link-field search restricted to the users the caller administers.

	A plain `User` link would offer every name on the site and then fail at
	`assign_access`, which reads as the field being broken. Scoping the search
	itself means the picker can only ever suggest a legitimate target.

	Signature follows `frappe.desk.search.search_link`, which calls this with
	positional (doctype, txt, searchfield, start, page_len, filters) plus keyword
	arguments this function has no use for.
	"""
	admin = delegation.assert_delegate()

	companies = delegation.scope_companies(admin)
	if not companies:
		return []

	like = f"%{txt or ''}%"
	rows = frappe.db.sql(
		"""
		select u.name, u.full_name
		from `tabUser` u
		join `tabEmployee` e
		     on e.user_id = u.name and e.status = 'Active'
		where u.enabled = 1
		  and e.company in %(companies)s
		  and (u.name like %(like)s or u.full_name like %(like)s)
		order by u.full_name
		limit %(page_len)s offset %(start)s
		""",
		{
			"companies": tuple(companies),
			"like": like,
			"page_len": cint(page_len) or 20,
			"start": cint(start) or 0,
		},
	)

	# Branch scope and the reserved-user rules live in `can_manage`; re-check so
	# the picker and the write gate can never disagree.
	return [row for row in rows if delegation.can_manage(admin, row[0])]


@frappe.whitelist()
def get_manageable_users(search: str | None = None, limit: int = 50) -> list[dict]:
	"""Users inside the caller's scope."""
	admin = delegation.assert_delegate()

	filters = {"enabled": 1}
	# Match either the login or the display name: callers search by both, and a
	# full_name-only filter silently returns nothing for an email address.
	or_filters = (
		{"name": ("like", f"%{search}%"), "full_name": ("like", f"%{search}%")}
		if search
		else None
	)

	rows = frappe.get_all(
		"User",
		filters=filters,
		or_filters=or_filters,
		fields=["name", "full_name", "user_type", "module_profile"],
		limit=cint(limit) or 50,
		order_by="full_name asc",
	)

	# `get_all` already applies the query-condition hook, but a delegate whose
	# scope changed mid-session could hold a stale list, so each row is
	# re-checked against the same gate that authorises writes.
	manageable = [row for row in rows if delegation.can_manage(admin, row["name"])]

	for row in manageable:
		row["role_profiles"] = capability.get_user_role_profiles(row["name"])

	return manageable


@frappe.whitelist()
def get_grantable_profiles() -> list[dict]:
	"""The caller's allowlist, with what each profile grants."""
	admin = delegation.assert_delegate()
	index = capability.build_capability_index()

	profiles = []
	for row in admin.get("allowed_role_profiles") or []:
		granted = index.get(row.role_profile, {})
		profiles.append(
			{
				"role_profile": row.role_profile,
				"doctype_count": len(granted),
				"perm_count": capability.total_perm_count(granted),
			}
		)

	# Tightest first, so the least-privilege option is the obvious one to pick.
	return sorted(profiles, key=lambda row: row["perm_count"])


@frappe.whitelist()
def preview_assignment(
	user: str, role_profile: str, module_profile: str | None = None
) -> dict:
	"""What would change, without changing it."""
	admin = delegation.assert_delegate()
	delegation.assert_can_manage(admin, user)
	delegation.assert_can_grant(admin, role_profile, module_profile)

	before = audit.snapshot(user)
	index = capability.build_capability_index()

	profiles_after = _target_profiles(before["profiles"], role_profile)
	roles_after = _profile_roles(profiles_after)

	return {
		"user": user,
		"profiles_before": before["profiles"],
		"profiles_after": profiles_after,
		"module_profile_before": before["module_profile"],
		"module_profile_after": module_profile or before["module_profile"],
		"roles_gained": sorted(roles_after - before["roles"]),
		"roles_lost": sorted(before["roles"] - roles_after),
		"grants": {
			doctype: sorted(perms)
			for doctype, perms in sorted(index.get(role_profile, {}).items())
		},
	}


@frappe.whitelist()
def assign_access(
	user: str, role_profile: str, module_profile: str | None = None
) -> dict:
	"""Assign a role profile, and optionally a module profile, to `user`."""
	admin = delegation.assert_delegate()
	delegation.assert_can_manage(admin, user)
	delegation.assert_can_grant(admin, role_profile, module_profile)

	before = audit.snapshot(user)

	doc = frappe.get_doc("User", user)
	capability.set_user_role_profiles(
		doc, _target_profiles(before["profiles"], role_profile)
	)
	if module_profile:
		doc.module_profile = module_profile

	# `role_profiles` is permlevel 1, so no permitted route to this write exists.
	# Reached only after all three gates above have passed.
	doc.save(ignore_permissions=True)

	after = audit.snapshot(user)
	unchanged = (before["profiles"], before["module_profile"]) == (
		after["profiles"],
		after["module_profile"],
	)
	outcome = audit.OUTCOME_NO_CHANGE if unchanged else audit.OUTCOME_APPLIED
	log = audit.log_assignment(user, before, after, audit.TRIGGER_MANUAL, outcome=outcome)

	return {
		"user": user,
		"profiles": after["profiles"],
		"module_profile": after["module_profile"],
		"roles_gained": sorted(after["roles"] - before["roles"]),
		"roles_lost": sorted(before["roles"] - after["roles"]),
		"outcome": outcome,
		"log": log,
	}
