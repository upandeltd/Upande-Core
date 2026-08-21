# Copyright (c) 2026, ghost-mann and contributors
# For license information, please see license.txt

"""Resolve "what I need to do" into "which profile grants it".

The point of the whole app in one module: a person names the documents they need
to work with, and the permission model is worked out for them. Nobody raising a
request has to know that `Agriculture Supervisor` is the answer.

**The unit is the doctype**, not a catalogue entry. A doctype plus a right
already says what someone needs, in the vocabulary they see on every form, and
it needs no authoring and never goes stale when an app adds doctypes. A named
bundle (`Access Transaction`) is optional sugar for the one case it earns - an
ask spanning several documents, like "run payroll".

Four outcomes, and the two Gap kinds are genuinely different problems:

    Covered                    what they hold already grants every request
    Fit Found                  an existing profile covers it - here is the over-grant
    Gap - New Profile Needed   every requirement exists in some role, but no
                               single profile bundles them
    Gap - New Role Needed      some requirement is granted by no role on the
                               site, so a role has to be built first
"""

import frappe
from frappe import _
from frappe.utils import cint

from role_advisor import audit, capability, delegation, settings

COVERED = "Covered"
FIT_FOUND = "Fit Found"
GAP_PROFILE = "Gap - New Profile Needed"
GAP_ROLE = "Gap - New Role Needed"

# How a right reads when a catalogue entry is drafted from raw permission data.
VERBS = {
	"read": "View",
	"write": "Edit",
	"create": "Create",
	"submit": "Submit",
	"cancel": "Cancel",
	"delete": "Delete",
	"report": "Report on",
	"export": "Export",
}


def _clean(requirements) -> list[dict]:
	"""Normalise and validate a list of {doctype, right} asks."""
	if isinstance(requirements, str):
		requirements = frappe.parse_json(requirements)
	if not requirements:
		frappe.throw(_("Name at least one document you need to work with."))

	rights = set(capability.TRACKED_PERMS)
	seen, cleaned = set(), []

	for row in requirements:
		doctype = (row.get("doctype") or row.get("document_type") or "").strip()
		right = (row.get("right") or "").strip()

		if not doctype or not right:
			frappe.throw(_("Each line needs a document and a right."))
		if right not in rights:
			frappe.throw(_("{0} is not a permission this app tracks.").format(right))
		if not frappe.db.exists("DocType", doctype):
			frappe.throw(_("{0} is not a document type on this site.").format(doctype))
		if frappe.db.get_value("DocType", doctype, "istable"):
			frappe.throw(
				_("{0} is a child table and cannot be granted on its own.").format(doctype)
			)

		key = (doctype, right)
		if key in seen:
			continue
		seen.add(key)
		cleaned.append(
			{
				"document_type": doctype,
				"right": right,
				"from_bundle": row.get("from_bundle"),
			}
		)

	return cleaned


def _covers(caps: dict[str, set[str]], requirements: list[dict]) -> bool:
	return all(req["right"] in caps.get(req["document_type"], ()) for req in requirements)


def _uncovered(caps: dict[str, set[str]], requirements: list[dict]) -> list[dict]:
	return [req for req in requirements if req["right"] not in caps.get(req["document_type"], ())]


def _over_grant(caps: dict[str, set[str]], requirements: list[dict]) -> list[str]:
	"""What a profile hands over beyond the ask, worst first."""
	asked = {(req["document_type"], req["right"]) for req in requirements}
	extra: dict[str, set[str]] = {}
	for doctype, rights in caps.items():
		beyond = {r for r in rights if (doctype, r) not in asked}
		if beyond:
			extra[doctype] = beyond

	return [
		f"{doctype}: {', '.join(sorted(extra[doctype]))}"
		for doctype in sorted(extra, key=lambda dt: (-len(extra[dt]), dt))
	]


@frappe.whitelist()
def search_documents(txt: str = "", limit: int = 25) -> list[dict]:
	"""Search the documents a person might need to work with.

	Searches doctypes directly - no catalogue to maintain. Submittable documents
	rank first because they are the ones people perform transactions on, and an
	exact prefix match beats a mid-string one.
	"""
	like = f"%{txt or ''}%"

	return frappe.db.sql(
		"""
		select d.name, d.module, d.is_submittable
		from `tabDocType` d
		where d.istable = 0 and d.issingle = 0
		  and ifnull(d.module, '') != ''
		  and (d.name like %(like)s or d.module like %(like)s)
		order by
		  case when d.name like %(starts)s then 0 else 1 end,
		  d.is_submittable desc,
		  d.name
		limit %(limit)s
		""",
		{"like": like, "starts": f"{txt or ''}%", "limit": cint(limit) or 25},
		as_dict=True,
	)


