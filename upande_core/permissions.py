# Copyright (c) 2026, Upande and contributors
# For license information, please see license.txt

"""Who sees IT Operations on the apps screen."""

import frappe

# The role the IT dashboard has always gated its writes on, alongside System
# Manager. Kept as the name it already has on live rather than renamed.
IT_ROLE = "IT User Admin"


def has_app_permission() -> bool:
	"""Show the tile to anyone who can do something on the page.

	Deliberately broader than the write gates: the page holds helpdesk, assets,
	monitoring and attendance as well as access, and each view applies its own
	rule. Someone who can reach only one of them should still find the door.
	"""
	roles = set(frappe.get_roles())
	if {"System Manager", IT_ROLE} & roles:
		return True

	# A delegated access administrator, configured or merely on paper - hiding
	# the app from somebody mid-rollout reads as the app being broken.
	from role_advisor import settings

	if settings.delegate_role() in roles:
		return True

	return bool(frappe.db.exists("Delegated User Admin", {"user": frappe.session.user}))
