# Copyright (c) 2026, ghost-mann and contributors
# For license information, please see license.txt

"""Anomalies and discrepancies in how access is actually assigned.

An anomaly is a fact about this site that a human should look at. Every one is
counted from stored data - there is no scoring model here and no heuristic that
invents a number. Where a check needs a threshold the threshold is named, in
one place, at the top of the file.

The distinction the checks are built around:

  anomaly     - the shape of the grant is wrong on its own terms. A profile
                that permits nothing. A profile no-one holds. A disabled
                account that still carries access.

  discrepancy - the grant disagrees with something else that is also true.
                Two people with the same job in the same company holding
                different access. A user whose roles exceed the profiles they
                hold. A held profile that contradicts the designation map.

Discrepancies are the expensive ones to find by hand and the ones that actually
bite, so they are ranked above anomalies of equal severity.
"""

from collections import Counter, defaultdict

import frappe
from frappe import _
from frappe.utils import get_datetime, now_datetime

from upande_core import capability, delegation, privilege, settings

SEVERITY_HIGH = "high"
SEVERITY_MODERATE = "moderate"
SEVERITY_LOW = "low"

_ORDER = {SEVERITY_HIGH: 0, SEVERITY_MODERATE: 1, SEVERITY_LOW: 2}

# --- Named thresholds ------------------------------------------------------
#
# A group smaller than this cannot establish a norm, so a disagreement inside
# it is not evidence of anything. Two people doing the same job differently is
# a coin toss; three with one outlier is a pattern.
MIN_GROUP_FOR_NORM = 3

# Rows returned inline per anomaly. The full list is one call away via
# `detail`, and a card that renders 400 names is a card nobody reads.
INLINE_ROWS = 8

# An account that has not been used in this long, but still carries access, is
# access nobody is watching. Six months spans a full leave cycle.
DORMANT_DAYS = 180

# How many containment pairs to carry. Ninety-two profiles can nest thousands
# of ways; the ones with people on the wider side are the actionable ones, and
# the count reported is always the true total, not the length of what was kept.
MAX_PAIRS = 60


# ---------------------------------------------------------------------------
# Shared reads. Each is fetched once per scan - the checks overlap heavily and
# re-querying per check turned a 1.2s scan into 9s on Kaitet's 585 users.
# ---------------------------------------------------------------------------


class Estate:
	"""Everything the checks read, gathered once."""

	def __init__(self):
		self.index = capability.build_capability_index()

		self.users = {
			row["name"]: row
			for row in frappe.get_all(
				"User",
				fields=[
					"name",
					"full_name",
					"enabled",
					"user_type",
					"module_profile",
					"last_active",
					"last_login",
				],
			)
		}

		self.profiles_by_user: dict[str, set[str]] = defaultdict(set)
		for row in frappe.get_all(
			"User Role Profile",
			filters={"parenttype": "User"},
			fields=["parent", "role_profile"],
		):
			self.profiles_by_user[row["parent"]].add(row["role_profile"])

		self.roles_by_user: dict[str, set[str]] = defaultdict(set)
		for row in frappe.get_all(
			"Has Role", filters={"parenttype": "User"}, fields=["parent", "role"]
		):
			self.roles_by_user[row["parent"]].add(row["role"])

		self.roles_by_profile = capability._roles_by_role_profile()

		self.employees: dict[str, dict] = {}
		for row in frappe.get_all(
			"Employee",
			filters={"status": "Active"},
			fields=["user_id", "designation", "company", "branch", "grade"],
		):
			if row["user_id"]:
				self.employees.setdefault(row["user_id"], row)

		self.headcount = Counter()
		for user, profiles in self.profiles_by_user.items():
			for profile in profiles:
				self.headcount[profile] += 1

	def name(self, user: str) -> str:
		row = self.users.get(user) or {}
		return row.get("full_name") or user

	def enabled_system_users(self) -> list[str]:
		return [
			name
			for name, row in self.users.items()
			if row["enabled"] and row["user_type"] == "System User"
		]


