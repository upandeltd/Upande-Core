# Copyright (c) 2026, ghost-mann and contributors
# For license information, please see license.txt

"""Seed the Designation Access Map from what users already hold.

Everything here records *observed* state. Kaitet's existing assignments were
made without consistent regard to designation, company or branch - an Irrigator
holds an Approver profile, three Task Workers hold `scout`, and two users carry
a company that contradicts their email domain. So the seeder's output is a
hypothesis for review, and only unambiguous rows are activated.
"""

import frappe

from upande_core import mapping, settings
from upande_core.upande_core.doctype.designation_access_map.designation_access_map import (
	CONFIDENCE_HIGH,
	CONFIDENCE_LOW,
	CONFIDENCE_MEDIUM,
)

# Share of peers that must agree before a split counts as agreement. 29 of 31
# is consensus; 4 of 7 is a genuine disagreement needing a human.
HIGH_AGREEMENT_RATIO = 0.8

# Peers needed before a candidate is credible enough to compete on tightness.
# Without this floor, tightest-wins lets one stray assignment beat 29 peers.
MATERIAL_SUPPORT = 2


def observe_assignments() -> dict[tuple, dict[str, int]]:
	"""Return {(designation, *scope_values): {role_profile: peer_count}}.

	Counts only enabled System Users with an active Employee, a designation and
	at least one role profile - the users who can actually evidence a mapping.
	"""
	dimensions = settings.scope_dimensions()
	columns = ", ".join(f"e.`{d}` as `{d}`" for d in dimensions)
	group_by = ", ".join(f"e.`{d}`" for d in dimensions)

	rows = frappe.db.sql(
		f"""
		select e.designation as designation,
		       {columns},
		       urp.role_profile as role_profile,
		       count(distinct u.name) as peers
		from `tabUser` u
		join `tabEmployee` e on e.user_id = u.name and e.status = 'Active'
		join `tabUser Role Profile` urp
		     on urp.parent = u.name and urp.parenttype = 'User'
		where u.enabled = 1
		  and u.user_type = 'System User'
		  and ifnull(e.designation, '') != ''
		group by e.designation, {group_by}, urp.role_profile
		""",
		as_dict=True,
	)

	observed: dict[tuple, dict[str, int]] = {}
	for row in rows:
		key = (row["designation"], *(row.get(d) or None for d in dimensions))
		observed.setdefault(key, {})[row["role_profile"]] = row["peers"]

	return observed


def classify(counts: dict[str, int]) -> dict | None:
	"""Judge one (designation, scope) combination.

	Returns the proposed profile, a confidence tier, and whether a human must
	rule on it before it can drive assignment.
	"""
	if not counts:
		return None

	total = sum(counts.values())
	# Sort by peer count desc, then name, so the majority pick is deterministic.
	ordered = sorted(counts.items(), key=lambda pair: (-pair[1], pair[0]))
	majority, top_count = ordered[0]

	supported = [profile for profile, count in ordered if count >= MATERIAL_SUPPORT]
	if not supported:
		supported = [profile for profile, _count in ordered]

	tightest = mapping.tie_break(supported) or majority

	ratio = top_count / total
	if len(counts) == 1 or ratio >= HIGH_AGREEMENT_RATIO:
		if top_count >= settings.min_peers_high_confidence():
			confidence = CONFIDENCE_HIGH
		elif top_count >= MATERIAL_SUPPORT:
			confidence = CONFIDENCE_MEDIUM
		else:
			confidence = CONFIDENCE_LOW
	elif total >= MATERIAL_SUPPORT:
		confidence = CONFIDENCE_MEDIUM
	else:
		confidence = CONFIDENCE_LOW

	# Disagreement between the popular choice and the least-privilege choice is
	# exactly where a human is needed, whatever the confidence tier says.
	disagrees = majority != tightest
	flagged = confidence != CONFIDENCE_HIGH or disagrees

	evidence = [f"{count} of {total} peers hold {profile}" for profile, count in ordered]
	if disagrees:
		evidence.append(
			f"majority is {majority} but {tightest} grants less - review before activating"
		)

	return {
		# Tightest wins per settings, but the row is flagged so a human rules on it.
		"profile": tightest,
		"majority": majority,
		"tightest": tightest,
		"confidence": confidence,
		"flagged": flagged,
		"evidence": ". ".join(evidence) + ".",
	}


def seed(dry_run: bool = True) -> list[dict]:
	"""Propose (and optionally write) map rows. Idempotent.

	`seed_mode = "Author from intent"` returns nothing: on a project where the
	existing data should not be trusted at all, an empty map is the correct
	starting point.
	"""
	if settings.seed_mode() != "Seed from existing users":
		return []

	dimensions = settings.scope_dimensions()
	proposals = []

	for key, counts in observe_assignments().items():
		designation, scope_values = key[0], key[1:]
		verdict = classify(counts)
		if not verdict:
			continue

		scope = dict(zip(dimensions, scope_values, strict=True))

		# A branch-scoped row needs a company; skip rows the doctype would
		# reject rather than raising mid-seed.
		if scope.get("branch") and not scope.get("company"):
			continue

		row = {settings.map_fieldname(d): scope.get(d) for d in dimensions}
		proposal = {
			"designation": designation,
			**row,
			"role_profile": verdict["profile"],
			"confidence": verdict["confidence"],
			"evidence": verdict["evidence"],
			"is_active": 0 if verdict["flagged"] else 1,
		}
		proposals.append(proposal)

		if dry_run:
			continue

		if mapping.resolve(designation, scope, active_only=False):
			continue

		frappe.get_doc(
			{
				"doctype": "Designation Access Map",
				"source": "Seeded from existing users",
				**proposal,
			}
		).insert(ignore_permissions=True)

	return proposals
