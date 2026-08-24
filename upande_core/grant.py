# Copyright (c) 2026, ghost-mann and contributors
# For license information, please see license.txt

"""Granting access the way Frappe actually enforces it.

Frappe is role-based. A user holds roles; a role carries permission rows; a
permission row says which rights it grants on which doctype. Nothing else in
the framework decides whether an action is allowed. So the honest question to
ask an administrator is not "which profile shall I give this person" - it is
"which documents does this person need to work with, and what must they do to
them" - and then to derive the profile from the answer.

That is what this module does:

    module -> doctype -> right      what the person needs to do
        v
    capability index                which profiles satisfy it
        v
    tightest fit                    the one that satisfies it and no more
        v
    upande_core.api.assign_access  the only write path

The picker only ever offers a (doctype, right) pair that some role on this site
actually grants. An interface that lets you ask for the impossible and then
fails is worse than one that never offered it.
"""

from collections import defaultdict

import frappe
from frappe import _
from frappe.utils import cint

from upande_core import api, capability, delegation, requests, settings

# A right nobody thinks about but every role carries; offering it as a choice
# adds noise without adding an option.
IMPLICIT_RIGHTS = frozenset({"print", "email", "share", "report", "export"})

# The order an administrator reasons in: look, change, make, finish, undo, remove.
RIGHT_ORDER = ("read", "write", "create", "submit", "cancel", "amend", "delete")


def _guard():
	frappe.only_for(["System Manager", settings.delegate_role()])


def _reachable() -> dict[str, set[str]]:
	"""Every (doctype, right) some role on this site grants.

	The ceiling on what can be asked for. Cached with the capability index it is
	derived from, because recomputing it walks every permission row on the site.
	"""
	return capability.site_wide_role_capabilities()


# ---------------------------------------------------------------------------
# The catalogue an administrator picks from
# ---------------------------------------------------------------------------


@frappe.whitelist()
def modules() -> list[dict]:
	"""Modules that contain at least one grantable document, with counts."""
	_guard()
	reachable = _reachable()

	rows = frappe.db.sql(
		"""
		select d.name, d.module, d.is_submittable
		from `tabDocType` d
		where d.istable = 0 and d.issingle = 0 and ifnull(d.module, '') != ''
		""",
		as_dict=True,
	)

	grouped: dict[str, list[dict]] = defaultdict(list)
	for row in rows:
		rights = reachable.get(row["name"])
		if not rights:
			continue
		grouped[row["module"]].append(row)

	out = [
		{
			"module": module,
			"doctypes": len(members),
			"submittable": sum(1 for row in members if row["is_submittable"]),
		}
		for module, members in grouped.items()
	]

	return sorted(out, key=lambda row: row["module"])


@frappe.whitelist()
def documents(module: str | None = None, txt: str = "", limit: int = 200) -> list[dict]:
	"""Grantable documents, optionally within one module.

	`rights` on each row is what some role on this site can actually grant on
	that document - not the full list of rights the doctype declares. Asking for
	`submit` on a doctype where no role grants it produces a gap finding and
	wastes everybody's afternoon.
	"""
	_guard()
	reachable = _reachable()

	filters = ["d.istable = 0", "d.issingle = 0", "ifnull(d.module, '') != ''"]
	args: dict = {"limit": cint(limit) or 200}

	if module:
		filters.append("d.module = %(module)s")
		args["module"] = module
	if txt:
		filters.append("(d.name like %(like)s or d.module like %(like)s)")
		args["like"] = f"%{txt}%"

	rows = frappe.db.sql(
		f"""
		select d.name, d.module, d.is_submittable
		from `tabDocType` d
		where {" and ".join(filters)}
		order by d.is_submittable desc, d.name
		limit %(limit)s
		""",
		args,
		as_dict=True,
	)

	out = []
	for row in rows:
		granted = reachable.get(row["name"])
		if not granted:
			continue

		offered = [
			right
			for right in RIGHT_ORDER
			if right in granted and right not in IMPLICIT_RIGHTS
		]
		if not row["is_submittable"]:
			# `submit`, `cancel` and `amend` are meaningless off a submittable
			# doctype even where a permission row carries them.
			offered = [r for r in offered if r not in ("submit", "cancel", "amend")]
		if not offered:
			continue

		out.append(
			{
				"doctype": row["name"],
				"module": row["module"],
				"submittable": bool(row["is_submittable"]),
				"rights": offered,
			}
		)

	return out