def _finding(
	kind: str,
	severity: str,
	title: str,
	detail: str,
	rows: list[dict],
	*,
	count: int | None = None,
	discrepancy: bool = False,
	fix: str | None = None,
) -> dict:
	"""One anomaly, shaped for both the card and the drill-in."""
	total = len(rows) if count is None else count
	return {
		# The full list travels with the finding and is stripped by `overview`.
		# One scan, two shapes - the alternative was running every check twice.
		"_all": rows,
		"kind": kind,
		"severity": severity,
		"title": title,
		"detail": detail,
		"count": total,
		"total_rows": len(rows),
		"rows": rows[:INLINE_ROWS],
		"truncated": max(0, len(rows) - INLINE_ROWS),
		"discrepancy": discrepancy,
		"fix": fix,
	}


# ---------------------------------------------------------------------------
# Discrepancies - a grant that disagrees with another fact
# ---------------------------------------------------------------------------


def check_designation_split(estate: Estate) -> list[dict]:
	"""Same job, same company, different access.

	The strongest signal on this site. Kaitet assigns profiles by hand, so where
	a designation has settled on one profile the exceptions are either a
	deliberate variation nobody recorded or a mistake - and the dashboard cannot
	tell which, so it reports rather than decides.
	"""
	groups: dict[tuple[str, str], list[str]] = defaultdict(list)
	for user, row in estate.employees.items():
		if not row.get("designation") or not row.get("company"):
			continue
		if not estate.users.get(user, {}).get("enabled"):
			continue
		groups[(row["designation"], row["company"])].append(user)

	rows = []
	for (designation, company), members in groups.items():
		if len(members) < MIN_GROUP_FOR_NORM:
			continue

		held = Counter(
			frozenset(estate.profiles_by_user.get(user, set())) for user in members
		)
		if len(held) < 2:
			continue

		norm, norm_count = held.most_common(1)[0]
		# A group with no majority has no norm to deviate from - every member is
		# an exception, which is a different problem (an unmanaged designation)
		# and is reported by the coverage view, not here.
		if norm_count < 2:
			continue

		outliers = [
			user
			for user in members
			if frozenset(estate.profiles_by_user.get(user, set())) != norm
		]
		rows.append(
			{
				"label": f"{designation} · {company}",
				"meta": _("{0} of {1} hold {2}").format(
					norm_count,
					len(members),
					", ".join(sorted(norm)) or _("no profile"),
				),
				"extra": _("{0} differ: {1}").format(
					len(outliers),
					", ".join(estate.name(u) for u in outliers[:4])
					+ ("…" if len(outliers) > 4 else ""),
				),
				"users": outliers,
				"weight": len(outliers),
			}
		)

	rows.sort(key=lambda row: -row["weight"])
	affected = sum(row["weight"] for row in rows)

	if not rows:
		return []

	return [
		_finding(
			"designation_split",
			SEVERITY_HIGH,
			_("{0} job groups disagree with themselves").format(len(rows)),
			_(
				"{0} people hold access that differs from the majority in the same "
				"designation and company. Each is either an unrecorded exception "
				"or a mistake."
			).format(affected),
			rows,
			count=affected,
			discrepancy=True,
			fix=_("Open a group to see who differs, then align or record the exception."),
		)
	]


