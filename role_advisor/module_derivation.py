# Copyright (c) 2026, ghost-mann and contributors
# For license information, please see license.txt

"""Derive a draft Module Profile from what a Role Profile grants.

Kaitet's hand-built profiles work by blocking what the author thought of, which
is why `cgi`, `Domain Enrichment`, `Kenya Etims Compliance`, `Loan Origination`
and `TagMeter Control` sit in *every* profile's allowed list - not by intent.
Deriving from granted doctypes instead is both tighter and more consistent.

There is no mandatory safe-list: `Roses Production Supervisor` allows 8 of 73
modules, blocking `Core` and `Desk`, and works in production. So
`never_block_modules` defaults to empty and is configuration, not a constant.

Sequenced last because module profiles are navigation hygiene, not containment
- `frappe/permissions.py` never consults modules.
"""

import frappe

from role_advisor import capability, settings

# Drafts are prefixed rather than flagged: Module Profile has no enabled field,
# so the name is the only place a "do not assign yet" marker can live.
DRAFT_PREFIX = "[draft] "


def _module_by_doctype() -> dict[str, str]:
	return {
		row["name"]: row["module"]
		for row in frappe.get_all("DocType", fields=["name", "module"])
	}


def modules_for_profile(role_profile: str) -> set[str]:
	"""Modules containing at least one doctype this profile grants."""
	granted = capability.build_capability_index().get(role_profile, {})
	lookup = _module_by_doctype()

	return {lookup[doctype] for doctype in granted if doctype in lookup}


def blocked_for_profile(role_profile: str) -> list[str]:
	"""Every module except those the profile needs, and those never blocked."""
	allowed = modules_for_profile(role_profile) | set(settings.never_block_modules())
	all_modules = frappe.get_all("Module Def", pluck="name")

	return sorted(module for module in all_modules if module not in allowed)


def derive(dry_run: bool = True) -> list[dict]:
	"""Propose (and optionally write) one draft Module Profile per Role Profile."""
	if settings.module_profile_strategy() != "Derive from Role Profile":
		return []

	pattern = settings.naming_pattern()
	proposals = []

	for role_profile in frappe.get_all("Role Profile", pluck="name"):
		allowed = modules_for_profile(role_profile)
		if not allowed:
			# A profile granting nothing would derive a block-list covering every
			# module, leaving an empty desk rather than a tight one.
			continue

		name = DRAFT_PREFIX + pattern.format(role_profile=role_profile)
		blocked = blocked_for_profile(role_profile)

		proposals.append(
			{
				"role_profile": role_profile,
				"module_profile": name,
				"allowed_count": len(allowed),
				"blocked_count": len(blocked),
				"allowed": sorted(allowed),
			}
		)

		if dry_run or frappe.db.exists("Module Profile", name):
			continue

		frappe.get_doc(
			{
				"doctype": "Module Profile",
				"module_profile_name": name,
				"block_modules": [{"module": module} for module in blocked],
			}
		).insert(ignore_permissions=True)

	return sorted(proposals, key=lambda row: row["allowed_count"])
