# Copyright (c) 2026, ghost-mann and contributors
# For license information, please see license.txt

"""The audit trail: every real access change, whoever made it.

`Access Assignment Log` records what this app did. It holds 13 rows. `Version`
holds 75,768 access-relevant rows the app cannot see, so the trail worth having
is mostly of changes made outside it - which is exactly the thing worth knowing.

Derived, never stored. Nothing here writes, so the trail can never itself be
the thing that is wrong.
"""

import collections
import json

import frappe
from frappe.utils import add_days, cint, getdate, nowdate

from role_advisor import capability, dashboard

ACCESS_DOCTYPES = ("User", "Role", "Role Profile", "Module Profile", "Property Setter")

MAX_PAGE_SIZE = 500
DEFAULT_DAYS = 30
MAX_UNTARGETED_DAYS = 90
ATTRIBUTION_WINDOW_SECONDS = 2
HISTORY_FLOOR = "2025-10-08"

# Stated with every response. A trail that looks complete while being silently
# partial is worse than none.
UNCOVERED = (
	"Custom DocPerm changes are not versioned and cannot appear here.",
	f"No history exists before {HISTORY_FLOOR}.",
)

# Scalar fields on the parent doc that mean something for access. Everything
# else on User - birth_date, gender, user_image, last_active - is churn, and
# 75,226 version rows of it would bury the changes that matter.
INTEREST_FIELDS = frozenset(
	{"role_profile_name", "module_profile", "user_type", "enabled", "api_key", "api_secret"}
)

# Child table -> the key in its row payload holding the value we care about.
# Recording only that "the roles table changed" is the specific defect that
# makes the IT dashboard's version_flat useless for access auditing.
CHILD_VALUE_KEY = {"roles": "role", "role_profiles": "role_profile", "block_modules": "module"}


def _child_multisets(blob: dict) -> tuple[dict, dict]:
	"""Added and removed child rows as multisets of their meaningful value.

	Multisets rather than sets: a save can legitimately add two rows carrying
	the same value, and collapsing them would understate the change.
	"""
	out: dict[str, dict[str, collections.Counter]] = {"added": {}, "removed": {}}

	for kind in ("added", "removed"):
		for entry in blob.get(kind) or []:
			if not isinstance(entry, list) or len(entry) < 2:
				continue
			table, payload = entry[0], entry[1]
			key = CHILD_VALUE_KEY.get(table)
			if not key or not isinstance(payload, dict):
				continue
			value = payload.get(key)
			if not value:
				continue
			out[kind].setdefault(table, collections.Counter())[value] += 1

	return out["added"], out["removed"]


def _delta(data: str, ref_doctype: str) -> dict | None:
	"""One version row's `data` JSON reduced to what actually changed.

	Returns None when nothing access-relevant survives, which is the common
	case: most User versions are ordinary profile churn.
	"""
	try:
		blob = json.loads(data or "{}")
	except (ValueError, TypeError):
		return None
	if not isinstance(blob, dict):
		return None

	fields: list[tuple] = []
	profile_before = None
	profile_after = None

	for change in blob.get("changed") or []:
		if not isinstance(change, list) or not change:
			continue
		name = change[0]
		if name not in INTEREST_FIELDS:
			continue
		old = change[1] if len(change) > 1 else None
		new = change[2] if len(change) > 2 else None
		if name == "role_profile_name":
			# v15 kept the profile in a scalar field. Canonicalised here so a
			# v15 change and a v16 child-table change read identically.
			profile_before, profile_after = old, new
		else:
			fields.append((name, old, new))

	for entry in blob.get("row_changed") or []:
		if not isinstance(entry, list) or len(entry) < 4:
			continue
		table = entry[0]
		if table not in CHILD_VALUE_KEY:
			continue
		for change in entry[3] or []:
			if isinstance(change, list) and change:
				old = change[1] if len(change) > 1 else None
				new = change[2] if len(change) > 2 else None
				fields.append((f"{table}.{change[0]}", old, new))

	added, removed = _child_multisets(blob)

	def net(table: str) -> tuple[list, list]:
		gained = added.get(table, collections.Counter())
		lost = removed.get(table, collections.Counter())
		return sorted((gained - lost).elements()), sorted((lost - gained).elements())

	roles_gained, roles_lost = net("roles")
	modules_blocked, modules_unblocked = net("block_modules")
	profiles_gained, profiles_lost = net("role_profiles")

	# v16 keeps profiles in a child table. Fold it onto the same two fields the
	# v15 scalar produces, so the 439 old rows and the 52 new ones render alike.
	if profiles_lost:
		profile_before = ", ".join(profiles_lost)
	if profiles_gained:
		profile_after = ", ".join(profiles_gained)

	if not (
		fields
		or roles_gained
		or roles_lost
		or modules_blocked
		or modules_unblocked
		or profile_before
		or profile_after
	):
		return None

	return {
		"doctype": ref_doctype,
		"roles_gained": roles_gained,
		"roles_lost": roles_lost,
		"modules_blocked": modules_blocked,
		"modules_unblocked": modules_unblocked,
		"profile_before": profile_before,
		"profile_after": profile_after,
		"fields": fields,
		"updater_reference": blob.get("updater_reference"),
	}