def check_map_conflict(estate: Estate) -> list[dict]:
	"""Held access contradicts the active designation map.

	The map is policy. Where a row is active and the holder has something else,
	one of the two is wrong, and it matters which: the map is what a bulk sweep
	would apply.
	"""
	active = {}
	dimension = settings.map_fieldname("company")
	for row in frappe.get_all(
		"Designation Access Map",
		filters={"is_active": 1},
		fields=["designation", dimension, "role_profile"],
	):
		active[(row["designation"], row[dimension] or None)] = row["role_profile"]

	if not active:
		return []

	rows = []
	for user, employee in estate.employees.items():
		if not estate.users.get(user, {}).get("enabled"):
			continue
		designation = employee.get("designation")
		if not designation:
			continue

		expected = active.get((designation, employee.get("company"))) or active.get(
			(designation, None)
		)
		if not expected:
			continue

		held = estate.profiles_by_user.get(user, set())
		if expected in held:
			continue

		rows.append(
			{
				"label": estate.name(user),
				"meta": f"{designation} · {employee.get('company') or '—'}",
				"extra": _("policy says {0}, holds {1}").format(
					expected, ", ".join(sorted(held)) or _("nothing")
				),
				"users": [user],
				"profile": expected,
			}
		)

	if not rows:
		return []

	return [
		_finding(
			"map_conflict",
			SEVERITY_HIGH,
			_("{0} people contradict the designation map").format(len(rows)),
			_(
				"An active map row says one thing and the account says another. A "
				"bulk sweep would change every one of these."
			),
			rows,
			discrepancy=True,
			fix=_("Fix the account from here, or deactivate the map row if policy moved."),
		)
	]


def check_role_drift(estate: Estate) -> list[dict]:
	"""Roles held that no profile the user holds accounts for.

	v16 prunes roles to the profile union on save, so drift means something
	added a role afterwards - HRMS re-adds approver roles in a User.validate
	doc_event, and a hand-edit does it too. Either way the account grants more
	than its profile says it does, which makes the profile a lie.
	"""
	rows = []
	for user, roles in estate.roles_by_user.items():
		row = estate.users.get(user)
		if not row or not row["enabled"] or user in delegation.RESERVED_USERS:
			continue

		profiles = estate.profiles_by_user.get(user, set())
		if not profiles:
			continue

		accounted = set()
		for profile in profiles:
			accounted.update(estate.roles_by_profile.get(profile, []))

		extra = {r for r in roles if r not in accounted and r != "All"}
		if not extra:
			continue

		rows.append(
			{
				"label": estate.name(user),
				"meta": ", ".join(sorted(profiles)),
				"extra": _("also holds {0}").format(", ".join(sorted(extra)[:5]))
				+ ("…" if len(extra) > 5 else ""),
				"users": [user],
				"weight": len(extra),
			}
		)

	if not rows:
		return []

	rows.sort(key=lambda row: -row["weight"])
	return [
		_finding(
			"role_drift",
			SEVERITY_MODERATE,
			_("{0} accounts hold roles their profile does not grant").format(len(rows)),
			_(
				"Re-saving the user prunes these back to the profile. Where the extra "
				"role is needed, it belongs in a profile instead."
			),
			rows,
			discrepancy=True,
			fix=_("Re-assign the profile to prune, or add the role to a profile."),
		)
	]


def check_multi_profile(estate: Estate) -> list[dict]:
	"""More than one profile on one account.

	Legal in v16 and occasionally right, but the union is what the person can
	do, and nobody designed the union. It is reported with what the extra
	profiles add beyond the largest one, because that number is the whole
	argument.
	"""
	rows = []
	for user, profiles in estate.profiles_by_user.items():
		if len(profiles) < 2:
			continue
		row = estate.users.get(user)
		if not row or not row["enabled"]:
			continue

		largest = max(
			profiles, key=lambda p: capability.total_perm_count(estate.index.get(p, {}))
		)
		base = estate.index.get(largest, {})
		union: dict[str, set[str]] = {dt: set(v) for dt, v in base.items()}
		for profile in profiles:
			for doctype, rights in estate.index.get(profile, {}).items():
				union.setdefault(doctype, set()).update(rights)

		added = capability.total_perm_count(union) - capability.total_perm_count(base)
		rows.append(
			{
				"label": estate.name(user),
				"meta": ", ".join(sorted(profiles)),
				"extra": _("{0} grants beyond {1} alone").format(added, largest),
				"users": [user],
				"weight": added,
			}
		)

	if not rows:
		return []

	rows.sort(key=lambda row: -row["weight"])
	return [
		_finding(
			"multi_profile",
			SEVERITY_MODERATE,
			_("{0} accounts hold more than one role profile").format(len(rows)),
			_(
				"The union of several profiles is access no-one specified. One "
				"profile that covers the job is reviewable; a union is not."
			),
			rows,
			discrepancy=True,
			fix=_("Assign a single profile that covers the job, or create one that does."),
		)
	]


