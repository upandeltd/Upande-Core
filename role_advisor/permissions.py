# Copyright (c) 2026, ghost-mann and contributors
# For license information, please see license.txt

"""Deny-only permission hooks bounding what a delegate can see.

Core already registers hooks for `User`. `permission_query_conditions[doctype]`
is a list joined with " and " (frappe/model/db_query.py:1157), and controller
`has_permission` hooks can only deny, never grant
(frappe/permissions.py:480). So everything here narrows core's result and
nothing here can widen it.

`User Permission` has no core hooks at all, which is why the middle pair
exists: without them a delegate could delete their own Company scoping row and
see every company's data.
"""

import frappe

from role_advisor import delegation, settings

# Rights that let a delegate alter their own boundary. `read` is included:
# harmless in itself, but a readable row invites a UI that offers delete.
_SELF_DENIED = frozenset({"read", "write", "create", "delete", "submit", "cancel"})


def _escape_list(values: list[str]) -> str:
	return ", ".join(frappe.db.escape(value) for value in values)


def _in_scope_users_subquery(field: str, values: list[str]) -> str:
	return f"""select e.user_id from `tabEmployee` e
		where e.user_id is not null and e.user_id != ''
		  and e.status = 'Active'
		  and e.`{field}` in ({_escape_list(values)})"""


def user_query_conditions(user: str | None = None, doctype: str | None = None) -> str:
	"""Restrict a delegate's User list to their company scope.

	Returns "" for anyone who is not an enabled delegate, which is what makes
	enforcement opt-in rather than a flag day for the 23 User Manager holders.
	"""
	user = user or frappe.session.user
	if user == "Administrator":
		return ""

	admin = delegation.current_admin(user)
	if not admin:
		return ""

	companies = delegation.scope_companies(admin)
	if not companies:
		# A delegate with no scope should see nobody rather than everybody.
		return f"`tabUser`.name = {frappe.db.escape(user)}"

	conditions = [f"`tabUser`.name in ({_in_scope_users_subquery('company', companies)})"]

	branches = delegation.scope_branches(admin)
	if branches:
		conditions.append(
			f"`tabUser`.name in ({_in_scope_users_subquery('branch', branches)})"
		)

	scoped = " and ".join(conditions)

	# A delegate must still see their own record or their desk breaks.
	return f"(({scoped}) or `tabUser`.name = {frappe.db.escape(user)})"


def user_has_permission(
	doc, ptype: str | None = None, user: str | None = None, debug: bool = False
) -> bool:
	"""Block opening an out-of-scope User by name.

	The query condition filters lists; it does nothing about a typed URL or a
	direct API read, which is why this exists as a separate layer.
	"""
	user = user or frappe.session.user
	if user == "Administrator":
		return True

	admin = delegation.current_admin(user)
	if not admin:
		return True

	if doc.name == user:
		return True

	return delegation.can_manage(admin, doc.name)


def user_permission_query_conditions(
	user: str | None = None, doctype: str | None = None
) -> str:
	"""Restrict a delegate to User Permission rows of users they administer.

	Core registers no hook for this doctype, so without this a `User Manager`
	holder - who has full CRUD on it - can delete their own Company row and see
	every company's data.
	"""
	user = user or frappe.session.user
	if user == "Administrator":
		return ""

	admin = delegation.current_admin(user)
	if not admin:
		return ""

	companies = delegation.scope_companies(admin)
	if not companies:
		return "1 = 0"

	return f"""(
		`tabUser Permission`.user != {frappe.db.escape(user)}
		and `tabUser Permission`.user in ({_in_scope_users_subquery('company', companies)})
	)"""


def user_permission_has_permission(
	doc, ptype: str | None = None, user: str | None = None, debug: bool = False
) -> bool:
	"""Deny a delegate any access to their own User Permission rows."""
	user = user or frappe.session.user
	if user == "Administrator":
		return True

	admin = delegation.current_admin(user)
	if not admin:
		return True

	if doc.user == user and (ptype or "read") in _SELF_DENIED:
		return False

	return delegation.can_manage(admin, doc.user)


def delegated_admin_has_permission(
	doc, ptype: str | None = None, user: str | None = None, debug: bool = False
) -> bool:
	"""A delegate may read their own record only, and never write it.

	Read-own cannot be expressed as a role grant - a grant would let every
	delegate read every other delegate's allowlist. Write is denied outright: a
	delegate who could edit this record would widen their own allowlist.
	"""
	user = user or frappe.session.user
	if user == "Administrator":
		return True

	if "System Manager" in frappe.get_roles(user):
		return True

	if doc.user != user:
		return False

	return (ptype or "read") == "read"


# ---------------------------------------------------------------------------
# The apps screen
# ---------------------------------------------------------------------------


def has_app_permission() -> bool:
	"""Should Role Advisor show on this user's /apps screen?

	Anyone who can administer access, plus anyone who is a delegate on paper
	even if their record is currently disabled - hiding the app from someone
	mid-rollout reads as the app being broken. Everyone else reaches their own
	access through `/my-access`, which needs no role at all.
	"""
	roles = frappe.get_roles()
	if "System Manager" in roles or settings.delegate_role() in roles:
		return True

	return bool(
		frappe.db.exists("Delegated User Admin", {"user": frappe.session.user})
	)
