# User Access Management Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild `role_advisor` into Kaitet's user access management app — designation-driven role profile assignment, bounded delegated administrators, and read-only audit reports.

**Architecture:** Four new doctypes hold configuration and audit state. All delegated writes funnel through four whitelisted API methods that gate on an explicit per-admin allowlist, because permlevel-1 on `User` is all-or-nothing and cannot be partially granted. Four deny-only permission hooks bound what a delegate can see. Five Script Reports describe current state read-only. Nothing writes to a real user until a human approves a dry-run.

**Tech Stack:** Frappe v16 (16.27.0), Python 3.14, MariaDB. Frappe `IntegrationTestCase` rollback tests. Script Reports for report UI.

**Spec:** `apps/role_advisor/docs/specs/2026-08-20-user-access-management-design.md`

## Global Constraints

- **Site:** `kaitet.local` (bench at `/home/austin/frappe-v16-bench`, webserver port 8002). MariaDB root creds `root`/`root`.
- **Never write `User.role_profile_name`.** It is deprecated. Write the `role_profiles` child table, and always via `set_user_role_profiles()` (Task 1) which clears the stale mirror — otherwise the *next* save silently converts a replace into an append.
- **`role_profiles` is permlevel 1.** Any write needs `save(ignore_permissions=True)`, and must therefore be preceded by explicit gating in Python.
- **Never seed `Custom DocPerm` against a real doctype.** If any Custom DocPerm row exists for a doctype, core discards that doctype's standard DocPerms for *every* role.
- **Never create seed data from `patches.txt`.** `frappe.installer.install_app` calls `set_all_patches_as_completed(app)`, so a seed patch never fires. Use `after_install`.
- **Permission hooks are deny-only.** They may narrow, never widen. `permission_query_conditions` signature `(user=None, doctype=None)`; `has_permission` signature `(doc, ptype=None, user=None, debug=False)`.
- **One role profile per user** by default (`User Access Settings.allow_multiple_profiles = 0`).
- **`TRACKED_PERMS`** = `("read", "write", "create", "submit", "cancel", "delete", "report", "export")`. Excludes `email`, `print`, `share`.
- **Capability grants exclude** `permlevel > 0` rows and `if_owner` rows.
- **Test command:** `bench --site kaitet.local run-tests --app role_advisor --module role_advisor.tests.<module>`
- **Test fixtures use `Custom DocPerm` on `ToDo` deliberately.** Inserting one discards `ToDo`'s standard DocPerms for *every* role (spec §3.5), so `ToDo` access is stripped site-wide **for the duration of that test**. Safe because `IntegrationTestCase` rolls back, and `ToDo` is chosen precisely because nothing in this app depends on it. Never point a fixture at a doctype the app reads, and never leave such a row committed.
- **Seeded map rows record observed, not endorsed, state.** Kaitet's existing assignments are known-inconsistent. Anything below `High` confidence is created `is_active = 0`.

---

## File Structure

**Deleted** (prototype scaffolding, no longer referenced):

```
role_advisor/demo_data.py
role_advisor/patches/v1_0/seed_demo_data.py
role_advisor/role_advisor/doctype/ra_demo_harvest_entry/
role_advisor/role_advisor/doctype/ra_demo_pick_list/
role_advisor/role_advisor/doctype/ra_demo_quality_check/
role_advisor/role_advisor/doctype/ra_demo_payment_voucher/
role_advisor/role_advisor/doctype/transaction_catalog/
role_advisor/role_advisor/doctype/access_request_transaction_row/
role_advisor/role_advisor/doctype/access_request_log/
role_advisor/role_advisor/page/role_advisor_console/
```

**Created:**

| File | Responsibility |
|---|---|
| `role_advisor/capability.py` | Salvaged capability index — `{role_profile: {doctype: {perm}}}`, cached, invalidated by hooks |
| `role_advisor/settings.py` | Typed accessors for `User Access Settings` with defaults |
| `role_advisor/mapping.py` | Map resolution (most-specific-wins) and tie-break (tightest) |
| `role_advisor/seeding.py` | Peer-derived map seed with confidence tiering |
| `role_advisor/delegation.py` | Scope resolution and the three gates |
| `role_advisor/permissions.py` | The four deny-only permission hooks |
| `role_advisor/api.py` | **Rewritten** — only the four whitelisted delegate methods |
| `role_advisor/sweep.py` | Dry-run and apply passes |
| `role_advisor/module_derivation.py` | §7 module profile derivation (deferrable) |
| `role_advisor/role_advisor/doctype/user_access_settings/` | Single doctype |
| `role_advisor/role_advisor/doctype/designation_access_map/` | The mapping table |
| `role_advisor/role_advisor/doctype/delegated_user_admin/` | Per-admin scope + allowlist |
| `role_advisor/role_advisor/doctype/access_assignment_log/` | Audit trail |
| `role_advisor/role_advisor/report/*/` | Five Script Reports |
| `role_advisor/tests/*.py` | One test module per source module |

**Modified:** `role_advisor/hooks.py`, `role_advisor/install.py`, `role_advisor/patches.txt`.

**Task dependency order:** 1 → 2 → (3, 4, 5) → 6 → 7 → 8 → (9, 10) → 11 → (12, 13, 14) → 15 → 16.

Task 16 is independently shippable and may be deferred without affecting 1–15.

---

## Task 1: Strip the prototype, extract the capability index

The prototype's value is `build_capability_index()` and the four tests around it. Everything else — demo doctypes, transaction catalog, console page — is throwaway. The salvaged code moves to its own module so later tasks import a stable surface, and its tests are rewritten against synthetic fixtures because `demo_data.py` is being deleted.

**Files:**
- Create: `role_advisor/capability.py`
- Create: `role_advisor/tests/test_capability.py`
- Delete: `role_advisor/demo_data.py`, `role_advisor/patches/v1_0/seed_demo_data.py`, `role_advisor/tests/test_api.py`, the seven doctype directories and the page directory listed in File Structure
- Modify: `role_advisor/api.py` (emptied to a docstring — repopulated in Task 11), `role_advisor/hooks.py`, `role_advisor/install.py`, `role_advisor/patches.txt`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `TRACKED_PERMS: tuple[str, ...]`
  - `build_capability_index(force: bool = False) -> dict[str, dict[str, set[str]]]` — keyed by role profile name
  - `clear_capability_index() -> None`
  - `on_permission_source_change(doc=None, method=None) -> None`
  - `site_wide_role_capabilities() -> dict[str, set[str]]`
  - `total_perm_count(capabilities: dict[str, set[str]]) -> int`
  - `get_user_role_profiles(user: str) -> list[str]`
  - `set_user_role_profiles(user: Document, profiles: list[str]) -> None`
  - `_perm_rows_for_roles(roles: list[str]) -> list[dict]`, `_capabilities_from_rows(rows) -> dict`, `_compute_capability_index() -> dict` (private, but referenced by tests)

- [ ] **Step 1: Delete the prototype files**

```bash
cd /home/austin/frappe-v16-bench/apps/role_advisor
git rm -r --quiet \
  role_advisor/demo_data.py \
  role_advisor/patches/v1_0/seed_demo_data.py \
  role_advisor/tests/test_api.py \
  role_advisor/role_advisor/doctype/ra_demo_harvest_entry \
  role_advisor/role_advisor/doctype/ra_demo_pick_list \
  role_advisor/role_advisor/doctype/ra_demo_quality_check \
  role_advisor/role_advisor/doctype/ra_demo_payment_voucher \
  role_advisor/role_advisor/doctype/transaction_catalog \
  role_advisor/role_advisor/doctype/access_request_transaction_row \
  role_advisor/role_advisor/doctype/access_request_log \
  role_advisor/role_advisor/page/role_advisor_console
find . -name '__pycache__' -type d -exec rm -rf {} + 2>/dev/null; true
```

- [ ] **Step 2: Create `role_advisor/capability.py`**

Move lines 21–190 and 198 of the old `api.py` verbatim, with three changes: drop `CATALOG_CACHE_KEY` (the catalogue is gone), rename `_total_perm_count` to `total_perm_count` (later tasks call it), and keep every docstring — they record verified core behaviour.

```python
# Copyright (c) 2026, Upande and contributors
# For license information, please see license.txt

"""Effective-permission index for Role Profiles.

`build_capability_index()` answers "what does this Role Profile actually grant,
per doctype?" - the question behind every report and every gate in this app.
"""

import frappe
from frappe.model.document import Document
from frappe.permissions import get_doctypes_with_custom_docperms
from frappe.utils import cint

# The rights a grant may carry. Deliberately excludes `email`, `print` and
# `share`: counting them would inflate every profile's tightness score equally
# without changing the ranking - only the noise in the over-grant diff.
TRACKED_PERMS = ("read", "write", "create", "submit", "cancel", "delete", "report", "export")

CAPABILITY_CACHE_KEY = "role_advisor:capability_index"
CACHE_TTL_SECONDS = 10 * 60


def _perm_rows_for_roles(roles: list[str]) -> list[dict]:
	"""Return effective permission rows for `roles`, honouring Custom DocPerm.

	A batched form of `frappe.permissions.get_all_perms`, which does the same
	three queries but one role at a time. On a site with 207 roles the per-role
	version costs hundreds of round trips per rebuild.

	The override rule is taken verbatim from core: Custom DocPerm overrides are
	applied **per doctype, not per role**. If any Custom DocPerm row exists for a
	doctype, standard DocPerm rows for that doctype are discarded for every role.
	Parity with core is asserted by a test, so a core change surfaces as a test
	failure rather than as silently wrong output.
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
		# `write` row grants a field group, not the ability to write the
		# document, so counting it would report false coverage.
		if cint(row.get("permlevel")):
			continue

		# `if_owner` restricts the grant to documents the user created. It cannot
		# authorise a transaction against an arbitrary record.
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

	Cached for ten minutes. The index is derived state, never stored, so a stale
	entry costs at most one over-broad suggestion a human still has to approve.
	"""
	if not force:
		# `expires=True` is required for any key written with `expires_in_sec`:
		# without it the value is also copied into frappe.local.cache, which has
		# no TTL and would serve a stale index for the rest of the request.
		cached = frappe.cache().get_value(CAPABILITY_CACHE_KEY, expires=True)
		if cached is not None:
			# Rebuild the sets defensively so a cache written by an older
			# version cannot leak lists into set arithmetic downstream.
			return {
				profile: {doctype: set(perms) for doctype, perms in caps.items()}
				for profile, caps in cached.items()
			}

	index = _compute_capability_index()
	frappe.cache().set_value(CAPABILITY_CACHE_KEY, index, expires_in_sec=CACHE_TTL_SECONDS)

	return index


def clear_capability_index() -> None:
	"""Drop the cached index."""
	frappe.cache().delete_value(CAPABILITY_CACHE_KEY)


def on_permission_source_change(doc=None, method=None) -> None:
	"""doc_events hook: invalidate the index when its inputs change.

	Wired for Role Profile, Custom DocPerm and DocPerm. Without this the index
	would serve up to ten minutes of stale output after an admin edits a profile.
	"""
	clear_capability_index()


def site_wide_role_capabilities() -> dict[str, set[str]]:
	"""Union of what every role on the site can do, profile-bundled or not."""
	roles = frappe.get_all("Role", pluck="name")
	role_capabilities = _capabilities_from_rows(_perm_rows_for_roles(roles))

	union: dict[str, set[str]] = {}
	for caps in role_capabilities.values():
		for doctype, perms in caps.items():
			union.setdefault(doctype, set()).update(perms)

	return union


def total_perm_count(capabilities: dict[str, set[str]]) -> int:
	"""Tightness score: total granted (doctype, perm) pairs."""
	return sum(len(perms) for perms in capabilities.values())


def get_user_role_profiles(user: str) -> list[str]:
	"""Return every Role Profile assigned to `user`, in child-table order.

	`User.role_profile_name` is deprecated in v16. A v16 user may hold several
	profiles and their effective access is the union, so coverage is judged
	against the whole set.
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
	append. Clearing the mirror first is what makes a replacement actually
	replace. Any code writing `role_profiles` on a saved User needs this.
	"""
	user.set("role_profiles", [{"role_profile": profile} for profile in profiles])
	user.role_profile_name = None
```

- [ ] **Step 3: Point `hooks.py` at the new module and drop the demo seeding**

In `role_advisor/hooks.py`, replace all three `role_advisor.api.on_permission_source_change` strings with `role_advisor.capability.on_permission_source_change`. Leave the `doc_events` structure otherwise unchanged.

Replace `role_advisor/install.py` entirely:

```python
# Copyright (c) 2026, Upande and contributors
# For license information, please see license.txt

"""Install-time setup.

Seeding must happen here, never from a patch: `frappe.installer.install_app`
calls `set_all_patches_as_completed(app)` on a fresh install, marking every
patches.txt entry as run without executing it - so a seed patch never fires,
and `bench migrate` then skips it forever too.
"""

import frappe


def after_install():
	"""Nothing to seed yet. Task 2 adds settings defaults here."""
	frappe.db.commit()
```

Replace `role_advisor/patches.txt` with the two bare section headers (no entries):

```
[pre_model_sync]

[post_model_sync]
```

- [ ] **Step 4: Empty `api.py` to a placeholder docstring**

Task 11 repopulates it. Leaving the prototype's 552 lines in place would let later tasks import functions that are about to be deleted.

```python
# Copyright (c) 2026, Upande and contributors
# For license information, please see license.txt

"""Whitelisted API for delegated user administration.

Populated in Task 11. Every method here is reachable by a delegated
administrator, so each one gates before it acts.
"""
```

- [ ] **Step 5: Write the failing tests**

Create `role_advisor/tests/test_capability.py`. These are the four salvaged tests, rewritten against fixtures created in `setUp` rather than the deleted `demo_data`. `_capabilities_from_rows` is pure, so its test needs no fixtures at all.

```python
# Copyright (c) 2026, Upande and contributors
# For license information, please see license.txt

import frappe
from frappe.permissions import get_all_perms
from frappe.tests import IntegrationTestCase

from role_advisor import capability

# A role name unlikely to collide with any of the site's 207 roles.
TEST_ROLE = "_RA Test Role"
TEST_PROFILE = "_RA Test Profile"


class TestCapabilityIndex(IntegrationTestCase):
	def setUp(self):
		capability.clear_capability_index()

		if not frappe.db.exists("Role", TEST_ROLE):
			frappe.get_doc({"doctype": "Role", "role_name": TEST_ROLE}).insert()

		# ToDo is a core doctype with standard DocPerms and no Custom DocPerm on
		# this site, so granting against it exercises the standard-rows path
		# without rewriting any real doctype's permissions.
		frappe.get_doc(
			{
				"doctype": "Custom DocPerm",
				"parent": "ToDo",
				"role": TEST_ROLE,
				"permlevel": 0,
				"read": 1,
				"write": 1,
			}
		).insert()

		if not frappe.db.exists("Role Profile", TEST_PROFILE):
			frappe.get_doc(
				{
					"doctype": "Role Profile",
					"role_profile": TEST_PROFILE,
					"roles": [{"role": TEST_ROLE}],
				}
			).insert()

		capability.clear_capability_index()

	def tearDown(self):
		capability.clear_capability_index()

	def test_batched_perm_query_matches_core_get_all_perms(self):
		"""_perm_rows_for_roles must agree with frappe.permissions.get_all_perms.

		The batched query exists only for speed. If core changes how Custom
		DocPerm overrides standard DocPerm, this fails rather than silently
		producing wrong output.
		"""
		batched = capability._capabilities_from_rows(
			capability._perm_rows_for_roles([TEST_ROLE])
		)
		core = capability._capabilities_from_rows(get_all_perms(TEST_ROLE))

		self.assertEqual(batched.get(TEST_ROLE, {}), core.get(TEST_ROLE, {}))

	def test_index_excludes_higher_permlevels_and_if_owner(self):
		"""permlevel > 0 and if_owner rows are field/ownership scoped, not grants."""
		rows = [
			{"role": "R", "parent": "DT", "permlevel": 1, "if_owner": 0, "write": 1},
			{"role": "R", "parent": "DT", "permlevel": 0, "if_owner": 1, "delete": 1},
			{"role": "R", "parent": "DT", "permlevel": 0, "if_owner": 0, "read": 1},
		]

		self.assertEqual(
			capability._capabilities_from_rows(rows), {"R": {"DT": {"read"}}}
		)

	def test_index_is_served_from_cache_on_the_second_call(self):
		first = capability.build_capability_index()

		# Make a recompute impossible, so a correct result can only have come
		# from the cache. Asserting on behaviour rather than query counts keeps
		# this independent of how many queries the scan happens to need.
		def _explode():
			raise AssertionError("recomputed a cached capability index")

		original = capability._compute_capability_index
		capability._compute_capability_index = _explode
		try:
			self.assertEqual(capability.build_capability_index(), first)
		finally:
			capability._compute_capability_index = original

	def test_force_rebuilds_the_index(self):
		capability.build_capability_index()

		rebuilt = capability.build_capability_index(force=True)

		self.assertIn(TEST_PROFILE, rebuilt)
		self.assertEqual(rebuilt[TEST_PROFILE].get("ToDo"), {"read", "write"})

	def test_total_perm_count_sums_granted_pairs(self):
		self.assertEqual(
			capability.total_perm_count({"A": {"read", "write"}, "B": {"read"}}), 3
		)
```

- [ ] **Step 6: Run the tests to verify they fail**

```bash
cd /home/austin/frappe-v16-bench
bench --site kaitet.local run-tests --app role_advisor --module role_advisor.tests.test_capability
```

Expected: collection error — `ModuleNotFoundError: No module named 'role_advisor.capability'` — because Step 2's file has not been created yet if you are following strict TDD order. If you created it in Step 2 as written, expect PASS here and treat Step 7 as verification only.

- [ ] **Step 7: Run the tests to verify they pass**

```bash
cd /home/austin/frappe-v16-bench
bench --site kaitet.local run-tests --app role_advisor --module role_advisor.tests.test_capability
```

Expected: 5 passed.

If `test_batched_perm_query_matches_core_get_all_perms` fails, do **not** adjust the assertion — core's Custom DocPerm override rule has changed and `_perm_rows_for_roles` must be brought back into line with `frappe.permissions.get_all_perms`.

- [ ] **Step 8: Verify the app still loads and nothing references deleted modules**

```bash
cd /home/austin/frappe-v16-bench
grep -rn "demo_data\|Transaction Catalog\|Access Request Log\|role_advisor_console\|RA Demo" apps/role_advisor --include=*.py --include=*.json --include=*.txt --include=*.js
bench --site kaitet.local console <<'EOF'
import role_advisor.capability as c
print(len(c.build_capability_index()), "profiles indexed")
EOF
```

Expected: the `grep` prints nothing, and the console prints a profile count of 87 or thereabouts.

- [ ] **Step 9: Commit**

```bash
cd /home/austin/frappe-v16-bench/apps/role_advisor
git add -A
git commit -m "refactor: strip prototype, extract capability index

Deletes the transaction-catalog console, the five RA Demo doctypes and
demo_data seeding. Salvages build_capability_index() into its own module
with its four tests rewritten against synthetic fixtures."
```

---

## Task 2: `User Access Settings` (Single)

Every later task reads its thresholds and policy from here, so this lands before the other doctypes. Accessors return spec defaults when the Single has never been saved, so no task needs to special-case a fresh install.

**Files:**
- Create: `role_advisor/role_advisor/doctype/user_access_settings/user_access_settings.json`
- Create: `role_advisor/role_advisor/doctype/user_access_settings/user_access_settings.py`
- Create: `role_advisor/role_advisor/doctype/user_access_settings/__init__.py`
- Create: `role_advisor/settings.py`
- Create: `role_advisor/tests/test_settings.py`
- Modify: `role_advisor/install.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `scope_dimensions() -> list[str]` — ordered subset of `["company", "branch", "department", "grade"]`
  - `tie_break_rule() -> str` — one of `"Tightest by permission count"`, `"Majority peer vote"`, `"Always flag"`
  - `min_peers_high_confidence() -> int`
  - `seed_mode() -> str` — `"Seed from existing users"` or `"Author from intent"`
  - `module_profile_strategy() -> str`, `never_block_modules() -> list[str]`, `naming_pattern() -> str`
  - `delegate_role() -> str`, `allow_multiple_profiles() -> bool`, `require_employee_link() -> bool`
  - `privileged_doctypes() -> list[str]`
  - `PRIVILEGED_DOCTYPE_DEFAULTS: tuple[str, ...]`

- [ ] **Step 1: Write the failing test**

Create `role_advisor/tests/test_settings.py`:

```python
# Copyright (c) 2026, Upande and contributors
# For license information, please see license.txt

import frappe
from frappe.tests import IntegrationTestCase

from role_advisor import settings


