# Copyright (c) 2026, Upande and contributors
# For license information, please see license.txt

"""Minimum-redundancy Role Profile advisor.

Given the transactions a user needs to perform, work out the tightest-fitting
Role Profile that covers them - and show the administrator exactly what that
profile would over-grant before they approve it.
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.permissions import get_doctypes_with_custom_docperms
from frappe.utils import cint

# The rights a Transaction Catalog row may require. Deliberately excludes
# `email`, `print` and `share`: they are not transactions anyone requests here,
# and counting them would inflate every profile's tightness score equally
# without changing the ranking - only the noise in the over-grant diff.
TRACKED_PERMS = ("read", "write", "create", "submit", "cancel", "delete", "report", "export")

CAPABILITY_CACHE_KEY = "role_advisor:capability_index"
CATALOG_CACHE_KEY = "role_advisor:transaction_catalog"
CACHE_TTL_SECONDS = 10 * 60

STATUS_COVERED = "Covered"
STATUS_FIT_FOUND = "Fit Found"
STATUS_GAP_NEW_ROLE = "Gap - New Role Needed"
STATUS_GAP_NEW_PROFILE = "Gap - New Profile Needed"


# ---------------------------------------------------------------------------
# Capability index
# ---------------------------------------------------------------------------


def _perm_rows_for_roles(roles: list[str]) -> list[dict]:
	"""Return effective permission rows for `roles`, honouring Custom DocPerm.

	This is a batched form of `frappe.permissions.get_all_perms`, which does the
	same three queries but for a single role at a time. On a site with a few
	hundred roles the per-role version costs hundreds of round trips every time
	the index is rebuilt, which is exactly the scan we are trying to keep cheap.

	The override rule is taken verbatim from core (see `get_all_perms` in
	frappe/permissions.py): Custom DocPerm overrides are applied **per doctype,
	not per role**. If any Custom DocPerm row exists for a doctype, the standard
	DocPerm rows for that doctype are discarded for every role. The parity of
	this function with core is asserted by a test, so a change in core surfaces
	as a test failure rather than as silently wrong advice.
	"""
	if not roles:
		return []

	standard = frappe.get_all("DocPerm", fields="*", filters={"role": ("in", roles)})
	custom = frappe.get_all("Custom DocPerm", fields="*", filters={"role": ("in", roles)})

	overridden = set(get_doctypes_with_custom_docperms())
	effective = list(custom)
	effective.extend(row for row in standard if row.parent not in overridden)

	return effective


def _capabilities_from_rows(rows: list[dict]) -> dict[str, dict[str, set[str]]]:
	"""Fold permission rows into {role: {doctype: {perm, ...}}}."""
	capabilities: dict[str, dict[str, set[str]]] = {}

	for row in rows:
		# Only permlevel 0 grants act on the document itself. A permlevel 1
		# `write` row grants access to a field group, not the ability to write
		# the document, so treating it as a grant would report false coverage.
		if cint(row.get("permlevel")):
			continue

		# `if_owner` restricts the grant to documents the user created. It cannot
		# be relied on to authorise a transaction against an arbitrary record, so
		# it is not counted. Erring this way suggests a profile the user may not
		# strictly need, rather than wrongly reporting them as already covered.
		if cint(row.get("if_owner")):
			continue

		granted = {perm for perm in TRACKED_PERMS if cint(row.get(perm))}
		if not granted:
			continue

		by_doctype = capabilities.setdefault(row.get("role"), {})
		by_doctype.setdefault(row.get("parent"), set()).update(granted)

	return capabilities


def _roles_by_role_profile() -> dict[str, list[str]]:
	"""Return {role_profile: [role, ...]} in one query."""
	rows = frappe.get_all(
		"Has Role",
		filters={"parenttype": "Role Profile"},
		fields=["parent", "role"],
	)

	profiles: dict[str, list[str]] = {
		name: [] for name in frappe.get_all("Role Profile", pluck="name")
	}
	for row in rows:
		# A profile row can outlive its profile in edge cases; ignore orphans.
		if row.parent in profiles:
			profiles[row.parent].append(row.role)

	return profiles


def _compute_capability_index() -> dict[str, dict[str, set[str]]]:
	profile_roles = _roles_by_role_profile()

	all_roles = sorted({role for roles in profile_roles.values() for role in roles})
	role_capabilities = _capabilities_from_rows(_perm_rows_for_roles(all_roles))

	index: dict[str, dict[str, set[str]]] = {}
	for profile, roles in profile_roles.items():
		merged: dict[str, set[str]] = {}
		for role in roles:
			for doctype, perms in role_capabilities.get(role, {}).items():
				merged.setdefault(doctype, set()).update(perms)
		index[profile] = merged

	return index


def build_capability_index(force: bool = False) -> dict[str, dict[str, set[str]]]:
	"""Return {role_profile: {doctype: {perm, ...}}} for every Role Profile.

	Cached for ten minutes. The index is derived state, never stored as a
	doctype, so a stale entry costs at most one over-broad suggestion that the
	admin still has to approve by hand.
	"""
	if not force:
		# `expires=True` is required for any key written with `expires_in_sec`:
		# without it the value is also copied into frappe.local.cache, which has
		# no TTL and would serve a stale index for the rest of the request.
		cached = frappe.cache().get_value(CAPABILITY_CACHE_KEY, expires=True)
		if cached is not None:
			# Sets survive the cache round trip via pickle, but rebuild them
			# defensively so a cache written by an older version cannot leak
			# lists into set arithmetic below.
			return {
				profile: {doctype: set(perms) for doctype, perms in caps.items()}
				for profile, caps in cached.items()
			}

	index = _compute_capability_index()
	frappe.cache().set_value(CAPABILITY_CACHE_KEY, index, expires_in_sec=CACHE_TTL_SECONDS)

	return index


def clear_capability_index() -> None:
	"""Drop the cached index and catalogue payload."""
	frappe.cache().delete_value([CAPABILITY_CACHE_KEY, CATALOG_CACHE_KEY])


def on_permission_source_change(doc=None, method=None) -> None:
	"""doc_events hook: invalidate the index when its inputs change.

	Wired in hooks.py for Role Profile, Custom DocPerm and DocPerm. Without this
	the index would serve up to ten minutes of stale advice after an admin edits
	a profile - long enough to suggest a profile that no longer fits.
	"""
	clear_capability_index()


def site_wide_role_capabilities() -> dict[str, set[str]]:
	"""Union of what *every* role on the site can do, profile-bundled or not.

	Used only to tell the two Gap kinds apart, so it is computed on demand
	rather than cached with the index.
	"""
	roles = frappe.get_all("Role", pluck="name")
	role_capabilities = _capabilities_from_rows(_perm_rows_for_roles(roles))

	union: dict[str, set[str]] = {}
	for caps in role_capabilities.values():
		for doctype, perms in caps.items():
			union.setdefault(doctype, set()).update(perms)

	return union


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _covers(capabilities: dict[str, set[str]], doctype: str, perm: str) -> bool:
	return perm in capabilities.get(doctype, ())


def _total_perm_count(capabilities: dict[str, set[str]]) -> int:
	return sum(len(perms) for perms in capabilities.values())


def _format_pairs(pairs) -> str:
	"""Render (doctype, perm) pairs as 'DocType: perm, perm; DocType: perm'."""
	grouped: dict[str, set[str]] = {}
	for doctype, perm in pairs:
		grouped.setdefault(doctype, set()).add(perm)

	return "; ".join(
		f"{doctype}: {', '.join(sorted(grouped[doctype]))}" for doctype in sorted(grouped)
	)


def get_user_role_profiles(user: str) -> list[str]:
	"""Return every Role Profile assigned to `user`, in child-table order.

	`User.role_profile_name` is deprecated in v16 - `User.populate_role_profile_roles`
	moves it into the `role_profiles` child table and nulls it, keeping it only as
	a mirror of `role_profiles[0]` for list-view display. A v16 user can hold
	several profiles, and their effective access is the union of all of them, so
	coverage has to be judged against the whole set.
	"""
	profiles = frappe.get_all(
		"User Role Profile",
		filters={"parent": user, "parenttype": "User"},
		fields=["role_profile"],
		order_by="idx asc",
		pluck="role_profile",
	)
	if profiles:
		return profiles

	# Fall back to the deprecated field for rows written before the migration.
	legacy = frappe.db.get_value("User", user, "role_profile_name")

	return [legacy] if legacy else []


def set_user_role_profiles(user: Document, profiles: list[str]) -> None:
	"""Replace a user's role profiles, defusing the deprecated mirror field.

	`User.sync_role_profile_name` persists `role_profile_name` as a mirror of
	`role_profiles[0]` on every save. On the *next* save, if that stale value is
	no longer among the new profiles, `User.move_role_profile_name_to_role_profiles`
	appends it back as an extra profile - silently turning a replace into an
	append, and emitting a deprecation warning as it does so.

	Clearing the mirror first is what makes a replacement actually replace. Any
	code writing `role_profiles` on an already-saved User needs this.
	"""
	user.set("role_profiles", [{"role_profile": profile} for profile in profiles])
	user.role_profile_name = None


def get_requirements(transaction_names: list[str]) -> list[dict]:
	"""Resolve catalogue names to ordered, de-duplicated requirements."""
	if not transaction_names:
		frappe.throw(_("Select at least one transaction."), title=_("Nothing Requested"))

	rows = frappe.get_all(
		"Transaction Catalog",
		filters={"name": ("in", transaction_names)},
		fields=["name", "reference_doctype", "required_perm"],
	)
	by_name = {row.name: row for row in rows}

	if missing := [name for name in transaction_names if name not in by_name]:
		frappe.throw(
			_("Unknown Transaction Catalog entries: {0}").format(", ".join(missing)),
			frappe.DoesNotExistError,
		)

	requirements: list[dict] = []
	seen: set[tuple[str, str]] = set()
	for name in transaction_names:
		row = by_name[name]
		pair = (row.reference_doctype, row.required_perm)
		if pair in seen:
			# Two catalogue entries can reduce to the same (doctype, perm); keep
			# the first so the requirement set stays minimal.
			continue
		seen.add(pair)
		requirements.append(
			{"transaction": name, "doctype": row.reference_doctype, "perm": row.required_perm}
		)

	return requirements


# ---------------------------------------------------------------------------
# Resolver
# ---------------------------------------------------------------------------


def _select_tightest_fit(candidates: dict[str, dict[str, set[str]]]) -> str:
	"""Pick the least over-granting profile among those that cover the request.

	This is the anti-redundancy rule. Every candidate already satisfies the whole
	requirement set, so they differ only in what else they hand over. Ranking by
	total permission count therefore picks the profile with the least authority
	beyond the ask - the smallest blast radius if the account is compromised.

	Ties break on fewer distinct doctypes (narrower surface for the same number
	of rights), then on profile name so the choice is stable across runs. The
	name tiebreak matters: without it two equally tight profiles would be picked
	arbitrarily by dict order and the suggestion would flap between resolves.
	"""
	return min(
		candidates,
		key=lambda profile: (
			_total_perm_count(candidates[profile]),
			len(candidates[profile]),
			profile,
		),
	)


def resolve_transactions(user: str, transaction_names: list[str]) -> dict:
	"""Resolve an access request and log the outcome.

	Returns a dict with `status`, `current_profile`, `current_profiles`,
	`suggested_profile`, `extra_perms`, `unmet_requirements` and
	`access_request_log`.
	"""
	if not frappe.db.exists("User", user):
		frappe.throw(_("User {0} does not exist.").format(user), frappe.DoesNotExistError)

	requirements = get_requirements(transaction_names)
	required_pairs = {(req["doctype"], req["perm"]) for req in requirements}

	index = build_capability_index()
	current_profiles = get_user_role_profiles(user)

	# Effective current access is the union across every assigned profile.
	current_caps: dict[str, set[str]] = {}
	for profile in current_profiles:
		for doctype, perms in index.get(profile, {}).items():
			current_caps.setdefault(doctype, set()).update(perms)

	uncovered = [req for req in requirements if not _covers(current_caps, req["doctype"], req["perm"])]

	if not uncovered:
		result = {
			"status": STATUS_COVERED,
			"suggested_profile": None,
			"extra_perms": [],
			"extra_perms_summary": "",
			"unmet_requirements": [],
		}
	else:
		candidates = {
			profile: caps
			for profile, caps in index.items()
			if all(_covers(caps, doctype, perm) for doctype, perm in required_pairs)
		}

		if candidates:
			suggested = _select_tightest_fit(candidates)
			extra_pairs = sorted(
				(doctype, perm)
				for doctype, perms in candidates[suggested].items()
				for perm in perms
				if (doctype, perm) not in required_pairs
			)
			result = {
				"status": STATUS_FIT_FOUND,
				"suggested_profile": suggested,
				"extra_perms": [{"doctype": dt, "perm": perm} for dt, perm in extra_pairs],
				"extra_perms_summary": _format_pairs(extra_pairs),
				"unmet_requirements": [],
			}
		else:
			result = _describe_gap(requirements, index)

	log = _log_request(user, transaction_names, current_profiles, result)

	return {
		"user": user,
		"current_profile": current_profiles[0] if current_profiles else None,
		"current_profiles": current_profiles,
		"access_request_log": log.name,
		**result,
	}


def _describe_gap(requirements: list[dict], index: dict[str, dict[str, set[str]]]) -> dict:
	"""Classify a gap and list what cannot be satisfied.

	No single profile covers the whole request. Two very different fixes follow,
	and the Access Request Log distinguishes them:

	* some required (doctype, perm) is granted by no Role anywhere on the site -
	  a Role has to be created or extended first  -> Gap - New Role Needed
	* every requirement is granted by some Role, but no one profile bundles them
	  all - only a new Role Profile is needed     -> Gap - New Profile Needed

	The second is a far cheaper administrative action, which is why it is worth
	telling them apart rather than reporting a single undifferentiated "Gap".
	"""
	profile_union: dict[str, set[str]] = {}
	for caps in index.values():
		for doctype, perms in caps.items():
			profile_union.setdefault(doctype, set()).update(perms)

	role_union = site_wide_role_capabilities()

	unmet = []
	needs_new_role = False
	for req in requirements:
		if _covers(profile_union, req["doctype"], req["perm"]):
			continue

		granted_by_role = _covers(role_union, req["doctype"], req["perm"])
		needs_new_role = needs_new_role or not granted_by_role
		unmet.append(
			{
				"transaction": req["transaction"],
				"doctype": req["doctype"],
				"perm": req["perm"],
				# False means no Role grants this at all, so a Role must be
				# created or extended. True means a Role has it but no profile
				# bundles it with the rest of the request.
				"granted_by_any_role": granted_by_role,
			}
		)

	return {
		"status": STATUS_GAP_NEW_ROLE if needs_new_role else STATUS_GAP_NEW_PROFILE,
		"suggested_profile": None,
		"extra_perms": [],
		"extra_perms_summary": "",
		"unmet_requirements": unmet,
	}


def _log_request(
	user: str, transaction_names: list[str], current_profiles: list[str], result: dict
) -> Document:
	"""Write the audit trail row. Every outcome is logged, including Covered."""
	log = frappe.new_doc("Access Request Log")
	log.user = user
	log.current_role_profile = current_profiles[0] if current_profiles else None
	log.current_role_profiles = ", ".join(current_profiles)
	log.resolution_status = result["status"]
	log.suggested_role_profile = result["suggested_profile"]
	log.extra_perms_granted = result["extra_perms_summary"]
	log.unmet_requirements = _format_pairs(
		(req["doctype"], req["perm"]) for req in result["unmet_requirements"]
	)

	for name in transaction_names:
		log.append("requested_transactions", {"transaction": name})

	# The log is a system-written audit record: a requester who is allowed to ask
	# the question must not need write access to the trail that records it.
	log.insert(ignore_permissions=True)

	return log


# ---------------------------------------------------------------------------
# Whitelisted endpoints
# ---------------------------------------------------------------------------


@frappe.whitelist()
def get_transaction_catalog() -> list[dict]:
	"""Return the catalogue for the console's picker.

	Read via `frappe.get_all`, which does not check permissions: the catalogue is
	a list of transaction labels, and a requester needs to see it in order to ask
	for access without also being granted read on the doctype itself.
	"""
	# Note the deliberate absence of `generator=`: frappe.cache().get_value only
	# invokes the generator when `expires` is False (see RedisWrapper.get_value),
	# so pairing the two would return None forever on a cold cache.
	cached = frappe.cache().get_value(CATALOG_CACHE_KEY, expires=True)
	if cached is not None:
		return cached

	catalog = frappe.get_all(
		"Transaction Catalog",
		fields=["name", "transaction_name", "reference_doctype", "required_perm", "module", "keywords"],
		order_by="module asc, transaction_name asc",
	)
	frappe.cache().set_value(CATALOG_CACHE_KEY, catalog, expires_in_sec=CACHE_TTL_SECONDS)

	return catalog


@frappe.whitelist()
def resolve_access(user: str, transaction_names) -> dict:
	"""Resolve an access request. Returns the resolution and logs it."""
	# frappe.call sends arrays as a JSON string.
	transaction_names = frappe.parse_json(transaction_names) or []
	if isinstance(transaction_names, str):
		transaction_names = [transaction_names]

	return resolve_transactions(user, list(transaction_names))


@frappe.whitelist()
def apply_suggestion(access_request_log_name: str, decision_notes: str | None = None) -> dict:
	"""Assign the suggested profile to the user. System Manager only."""
	frappe.only_for("System Manager")

	log = frappe.get_doc("Access Request Log", access_request_log_name)

	if log.resolution_status != STATUS_FIT_FOUND or not log.suggested_role_profile:
		frappe.throw(
			_("{0} has no suggested role profile to apply (status: {1}).").format(
				log.name, log.resolution_status or _("not resolved")
			),
			title=_("Nothing to Apply"),
		)

	if log.decided_by:
		frappe.throw(
			_("{0} was already decided by {1}.").format(log.name, log.decided_by),
			title=_("Already Decided"),
		)

	user = frappe.get_doc("User", log.user)
	previous = [row.role_profile for row in user.role_profiles]

	# Replace rather than append. The point of the exercise is minimum
	# redundancy: leaving the previous, broader profile in place would keep every
	# grant the tighter profile was chosen to avoid. This must go through
	# set_user_role_profiles - assigning role_profiles directly lets User's
	# deprecated role_profile_name mirror resurrect the profile we just dropped.
	set_user_role_profiles(user, [log.suggested_role_profile])
	# `role_profiles` sits at permlevel 1 on User. Authorisation for this call is
	# the frappe.only_for gate above, so the permlevel check is bypassed here
	# rather than requiring the caller to also hold permlevel-1 write on User.
	user.save(ignore_permissions=True)

	note = _("Applied {0}, replacing: {1}").format(
		log.suggested_role_profile, ", ".join(previous) if previous else _("no previous profile")
	)
	if decision_notes:
		note = f"{decision_notes}\n{note}"

	log.decided_by = frappe.session.user
	log.decision_notes = note
	log.save(ignore_permissions=True)

	return {
		"applied": True,
		"user": log.user,
		"role_profile": log.suggested_role_profile,
		"replaced_profiles": previous,
		"decision_notes": note,
	}
