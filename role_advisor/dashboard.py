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
		"open_requests": frappe.db.count(
			"Access Request", {"status": ("in", ["Open", "Resolved"])}
		),
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


# ---------------------------------------------------------------------------
# Drill-in detail. Everything the desk form would have shown, so the dashboard
# does not have to hand off to it.
# ---------------------------------------------------------------------------


@frappe.whitelist()
def user_detail(user: str) -> dict:
	"""Everything about one user's access, in one call."""
	admin = _guard()
	if admin:
		delegation.assert_can_manage(admin, user)

	doc = frappe.db.get_value(
		"User",
		user,
		["name", "full_name", "enabled", "user_type", "module_profile", "last_active", "last_login"],
		as_dict=True,
	)
	if not doc:
		frappe.throw(frappe._("{0} not found").format(user), frappe.DoesNotExistError)

	employee = frappe.db.get_value(
		"Employee",
		{"user_id": user, "status": "Active"},
		["name", "company", "branch", "department", "designation", "grade"],
		as_dict=True,
	)

	profiles = capability.get_user_role_profiles(user)
	index = capability.build_capability_index()
	granted: dict[str, set[str]] = {}
	for profile in profiles:
		for doctype, perms in index.get(profile, {}).items():
			granted.setdefault(doctype, set()).update(perms)

	profile_roles = set()
	if profiles:
		profile_roles = set(
			frappe.get_all(
				"Has Role",
				filters={"parent": ("in", profiles), "parenttype": "Role Profile"},
				pluck="role",
			)
		)
	held = set(
		frappe.get_all("Has Role", filters={"parent": user, "parenttype": "User"}, pluck="role")
	)

	return {
		"user": doc,
		"employee": employee,
		"profiles": profiles,
		"roles": sorted(held),
		# Roles outside every profile are what v16 prunes on the next save.
		"roles_outside_profile": sorted(held - profile_roles) if profiles else [],
		"doctypes": len(granted),
		"grants": capability.total_perm_count(granted),
		"top_grants": sorted(
			({"doctype": dt, "rights": sorted(p)} for dt, p in granted.items()),
			key=lambda row: (-len(row["rights"]), row["doctype"]),
		)[:20],
		"permissions": frappe.get_all(
			"User Permission", filters={"user": user}, fields=["allow", "for_value"], limit=50
		),
		"history": frappe.get_all(
			"Access Assignment Log",
			filters={"target_user": user},
			fields=["name", "actor", "trigger", "outcome", "profiles_before", "profiles_after", "creation"],
			order_by="creation desc",
			limit=10,
		),
	}


@frappe.whitelist()
def profile_detail(profile: str) -> dict:
	"""What a profile grants, who holds it, and what it duplicates."""
	_guard()
	index = capability.build_capability_index()
	if profile not in index:
		frappe.throw(frappe._("{0} not found").format(profile), frappe.DoesNotExistError)

	granted = index[profile]
	signature = frozenset((dt, pm) for dt, perms in granted.items() for pm in perms)

	duplicates, supersets = [], []
	for other, caps in index.items():
		if other == profile:
			continue
		other_sig = frozenset((dt, pm) for dt, perms in caps.items() for pm in perms)
		if other_sig and other_sig == signature:
			duplicates.append(other)
		elif signature and signature < other_sig:
			supersets.append((len(other_sig), other))

	grants = privilege.privileged_grants(profile)
	if privilege.UNKNOWN_PROFILE in grants:
		grants = {}

	module_of = {
		row["name"]: row["module"]
		for row in frappe.get_all("DocType", fields=["name", "module"])
	}
	by_module = Counter(module_of.get(dt) for dt in granted if module_of.get(dt))

	return {
		"profile": profile,
		"roles": sorted(
			frappe.get_all(
				"Has Role", filters={"parent": profile, "parenttype": "Role Profile"}, pluck="role"
			)
		),
		"holders": frappe.db.sql(
			"""
			select u.name as user, u.full_name as full_name, u.enabled as enabled,
			       e.company as company, e.designation as designation
			from `tabUser Role Profile` p
			join `tabUser` u on u.name = p.parent
			left join `tabEmployee` e on e.user_id = u.name and e.status = 'Active'
			where p.parenttype = 'User' and p.role_profile = %(profile)s
			order by u.enabled desc, u.full_name
			""",
			{"profile": profile},
			as_dict=True,
		),
		"doctypes": len(granted),
		"grants": capability.total_perm_count(granted),
		"privileged": bool(grants),
		"privileged_grants": privilege.describe(grants) if grants else "",
		"duplicate_of": sorted(duplicates),
		"subset_of": min(supersets)[1] if supersets else None,
		"modules": [{"module": m, "doctypes": n} for m, n in by_module.most_common()],
		"matrix": sorted(
			({"doctype": dt, "module": module_of.get(dt, ""), "rights": sorted(p)} for dt, p in granted.items()),
			key=lambda row: (row["module"], row["doctype"]),
		),
	}