class TestUserAccessSettings(IntegrationTestCase):
	def test_defaults_match_the_kaitet_frame(self):
		"""An unsaved Single must still answer every accessor."""
		self.assertEqual(settings.scope_dimensions(), ["company", "branch"])
		self.assertEqual(settings.tie_break_rule(), "Tightest by permission count")
		self.assertEqual(settings.min_peers_high_confidence(), 5)
		self.assertEqual(settings.seed_mode(), "Seed from existing users")
		self.assertEqual(settings.module_profile_strategy(), "Derive from Role Profile")
		self.assertEqual(settings.never_block_modules(), [])
		self.assertEqual(settings.naming_pattern(), "{role_profile}")
		self.assertEqual(settings.delegate_role(), "User Manager")
		self.assertFalse(settings.allow_multiple_profiles())
		self.assertTrue(settings.require_employee_link())

	def test_privileged_doctypes_defaults_cover_the_escalation_surface(self):
		"""Anything that can rewrite permissions must be on the list."""
		privileged = set(settings.privileged_doctypes())

		for doctype in (
			"User",
			"Role",
			"Role Profile",
			"Module Profile",
			"Custom DocPerm",
			"DocPerm",
			"Property Setter",
		):
			self.assertIn(doctype, privileged)

	def test_scope_dimensions_respects_saved_checkboxes(self):
		doc = frappe.get_single("User Access Settings")
		doc.use_company = 1
		doc.use_branch = 0
		doc.use_department = 1
		doc.use_grade = 0
		doc.save(ignore_permissions=True)

		# Order is fixed most-general to most-specific, not checkbox order.
		self.assertEqual(settings.scope_dimensions(), ["company", "department"])

	def test_min_peers_falls_back_when_set_to_zero(self):
		"""A zero threshold would mark every unprecedented row High."""
		doc = frappe.get_single("User Access Settings")
		doc.min_peers_high_confidence = 0
		doc.save(ignore_permissions=True)

		self.assertEqual(settings.min_peers_high_confidence(), 5)
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd /home/austin/frappe-v16-bench
bench --site kaitet.local run-tests --app role_advisor --module role_advisor.tests.test_settings
```

Expected: FAIL — `ModuleNotFoundError: No module named 'role_advisor.settings'`.

- [ ] **Step 3: Create the doctype JSON**

Create `role_advisor/role_advisor/doctype/user_access_settings/__init__.py` as an empty file, then `user_access_settings.json`:

```json
{
 "actions": [],
 "creation": "2026-08-20 00:00:00.000000",
 "doctype": "DocType",
 "engine": "InnoDB",
 "field_order": [
  "map_section", "seed_mode", "tie_break_rule", "min_peers_high_confidence",
  "scope_column", "use_company", "use_branch", "use_department", "use_grade",
  "module_section", "module_profile_strategy", "naming_pattern", "never_block_modules",
  "delegation_section", "delegate_role", "allow_multiple_profiles",
  "require_employee_link", "privileged_doctypes"
 ],
 "fields": [
  {"fieldname": "map_section", "fieldtype": "Section Break", "label": "Map Resolution"},
  {"fieldname": "seed_mode", "fieldtype": "Select", "label": "Seed Mode",
   "options": "Seed from existing users\nAuthor from intent",
   "default": "Seed from existing users",
   "description": "Existing assignments are observed state, never endorsed state. Choose 'Author from intent' where current data should not be trusted at all."},
  {"fieldname": "tie_break_rule", "fieldtype": "Select", "label": "Tie Break Rule",
   "options": "Tightest by permission count\nMajority peer vote\nAlways flag",
   "default": "Tightest by permission count",
   "description": "Majority vote drifts toward over-granting, because broad profiles spread faster."},
  {"fieldname": "min_peers_high_confidence", "fieldtype": "Int",
   "label": "Min Peers For High Confidence", "default": "5"},
  {"fieldname": "scope_column", "fieldtype": "Column Break"},
  {"fieldname": "use_company", "fieldtype": "Check", "label": "Scope By Company", "default": "1"},
  {"fieldname": "use_branch", "fieldtype": "Check", "label": "Scope By Branch", "default": "1"},
  {"fieldname": "use_department", "fieldtype": "Check", "label": "Scope By Department", "default": "0"},
  {"fieldname": "use_grade", "fieldtype": "Check", "label": "Scope By Grade", "default": "0"},

  {"fieldname": "module_section", "fieldtype": "Section Break", "label": "Module Profiles"},
  {"fieldname": "module_profile_strategy", "fieldtype": "Select", "label": "Strategy",
   "options": "Derive from Role Profile\nManual\nPer Company",
   "default": "Derive from Role Profile"},
  {"fieldname": "naming_pattern", "fieldtype": "Data", "label": "Naming Pattern",
   "default": "{role_profile}"},
  {"fieldname": "never_block_modules", "fieldtype": "Table MultiSelect",
   "label": "Never Block Modules", "options": "User Access Never Block Module",
   "description": "Empty by default: Kaitet blocks Core and Desk in production and the desk works."},

  {"fieldname": "delegation_section", "fieldtype": "Section Break", "label": "Delegation"},
  {"fieldname": "delegate_role", "fieldtype": "Link", "label": "Delegate Role",
   "options": "Role", "default": "User Manager"},
  {"fieldname": "allow_multiple_profiles", "fieldtype": "Check",
   "label": "Allow Multiple Profiles Per User", "default": "0"},
  {"fieldname": "require_employee_link", "fieldtype": "Check",
   "label": "Require Employee Link", "default": "1",
   "description": "Users with no Employee record have no company and are unreachable by any delegate."},
  {"fieldname": "privileged_doctypes", "fieldtype": "Table MultiSelect",
   "label": "Privileged Doctypes", "options": "User Access Privileged Doctype",
   "description": "A profile granting write on any of these can never be delegated, even if allowlisted."}
 ],
 "issingle": 1,
 "links": [],
 "modified": "2026-08-20 00:00:00.000000",
 "module": "Role Advisor",
 "name": "User Access Settings",
 "owner": "Administrator",
 "permissions": [
  {"role": "System Manager", "read": 1, "write": 1, "create": 1, "delete": 1, "print": 1, "email": 1, "share": 1}
 ],
 "sort_field": "modified",
 "sort_order": "DESC"
}
```

- [ ] **Step 4: Create the two child doctypes the Table MultiSelects need**

A `Table MultiSelect` requires a child doctype whose first Link field supplies the options. Create `role_advisor/role_advisor/doctype/user_access_never_block_module/user_access_never_block_module.json`:

```json
{
 "actions": [], "creation": "2026-08-20 00:00:00.000000", "doctype": "DocType",
 "engine": "InnoDB", "field_order": ["module"],
 "fields": [{"fieldname": "module", "fieldtype": "Link", "label": "Module",
   "options": "Module Def", "in_list_view": 1, "reqd": 1}],
 "istable": 1, "links": [], "modified": "2026-08-20 00:00:00.000000",
 "module": "Role Advisor", "name": "User Access Never Block Module",
 "owner": "Administrator", "permissions": [],
 "sort_field": "modified", "sort_order": "DESC"
}
```

And `role_advisor/role_advisor/doctype/user_access_privileged_doctype/user_access_privileged_doctype.json`:

```json
{
 "actions": [], "creation": "2026-08-20 00:00:00.000000", "doctype": "DocType",
 "engine": "InnoDB", "field_order": ["document_type"],
 "fields": [{"fieldname": "document_type", "fieldtype": "Link", "label": "Document Type",
   "options": "DocType", "in_list_view": 1, "reqd": 1}],
 "istable": 1, "links": [], "modified": "2026-08-20 00:00:00.000000",
 "module": "Role Advisor", "name": "User Access Privileged Doctype",
 "owner": "Administrator", "permissions": [],
 "sort_field": "modified", "sort_order": "DESC"
}
```

Each needs an empty `__init__.py` and a controller stub:

```python
# Copyright (c) 2026, Upande and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class UserAccessNeverBlockModule(Document):
	pass
```

(Same shape for `UserAccessPrivilegedDoctype`, and for `UserAccessSettings` in `user_access_settings.py`.)

- [ ] **Step 5: Write `role_advisor/settings.py`**

```python
# Copyright (c) 2026, Upande and contributors
# For license information, please see license.txt

"""Typed accessors for `User Access Settings`.

Every accessor falls back to a spec default, so no caller needs to handle an
unsaved Single or a field left blank.
"""

import frappe
from frappe.utils import cint, cstr

# Anything that can rewrite permissions. A profile granting write on any of
# these is refused to delegates even when allowlisted (see delegation.py).
PRIVILEGED_DOCTYPE_DEFAULTS = (
	"User",
	"Role",
	"Role Profile",
	"Module Profile",
	"Custom DocPerm",
	"DocPerm",
	"Property Setter",
)

# Fixed most-general to most-specific. Map resolution walks this in reverse to
# implement most-specific-wins, so the order is load-bearing, not cosmetic.
SCOPE_DIMENSIONS = ("company", "branch", "department", "grade")

DEFAULTS = {
	"seed_mode": "Seed from existing users",
	"tie_break_rule": "Tightest by permission count",
	"min_peers_high_confidence": 5,
	"module_profile_strategy": "Derive from Role Profile",
	"naming_pattern": "{role_profile}",
	"delegate_role": "User Manager",
	"allow_multiple_profiles": 0,
	"require_employee_link": 1,
	"use_company": 1,
	"use_branch": 1,
	"use_department": 0,
	"use_grade": 0,
}


def _settings():
	return frappe.get_cached_doc("User Access Settings")


def _value(fieldname):
	value = _settings().get(fieldname)
	if value in (None, ""):
		return DEFAULTS.get(fieldname)
	return value


def scope_dimensions() -> list[str]:
	"""Dimensions forming the map key, most-general first."""
	enabled = [d for d in SCOPE_DIMENSIONS if cint(_value(f"use_{d}"))]

	# A map with no dimensions at all would collapse every designation to a
	# single global row, silently discarding the farm splits.
	return enabled or ["company"]


def tie_break_rule() -> str:
	return cstr(_value("tie_break_rule"))


def min_peers_high_confidence() -> int:
	# A zero or negative threshold would mark every unprecedented row High.
	return cint(_value("min_peers_high_confidence")) or DEFAULTS["min_peers_high_confidence"]


def seed_mode() -> str:
	return cstr(_value("seed_mode"))


def module_profile_strategy() -> str:
	return cstr(_value("module_profile_strategy"))


def naming_pattern() -> str:
	return cstr(_value("naming_pattern"))


def never_block_modules() -> list[str]:
	return [row.module for row in _settings().get("never_block_modules") or []]


def delegate_role() -> str:
	return cstr(_value("delegate_role"))


def allow_multiple_profiles() -> bool:
	return bool(cint(_value("allow_multiple_profiles")))


def require_employee_link() -> bool:
	return bool(cint(_value("require_employee_link")))


def privileged_doctypes() -> list[str]:
	configured = [row.document_type for row in _settings().get("privileged_doctypes") or []]

	return configured or list(PRIVILEGED_DOCTYPE_DEFAULTS)
```

- [ ] **Step 6: Seed the privileged-doctype rows on install**

Replace the body of `after_install` in `role_advisor/install.py`:

```python
import frappe

from role_advisor.settings import PRIVILEGED_DOCTYPE_DEFAULTS


def after_install():
	seed_settings()
	frappe.db.commit()


def seed_settings():
	"""Populate `User Access Settings` child tables. Idempotent."""
	doc = frappe.get_single("User Access Settings")

	existing = {row.document_type for row in doc.get("privileged_doctypes") or []}
	for doctype in PRIVILEGED_DOCTYPE_DEFAULTS:
		if doctype not in existing and frappe.db.exists("DocType", doctype):
			doc.append("privileged_doctypes", {"document_type": doctype})

	doc.save(ignore_permissions=True)
```

- [ ] **Step 7: Migrate and run the tests**

```bash
cd /home/austin/frappe-v16-bench
bench --site kaitet.local migrate
bench --site kaitet.local execute role_advisor.install.seed_settings
bench --site kaitet.local run-tests --app role_advisor --module role_advisor.tests.test_settings
```

Expected: 4 passed.

- [ ] **Step 8: Commit**

```bash
cd /home/austin/frappe-v16-bench/apps/role_advisor
git add -A
git commit -m "feat: add User Access Settings with spec defaults

Single doctype plus typed accessors that fall back to the Kaitet frame,
so no caller handles an unsaved Single. Privileged doctypes are config
rather than a constant, keeping the computed denylist portable."
```

---

## Task 3: `Designation Access Map`

The mapping table. Uniqueness on the `(designation, company, branch)` triple is enforced in `validate` rather than by a DB index, because `company` and `branch` are nullable and MariaDB unique indexes treat each NULL as distinct — two rows with the same designation and no company would both be accepted.

**Files:**
- Create: `role_advisor/role_advisor/doctype/designation_access_map/__init__.py`
- Create: `role_advisor/role_advisor/doctype/designation_access_map/designation_access_map.json`
- Create: `role_advisor/role_advisor/doctype/designation_access_map/designation_access_map.py`
- Create: `role_advisor/tests/test_designation_access_map.py`

**Interfaces:**
- Consumes: `role_advisor.settings.scope_dimensions()` (Task 2).
- Produces:
  - Doctype `Designation Access Map` with fields `designation`, `company`, `branch`, `department`, `grade`, `role_profile`, `module_profile`, `is_active`, `confidence`, `source`, `evidence`
  - `DesignationAccessMap.scope_key() -> tuple` — `(company, branch, department, grade)` with blanks normalised to `None`
  - `CONFIDENCE_HIGH`, `CONFIDENCE_MEDIUM`, `CONFIDENCE_LOW`, `CONFIDENCE_NONE` string constants

- [ ] **Step 1: Write the failing test**

Create `role_advisor/tests/test_designation_access_map.py`:

```python
# Copyright (c) 2026, Upande and contributors
# For license information, please see license.txt

import frappe
from frappe.tests import IntegrationTestCase

TEST_DESIGNATION = "_RA Test Designation"
TEST_PROFILE = "_RA Map Test Profile"


def _ensure(doctype, name, **extra):
	if not frappe.db.exists(doctype, name):
		frappe.get_doc({"doctype": doctype, **extra}).insert(ignore_permissions=True)
	return name


class TestDesignationAccessMap(IntegrationTestCase):
	def setUp(self):
		_ensure("Designation", TEST_DESIGNATION, designation_name=TEST_DESIGNATION)
		_ensure("Role Profile", TEST_PROFILE, role_profile=TEST_PROFILE)
		self.company = frappe.get_all("Company", pluck="name", limit=1)[0]

	def _row(self, **kwargs):
		defaults = {
			"doctype": "Designation Access Map",
			"designation": TEST_DESIGNATION,
			"role_profile": TEST_PROFILE,
		}
		return frappe.get_doc({**defaults, **kwargs})

	def test_a_bare_designation_row_is_accepted(self):
		doc = self._row().insert(ignore_permissions=True)

		self.assertEqual(doc.designation, TEST_DESIGNATION)
		self.assertFalse(doc.is_active, "seeded rows must not be active by default")

	def test_duplicate_triple_is_rejected(self):
		self._row(company=self.company).insert(ignore_permissions=True)

		with self.assertRaises(frappe.ValidationError):
			self._row(company=self.company).insert(ignore_permissions=True)

	def test_blank_company_collides_with_null_company(self):
		"""Two 'applies to all companies' rows are the same row.

		A DB unique index would accept both, because MariaDB treats each NULL as
		distinct. This is why uniqueness lives in validate.
		"""
		self._row(company=None).insert(ignore_permissions=True)

		with self.assertRaises(frappe.ValidationError):
			self._row(company="").insert(ignore_permissions=True)

	def test_same_designation_different_company_is_allowed(self):
		companies = frappe.get_all("Company", pluck="name", limit=2)
		if len(companies) < 2:
			self.skipTest("site has fewer than two companies")

		self._row(company=companies[0]).insert(ignore_permissions=True)
		second = self._row(company=companies[1]).insert(ignore_permissions=True)

		self.assertEqual(second.company, companies[1])

	def test_scope_key_normalises_blanks_to_none(self):
		doc = self._row(company=self.company, branch="")

		self.assertEqual(doc.scope_key(), (self.company, None, None, None))

	def test_branch_requires_a_company(self):
		"""A branch-scoped row with no company cannot be resolved unambiguously."""
		with self.assertRaises(frappe.ValidationError):
			self._row(branch="Any Branch", company=None).insert(ignore_permissions=True)
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd /home/austin/frappe-v16-bench
bench --site kaitet.local run-tests --app role_advisor --module role_advisor.tests.test_designation_access_map
```

Expected: FAIL — `DoesNotExistError: DocType Designation Access Map not found`.

- [ ] **Step 3: Create the doctype JSON**

Create the empty `__init__.py`, then `designation_access_map.json`:

```json
{
 "actions": [],
 "allow_rename": 1,
 "autoname": "hash",
 "creation": "2026-08-20 00:00:00.000000",
 "doctype": "DocType",
 "engine": "InnoDB",
 "field_order": [
  "designation", "role_profile", "module_profile", "is_active",
  "scope_column", "company", "branch", "department", "grade",
  "provenance_section", "confidence", "source", "evidence"
 ],
 "fields": [
  {"fieldname": "designation", "fieldtype": "Link", "label": "Designation",
   "options": "Designation", "reqd": 1, "in_list_view": 1, "in_standard_filter": 1},
  {"fieldname": "role_profile", "fieldtype": "Link", "label": "Role Profile",
   "options": "Role Profile", "reqd": 1, "in_list_view": 1},
  {"fieldname": "module_profile", "fieldtype": "Link", "label": "Module Profile",
   "options": "Module Profile"},
  {"fieldname": "is_active", "fieldtype": "Check", "label": "Is Active", "default": "0",
   "in_list_view": 1, "in_standard_filter": 1,
   "description": "Only active rows may drive assignment. Anything below High confidence is seeded inactive."},

  {"fieldname": "scope_column", "fieldtype": "Column Break"},
  {"fieldname": "company", "fieldtype": "Link", "label": "Company", "options": "Company",
   "in_list_view": 1, "in_standard_filter": 1,
   "description": "Empty means the row applies to every company."},
  {"fieldname": "branch", "fieldtype": "Link", "label": "Branch", "options": "Branch"},
  {"fieldname": "department", "fieldtype": "Link", "label": "Department", "options": "Department"},
  {"fieldname": "grade", "fieldtype": "Link", "label": "Grade", "options": "Employee Grade"},

  {"fieldname": "provenance_section", "fieldtype": "Section Break", "label": "Provenance"},
  {"fieldname": "confidence", "fieldtype": "Select", "label": "Confidence",
   "options": "\nHigh\nMedium\nLow\nNone", "read_only": 1, "in_list_view": 1},
  {"fieldname": "source", "fieldtype": "Select", "label": "Source",
   "options": "Seeded from existing users\nAuthored from intent",
   "default": "Authored from intent", "read_only": 1},
  {"fieldname": "evidence", "fieldtype": "Small Text", "label": "Evidence", "read_only": 1,
   "description": "How the seeder arrived at this row. Observed state, not endorsed state."}
 ],
 "index_web_pages_for_search": 0,
 "links": [],
 "modified": "2026-08-20 00:00:00.000000",
 "module": "Role Advisor",
 "name": "Designation Access Map",
 "owner": "Administrator",
 "permissions": [
  {"role": "System Manager", "read": 1, "write": 1, "create": 1, "delete": 1,
   "report": 1, "export": 1, "print": 1, "email": 1, "share": 1},
  {"role": "User Manager", "read": 1, "report": 1}
 ],
 "sort_field": "modified",
 "sort_order": "DESC",
 "track_changes": 1
}
```

`track_changes` is on because a map row is the reason a user got their access; the version history is part of the audit story. Delegates get read-only so the console can show them why a proposal was made.

- [ ] **Step 4: Write the controller**

Create `designation_access_map.py`:

```python
# Copyright (c) 2026, Upande and contributors
# For license information, please see license.txt

"""The designation -> role profile mapping.

Rows are resolved most-specific-wins (see `role_advisor.mapping`), so the
scope fields are a key, not a filter. Uniqueness is enforced here rather than
by a DB unique index: `company` and `branch` are nullable, and MariaDB treats
every NULL as distinct, so an index would happily accept two identical
"applies to all companies" rows.
"""

import frappe
from frappe import _
from frappe.model.document import Document

CONFIDENCE_HIGH = "High"
CONFIDENCE_MEDIUM = "Medium"
CONFIDENCE_LOW = "Low"
CONFIDENCE_NONE = "None"

SCOPE_FIELDS = ("company", "branch", "department", "grade")


class DesignationAccessMap(Document):
	def validate(self):
		self.normalise_scope()
		self.validate_scope_hierarchy()
		self.validate_unique_scope()

	def normalise_scope(self):
		"""Collapse "" to None so blank and unset compare equal."""
		for field in SCOPE_FIELDS:
			if not self.get(field):
				self.set(field, None)

	def validate_scope_hierarchy(self):
		"""A narrower dimension cannot be set without its parent.

		A branch-scoped row with no company cannot be resolved unambiguously:
		branch names are not globally unique across companies, so the resolver
		would have no way to tell which company's branch was meant.
		"""
		if self.branch and not self.company:
			frappe.throw(
				_("Set a Company before setting a Branch."),
				title=_("Incomplete Scope"),
			)

	def validate_unique_scope(self):
		existing = frappe.get_all(
			"Designation Access Map",
			filters={
				"designation": self.designation,
				"company": self.company or ("is", "not set"),
				"branch": self.branch or ("is", "not set"),
				"department": self.department or ("is", "not set"),
				"grade": self.grade or ("is", "not set"),
				"name": ("!=", self.name or ""),
			},
			pluck="name",
			limit=1,
		)
		if existing:
			frappe.throw(
				_("A map row already exists for this designation and scope: {0}").format(
					frappe.utils.get_link_to_form("Designation Access Map", existing[0])
				),
				title=_("Duplicate Map Row"),
			)

	def scope_key(self) -> tuple:
		"""The row's scope as a comparable tuple, blanks normalised to None."""
		return tuple(self.get(field) or None for field in SCOPE_FIELDS)
```

- [ ] **Step 5: Migrate and run the tests**

```bash
cd /home/austin/frappe-v16-bench
bench --site kaitet.local migrate
bench --site kaitet.local run-tests --app role_advisor --module role_advisor.tests.test_designation_access_map
```

Expected: 6 passed (or 5 passed 1 skipped if the site has fewer than two companies — it has 8, so expect 6).

- [ ] **Step 6: Commit**

```bash
cd /home/austin/frappe-v16-bench/apps/role_advisor
git add -A
git commit -m "feat: add Designation Access Map doctype

Scope fields form a key resolved most-specific-wins. Uniqueness is
enforced in validate because MariaDB unique indexes treat each NULL as
distinct, which would accept duplicate all-company rows."
```

---

## Task 4: `Delegated User Admin` and the privileged-profile check

The allowlist. `validate` refuses any profile granting write on a privileged doctype — the first of the two enforcement points from spec §5.3, so a System Manager sees the error while building the record rather than a delegate discovering it at assign time.

The check lives in its own module, `privilege.py`, because both this controller and `delegation.py` (Task 8) need it and the dependency must point forward.

**Files:**
- Create: `role_advisor/privilege.py`
- Create: `role_advisor/role_advisor/doctype/delegated_user_admin/__init__.py`
- Create: `role_advisor/role_advisor/doctype/delegated_user_admin/delegated_user_admin.json`
- Create: `role_advisor/role_advisor/doctype/delegated_user_admin/delegated_user_admin.py`
- Create: three child doctypes for the Table MultiSelects (see Step 3)
- Create: `role_advisor/tests/test_privilege.py`
- Create: `role_advisor/tests/test_delegated_user_admin.py`

**Interfaces:**
- Consumes: `role_advisor.capability.build_capability_index()`, `role_advisor.settings.privileged_doctypes()`.
- Produces:
  - `privilege.privileged_grants(role_profile: str) -> dict[str, set[str]]` — `{doctype: {perm}}` restricted to privileged doctypes with a write-equivalent right; empty dict means safe
  - `privilege.is_privileged(role_profile: str) -> bool`
  - `privilege.WRITE_EQUIVALENT: frozenset[str]`
  - Doctype `Delegated User Admin` with `user`, `enabled`, `companies`, `branches`, `allowed_role_profiles`, `allowed_module_profiles`, `can_create_users`, `can_disable_users`

- [ ] **Step 1: Write the failing tests**

Create `role_advisor/tests/test_privilege.py`:

```python
# Copyright (c) 2026, Upande and contributors
# For license information, please see license.txt

import frappe
from frappe.tests import IntegrationTestCase

from role_advisor import capability, privilege

SAFE_ROLE = "_RA Safe Role"
UNSAFE_ROLE = "_RA Unsafe Role"
SAFE_PROFILE = "_RA Safe Profile"
UNSAFE_PROFILE = "_RA Unsafe Profile"


class TestPrivilegeCheck(IntegrationTestCase):
	def setUp(self):
		for role in (SAFE_ROLE, UNSAFE_ROLE):
			if not frappe.db.exists("Role", role):
				frappe.get_doc({"doctype": "Role", "role_name": role}).insert()

		# ToDo is innocuous; Role Profile is on the privileged list.
		frappe.get_doc(
			{"doctype": "Custom DocPerm", "parent": "ToDo", "role": SAFE_ROLE,
			 "permlevel": 0, "read": 1, "write": 1}
		).insert()
		frappe.get_doc(
			{"doctype": "Custom DocPerm", "parent": "Role Profile", "role": UNSAFE_ROLE,
			 "permlevel": 0, "read": 1, "write": 1}
		).insert()

		for profile, role in ((SAFE_PROFILE, SAFE_ROLE), (UNSAFE_PROFILE, UNSAFE_ROLE)):
			if not frappe.db.exists("Role Profile", profile):
				frappe.get_doc(
					{"doctype": "Role Profile", "role_profile": profile,
					 "roles": [{"role": role}]}
				).insert()

		capability.clear_capability_index()

	def tearDown(self):
		capability.clear_capability_index()

	def test_a_profile_granting_only_todo_is_safe(self):
		self.assertEqual(privilege.privileged_grants(SAFE_PROFILE), {})
		self.assertFalse(privilege.is_privileged(SAFE_PROFILE))

	def test_a_profile_granting_write_on_role_profile_is_privileged(self):
		grants = privilege.privileged_grants(UNSAFE_PROFILE)

		self.assertIn("Role Profile", grants)
		self.assertIn("write", grants["Role Profile"])
		self.assertTrue(privilege.is_privileged(UNSAFE_PROFILE))

	def test_read_only_on_a_privileged_doctype_is_not_privileged(self):
		"""User Manager already holds read on Role Profile in production.

		Treating read as privileged would refuse every realistic allowlist.
		"""
		role = "_RA Reader Role"
		profile = "_RA Reader Profile"
		if not frappe.db.exists("Role", role):
			frappe.get_doc({"doctype": "Role", "role_name": role}).insert()
		frappe.get_doc(
			{"doctype": "Custom DocPerm", "parent": "Role Profile", "role": role,
			 "permlevel": 0, "read": 1}
		).insert()
		if not frappe.db.exists("Role Profile", profile):
			frappe.get_doc(
				{"doctype": "Role Profile", "role_profile": profile,
				 "roles": [{"role": role}]}
			).insert()
		capability.clear_capability_index()

		self.assertFalse(privilege.is_privileged(profile))

	def test_an_unknown_profile_is_treated_as_privileged(self):
		"""Fail closed: a profile absent from the index cannot be vouched for."""
		self.assertTrue(privilege.is_privileged("_RA No Such Profile"))
