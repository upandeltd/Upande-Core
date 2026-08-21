# Copyright (c) 2026, ghost-mann and contributors
# For license information, please see license.txt

"""Read-only aggregates for the access dashboard.

Every number here is counted from the site, never estimated. Where a trend
cannot be derived from stored data it is not shown - a fabricated line on an
access dashboard is worse than a missing one.

Visible to System Manager and to the delegate role. A delegate with an enabled
`Delegated User Admin` record sees their own scope; a System Manager sees
everything.
"""

from collections import Counter, defaultdict

import frappe
from frappe.utils import cint

from role_advisor import capability, delegation, privilege, settings

SEVERITY_HIGH = "high"
SEVERITY_MODERATE = "moderate"
SEVERITY_LOW = "low"
SEVERITY_CLEAR = "clear"


def _guard():
	"""Anyone who may administer access may read the dashboard.

	Returns the caller's delegation record, or None if they should see
	everything. A System Manager sees the whole site even when they also hold a
	delegate record - the record bounds what they may *grant*, not what they may
	*see*, and silently shrinking their dashboard would misreport the estate.
	"""
	frappe.only_for(["System Manager", settings.delegate_role()])

	if "System Manager" in frappe.get_roles():
		return None

	return delegation.current_admin()


def _scoped_users(admin) -> list[str] | None:
	"""The user names in scope, or None for unrestricted."""
	if not admin:
		return None

	companies = delegation.scope_companies(admin)
	if not companies:
		return []

	return frappe.db.sql_list(
		"""
		select distinct e.user_id from `tabEmployee` e
		join `tabUser` u on u.name = e.user_id
		where e.status = 'Active' and e.company in %(companies)s
		  and e.user_id is not null and e.user_id != ''
		""",
		{"companies": tuple(companies)},
	)


@frappe.whitelist()
def summary() -> dict:
	"""Headline counts for the overview."""
	admin = _guard()
	scope = _scoped_users(admin)

	where = "1=1" if scope is None else "u.name in %(scope)s"
	params = {} if scope is None else {"scope": tuple(scope or ["__none__"])}

	totals = frappe.db.sql(
		f"""
		select count(*) as users,
		       sum(u.enabled = 1) as enabled,
		       sum(u.user_type = 'System User') as system_users,
		       sum(u.enabled = 1 and (u.module_profile is null or u.module_profile = '')) as no_module_profile
		from `tabUser` u where {where}
		""",
		params,
		as_dict=True,
	)[0]

	profiled = cint(
		frappe.db.sql(
			f"""
			select count(distinct p.parent) from `tabUser Role Profile` p
			join `tabUser` u on u.name = p.parent
			where p.parenttype = 'User' and u.enabled = 1 and {where}
			""",
			params,
		)[0][0]
	)

	enabled = cint(totals["enabled"])
	index = capability.build_capability_index()
	privileged = [p for p in index if privilege.is_privileged(p)]

	return {
		"users": cint(totals["users"]),
		"enabled": enabled,
		"system_users": cint(totals["system_users"]),
		"profiled": profiled,
		"gap": max(enabled - profiled, 0),
		"coverage": round(profiled / enabled * 100, 1) if enabled else 0.0,
		"profiles": len(index),
		"privileged_profiles": len(privileged),
		"roles": frappe.db.count("Role"),
		"modules": frappe.db.count("Module Def"),
		"no_module_profile": cint(totals["no_module_profile"]),
		"map_rows": frappe.db.count("Designation Access Map"),
		"map_active": frappe.db.count("Designation Access Map", {"is_active": 1}),
		"delegates": frappe.db.count("Delegated User Admin", {"enabled": 1}),
		"assignments": frappe.db.count("Access Assignment Log"),
		"scoped": scope is not None,
		"scope_companies": delegation.scope_companies(admin) if admin else [],
	}


