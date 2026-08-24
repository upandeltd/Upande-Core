# Copyright (c) 2026, ghost-mann and contributors
# For license information, please see license.txt

"""The gated write API for access assignment.

Lives in the package __init__ rather than a sibling module because this app
already has an `api` package (it_dashboard). Keeping the name means every
caller path - `upande_core.api.assign_access` in Python and in the
front end - survived the fold unchanged.
"""

import frappe
from frappe.utils import cint

from upande_core import audit, capability, delegation, privilege, settings


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
	admin = delegation.acting_admin()

	like = f"%{txt or ''}%"
	args = {
		"like": like,
		"page_len": cint(page_len) or 20,
		"start": cint(start) or 0,
		"reserved": tuple(delegation.RESERVED_USERS),
	}

	if admin is None:
		# Unbounded caller: every enabled user, employee record or not. Joining
		# Employee here would hide the 170 unlinked accounts, which are exactly
		# the ones a System Manager most often needs to reach.
		rows = frappe.db.sql(
			"""
			select u.name, u.full_name
			from `tabUser` u
			where u.enabled = 1 and u.name not in %(reserved)s
			  and (u.name like %(like)s or u.full_name like %(like)s)
			order by u.full_name
			limit %(page_len)s offset %(start)s
			""",
			args,
		)
		return rows

	companies = delegation.scope_companies(admin)
	if not companies:
		return []

	args["companies"] = tuple(companies)
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
		args,
	)

	# Branch scope and the reserved-user rules live in `can_manage`; re-check so
	# the picker and the write gate can never disagree.
	return [row for row in rows if delegation.can_manage(admin, row[0])]


@frappe.whitelist()
def get_manageable_users(search: str | None = None, limit: int = 50) -> list[dict]:
	"""Users the caller may administer.

	A System Manager gets the whole site; a delegate gets their scope.
	"""
	admin = delegation.acting_admin()

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
	manageable = [
		row
		for row in rows
		if row["name"] not in delegation.RESERVED_USERS
		and (admin is None or delegation.can_manage(admin, row["name"]))
	]

	for row in manageable:
		row["role_profiles"] = capability.get_user_role_profiles(row["name"])

	return manageable


@frappe.whitelist()
def get_grantable_profiles() -> list[dict]:
	"""What the caller may hand out, with what each profile grants.

	A delegate gets their allowlist. A System Manager gets every profile on the
	site, flagged with whether it is privileged - they may grant those, but the
	dashboard says so before they do.
	"""
	admin = delegation.acting_admin()
	index = capability.build_capability_index()

	names = (
		[row.role_profile for row in admin.get("allowed_role_profiles") or []]
		if admin
		else frappe.get_all("Role Profile", pluck="name")
	)

	profiles = []
	for name in names:
		granted = index.get(name, {})
		profiles.append(
			{
				"role_profile": name,
				"doctype_count": len(granted),
				"perm_count": capability.total_perm_count(granted),
				"privileged": bool(privilege.privileged_grants(name)) if not admin else False,
			}
		)

	# Tightest first, so the least-privilege option is the obvious one to pick.
	return sorted(profiles, key=lambda row: row["perm_count"])


@frappe.whitelist()
def preview_assignment(
	user: str, role_profile: str, module_profile: str | None = None
) -> dict:
	"""What would change, without changing it."""
	admin = delegation.acting_admin()
	delegation.assert_target(admin, user)
	delegation.assert_grant(admin, role_profile, module_profile)

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


def write_assignment(
	user: str,
	role_profile: str,
	module_profile: str | None = None,
	trigger: str = audit.TRIGGER_MANUAL,
	notes: str | None = None,
) -> dict:
	"""Put `role_profile` on `user` and log it. The only writer.

	Ungated on purpose. `role_profiles` sits at permlevel 1, so nothing reaches
	this except through a caller that has already established the right to make
	the change - `assign_access` for a named profile, `compose.apply` for one it
	just built. Keeping the write in one place is what makes "every change is in
	the log" true rather than aspirational; adding a second writer would quietly
	make it false.

	Not whitelisted. Do not call it from the client.
	"""
	before = audit.snapshot(user)

	doc = frappe.get_doc("User", user)
	capability.set_user_role_profiles(
		doc, _target_profiles(before["profiles"], role_profile)
	)
	if module_profile:
		doc.module_profile = module_profile

	doc.save(ignore_permissions=True)

	after = audit.snapshot(user)
	unchanged = (before["profiles"], before["module_profile"]) == (
		after["profiles"],
		after["module_profile"],
	)
	outcome = audit.OUTCOME_NO_CHANGE if unchanged else audit.OUTCOME_APPLIED
	log = audit.log_assignment(user, before, after, trigger, outcome=outcome, notes=notes)

	return {
		"user": user,
		"profiles": after["profiles"],
		"module_profile": after["module_profile"],
		"roles_gained": sorted(after["roles"] - before["roles"]),
		"roles_lost": sorted(before["roles"] - after["roles"]),
		"outcome": outcome,
		"log": log,
	}


@frappe.whitelist()
def assign_access(
	user: str, role_profile: str, module_profile: str | None = None
) -> dict:
	"""Assign a role profile, and optionally a module profile, to `user`.

	Replaces what they hold. For the additive alternative - keep everything they
	have and add what they asked for - see `upande_core.compose`.
	"""
	admin = delegation.acting_admin()
	delegation.assert_target(admin, user)
	delegation.assert_grant(admin, role_profile, module_profile)

	return write_assignment(user, role_profile, module_profile)
