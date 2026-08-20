# Copyright (c) 2026, Upande and contributors
# For license information, please see license.txt

"""Shared test fixtures.

`IntegrationTestCase` rolls back once per class, not per test
(frappe/tests/classes/integration_test_case.py:72), so every helper here is
idempotent and callers clear their own mutable rows in setUp.

Custom DocPerm defaults `read` and `export` to 1. Every helper therefore sets
all tracked rights explicitly, including the denied ones - otherwise a fixture
meant to grant `read` silently grants `export` too.
"""

import frappe

# ToDo is chosen as the innocuous grant target: it is a core doctype nothing in
# this app depends on, so flipping it to Custom-DocPerm-only for the duration of
# a test harms nothing. Never point a fixture at a doctype this app reads.
INNOCUOUS_DOCTYPE = "ToDo"

ALL_RIGHTS = ("read", "write", "create", "submit", "cancel", "delete", "report", "export")


def ensure_role(role: str) -> str:
	if not frappe.db.exists("Role", role):
		frappe.get_doc({"doctype": "Role", "role_name": role}).insert(ignore_permissions=True)
	return role


def grant(role: str, doctype: str, *rights: str) -> None:
	"""Give `role` exactly `rights` on `doctype`, and nothing else."""
	existing = frappe.get_all(
		"Custom DocPerm", filters={"role": role, "parent": doctype, "permlevel": 0}, pluck="name"
	)
	for name in existing:
		frappe.delete_doc("Custom DocPerm", name, force=True)

	row = {"doctype": "Custom DocPerm", "parent": doctype, "role": role, "permlevel": 0}
	row.update({right: (1 if right in rights else 0) for right in ALL_RIGHTS})
	frappe.get_doc(row).insert(ignore_permissions=True)


def ensure_profile(profile: str, *roles: str) -> str:
	if frappe.db.exists("Role Profile", profile):
		doc = frappe.get_doc("Role Profile", profile)
		doc.set("roles", [{"role": role} for role in roles])
		doc.save(ignore_permissions=True)
	else:
		frappe.get_doc(
			{
				"doctype": "Role Profile",
				"role_profile": profile,
				"roles": [{"role": role} for role in roles],
			}
		).insert(ignore_permissions=True)
	return profile


def ensure_user(email: str) -> str:
	if not frappe.db.exists("User", email):
		frappe.get_doc(
			{
				"doctype": "User",
				"email": email,
				"first_name": email.split("@")[0],
				"send_welcome_email": 0,
				"user_type": "System User",
			}
		).insert(ignore_permissions=True)
	return email


def ensure_employee(user: str, company: str, designation: str | None = None) -> str:
	"""An active Employee linked to `user`, which is what puts them in scope."""
	name = frappe.db.get_value("Employee", {"user_id": user})
	if name:
		doc = frappe.get_doc("Employee", name)
		doc.company = company
		doc.status = "Active"
		if designation:
			doc.designation = designation
		doc.save(ignore_permissions=True)
		return name

	gender = frappe.get_all("Gender", pluck="name", limit=1)[0]
	doc = {
		"doctype": "Employee",
		"first_name": user.split("@")[0],
		"user_id": user,
		"company": company,
		"status": "Active",
		"date_of_joining": "2020-01-01",
		"date_of_birth": "1990-01-01",
		"gender": gender,
	}
	if designation:
		doc["designation"] = designation

	return frappe.get_doc(doc).insert(ignore_permissions=True).name


def ensure_designation(designation: str) -> str:
	if not frappe.db.exists("Designation", designation):
		frappe.get_doc(
			{"doctype": "Designation", "designation_name": designation}
		).insert(ignore_permissions=True)
	return designation


def clear_map(designation: str) -> None:
	for name in frappe.get_all(
		"Designation Access Map", filters={"designation": designation}, pluck="name"
	):
		frappe.delete_doc("Designation Access Map", name, force=True)


def clear_delegate(user: str) -> None:
	if frappe.db.exists("Delegated User Admin", user):
		frappe.delete_doc("Delegated User Admin", user, force=True)
