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
	"""An active Employee linked to `user`, which is what puts them in scope.

	Written with raw SQL rather than the ORM, deliberately. This site's Employee
	carries a thicket of customisation from the Upande apps - a mandatory
	Employee Number, a "Only Security Head can modify Reference Validated"
	guard, and an after_insert Server Script that mails about salary structure
	assignments. None of it relates to what these tests exercise, and
	`flags.ignore_validate` only skips `validate` (frappe/model/document.py:1399),
	not `after_insert`.

	All `mapping.employee_scope` needs is a row it can read company, branch,
	department and grade from.
	"""
	name = frappe.db.get_value("Employee", {"user_id": user})
	if name:
		frappe.db.set_value(
			"Employee",
			name,
			{"company": company, "status": "Active", "designation": designation},
			update_modified=False,
		)
		return name

	name = f"_RA-EMP-{frappe.generate_hash(length=8)}"
	frappe.db.sql(
		"""
		insert into `tabEmployee`
			(name, creation, modified, modified_by, owner, docstatus, idx,
			 employee_name, first_name, user_id, company, status,
			 date_of_joining, date_of_birth, designation, employee_number)
		values
			(%(name)s, now(), now(), 'Administrator', 'Administrator', 0, 0,
			 %(label)s, %(label)s, %(user)s, %(company)s, 'Active',
			 '2020-01-01', '1990-01-01', %(designation)s, %(name)s)
		""",
		{
			"name": name,
			"label": user.split("@")[0],
			"user": user,
			"company": company,
			"designation": designation,
		},
	)

	return name


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
