# Copyright (c) 2026, ghost-mann and contributors
# For license information, please see license.txt

"""Who may a delegated administrator reach, and what may they hand out?

Enforcement is opt-in: restrictions apply only to a `delegate_role` holder who
also has an enabled `Delegated User Admin` record. Without one, behaviour is
stock. That makes rollout one person at a time, and means no migration can lock
anyone out.
"""

import frappe
from frappe import _

from upande_core import mapping, privilege, settings

CACHE_ATTR = "_upande_core_delegated_admins"

# Never administrable by a delegate, whatever their scope says.
RESERVED_USERS = frozenset({"Administrator", "Guest"})


def clear_cache(doc=None, method=None) -> None:
	"""Drop the request-local admin cache. Also a doc_events hook."""
	if hasattr(frappe.local, CACHE_ATTR):
		delattr(frappe.local, CACHE_ATTR)


def current_admin(user: str | None = None):
	"""Return the caller's enabled Delegated User Admin record, or None.

	Memoised per request: the permission hooks call this for every User row
	fetched, so a query per row would be a real cost on a 374-user list.
	"""
	user = user or frappe.session.user

	cache = getattr(frappe.local, CACHE_ATTR, None)
	if cache is None:
		cache = {}
		setattr(frappe.local, CACHE_ATTR, cache)

	if user not in cache:
		name = frappe.db.get_value(
			"Delegated User Admin", {"user": user, "enabled": 1}, "name"
		)
		cache[user] = frappe.get_doc("Delegated User Admin", name) if name else None

	return cache[user]


def assert_delegate(user: str | None = None):
	admin = current_admin(user)
	if not admin:
		frappe.throw(
			_("You are not configured as a delegated user administrator."),
			frappe.PermissionError,
			title=_("Not A Delegate"),
		)

	return admin


def scope_companies(admin) -> list[str]:
	return [row.company for row in admin.get("companies") or []]


def scope_branches(admin) -> list[str]:
	return [row.branch for row in admin.get("branches") or []]


def can_manage(admin, target: str) -> bool:
	"""Is `target` inside `admin`'s company (and optionally branch) scope?

	A target with no active Employee record has no company. Such users are
	unreachable by any delegate - deliberately: the 109 unlinked users on Kaitet
	include service accounts and Upande staff, and defaulting them to "in scope"
	would be the single worst failure mode here.
	"""
	if not target or target in RESERVED_USERS:
		return False

	scope = mapping.employee_scope(target)

	if settings.require_employee_link() and not scope.get("company"):
		return False

	if scope.get("company") not in scope_companies(admin):
		return False

	branches = scope_branches(admin)
	# An empty branch list means every branch within the allowed companies.
	if branches and scope.get("branch") not in branches:
		return False

	return True


def assert_can_manage(admin, target: str) -> None:
	if not can_manage(admin, target):
		frappe.throw(
			_("{0} is outside the users you administer.").format(target),
			frappe.PermissionError,
			title=_("Out Of Scope"),
		)


def assert_can_grant(admin, role_profile: str, module_profile: str | None = None) -> None:
	"""Refuse anything off the allowlist, or privileged regardless of allowlist."""
	allowed = {row.role_profile for row in admin.get("allowed_role_profiles") or []}
	if role_profile not in allowed:
		frappe.throw(
			_("{0} is not one of the role profiles you may grant.").format(role_profile),
			frappe.PermissionError,
			title=_("Not Grantable"),
		)

	# Re-checked here even though DelegatedUserAdmin.validate already refused it
	# at save: a profile's roles can be widened after it was allowlisted.
	grants = privilege.privileged_grants(role_profile)
	if grants:
		frappe.throw(
			_("{0} can no longer be delegated: it grants {1}.").format(
				role_profile, privilege.describe(grants)
			),
			frappe.PermissionError,
			title=_("Privileged Profile"),
		)

	if module_profile:
		allowed_modules = {
			row.module_profile for row in admin.get("allowed_module_profiles") or []
		}
		if module_profile not in allowed_modules:
			frappe.throw(
				_("{0} is not one of the module profiles you may grant.").format(
					module_profile
				),
				frappe.PermissionError,
				title=_("Not Grantable"),
			)


# ---------------------------------------------------------------------------
# Acting as an administrator
#
# Everything above bounds a *delegate*. A System Manager is not bounded: they
# already hold write on `User`, `Role`, `Role Profile` and `Custom DocPerm`, so
# refusing them here would buy no safety and would leave the person who
# configures delegation unable to use the tool they configure. Routing them
# through the same functions is a net gain - their change gets an Access
# Assignment Log row, which the desk form does not write.
# ---------------------------------------------------------------------------


def acting_admin(user: str | None = None):
	"""The record bounding the caller, or None when the caller is unbounded.

	None means "no scope, no allowlist" - it does not mean "no checks": the
	reserved-user rule below still applies, and every write is still logged.
	"""
	if "System Manager" in frappe.get_roles(user or frappe.session.user):
		return None

	return assert_delegate(user)


def assert_target(admin, target: str) -> None:
	"""May the caller act on this user at all?

	Administrator and Guest are refused for everyone. Assigning a role profile
	replaces the holder's roles, so pointing this at Administrator would prune
	the only account guaranteed to be able to undo it.
	"""
	if not target:
		frappe.throw(_("Choose a user first."), frappe.ValidationError)

	if target in RESERVED_USERS:
		frappe.throw(
			_("{0} cannot be assigned a role profile.").format(target),
			frappe.PermissionError,
			title=_("Reserved Account"),
		)

	if admin:
		assert_can_manage(admin, target)


def assert_grant(admin, role_profile: str, module_profile: str | None = None) -> None:
	"""Enforce the allowlist and the privilege denylist, for a delegate only."""
	if admin:
		assert_can_grant(admin, role_profile, module_profile)