def check_stale_allowlist(estate: Estate) -> list[dict]:
	"""A delegate is allowed to grant a profile that has since become privileged.

	`assert_can_grant` re-checks at write time and refuses, so this is not a
	hole - it is a delegate who will hit a wall the next time they try, and who
	deserves to be told before they do.
	"""
	rows = []
	for name in frappe.get_all("Delegated User Admin", pluck="name"):
		doc = frappe.get_doc("Delegated User Admin", name)
		blocked = [
			row.role_profile
			for row in doc.get("allowed_role_profiles") or []
			if privilege.privileged_grants(row.role_profile)
		]
		if not blocked:
			continue
		rows.append(
			{
				"label": estate.name(doc.user),
				"meta": _("delegate{0}").format("" if doc.enabled else _(" · disabled")),
				"extra": _("would be refused: {0}").format(", ".join(sorted(blocked))),
				"users": [doc.user],
			}
		)

	if not rows:
		return []

	return [
		_finding(
			"stale_allowlist",
			SEVERITY_MODERATE,
			_("{0} delegates may grant a profile that is now privileged").format(len(rows)),
			_(
				"The profile gained write on a permission-bearing doctype after it "
				"was allowlisted. The grant is refused at write time, silently to "
				"the delegate until they try."
			),
			rows,
			discrepancy=True,
			fix=_("Remove it from the allowlist, or narrow the profile."),
		)
	]


# ---------------------------------------------------------------------------
# Anomalies - a grant that is wrong on its own terms
# ---------------------------------------------------------------------------


def check_empty_profiles(estate: Estate) -> list[dict]:
	"""A profile that permits no action at all, held by somebody."""
	rows = [
		{
			"label": profile,
			"meta": _("{0} holders").format(estate.headcount[profile]),
			"extra": _("permits nothing"),
			"profile": profile,
			"weight": estate.headcount[profile],
		}
		for profile, caps in estate.index.items()
		if not caps and estate.headcount.get(profile)
	]

	if not rows:
		return []

	rows.sort(key=lambda row: -row["weight"])
	held = sum(row["weight"] for row in rows)
	return [
		_finding(
			"empty_profile",
			SEVERITY_HIGH,
			_("{0} grants nothing").format(rows[0]["label"])
			if len(rows) == 1
			else _("{0} profiles grant nothing").format(len(rows)),
			_(
				"{0} people hold a profile that permits no action. They either cannot "
				"work, or they are working through a role the profile does not name."
			).format(held),
			rows,
			count=held,
			fix=_("Give the profile roles, or move its holders to one that works."),
		)
	]


def check_identical_profiles(estate: Estate) -> list[dict]:
	"""Different names, byte-identical grants."""
	signatures: dict[frozenset, list[str]] = defaultdict(list)
	for profile, caps in estate.index.items():
		if caps:
			signatures[
				frozenset((dt, right) for dt, rights in caps.items() for right in rights)
			].append(profile)

	rows = []
	for members in signatures.values():
		if len(members) < 2:
			continue
		held = sum(estate.headcount.get(m, 0) for m in members)
		rows.append(
			{
				"label": ", ".join(sorted(members)),
				"meta": _("{0} holders between them").format(held),
				"extra": _("identical grants"),
				"profiles": sorted(members),
				"weight": held,
			}
		)

	if not rows:
		return []

	rows.sort(key=lambda row: -row["weight"])
	return [
		_finding(
			"identical_profiles",
			SEVERITY_MODERATE,
			_("{0} and {1} are identical").format(*rows[0]["profiles"])
			if len(rows) == 1 and len(rows[0]["profiles"]) == 2
			else _("{0} sets of profiles are identical").format(len(rows)),
			_(
				"Same access, different names. Every duplicate is another thing to "
				"keep in step the next time a permission changes."
			),
			rows,
			fix=_("Keep one, move the holders, delete the rest."),
		)
	]