# ---------------------------------------------------------------------------
# Resolution and the write
# ---------------------------------------------------------------------------


@frappe.whitelist()
def resolve(user: str, needs) -> dict:
	"""What would satisfy these needs for this user, and at what cost.

	Delegates to `requests.resolve` so the answer an administrator sees granting
	access is the same answer a requester saw asking for it. Two resolvers that
	could disagree is a bug waiting for a Friday.
	"""
	_guard()
	admin = delegation.acting_admin()
	delegation.assert_target(admin, user)

	verdict = requests.resolve(user, needs)

	# A delegate can only act on a recommendation inside their allowlist. Saying
	# so here, rather than at the write, keeps the button honest.
	if admin and verdict.get("profile"):
		allowed = {row.role_profile for row in admin.get("allowed_role_profiles") or []}
		verdict["grantable"] = verdict["profile"] in allowed
		if not verdict["grantable"]:
			verdict["blocked_reason"] = _(
				"{0} covers this but is not one of the profiles you may grant."
			).format(verdict["profile"])
		alternatives = [p for p in verdict.get("alternatives", []) if p in allowed]
		verdict["grantable_alternatives"] = alternatives
	else:
		verdict["grantable"] = bool(verdict.get("profile"))
		verdict["grantable_alternatives"] = verdict.get("alternatives", [])

	return verdict


@frappe.whitelist()
def coverage(user: str) -> dict:
	"""What this user can do now, by module.

	The "before" half of every grant decision. Grouped by module because that is
	how the person asking thinks about their own job.
	"""
	_guard()
	admin = delegation.acting_admin()
	delegation.assert_target(admin, user)

	index = capability.build_capability_index()
	held = capability.get_user_role_profiles(user)

	current: dict[str, set[str]] = {}
	for profile in held:
		for doctype, rights in index.get(profile, {}).items():
			current.setdefault(doctype, set()).update(rights)

	module_of = dict(
		frappe.db.sql("select name, module from `tabDocType` where ifnull(module,'') != ''")
	)

	by_module: dict[str, dict] = defaultdict(lambda: {"doctypes": 0, "rights": 0})
	for doctype, rights in current.items():
		module = module_of.get(doctype)
		if not module:
			continue
		by_module[module]["doctypes"] += 1
		by_module[module]["rights"] += len(rights)

	return {
		"user": user,
		"full_name": frappe.db.get_value("User", user, "full_name") or user,
		"profiles": held,
		"module_profile": frappe.db.get_value("User", user, "module_profile"),
		"doctypes": len(current),
		"rights": capability.total_perm_count(current),
		"modules": sorted(
			(
				{"module": module, **counts}
				for module, counts in by_module.items()
			),
			key=lambda row: -row["rights"],
		),
	}


@frappe.whitelist()
def apply(user: str, role_profile: str, needs=None, note: str = "") -> dict:
	"""Grant the profile, then verify it actually covers what was asked for.

	The verification is the point. `assign_access` reports what it changed;
	it does not know what the change was *for*. Re-resolving afterwards turns
	"a profile was assigned" into "the person can now do the thing", which is
	the only outcome anybody wanted.
	"""
	_guard()
	result = api.assign_access(user, role_profile)

	if needs:
		wanted = requests._clean(needs)
		index = capability.build_capability_index()
		now: dict[str, set[str]] = {}
		for profile in capability.get_user_role_profiles(user):
			for doctype, rights in index.get(profile, {}).items():
				now.setdefault(doctype, set()).update(rights)

		missing = requests._uncovered(now, wanted)
		result["covered"] = not missing
		result["still_missing"] = [
			f"{row['document_type']}: {row['right']}" for row in missing
		]
		result["verified_against"] = wanted
	else:
		result["covered"] = None

	if note:
		frappe.db.set_value(
			"Access Assignment Log", result["log"], "decision_notes", note[:1000]
		)

	return result