@frappe.whitelist()
def search_bundles(txt: str = "", limit: int = 10) -> list[dict]:
	"""Named multi-document asks, if anyone has authored any."""
	like = f"%{txt or ''}%"
	rows = frappe.db.sql(
		"""
		select name, transaction_name, description
		from `tabAccess Transaction`
		where is_active = 1 and transaction_name like %(like)s
		order by transaction_name limit %(limit)s
		""",
		{"like": like, "limit": cint(limit) or 10},
		as_dict=True,
	)

	for row in rows:
		row["requirements"] = frappe.get_all(
			"Access Transaction Requirement",
			filters={"parent": row["name"]},
			fields=["document_type", "right"],
		)

	return rows


@frappe.whitelist()
def expand_bundle(bundle: str) -> list[dict]:
	"""The requirements a bundle stands for."""
	rows = frappe.get_all(
		"Access Transaction Requirement",
		filters={"parent": bundle},
		fields=["document_type as doctype", "right"],
	)
	for row in rows:
		row["from_bundle"] = bundle

	return _clean(rows)


@frappe.whitelist()
def rights_for(doctype: str) -> list[str]:
	"""Which rights are meaningful on this document.

	`submit` and `cancel` only mean something on a submittable doctype, so
	offering them elsewhere would invite an ask that can never be satisfied.
	"""
	if not frappe.db.exists("DocType", doctype):
		frappe.throw(_("{0} is not a document type on this site.").format(doctype))

	rights = ["read", "write", "create", "delete"]
	if cint(frappe.db.get_value("DocType", doctype, "is_submittable")):
		rights = ["read", "write", "create", "submit", "cancel", "delete"]

	return rights


@frappe.whitelist()
def resolve(user: str, requirements) -> dict:
	"""Work out which profile satisfies a request, and what it would over-grant.

	Read-only. Callable by anyone for themselves, and by a delegate for anyone
	in their scope - the same rule the request doctype enforces.
	"""
	if user != frappe.session.user and "System Manager" not in frappe.get_roles():
		admin = delegation.current_admin()
		if not admin:
			frappe.throw(
				_("You may only check this for yourself."), frappe.PermissionError
			)
		delegation.assert_can_manage(admin, user)

	requirements = _clean(requirements)
	index = capability.build_capability_index()
	held = capability.get_user_role_profiles(user)

	# Already covered by what they hold? Then there is nothing to grant.
	current: dict[str, set[str]] = {}
	for profile in held:
		for doctype, rights in index.get(profile, {}).items():
			current.setdefault(doctype, set()).update(rights)

	base = {
		"user": user,
		"requirements": requirements,
		"holds": held,
	}

	if held and _covers(current, requirements):
		return {
			**base,
			"resolution": COVERED,
			"profile": None,
			"over_grant": [],
			"notes": _("{0} already covers every one of these.").format(", ".join(held)),
		}

	candidates = [
		profile for profile, caps in index.items() if caps and _covers(caps, requirements)
	]

	if candidates:
		# Where several cover the ask they differ only in what *else* they hand
		# over, so the smallest total grant wins: least authority beyond the
		# request, smallest blast radius. Ties break on name for repeatability.
		best = min(
			candidates,
			key=lambda profile: (
				capability.total_perm_count(index[profile]),
				len(index[profile]),
				profile,
			),
		)
		over = _over_grant(index[best], requirements)

		return {
			**base,
			"resolution": FIT_FOUND,
			"profile": best,
			"alternatives": sorted(
				candidates, key=lambda p: capability.total_perm_count(index[p])
			)[:5],
			"over_grant": over,
			"grants": capability.total_perm_count(index[best]),
			"doctypes": len(index[best]),
			"notes": _(
				"{0} is the tightest profile that covers this. It also grants {1} other things."
			).format(best, len(over)),
		}

	# Nothing bundles it. Is every piece available *somewhere* on the site?
	site_wide = capability.site_wide_role_capabilities()
	unreachable = _uncovered(site_wide, requirements)

	if unreachable:
		return {
			**base,
			"resolution": GAP_ROLE,
			"profile": None,
			"over_grant": [],
			"unreachable": [
				f"{req['document_type']}: {req['right']}" for req in unreachable
			],
			"notes": _(
				"No role on this site grants {0}. A role has to be created or extended first."
			).format(
				", ".join(f"{r['document_type']} ({r['right']})" for r in unreachable)
			),
		}

	roles = _roles_that_cover(requirements)

	return {
		**base,
		"resolution": GAP_PROFILE,
		"profile": None,
		"over_grant": [],
		"suggested_roles": roles,
		"notes": _(
			"Every piece exists in some role, but no single profile bundles them. "
			"A new profile from these {0} roles would do it."
		).format(len(roles)),
	}


