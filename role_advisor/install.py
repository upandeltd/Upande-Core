# Copyright (c) 2026, ghost-mann and contributors
# For license information, please see license.txt

"""Install-time setup.

Seeding must happen here, never from a patch: `frappe.installer.install_app`
calls `set_all_patches_as_completed(app)` on a fresh install, marking every
patches.txt entry as run without executing it - so a seed patch never fires,
and `bench migrate` then skips it forever too.
"""

import frappe

from role_advisor.settings import PRIVILEGED_DOCTYPE_DEFAULTS


def after_install():
	seed_settings()
	frappe.db.commit()


def seed_settings():
	"""Populate `User Access Settings` child tables. Idempotent."""
	doc = frappe.get_single("User Access Settings")

	existing = {row.document_type for row in doc.get("privileged_doctypes") or []}
	for doctype in PRIVILEGED_DOCTYPE_DEFAULTS:
		if doctype not in existing and frappe.db.exists("DocType", doctype):
			doc.append("privileged_doctypes", {"document_type": doctype})

	doc.save(ignore_permissions=True)
