# Copyright (c) 2026, ghost-mann and contributors
# For license information, please see license.txt

"""Add access on top of what someone already has.

Assigning a role profile in v16 *replaces* the holder's roles. That is usually
right - it is what keeps a profile a reviewable statement about a job rather
than an accumulating pile - but it is wrong in one common case: somebody who
already does their job needs one more thing, and taking away the rest to give
it to them is absurd.

So there are two answers to "grant this", and the administrator picks:

  replace  - `api.assign_access`. They end up holding exactly the profile that
             covers the ask, and lose anything it does not cover.
  add      - this module. Their existing roles, plus the smallest set of roles
             that covers the ask, bundled into one profile and assigned. They
             lose nothing.

The addition is roles, not a whole second profile. A profile is a bundle chosen
for a job; borrowing another job's bundle to get at one permission inside it
hands over everything else in the bundle too. `requests._roles_that_cover`
already computes the minimal covering set, and that is what gets added.

Two things this module is careful about.

An identical profile is reused rather than recreated. Without that, granting the
same thing to five people would manufacture five byte-identical profiles - which
the anomaly scan would then correctly report as a problem this app caused.

A delegate cannot compose freely. Their allowlist is the whole of their
authority; letting them assemble a profile from arbitrary roles would make it
decorative. They may compose only from roles that already appear in profiles
they may grant, and only when a System Manager has switched it on.
"""

import frappe
from frappe import _
from frappe.utils import cint

from upande_core import api, audit, capability, delegation, privilege, requests, settings

# A composed name longer than this is unreadable in a list view, so past it the
# added roles are counted rather than named.
MAX_NAME = 120

# Role Profile.name is a Data field; Frappe's limit is 140.
NAME_LIMIT = 140


def _roles_of(profiles) -> set[str]:
	"""Every role the given profiles carry, as one set."""
	if not profiles:
		return set()

	return set(
		frappe.get_all(
			"Has Role",
			filters={"parent": ("in", list(profiles)), "parenttype": "Role Profile"},
			pluck="role",
		)
	)


def _grantable_roles(admin) -> set[str]:
	"""The roles a delegate may assemble from: those inside their allowlist.

	The union of the profiles they may already grant. It is a real widening -
	they can now grant A and B together where before it was A or B - but it is
	bounded by the allowlist, so a System Manager who reviews the allowlist has
	reviewed this too.
	"""
	allowed = [row.role_profile for row in admin.get("allowed_role_profiles") or []]

	return _roles_of(allowed)


def propose_name(held: list[str], added: list[str]) -> str:
	"""A name that says what the profile is, and stays the same next time.

	Deterministic on purpose: the same composition produces the same name, so a
	second attempt finds the first one instead of making a near-duplicate.
	"""
	base = ", ".join(sorted(held)) or _("No profile")
	if len(added) == 1:
		suffix = added[0]
	else:
		suffix = " + ".join(sorted(added))

	name = f"{base} + {suffix}"
	if len(name) > MAX_NAME:
		name = f"{base} + {len(added)} roles"

	return name[:NAME_LIMIT]


def find_equivalent(roles: set[str]) -> str | None:
	"""An existing Role Profile carrying exactly `roles`, if there is one.

	Exactly, not a superset: a superset would grant more than was asked for and
	silently defeat the point of computing a minimal addition.
	"""
	if not roles:
		return None

	rows = frappe.get_all(
		"Has Role", filters={"parenttype": "Role Profile"}, fields=["parent", "role"]
	)

	by_profile: dict[str, set[str]] = {}
	for row in rows:
		by_profile.setdefault(row["parent"], set()).add(row["role"])

	for profile in sorted(by_profile):
		if by_profile[profile] == roles:
			return profile

	return None


def _unique_name(name: str) -> str:
	"""`name`, or the first free `name (2)`, `name (3)`, …

	Reached only when a *different* profile already holds the obvious name -
	`find_equivalent` has already ruled out one that would do.
	"""
	if not frappe.db.exists("Role Profile", name):
		return name

	for n in range(2, 50):
		suffix = f" ({n})"
		candidate = name[: NAME_LIMIT - len(suffix)] + suffix
		if not frappe.db.exists("Role Profile", candidate):
			return candidate

	frappe.throw(_("Could not find a free name for the composed profile."))


def _plan(user: str, requirements) -> dict:
	"""Work out what the composed profile would be. No writes, no gating."""
	wanted = requests._clean(requirements)
	held = capability.get_user_role_profiles(user)
	held_roles = _roles_of(held)

	index = capability.build_capability_index()
	current: dict[str, set[str]] = {}
	for profile in held:
		for doctype, rights in index.get(profile, {}).items():
			current.setdefault(doctype, set()).update(rights)

	missing = requests._uncovered(current, wanted)
	added = sorted(requests._roles_that_cover(missing)) if missing else []

	roles_after = held_roles | set(added)
	existing = find_equivalent(roles_after)

	return {
		"user": user,
		"requirements": wanted,
		"holds": held,
		"held_roles": sorted(held_roles),
		"missing": [f"{row['document_type']}: {row['right']}" for row in missing],
		"added_roles": added,
		"roles_after": sorted(roles_after),
		"reuses": existing,
		"name": existing or propose_name(held, added),
		"already_covered": not missing,
	}


def _privileged_in(roles) -> dict[str, set[str]]:
	"""Privileged grants a role set would carry, without needing a profile first.

	`privilege.privileged_grants` reads the capability index, which is keyed by
	profile - and the composed profile does not exist yet. Same rule, applied to
	roles.
	"""
	granted = capability.capabilities_of_roles(roles)
	privileged = set(settings.privileged_doctypes())

	found: dict[str, set[str]] = {}
	for doctype, perms in granted.items():
		if doctype not in privileged:
			continue
		offending = perms & privilege.WRITE_EQUIVALENT
		if offending:
			found[doctype] = offending

	return found


