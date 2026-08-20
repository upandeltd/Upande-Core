# Copyright (c) 2026, Upande and contributors
# For license information, please see license.txt

"""Install-time setup.

The demo data has to be seeded from `after_install`, not from a patch.
`frappe.installer.install_app` calls `set_all_patches_as_completed(app)` on a
fresh install, which marks every entry in patches.txt as already run without
executing it - so a seed patch would never fire on install, and `bench migrate`
would then skip it forever as well.

The patch is kept for sites that installed the app before the patch existed;
`seed()` is idempotent, so running from both paths is harmless.
"""

import frappe

from role_advisor.demo_data import seed


def after_install():
	seed()
	frappe.db.commit()
