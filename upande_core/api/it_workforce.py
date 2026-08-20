# Copyright (c) 2026, Upande and contributors
# For license information, please see license.txt
#
# IT — Workforce reconciliation API
# Cross-checks HR (Employee) against IT (User accounts) to surface access-
# governance gaps: offboarded employees who still hold enabled login accounts,
# active employees whose accounts are disabled, and enabled accounts with no
# linked active employee. All data is fetched in two bulk queries (no N+1).

import frappe

INACTIVE_STATUSES = ["Inactive", "Suspended", "Left"]
SYSTEM_ACCOUNTS = {"Administrator", "Guest"}


@frappe.whitelist()
def get_reconciliation():
	"""Return the full active-accounts vs inactive-employees reconciliation."""
	frappe.only_for(["System Manager", "IT User Admin"])

	employees = frappe.get_all(
		"Employee",
		fields=[
			"name", "employee_name", "status", "user_id", "company",
			"department", "designation", "relieving_date", "date_of_joining",
		],
		limit_page_length=0,
	)
	users = frappe.get_all(
		"User",
		filters={"user_type": "System User"},
		fields=["name", "enabled", "full_name", "last_login", "last_active"],
		limit_page_length=0,
	)
	user_map = {u["name"]: u for u in users}

	active_emps = [e for e in employees if e.get("status") == "Active"]
	inactive_emps = [e for e in employees if e.get("status") in INACTIVE_STATUSES]

	real_users = [u for u in users if u["name"] not in SYSTEM_ACCOUNTS]
	enabled_accounts = [u for u in real_users if u.get("enabled")]

	all_linked = {e.get("user_id") for e in employees if e.get("user_id")}
	active_linked = {e.get("user_id") for e in active_emps if e.get("user_id")}

	# RISK — inactive/left employee whose account is still enabled.
	risk = []
	for e in inactive_emps:
		uid = e.get("user_id")
		u = user_map.get(uid)
		if uid and u and u.get("enabled"):
			risk.append({
				"employee": e["name"],
				"employee_name": e.get("employee_name"),
				"status": e.get("status"),
				"user": uid,
				"department": e.get("department"),
				"relieving_date": str(e.get("relieving_date") or ""),
				"last_login": str(u.get("last_login") or ""),
			})

	# BLOCKED — active employee whose account is disabled (cannot work).
	blocked = []
	for e in active_emps:
		uid = e.get("user_id")
		u = user_map.get(uid)
		if uid and u and not u.get("enabled"):
			blocked.append({
				"employee": e["name"],
				"employee_name": e.get("employee_name"),
				"user": uid,
				"department": e.get("department"),
			})

	# ORPHAN — enabled account not tied to any active employee.
	orphan = []
	for u in enabled_accounts:
		if u["name"] not in active_linked:
			orphan.append({
				"user": u["name"],
				"full_name": u.get("full_name"),
				"last_login": str(u.get("last_login") or ""),
				"linked_to_employee": u["name"] in all_linked,
			})

	by_status = {}
	for e in employees:
		s = e.get("status") or "Unknown"
		by_status[s] = by_status.get(s, 0) + 1

	return {
		"totals": {
			"employees": len(employees),
			"active_employees": len(active_emps),
			"inactive_employees": len(inactive_emps),
			"enabled_accounts": len(enabled_accounts),
			"risk_count": len(risk),
			"blocked_count": len(blocked),
			"orphan_count": len(orphan),
		},
		"by_status": [{"status": k, "count": v} for k, v in sorted(by_status.items())],
		"risk": risk,
		"blocked": blocked,
		"orphan": orphan,
	}
