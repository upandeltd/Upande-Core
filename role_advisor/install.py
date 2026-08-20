# Copyright (c) 2026, Upande and contributors
# For license information, please see license.txt

"""Install-time setup.

Seeding must happen here, never from a patch: `frappe.installer.install_app`
calls `set_all_patches_as_completed(app)` on a fresh install, marking every
patches.txt entry as run without executing it - so a seed patch never fires,
and `bench migrate` then skips it forever too.
"""

import frappe


def after_install():
	frappe.db.commit()