def check_contained_profiles(estate: Estate) -> list[dict]:
	"""One profile wholly contains another, and people hold the wider one.

	Not a fault - a ladder of profiles is often deliberate. It is reported
	because it names, exactly, who could be moved down without losing anything
	they can currently do, which is the cheapest least-privilege win available.
	"""
	signatures = {
		profile: frozenset(
			(dt, right) for dt, rights in caps.items() for right in rights
		)
		for profile, caps in estate.index.items()
		if caps
	}
	ordered = sorted(signatures, key=lambda p: len(signatures[p]))

	rows = []
	for i, narrow in enumerate(ordered):
		for wide in ordered[i + 1 :]:
			if len(signatures[narrow]) == len(signatures[wide]):
				continue  # identical sets are their own finding
			if not signatures[narrow] < signatures[wide]:
				continue
			holders = estate.headcount.get(wide, 0)
			if not holders:
				continue
			rows.append(
				{
					"label": f"{narrow} ⊂ {wide}",
					"meta": _("{0} hold the wider one").format(holders),
					"extra": _("{0} adds {1} grants").format(
						wide, len(signatures[wide]) - len(signatures[narrow])
					),
					"profiles": [narrow, wide],
					"weight": holders,
				}
			)

	if not rows:
		return []

	rows.sort(key=lambda row: -row["weight"])
	total = len(rows)
	kept = rows[:MAX_PAIRS]

	detail = _(
		"Everything the narrower profile permits, the wider one permits too. "
		"Anyone on the wider one who only needs the narrower is over-granted."
	)
	if total > len(kept):
		detail += " " + _("Showing the {0} with the most holders.").format(len(kept))

	return [
		_finding(
			"contained_profiles",
			SEVERITY_LOW,
			_("{0} profile pairs are nested").format(total),
			detail,
			kept,
			count=total,
			fix=_("Check whether the holders need the difference."),
		)
	]


def check_dead_profiles(estate: Estate) -> list[dict]:
	"""A profile nobody holds."""
	rows = [
		{
			"label": profile,
			"meta": _("{0} grants").format(capability.total_perm_count(caps)),
			"extra": _("no holders"),
			"profile": profile,
		}
		for profile, caps in sorted(estate.index.items())
		if not estate.headcount.get(profile)
	]

	if not rows:
		return []

	return [
		_finding(
			"dead_profile",
			SEVERITY_LOW,
			_("{0} profiles are held by nobody").format(len(rows)),
			_(
				"Unused, still maintained, and still available to grant. Some are "
				"deliberately kept ready; the rest are clutter."
			),
			rows,
			fix=_("Delete what is not coming back."),
		)
	]


def check_no_profile(estate: Estate) -> list[dict]:
	"""An enabled system user with no profile at all."""
	rows = []
	for user in estate.enabled_system_users():
		if user in delegation.RESERVED_USERS:
			continue
		if estate.profiles_by_user.get(user):
			continue
		employee = estate.employees.get(user) or {}
		rows.append(
			{
				"label": estate.name(user),
				"meta": employee.get("designation") or _("no designation"),
				"extra": employee.get("company") or _("no employee record"),
				"users": [user],
			}
		)

	if not rows:
		return []

	return [
		_finding(
			"no_profile",
			SEVERITY_MODERATE,
			_("{0} enabled accounts hold no role profile").format(len(rows)),
			_(
				"Whatever they can do comes from roles set by hand, which no profile "
				"describes and no review covers."
			),
			rows,
			fix=_("Assign a profile, or disable the account."),
		)
	]