def _roles_that_cover(requirements: list[dict]) -> list[str]:
	"""A small set of roles that between them satisfy the request.

	Greedy: repeatedly take the role covering the most of what is still missing.
	Not provably minimal - set cover never is cheaply - but it produces a short,
	explainable list rather than every role that touches the doctypes.
	"""
	all_roles = frappe.get_all("Role", pluck="name")
	role_caps = capability._capabilities_from_rows(
		capability._perm_rows_for_roles(all_roles)
	)

	outstanding = {(req["document_type"], req["right"]) for req in requirements}
	chosen = []

	while outstanding:
		best, covered = None, set()
		for role, caps in role_caps.items():
			hits = {
				(doctype, right)
				for doctype, right in outstanding
				if right in caps.get(doctype, ())
			}
			if len(hits) > len(covered):
				best, covered = role, hits
		if not best:
			break
		chosen.append(best)
		outstanding -= covered

	return chosen


@frappe.whitelist()
def submit_request(user: str, requirements, reason: str = "") -> dict:
	"""Record the ask, with its resolution attached."""
	verdict = resolve(user, requirements)

	doc = frappe.new_doc("Access Request")
	doc.for_user = user
	doc.reason = reason
	for row in verdict["requirements"]:
		doc.append("transactions", row)
	doc.resolution = verdict["resolution"]
	doc.recommended_profile = verdict.get("profile")
	doc.over_grant = "; ".join(verdict.get("over_grant", [])[:12])
	doc.resolution_notes = verdict.get("notes")
	doc.status = "Resolved" if verdict.get("profile") else "Open"
	doc.insert(ignore_permissions=True)
	frappe.db.commit()

	return {"request": doc.name, **verdict}


@frappe.whitelist()
def fulfil(request: str) -> dict:
	"""Assign the recommended profile, through the ordinary gated path.

	Deliberately calls `api.assign_access` rather than writing the user: the
	request flow gets no privileged shortcut of its own, so a delegate can only
	fulfil what they could already have assigned by hand.
	"""
	from role_advisor import api

	doc = frappe.get_doc("Access Request", request)
	if not doc.recommended_profile:
		frappe.throw(_("This request has no recommended profile to assign."))
	if doc.status == "Fulfilled":
		frappe.throw(_("Already fulfilled."))

	result = api.assign_access(doc.for_user, doc.recommended_profile)

	doc.assigned_profile = doc.recommended_profile
	doc.assignment_log = result["log"]
	doc.status = "Fulfilled"
	doc.save(ignore_permissions=True)
	frappe.db.commit()

	return {"request": doc.name, **result}


@frappe.whitelist()
def my_requests(limit: int = 20) -> list[dict]:
	"""Requests the caller raised or is the subject of."""
	return frappe.db.sql(
		"""
		select name, for_user, raised_by, status, resolution, recommended_profile,
		       assigned_profile, reason, creation
		from `tabAccess Request`
		where for_user = %(me)s or raised_by = %(me)s
		order by creation desc limit %(limit)s
		""",
		{"me": frappe.session.user, "limit": cint(limit) or 20},
		as_dict=True,
	)


@frappe.whitelist()
def queue(limit: int = 50) -> list[dict]:
	"""Open requests an administrator should look at."""
	frappe.only_for(["System Manager", settings.delegate_role()])
	# A System Manager sees every request even when they also hold a delegate
	# record. The record bounds what a delegate may do; it never narrows an
	# administrator's view - otherwise requests silently vanish from the queue.
	admin = (
		None
		if "System Manager" in frappe.get_roles()
		else delegation.current_admin()
	)

	rows = frappe.get_all(
		"Access Request",
		filters={"status": ("in", ["Open", "Resolved"])},
		fields=[
			"name", "for_user", "raised_by", "status", "resolution",
			"recommended_profile", "over_grant", "reason", "company", "creation",
		],
		order_by="creation desc",
		limit=cint(limit) or 50,
	)

	if admin:
		rows = [row for row in rows if delegation.can_manage(admin, row["for_user"])]

	for row in rows:
		row["transactions"] = frappe.get_all(
			"Access Request Line",
			filters={"parent": row["name"]},
			fields=["document_type", "right", "from_bundle"],
		)

	return rows


