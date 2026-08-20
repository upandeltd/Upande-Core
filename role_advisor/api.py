# Copyright (c) 2026, Upande and contributors
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
def get_manageable_users(search: str | None = None, limit: int = 50) -> list[dict]:
	"""Users inside the caller's scope."""
	admin = delegation.assert_delegate()

	filters = {"enabled": 1}
	if search:
		filters["full_name"] = ("like", f"%{search}%")

	rows = frappe.get_all(
		"User",
		filters=filters,
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