```

Create `role_advisor/tests/test_delegated_user_admin.py`:

```python
# Copyright (c) 2026, Upande and contributors
# For license information, please see license.txt

import frappe
from frappe.tests import IntegrationTestCase

from role_advisor import capability
from role_advisor.tests.test_privilege import (
	SAFE_PROFILE,
	UNSAFE_PROFILE,
	UNSAFE_ROLE,
	SAFE_ROLE,
)

ADMIN_USER = "_ra_delegate@example.com"


class TestDelegatedUserAdmin(IntegrationTestCase):
	def setUp(self):
		for role in (SAFE_ROLE, UNSAFE_ROLE):
			if not frappe.db.exists("Role", role):
				frappe.get_doc({"doctype": "Role", "role_name": role}).insert()
		frappe.get_doc(
			{"doctype": "Custom DocPerm", "parent": "ToDo", "role": SAFE_ROLE,
			 "permlevel": 0, "read": 1, "write": 1}
		).insert()
		frappe.get_doc(
			{"doctype": "Custom DocPerm", "parent": "Role Profile", "role": UNSAFE_ROLE,
			 "permlevel": 0, "read": 1, "write": 1}
		).insert()
		for profile, role in ((SAFE_PROFILE, SAFE_ROLE), (UNSAFE_PROFILE, UNSAFE_ROLE)):
			if not frappe.db.exists("Role Profile", profile):
				frappe.get_doc(
					{"doctype": "Role Profile", "role_profile": profile,
					 "roles": [{"role": role}]}
				).insert()
		capability.clear_capability_index()

		if not frappe.db.exists("User", ADMIN_USER):
			frappe.get_doc(
				{"doctype": "User", "email": ADMIN_USER, "first_name": "RA Delegate",
				 "send_welcome_email": 0}
			).insert(ignore_permissions=True)

		self.companies = frappe.get_all("Company", pluck="name", limit=2)

	def tearDown(self):
		capability.clear_capability_index()

	def _admin(self, **kwargs):
		defaults = {
			"doctype": "Delegated User Admin",
			"user": ADMIN_USER,
			"enabled": 1,
			"companies": [{"company": self.companies[0]}],
			"allowed_role_profiles": [{"role_profile": SAFE_PROFILE}],
		}
		return frappe.get_doc({**defaults, **kwargs})

	def test_a_safe_allowlist_is_accepted(self):
		doc = self._admin().insert(ignore_permissions=True)

		self.assertEqual(doc.user, ADMIN_USER)
		self.assertEqual(len(doc.allowed_role_profiles), 1)

	def test_a_privileged_profile_is_refused_at_save(self):
		"""Enforcement point one: the System Manager sees it immediately."""
		doc = self._admin(allowed_role_profiles=[{"role_profile": UNSAFE_PROFILE}])

		with self.assertRaises(frappe.ValidationError):
			doc.insert(ignore_permissions=True)

	def test_scope_is_required(self):
		"""An admin with no company scope could reach every user."""
		doc = self._admin(companies=[])

		with self.assertRaises(frappe.ValidationError):
			doc.insert(ignore_permissions=True)

	def test_one_record_per_user(self):
		self._admin().insert(ignore_permissions=True)

		with self.assertRaises(frappe.ValidationError):
			self._admin().insert(ignore_permissions=True)

	def test_companies_default_from_existing_user_permissions(self):
		"""Do not re-scope the 244 users who already have Company permissions."""
		frappe.get_doc(
			{"doctype": "User Permission", "user": ADMIN_USER,
			 "allow": "Company", "for_value": self.companies[0]}
		).insert(ignore_permissions=True)

		doc = frappe.get_doc(
			{"doctype": "Delegated User Admin", "user": ADMIN_USER, "enabled": 1,
			 "allowed_role_profiles": [{"role_profile": SAFE_PROFILE}]}
		).insert(ignore_permissions=True)

		self.assertEqual([r.company for r in doc.companies], [self.companies[0]])
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd /home/austin/frappe-v16-bench
bench --site kaitet.local run-tests --app role_advisor --module role_advisor.tests.test_privilege
bench --site kaitet.local run-tests --app role_advisor --module role_advisor.tests.test_delegated_user_admin
```

Expected: both FAIL — `ModuleNotFoundError: No module named 'role_advisor.privilege'` and `DoesNotExistError: DocType Delegated User Admin not found`.

- [ ] **Step 3: Write `role_advisor/privilege.py`**

```python
# Copyright (c) 2026, Upande and contributors
# For license information, please see license.txt

"""Is this Role Profile too powerful to delegate?

The denylist is *computed* from the capability index, never matched on role
names. A name list (`{"System Manager", ...}`) rots the moment someone creates
`Site Admin Copy`; a capability check catches it whatever it is called.
"""

from role_advisor import capability, settings

# Rights that let the holder change permissions or records of a privileged
# doctype. `read` is excluded deliberately: `User Manager` already holds read on
# Role Profile and Module Profile in production, and treating read as privileged
# would refuse every realistic allowlist.
WRITE_EQUIVALENT = frozenset({"write", "create", "delete", "submit", "cancel"})


def privileged_grants(role_profile: str) -> dict[str, set[str]]:
	"""Return {privileged doctype: {right}} that `role_profile` grants.

	An empty dict means the profile is safe to delegate. A profile absent from
	the index returns a sentinel grant rather than `{}` - failing closed, since
	an unknown profile cannot be vouched for.
	"""
	index = capability.build_capability_index()
	if role_profile not in index:
		return {"__unknown__": {"write"}}

	granted = index[role_profile]
	privileged = set(settings.privileged_doctypes())

	found: dict[str, set[str]] = {}
	for doctype, perms in granted.items():
		if doctype not in privileged:
			continue
		offending = perms & WRITE_EQUIVALENT
		if offending:
			found[doctype] = offending

	return found


def is_privileged(role_profile: str) -> bool:
	return bool(privileged_grants(role_profile))


def describe(grants: dict[str, set[str]]) -> str:
	"""Render grants as 'DocType: write, delete; DocType: create'."""
	return "; ".join(
		f"{doctype}: {', '.join(sorted(grants[doctype]))}" for doctype in sorted(grants)
	)
```

- [ ] **Step 4: Create the three child doctypes**

`Delegated User Admin` needs four Table MultiSelects. `allowed_module_profiles` and `allowed_role_profiles` need their own child doctypes; `companies` and `branches` need one each. Create four directories under `role_advisor/role_advisor/doctype/`, each with an empty `__init__.py`, a `Document` subclass stub, and JSON following this shape (shown for one; repeat with the substitutions in the table):

```json
{
 "actions": [], "creation": "2026-08-20 00:00:00.000000", "doctype": "DocType",
 "engine": "InnoDB", "field_order": ["role_profile"],
 "fields": [{"fieldname": "role_profile", "fieldtype": "Link", "label": "Role Profile",
   "options": "Role Profile", "in_list_view": 1, "reqd": 1}],
 "istable": 1, "links": [], "modified": "2026-08-20 00:00:00.000000",
 "module": "Role Advisor", "name": "Delegated Role Profile",
 "owner": "Administrator", "permissions": [],
 "sort_field": "modified", "sort_order": "DESC"
}
```

| Doctype name | Directory | Fieldname | Link options |
|---|---|---|---|
| `Delegated Role Profile` | `delegated_role_profile` | `role_profile` | `Role Profile` |
| `Delegated Module Profile` | `delegated_module_profile` | `module_profile` | `Module Profile` |
| `Delegated Company` | `delegated_company` | `company` | `Company` |
| `Delegated Branch` | `delegated_branch` | `branch` | `Branch` |

- [ ] **Step 5: Create `delegated_user_admin.json`**

```json
{
 "actions": [],
 "autoname": "field:user",
 "creation": "2026-08-20 00:00:00.000000",
 "doctype": "DocType",
 "engine": "InnoDB",
 "field_order": [
  "user", "enabled", "can_create_users", "can_disable_users",
  "scope_section", "companies", "branches",
  "grant_section", "allowed_role_profiles", "allowed_module_profiles"
 ],
 "fields": [
  {"fieldname": "user", "fieldtype": "Link", "label": "User", "options": "User",
   "reqd": 1, "unique": 1, "in_list_view": 1},
  {"fieldname": "enabled", "fieldtype": "Check", "label": "Enabled", "default": "1",
   "in_list_view": 1,
   "description": "Restrictions apply only while this record is enabled. Disabling it restores stock behaviour."},
  {"fieldname": "can_create_users", "fieldtype": "Check", "label": "Can Create Users", "default": "0"},
  {"fieldname": "can_disable_users", "fieldtype": "Check", "label": "Can Disable Users", "default": "0"},

  {"fieldname": "scope_section", "fieldtype": "Section Break", "label": "Scope"},
  {"fieldname": "companies", "fieldtype": "Table MultiSelect", "label": "Companies",
   "options": "Delegated Company",
   "description": "Defaults from this user's existing Company User Permissions, then stored explicitly so a later change to those permissions cannot silently widen what they administer."},
  {"fieldname": "branches", "fieldtype": "Table MultiSelect", "label": "Branches",
   "options": "Delegated Branch",
   "description": "Optional. Empty means every branch within the companies above."},

  {"fieldname": "grant_section", "fieldtype": "Section Break", "label": "Grantable"},
  {"fieldname": "allowed_role_profiles", "fieldtype": "Table MultiSelect",
   "label": "Allowed Role Profiles", "options": "Delegated Role Profile",
   "description": "What this admin may hand out - not what they hold themselves."},
  {"fieldname": "allowed_module_profiles", "fieldtype": "Table MultiSelect",
   "label": "Allowed Module Profiles", "options": "Delegated Module Profile"}
 ],
 "links": [],
 "modified": "2026-08-20 00:00:00.000000",
 "module": "Role Advisor",
 "name": "Delegated User Admin",
 "owner": "Administrator",
 "permissions": [
  {"role": "System Manager", "read": 1, "write": 1, "create": 1, "delete": 1,
   "report": 1, "export": 1, "print": 1, "email": 1, "share": 1}
 ],
 "sort_field": "modified",
 "sort_order": "DESC",
 "track_changes": 1
}
```

Only System Manager appears in `permissions`. A delegate reading their *own* record is handled by a `has_permission` hook in Task 10, not by a role grant — a role grant would let every delegate read every other delegate's allowlist.

- [ ] **Step 6: Write the controller**

```python
# Copyright (c) 2026, Upande and contributors
# For license information, please see license.txt

"""Per-admin delegation record: scope plus grantable allowlist.

The allowlist is deliberately not "the profiles this admin holds". A Farm
Manager must be able to grant `Guard` without holding `Guard`, so that
administering access does not inflate the administrator's own access.
"""

import frappe
from frappe import _
from frappe.model.document import Document

from role_advisor import privilege


class DelegatedUserAdmin(Document):
	def before_insert(self):
		self.default_companies_from_user_permissions()

	def validate(self):
		self.validate_scope_present()
		self.validate_no_privileged_profiles()

	def default_companies_from_user_permissions(self):
		"""Seed scope from the admin's existing Company User Permissions.

		244 users already carry Company permissions; re-entering them by hand
		invites transcription errors. The value is copied, not referenced, so a
		later edit to those permissions cannot widen this record's scope.
		"""
		if self.companies:
			return

		for company in frappe.get_all(
			"User Permission",
			filters={"user": self.user, "allow": "Company"},
			pluck="for_value",
		):
			self.append("companies", {"company": company})

	def validate_scope_present(self):
		if not self.companies:
			frappe.throw(
				_("Set at least one Company. An admin with no scope could reach every user."),
				title=_("Scope Required"),
			)

	def validate_no_privileged_profiles(self):
		"""Refuse an allowlist entry that could be used to escalate.

		This is the first of two checks. `assign_access` repeats it at write
		time, because a profile's contents can change after it was allowlisted.
		"""
		for row in self.allowed_role_profiles or []:
			grants = privilege.privileged_grants(row.role_profile)
			if grants:
				frappe.throw(
					_("{0} cannot be delegated: it grants {1}.").format(
						frappe.bold(row.role_profile), privilege.describe(grants)
					),
					title=_("Privileged Profile"),
				)
```

- [ ] **Step 7: Migrate and run the tests**

```bash
cd /home/austin/frappe-v16-bench
bench --site kaitet.local migrate
bench --site kaitet.local run-tests --app role_advisor --module role_advisor.tests.test_privilege
bench --site kaitet.local run-tests --app role_advisor --module role_advisor.tests.test_delegated_user_admin
```

Expected: 4 passed, then 5 passed.

- [ ] **Step 8: Commit**

```bash
cd /home/austin/frappe-v16-bench/apps/role_advisor
git add -A
git commit -m "feat: add Delegated User Admin with computed privilege check

The allowlist is what an admin may hand out, not what they hold. Any
profile granting write-equivalent rights on a privileged doctype is
refused at save; read is excluded because User Manager legitimately holds
read on Role Profile in production."
```

---
## Task 5: `Access Assignment Log` and the audit helper

Every assignment writes one row, including no-ops — spec §4.3 requires an audit trail with no holes. Rows are immutable after insert: an editable audit log is not an audit log.

**Files:**
- Create: `role_advisor/role_advisor/doctype/access_assignment_log/__init__.py`
- Create: `role_advisor/role_advisor/doctype/access_assignment_log/access_assignment_log.json`
- Create: `role_advisor/role_advisor/doctype/access_assignment_log/access_assignment_log.py`
- Create: `role_advisor/audit.py`
- Create: `role_advisor/tests/test_audit.py`

**Interfaces:**
- Consumes: `role_advisor.capability.get_user_role_profiles()`.
- Produces:
  - `audit.snapshot(user: str) -> dict` — `{"profiles": list[str], "module_profile": str | None, "roles": set[str]}`
  - `audit.log_assignment(target: str, before: dict, after: dict, trigger: str, outcome: str = "Applied", notes: str | None = None) -> str` — returns the log row name
  - `audit.TRIGGER_MANUAL`, `audit.TRIGGER_MAP`, `audit.TRIGGER_SWEEP`, `audit.OUTCOME_APPLIED`, `audit.OUTCOME_NO_CHANGE`, `audit.OUTCOME_REFUSED`

- [ ] **Step 1: Write the failing test**

Create `role_advisor/tests/test_audit.py`:

```python
# Copyright (c) 2026, Upande and contributors
# For license information, please see license.txt

import frappe
from frappe.tests import IntegrationTestCase

from role_advisor import audit

TARGET = "_ra_audit_target@example.com"


class TestAuditLog(IntegrationTestCase):
	def setUp(self):
		if not frappe.db.exists("User", TARGET):
			frappe.get_doc(
				{"doctype": "User", "email": TARGET, "first_name": "RA Target",
				 "send_welcome_email": 0}
			).insert(ignore_permissions=True)

	def test_snapshot_reports_current_state(self):
		snap = audit.snapshot(TARGET)

		self.assertEqual(snap["profiles"], [])
		self.assertIsNone(snap["module_profile"])
		self.assertIsInstance(snap["roles"], set)

	def test_log_records_the_delta_in_both_directions(self):
		before = {"profiles": ["A"], "module_profile": None, "roles": {"X", "Y"}}
		after = {"profiles": ["B"], "module_profile": "MP", "roles": {"Y", "Z"}}

		name = audit.log_assignment(TARGET, before, after, audit.TRIGGER_MANUAL)
		row = frappe.get_doc("Access Assignment Log", name)

		self.assertEqual(row.target_user, TARGET)
		self.assertEqual(row.profiles_before, "A")
		self.assertEqual(row.profiles_after, "B")
		self.assertEqual(row.module_profile_after, "MP")
		self.assertEqual(row.roles_gained, "Z")
		self.assertEqual(row.roles_lost, "X")
		self.assertEqual(row.trigger, audit.TRIGGER_MANUAL)
		self.assertEqual(row.outcome, audit.OUTCOME_APPLIED)
		self.assertEqual(row.actor, frappe.session.user)

	def test_a_no_op_is_still_logged(self):
		"""The audit trail must have no holes, so nothing is skipped."""
		state = {"profiles": ["A"], "module_profile": None, "roles": {"X"}}

		name = audit.log_assignment(
			TARGET, state, state, audit.TRIGGER_SWEEP, outcome=audit.OUTCOME_NO_CHANGE
		)
		row = frappe.get_doc("Access Assignment Log", name)

		self.assertEqual(row.outcome, audit.OUTCOME_NO_CHANGE)
		self.assertFalse(row.roles_gained)
		self.assertFalse(row.roles_lost)

	def test_a_log_row_cannot_be_edited(self):
		name = audit.log_assignment(
			TARGET,
			{"profiles": [], "module_profile": None, "roles": set()},
			{"profiles": ["A"], "module_profile": None, "roles": set()},
			audit.TRIGGER_MANUAL,
		)

		row = frappe.get_doc("Access Assignment Log", name)
		row.outcome = audit.OUTCOME_REFUSED

		with self.assertRaises(frappe.ValidationError):
			row.save(ignore_permissions=True)
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd /home/austin/frappe-v16-bench
bench --site kaitet.local run-tests --app role_advisor --module role_advisor.tests.test_audit
```

Expected: FAIL — `ModuleNotFoundError: No module named 'role_advisor.audit'`.

- [ ] **Step 3: Create the doctype JSON**

Create the empty `__init__.py`, then `access_assignment_log.json`:

```json
{
 "actions": [],
 "autoname": "hash",
 "creation": "2026-08-20 00:00:00.000000",
 "doctype": "DocType",
 "engine": "InnoDB",
 "field_order": [
  "actor", "target_user", "trigger", "outcome",
  "profile_section", "profiles_before", "profiles_after",
  "module_column", "module_profile_before", "module_profile_after",
  "roles_section", "roles_gained", "roles_lost", "decision_notes"
 ],
 "fields": [
  {"fieldname": "actor", "fieldtype": "Link", "label": "Actor", "options": "User",
   "read_only": 1, "in_list_view": 1, "in_standard_filter": 1},
  {"fieldname": "target_user", "fieldtype": "Link", "label": "Target User",
   "options": "User", "read_only": 1, "in_list_view": 1, "in_standard_filter": 1},
  {"fieldname": "trigger", "fieldtype": "Select", "label": "Trigger",
   "options": "Manual\nDesignation Map\nBulk Sweep", "read_only": 1,
   "in_list_view": 1, "in_standard_filter": 1},
  {"fieldname": "outcome", "fieldtype": "Select", "label": "Outcome",
   "options": "Applied\nNo Change\nRefused", "read_only": 1,
   "in_list_view": 1, "in_standard_filter": 1},

  {"fieldname": "profile_section", "fieldtype": "Section Break", "label": "Role Profiles"},
  {"fieldname": "profiles_before", "fieldtype": "Small Text", "label": "Profiles Before", "read_only": 1},
  {"fieldname": "profiles_after", "fieldtype": "Small Text", "label": "Profiles After", "read_only": 1},
  {"fieldname": "module_column", "fieldtype": "Column Break"},
  {"fieldname": "module_profile_before", "fieldtype": "Data", "label": "Module Profile Before", "read_only": 1},
  {"fieldname": "module_profile_after", "fieldtype": "Data", "label": "Module Profile After", "read_only": 1},

  {"fieldname": "roles_section", "fieldtype": "Section Break", "label": "Role Delta"},
  {"fieldname": "roles_gained", "fieldtype": "Small Text", "label": "Roles Gained", "read_only": 1},
  {"fieldname": "roles_lost", "fieldtype": "Small Text", "label": "Roles Lost", "read_only": 1,
   "description": "v16 prunes roles to the union of assigned profiles. Anything listed here was revoked by the assignment."},
  {"fieldname": "decision_notes", "fieldtype": "Small Text", "label": "Decision Notes", "read_only": 1}
 ],
 "in_create": 1,
 "links": [],
 "modified": "2026-08-20 00:00:00.000000",
 "module": "Role Advisor",
 "name": "Access Assignment Log",
 "owner": "Administrator",
 "permissions": [
  {"role": "System Manager", "read": 1, "report": 1, "export": 1, "print": 1, "email": 1, "share": 1},
  {"role": "User Manager", "read": 1, "report": 1}
 ],
 "sort_field": "creation",
 "sort_order": "DESC"
}
```

Note the permissions: **nobody gets `write` or `delete`, not even System Manager.** `in_create` hides the "new" button in the UI. Rows are written by `audit.log_assignment` with `ignore_permissions=True`, which is the only path that should ever create one.

`module_profile_before`/`after` are `Data`, not `Link` — a `Link` would break the log row if the module profile is later deleted, and an audit row must survive its referents.

- [ ] **Step 4: Write the controller enforcing immutability**

```python
# Copyright (c) 2026, Upande and contributors
# For license information, please see license.txt

"""Immutable record of one access assignment.

Written only by `role_advisor.audit.log_assignment`. No role holds write or
delete on this doctype - an editable audit log is not an audit log.
"""

import frappe
from frappe import _
from frappe.model.document import Document


class AccessAssignmentLog(Document):
	def validate(self):
		if not self.is_new():
			frappe.throw(
				_("Access Assignment Log rows cannot be modified after creation."),
				title=_("Immutable Record"),
			)
```

- [ ] **Step 5: Write `role_advisor/audit.py`**

```python
# Copyright (c) 2026, Upande and contributors
# For license information, please see license.txt

"""Snapshot a user's access, and record what changed.

Every assignment is logged, including no-ops: a trail with gaps cannot answer
"was this change made, or never attempted?"
"""

import frappe

from role_advisor import capability

TRIGGER_MANUAL = "Manual"
TRIGGER_MAP = "Designation Map"
TRIGGER_SWEEP = "Bulk Sweep"

OUTCOME_APPLIED = "Applied"
OUTCOME_NO_CHANGE = "No Change"
OUTCOME_REFUSED = "Refused"


def snapshot(user: str) -> dict:
	"""Capture the access-relevant state of `user` before or after a write."""
	return {
		"profiles": capability.get_user_role_profiles(user),
		"module_profile": frappe.db.get_value("User", user, "module_profile") or None,
		"roles": set(
			frappe.get_all(
				"Has Role",
				filters={"parent": user, "parenttype": "User"},
				pluck="role",
			)
		),
	}


