# Copyright (c) 2026, ghost-mann and contributors
# For license information, please see license.txt

"""Bring a local bench's users into line with a remote site, for testing.

The local bench is a restore that drifts from production the moment it is taken.
This pulls the current user list across so tests and demos run against real
numbers rather than a stale snapshot.

    export KAITET_HOST=https://kaitet-group.upande.com
    export KAITET_TOKEN=api_key:api_secret
    bench --site <site> execute upande_core.live_sync.run            # dry run
    bench --site <site> execute upande_core.live_sync.run --kwargs "{'apply': True}"

Only ever touches User: creation, `enabled`, `user_type`, names, module profile
and role profile. It never writes roles directly - those derive from the profile
- and never touches passwords, API keys or Employee records.

The remote may be v15, where a user's profile lives in `role_profile_name`.
Locally on v16 it lives in the `role_profiles` child table, so the value is
mapped across rather than copied.
"""

import frappe

from upande_core import capability, live_export

# Never created or modified by a sync: framework-owned accounts.
PROTECTED = frozenset({"Administrator", "Guest"})


def _local_users() -> dict[str, dict]:
	rows = frappe.get_all(
		"User",
		fields=["name", "enabled", "user_type", "full_name", "module_profile"],
		limit_page_length=0,
	)
	local = {row["name"]: row for row in rows}

	for row in frappe.get_all(
		"User Role Profile", filters={"parenttype": "User"}, fields=["parent", "role_profile"]
	):
		local.setdefault(row["parent"], {}).setdefault("profiles", []).append(
			row["role_profile"]
		)

	return local


def plan() -> dict:
	"""Compare remote against local and describe the work. Writes nothing."""
	remote = {row["user"]: row for row in live_export.collect()}
	local = _local_users()

	known_profiles = set(frappe.get_all("Role Profile", pluck="name"))
	known_module_profiles = set(frappe.get_all("Module Profile", pluck="name"))

	create, update, missing_profiles = [], [], set()

	for name, row in remote.items():
		if name in PROTECTED:
			continue

		profile = row["role_profile_name"]
		# A profile that exists remotely but not here cannot be assigned; the
		# user is still worth creating, so record the gap and carry on.
		if profile and profile not in known_profiles:
			missing_profiles.add(profile)
			profile = ""

		module_profile = row["module_profile"]
		if module_profile and module_profile not in known_module_profiles:
			module_profile = ""

		desired = {
			"enabled": int(row["enabled"]),
			"user_type": row["user_type"] or "System User",
			"full_name": row["full_name"],
			"profile": profile,
			"module_profile": module_profile,
		}

		if name not in local:
			create.append({"user": name, **desired})
			continue

		current = local[name]
		changes = {}
		if int(current.get("enabled") or 0) != desired["enabled"]:
			changes["enabled"] = desired["enabled"]
		if (current.get("user_type") or "") != desired["user_type"]:
			changes["user_type"] = desired["user_type"]
		if (current.get("module_profile") or "") != desired["module_profile"]:
			changes["module_profile"] = desired["module_profile"]

		current_profiles = current.get("profiles") or []
		wanted = [desired["profile"]] if desired["profile"] else []
		if sorted(current_profiles) != sorted(wanted):
			changes["profile"] = desired["profile"]

		if changes:
			update.append({"user": name, **changes})

	# Users here but not there: reported, never deleted. A sync that removes
	# accounts is a sync that can destroy data on a bad fetch.
	extra = sorted(set(local) - set(remote) - PROTECTED)

	return {
		"remote_total": len(remote),
		"local_total": len(local),
		"create": create,
		"update": update,
		"extra_local": extra,
		"missing_profiles": sorted(missing_profiles),
	}


def _apply_user(row: dict, creating: bool) -> None:
	if creating:
		doc = frappe.new_doc("User")
		doc.email = row["user"]
		doc.first_name = row.get("full_name") or row["user"].split("@")[0]
		# No welcome mail: this is a test bench full of real addresses.
		doc.flags.no_welcome_mail = True
		doc.send_welcome_email = 0
	else:
		doc = frappe.get_doc("User", row["user"])

	for field in ("enabled", "user_type", "module_profile"):
		if field in row:
			doc.set(field, row[field])

	if "profile" in row:
		profiles = [row["profile"]] if row["profile"] else []
		capability.set_user_role_profiles(doc, profiles)

	# A user with no desk role is demoted to Website User by core on save, so
	# user_type is re-asserted afterwards rather than fought with here.
	doc.flags.ignore_permissions = True
	doc.save(ignore_permissions=True)


def run(apply: bool = False, limit: int | None = None) -> dict:
	"""Report the plan, and optionally carry it out."""
	work = plan()

	print(f"remote {work['remote_total']} users / local {work['local_total']}")
	print(f"  to create: {len(work['create'])}")
	print(f"  to update: {len(work['update'])}")
	print(f"  local-only (reported, never deleted): {len(work['extra_local'])}")
	if work["missing_profiles"]:
		print(f"  role profiles missing locally: {', '.join(work['missing_profiles'])}")

	if not apply:
		for row in work["create"][:5]:
			print(f"    + {row['user']} ({row['profile'] or 'no profile'})")
		for row in work["update"][:5]:
			print(f"    ~ {row['user']} {  {k: v for k, v in row.items() if k != 'user'} }")
		print("dry run - nothing written. Pass apply=True to write.")
		return work

	created = updated = failed = 0
	for row in work["create"][:limit] if limit else work["create"]:
		try:
			_apply_user(row, creating=True)
			created += 1
		except Exception as error:
			failed += 1
			print(f"    ! create {row['user']}: {error}")

	for row in work["update"][:limit] if limit else work["update"]:
		try:
			_apply_user(row, creating=False)
			updated += 1
		except Exception as error:
			failed += 1
			print(f"    ! update {row['user']}: {error}")

	frappe.db.commit()
	capability.clear_capability_index()
	print(f"created {created}, updated {updated}, failed {failed}")
	print(f"local users now: {frappe.db.count('User')}")

	return work
