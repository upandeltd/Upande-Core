# Copyright (c) 2026, Upande and contributors
# For license information, please see license.txt

"""Rename IT Operations to IT Dashboard, in the Upande CRM design.

All of the work is in `upande_core.it_workspace.sync`, which also runs after every migrate; the patch exists so it runs once
at the right point among the older workspace patches on a site that is being brought up to date.
"""

import frappe


def execute():
	from upande_core import it_workspace

	it_workspace.sync()