def _is_parseable(data: str) -> bool:
	try:
		json.loads(data)
	except (ValueError, TypeError):
		return False
	return True


def _window(start: str | None, end: str | None, target: str | None) -> tuple[str, str]:
	"""The date range to scan, refusing one too wide to answer cheaply."""
	end = str(getdate(end) if end else getdate(nowdate()))
	start = str(getdate(start) if start else getdate(add_days(end, -DEFAULT_DAYS)))

	if getdate(start) > getdate(end):
		frappe.throw(f"Start date {start} is after end date {end}.")

	if not target:
		span = (getdate(end) - getdate(start)).days
		if span > MAX_UNTARGETED_DAYS:
			frappe.throw(
				f"A range of {span} days needs a target user. "
				f"Without one the range must be {MAX_UNTARGETED_DAYS} days or fewer."
			)

	return start, end


def _fetch(start, end, target, actor, doctype, limit, offset) -> tuple[list[dict], bool]:
	"""A page of version rows, newest first. One extra row answers has_more."""
	doctypes = (doctype,) if doctype in ACCESS_DOCTYPES else ACCESS_DOCTYPES

	conditions = ["v.ref_doctype in %(doctypes)s", "v.creation between %(start)s and %(end)s"]
	params = {
		"doctypes": doctypes,
		"start": f"{start} 00:00:00",
		"end": f"{end} 23:59:59",
		"limit": limit + 1,
		"offset": offset,
	}
	if target:
		conditions.append("v.docname = %(target)s")
		params["target"] = target
	if actor:
		conditions.append("v.owner = %(actor)s")
		params["actor"] = actor

	rows = frappe.db.sql(
		f"""
		select v.name, v.owner, v.ref_doctype, v.docname, v.data, v.creation,
		       u.full_name as actor_name
		from `tabVersion` v
		left join `tabUser` u on u.name = v.owner
		where {" and ".join(conditions)}
		order by v.creation desc
		limit %(limit)s offset %(offset)s
		""",
		params,
		as_dict=True,
	)

	return rows[:limit], len(rows) > limit


def _attribute(rows: list[dict]) -> list[dict]:
	"""Did this change go through Role Advisor, or around it?

	Matched on target and timestamp proximity, because nothing stamps an
	identifier onto the write. The window is deliberately tight: a bulk sweep
	touching many users inside one second could otherwise claim a concurrent
	external edit. Every caller is told the attribution is heuristic.
	"""
	if not rows:
		return rows

	targets = {row["document"] for row in rows if row.get("document")}
	logs = (
		frappe.get_all(
			"Access Assignment Log",
			filters={"target_user": ("in", list(targets))},
			fields=["name", "target_user", "trigger", "outcome", "creation"],
			limit_page_length=0,
		)
		if targets
		else []
	)

	by_target: dict[str, list[dict]] = {}
	for log in logs:
		by_target.setdefault(log["target_user"], []).append(log)

	for row in rows:
		match = None
		for log in by_target.get(row.get("document"), []):
			gap = abs((row["when"] - log["creation"]).total_seconds())
			if gap <= ATTRIBUTION_WINDOW_SECONDS:
				match = log
				break

		if match:
			row["source"] = "role_advisor"
			row["assignment_log"] = match["name"]
			row["trigger"] = match["trigger"]
			row["outcome"] = match["outcome"]
		elif row.get("updater_reference"):
			row["source"] = "system"
		else:
			row["source"] = "external"

	return rows