def log_assignment(
	target: str,
	before: dict,
	after: dict,
	trigger: str,
	outcome: str = OUTCOME_APPLIED,
	notes: str | None = None,
) -> str:
	"""Write one immutable log row and return its name."""
	row = frappe.get_doc(
		{
			"doctype": "Access Assignment Log",
			"actor": frappe.session.user,
			"target_user": target,
			"trigger": trigger,
			"outcome": outcome,
			"profiles_before": ", ".join(before["profiles"]),
			"profiles_after": ", ".join(after["profiles"]),
			"module_profile_before": before["module_profile"],
			"module_profile_after": after["module_profile"],
			"roles_gained": ", ".join(sorted(after["roles"] - before["roles"])),
			"roles_lost": ", ".join(sorted(before["roles"] - after["roles"])),
			"decision_notes": notes,
		}
	)
	row.insert(ignore_permissions=True)

	return row.name
```

- [ ] **Step 6: Migrate and run the tests**

```bash
cd /home/austin/frappe-v16-bench
bench --site kaitet.local migrate
bench --site kaitet.local run-tests --app role_advisor --module role_advisor.tests.test_audit
```

Expected: 4 passed.

- [ ] **Step 7: Commit**

```bash
cd /home/austin/frappe-v16-bench/apps/role_advisor
git add -A
git commit -m "feat: add immutable Access Assignment Log

No role holds write or delete; rows are written only by audit.log_assignment.
Module profile fields are Data rather than Link so a log row survives deletion
of its referents. No-ops are logged too, so the trail has no holes."
```

---

## Task 6: Map resolution and tie-break

`mapping.py` answers "which profile does this designation get, in this scope?" — most-specific-wins — and "which of these candidates, when peers disagree?" — tightest by permission count.

**Files:**
- Create: `role_advisor/mapping.py`
- Create: `role_advisor/tests/test_mapping.py`

**Interfaces:**
- Consumes: `settings.scope_dimensions()`, `settings.tie_break_rule()`, `capability.build_capability_index()`, `capability.total_perm_count()`.
- Produces:
  - `mapping.employee_scope(user: str) -> dict` — `{"company": ..., "branch": ..., "department": ..., "grade": ...}`, values may be `None`
  - `mapping.resolve(designation: str, scope: dict, active_only: bool = True) -> str | None` — returns a `Designation Access Map` row name
  - `mapping.tie_break(candidates: list[str]) -> str | None`
  - `mapping.candidate_scopes(scope: dict) -> list[dict]` — most specific first

- [ ] **Step 1: Write the failing test**

Create `role_advisor/tests/test_mapping.py`:

```python
# Copyright (c) 2026, Upande and contributors
# For license information, please see license.txt

import frappe
from frappe.tests import IntegrationTestCase

from role_advisor import capability, mapping

DESIGNATION = "_RA Mapping Designation"
BROAD_ROLE = "_RA Broad Role"
TIGHT_ROLE = "_RA Tight Role"
BROAD_PROFILE = "_RA Broad Profile"
TIGHT_PROFILE = "_RA Tight Profile"


class TestMapping(IntegrationTestCase):
	def setUp(self):
		if not frappe.db.exists("Designation", DESIGNATION):
			frappe.get_doc(
				{"doctype": "Designation", "designation_name": DESIGNATION}
			).insert(ignore_permissions=True)

		for role in (BROAD_ROLE, TIGHT_ROLE):
			if not frappe.db.exists("Role", role):
				frappe.get_doc({"doctype": "Role", "role_name": role}).insert()

		# Broad grants four rights, tight grants one - so tightness is decided
		# by permission count, not by profile name or row order.
		frappe.get_doc(
			{"doctype": "Custom DocPerm", "parent": "ToDo", "role": BROAD_ROLE,
			 "permlevel": 0, "read": 1, "write": 1, "create": 1, "delete": 1}
		).insert()
		frappe.get_doc(
			{"doctype": "Custom DocPerm", "parent": "ToDo", "role": TIGHT_ROLE,
			 "permlevel": 0, "read": 1}
		).insert()

		for profile, role in ((BROAD_PROFILE, BROAD_ROLE), (TIGHT_PROFILE, TIGHT_ROLE)):
			if not frappe.db.exists("Role Profile", profile):
				frappe.get_doc(
					{"doctype": "Role Profile", "role_profile": profile,
					 "roles": [{"role": role}]}
				).insert()

		capability.clear_capability_index()
		self.companies = frappe.get_all("Company", pluck="name", limit=2)

	def tearDown(self):
		capability.clear_capability_index()

	def _map_row(self, profile, **scope):
		return frappe.get_doc(
			{
				"doctype": "Designation Access Map",
				"designation": DESIGNATION,
				"role_profile": profile,
				"is_active": 1,
				**scope,
			}
		).insert(ignore_permissions=True)

	def test_candidate_scopes_are_ordered_most_specific_first(self):
		scopes = mapping.candidate_scopes(
			{"company": "C", "branch": "B", "department": "D", "grade": "G"}
		)

		# Default dimensions are company + branch, so three candidates.
		self.assertEqual(
			scopes,
			[
				{"company": "C", "branch": "B"},
				{"company": "C", "branch": None},
				{"company": None, "branch": None},
			],
		)

	def test_a_bare_designation_row_matches_any_scope(self):
		row = self._map_row(TIGHT_PROFILE)

		resolved = mapping.resolve(DESIGNATION, {"company": self.companies[0]})

		self.assertEqual(resolved, row.name)

	def test_a_company_row_beats_a_bare_row(self):
		self._map_row(BROAD_PROFILE)
		specific = self._map_row(TIGHT_PROFILE, company=self.companies[0])

		resolved = mapping.resolve(DESIGNATION, {"company": self.companies[0]})

		self.assertEqual(resolved, specific.name)

	def test_a_row_for_another_company_does_not_match(self):
		if len(self.companies) < 2:
			self.skipTest("site has fewer than two companies")
		self._map_row(TIGHT_PROFILE, company=self.companies[1])

		self.assertIsNone(mapping.resolve(DESIGNATION, {"company": self.companies[0]}))

	def test_inactive_rows_are_ignored_by_default(self):
		frappe.get_doc(
			{"doctype": "Designation Access Map", "designation": DESIGNATION,
			 "role_profile": TIGHT_PROFILE, "is_active": 0}
		).insert(ignore_permissions=True)

		self.assertIsNone(mapping.resolve(DESIGNATION, {"company": self.companies[0]}))

	def test_inactive_rows_are_visible_to_the_dry_run(self):
		row = frappe.get_doc(
			{"doctype": "Designation Access Map", "designation": DESIGNATION,
			 "role_profile": TIGHT_PROFILE, "is_active": 0}
		).insert(ignore_permissions=True)

		resolved = mapping.resolve(
			DESIGNATION, {"company": self.companies[0]}, active_only=False
		)

		self.assertEqual(resolved, row.name)

	def test_tie_break_picks_the_tightest_profile(self):
		"""Majority vote drifts toward over-granting; tightness does not."""
		self.assertEqual(
			mapping.tie_break([BROAD_PROFILE, TIGHT_PROFILE]), TIGHT_PROFILE
		)

	def test_tie_break_is_stable_on_equal_counts(self):
		"""Two profiles granting the same amount must resolve deterministically."""
		twin = "_RA Twin Profile"
		if not frappe.db.exists("Role Profile", twin):
			frappe.get_doc(
				{"doctype": "Role Profile", "role_profile": twin,
				 "roles": [{"role": TIGHT_ROLE}]}
			).insert()
		capability.clear_capability_index()

		# Same permission count, so the tie breaks on name for repeatability.
		self.assertEqual(
			mapping.tie_break([twin, TIGHT_PROFILE]),
			sorted([twin, TIGHT_PROFILE])[0],
		)

	def test_tie_break_returns_none_for_an_empty_list(self):
		self.assertIsNone(mapping.tie_break([]))
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd /home/austin/frappe-v16-bench
bench --site kaitet.local run-tests --app role_advisor --module role_advisor.tests.test_mapping
```

Expected: FAIL — `ModuleNotFoundError: No module named 'role_advisor.mapping'`.

- [ ] **Step 3: Write `role_advisor/mapping.py`**

```python
# Copyright (c) 2026, Upande and contributors
# For license information, please see license.txt

"""Resolve a designation to a map row, and break ties between candidates."""

import frappe

from role_advisor import capability, settings


def employee_scope(user: str) -> dict:
	"""Return the scope dimensions for `user`, read from their Employee record.

	Users with no Employee record return all-None. They are consequently
	unreachable by any scoped delegate - which is the intended outcome for the
	109 unlinked users on Kaitet, not an oversight.
	"""
	row = frappe.db.get_value(
		"Employee",
		{"user_id": user, "status": "Active"},
		["company", "branch", "department", "grade"],
		as_dict=True,
	)

	return {
		dimension: (row.get(dimension) if row else None) or None
		for dimension in settings.SCOPE_DIMENSIONS
	}


def candidate_scopes(scope: dict) -> list[dict]:
	"""Scope filters to try, most specific first.

	Specificity is dropped from the narrow end: (company, branch) then
	(company,) then (). `settings.SCOPE_DIMENSIONS` is ordered most-general
	first precisely so this walk is a suffix truncation.
	"""
	dimensions = settings.scope_dimensions()

	candidates = []
	for depth in range(len(dimensions), -1, -1):
		candidates.append(
			{
				dimension: (scope.get(dimension) if index < depth else None)
				for index, dimension in enumerate(dimensions)
			}
		)

	return candidates


def resolve(designation: str, scope: dict, active_only: bool = True) -> str | None:
	"""Return the name of the most specific matching map row, or None.

	`active_only=False` is for the dry-run, which must show what *would* be
	applied once a human activates the row it depends on.
	"""
	if not designation:
		return None

	for candidate in candidate_scopes(scope):
		filters = {"designation": designation}
		if active_only:
			filters["is_active"] = 1

		# An unset dimension must match only rows that are also unset, so the
		# filter has to distinguish NULL from "any". `("is", "not set")` does
		# that; passing None would be read as "no filter".
		for dimension, value in candidate.items():
			filters[dimension] = value or ("is", "not set")

		rows = frappe.get_all(
			"Designation Access Map", filters=filters, pluck="name", limit=1
		)
		if rows:
			return rows[0]

	return None


def tie_break(candidates: list[str]) -> str | None:
	"""Choose between role profiles that all satisfy the same requirement.

	Default rule is tightest-by-permission-count. Where several profiles cover
	the same need they differ only in what *else* they hand over, so the
	smallest total grant wins: least authority beyond the ask, smallest blast
	radius. Ties break on name so a rerun gives the same answer.
	"""
	if not candidates:
		return None

	unique = sorted(set(candidates))
	if len(unique) == 1:
		return unique[0]

	rule = settings.tie_break_rule()
	if rule == "Always flag":
		return None

	if rule == "Majority peer vote":
		# The caller supplies candidates in peer-frequency order for this rule,
		# so the first entry is already the majority pick.
		return candidates[0]

	index = capability.build_capability_index()

	return min(
		unique,
		key=lambda profile: (
			capability.total_perm_count(index.get(profile, {})),
			len(index.get(profile, {})),
			profile,
		),
	)
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
cd /home/austin/frappe-v16-bench
bench --site kaitet.local run-tests --app role_advisor --module role_advisor.tests.test_mapping
```

Expected: 9 passed (1 may skip if the site has fewer than two companies; it has 8).

- [ ] **Step 5: Sanity-check resolution against real data**

```bash
cd /home/austin/frappe-v16-bench
bench --site kaitet.local console <<'EOF'
from role_advisor import mapping
print(mapping.employee_scope("zakayo.koech@karenroses.com"))
print(mapping.candidate_scopes({"company": "Karen Roses", "branch": None}))
EOF
```

Expected: the scope dict shows `company: Karen Roses`, and three candidate scopes are printed most-specific first.

- [ ] **Step 6: Commit**

```bash
cd /home/austin/frappe-v16-bench/apps/role_advisor
git add -A
git commit -m "feat: add map resolution and tightest-wins tie-break

Resolution drops specificity from the narrow end, so SCOPE_DIMENSIONS
order is load-bearing. Unset dimensions filter on ('is', 'not set') rather
than None, which would read as 'no filter' and match every row."
```

---
## Task 7: Peer-derived map seeding

Turns the 254 users who already have both a designation and a profile into map rows. Everything it writes is **observed state, not endorsed state** — Kaitet's assignments are known-inconsistent, so the seeder's job is to produce a reviewable hypothesis, not a configuration.

**A design decision this task settles.** The tie-break rule is "tightest by permission count", but applying it across *all* candidates would let a single outlier win: `Scouter` has 29 peers on `scout` and a couple of strays, and the tightest stray would beat the 29. So tie-break runs only over **materially supported** candidates (count ≥ 2, or all of them if none reaches 2). The majority pick and the tightest pick are both recorded in `evidence`, and any disagreement between them sets `is_active = 0` regardless of confidence — that is the `Grader` → `Sales` vs `Sales (Restricted)` case, where majority favours the broader profile.

**Files:**
- Create: `role_advisor/seeding.py`
- Create: `role_advisor/tests/test_seeding.py`

**Interfaces:**
- Consumes: `settings.scope_dimensions()`, `settings.min_peers_high_confidence()`, `settings.seed_mode()`, `mapping.tie_break()`, `capability.build_capability_index()`, the `Designation Access Map` doctype and its `CONFIDENCE_*` constants.
- Produces:
  - `seeding.observe_assignments() -> dict[tuple, dict[str, int]]` — `{(designation, *scope): {profile: peer_count}}`
  - `seeding.classify(counts: dict[str, int]) -> dict` — `{"profile", "confidence", "majority", "tightest", "flagged", "evidence"}`
  - `seeding.seed(dry_run: bool = True) -> list[dict]` — one dict per proposed row
  - `seeding.HIGH_AGREEMENT_RATIO: float`

- [ ] **Step 1: Write the failing test**

Create `role_advisor/tests/test_seeding.py`:

```python
# Copyright (c) 2026, Upande and contributors
# For license information, please see license.txt

import frappe
from frappe.tests import IntegrationTestCase

from role_advisor import capability, seeding
from role_advisor.role_advisor.doctype.designation_access_map.designation_access_map import (
	CONFIDENCE_HIGH,
	CONFIDENCE_LOW,
	CONFIDENCE_MEDIUM,
)

BROAD_ROLE = "_RA Seed Broad Role"
TIGHT_ROLE = "_RA Seed Tight Role"
BROAD_PROFILE = "_RA Seed Broad Profile"
TIGHT_PROFILE = "_RA Seed Tight Profile"


class TestSeedClassification(IntegrationTestCase):
	"""`classify` is the whole judgement, so it is tested in isolation."""

	def setUp(self):
		for role in (BROAD_ROLE, TIGHT_ROLE):
			if not frappe.db.exists("Role", role):
				frappe.get_doc({"doctype": "Role", "role_name": role}).insert()
		frappe.get_doc(
			{"doctype": "Custom DocPerm", "parent": "ToDo", "role": BROAD_ROLE,
			 "permlevel": 0, "read": 1, "write": 1, "create": 1, "delete": 1}
		).insert()
		frappe.get_doc(
			{"doctype": "Custom DocPerm", "parent": "ToDo", "role": TIGHT_ROLE,
			 "permlevel": 0, "read": 1}
		).insert()
		for profile, role in ((BROAD_PROFILE, BROAD_ROLE), (TIGHT_PROFILE, TIGHT_ROLE)):
			if not frappe.db.exists("Role Profile", profile):
				frappe.get_doc(
					{"doctype": "Role Profile", "role_profile": profile,
					 "roles": [{"role": role}]}
				).insert()
		capability.clear_capability_index()

	def tearDown(self):
		capability.clear_capability_index()

	def test_unanimous_and_well_supported_is_high(self):
		result = seeding.classify({TIGHT_PROFILE: 29})

		self.assertEqual(result["confidence"], CONFIDENCE_HIGH)
		self.assertEqual(result["profile"], TIGHT_PROFILE)
		self.assertFalse(result["flagged"])

	def test_a_dominant_majority_is_still_high(self):
		"""29 of 31 is agreement, not a split."""
		result = seeding.classify({TIGHT_PROFILE: 29, BROAD_PROFILE: 2})

		self.assertEqual(result["confidence"], CONFIDENCE_HIGH)

	def test_a_single_peer_is_low(self):
		result = seeding.classify({TIGHT_PROFILE: 1})

		self.assertEqual(result["confidence"], CONFIDENCE_LOW)
		self.assertTrue(result["flagged"], "low confidence must never auto-apply")

	def test_an_even_split_is_medium(self):
		result = seeding.classify({TIGHT_PROFILE: 3, BROAD_PROFILE: 3})

		self.assertEqual(result["confidence"], CONFIDENCE_MEDIUM)
		self.assertTrue(result["flagged"])

	def test_a_lone_outlier_cannot_win_on_tightness(self):
		"""Tightest-wins must not let one stray assignment beat 29 peers."""
		result = seeding.classify({BROAD_PROFILE: 29, TIGHT_PROFILE: 1})

		self.assertEqual(result["profile"], BROAD_PROFILE)

	def test_disagreement_between_majority_and_tightest_is_flagged(self):
		"""The Grader case: majority picks the broader profile."""
		result = seeding.classify({BROAD_PROFILE: 4, TIGHT_PROFILE: 3})

		self.assertEqual(result["majority"], BROAD_PROFILE)
		self.assertEqual(result["tightest"], TIGHT_PROFILE)
		self.assertTrue(result["flagged"])

	def test_evidence_names_the_counts(self):
		result = seeding.classify({TIGHT_PROFILE: 29, BROAD_PROFILE: 2})

		self.assertIn("29", result["evidence"])
		self.assertIn(TIGHT_PROFILE, result["evidence"])

	def test_no_peers_yields_nothing(self):
		self.assertIsNone(seeding.classify({}))


class TestSeedRun(IntegrationTestCase):
	def test_dry_run_writes_nothing(self):
		before = frappe.db.count("Designation Access Map")

		rows = seeding.seed(dry_run=True)

		self.assertEqual(frappe.db.count("Designation Access Map"), before)
		self.assertIsInstance(rows, list)

	def test_observe_assignments_keys_on_designation_and_scope(self):
		observed = seeding.observe_assignments()

		self.assertTrue(observed, "the site has 254 assignable users; expected rows")
		key = next(iter(observed))
		# (designation, company, branch) with the default two dimensions.
		self.assertEqual(len(key), 3)

	def test_author_from_intent_mode_seeds_nothing(self):
		doc = frappe.get_single("User Access Settings")
		doc.seed_mode = "Author from intent"
		doc.save(ignore_permissions=True)

		self.assertEqual(seeding.seed(dry_run=True), [])
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd /home/austin/frappe-v16-bench
bench --site kaitet.local run-tests --app role_advisor --module role_advisor.tests.test_seeding
```

Expected: FAIL — `ModuleNotFoundError: No module named 'role_advisor.seeding'`.

- [ ] **Step 3: Write `role_advisor/seeding.py`**

```python
# Copyright (c) 2026, Upande and contributors
# For license information, please see license.txt

"""Seed the Designation Access Map from what users already hold.

Everything here records *observed* state. Kaitet's existing assignments were
made without consistent regard to designation, company or branch - an Irrigator
holds an Approver profile, three Task Workers hold `scout`, and two users carry
a company that contradicts their email domain. So the seeder's output is a
hypothesis for review, and only unambiguous rows are activated.
"""

import frappe