def check_disabled_with_access(estate: Estate) -> list[dict]:
	"""A disabled account that still carries a profile.

	Disabling stops the login, not the grant. Re-enabling - which is a one-click
	act nobody reviews - restores everything at once.
	"""
	rows = []
	for user, row in estate.users.items():
		if row["enabled"] or user in delegation.RESERVED_USERS:
			continue
		profiles = estate.profiles_by_user.get(user, set())
		if not profiles:
			continue
		rows.append(
			{
				"label": estate.name(user),
				"meta": _("disabled"),
				"extra": ", ".join(sorted(profiles)),
				"users": [user],
			}
		)

	if not rows:
		return []

	return [
		_finding(
			"disabled_with_access",
			SEVERITY_MODERATE,
			_("{0} disabled accounts still carry a profile").format(len(rows)),
			_(
				"Disabling blocks the login and leaves the grant. Re-enabling restores "
				"all of it without a review."
			),
			rows,
			fix=_("Strip the profile when the person leaves, not just the login."),
		)
	]


def check_dormant_access(estate: Estate) -> list[dict]:
	"""Enabled, granted, and not used in a long time."""
	cutoff = now_datetime()
	rows = []
	for user in estate.enabled_system_users():
		if user in delegation.RESERVED_USERS:
			continue
		if not estate.profiles_by_user.get(user):
			continue

		row = estate.users[user]
		seen = row.get("last_active") or row.get("last_login")
		if seen:
			days = (cutoff - get_datetime(seen)).days
			if days < DORMANT_DAYS:
				continue
			meta = _("last seen {0} days ago").format(days)
		else:
			days = 10_000
			meta = _("never signed in")

		rows.append(
			{
				"label": estate.name(user),
				"meta": meta,
				"extra": ", ".join(sorted(estate.profiles_by_user[user])),
				"users": [user],
				"weight": days,
			}
		)

	if not rows:
		return []

	rows.sort(key=lambda row: -row["weight"])
	return [
		_finding(
			"dormant_access",
			SEVERITY_LOW,
			_("{0} granted accounts have gone unused").format(len(rows)),
			_(
				"Enabled, carrying a profile, and not signed in for {0} days or "
				"more. Access nobody is watching."
			).format(DORMANT_DAYS),
			rows,
			fix=_("Confirm the person still needs it, or disable and strip."),
		)
	]


def check_privileged_holders(estate: Estate) -> list[dict]:
	"""Who holds a profile that can change permissions.

	This is the one list where the count matters less than the names.
	"""
	privileged = {p for p in estate.index if privilege.is_privileged(p)}
	role = "System Manager"

	rows = []
	for user, row in estate.users.items():
		if user in delegation.RESERVED_USERS or not row["enabled"]:
			continue
		held = estate.profiles_by_user.get(user, set()) & privileged
		has_role = role in estate.roles_by_user.get(user, set())
		if not held and not has_role:
			continue
		rows.append(
			{
				"label": estate.name(user),
				"meta": (estate.employees.get(user) or {}).get("company")
				or _("no employee record"),
				"extra": ", ".join(sorted(held) + ([role] if has_role else [])),
				"users": [user],
				"weight": 2 if has_role else 1,
			}
		)

	if not rows:
		return []

	rows.sort(key=lambda row: (-row["weight"], row["label"]))
	return [
		_finding(
			"privileged_holder",
			SEVERITY_HIGH,
			_("{0} accounts can change permissions").format(len(rows)),
			_(
				"System Manager, or a profile granting write on a permission-bearing "
				"doctype. No delegate can grant these; every one was set by hand."
			),
			rows,
			fix=_("Confirm each name belongs on this list."),
		)
	]


def check_orphan_users(estate: Estate) -> list[dict]:
	"""Enabled system users with no active employee record."""
	rows = [
		{
			"label": estate.name(user),
			"meta": _("no active employee record"),
			"extra": ", ".join(sorted(estate.profiles_by_user.get(user, set())))
			or _("no profile"),
			"users": [user],
		}
		for user in sorted(estate.enabled_system_users())
		if user not in delegation.RESERVED_USERS and user not in estate.employees
	]

	if not rows:
		return []

	return [
		_finding(
			"orphan_user",
			SEVERITY_LOW,
			_("{0} accounts have no employee record").format(len(rows)),
			_(
				"With no employee there is no company, so no delegated administrator "
				"can reach them and no designation rule applies."
			),
			rows,
			fix=_("Link an employee, or accept that only a System Manager can manage them."),
		)
	]