@frappe.whitelist()
def trail(
	target: str | None = None,
	actor: str | None = None,
	doctype: str | None = None,
	start: str | None = None,
	end: str | None = None,
	page: int = 1,
	page_size: int = 50,
) -> dict:
	"""Every real access change in the window, newest first.

	`scanned` and `surfaced` are both reported because most version rows carry
	no net change: a page of three rows out of four hundred scanned is the
	correct answer, and without both numbers it reads as a bug.
	"""
	admin = dashboard._guard()
	scoped = dashboard._scoped_users(admin)

	page = max(cint(page) or 1, 1)
	page_size = min(max(cint(page_size) or 50, 1), MAX_PAGE_SIZE)
	start, end = _window(start, end, target)

	if scoped is not None:
		if target and target not in scoped:
			frappe.throw(f"{target} is not in your scope.")
		if not scoped:
			scoped = ["\0"]

	versions, has_more = _fetch(
		start, end, target, actor, doctype, page_size, (page - 1) * page_size
	)

	rows = []
	unparsed = 0
	for version in versions:
		if scoped is not None and version.ref_doctype == "User" and version.docname not in scoped:
			continue
		delta = _delta(version.data, version.ref_doctype)
		if delta is None:
			if version.data and not _is_parseable(version.data):
				unparsed += 1
			continue
		rows.append(
			{
				**delta,
				"version": version.name,
				"when": version.creation,
				"actor": version.owner,
				"actor_name": version.actor_name,
				"document": version.docname,
			}
		)

	return {
		"rows": _attribute(rows),
		"page": page,
		"page_size": page_size,
		"has_more": has_more,
		"scanned": len(versions),
		"surfaced": len(rows),
		"unparsed": unparsed,
		"attribution": "heuristic",
		"limits": {"history_floor": HISTORY_FLOOR, "uncovered": list(UNCOVERED)},
	}


@frappe.whitelist()
def event(version: str) -> dict:
	"""Everything behind one trail row, including the events that cancelled.

	The netted view is what makes the trail readable; this is what makes it
	provable. An auditor asking "what did the database actually record" gets
	the unabridged blob.
	"""
	dashboard._guard()

	row = frappe.db.get_value(
		"Version",
		version,
		["name", "owner", "ref_doctype", "docname", "data", "creation"],
		as_dict=True,
	)
	if not row:
		frappe.throw(f"No version {version}.", frappe.DoesNotExistError)
	if row.ref_doctype not in ACCESS_DOCTYPES:
		frappe.throw(f"{row.ref_doctype} is not an access doctype.", frappe.PermissionError)

	try:
		raw = json.loads(row.data or "{}")
	except (ValueError, TypeError):
		raw = {}

	logins = (
		frappe.db.sql(
			"""
			select operation, status, ip_address, creation
			from `tabActivity Log`
			where user = %(user)s and creation between %(start)s and %(end)s
			order by creation desc limit 20
			""",
			{
				"user": row.docname,
				"start": frappe.utils.add_to_date(row.creation, hours=-12),
				"end": frappe.utils.add_to_date(row.creation, hours=12),
			},
			as_dict=True,
		)
		if row.ref_doctype == "User"
		else []
	)

	return {
		"version": row.name,
		"when": row.creation,
		"actor": row.owner,
		"doctype": row.ref_doctype,
		"document": row.docname,
		"delta": _delta(row.data, row.ref_doctype),
		"raw": raw,
		"logins": logins,
	}