def clear_catalogue() -> int:
	"""Remove every bundle. Bundles are authored by hand, never generated.

	An earlier version drafted one bundle per (doctype, right) pair and produced
	2,041 entries whose names were literally the doctype and the right - pure
	indirection over what a document search already gives. Bundles now exist
	only where a human decides one ask spans several documents.
	"""
	names = frappe.get_all("Access Transaction", pluck="name")
	for name in names:
		frappe.delete_doc("Access Transaction", name, force=True)
	frappe.db.commit()
	print(f"removed {len(names)} bundles")

	return len(names)


# ---------------------------------------------------------------------------
# Self-service. Every method here is about the caller and takes no user
# argument, so there is no parameter to tamper with - an ordinary employee
# cannot ask these anything about anybody else.
# ---------------------------------------------------------------------------


@frappe.whitelist()
def my_access() -> dict:
	"""What the caller can do today, in their own terms."""
	user = frappe.session.user

	profiles = capability.get_user_role_profiles(user)
	index = capability.build_capability_index()

	granted: dict[str, set[str]] = {}
	for profile in profiles:
		for doctype, rights in index.get(profile, {}).items():
			granted.setdefault(doctype, set()).update(rights)

	module_of = {
		row["name"]: row["module"]
		for row in frappe.get_all("DocType", fields=["name", "module"])
	}
	areas: dict[str, int] = {}
	for doctype in granted:
		module = module_of.get(doctype)
		if module:
			areas[module] = areas.get(module, 0) + 1

	employee = frappe.db.get_value(
		"Employee",
		{"user_id": user, "status": "Active"},
		["company", "department", "designation"],
		as_dict=True,
	)

	return {
		"user": user,
		"full_name": frappe.db.get_value("User", user, "full_name"),
		"profiles": profiles,
		"roles": frappe.db.count("Has Role", {"parent": user, "parenttype": "User"}),
		"doctypes": len(granted),
		"grants": capability.total_perm_count(granted),
		"employee": employee,
		"areas": [
			{"module": module, "doctypes": count}
			for module, count in sorted(areas.items(), key=lambda kv: -kv[1])[:12]
		],
		# Whether to offer the full dashboard at all.
		"is_administrator": bool(
			{"System Manager", settings.delegate_role()} & set(frappe.get_roles())
		),
	}


@frappe.whitelist()
def check_for_me(requirements) -> dict:
	"""Can I already do this? Resolves for the caller and nobody else."""
	return resolve(frappe.session.user, requirements)


@frappe.whitelist()
def request_for_me(requirements, reason: str = "") -> dict:
	"""Raise a request for the caller. No user argument, by design."""
	return submit_request(frappe.session.user, requirements, reason)


@frappe.whitelist()
def refuse(request: str, note: str = "") -> dict:
	"""Turn a request down, with a reason the requester can read."""
	frappe.only_for(["System Manager", settings.delegate_role()])

	doc = frappe.get_doc("Access Request", request)
	if doc.status == "Fulfilled":
		frappe.throw(_("Already fulfilled — it cannot be refused now."))

	if "System Manager" not in frappe.get_roles():
		admin = delegation.current_admin()
		if admin:
			delegation.assert_can_manage(admin, doc.for_user)

	doc.status = "Refused"
	doc.resolution_notes = (note or "").strip() or _("Refused without a note.")
	doc.save(ignore_permissions=True)
	frappe.db.commit()

	return {"request": doc.name, "status": doc.status}


@frappe.whitelist()
def recheck(request: str) -> dict:
	"""Resolve a request again against permissions as they are now.

	A request answered last week may answer differently today - profiles get
	edited. Re-checking before granting means the recommendation shown is the
	one that will actually be applied.
	"""
	frappe.only_for(["System Manager", settings.delegate_role()])

	doc = frappe.get_doc("Access Request", request)
	requirements = [
		{"doctype": line.document_type, "right": line.right} for line in doc.transactions
	]
	verdict = resolve(doc.for_user, requirements)

	doc.resolution = verdict["resolution"]
	doc.recommended_profile = verdict.get("profile")
	doc.over_grant = "; ".join(verdict.get("over_grant", [])[:12])
	doc.resolution_notes = verdict.get("notes")
	if doc.status != "Fulfilled":
		doc.status = "Resolved" if verdict.get("profile") else "Open"
	doc.save(ignore_permissions=True)
	frappe.db.commit()

	return {"request": doc.name, **verdict}
