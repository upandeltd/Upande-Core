# Copyright (c) 2026, Upande and contributors
# For license information, please see license.txt

"""Seed data for exercising the advisor.

Called from the post-model-sync patch and from the test suite, so the scenarios
an administrator can click through in the console are byte-for-byte the ones the
tests assert on. Every helper is idempotent - `seed()` can be run repeatedly.

Everything created here is prefixed `RA ` / `RA-` so it is easy to identify and
remove. Permissions are attached to the app's own demo doctypes, never to real
ones: a Custom DocPerm row causes core to discard *all* standard DocPerms for
that doctype, for every role on the site.
"""

import frappe
from frappe.permissions import setup_custom_perms

from role_advisor.api import TRACKED_PERMS, clear_capability_index, set_user_role_profiles

DEMO_DOCTYPES = (
	"RA Demo Harvest Entry",
	"RA Demo Pick List",
	"RA Demo Payment Voucher",
	"RA Demo Quality Check",
)

# {role: {doctype: (perm, ...)}}
DEMO_ROLES = {
	"RA Harvest Clerk": {
		"RA Demo Harvest Entry": ("read", "write", "create", "report"),
	},
	"RA Harvest Submitter": {
		"RA Demo Harvest Entry": ("read", "submit"),
	},
	"RA Pick List Viewer": {
		"RA Demo Pick List": ("read",),
	},
	"RA Pick List Submitter": {
		"RA Demo Pick List": ("read", "submit"),
	},
	"RA Finance Clerk": {
		"RA Demo Payment Voucher": ("read", "write", "create", "submit"),
	},
	"RA Quality Inspector": {
		"RA Demo Quality Check": ("read", "write", "create"),
	},
	# Deliberately bundled into no role profile. This is what makes the
	# "Gap - New Profile Needed" case reachable: the right exists on the site, but
	# nothing packages it, so the fix is a new profile rather than a new role.
	"RA Payment Auditor": {
		"RA Demo Payment Voucher": ("read", "cancel"),
	},
}

# {role_profile: (role, ...)}
# Resulting capability sizes, which drive the tightest-fit ranking:
#   RA Harvest Basic      -> Harvest{read,write,create,report} + PickList{read}            =  5
#   RA Harvest Supervisor -> Harvest{+submit}                  + PickList{read,submit}     =  7
#   RA Finance Only       -> Voucher{read,write,create,submit}                             =  4
#   RA Operations Broad   -> everything above plus Quality{read,write,create}              = 14
DEMO_ROLE_PROFILES = {
	"RA Harvest Basic": ("RA Harvest Clerk", "RA Pick List Viewer"),
	"RA Harvest Supervisor": (
		"RA Harvest Clerk",
		"RA Harvest Submitter",
		"RA Pick List Submitter",
	),
	"RA Finance Only": ("RA Finance Clerk",),
	"RA Operations Broad": (
		"RA Harvest Clerk",
		"RA Harvest Submitter",
		"RA Pick List Submitter",
		"RA Finance Clerk",
		"RA Quality Inspector",
	),
}

# (transaction_name, reference_doctype, required_perm, module, keywords)
DEMO_TRANSACTIONS = (
	(
		"View Harvest Entry",
		"RA Demo Harvest Entry",
		"read",
		"Mona Flowers Harvest",
		"harvest, view, open",
	),
	(
		"Record Harvest Entry",
		"RA Demo Harvest Entry",
		"create",
		"Mona Flowers Harvest",
		"harvest, new, capture",
	),
	(
		"Amend Harvest Entry",
		"RA Demo Harvest Entry",
		"write",
		"Mona Flowers Harvest",
		"harvest, edit, correct",
	),
	(
		"Submit Harvest Entry",
		"RA Demo Harvest Entry",
		"submit",
		"Mona Flowers Harvest",
		"harvest, approve, post",
	),
	(
		"Cancel Harvest Entry",
		"RA Demo Harvest Entry",
		"cancel",
		"Mona Flowers Harvest",
		"harvest, void, reverse",
	),
	(
		"Run Harvest Report",
		"RA Demo Harvest Entry",
		"report",
		"Mona Flowers Harvest",
		"harvest, report, analyse",
	),
	("View Order Pick List", "RA Demo Pick List", "read", "Warehouse", "pick list, view"),
	(
		"Submit Order Pick List",
		"RA Demo Pick List",
		"submit",
		"Warehouse",
		"pick list, dispatch, release",
	),
	(
		"Delete Order Pick List",
		"RA Demo Pick List",
		"delete",
		"Warehouse",
		"pick list, remove, purge",
	),
	("View Payment Voucher", "RA Demo Payment Voucher", "read", "Finance", "payment, voucher"),
	(
		"Approve Payment Voucher",
		"RA Demo Payment Voucher",
		"submit",
		"Finance",
		"payment, approve, release",
	),
	(
		"Cancel Payment Voucher",
		"RA Demo Payment Voucher",
		"cancel",
		"Finance",
		"payment, void, reverse",
	),
	(
		"Record Quality Check",
		"RA Demo Quality Check",
		"create",
		"Quality",
		"quality, inspection, qc",
	),
)

DEMO_USERS = {
	# The user the four documented scenarios are written against.
	"ra.demo.clerk@example.com": ("RA Harvest Basic",),
	# Holds nothing, for checking the no-profile path.
	"ra.demo.newjoiner@example.com": (),
}