def _refuse_reason(admin, plan: dict) -> str | None:
	"""Why this composition may not go ahead, or None."""
	if plan["already_covered"]:
		return _("{0} already covers every one of these. Nothing to add.").format(
			", ".join(plan["holds"]) or _("Their current access")
		)

	if not plan["added_roles"]:
		return _(
			"No role on this site grants {0}, so there is nothing to add. A role "
			"has to be created or extended first."
		).format(", ".join(plan["missing"]))

	if admin is None:
		return None

	if not settings.allow_delegate_compose():
		return _(
			"Composing a new profile is switched off for delegated administrators. "
			"A System Manager can enable it in Access Settings."
		)

	outside = sorted(set(plan["added_roles"]) - _grantable_roles(admin))
	if outside:
		return _(
			"This would need {0}, which is not in any profile you may grant."
		).format(", ".join(outside))

	return None


@frappe.whitelist()
def preview(user: str, requirements) -> dict:
	"""What adding to their access would produce, and whether it is allowed."""
	admin = delegation.acting_admin()
	delegation.assert_target(admin, user)

	plan = _plan(user, requirements)
	index = capability.build_capability_index()

	before_caps: dict[str, set[str]] = {}
	for profile in plan["holds"]:
		for doctype, rights in index.get(profile, {}).items():
			before_caps.setdefault(doctype, set()).update(rights)

	after_caps = (
		index.get(plan["reuses"], {})
		if plan["reuses"]
		else capability.capabilities_of_roles(plan["roles_after"])
	)

	privileged = _privileged_in(plan["roles_after"])
	refusal = _refuse_reason(admin, plan)

	return {
		**plan,
		"doctypes_before": len(before_caps),
		"doctypes_after": len(after_caps),
		"grants_before": capability.total_perm_count(before_caps),
		"grants_after": capability.total_perm_count(after_caps),
		"roles_before": len(plan["held_roles"]),
		# Additive by construction: nothing they hold today is taken away. Worth
		# saying explicitly, because the replace path does take things away and
		# that is the surprise this option exists to avoid.
		"roles_lost": [],
		"privileged": privilege.describe(privileged) if privileged else None,
		"allowed": refusal is None,
		"refusal": refusal,
	}


@frappe.whitelist()
def apply(user: str, requirements, note: str = "", confirm_privileged=0) -> dict:
	"""Create (or reuse) the composed profile and assign it.

	The write goes through `api.write_assignment`, the same one `assign_access`
	uses, so a composed grant lands in the assignment log looking like any other
	- with the composition recorded in the note.
	"""
	admin = delegation.acting_admin()
	delegation.assert_target(admin, user)

	plan = _plan(user, requirements)

	refusal = _refuse_reason(admin, plan)
	if refusal:
		frappe.throw(refusal, frappe.PermissionError, title=_("Cannot Add"))

	privileged = _privileged_in(plan["roles_after"])
	if privileged:
		if admin is not None:
			# Unreachable via `_refuse_reason` today, since a delegate's roles all
			# come from allowlisted profiles which are themselves non-privileged.
			# Kept because that is an invariant of another module, not this one.
			frappe.throw(
				_("The result would grant {0}, which cannot be delegated.").format(
					privilege.describe(privileged)
				),
				frappe.PermissionError,
				title=_("Privileged Result"),
			)
		if not cint(confirm_privileged):
			frappe.throw(
				_(
					"The result would grant {0}. Confirm that you mean to hand over "
					"the ability to change permissions."
				).format(privilege.describe(privileged)),
				frappe.ValidationError,
				title=_("Confirm Privileged Grant"),
			)

	profile = plan["reuses"] or _create(plan)

	asked = ", ".join(
		f"{row['document_type']}: {row['right']}" for row in plan["requirements"]
	)
	trail = _("Added {0} to {1}. Asked for: {2}.").format(
		", ".join(plan["added_roles"]),
		", ".join(plan["holds"]) or _("no profile"),
		asked,
	)
	if plan["reuses"]:
		trail += " " + _("Reused the existing profile {0}.").format(plan["reuses"])
	if note:
		trail += " " + note.strip()

	result = api.write_assignment(
		user, profile, trigger=audit.TRIGGER_MANUAL, notes=trail[:1000]
	)

	# The same verification the replace path does: whether they can now actually
	# do what was asked, not merely whether a profile was assigned.
	after: dict[str, set[str]] = {}
	fresh = capability.build_capability_index()
	for held in capability.get_user_role_profiles(user):
		for doctype, rights in fresh.get(held, {}).items():
			after.setdefault(doctype, set()).update(rights)

	still = requests._uncovered(after, plan["requirements"])

	return {
		**result,
		"composed": profile,
		"created": not plan["reuses"],
		"added_roles": plan["added_roles"],
		"covered": not still,
		"still_missing": [f"{row['document_type']}: {row['right']}" for row in still],
	}


def _create(plan: dict) -> str:
	"""Insert the composed Role Profile."""
	doc = frappe.get_doc(
		{
			"doctype": "Role Profile",
			"role_profile": _unique_name(plan["name"]),
			"roles": [{"role": role} for role in plan["roles_after"]],
		}
	)
	doc.insert(ignore_permissions=True)

	# The index is keyed by profile and has just gained one.
	capability.clear_capability_index()

	return doc.name