@frappe.whitelist()
def module_exposure() -> list[dict]:
	"""One row per module: how many users can reach it, and how exposed it is.

	Drives the module grid. Severity is by share of the user base, not raw count,
	so a small site and a large one read the same way.
	"""
	_guard()
	index = capability.build_capability_index()

	module_of = {
		row["name"]: row["module"]
		for row in frappe.get_all("DocType", fields=["name", "module"])
		if row["module"]
	}

	holders = defaultdict(set)
	for row in frappe.get_all(
		"User Role Profile", filters={"parenttype": "User"}, fields=["parent", "role_profile"]
	):
		holders[row["role_profile"]].add(row["parent"])

	enabled = set(frappe.get_all("User", filters={"enabled": 1}, pluck="name"))
	total = len(enabled) or 1

	per_module = defaultdict(lambda: {"users": set(), "profiles": set(), "doctypes": set()})
	for profile, caps in index.items():
		for doctype in caps:
			module = module_of.get(doctype)
			if not module:
				continue
			bucket = per_module[module]
			bucket["profiles"].add(profile)
			bucket["doctypes"].add(doctype)
			bucket["users"] |= holders.get(profile, set()) & enabled

	doctypes_in_module = Counter(module_of.values())

	rows = []
	for module, bucket in per_module.items():
		share = len(bucket["users"]) / total
		if share >= 0.75:
			severity = SEVERITY_HIGH
		elif share >= 0.4:
			severity = SEVERITY_MODERATE
		elif share > 0:
			severity = SEVERITY_LOW
		else:
			severity = SEVERITY_CLEAR

		rows.append(
			{
				"module": module,
				"users": len(bucket["users"]),
				"profiles": len(bucket["profiles"]),
				"doctypes_granted": len(bucket["doctypes"]),
				"doctypes_total": doctypes_in_module.get(module, 0),
				"share": round(share * 100, 1),
				"severity": severity,
			}
		)

	# Untouched modules still matter - they are the ones nobody can reach.
	for module, count in doctypes_in_module.items():
		if module not in per_module:
			rows.append(
				{
					"module": module,
					"users": 0,
					"profiles": 0,
					"doctypes_granted": 0,
					"doctypes_total": count,
					"share": 0.0,
					"severity": SEVERITY_CLEAR,
				}
			)

	return sorted(rows, key=lambda row: -row["users"])


@frappe.whitelist()
def profile_leaderboard(limit: int = 12) -> list[dict]:
	"""Profiles by headcount, with what each actually grants."""
	_guard()
	index = capability.build_capability_index()

	users = Counter()
	for row in frappe.get_all(
		"User Role Profile", filters={"parenttype": "User"}, fields=["role_profile"]
	):
		users[row["role_profile"]] += 1

	roles = Counter()
	for row in frappe.get_all(
		"Has Role", filters={"parenttype": "Role Profile"}, fields=["parent"]
	):
		roles[row["parent"]] += 1

	rows = []
	for profile, caps in index.items():
		grants = privilege.privileged_grants(profile)
		if privilege.UNKNOWN_PROFILE in grants:
			grants = {}
		rows.append(
			{
				"profile": profile,
				"users": users.get(profile, 0),
				"roles": roles.get(profile, 0),
				"doctypes": len(caps),
				"grants": capability.total_perm_count(caps),
				"privileged": bool(grants),
				"empty": not caps,
			}
		)

	return sorted(rows, key=lambda row: (-row["users"], -row["grants"]))[: cint(limit) or 12]


@frappe.whitelist()
def designation_coverage(limit: int = 14) -> list[dict]:
	"""Per designation: how many login users hold a profile, and how many do not."""
	_guard()

	rows = frappe.db.sql(
		"""
		select e.designation as designation, e.company as company,
		       count(distinct u.name) as users,
		       count(distinct case when p.parent is not null then u.name end) as profiled
		from `tabUser` u
		join `tabEmployee` e on e.user_id = u.name and e.status = 'Active'
		left join `tabUser Role Profile` p on p.parent = u.name and p.parenttype = 'User'
		where u.enabled = 1 and ifnull(e.designation, '') != ''
		group by e.designation, e.company
		order by (count(distinct u.name) - count(distinct case when p.parent is not null then u.name end)) desc,
		         count(distinct u.name) desc
		""",
		as_dict=True,
	)

	for row in rows:
		row["gap"] = cint(row["users"]) - cint(row["profiled"])
		row["coverage"] = (
			round(cint(row["profiled"]) / cint(row["users"]) * 100) if row["users"] else 0
		)

	return rows[: cint(limit) or 14]