@frappe.whitelist()
def module_detail(module: str) -> dict:
	"""Which profiles reach a module, and who holds them."""
	_guard()
	index = capability.build_capability_index()
	doctypes = set(frappe.get_all("DocType", filters={"module": module}, pluck="name"))

	holders = defaultdict(set)
	for row in frappe.get_all(
		"User Role Profile", filters={"parenttype": "User"}, fields=["parent", "role_profile"]
	):
		holders[row["role_profile"]].add(row["parent"])

	profiles, users = [], set()
	for profile, caps in index.items():
		touched = doctypes & set(caps)
		if not touched:
			continue
		people = holders.get(profile, set())
		users |= people
		profiles.append(
			{"profile": profile, "doctypes": len(touched), "users": len(people)}
		)

	return {
		"module": module,
		"doctypes_total": len(doctypes),
		"users": len(users),
		"profiles": sorted(profiles, key=lambda row: (-row["users"], -row["doctypes"])),
	}


@frappe.whitelist()
def log_detail(name: str) -> dict:
	"""One audit row in full."""
	_guard()

	return frappe.db.get_value(
		"Access Assignment Log",
		name,
		[
			"name", "actor", "target_user", "trigger", "outcome", "creation",
			"profiles_before", "profiles_after", "module_profile_before",
			"module_profile_after", "roles_gained", "roles_lost", "decision_notes",
		],
		as_dict=True,
	)


# ---------------------------------------------------------------------------
# Designation Access Map, editable in place.
# ---------------------------------------------------------------------------


@frappe.whitelist()
def map_list() -> list[dict]:
	_guard()

	rows = frappe.get_all(
		"Designation Access Map",
		fields=[
			"name", "designation", "for_company", "for_branch", "role_profile",
			"module_profile", "is_active", "confidence", "source", "evidence",
		],
		limit_page_length=0,
	)
	order = {"High": 0, "Medium": 1, "Low": 2, "None": 3}

	return sorted(
		rows, key=lambda row: (row["is_active"], order.get(row["confidence"], 9), row["designation"])
	)


@frappe.whitelist()
def map_update(name: str, field: str, value=None) -> dict:
	"""Activate, deactivate or repoint one map row.

	System-Manager-only, and confined to three fields - the dashboard must not
	become a general-purpose document editor with no validation.
	"""
	frappe.only_for("System Manager")

	allowed = {"is_active", "role_profile", "module_profile"}
	if field not in allowed:
		frappe.throw(frappe._("{0} cannot be edited here.").format(field))

	doc = frappe.get_doc("Designation Access Map", name)
	if field == "is_active":
		doc.is_active = cint(value)
	else:
		doc.set(field, value or None)
	doc.save(ignore_permissions=True)
	frappe.db.commit()

	return {"name": doc.name, "field": field, "value": doc.get(field)}


@frappe.whitelist()
def profile_options() -> list[dict]:
	"""Every profile, flagged so the map editor can warn before it is chosen."""
	_guard()
	index = capability.build_capability_index()

	return sorted(
		(
			{
				"profile": profile,
				"grants": capability.total_perm_count(caps),
				"privileged": privilege.is_privileged(profile),
			}
			for profile, caps in index.items()
		),
		key=lambda row: row["profile"],
	)


# ---------------------------------------------------------------------------
# Reports and the sweep, in place of their desk equivalents.
# ---------------------------------------------------------------------------

REPORTS = (
	"Designation Gap",
	"Module Exposure",
	"Role Drift",
	"System Manager Audit",
	"Role Profile Overgrant",
)


@frappe.whitelist()
def report(name: str) -> dict:
	"""Run one of this app's reports and return columns and rows."""
	_guard()
	if name not in REPORTS:
		frappe.throw(frappe._("{0} is not a Role Advisor report.").format(name))

	from frappe.desk.query_report import run

	result = run(report_name=name, ignore_prepared_report=True)

	return {
		"name": name,
		"columns": result.get("columns") or [],
		"rows": result.get("result") or [],
	}


@frappe.whitelist()
def sweep_preview() -> dict:
	"""What the bulk sweep would do. Writes nothing."""
	frappe.only_for("System Manager")
	from role_advisor import sweep

	rows = sweep.dry_run()
	ready = [row for row in rows if not row["blocked_reason"]]

	return {
		"total": len(rows),
		"ready": ready,
		"blocked": [row for row in rows if row["blocked_reason"]],
		"reasons": dict(
			Counter(
				"no employee record"
				if row["blocked_reason"] and "No active Employee" in row["blocked_reason"]
				else "map row not active"
				if row["blocked_reason"] and "not active" in row["blocked_reason"]
				else "no map row"
				for row in rows
				if row["blocked_reason"]
			)
		),
	}


