# Copyright (c) 2026, ghost-mann and contributors
# For license information, please see license.txt

"""Re-home the access metadata after the Role Advisor app was folded in here.

The doctypes, reports, pages and workspace used to belong to a separate app and
carry `module = "Role Advisor"` in the database. Their JSON now says
`Upande Core`, so without this the two disagree: Frappe resolves a doctype's
controller through its module, and a stale module sends it looking in an app
that is no longer installed.

Data is untouched. Doctype *names* did not change in the fold, so every
`tab<Doctype>` table and every row in it stays exactly where it was - this
moves metadata only.

Idempotent, and safe on a site that never had the old app: the update simply
matches nothing.
"""

import frappe

OLD_MODULE = "Role Advisor"
NEW_MODULE = "Upande Core"

# Every doctype that came across, named explicitly rather than swept by module,
# so a site that has its own unrelated "Role Advisor" module is not raided.
ADOPTED = (
	"Access Assignment Log",
	"Access Request",
	"Access Request Line",
	"Access Transaction",
	"Access Transaction Requirement",
	"Delegated Branch",
	"Delegated Company",
	"Delegated Module Profile",
	"Delegated Role Profile",
	"Delegated User Admin",
	"Designation Access Map",
	"User Access Never Block Module",
	"User Access Privileged Doctype",
	"User Access Settings",
)


def execute():
	moved = {}

	for name in ADOPTED:
		if frappe.db.get_value("DocType", name, "module") == OLD_MODULE:
			frappe.db.set_value("DocType", name, "module", NEW_MODULE, update_modified=False)
			moved.setdefault("DocType", []).append(name)

	# Reports, pages and the workspace are addressed by module: they were only
	# ever created by the folded app, so there is nothing else to catch.
	for doctype in ("Report", "Page", "Workspace"):
		for name in frappe.get_all(doctype, filters={"module": OLD_MODULE}, pluck="name"):
			frappe.db.set_value(doctype, name, "module", NEW_MODULE, update_modified=False)
			moved.setdefault(doctype, []).append(name)

	if moved:
		for doctype, names in moved.items():
			print(f"  adopted {len(names)} {doctype}: {', '.join(sorted(names))}")
		frappe.clear_cache()
