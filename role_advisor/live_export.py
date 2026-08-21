# Copyright (c) 2026, ghost-mann and contributors
# For license information, please see license.txt

"""Export every user from a remote Frappe site to CSV.

For the case where the site holding the real data is not the site this app runs
on - Kaitet's production is v15, while the app targets v16 - so `frappe.get_all`
against the local bench would report a stale copy.

Credentials come from the environment, never from code or a committed file:

    export KAITET_HOST=https://kaitet-group.upande.com
    export KAITET_TOKEN=api_key:api_secret
    bench --site <site> execute role_advisor.live_export.run

The transform is separated from the fetch so it can be tested without a network.
Works against v15 and v16: `role_profile_name` is read directly, which is the
real field on v15 and a read-only mirror of `role_profiles[0]` on v16.
"""

import collections
import csv
import json
import os
import urllib.parse
import urllib.request

COLUMNS = (
	"user",
	"full_name",
	"enabled",
	"user_type",
	"role_profile_name",
	"module_profile",
	"employee",
	"employee_status",
	"company",
	"branch",
	"department",
	"designation",
	"grade",
	"role_count",
	"roles_outside_profile",
	"user_permissions",
	"permitted_companies",
	"is_system_manager",
	"is_user_manager",
	"last_login",
	"last_active",
	"creation",
)


def _credentials() -> tuple[str, str]:
	host = os.environ.get("KAITET_HOST")
	token = os.environ.get("KAITET_TOKEN")
	if not host or not token:
		raise RuntimeError(
			"Set KAITET_HOST and KAITET_TOKEN in the environment. "
			"Credentials must never be committed."
		)

	return host.rstrip("/"), token


def fetch(doctype: str, fields: list[str], filters=None, parent=None) -> list[dict]:
	"""Read a doctype from the remote site via the REST API."""
	host, token = _credentials()

	params = {
		"doctype": doctype,
		"fields": json.dumps(fields),
		"limit_page_length": 0,
	}
	if filters:
		params["filters"] = json.dumps(filters)
	# Child tables are only readable when the parent doctype is named.
	if parent:
		params["parent"] = parent

	url = f"{host}/api/method/frappe.client.get_list?{urllib.parse.urlencode(params)}"
	request = urllib.request.Request(url, headers={"Authorization": f"token {token}"})
	with urllib.request.urlopen(request, timeout=180) as response:
		return json.loads(response.read())["message"]


def build_rows(
	users: list[dict],
	employees: list[dict],
	user_roles: list[dict],
	profile_roles: list[dict],
	permissions: list[dict],
) -> list[dict]:
	"""Join the five datasets into one row per user. Pure - no network."""
	# An Active employee wins; otherwise fall back to any linked record, so a
	# leaver still supplies company and designation rather than showing blank.
	active, any_emp = {}, {}
	for employee in employees:
		uid = employee.get("user_id")
		if not uid:
			continue
		any_emp.setdefault(uid, employee)
		if employee.get("status") == "Active":
			active.setdefault(uid, employee)

	held = collections.defaultdict(set)
	for row in user_roles:
		held[row["parent"]].add(row["role"])

	by_profile = collections.defaultdict(set)
	for row in profile_roles:
		by_profile[row["parent"]].add(row["role"])

	perm_count = collections.Counter()
	companies = collections.defaultdict(set)
	for row in permissions:
		perm_count[row["user"]] += 1
		if row.get("allow") == "Company":
			companies[row["user"]].add(row["for_value"])

	rows = []
	for user in users:
		name = user["name"]
		employee = active.get(name) or any_emp.get(name) or {}
		roles = held.get(name, set())
		profile = (user.get("role_profile_name") or "").strip()
		# Roles held outside the profile are exactly what v16 prunes on save.
		outside = roles - by_profile.get(profile, set()) if profile else set()

		rows.append(
			{
				"user": name,
				"full_name": user.get("full_name") or "",
				"enabled": user.get("enabled") or 0,
				"user_type": user.get("user_type") or "",
				"role_profile_name": profile,
				"module_profile": user.get("module_profile") or "",
				"employee": employee.get("name", ""),
				"employee_status": employee.get("status", ""),
				"company": employee.get("company", ""),
				"branch": employee.get("branch", ""),
				"department": employee.get("department", ""),
				"designation": employee.get("designation", ""),
				"grade": employee.get("grade", ""),
				"role_count": len(roles),
				"roles_outside_profile": ", ".join(sorted(outside)),
				"user_permissions": perm_count.get(name, 0),
				"permitted_companies": ", ".join(sorted(companies.get(name, ()))),
				"is_system_manager": int("System Manager" in roles),
				"is_user_manager": int("User Manager" in roles),
				"last_login": user.get("last_login") or "",
				"last_active": user.get("last_active") or "",
				"creation": user.get("creation") or "",
			}
		)

	# Enabled first, then by company, then by name - the order a reviewer wants.
	rows.sort(key=lambda row: (not row["enabled"], row["company"] or "~", row["full_name"]))

	return rows


def collect() -> list[dict]:
	"""Fetch everything from the remote site and join it."""
	return build_rows(
		fetch(
			"User",
			[
				"name", "full_name", "enabled", "user_type", "last_active",
				"last_login", "creation", "role_profile_name", "module_profile",
			],
		),
		fetch(
			"Employee",
			["name", "user_id", "company", "branch", "department", "designation", "grade", "status"],
			filters=[["user_id", "!=", ""]],
		),
		fetch("Has Role", ["parent", "role"], filters=[["parenttype", "=", "User"]], parent="User"),
		fetch(
			"Has Role",
			["parent", "role"],
			filters=[["parenttype", "=", "Role Profile"]],
			parent="Role Profile",
		),
		fetch("User Permission", ["user", "allow", "for_value"]),
	)


def write_csv(rows: list[dict], path: str) -> str:
	with open(path, "w", newline="", encoding="utf-8") as handle:
		writer = csv.DictWriter(handle, fieldnames=COLUMNS)
		writer.writeheader()
		writer.writerows(rows)

	return path


def run(path: str | None = None) -> str:
	"""Fetch and write. Defaults outside the repository - this file is PII."""
	rows = collect()
	path = path or os.path.join(os.path.expanduser("~"), "kaitet-live-users.csv")
	write_csv(rows, path)

	enabled = sum(1 for row in rows if row["enabled"])
	print(f"{len(rows)} users ({enabled} enabled, {len(rows) - enabled} disabled) -> {path}")

	return path