@frappe.whitelist()
def sweep_apply(users=None) -> dict:
	"""Apply the sweep to the named users. System-Manager-only."""
	frappe.only_for("System Manager")
	from role_advisor import sweep

	if isinstance(users, str):
		users = frappe.parse_json(users)
	if not users:
		frappe.throw(frappe._("Select at least one user."))

	result = sweep.apply(users=list(users))

	return {k: v for k, v in result.items() if k != "logs"} | {"logs": len(result["logs"])}


# ---------------------------------------------------------------------------
# Delegates and settings.
# ---------------------------------------------------------------------------


@frappe.whitelist()
def delegate_list() -> list[dict]:
	_guard()

	rows = frappe.get_all(
		"Delegated User Admin",
		fields=["name", "user", "enabled", "can_create_users", "can_disable_users"],
		limit_page_length=0,
	)
	for row in rows:
		doc = frappe.get_doc("Delegated User Admin", row["name"])
		row["companies"] = [c.company for c in doc.companies]
		row["branches"] = [b.branch for b in doc.branches]
		row["profiles"] = [p.role_profile for p in doc.allowed_role_profiles]
		row["has_role"] = int(
			bool(
				frappe.db.exists(
					"Has Role",
					{"parent": row["user"], "parenttype": "User", "role": settings.delegate_role()},
				)
			)
		)

	return rows


@frappe.whitelist()
def delegate_save(user: str, companies=None, profiles=None, enabled=1) -> dict:
	"""Create or update a delegate, and grant the delegate role if missing.

	The record alone grants nothing - a delegate must also hold the delegate
	role - so saving one here does both, rather than leaving a record that
	silently does not work.
	"""
	frappe.only_for("System Manager")

	if isinstance(companies, str):
		companies = frappe.parse_json(companies)
	if isinstance(profiles, str):
		profiles = frappe.parse_json(profiles)

	doc = (
		frappe.get_doc("Delegated User Admin", user)
		if frappe.db.exists("Delegated User Admin", user)
		else frappe.new_doc("Delegated User Admin")
	)
	doc.user = user
	doc.enabled = cint(enabled)
	doc.set("companies", [{"company": c} for c in (companies or [])])
	doc.set("allowed_role_profiles", [{"role_profile": p} for p in (profiles or [])])
	doc.save(ignore_permissions=True)

	role = settings.delegate_role()
	if not frappe.db.exists(
		"Has Role", {"parent": user, "parenttype": "User", "role": role}
	):
		target = frappe.get_doc("User", user)
		target.append("roles", {"role": role})
		target.save(ignore_permissions=True)

	frappe.db.commit()
	delegation.clear_cache()

	return {"user": doc.user, "enabled": doc.enabled, "granted_role": role}


@frappe.whitelist()
def delegate_toggle(user: str, enabled) -> dict:
	frappe.only_for("System Manager")

	doc = frappe.get_doc("Delegated User Admin", user)
	doc.enabled = cint(enabled)
	doc.save(ignore_permissions=True)
	frappe.db.commit()
	delegation.clear_cache()

	return {"user": user, "enabled": doc.enabled}


@frappe.whitelist()
def settings_read() -> dict:
	_guard()

	return {
		"seed_mode": settings.seed_mode(),
		"tie_break_rule": settings.tie_break_rule(),
		"min_peers_high_confidence": settings.min_peers_high_confidence(),
		"scope_dimensions": settings.scope_dimensions(),
		"module_profile_strategy": settings.module_profile_strategy(),
		"naming_pattern": settings.naming_pattern(),
		"delegate_role": settings.delegate_role(),
		"allow_multiple_profiles": settings.allow_multiple_profiles(),
		"require_employee_link": settings.require_employee_link(),
		"privileged_doctypes": settings.privileged_doctypes(),
	}


@frappe.whitelist()
def settings_write(values) -> dict:
	"""Save the policy fields the dashboard exposes. System-Manager-only."""
	frappe.only_for("System Manager")

	if isinstance(values, str):
		values = frappe.parse_json(values)

	editable = {
		"seed_mode",
		"tie_break_rule",
		"min_peers_high_confidence",
		"module_profile_strategy",
		"naming_pattern",
		"allow_multiple_profiles",
		"require_employee_link",
		"use_company",
		"use_branch",
		"use_department",
		"use_grade",
	}

	doc = frappe.get_single("User Access Settings")
	for key, value in (values or {}).items():
		if key in editable:
			doc.set(key, value)
	doc.save(ignore_permissions=True)
	frappe.db.commit()
	frappe.clear_document_cache("User Access Settings")

	return settings_read()