def check_map_pending(estate: Estate) -> list[dict]:
	"""Map rows seeded from observation and never reviewed."""
	pending = frappe.get_all(
		"Designation Access Map",
		filters={"is_active": 0},
		fields=["name", "designation", "role_profile", "for_company"],
		limit=200,
	)
	if not pending:
		return []

	rows = [
		{
			"label": row["designation"],
			"meta": row["for_company"] or _("all companies"),
			"extra": _("would grant {0}").format(row["role_profile"]),
			"map_row": row["name"],
		}
		for row in pending
	]

	return [
		_finding(
			"map_pending",
			SEVERITY_LOW,
			_("{0} map rows await a decision").format(len(rows)),
			_(
				"Seeded from what people already hold and left inactive. Until a row "
				"is activated it governs nothing."
			),
			rows,
			fix=_("Activate the rows that match policy on the Designation Map."),
		)
	]


CHECKS = (
	# Discrepancies first: they cost the most to find by hand.
	check_designation_split,
	check_map_conflict,
	check_privileged_holders,
	check_empty_profiles,
	check_role_drift,
	check_multi_profile,
	check_disabled_with_access,
	check_no_profile,
	check_stale_allowlist,
	check_identical_profiles,
	check_contained_profiles,
	check_dormant_access,
	check_dead_profiles,
	check_orphan_users,
	check_map_pending,
)


CACHE_KEY = "upande_core:anomaly_scan"
CACHE_TTL = 600


def clear_cache(doc=None, method=None) -> None:
	"""Drop the cached scan. Also a doc_events hook."""
	frappe.cache().delete_value(CACHE_KEY)


def scan(force: bool = False) -> list[dict]:
	"""Run every check. Ordered by severity, then discrepancies, then size.

	Cached: fifteen checks over every user, profile and permission row is 5.8s
	on Kaitet, and the answer only moves when an assignment or a permission
	does - both of which clear this key.
	"""
	if not force:
		cached = frappe.cache().get_value(CACHE_KEY)
		if cached is not None:
			return cached

	found = _run()
	frappe.cache().set_value(CACHE_KEY, found, expires_in_sec=CACHE_TTL)
	return found


def _run() -> list[dict]:
	estate = Estate()

	out = []
	for check in CHECKS:
		try:
			out.extend(check(estate))
		except Exception:
			# One broken check must not blank the page. The traceback goes to the
			# error log where it can be fixed; the other fourteen still report.
			frappe.log_error(title=f"Role Advisor anomaly check: {check.__name__}")

	return sorted(
		out,
		key=lambda row: (
			_ORDER[row["severity"]],
			0 if row["discrepancy"] else 1,
			-row["count"],
		),
	)


# ---------------------------------------------------------------------------
# Whitelisted surface
# ---------------------------------------------------------------------------


def _guard():
	frappe.only_for(["System Manager", settings.delegate_role()])


@frappe.whitelist()
def overview(force: int | str = 0) -> dict:
	"""Every anomaly, plus the counts the header needs."""
	_guard()
	found = scan(force=bool(int(force or 0)))

	people = {
		user
		for row in found
		if row["discrepancy"]
		for entry in row["_all"]
		for user in entry.get("users", [])
	}

	return {
		"anomalies": [
			{key: value for key, value in row.items() if key != "_all"} for row in found
		],
		"counts": {
			"high": sum(1 for row in found if row["severity"] == SEVERITY_HIGH),
			"moderate": sum(1 for row in found if row["severity"] == SEVERITY_MODERATE),
			"low": sum(1 for row in found if row["severity"] == SEVERITY_LOW),
			"discrepancies": sum(1 for row in found if row["discrepancy"]),
			"people": len(people),
		},
	}


@frappe.whitelist()
def detail(kind: str) -> dict:
	"""Every row for one anomaly, not just the inline sample."""
	_guard()

	for row in scan():
		if row["kind"] == kind:
			return {**row, "rows": row.pop("_all")}

	frappe.throw(_("{0} is not an anomaly this site reports.").format(kind))