@frappe.whitelist()
def user_table() -> list[dict]:
	"""One row per user for the Users view.

	Includes disabled accounts, with the flag: a disabled user still holds every
	role and profile, and re-enabling silently restores them.
	"""
	admin = _guard()
	scope = _scoped_users(admin)

	where = "1=1" if scope is None else "u.name in %(scope)s"
	params = {} if scope is None else {"scope": tuple(scope or ["__none__"])}

	rows = frappe.db.sql(
		f"""
		select u.name as user, u.full_name as full_name, u.enabled as enabled,
		       u.user_type as user_type, nullif(u.module_profile, '') as module_profile,
		       e.company as company, e.designation as designation, e.branch as branch,
		       (select group_concat(p.role_profile separator ', ')
		        from `tabUser Role Profile` p
		        where p.parent = u.name and p.parenttype = 'User') as profile,
		       (select count(*) from `tabHas Role` r
		        where r.parent = u.name and r.parenttype = 'User') as roles
		from `tabUser` u
		left join `tabEmployee` e on e.user_id = u.name and e.status = 'Active'
		where {where}
		order by u.enabled desc, e.company, u.full_name
		""",
		params,
		as_dict=True,
	)

	privileged = defaultdict(set)
	for row in frappe.get_all(
		"Has Role",
		filters={"parenttype": "User", "role": ("in", ["System Manager", "User Manager"])},
		fields=["parent", "role"],
	):
		privileged[row["parent"]].add(row["role"])

	for row in rows:
		held = privileged.get(row["user"], set())
		row["is_system_manager"] = int("System Manager" in held)
		row["is_user_manager"] = int("User Manager" in held)

	return rows


@frappe.whitelist()
def recent_assignments(limit: int = 12) -> list[dict]:
	"""The audit trail, newest first."""
	_guard()

	return frappe.get_all(
		"Access Assignment Log",
		fields=[
			"name", "actor", "target_user", "trigger", "outcome",
			"profiles_before", "profiles_after", "roles_gained", "roles_lost", "creation",
		],
		order_by="creation desc",
		limit=cint(limit) or 12,
	)


@frappe.whitelist()
def findings() -> list[dict]:
	"""The things a human should act on, worst first. Counted, never guessed."""
	_guard()
	index = capability.build_capability_index()

	users = Counter()
	for row in frappe.get_all(
		"User Role Profile", filters={"parenttype": "User"}, fields=["role_profile"]
	):
		users[row["role_profile"]] += 1

	out = []

	empty_held = [
		(p, users[p]) for p, caps in index.items() if not caps and users.get(p)
	]
	for profile, count in sorted(empty_held, key=lambda pair: -pair[1]):
		out.append(
			{
				"severity": SEVERITY_HIGH,
				"title": f"{profile} grants nothing",
				"detail": f"{count} users hold a profile that permits no action at all.",
				"count": count,
			}
		)

	# Profiles with identical grant sets: different names, same access.
	signatures = defaultdict(list)
	for profile, caps in index.items():
		if caps:
			signatures[
				frozenset((dt, pm) for dt, perms in caps.items() for pm in perms)
			].append(profile)
	for members in signatures.values():
		if len(members) > 1:
			held = sum(users.get(m, 0) for m in members)
			out.append(
				{
					"severity": SEVERITY_MODERATE,
					"title": f"{len(members)} profiles are identical",
					"detail": ", ".join(sorted(members)) + f" — {held} users between them.",
					"count": held,
				}
			)

	privileged = [p for p in index if privilege.is_privileged(p)]
	if privileged:
		out.append(
			{
				"severity": SEVERITY_MODERATE,
				"title": f"{len(privileged)} profiles cannot be delegated",
				"detail": ", ".join(sorted(privileged))
				+ " — each grants write on permission-bearing doctypes.",
				"count": len(privileged),
			}
		)

	orphans = frappe.db.sql(
		"""
		select count(*) from `tabUser` u
		where u.enabled = 1 and u.user_type = 'System User'
		  and not exists (select 1 from `tabEmployee` e where e.user_id = u.name and e.status = 'Active')
		"""
	)[0][0]
	if orphans:
		out.append(
			{
				"severity": SEVERITY_LOW,
				"title": f"{orphans} users have no employee record",
				"detail": "They have no company, so no delegated administrator can reach them.",
				"count": cint(orphans),
			}
		)

	inactive_map = frappe.db.count("Designation Access Map", {"is_active": 0})
	if inactive_map:
		out.append(
			{
				"severity": SEVERITY_LOW,
				"title": f"{inactive_map} map rows await a decision",
				"detail": "Seeded from observed assignments and left inactive until reviewed.",
				"count": inactive_map,
			}
		)

	order = {SEVERITY_HIGH: 0, SEVERITY_MODERATE: 1, SEVERITY_LOW: 2}

	return sorted(out, key=lambda row: (order[row["severity"]], -row["count"]))