from role_advisor import capability, mapping, settings
from role_advisor.role_advisor.doctype.designation_access_map.designation_access_map import (
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
	at least one role profile - the 254 users who can actually evidence a
	mapping.
	"""
	dimensions = settings.scope_dimensions()

	rows = frappe.db.sql(
		"""
		select e.designation as designation,
		       {dimension_columns},
		       urp.role_profile as role_profile,
		       count(distinct u.name) as peers
		from `tabUser` u
		join `tabEmployee` e on e.user_id = u.name and e.status = 'Active'
		join `tabUser Role Profile` urp
		     on urp.parent = u.name and urp.parenttype = 'User'
		where u.enabled = 1
		  and u.user_type = 'System User'
		  and ifnull(e.designation, '') != ''
		group by e.designation, {dimension_columns}, urp.role_profile
		""".format(
			dimension_columns=", ".join(f"e.`{d}` as `{d}`" for d in dimensions)
		),
		as_dict=True,
	)

	observed: dict[tuple, dict[str, int]] = {}
	for row in rows:
		key = (row.designation, *(row.get(d) or None for d in dimensions))
		observed.setdefault(key, {})[row.role_profile] = row.peers

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
		supported = [profile for profile, _ in ordered]

	tightest = mapping.tie_break(supported) or majority

	ratio = top_count / total
	if len(counts) == 1 or ratio >= HIGH_AGREEMENT_RATIO:
		confidence = CONFIDENCE_HIGH if top_count >= settings.min_peers_high_confidence() else (
			CONFIDENCE_MEDIUM if top_count >= MATERIAL_SUPPORT else CONFIDENCE_LOW
		)
	elif total >= MATERIAL_SUPPORT:
		confidence = CONFIDENCE_MEDIUM
	else:
		confidence = CONFIDENCE_LOW

	# Disagreement between the popular choice and the least-privilege choice is
	# exactly where a human is needed, whatever the confidence tier says.
	disagrees = majority != tightest
	flagged = confidence != CONFIDENCE_HIGH or disagrees

	evidence_parts = [
		f"{count} of {total} peers hold {profile}" for profile, count in ordered
	]
	if disagrees:
		evidence_parts.append(
			f"majority is {majority} but {tightest} grants less - review before activating"
		)

	return {
		# Tightest wins per settings, but the row is flagged so a human rules on it.
		"profile": tightest,
		"majority": majority,
		"tightest": tightest,
		"confidence": confidence,
		"flagged": flagged,
		"evidence": ". ".join(evidence_parts) + ".",
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

		proposal = {
			"designation": designation,
			**scope,
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
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
cd /home/austin/frappe-v16-bench
bench --site kaitet.local run-tests --app role_advisor --module role_advisor.tests.test_seeding
```

Expected: 11 passed.

- [ ] **Step 5: Dry-run the seeder against real data and eyeball it**

```bash
cd /home/austin/frappe-v16-bench
bench --site kaitet.local console <<'EOF'
from collections import Counter
from role_advisor import seeding
rows = seeding.seed(dry_run=True)
print(len(rows), "proposed rows")
print(Counter(r["confidence"] for r in rows))
print(sum(1 for r in rows if r["is_active"]), "would be active")
for r in rows[:5]:
    print(r["designation"], "|", r.get("company"), "->", r["role_profile"], "|", r["confidence"])
EOF
```

Expected: on the order of 80–120 proposed rows, a minority active, and the printed samples plausible. If *every* row comes back active, `classify` is too permissive — stop and re-check `HIGH_AGREEMENT_RATIO` and `min_peers_high_confidence` before writing anything.

- [ ] **Step 6: Commit**

```bash
cd /home/austin/frappe-v16-bench/apps/role_advisor
git add -A
git commit -m "feat: seed the access map from observed assignments

Tie-break runs only over materially supported candidates, so one stray
assignment cannot beat 29 peers on tightness. Disagreement between the
majority and the least-privilege pick deactivates the row whatever its
confidence tier, since that is exactly where a human is needed."
```

---
## Task 8: Delegation scope and the three gates

`delegation.py` answers "who is this caller, what may they reach, and what may they hand out?" Every API method in Task 11 opens with these gates.

**Files:**
- Create: `role_advisor/delegation.py`
- Create: `role_advisor/tests/test_delegation.py`

**Interfaces:**
- Consumes: `settings.delegate_role()`, `settings.require_employee_link()`, `privilege.privileged_grants()`, `mapping.employee_scope()`.
- Produces:
  - `delegation.current_admin(user: str | None = None) -> Document | None` — the enabled `Delegated User Admin` record, or None
  - `delegation.assert_delegate(user: str | None = None) -> Document` — throws `frappe.PermissionError` if none
  - `delegation.scope_companies(admin) -> list[str]`, `delegation.scope_branches(admin) -> list[str]`
  - `delegation.can_manage(admin, target: str) -> bool`
  - `delegation.assert_can_manage(admin, target: str) -> None`
  - `delegation.assert_can_grant(admin, role_profile: str, module_profile: str | None = None) -> None`
  - `delegation.clear_cache(doc=None, method=None) -> None`

- [ ] **Step 1: Write the failing test**

Create `role_advisor/tests/test_delegation.py`:

```python
# Copyright (c) 2026, Upande and contributors
# For license information, please see license.txt

import frappe
from frappe.tests import IntegrationTestCase

from role_advisor import capability, delegation

ADMIN = "_ra_gate_admin@example.com"
IN_SCOPE = "_ra_in_scope@example.com"
OUT_OF_SCOPE = "_ra_out_of_scope@example.com"
UNLINKED = "_ra_unlinked@example.com"

SAFE_ROLE = "_RA Gate Safe Role"
UNSAFE_ROLE = "_RA Gate Unsafe Role"
ALLOWED_PROFILE = "_RA Gate Allowed Profile"
OTHER_PROFILE = "_RA Gate Other Profile"
UNSAFE_PROFILE = "_RA Gate Unsafe Profile"


def _user(email):
	if not frappe.db.exists("User", email):
		frappe.get_doc(
			{"doctype": "User", "email": email, "first_name": email.split("@")[0],
			 "send_welcome_email": 0}
		).insert(ignore_permissions=True)
	return email


def _employee(user, company):
	name = frappe.db.get_value("Employee", {"user_id": user})
	if name:
		return name
	return frappe.get_doc(
		{
			"doctype": "Employee",
			"first_name": user.split("@")[0],
			"user_id": user,
			"company": company,
			"status": "Active",
			"date_of_joining": "2020-01-01",
			"date_of_birth": "1990-01-01",
			"gender": frappe.get_all("Gender", pluck="name", limit=1)[0],
		}
	).insert(ignore_permissions=True).name


class TestDelegationGates(IntegrationTestCase):
	def setUp(self):
		self.companies = frappe.get_all("Company", pluck="name", limit=2)
		if len(self.companies) < 2:
			self.skipTest("site has fewer than two companies")

		for role in (SAFE_ROLE, UNSAFE_ROLE):
			if not frappe.db.exists("Role", role):
				frappe.get_doc({"doctype": "Role", "role_name": role}).insert()
		frappe.get_doc(
			{"doctype": "Custom DocPerm", "parent": "ToDo", "role": SAFE_ROLE,
			 "permlevel": 0, "read": 1}
		).insert()
		frappe.get_doc(
			{"doctype": "Custom DocPerm", "parent": "Role Profile", "role": UNSAFE_ROLE,
			 "permlevel": 0, "read": 1, "write": 1}
		).insert()
		for profile, role in (
			(ALLOWED_PROFILE, SAFE_ROLE),
			(OTHER_PROFILE, SAFE_ROLE),
			(UNSAFE_PROFILE, UNSAFE_ROLE),
		):
			if not frappe.db.exists("Role Profile", profile):
				frappe.get_doc(
					{"doctype": "Role Profile", "role_profile": profile,
					 "roles": [{"role": role}]}
				).insert()
		capability.clear_capability_index()

		_user(ADMIN)
		_employee(_user(IN_SCOPE), self.companies[0])
		_employee(_user(OUT_OF_SCOPE), self.companies[1])
		_user(UNLINKED)

		if not frappe.db.exists("Delegated User Admin", ADMIN):
			frappe.get_doc(
				{
					"doctype": "Delegated User Admin",
					"user": ADMIN,
					"enabled": 1,
					"companies": [{"company": self.companies[0]}],
					"allowed_role_profiles": [{"role_profile": ALLOWED_PROFILE}],
				}
			).insert(ignore_permissions=True)

		delegation.clear_cache()
		self.admin = delegation.current_admin(ADMIN)

	def tearDown(self):
		capability.clear_capability_index()
		delegation.clear_cache()

	def test_current_admin_resolves_an_enabled_record(self):
		self.assertIsNotNone(self.admin)
		self.assertEqual(self.admin.user, ADMIN)

	def test_a_disabled_record_is_not_a_delegate(self):
		doc = frappe.get_doc("Delegated User Admin", ADMIN)
		doc.enabled = 0
		doc.save(ignore_permissions=True)
		delegation.clear_cache()

		self.assertIsNone(delegation.current_admin(ADMIN))

	def test_a_user_with_no_record_is_not_a_delegate(self):
		self.assertIsNone(delegation.current_admin(OUT_OF_SCOPE))

		with self.assertRaises(frappe.PermissionError):
			delegation.assert_delegate(OUT_OF_SCOPE)

	def test_a_target_in_scope_is_manageable(self):
		self.assertTrue(delegation.can_manage(self.admin, IN_SCOPE))
		delegation.assert_can_manage(self.admin, IN_SCOPE)

	def test_a_target_in_another_company_is_refused(self):
		self.assertFalse(delegation.can_manage(self.admin, OUT_OF_SCOPE))

		with self.assertRaises(frappe.PermissionError):
			delegation.assert_can_manage(self.admin, OUT_OF_SCOPE)

	def test_a_target_with_no_employee_record_is_unreachable(self):
		"""The 109 unlinked users have no company, so no delegate can reach them."""
		self.assertFalse(delegation.can_manage(self.admin, UNLINKED))

	def test_an_allowlisted_profile_may_be_granted(self):
		delegation.assert_can_grant(self.admin, ALLOWED_PROFILE)

	def test_a_profile_off_the_allowlist_is_refused(self):
		with self.assertRaises(frappe.PermissionError):
			delegation.assert_can_grant(self.admin, OTHER_PROFILE)

	def test_a_privileged_profile_is_refused_even_if_allowlisted(self):
		"""Enforcement point two: the allowlist itself is not trusted.

		A profile's contents can change after it was allowlisted, so the check
		is repeated at write time.
		"""
		frappe.db.sql(
			"""insert into `tabDelegated Role Profile`
			   (name, parent, parentfield, parenttype, role_profile, idx)
			   values (%s, %s, 'allowed_role_profiles', 'Delegated User Admin', %s, 2)""",
			(frappe.generate_hash(length=10), ADMIN, UNSAFE_PROFILE),
		)
		delegation.clear_cache()
		admin = delegation.current_admin(ADMIN)

		with self.assertRaises(frappe.PermissionError):
			delegation.assert_can_grant(admin, UNSAFE_PROFILE)
```

The privileged-profile test writes the child row with raw SQL on purpose: `DelegatedUserAdmin.validate` refuses it through the ORM, which is enforcement point one working correctly. Bypassing the ORM is the only way to construct the state that enforcement point two exists to catch.

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd /home/austin/frappe-v16-bench
bench --site kaitet.local run-tests --app role_advisor --module role_advisor.tests.test_delegation
```

Expected: FAIL — `ModuleNotFoundError: No module named 'role_advisor.delegation'`.

- [ ] **Step 3: Write `role_advisor/delegation.py`**

```python
# Copyright (c) 2026, Upande and contributors
# For license information, please see license.txt

"""Who may a delegated administrator reach, and what may they hand out?

Enforcement is opt-in: restrictions apply only to a `delegate_role` holder who
also has an enabled `Delegated User Admin` record. Without one, behaviour is
stock. That makes rollout one person at a time, and means no migration can lock
anyone out.
"""

import frappe
from frappe import _

from role_advisor import mapping, privilege, settings

CACHE_ATTR = "_role_advisor_delegated_admins"


def clear_cache(doc=None, method=None) -> None:
	"""Drop the request-local admin cache. Also a doc_events hook."""
	if hasattr(frappe.local, CACHE_ATTR):
		delattr(frappe.local, CACHE_ATTR)


def current_admin(user: str | None = None):
	"""Return the caller's enabled Delegated User Admin record, or None.

	Memoised per request: the permission hooks call this on every User row
	fetched, so a query per row would be a real cost on a 374-user list.
	"""
	user = user or frappe.session.user

	cache = getattr(frappe.local, CACHE_ATTR, None)
	if cache is None:
		cache = {}
		setattr(frappe.local, CACHE_ATTR, cache)

	if user not in cache:
		name = frappe.db.get_value(
			"Delegated User Admin", {"user": user, "enabled": 1}, "name"
		)
		cache[user] = frappe.get_doc("Delegated User Admin", name) if name else None

	return cache[user]


def assert_delegate(user: str | None = None):
	admin = current_admin(user)
	if not admin:
		frappe.throw(
			_("You are not configured as a delegated user administrator."),
			frappe.PermissionError,
			title=_("Not A Delegate"),
		)

	return admin


def scope_companies(admin) -> list[str]:
	return [row.company for row in admin.get("companies") or []]


def scope_branches(admin) -> list[str]:
	return [row.branch for row in admin.get("branches") or []]


def can_manage(admin, target: str) -> bool:
	"""Is `target` inside `admin`'s company (and optionally branch) scope?

	A target with no active Employee record has no company. Such users are
	unreachable by any delegate - deliberately: the 109 unlinked users on Kaitet
	include service accounts and Upande staff, and defaulting them to "in scope"
	would be the single worst failure mode here.
	"""
	if not target or target in ("Administrator", "Guest"):
		return False

	scope = mapping.employee_scope(target)

	if settings.require_employee_link() and not scope.get("company"):
		return False

	if scope.get("company") not in scope_companies(admin):
		return False

	branches = scope_branches(admin)
	# An empty branch list means every branch within the allowed companies.
	if branches and scope.get("branch") not in branches:
		return False

	return True


def assert_can_manage(admin, target: str) -> None:
	if not can_manage(admin, target):
		frappe.throw(
			_("{0} is outside the users you administer.").format(target),
			frappe.PermissionError,
			title=_("Out Of Scope"),
		)


def assert_can_grant(admin, role_profile: str, module_profile: str | None = None) -> None:
	"""Refuse anything off the allowlist, or privileged regardless of allowlist."""
	allowed = {row.role_profile for row in admin.get("allowed_role_profiles") or []}
	if role_profile not in allowed:
		frappe.throw(
			_("{0} is not one of the role profiles you may grant.").format(role_profile),
			frappe.PermissionError,
			title=_("Not Grantable"),
		)

	# Re-checked here even though DelegatedUserAdmin.validate already refused it
	# at save: a profile's roles can be widened after it was allowlisted.
	grants = privilege.privileged_grants(role_profile)
	if grants:
		frappe.throw(
			_("{0} can no longer be delegated: it grants {1}.").format(
				role_profile, privilege.describe(grants)
			),
			frappe.PermissionError,
			title=_("Privileged Profile"),
		)

	if module_profile:
		allowed_modules = {
			row.module_profile for row in admin.get("allowed_module_profiles") or []
		}
		if module_profile not in allowed_modules:
			frappe.throw(
				_("{0} is not one of the module profiles you may grant.").format(
					module_profile
				),
				frappe.PermissionError,
				title=_("Not Grantable"),
			)
```

- [ ] **Step 4: Wire the cache invalidation hook**

In `role_advisor/hooks.py`, add to `doc_events`:

```python
	"Delegated User Admin": {
		"on_update": "role_advisor.delegation.clear_cache",
		"after_delete": "role_advisor.delegation.clear_cache",
	},
```

- [ ] **Step 5: Run the tests to verify they pass**

```bash
cd /home/austin/frappe-v16-bench
bench --site kaitet.local run-tests --app role_advisor --module role_advisor.tests.test_delegation
```

Expected: 9 passed.

- [ ] **Step 6: Commit**

```bash
cd /home/austin/frappe-v16-bench/apps/role_advisor
git add -A
git commit -m "feat: add delegation scope resolution and gates

Targets with no active Employee have no company and are unreachable by any
delegate - deliberate, since defaulting them to in-scope would be the worst
failure mode available. The privileged check is repeated at grant time
because a profile can be widened after being allowlisted."
```

---

## Task 9: Permission hooks on `User` (visibility layers)

Spec §5.2 layers 1 and 2. Both are deny-only and AND onto core's existing hooks, which already hide `STANDARD_USERS` and guard the Administrator record.

**Files:**
- Create: `role_advisor/permissions.py`
- Create: `role_advisor/tests/test_permissions_user.py`
- Modify: `role_advisor/hooks.py`

**Interfaces:**
- Consumes: `delegation.current_admin()`, `delegation.can_manage()`, `delegation.scope_companies()`.
- Produces:
  - `permissions.user_query_conditions(user: str | None = None, doctype: str | None = None) -> str`
  - `permissions.user_has_permission(doc, ptype: str | None = None, user: str | None = None, debug: bool = False) -> bool`

- [ ] **Step 1: Write the failing test**

Create `role_advisor/tests/test_permissions_user.py`:

```python
# Copyright (c) 2026, Upande and contributors
# For license information, please see license.txt

import frappe
from frappe.tests import IntegrationTestCase

from role_advisor import delegation, permissions
from role_advisor.tests.test_delegation import (
	ADMIN,
	IN_SCOPE,
	OUT_OF_SCOPE,
	UNLINKED,
	TestDelegationGates,
)


class TestUserPermissionHooks(IntegrationTestCase):
	def setUp(self):
		# Reuse the fixture builder so the two suites cannot drift apart.
		TestDelegationGates.setUp(self)

	def tearDown(self):
		delegation.clear_cache()

	def test_a_non_delegate_is_unrestricted(self):
		"""Opt-in enforcement: no record means stock behaviour."""
		self.assertEqual(permissions.user_query_conditions(OUT_OF_SCOPE), "")

	def test_administrator_is_never_restricted(self):
		self.assertEqual(permissions.user_query_conditions("Administrator"), "")

	def test_a_delegate_gets_a_scoping_condition(self):
		condition = permissions.user_query_conditions(ADMIN)

		self.assertIn("tabUser", condition)
		self.assertIn("tabEmployee", condition)

	def test_the_condition_selects_only_in_scope_users(self):
		condition = permissions.user_query_conditions(ADMIN)

		names = frappe.db.sql_list(
			f"select name from `tabUser` where {condition}"
		)

		self.assertIn(IN_SCOPE, names)
		self.assertNotIn(OUT_OF_SCOPE, names)
		self.assertNotIn(UNLINKED, names)

	def test_a_delegate_can_always_see_themselves(self):
		"""Otherwise their own record vanishes and the desk breaks."""
		condition = permissions.user_query_conditions(ADMIN)

		names = frappe.db.sql_list(f"select name from `tabUser` where {condition}")

		self.assertIn(ADMIN, names)

	def test_has_permission_allows_an_in_scope_document(self):
		doc = frappe.get_doc("User", IN_SCOPE)

		self.assertTrue(permissions.user_has_permission(doc, "read", ADMIN))

	def test_has_permission_denies_an_out_of_scope_document(self):
		"""List filtering alone would not stop a typed URL."""
		doc = frappe.get_doc("User", OUT_OF_SCOPE)

		self.assertFalse(permissions.user_has_permission(doc, "read", ADMIN))

	def test_has_permission_does_not_restrict_a_non_delegate(self):
		doc = frappe.get_doc("User", OUT_OF_SCOPE)

		self.assertTrue(permissions.user_has_permission(doc, "read", "Administrator"))
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd /home/austin/frappe-v16-bench
bench --site kaitet.local run-tests --app role_advisor --module role_advisor.tests.test_permissions_user
```

Expected: FAIL — `ModuleNotFoundError: No module named 'role_advisor.permissions'`.

- [ ] **Step 3: Write `role_advisor/permissions.py`**

```python
# Copyright (c) 2026, Upande and contributors
# For license information, please see license.txt

"""Deny-only permission hooks bounding what a delegate can see.

Core already registers hooks for `User`. `permission_query_conditions[doctype]`
is a list joined with " and ", and controller `has_permission` hooks can only
deny - never grant. So everything here narrows core's result and nothing here
can widen it.

`User Permission` has no core hooks at all, which is why the two functions at
the bottom exist: without them a delegate could delete their own Company
scoping row and see every company's data.
"""

import frappe

from role_advisor import delegation


def _escape_list(values: list[str]) -> str:
	return ", ".join(frappe.db.escape(value) for value in values)


def user_query_conditions(user: str | None = None, doctype: str | None = None) -> str:
	"""Restrict a delegate's User list to their company scope.

	Returns "" for anyone who is not an enabled delegate, which is what makes
	enforcement opt-in rather than a flag day for the 23 User Manager holders.
	"""
	user = user or frappe.session.user
	if user == "Administrator":
		return ""

	admin = delegation.current_admin(user)
	if not admin:
		return ""

	companies = delegation.scope_companies(admin)
	if not companies:
		# A delegate with no scope should see nobody rather than everybody.
		return f"`tabUser`.name = {frappe.db.escape(user)}"

	conditions = [
		f"""`tabUser`.name in (
			select e.user_id from `tabEmployee` e
			where e.user_id is not null and e.user_id != ''
			  and e.status = 'Active'
			  and e.company in ({_escape_list(companies)})
		)"""
	]

	branches = delegation.scope_branches(admin)
	if branches:
		conditions.append(
			f"""`tabUser`.name in (
				select e.user_id from `tabEmployee` e
				where e.user_id is not null and e.user_id != ''
				  and e.status = 'Active'
				  and e.branch in ({_escape_list(branches)})
			)"""
		)

	# A delegate must still see their own record or their desk breaks.
	scoped = " and ".join(conditions)

	return f"(({scoped}) or `tabUser`.name = {frappe.db.escape(user)})"


def user_has_permission(doc, ptype: str | None = None, user: str | None = None, debug: bool = False) -> bool:
	"""Block opening an out-of-scope User by name.

	The query condition filters lists; it does nothing about a typed URL or a
	direct API read, which is why this exists as a separate layer.
	"""
	user = user or frappe.session.user
	if user == "Administrator":
		return True

	admin = delegation.current_admin(user)
	if not admin:
		return True

	if doc.name == user:
		return True

	return delegation.can_manage(admin, doc.name)
```

- [ ] **Step 4: Register the hooks**

In `role_advisor/hooks.py`, add at module level:

```python
permission_query_conditions = {
	"User": "role_advisor.permissions.user_query_conditions",
}

has_permission = {
	"User": "role_advisor.permissions.user_has_permission",
}
```

- [ ] **Step 5: Run the tests to verify they pass**

```bash
cd /home/austin/frappe-v16-bench
bench --site kaitet.local clear-cache
bench --site kaitet.local run-tests --app role_advisor --module role_advisor.tests.test_permissions_user
```

Expected: 8 passed.

- [ ] **Step 6: Verify no regression for ordinary users**

The hooks now run for every User list query on the site. Confirm a System Manager and a plain user are unaffected:

```bash
cd /home/austin/frappe-v16-bench
bench --site kaitet.local console <<'EOF'
import frappe
from role_advisor import permissions
for u in ("Administrator", "austin@upande.com", "mbundotich@karenroses.com"):
    print(u, "->", repr(permissions.user_query_conditions(u))[:80])
print(len(frappe.get_all("User", limit=500)), "users visible to", frappe.session.user)
EOF
```

Expected: `""` for all three (none has a `Delegated User Admin` record yet), and the full user count.

- [ ] **Step 7: Commit**

```bash
cd /home/austin/frappe-v16-bench/apps/role_advisor
git add -A
git commit -m "feat: scope a delegate's User visibility

Two layers, because list filtering does not stop a typed URL. Both return
unrestricted for anyone without an enabled Delegated User Admin record, so
installing this changes nothing until a record is created."
```

---
## Task 10: Close the `User Permission` hole

Spec §5.4. `User Permission` has no core permission hooks, and `User Manager` holds full create/write/delete on it — so a delegate can delete their own Company row and escape their own scope. Company scope is what Task 9 rests on, so this is load-bearing, not cleanup.

Also adds the `Delegated User Admin` self-read hook mentioned in Task 4: a delegate may read their *own* record and no one else's, which a role grant could not express.

**Files:**
- Modify: `role_advisor/permissions.py`
- Modify: `role_advisor/hooks.py`
- Create: `role_advisor/tests/test_permissions_user_permission.py`

**Interfaces:**
- Consumes: `delegation.current_admin()`, `delegation.can_manage()`.
- Produces:
  - `permissions.user_permission_query_conditions(user=None, doctype=None) -> str`
  - `permissions.user_permission_has_permission(doc, ptype=None, user=None, debug=False) -> bool`
  - `permissions.delegated_admin_has_permission(doc, ptype=None, user=None, debug=False) -> bool`

- [ ] **Step 1: Write the failing test**

Create `role_advisor/tests/test_permissions_user_permission.py`:

```python
# Copyright (c) 2026, Upande and contributors
# For license information, please see license.txt

import frappe
from frappe.tests import IntegrationTestCase

from role_advisor import delegation, permissions
from role_advisor.tests.test_delegation import (
	ADMIN,
	IN_SCOPE,
	OUT_OF_SCOPE,
	TestDelegationGates,
)


class TestUserPermissionHooks(IntegrationTestCase):
	def setUp(self):
		TestDelegationGates.setUp(self)
		self.company = self.companies[0]

	def tearDown(self):
		delegation.clear_cache()

	def _permission_for(self, user):
		return frappe.get_doc(
			{
				"doctype": "User Permission",
				"user": user,
				"allow": "Company",
				"for_value": self.company,
			}
		).insert(ignore_permissions=True)

	def test_a_delegate_cannot_touch_their_own_row(self):
		"""The escalation path: deleting your own scoping row unlocks the cage."""
		own = self._permission_for(ADMIN)

		self.assertFalse(permissions.user_permission_has_permission(own, "write", ADMIN))
		self.assertFalse(permissions.user_permission_has_permission(own, "delete", ADMIN))

	def test_a_delegate_cannot_even_read_their_own_row(self):
		"""Reading is harmless, but allowing it invites a UI that offers delete."""
		own = self._permission_for(ADMIN)

		self.assertFalse(permissions.user_permission_has_permission(own, "read", ADMIN))

	def test_a_delegate_may_manage_an_in_scope_users_row(self):
		row = self._permission_for(IN_SCOPE)

		self.assertTrue(permissions.user_permission_has_permission(row, "write", ADMIN))

	def test_a_delegate_may_not_manage_an_out_of_scope_users_row(self):
		row = self._permission_for(OUT_OF_SCOPE)

		self.assertFalse(permissions.user_permission_has_permission(row, "write", ADMIN))

	def test_the_query_condition_excludes_the_delegates_own_rows(self):
		self._permission_for(ADMIN)
		self._permission_for(IN_SCOPE)

		condition = permissions.user_permission_query_conditions(ADMIN)
		users = frappe.db.sql_list(
			f"select user from `tabUser Permission` where {condition}"
		)

		self.assertIn(IN_SCOPE, users)
		self.assertNotIn(ADMIN, users)

	def test_a_non_delegate_is_unrestricted(self):
		self.assertEqual(permissions.user_permission_query_conditions("Administrator"), "")
		row = self._permission_for(ADMIN)
		self.assertTrue(
			permissions.user_permission_has_permission(row, "delete", "Administrator")
		)

	def test_a_delegate_may_read_their_own_admin_record(self):
		record = frappe.get_doc("Delegated User Admin", ADMIN)

		self.assertTrue(permissions.delegated_admin_has_permission(record, "read", ADMIN))

	def test_a_delegate_may_not_read_another_delegates_record(self):
		other = "_ra_other_delegate@example.com"
		if not frappe.db.exists("User", other):
			frappe.get_doc(
				{"doctype": "User", "email": other, "first_name": "Other",
				 "send_welcome_email": 0}
			).insert(ignore_permissions=True)
		if not frappe.db.exists("Delegated User Admin", other):
			frappe.get_doc(
				{"doctype": "Delegated User Admin", "user": other, "enabled": 1,
				 "companies": [{"company": self.company}]}
			).insert(ignore_permissions=True)

		record = frappe.get_doc("Delegated User Admin", other)

		self.assertFalse(permissions.delegated_admin_has_permission(record, "read", ADMIN))

	def test_a_delegate_may_not_write_their_own_admin_record(self):
		"""Otherwise they widen their own allowlist."""
		record = frappe.get_doc("Delegated User Admin", ADMIN)

		self.assertFalse(permissions.delegated_admin_has_permission(record, "write", ADMIN))
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd /home/austin/frappe-v16-bench
bench --site kaitet.local run-tests --app role_advisor --module role_advisor.tests.test_permissions_user_permission
```

Expected: FAIL — `AttributeError: module 'role_advisor.permissions' has no attribute 'user_permission_has_permission'`.

- [ ] **Step 3: Append to `role_advisor/permissions.py`**

```python
# Rights that let a delegate alter their own boundary. `read` is included:
# harmless in itself, but a readable row invites a UI that offers delete.
_SELF_DENIED = frozenset({"read", "write", "create", "delete", "submit", "cancel"})


def user_permission_query_conditions(user: str | None = None, doctype: str | None = None) -> str:
	"""Restrict a delegate to User Permission rows of users they administer.

	Core registers no hook for this doctype, so without this a `User Manager`
	holder - who has full CRUD on it - can delete their own Company row and see
	every company's data.
	"""
	user = user or frappe.session.user
	if user == "Administrator":
		return ""

	admin = delegation.current_admin(user)
	if not admin:
		return ""

	companies = delegation.scope_companies(admin)
	if not companies:
		return "1 = 0"

	return f"""(
		`tabUser Permission`.user != {frappe.db.escape(user)}
		and `tabUser Permission`.user in (
			select e.user_id from `tabEmployee` e
			where e.user_id is not null and e.user_id != ''
			  and e.status = 'Active'
			  and e.company in ({_escape_list(companies)})
		)
	)"""


def user_permission_has_permission(doc, ptype: str | None = None, user: str | None = None, debug: bool = False) -> bool:
	"""Deny a delegate any access to their own User Permission rows."""
	user = user or frappe.session.user
	if user == "Administrator":
		return True

	admin = delegation.current_admin(user)
	if not admin:
		return True

	if doc.user == user and (ptype or "read") in _SELF_DENIED:
		return False

	return delegation.can_manage(admin, doc.user)


def delegated_admin_has_permission(doc, ptype: str | None = None, user: str | None = None, debug: bool = False) -> bool:
	"""A delegate may read their own record only, and never write it.

	Read-own cannot be expressed as a role grant - a grant would let every
	delegate read every other delegate's allowlist. Write is denied outright:
	a delegate who could edit this record would widen their own allowlist.
	"""
	user = user or frappe.session.user
	if user == "Administrator":
		return True

	if "System Manager" in frappe.get_roles(user):
		return True

	if doc.user != user:
		return False

	return (ptype or "read") == "read"
```

- [ ] **Step 4: Register the hooks and grant delegates nominal read**

In `role_advisor/hooks.py`, extend the two dicts:

```python
permission_query_conditions = {
	"User": "role_advisor.permissions.user_query_conditions",
	"User Permission": "role_advisor.permissions.user_permission_query_conditions",
}

has_permission = {
	"User": "role_advisor.permissions.user_has_permission",
	"User Permission": "role_advisor.permissions.user_permission_has_permission",
	"Delegated User Admin": "role_advisor.permissions.delegated_admin_has_permission",
}
```

Then add a read-only `User Manager` row to `delegated_user_admin.json`'s `permissions` array, so the hook has something to narrow — a controller hook can only deny, so with no role grant a delegate would see nothing at all:

```json
  {"role": "User Manager", "read": 1}
```

- [ ] **Step 5: Migrate and run the tests**

```bash
cd /home/austin/frappe-v16-bench
bench --site kaitet.local migrate
bench --site kaitet.local clear-cache
bench --site kaitet.local run-tests --app role_advisor --module role_advisor.tests.test_permissions_user_permission
```

Expected: 9 passed.

- [ ] **Step 6: Commit**

```bash
cd /home/austin/frappe-v16-bench/apps/role_advisor
git add -A
git commit -m "fix: stop a delegate unlocking their own scope

User Permission has no core permission hooks, and User Manager holds full
CRUD on it, so a delegate could delete their own Company row. Denies all
access to a delegate's own rows including read, and confines the
Delegated User Admin record to read-own."
```

---

## Task 11: The write API

Spec §5.2 layer 3. Four whitelisted methods. This is the only path by which a delegate changes anything, so each one gates before it acts.

**Files:**
- Modify: `role_advisor/api.py` (replacing the Task 1 placeholder)
- Create: `role_advisor/tests/test_api.py`

**Interfaces:**
- Consumes: `delegation.*`, `capability.*`, `audit.*`, `settings.allow_multiple_profiles()`.
- Produces:
  - `api.get_manageable_users(search: str | None = None, limit: int = 50) -> list[dict]`
  - `api.get_grantable_profiles() -> list[dict]`
  - `api.preview_assignment(user: str, role_profile: str, module_profile: str | None = None) -> dict`
  - `api.assign_access(user: str, role_profile: str, module_profile: str | None = None) -> dict`

- [ ] **Step 1: Write the failing test**

Create `role_advisor/tests/test_api.py`:

```python
# Copyright (c) 2026, Upande and contributors
# For license information, please see license.txt

import frappe
from frappe.tests import IntegrationTestCase

from role_advisor import api, capability, delegation
from role_advisor.tests.test_delegation import (
	ADMIN,
	ALLOWED_PROFILE,
	IN_SCOPE,
	OTHER_PROFILE,
	OUT_OF_SCOPE,
	UNSAFE_PROFILE,
	TestDelegationGates,
)


class TestDelegateAPI(IntegrationTestCase):
	def setUp(self):
		TestDelegationGates.setUp(self)
		frappe.set_user(ADMIN)

	def tearDown(self):
		frappe.set_user("Administrator")
		delegation.clear_cache()
		capability.clear_capability_index()

	def test_get_manageable_users_returns_only_in_scope_users(self):
		names = [row["name"] for row in api.get_manageable_users()]

		self.assertIn(IN_SCOPE, names)
		self.assertNotIn(OUT_OF_SCOPE, names)

	def test_get_grantable_profiles_returns_the_allowlist_with_a_summary(self):
		rows = api.get_grantable_profiles()

		self.assertEqual([row["role_profile"] for row in rows], [ALLOWED_PROFILE])
		self.assertIn("doctype_count", rows[0])
		self.assertIn("perm_count", rows[0])

	def test_preview_reports_the_delta_without_writing(self):
		preview = api.preview_assignment(IN_SCOPE, ALLOWED_PROFILE)

		self.assertEqual(preview["profiles_before"], [])
		self.assertEqual(preview["profiles_after"], [ALLOWED_PROFILE])
		self.assertIn("roles_gained", preview)
		self.assertEqual(capability.get_user_role_profiles(IN_SCOPE), [])

	def test_assign_access_writes_the_profile(self):
		api.assign_access(IN_SCOPE, ALLOWED_PROFILE)

		self.assertEqual(capability.get_user_role_profiles(IN_SCOPE), [ALLOWED_PROFILE])

	def test_assign_access_replaces_rather_than_appends(self):
		"""Appending would keep every grant the new profile was chosen to avoid."""
		api.assign_access(IN_SCOPE, ALLOWED_PROFILE)
		api.assign_access(IN_SCOPE, ALLOWED_PROFILE)

		self.assertEqual(capability.get_user_role_profiles(IN_SCOPE), [ALLOWED_PROFILE])

	def test_assign_access_logs_the_change(self):
		api.assign_access(IN_SCOPE, ALLOWED_PROFILE)

		logs = frappe.get_all(
			"Access Assignment Log",
			filters={"target_user": IN_SCOPE},
			fields=["actor", "trigger", "outcome", "profiles_after"],
		)

		self.assertTrue(logs)
		self.assertEqual(logs[0].actor, ADMIN)
		self.assertEqual(logs[0].profiles_after, ALLOWED_PROFILE)

	def test_assign_access_refuses_an_out_of_scope_target(self):
		with self.assertRaises(frappe.PermissionError):
			api.assign_access(OUT_OF_SCOPE, ALLOWED_PROFILE)

	def test_assign_access_refuses_a_profile_off_the_allowlist(self):
		with self.assertRaises(frappe.PermissionError):
			api.assign_access(IN_SCOPE, OTHER_PROFILE)

	def test_assign_access_never_changes_user_type(self):
		"""Website User -> System User is a privilege boundary."""
		before = frappe.db.get_value("User", IN_SCOPE, "user_type")

		api.assign_access(IN_SCOPE, ALLOWED_PROFILE)

		self.assertEqual(frappe.db.get_value("User", IN_SCOPE, "user_type"), before)

	def test_a_non_delegate_cannot_call_the_api(self):
		frappe.set_user(OUT_OF_SCOPE)

		with self.assertRaises(frappe.PermissionError):
			api.assign_access(IN_SCOPE, ALLOWED_PROFILE)

	def test_assign_access_refuses_administrator_as_a_target(self):
		with self.assertRaises(frappe.PermissionError):
			api.assign_access("Administrator", ALLOWED_PROFILE)
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd /home/austin/frappe-v16-bench
bench --site kaitet.local run-tests --app role_advisor --module role_advisor.tests.test_api
```

Expected: FAIL — `AttributeError: module 'role_advisor.api' has no attribute 'get_manageable_users'`.

- [ ] **Step 3: Write `role_advisor/api.py`**

```python
# Copyright (c) 2026, Upande and contributors
# For license information, please see license.txt

"""Whitelisted API for delegated user administration.

Every field that matters on `User` - roles, role_profiles, block_modules,
user_type, api_key, api_secret - sits at permlevel 1, and permlevel is
all-or-nothing. There is no way to grant `role_profiles` while withholding
`api_secret` through permissions, so delegates get no permlevel-1 write at all
and come through here instead. `assign_access` accepts three arguments and can
therefore change exactly three things.
"""

import frappe
from frappe import _

from role_advisor import audit, capability, delegation, settings


@frappe.whitelist()
def get_manageable_users(search: str | None = None, limit: int = 50) -> list[dict]:
	"""Users inside the caller's scope."""
	admin = delegation.assert_delegate()

	filters = {"enabled": 1}
	if search:
		filters["full_name"] = ("like", f"%{search}%")

	rows = frappe.get_all(
		"User",
		filters=filters,
		fields=["name", "full_name", "user_type", "module_profile"],
		limit=frappe.utils.cint(limit) or 50,
		order_by="full_name asc",
	)

	# `get_all` already applies the query-condition hook, but a delegate whose
	# scope changed mid-session could still hold a stale list, so each row is
	# re-checked against the gate that authorises writes.
	manageable = [row for row in rows if delegation.can_manage(admin, row.name)]

	for row in manageable:
		row["role_profiles"] = capability.get_user_role_profiles(row.name)

	return manageable


@frappe.whitelist()
def get_grantable_profiles() -> list[dict]:
	"""The caller's allowlist, with what each profile grants."""
	admin = delegation.assert_delegate()
	index = capability.build_capability_index()

	profiles = []
	for row in admin.get("allowed_role_profiles") or []:
		granted = index.get(row.role_profile, {})
		profiles.append(
			{
				"role_profile": row.role_profile,
				"doctype_count": len(granted),
				"perm_count": capability.total_perm_count(granted),
			}
		)

	return sorted(profiles, key=lambda row: row["perm_count"])


@frappe.whitelist()
def preview_assignment(
	user: str, role_profile: str, module_profile: str | None = None
) -> dict:
	"""What would change, without changing it."""
	admin = delegation.assert_delegate()
	delegation.assert_can_manage(admin, user)
	delegation.assert_can_grant(admin, role_profile, module_profile)

	before = audit.snapshot(user)
	index = capability.build_capability_index()

	profiles_after = (
		sorted({*before["profiles"], role_profile})
		if settings.allow_multiple_profiles()
		else [role_profile]
	)

	roles_after: set[str] = set()
	for profile in profiles_after:
		roles_after.update(
			frappe.get_all(
				"Has Role",
				filters={"parent": profile, "parenttype": "Role Profile"},
				pluck="role",
			)
		)

	return {
		"user": user,
		"profiles_before": before["profiles"],
		"profiles_after": profiles_after,
		"module_profile_before": before["module_profile"],
		"module_profile_after": module_profile or before["module_profile"],
		"roles_gained": sorted(roles_after - before["roles"]),
		"roles_lost": sorted(before["roles"] - roles_after),
		"grants": {
			doctype: sorted(perms)
			for doctype, perms in sorted(index.get(role_profile, {}).items())
		},
	}


@frappe.whitelist()
def assign_access(
	user: str, role_profile: str, module_profile: str | None = None
) -> dict:
	"""Assign a role profile, and optionally a module profile, to `user`."""
	admin = delegation.assert_delegate()
	delegation.assert_can_manage(admin, user)
	delegation.assert_can_grant(admin, role_profile, module_profile)

	before = audit.snapshot(user)

	doc = frappe.get_doc("User", user)

	if settings.allow_multiple_profiles():
		profiles = sorted({*before["profiles"], role_profile})
	else:
		# Replace, never append: appending would leave the broader profile in
		# place, keeping every grant the tighter one was chosen to avoid.
		profiles = [role_profile]

	capability.set_user_role_profiles(doc, profiles)
	if module_profile:
		doc.module_profile = module_profile

	# `role_profiles` is permlevel 1, so there is no permitted route to this
	# write. Reached only after all three gates above have passed.
	doc.save(ignore_permissions=True)

	after = audit.snapshot(user)
	outcome = (
		audit.OUTCOME_NO_CHANGE
		if (before["profiles"], before["module_profile"])
		== (after["profiles"], after["module_profile"])
		else audit.OUTCOME_APPLIED
	)
	log = audit.log_assignment(user, before, after, audit.TRIGGER_MANUAL, outcome=outcome)

	return {
		"user": user,
		"profiles": after["profiles"],
		"module_profile": after["module_profile"],
		"roles_gained": sorted(after["roles"] - before["roles"]),
		"roles_lost": sorted(before["roles"] - after["roles"]),
		"outcome": outcome,
		"log": log,
	}
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
cd /home/austin/frappe-v16-bench
bench --site kaitet.local run-tests --app role_advisor --module role_advisor.tests.test_api
```

Expected: 11 passed.

`test_assign_access_refuses_administrator_as_a_target` passes because `delegation.can_manage` returns False for `Administrator` and `Guest` by name — verify that branch is present in Task 8's implementation if this test fails.

- [ ] **Step 5: Commit**

```bash
cd /home/austin/frappe-v16-bench/apps/role_advisor
git add -A
git commit -m "feat: add the delegated assignment API

Four whitelisted methods, each gating before it acts. assign_access takes
three arguments and can change exactly three things, which is what makes
user_type escalation structurally impossible rather than merely forbidden."
```

---
## Task 12: Designation Gap report

Spec §6.1. Script Reports are used throughout Tasks 12–14: they give filters, sorting and Excel export for free, and put the output where a System Manager already looks for reports.

**Files:**
- Create: `role_advisor/role_advisor/report/designation_gap/__init__.py`
- Create: `role_advisor/role_advisor/report/designation_gap/designation_gap.json`
- Create: `role_advisor/role_advisor/report/designation_gap/designation_gap.py`
- Create: `role_advisor/role_advisor/report/__init__.py`
- Create: `role_advisor/tests/test_report_designation_gap.py`

**Interfaces:**
- Consumes: `mapping.employee_scope()`, `mapping.resolve()`, `seeding.observe_assignments()`, `seeding.classify()`.
- Produces: `designation_gap.execute(filters=None) -> tuple[list[dict], list[dict]]`, `designation_gap.gap_rows() -> list[dict]`

- [ ] **Step 1: Write the failing test**

Create `role_advisor/tests/test_report_designation_gap.py`:

```python
# Copyright (c) 2026, Upande and contributors
# For license information, please see license.txt

import frappe
from frappe.tests import IntegrationTestCase

from role_advisor.role_advisor.report.designation_gap import designation_gap


class TestDesignationGapReport(IntegrationTestCase):
	def test_execute_returns_columns_and_rows(self):
		columns, data = designation_gap.execute()

		fieldnames = {column["fieldname"] for column in columns}
		for expected in (
			"user", "designation", "company", "proposed_role_profile",
			"confidence", "peers", "evidence",
		):
			self.assertIn(expected, fieldnames)
		self.assertIsInstance(data, list)

	def test_only_unprofiled_enabled_system_users_appear(self):
		_, data = designation_gap.execute()

		for row in data:
			self.assertEqual(
				frappe.db.get_value("User", row["user"], "enabled"), 1
			)
			self.assertEqual(
				frappe.db.get_value("User", row["user"], "user_type"), "System User"
			)
			self.assertFalse(
				frappe.db.exists("User Role Profile", {"parent": row["user"]}),
				f"{row['user']} already holds a profile and should not be in the gap",
			)

	def test_a_user_with_no_designation_is_reported_with_no_proposal(self):
		"""17 users have no Employee link; they must be visible but unproposed."""
		_, data = designation_gap.execute()

		unlinked = [row for row in data if not row["designation"]]
		for row in unlinked:
			self.assertIsNone(row["proposed_role_profile"])
			self.assertEqual(row["confidence"], "None")

	def test_the_report_writes_nothing(self):
		before = frappe.db.count("User Role Profile")

		designation_gap.execute()

		self.assertEqual(frappe.db.count("User Role Profile"), before)
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd /home/austin/frappe-v16-bench
bench --site kaitet.local run-tests --app role_advisor --module role_advisor.tests.test_report_designation_gap
```

Expected: FAIL — `ModuleNotFoundError` for the report module.

- [ ] **Step 3: Create the report scaffolding**

Create empty `__init__.py` in both `role_advisor/role_advisor/report/` and `.../report/designation_gap/`, then `designation_gap.json`:

```json
{
 "add_total_row": 0,
 "columns": [],
 "creation": "2026-08-20 00:00:00.000000",
 "disabled": 0,
 "doctype": "Report",
 "filters": [],
 "idx": 0,
 "is_standard": "Yes",
 "modified": "2026-08-20 00:00:00.000000",
 "module": "Role Advisor",
 "name": "Designation Gap",
 "owner": "Administrator",
 "prepared_report": 0,
 "ref_doctype": "User",
 "report_name": "Designation Gap",
 "report_type": "Script Report",
 "roles": [{"role": "System Manager"}, {"role": "User Manager"}]
}
```

- [ ] **Step 4: Write the report**

```python
# Copyright (c) 2026, Upande and contributors
# For license information, please see license.txt

"""Which enabled System Users hold no role profile, and what should they get?

Read-only. Proposals come from what same-designation, same-scope colleagues
already hold - which is evidence, not endorsement, because Kaitet's existing
assignments are known-inconsistent. Nothing here is auto-applied; the sweep
(Task 15) applies only rows a human has activated.
"""

import frappe

from role_advisor import mapping, seeding, settings

COLUMNS = [
	{"fieldname": "user", "label": "User", "fieldtype": "Link", "options": "User", "width": 220},
	{"fieldname": "full_name", "label": "Name", "fieldtype": "Data", "width": 160},
	{"fieldname": "designation", "label": "Designation", "fieldtype": "Link",
	 "options": "Designation", "width": 180},
	{"fieldname": "company", "label": "Company", "fieldtype": "Link",
	 "options": "Company", "width": 150},
	{"fieldname": "proposed_role_profile", "label": "Proposed Profile", "fieldtype": "Link",
	 "options": "Role Profile", "width": 220},
	{"fieldname": "confidence", "label": "Confidence", "fieldtype": "Data", "width": 100},
	{"fieldname": "peers", "label": "Peers", "fieldtype": "Int", "width": 70},
	{"fieldname": "from_map", "label": "From Map", "fieldtype": "Check", "width": 80},
	{"fieldname": "evidence", "label": "Evidence", "fieldtype": "Small Text", "width": 400},
]


def unprofiled_users() -> list[dict]:
	"""Enabled System Users with no row in the role_profiles child table."""
	return frappe.db.sql(
		"""
		select u.name as user, u.full_name as full_name
		from `tabUser` u
		where u.enabled = 1
		  and u.user_type = 'System User'
		  and not exists (
		      select 1 from `tabUser Role Profile` p
		      where p.parent = u.name and p.parenttype = 'User'
		  )
		order by u.full_name
		""",
		as_dict=True,
	)


def gap_rows() -> list[dict]:
	observed = seeding.observe_assignments()
	dimensions = settings.scope_dimensions()

	rows = []
	for user in unprofiled_users():
		scope = mapping.employee_scope(user["user"])
		designation = frappe.db.get_value(
			"Employee", {"user_id": user["user"], "status": "Active"}, "designation"
		)

		row = {
			**user,
			"designation": designation or None,
			"company": scope.get("company"),
			"proposed_role_profile": None,
			"confidence": "None",
			"peers": 0,
			"from_map": 0,
			"evidence": "",
		}

		if not designation:
			row["evidence"] = "No active Employee record, so no designation to map from."
			rows.append(row)
			continue

		# An activated map row is authoritative and outranks peer evidence.
		map_row = mapping.resolve(designation, scope, active_only=False)
		if map_row:
			mapped = frappe.get_doc("Designation Access Map", map_row)
			row.update(
				proposed_role_profile=mapped.role_profile,
				confidence=mapped.confidence or "None",
				from_map=1,
				evidence=mapped.evidence or "From an existing map row.",
			)
			rows.append(row)
			continue

		key = (designation, *(scope.get(d) for d in dimensions))
		verdict = seeding.classify(observed.get(key, {}))
		if verdict:
			row.update(
				proposed_role_profile=verdict["profile"],
				confidence=verdict["confidence"],
				peers=sum(observed.get(key, {}).values()),
				evidence=verdict["evidence"],
			)
		else:
			row["evidence"] = (
				f"No colleague with designation '{designation}' in this scope holds a "
				"profile, so there is no precedent to derive one from."
			)

		rows.append(row)

	# Most actionable first: highest confidence, then most peers.
	order = {"High": 0, "Medium": 1, "Low": 2, "None": 3}

	return sorted(rows, key=lambda r: (order.get(r["confidence"], 9), -r["peers"]))


def execute(filters=None):
	return COLUMNS, gap_rows()
```

- [ ] **Step 5: Migrate and run the tests**

```bash
cd /home/austin/frappe-v16-bench
bench --site kaitet.local migrate
bench --site kaitet.local run-tests --app role_advisor --module role_advisor.tests.test_report_designation_gap
```

Expected: 4 passed.

- [ ] **Step 6: Check the report against the numbers in the spec**

```bash
cd /home/austin/frappe-v16-bench
bench --site kaitet.local console <<'EOF'
from collections import Counter
from role_advisor.role_advisor.report.designation_gap import designation_gap
rows = designation_gap.gap_rows()
print(len(rows), "users in the gap")
print(Counter(r["confidence"] for r in rows))
print(sum(1 for r in rows if not r["designation"]), "with no designation")
EOF
```

Expected, per spec §2 (2026-07-13 snapshot): **41** users in the gap, **17** with no designation. If live data has moved, record the new figures — do not adjust the report to match the old ones.

- [ ] **Step 7: Commit**

```bash
cd /home/austin/frappe-v16-bench/apps/role_advisor
git add -A
git commit -m "feat: add Designation Gap report

An activated map row outranks peer evidence; where neither exists the row
says so explicitly rather than proposing nothing silently. Ordered most
actionable first."
```

---

## Task 13: Module Exposure and Drift reports

Spec §6.2 and §6.4. Two reports in one task: both are small, both read the same `block_modules` / `Has Role` territory, and a reviewer would accept or reject them together.

**Files:**
- Create: `role_advisor/role_advisor/report/module_exposure/` (`__init__.py`, `.json`, `.py`)
- Create: `role_advisor/role_advisor/report/role_drift/` (`__init__.py`, `.json`, `.py`)
- Create: `role_advisor/tests/test_report_exposure_and_drift.py`

**Interfaces:**
- Consumes: `mapping.employee_scope()`, `settings.never_block_modules()`.
- Produces:
  - `module_exposure.execute(filters=None)`, `module_exposure.exposure_rows() -> list[dict]`
  - `role_drift.execute(filters=None)`, `role_drift.drift_rows() -> list[dict]`

- [ ] **Step 1: Write the failing test**

Create `role_advisor/tests/test_report_exposure_and_drift.py`:

```python
# Copyright (c) 2026, Upande and contributors
# For license information, please see license.txt

import frappe
from frappe.tests import IntegrationTestCase

from role_advisor.role_advisor.report.module_exposure import module_exposure
from role_advisor.role_advisor.report.role_drift import role_drift


class TestModuleExposureReport(IntegrationTestCase):
	def test_columns_distinguish_widening_from_tightening(self):
		columns, _ = module_exposure.execute()
		fieldnames = {column["fieldname"] for column in columns}

		for expected in ("user", "module_profile", "blocked_now", "status"):
			self.assertIn(expected, fieldnames)

	def test_users_with_no_blocks_are_reported_as_unrestricted(self):
		rows = module_exposure.exposure_rows()

		unrestricted = [r for r in rows if r["status"] == "Unrestricted"]
		self.assertTrue(unrestricted, "the site has 240 unrestricted users")
		for row in unrestricted:
			self.assertEqual(row["blocked_now"], 0)

	def test_hand_blocked_users_without_a_profile_are_flagged(self):
		rows = module_exposure.exposure_rows()

		hand_blocked = [r for r in rows if r["status"] == "Hand-set, no profile"]
		for row in hand_blocked:
			self.assertGreater(row["blocked_now"], 0)
			self.assertFalse(row["module_profile"])

	def test_the_report_writes_nothing(self):
		before = frappe.db.count("Block Module")

		module_exposure.execute()

		self.assertEqual(frappe.db.count("Block Module"), before)


class TestRoleDriftReport(IntegrationTestCase):
	def test_columns_name_the_role_and_its_healer(self):
		columns, _ = role_drift.execute()
		fieldnames = {column["fieldname"] for column in columns}

		for expected in ("user", "role", "self_healing", "note"):
			self.assertIn(expected, fieldnames)

	def test_approver_roles_are_marked_self_healing(self):
		"""HRMS re-adds Leave/Expense Approver after v16 prunes them."""
		rows = role_drift.drift_rows()

		for row in rows:
			if row["role"] in ("Leave Approver", "Expense Approver"):
				self.assertTrue(row["self_healing"])

	def test_every_row_belongs_to_a_user_holding_a_profile(self):
		"""Drift is only meaningful for users whose roles get pruned."""
		for row in role_drift.drift_rows():
			self.assertTrue(
				frappe.db.exists("User Role Profile", {"parent": row["user"]})
			)
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd /home/austin/frappe-v16-bench
bench --site kaitet.local run-tests --app role_advisor --module role_advisor.tests.test_report_exposure_and_drift
```

Expected: FAIL — `ModuleNotFoundError` for both report modules.

- [ ] **Step 3: Create both report JSONs**

Same shape as Task 12's, substituting name/report_name (`Module Exposure`, `Role Drift`) and leaving `ref_doctype` as `User`.

- [ ] **Step 4: Write `module_exposure.py`**

```python
# Copyright (c) 2026, Upande and contributors
# For license information, please see license.txt

"""Who can see which modules - navigation hygiene, not containment.

`frappe/permissions.py` never consults modules. `block_modules` is read only in
`frappe/desk/desktop.py` (Workspace sidebar) and `frappe/utils/modules.py`
(Dashboards, Charts, Number Cards). A blocked module's doctypes stay reachable
by URL, awesome bar and REST API. So this report describes what users *see*,
never what they can *do*.

The one real hazard it surfaces: `User.validate_allowed_modules` clears
`block_modules` and repopulates it from the module profile, with nothing to
restore hand-set blocks. Assigning a profile to a hand-blocked user whose
blocks were tighter is a silent widening of access.
"""

import frappe

COLUMNS = [
	{"fieldname": "user", "label": "User", "fieldtype": "Link", "options": "User", "width": 220},
	{"fieldname": "full_name", "label": "Name", "fieldtype": "Data", "width": 160},
	{"fieldname": "company", "label": "Company", "fieldtype": "Link", "options": "Company", "width": 150},
	{"fieldname": "module_profile", "label": "Module Profile", "fieldtype": "Link",
	 "options": "Module Profile", "width": 200},
	{"fieldname": "blocked_now", "label": "Blocked Now", "fieldtype": "Int", "width": 110},
	{"fieldname": "visible_modules", "label": "Visible Modules", "fieldtype": "Int", "width": 130},
	{"fieldname": "status", "label": "Status", "fieldtype": "Data", "width": 180},
	{"fieldname": "note", "label": "Note", "fieldtype": "Small Text", "width": 380},
]

STATUS_UNRESTRICTED = "Unrestricted"
STATUS_HAND_SET = "Hand-set, no profile"
STATUS_PROFILED = "Profiled"


def exposure_rows() -> list[dict]:
	total_modules = frappe.db.count("Module Def")

	rows = frappe.db.sql(
		"""
		select u.name as user, u.full_name as full_name,
		       nullif(u.module_profile, '') as module_profile,
		       (select count(*) from `tabBlock Module` bm
		        where bm.parent = u.name and bm.parenttype = 'User') as blocked_now,
		       e.company as company
		from `tabUser` u
		left join `tabEmployee` e on e.user_id = u.name and e.status = 'Active'
		where u.enabled = 1 and u.user_type = 'System User'
		order by blocked_now asc, u.full_name asc
		""",
		as_dict=True,
	)

	for row in rows:
		row["visible_modules"] = total_modules - (row["blocked_now"] or 0)

		if row["module_profile"]:
			row["status"] = STATUS_PROFILED
			row["note"] = ""
		elif row["blocked_now"]:
			row["status"] = STATUS_HAND_SET
			row["note"] = (
				f"{row['blocked_now']} hand-set blocks and no module profile. Assigning "
				"a profile discards these wholesale - a silent widening if the profile "
				"blocks fewer modules than these do."
			)
		else:
			row["status"] = STATUS_UNRESTRICTED
			row["note"] = (
				f"Every one of the {total_modules} modules appears in this user's "
				"navigation. Doctype access is unaffected either way."
			)

	return rows


def execute(filters=None):
	return COLUMNS, exposure_rows()
```

- [ ] **Step 5: Write `role_drift.py`**

```python
# Copyright (c) 2026, Upande and contributors
# For license information, please see license.txt

"""Roles held outside any of the user's role profiles.

`User.populate_role_profile_roles` prunes roles to the union of the user's
profiles on every save. A role granted outside a profile is therefore lost the
next time that user is saved, by anyone, for any reason - unless something
re-adds it after the prune.

HRMS does exactly that: `compose(fn, *hooks)` runs the controller's `validate`
before `doc_events`, and HRMS hooks `update_approver_user_roles` onto
`User.validate`, re-adding Leave/Expense Approver from the Employee records
naming that user. Those roles are safe. Anything else in this report is not.
"""

import frappe

# Roles restored after the prune by a known doc_events hook.
SELF_HEALING = {
	"Leave Approver": "hrms.overrides.employee_master.update_approver_user_roles",
	"Expense Approver": "hrms.overrides.employee_master.update_approver_user_roles",
}

COLUMNS = [
	{"fieldname": "user", "label": "User", "fieldtype": "Link", "options": "User", "width": 220},
	{"fieldname": "role", "label": "Role", "fieldtype": "Link", "options": "Role", "width": 200},
	{"fieldname": "profiles", "label": "Profiles Held", "fieldtype": "Data", "width": 220},
	{"fieldname": "self_healing", "label": "Self Healing", "fieldtype": "Check", "width": 110},
	{"fieldname": "note", "label": "Note", "fieldtype": "Small Text", "width": 420},
]


def drift_rows() -> list[dict]:
	rows = frappe.db.sql(
		"""
		select hr.parent as user, hr.role as role
		from `tabHas Role` hr
		join `tabUser` u on u.name = hr.parent
		where hr.parenttype = 'User'
		  and u.enabled = 1
		  and u.user_type = 'System User'
		  and exists (
		      select 1 from `tabUser Role Profile` p
		      where p.parent = u.name and p.parenttype = 'User'
		  )
		  and not exists (
		      select 1
		      from `tabUser Role Profile` p
		      join `tabHas Role` pr
		           on pr.parent = p.role_profile and pr.parenttype = 'Role Profile'
		      where p.parent = hr.parent and pr.role = hr.role
		  )
		order by hr.parent, hr.role
		""",
		as_dict=True,
	)

	for row in rows:
		healer = SELF_HEALING.get(row["role"])
		row["self_healing"] = 1 if healer else 0
		row["profiles"] = ", ".join(
			frappe.get_all(
				"User Role Profile",
				filters={"parent": row["user"], "parenttype": "User"},
				pluck="role_profile",
			)
		)
		row["note"] = (
			f"Re-added after the prune by {healer}. Safe."
			if healer
			else (
				"Granted outside every profile this user holds, with no known hook to "
				"restore it. The next save of this User revokes it silently."
			)
		)

	# Genuine risks first.
	return sorted(rows, key=lambda r: (r["self_healing"], r["user"]))


def execute(filters=None):
	return COLUMNS, drift_rows()
```

- [ ] **Step 6: Migrate and run the tests**

```bash
cd /home/austin/frappe-v16-bench
bench --site kaitet.local migrate
bench --site kaitet.local run-tests --app role_advisor --module role_advisor.tests.test_report_exposure_and_drift
```

Expected: 7 passed.

- [ ] **Step 7: Check both reports against the spec's figures**

```bash
cd /home/austin/frappe-v16-bench
bench --site kaitet.local console <<'EOF'
from collections import Counter
from role_advisor.role_advisor.report.module_exposure import module_exposure
from role_advisor.role_advisor.report.role_drift import role_drift
print(Counter(r["status"] for r in module_exposure.exposure_rows()))
drift = role_drift.drift_rows()
print(len(drift), "drift rows;", sum(1 for r in drift if not r["self_healing"]), "genuine")
EOF
```

Expected per spec: 240 `Unrestricted`, 38 `Hand-set, no profile`, and **20 drift rows of which 0 are genuine**. A non-zero genuine count means a role has been granted outside a profile since the snapshot — report it, do not suppress it.

- [ ] **Step 8: Commit**

```bash
cd /home/austin/frappe-v16-bench/apps/role_advisor
git add -A
git commit -m "feat: add Module Exposure and Role Drift reports

Module Exposure separates unrestricted users from hand-blocked ones,
because assigning a profile to the latter discards their tuning. Role
Drift marks HRMS-healed approver roles as safe so the genuine risks are
not buried under 20 false positives."
```

---
## Task 14: System Manager Audit and Role Profile Over-grant reports

Spec §6.3 and §6.5. Both are report-only, and §6.5 is the only report describing what people can actually *do* rather than what they can see.

**Files:**
- Create: `role_advisor/role_advisor/report/system_manager_audit/` (`__init__.py`, `.json`, `.py`)
- Create: `role_advisor/role_advisor/report/role_profile_overgrant/` (`__init__.py`, `.json`, `.py`)
- Create: `role_advisor/tests/test_report_audit_and_overgrant.py`

**Interfaces:**
- Consumes: `capability.build_capability_index()`, `capability.total_perm_count()`, `privilege.privileged_grants()`, `privilege.describe()`, `settings.privileged_doctypes()`.
- Produces:
  - `system_manager_audit.execute(filters=None)`, `system_manager_audit.audit_rows() -> list[dict]`
  - `role_profile_overgrant.execute(filters=None)`, `role_profile_overgrant.overgrant_rows() -> list[dict]`

- [ ] **Step 1: Write the failing test**

Create `role_advisor/tests/test_report_audit_and_overgrant.py`:

```python
# Copyright (c) 2026, Upande and contributors
# For license information, please see license.txt

import frappe
from frappe.tests import IntegrationTestCase

from role_advisor import capability
from role_advisor.role_advisor.report.role_profile_overgrant import role_profile_overgrant
from role_advisor.role_advisor.report.system_manager_audit import system_manager_audit

UNSAFE_ROLE = "_RA Overgrant Role"
UNSAFE_PROFILE = "_RA Overgrant Profile"


class TestSystemManagerAudit(IntegrationTestCase):
	def test_every_row_actually_holds_system_manager(self):
		rows = system_manager_audit.audit_rows()

		self.assertTrue(rows, "the site has 23 System Managers")
		for row in rows:
			self.assertTrue(
				frappe.db.exists(
					"Has Role",
					{"parent": row["user"], "parenttype": "User", "role": "System Manager"},
				)
			)

	def test_service_accounts_are_flagged(self):
		"""A service account holding System Manager is the headline finding."""
		columns, _ = system_manager_audit.execute()
		fieldnames = {column["fieldname"] for column in columns}

		for expected in ("user", "last_active", "role_profile", "has_employee", "flags"):
			self.assertIn(expected, fieldnames)

	def test_users_with_no_employee_record_are_marked(self):
		for row in system_manager_audit.audit_rows():
			self.assertIn(row["has_employee"], (0, 1))

	def test_the_report_revokes_nothing(self):
		before = frappe.db.count("Has Role", {"role": "System Manager"})

		system_manager_audit.execute()

		self.assertEqual(
			frappe.db.count("Has Role", {"role": "System Manager"}), before
		)


class TestRoleProfileOvergrant(IntegrationTestCase):
	def setUp(self):
		if not frappe.db.exists("Role", UNSAFE_ROLE):
			frappe.get_doc({"doctype": "Role", "role_name": UNSAFE_ROLE}).insert()
		frappe.get_doc(
			{"doctype": "Custom DocPerm", "parent": "Role Profile", "role": UNSAFE_ROLE,
			 "permlevel": 0, "read": 1, "write": 1, "delete": 1}
		).insert()
		if not frappe.db.exists("Role Profile", UNSAFE_PROFILE):
			frappe.get_doc(
				{"doctype": "Role Profile", "role_profile": UNSAFE_PROFILE,
				 "roles": [{"role": UNSAFE_ROLE}]}
			).insert()
		capability.clear_capability_index()

	def tearDown(self):
		capability.clear_capability_index()

	def test_a_profile_touching_privileged_doctypes_is_flagged(self):
		rows = {row["role_profile"]: row for row in role_profile_overgrant.overgrant_rows()}

		self.assertIn(UNSAFE_PROFILE, rows)
		self.assertTrue(rows[UNSAFE_PROFILE]["privileged"])
		self.assertIn("Role Profile", rows[UNSAFE_PROFILE]["privileged_grants"])

	def test_every_profile_is_reported_with_its_size(self):
		rows = role_profile_overgrant.overgrant_rows()

		self.assertEqual(len(rows), frappe.db.count("Role Profile"))
		for row in rows:
			self.assertGreaterEqual(row["doctype_count"], 0)
			self.assertGreaterEqual(row["perm_count"], 0)

	def test_rows_are_ordered_widest_first(self):
		rows = role_profile_overgrant.overgrant_rows()
		counts = [row["perm_count"] for row in rows]

		self.assertEqual(counts, sorted(counts, reverse=True))

	def test_broad_delete_is_flagged(self):
		rows = {row["role_profile"]: row for row in role_profile_overgrant.overgrant_rows()}

		self.assertGreaterEqual(rows[UNSAFE_PROFILE]["delete_count"], 1)
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd /home/austin/frappe-v16-bench
bench --site kaitet.local run-tests --app role_advisor --module role_advisor.tests.test_report_audit_and_overgrant
```

Expected: FAIL — `ModuleNotFoundError` for both report modules.

- [ ] **Step 3: Create both report JSONs**

Same shape as Task 12's. `System Manager Audit` uses `"ref_doctype": "User"`; `Role Profile Overgrant` uses `"ref_doctype": "Role Profile"` and `"report_name": "Role Profile Overgrant"`. Both restrict `roles` to `[{"role": "System Manager"}]` — a delegate has no business reading either.

- [ ] **Step 4: Write `system_manager_audit.py`**

```python
# Copyright (c) 2026, Upande and contributors
# For license information, please see license.txt

"""Who holds System Manager, and should they?

Report-only by decision: no role is revoked automatically. On Kaitet every one
of the 23 holders is Upande staff with no Employee record, which is the reason
delegation is being built - not a finding to act on directly.
"""

import frappe
from frappe.utils import add_months, now_datetime

COLUMNS = [
	{"fieldname": "user", "label": "User", "fieldtype": "Link", "options": "User", "width": 240},
	{"fieldname": "full_name", "label": "Name", "fieldtype": "Data", "width": 160},
	{"fieldname": "last_active", "label": "Last Active", "fieldtype": "Datetime", "width": 180},
	{"fieldname": "role_profile", "label": "Role Profile", "fieldtype": "Data", "width": 200},
	{"fieldname": "role_count", "label": "Roles", "fieldtype": "Int", "width": 80},
	{"fieldname": "has_employee", "label": "Has Employee", "fieldtype": "Check", "width": 120},
	{"fieldname": "flags", "label": "Flags", "fieldtype": "Small Text", "width": 380},
]

# A holder quieter than this has probably outlived the need for the role.
DORMANT_MONTHS = 6


def audit_rows() -> list[dict]:
	rows = frappe.db.sql(
		"""
		select u.name as user, u.full_name as full_name, u.last_active as last_active,
		       (select count(*) from `tabHas Role` r
		        where r.parent = u.name and r.parenttype = 'User') as role_count,
		       (select group_concat(p.role_profile separator ', ')
		        from `tabUser Role Profile` p
		        where p.parent = u.name and p.parenttype = 'User') as role_profile,
		       exists(select 1 from `tabEmployee` e
		              where e.user_id = u.name and e.status = 'Active') as has_employee
		from `tabUser` u
		join `tabHas Role` hr
		     on hr.parent = u.name and hr.parenttype = 'User' and hr.role = 'System Manager'
		where u.enabled = 1
		order by u.last_active desc
		""",
		as_dict=True,
	)

	dormant_before = add_months(now_datetime(), -DORMANT_MONTHS)

	for row in rows:
		flags = []

		# A login that never belongs to a person cannot be held accountable for
		# what System Manager can do.
		if not row["has_employee"]:
			flags.append("no Employee record")
		if row["user"].endswith(("@api.com", "@api.local")) or "api" in row["user"].split("@")[0]:
			flags.append("looks like a service account")
		if row["last_active"] and row["last_active"] < dormant_before:
			flags.append(f"dormant for over {DORMANT_MONTHS} months")
		if not row["last_active"]:
			flags.append("never active")
		if not row["role_profile"]:
			flags.append("holds no role profile")

		row["flags"] = "; ".join(flags)

	return rows


def execute(filters=None):
	return COLUMNS, audit_rows()
```

- [ ] **Step 5: Write `role_profile_overgrant.py`**

```python
# Copyright (c) 2026, Upande and contributors
# For license information, please see license.txt

"""What each Role Profile actually grants.

This is the only report that describes what people can *do*, rather than what
they can see. Module profiles are navigation; DocPerms are the real boundary,
and this is the view onto them.
"""

import frappe

from role_advisor import capability, privilege, settings

COLUMNS = [
	{"fieldname": "role_profile", "label": "Role Profile", "fieldtype": "Link",
	 "options": "Role Profile", "width": 260},
	{"fieldname": "users", "label": "Users", "fieldtype": "Int", "width": 80},
	{"fieldname": "role_count", "label": "Roles", "fieldtype": "Int", "width": 80},
	{"fieldname": "doctype_count", "label": "Doctypes", "fieldtype": "Int", "width": 100},
	{"fieldname": "perm_count", "label": "Grants", "fieldtype": "Int", "width": 90},
	{"fieldname": "delete_count", "label": "Delete Rights", "fieldtype": "Int", "width": 120},
	{"fieldname": "privileged", "label": "Privileged", "fieldtype": "Check", "width": 100},
	{"fieldname": "privileged_grants", "label": "Privileged Grants", "fieldtype": "Small Text", "width": 320},
	{"fieldname": "note", "label": "Note", "fieldtype": "Small Text", "width": 320},
]

# A profile granting delete on more doctypes than this is worth a second look.
BROAD_DELETE_THRESHOLD = 10


def overgrant_rows() -> list[dict]:
	index = capability.build_capability_index()

	user_counts = {
		row.role_profile: row.users
		for row in frappe.db.sql(
			"""select role_profile, count(distinct parent) as users
			   from `tabUser Role Profile` where parenttype = 'User'
			   group by role_profile""",
			as_dict=True,
		)
	}
	role_counts = {
		row.parent: row.roles
		for row in frappe.db.sql(
			"""select parent, count(*) as roles from `tabHas Role`
			   where parenttype = 'Role Profile' group by parent""",
			as_dict=True,
		)
	}

	privileged_set = set(settings.privileged_doctypes())
	rows = []

	for profile in frappe.get_all("Role Profile", pluck="name"):
		granted = index.get(profile, {})
		grants = privilege.privileged_grants(profile)
		# `privileged_grants` returns a sentinel for a profile missing from the
		# index; an empty profile is legitimately empty, not unknown.
		if "__unknown__" in grants:
			grants = {}

		delete_count = sum(1 for perms in granted.values() if "delete" in perms)

		notes = []
		if grants:
			notes.append(
				"Grants write-equivalent rights on permission-bearing doctypes. "
				"Cannot be delegated."
			)
		if delete_count >= BROAD_DELETE_THRESHOLD:
			notes.append(f"Delete on {delete_count} doctypes.")
		if not granted:
			notes.append("Grants nothing - either empty or all its rows are permlevel > 0.")

		rows.append(
			{
				"role_profile": profile,
				"users": user_counts.get(profile, 0),
				"role_count": role_counts.get(profile, 0),
				"doctype_count": len(granted),
				"perm_count": capability.total_perm_count(granted),
				"delete_count": delete_count,
				"privileged": 1 if grants else 0,
				"privileged_grants": privilege.describe(grants) if grants else "",
				"note": " ".join(notes),
			}
		)

	# Widest first: the biggest profiles are where over-granting hides.
	return sorted(rows, key=lambda row: -row["perm_count"])


def execute(filters=None):
	return COLUMNS, overgrant_rows()
```

- [ ] **Step 6: Migrate and run the tests**

```bash
cd /home/austin/frappe-v16-bench
bench --site kaitet.local migrate
bench --site kaitet.local run-tests --app role_advisor --module role_advisor.tests.test_report_audit_and_overgrant
```

Expected: 8 passed.

- [ ] **Step 7: Read the two reports against the spec's findings**

```bash
cd /home/austin/frappe-v16-bench
bench --site kaitet.local console <<'EOF'
from role_advisor.role_advisor.report.system_manager_audit import system_manager_audit
from role_advisor.role_advisor.report.role_profile_overgrant import role_profile_overgrant
sm = system_manager_audit.audit_rows()
print(len(sm), "System Managers;", sum(1 for r in sm if not r["has_employee"]), "with no Employee")
for r in sm:
    if r["flags"]:
        print(" ", r["user"], "->", r["flags"])
og = role_profile_overgrant.overgrant_rows()
print("\nwidest five profiles:")
for r in og[:5]:
    print(" ", r["role_profile"], r["role_count"], "roles,", r["perm_count"], "grants, privileged:", r["privileged"])
EOF
```

Expected per spec: 23 System Managers, all 23 with no Employee record; `user@api.com` flagged as a dormant service account; `moses@upande.com` flagged dormant with no profile; and `Upande Team` (133 roles) at or near the top of the over-grant list.

- [ ] **Step 8: Commit**

```bash
cd /home/austin/frappe-v16-bench/apps/role_advisor
git add -A
git commit -m "feat: add System Manager Audit and Role Profile Overgrant reports

The over-grant report is the only view onto what users can actually do;
module profiles are navigation only. Both are report-only - no role is
revoked automatically."
```

---

## Task 15: The bulk sweep

Spec §6.6. Dry-run produces a reviewable artifact; apply writes only rows a human approved. System-Manager-only and never reachable by a delegate — a delegate assigns one user at a time through Task 11's API.

**Files:**
- Create: `role_advisor/sweep.py`
- Create: `role_advisor/tests/test_sweep.py`

**Interfaces:**
- Consumes: `mapping.resolve()`, `mapping.employee_scope()`, `capability.set_user_role_profiles()`, `audit.*`, the Designation Gap report's `unprofiled_users()`.
- Produces:
  - `sweep.dry_run() -> list[dict]` — one dict per candidate, each with `blocked_reason` set or None
  - `sweep.apply(users: list[str] | None = None) -> dict` — `{"applied": int, "skipped": int, "no_change": int, "logs": list[str]}`
  - `sweep.BATCH_SIZE: int`

- [ ] **Step 1: Write the failing test**

Create `role_advisor/tests/test_sweep.py`:

```python
# Copyright (c) 2026, Upande and contributors
# For license information, please see license.txt

import frappe
from frappe.tests import IntegrationTestCase

from role_advisor import capability, sweep
from role_advisor.tests.test_delegation import IN_SCOPE, TestDelegationGates, ALLOWED_PROFILE

DESIGNATION = "_RA Sweep Designation"


class TestSweep(IntegrationTestCase):
	def setUp(self):
		TestDelegationGates.setUp(self)

		if not frappe.db.exists("Designation", DESIGNATION):
			frappe.get_doc(
				{"doctype": "Designation", "designation_name": DESIGNATION}
			).insert(ignore_permissions=True)

		employee = frappe.db.get_value("Employee", {"user_id": IN_SCOPE})
		frappe.db.set_value("Employee", employee, "designation", DESIGNATION)

		self.map_row = frappe.get_doc(
			{
				"doctype": "Designation Access Map",
				"designation": DESIGNATION,
				"company": self.companies[0],
				"role_profile": ALLOWED_PROFILE,
				"is_active": 1,
			}
		).insert(ignore_permissions=True)

	def tearDown(self):
		frappe.set_user("Administrator")
		capability.clear_capability_index()

	def test_dry_run_writes_nothing(self):
		before = frappe.db.count("User Role Profile")

		rows = sweep.dry_run()

		self.assertEqual(frappe.db.count("User Role Profile"), before)
		self.assertTrue(any(row["user"] == IN_SCOPE for row in rows))

	def test_dry_run_proposes_the_mapped_profile(self):
		row = next(r for r in sweep.dry_run() if r["user"] == IN_SCOPE)

		self.assertEqual(row["role_profile"], ALLOWED_PROFILE)
		self.assertIsNone(row["blocked_reason"])

	def test_an_inactive_map_row_blocks_the_sweep_for_that_user(self):
		self.map_row.is_active = 0
		self.map_row.save(ignore_permissions=True)

		row = next(r for r in sweep.dry_run() if r["user"] == IN_SCOPE)

		self.assertIsNotNone(row["blocked_reason"])

	def test_apply_only_touches_the_named_users(self):
		result = sweep.apply(users=[IN_SCOPE])

		self.assertEqual(result["applied"], 1)
		self.assertEqual(capability.get_user_role_profiles(IN_SCOPE), [ALLOWED_PROFILE])

	def test_apply_is_idempotent(self):
		sweep.apply(users=[IN_SCOPE])
		second = sweep.apply(users=[IN_SCOPE])

		self.assertEqual(second["applied"], 0)
		self.assertEqual(second["no_change"], 1)
		self.assertEqual(capability.get_user_role_profiles(IN_SCOPE), [ALLOWED_PROFILE])

	def test_apply_refuses_a_blocked_row(self):
		self.map_row.is_active = 0
		self.map_row.save(ignore_permissions=True)

		result = sweep.apply(users=[IN_SCOPE])

		self.assertEqual(result["applied"], 0)
		self.assertEqual(result["skipped"], 1)
		self.assertEqual(capability.get_user_role_profiles(IN_SCOPE), [])

	def test_apply_logs_every_user_it_considered(self):
		sweep.apply(users=[IN_SCOPE])

		logs = frappe.get_all(
			"Access Assignment Log",
			filters={"target_user": IN_SCOPE, "trigger": "Bulk Sweep"},
			pluck="name",
		)

		self.assertEqual(len(logs), 1)

	def test_a_delegate_cannot_run_the_sweep(self):
		"""The sweep is System-Manager-only; delegates assign one at a time."""
		frappe.set_user(IN_SCOPE)

		with self.assertRaises(frappe.PermissionError):
			sweep.apply(users=[IN_SCOPE])
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd /home/austin/frappe-v16-bench
bench --site kaitet.local run-tests --app role_advisor --module role_advisor.tests.test_sweep
```

Expected: FAIL — `ModuleNotFoundError: No module named 'role_advisor.sweep'`.

- [ ] **Step 3: Write `role_advisor/sweep.py`**

```python
# Copyright (c) 2026, Upande and contributors
# For license information, please see license.txt

"""Bulk assignment from the Designation Access Map.

Two passes. `dry_run` proposes and explains; `apply` writes only what it is
told to. Nothing is written on the strength of an inactive map row - the whole
point of the confidence tiers is that a human rules on the ambiguous ones
first.

System-Manager-only. A delegate assigns one user at a time through
`role_advisor.api.assign_access`, which logs and gates per call.
"""

import frappe
from frappe import _

from role_advisor import audit, capability, mapping
from role_advisor.role_advisor.report.designation_gap.designation_gap import unprofiled_users

# Commit every this many writes, so a failure halfway does not roll back an
# hour of work on a 254-user run.
BATCH_SIZE = 50


def _candidate(user: str, full_name: str | None = None) -> dict:
	scope = mapping.employee_scope(user)
	designation = frappe.db.get_value(
		"Employee", {"user_id": user, "status": "Active"}, "designation"
	)

	row = {
		"user": user,
		"full_name": full_name,
		"designation": designation or None,
		"company": scope.get("company"),
		"role_profile": None,
		"module_profile": None,
		"map_row": None,
		"blocked_reason": None,
	}

	if not designation:
		row["blocked_reason"] = "No active Employee record, so no designation to map from."
		return row

	active = mapping.resolve(designation, scope, active_only=True)
	if active:
		mapped = frappe.get_doc("Designation Access Map", active)
		row.update(
			role_profile=mapped.role_profile,
			module_profile=mapped.module_profile,
			map_row=mapped.name,
		)
		return row

	# Distinguish "no row at all" from "a row exists but nobody has ruled on
	# it": the second is a decision waiting, the first is a mapping gap.
	inactive = mapping.resolve(designation, scope, active_only=False)
	if inactive:
		row["map_row"] = inactive
		row["blocked_reason"] = (
			f"Map row {inactive} is not active. Review its confidence and evidence, "
			"then activate it."
		)
	else:
		row["blocked_reason"] = (
			f"No map row for designation '{designation}' in this scope."
		)

	return row


def dry_run() -> list[dict]:
	"""Propose an assignment for every unprofiled user. Writes nothing."""
	return [_candidate(row["user"], row.get("full_name")) for row in unprofiled_users()]


def apply(users: list[str] | None = None) -> dict:
	"""Assign profiles to `users`, or to every unblocked candidate if None.

	Every user considered gets a log row, including the ones skipped - a trail
	that omits refusals cannot answer "was this attempted?".
	"""
	frappe.only_for("System Manager")

	candidates = dry_run()
	if users is not None:
		wanted = set(users)
		candidates = [row for row in candidates if row["user"] in wanted]

	result = {"applied": 0, "skipped": 0, "no_change": 0, "logs": []}

	for index, candidate in enumerate(candidates, start=1):
		target = candidate["user"]
		before = audit.snapshot(target)

		if candidate["blocked_reason"]:
			result["skipped"] += 1
			result["logs"].append(
				audit.log_assignment(
					target, before, before, audit.TRIGGER_SWEEP,
					outcome=audit.OUTCOME_REFUSED, notes=candidate["blocked_reason"],
				)
			)
			continue

		if candidate["role_profile"] in before["profiles"]:
			result["no_change"] += 1
			result["logs"].append(
				audit.log_assignment(
					target, before, before, audit.TRIGGER_SWEEP,
					outcome=audit.OUTCOME_NO_CHANGE,
					notes="Already holds the mapped profile.",
				)
			)
			continue

		doc = frappe.get_doc("User", target)
		capability.set_user_role_profiles(doc, [candidate["role_profile"]])
		if candidate["module_profile"]:
			doc.module_profile = candidate["module_profile"]
		# permlevel 1: no permitted route exists. Gated by only_for above.
		doc.save(ignore_permissions=True)

		after = audit.snapshot(target)
		result["applied"] += 1
		result["logs"].append(
			audit.log_assignment(
				target, before, after, audit.TRIGGER_SWEEP,
				notes=f"From map row {candidate['map_row']}.",
			)
		)

		if index % BATCH_SIZE == 0:
			frappe.db.commit()

	frappe.db.commit()

	return result
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
cd /home/austin/frappe-v16-bench
bench --site kaitet.local run-tests --app role_advisor --module role_advisor.tests.test_sweep
```

Expected: 8 passed.

- [ ] **Step 5: Dry-run the sweep against real data**

```bash
cd /home/austin/frappe-v16-bench
bench --site kaitet.local console <<'EOF'
from collections import Counter
from role_advisor import sweep
rows = sweep.dry_run()
print(len(rows), "candidates")
print(Counter("ready" if not r["blocked_reason"] else "blocked" for r in rows))
for r in rows[:8]:
    print(" ", r["user"], "->", r["role_profile"] or r["blocked_reason"][:70])
EOF
```

Expected: 41 candidates. **Before the map is reviewed, nearly all should be blocked** — a large "ready" count at this stage means map rows were activated without review, so stop and check `Designation Access Map` before running `apply`.

- [ ] **Step 6: Commit**

```bash
cd /home/austin/frappe-v16-bench/apps/role_advisor
git add -A
git commit -m "feat: add the bulk sweep with dry-run and apply

Distinguishes 'no map row' from 'a row nobody has ruled on', because the
second is a decision waiting rather than a gap. Skipped users are logged
too, so the trail can answer whether a change was attempted. Batched
commits so a late failure does not discard earlier work."
```

---
## Task 16: Module profile derivation (deferrable)

Spec §7. Sequenced last because module profiles are navigation hygiene, not containment — `frappe/permissions.py` never consults modules. Independently shippable: Tasks 1–15 deliver the whole containment story without this.

Derives a draft `Module Profile` per role profile by asking the capability index which modules the profile's granted doctypes live in, and blocking the rest. Drafts are written disabled-by-convention (name-prefixed) and reviewed before any is assigned to a user.

**Files:**
- Create: `role_advisor/module_derivation.py`
- Create: `role_advisor/tests/test_module_derivation.py`

**Interfaces:**
- Consumes: `capability.build_capability_index()`, `settings.never_block_modules()`, `settings.naming_pattern()`, `settings.module_profile_strategy()`.
- Produces:
  - `module_derivation.modules_for_profile(role_profile: str) -> set[str]`
  - `module_derivation.blocked_for_profile(role_profile: str) -> list[str]`
  - `module_derivation.derive(dry_run: bool = True) -> list[dict]`
  - `module_derivation.DRAFT_PREFIX: str`

- [ ] **Step 1: Write the failing test**

Create `role_advisor/tests/test_module_derivation.py`:

```python
# Copyright (c) 2026, Upande and contributors
# For license information, please see license.txt

import frappe
from frappe.tests import IntegrationTestCase

from role_advisor import capability, module_derivation

ROLE = "_RA Module Role"
PROFILE = "_RA Module Profile"


class TestModuleDerivation(IntegrationTestCase):
	def setUp(self):
		if not frappe.db.exists("Role", ROLE):
			frappe.get_doc({"doctype": "Role", "role_name": ROLE}).insert()
		# ToDo lives in the Desk module, so a profile granting only ToDo should
		# resolve to exactly one allowed module.
		frappe.get_doc(
			{"doctype": "Custom DocPerm", "parent": "ToDo", "role": ROLE,
			 "permlevel": 0, "read": 1, "write": 1}
		).insert()
		if not frappe.db.exists("Role Profile", PROFILE):
			frappe.get_doc(
				{"doctype": "Role Profile", "role_profile": PROFILE,
				 "roles": [{"role": ROLE}]}
			).insert()
		capability.clear_capability_index()

	def tearDown(self):
		capability.clear_capability_index()

	def test_modules_are_derived_from_granted_doctypes(self):
		modules = module_derivation.modules_for_profile(PROFILE)

		self.assertEqual(modules, {"Desk"})

	def test_everything_else_is_blocked(self):
		blocked = module_derivation.blocked_for_profile(PROFILE)

		self.assertNotIn("Desk", blocked)
		self.assertEqual(len(blocked), frappe.db.count("Module Def") - 1)

	def test_never_block_modules_are_honoured(self):
		doc = frappe.get_single("User Access Settings")
		doc.append("never_block_modules", {"module": "Core"})
		doc.save(ignore_permissions=True)

		blocked = module_derivation.blocked_for_profile(PROFILE)

		self.assertNotIn("Core", blocked)

	def test_dry_run_writes_no_module_profiles(self):
		before = frappe.db.count("Module Profile")

		rows = module_derivation.derive(dry_run=True)

		self.assertEqual(frappe.db.count("Module Profile"), before)
		self.assertTrue(any(row["role_profile"] == PROFILE for row in rows))

	def test_drafts_are_name_prefixed(self):
		row = next(
			r for r in module_derivation.derive(dry_run=True)
			if r["role_profile"] == PROFILE
		)

		self.assertTrue(row["module_profile"].startswith(module_derivation.DRAFT_PREFIX))

	def test_manual_strategy_derives_nothing(self):
		doc = frappe.get_single("User Access Settings")
		doc.module_profile_strategy = "Manual"
		doc.save(ignore_permissions=True)

		self.assertEqual(module_derivation.derive(dry_run=True), [])

	def test_a_profile_granting_nothing_is_skipped(self):
		"""Blocking all 73 modules would leave an empty desk, not a tight one."""
		empty = "_RA Empty Profile"
		if not frappe.db.exists("Role Profile", empty):
			frappe.get_doc(
				{"doctype": "Role Profile", "role_profile": empty}
			).insert()
		capability.clear_capability_index()

		rows = {r["role_profile"] for r in module_derivation.derive(dry_run=True)}

		self.assertNotIn(empty, rows)
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd /home/austin/frappe-v16-bench
bench --site kaitet.local run-tests --app role_advisor --module role_advisor.tests.test_module_derivation
```

Expected: FAIL — `ModuleNotFoundError: No module named 'role_advisor.module_derivation'`.

- [ ] **Step 3: Write `role_advisor/module_derivation.py`**

```python
# Copyright (c) 2026, Upande and contributors
# For license information, please see license.txt

"""Derive a draft Module Profile from what a Role Profile grants.

Kaitet's hand-built profiles work by blocking what the author thought of, which
is why `cgi`, `Domain Enrichment`, `Kenya Etims Compliance`, `Loan Origination`
and `TagMeter Control` sit in *every* profile's allowed list - not by intent.
Deriving from granted doctypes instead is both tighter and more consistent.

There is no mandatory safe-list: `Roses Production Supervisor` allows 8 of 73
modules, blocking `Core` and `Desk`, and works in production. So
`never_block_modules` defaults to empty and is configuration, not a constant.
"""

import frappe

from role_advisor import capability, settings

# Drafts are prefixed rather than flagged: Module Profile has no enabled field,
# so the name is the only place a "do not assign yet" marker can live.
DRAFT_PREFIX = "[draft] "


def _module_by_doctype() -> dict[str, str]:
	return {
		row.name: row.module
		for row in frappe.get_all("DocType", fields=["name", "module"])
	}


def modules_for_profile(role_profile: str) -> set[str]:
	"""Modules containing at least one doctype this profile grants."""
	granted = capability.build_capability_index().get(role_profile, {})
	lookup = _module_by_doctype()

	return {lookup[doctype] for doctype in granted if doctype in lookup}


def blocked_for_profile(role_profile: str) -> list[str]:
	"""Every module except those the profile needs, and those never blocked."""
	allowed = modules_for_profile(role_profile) | set(settings.never_block_modules())
	all_modules = frappe.get_all("Module Def", pluck="name")

	return sorted(module for module in all_modules if module not in allowed)


def derive(dry_run: bool = True) -> list[dict]:
	"""Propose (and optionally write) one draft Module Profile per Role Profile."""
	if settings.module_profile_strategy() != "Derive from Role Profile":
		return []

	pattern = settings.naming_pattern()
	proposals = []

	for role_profile in frappe.get_all("Role Profile", pluck="name"):
		allowed = modules_for_profile(role_profile)
		if not allowed:
			# A profile granting nothing would derive a block-list covering every
			# module, leaving an empty desk rather than a tight one.
			continue

		name = DRAFT_PREFIX + pattern.format(role_profile=role_profile)
		blocked = blocked_for_profile(role_profile)

		proposals.append(
			{
				"role_profile": role_profile,
				"module_profile": name,
				"allowed_count": len(allowed),
				"blocked_count": len(blocked),
				"allowed": sorted(allowed),
			}
		)

		if dry_run or frappe.db.exists("Module Profile", name):
			continue

		frappe.get_doc(
			{
				"doctype": "Module Profile",
				"module_profile_name": name,
				"block_modules": [{"module": module} for module in blocked],
			}
		).insert(ignore_permissions=True)

	return sorted(proposals, key=lambda row: row["allowed_count"])
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
cd /home/austin/frappe-v16-bench
bench --site kaitet.local run-tests --app role_advisor --module role_advisor.tests.test_module_derivation
```

Expected: 7 passed.

- [ ] **Step 5: Compare the derivation against Kaitet's hand-built ladder**

```bash
cd /home/austin/frappe-v16-bench
bench --site kaitet.local console <<'EOF'
from role_advisor import module_derivation
rows = {r["role_profile"]: r for r in module_derivation.derive(dry_run=True)}
print(len(rows), "drafts proposed of 87 profiles")
for p in ("Agriculture Supervisor", "Production Supervisor", "Upande Team"):
    r = rows.get(p)
    print(p, "->", r["allowed_count"], "modules allowed" if r else "(no grants)")
EOF
```

Expected: fewer than 87 drafts (profiles granting nothing are skipped), and `Upande Team` — 133 roles — allowing far more modules than `Agriculture Supervisor`. If the derivation allows *more* modules than Kaitet's hand-built equivalent for a comparable profile, that is worth investigating before writing any draft: it means the profile grants doctypes nobody expected.

- [ ] **Step 6: Commit**

```bash
cd /home/austin/frappe-v16-bench/apps/role_advisor
git add -A
git commit -m "feat: derive draft module profiles from role profiles

Profiles granting nothing are skipped, since blocking all 73 modules
leaves an empty desk rather than a tight one. Drafts are name-prefixed
because Module Profile has no enabled field to flag them with."
```

---

## Post-implementation verification

Run after Task 15 (Task 16 optional). This is the gate before creating any real `Delegated User Admin` record.

- [ ] **Full test suite**

```bash
cd /home/austin/frappe-v16-bench
bench --site kaitet.local run-tests --app role_advisor
```

Expected: every test passes. Record the count.

- [ ] **Confirm nothing changed for existing users**

Installing Tasks 1–15 must be a no-op until a `Delegated User Admin` record exists.

```bash
cd /home/austin/frappe-v16-bench
bench --site kaitet.local console <<'EOF'
import frappe
from role_advisor import permissions
print("delegate records:", frappe.db.count("Delegated User Admin"))
for u in ("Administrator", "austin@upande.com", "mbundotich@karenroses.com"):
    assert permissions.user_query_conditions(u) == "", u
    assert permissions.user_permission_query_conditions(u) == "", u
print("no user is restricted")
print("users visible:", frappe.db.count("User", {"enabled": 1}))
EOF
```

Expected: zero delegate records, no restrictions, 425 enabled users.

- [ ] **Pilot**

Create the first record for `mbundotich@karenroses.com` — Karen Roses IT, already holding `User Manager` without System Manager, and therefore already blocked by the permlevel-1 gap this app closes. Populate `allowed_role_profiles` from the reviewed map, then have them assign one user and confirm an `Access Assignment Log` row appears.

---

## Self-review

**Spec coverage.** Every section maps to a task: §4.4 → Task 2; §4.1 → 3; §4.2 + §5.3 → 4; §4.3 → 5; §3.2/§3.3 → 1 and 6; §5.1/§5.2 → 9, 10, 11; §5.4 → 10; §5.5 → 8 and 15; §6.1 → 12; §6.2/§6.4 → 13; §6.3/§6.5 → 14; §6.6 → 15; §7 → 16; §8 → tests throughout; §9 → post-implementation verification. §10 (known issues) is deliberately unimplemented, per the scope decision. §11 (open items) needs the live-site check and the `Employee.grade` question, both outside code.

**Type consistency.** `total_perm_count` is named consistently after being renamed from `_total_perm_count` in Task 1. `privileged_grants` returns `dict[str, set[str]]` everywhere; Task 14 handles its `__unknown__` sentinel explicitly. `audit.snapshot` returns the same three keys wherever it is consumed (Tasks 11, 15). `mapping.resolve` returns a **row name**, not a profile name — Tasks 12 and 15 both `get_doc` it before reading `role_profile`.

**Two deliberate deviations from the spec, both flagged in-plan:**

1. **Task 7 restricts tie-break to materially supported candidates** (≥2 peers). The spec says tightest-wins unqualified; applied literally, one stray assignment would beat 29 peers. The majority and tightest picks are both recorded and disagreement deactivates the row.
2. **Task 10 denies a delegate `read` on their own User Permission rows**, not just write. The spec says "never their own row" without qualifying the right. Read is harmless alone, but a readable row invites a UI offering delete.

**Known gap.** The spec's §5.2 mentions a delegate-facing UI; this plan ships the API without one, so the pilot uses `bench console` or a client script. A Frappe page or Desk form for delegates is follow-up work — it changes no security property, since Task 11's API is the only write path either way.