@frappe.whitelist()
def summary(start: str | None = None, end: str | None = None) -> dict:
	"""Who has been changing access, and to what.

	Counts version rows rather than netted changes: this is a cheap orientation
	query, and making it exact would mean parsing every row in the window.
	"""
	dashboard._guard()
	start, end = _window(start, end, None)

	params = {
		"doctypes": ACCESS_DOCTYPES,
		"start": f"{start} 00:00:00",
		"end": f"{end} 23:59:59",
	}

	by_actor = frappe.db.sql(
		"""
		select v.owner as actor, u.full_name as actor_name, count(*) as changes
		from `tabVersion` v
		left join `tabUser` u on u.name = v.owner
		where v.ref_doctype in %(doctypes)s and v.creation between %(start)s and %(end)s
		group by v.owner, u.full_name
		order by changes desc limit 25
		""",
		params,
		as_dict=True,
	)

	by_doctype = frappe.db.sql(
		"""
		select v.ref_doctype as doctype, count(*) as changes
		from `tabVersion` v
		where v.ref_doctype in %(doctypes)s and v.creation between %(start)s and %(end)s
		group by v.ref_doctype
		order by changes desc
		""",
		params,
		as_dict=True,
	)

	return {"by_actor": by_actor, "by_doctype": by_doctype, "window": {"start": start, "end": end}}


def _current_roles(user: str) -> list[str]:
	return frappe.get_all("Has Role", filters={"parent": user, "parenttype": "User"}, pluck="role")


def _rewind(state: dict, chain: list[dict]) -> dict:
	"""Undo each delta, newest first, to arrive at the state before them all."""
	for delta in chain:
		for role in delta.get("roles_gained") or []:
			state["roles"].discard(role)
		for role in delta.get("roles_lost") or []:
			state["roles"].add(role)
		before = delta.get("profile_before")
		if before:
			state["profiles"] = [part.strip() for part in before.split(",") if part.strip()]
	return state


@frappe.whitelist()
def as_of(user: str, date: str) -> dict:
	"""What this user could do on `date`, worked back from what they hold now.

	Reconstruction, not a recording: it is only as complete as `Version` is, so
	`limits` travels with the answer and `exact` is false whenever the walk
	crossed something it could not account for. A reconstruction that looks
	authoritative while being silently partial is worse than none.
	"""
	admin = dashboard._guard()
	scoped = dashboard._scoped_users(admin)
	if scoped is not None and user not in scoped:
		frappe.throw(f"{user} is not in your scope.")

	date = str(getdate(date))
	notes = []
	exact = True

	if getdate(date) < getdate(HISTORY_FLOOR):
		notes.append(
			f"Requested {date} is before the history floor {HISTORY_FLOOR}; "
			"this is the earliest state on record, not the state on that date."
		)
		exact = False
		date = HISTORY_FLOOR

	state = {
		"roles": set(_current_roles(user)),
		"profiles": capability.get_user_role_profiles(user),
		"module_profile": frappe.db.get_value("User", user, "module_profile"),
	}

	chain = []
	page = 0
	while True:
		versions, has_more = _fetch(
			date, str(getdate(nowdate())), user, None, "User", MAX_PAGE_SIZE, page * MAX_PAGE_SIZE
		)
		for version in versions:
			delta = _delta(version.data, version.ref_doctype)
			if delta is None:
				if version.data and not _is_parseable(version.data):
					exact = False
				continue
			chain.append({**delta, "version": version.name, "when": version.creation})
		if not has_more:
			break
		page += 1

	_rewind(state, chain)

	notes.extend(UNCOVERED)
	return {
		"user": user,
		"date": date,
		"state": {
			"roles": sorted(state["roles"]),
			"profiles": state["profiles"],
			"module_profile": state["module_profile"],
		},
		"chain": chain,
		"limits": {"history_floor": HISTORY_FLOOR, "notes": notes},
		"exact": exact,
	}