def seed() -> None:
	"""Create every demo record. Safe to run more than once."""
	for role in DEMO_ROLES:
		_ensure_role(role)

	for doctype in DEMO_DOCTYPES:
		# Copies the doctype's standard DocPerms into Custom DocPerm the first
		# time, so System Manager keeps the access declared in the doctype JSON.
		setup_custom_perms(doctype)

	for role, grants in DEMO_ROLES.items():
		for doctype, perms in grants.items():
			_ensure_custom_docperm(doctype, role, perms)

	for profile, roles in DEMO_ROLE_PROFILES.items():
		_ensure_role_profile(profile, roles)

	for transaction in DEMO_TRANSACTIONS:
		_ensure_transaction(*transaction)

	for user, profiles in DEMO_USERS.items():
		_ensure_user(user, profiles)

	_validate_demo_doctype_permissions()

	clear_capability_index()


def _ensure_role(name: str) -> None:
	if frappe.db.exists("Role", name):
		return

	frappe.get_doc(
		{
			"doctype": "Role",
			"role_name": name,
			"desk_access": 1,
			# Kept out of the "new user gets these automatically" set so seeding
			# cannot widen access for anyone who is not explicitly assigned it.
			"is_custom": 1,
		}
	).insert(ignore_permissions=True)


def _ensure_custom_docperm(doctype: str, role: str, perms: tuple[str, ...]) -> None:
	"""Create or correct the permlevel-0 Custom DocPerm row for (doctype, role)."""
	name = frappe.db.get_value(
		"Custom DocPerm", {"parent": doctype, "role": role, "permlevel": 0, "if_owner": 0}
	)

	# Every tracked right is set explicitly, including the ones being denied.
	# Custom DocPerm defaults `read` AND `export` to 1, so listing only the
	# granted rights would hand every seeded role an export permission it was
	# never meant to have - and make the seed depend on doctype field defaults
	# rather than on this table. Spelling out the zeroes also makes re-seeding
	# after an edit converge instead of accumulating grants.
	values = {perm: (1 if perm in perms else 0) for perm in TRACKED_PERMS}

	if name:
		doc = frappe.get_doc("Custom DocPerm", name)
		doc.update(values)
		doc.save(ignore_permissions=True)
		return

	frappe.get_doc(
		{
			"doctype": "Custom DocPerm",
			"parent": doctype,
			"parenttype": "DocType",
			"parentfield": "permissions",
			"role": role,
			"permlevel": 0,
			**values,
		}
	).insert(ignore_permissions=True)


def _ensure_role_profile(name: str, roles: tuple[str, ...]) -> None:
	doc = (
		frappe.get_doc("Role Profile", name)
		if frappe.db.exists("Role Profile", name)
		else frappe.new_doc("Role Profile")
	)
	doc.role_profile = name

	doc.set("roles", [])
	for role in roles:
		doc.append("roles", {"role": role})

	# Document.save() routes a new doc to insert(), so this covers both cases.
	doc.save(ignore_permissions=True)


def _ensure_transaction(
	transaction_name: str, reference_doctype: str, required_perm: str, module: str, keywords: str
) -> None:
	doc = (
		frappe.get_doc("Transaction Catalog", transaction_name)
		if frappe.db.exists("Transaction Catalog", transaction_name)
		else frappe.new_doc("Transaction Catalog")
	)
	doc.update(
		{
			"transaction_name": transaction_name,
			"reference_doctype": reference_doctype,
			"required_perm": required_perm,
			"module": module,
			"keywords": keywords,
			"description": f"Demo transaction: {required_perm} on {reference_doctype}.",
		}
	)

	doc.save(ignore_permissions=True)


def _ensure_user(email: str, profiles: tuple[str, ...]) -> None:
	doc = (
		frappe.get_doc("User", email)
		if frappe.db.exists("User", email)
		else frappe.new_doc("User")
	)

	first_name = email.split("@")[0].replace(".", " ").title()
	doc.update(
		{
			"email": email,
			"first_name": first_name,
			"user_type": "System User",
			# example.com addresses must never be mailed.
			"send_welcome_email": 0,
		}
	)
	doc.flags.no_welcome_mail = True

	# v16 holds profiles in a child table. Re-seeding an existing user has to go
	# through the helper, or the deprecated role_profile_name mirror re-appends
	# whatever profile the user last had.
	set_user_role_profiles(doc, list(profiles))

	doc.save(ignore_permissions=True)


def _validate_demo_doctype_permissions() -> None:
	from frappe.core.doctype.doctype.doctype import validate_permissions_for_doctype

	for doctype in DEMO_DOCTYPES:
		validate_permissions_for_doctype(doctype)


def teardown() -> None:
	"""Remove the demo records. Not called automatically; provided for cleanup."""
	for email in DEMO_USERS:
		if frappe.db.exists("User", email):
			frappe.delete_doc("User", email, force=True, ignore_permissions=True)

	for transaction, *_ in DEMO_TRANSACTIONS:
		if frappe.db.exists("Transaction Catalog", transaction):
			frappe.delete_doc("Transaction Catalog", transaction, force=True, ignore_permissions=True)

	for profile in DEMO_ROLE_PROFILES:
		if frappe.db.exists("Role Profile", profile):
			frappe.delete_doc("Role Profile", profile, force=True, ignore_permissions=True)

	for role in DEMO_ROLES:
		frappe.db.delete("Custom DocPerm", {"role": role})
		if frappe.db.exists("Role", role):
			frappe.delete_doc("Role", role, force=True, ignore_permissions=True)

	clear_capability_index()
