# Audit Trail Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give Role Advisor an audit trail that shows every real access change on the site — from any source, not just changes Role Advisor made — derived from `Version`, `Activity Log` and `User` with no new storage.

**Architecture:** One new module `role_advisor/audit_trail.py`, built as four units: `_fetch` (paginated SQL over `Version`), `_delta` (a pure parser turning one version row's `data` JSON into a net access delta, or `None`), `_attribute` (tagging each delta `role_advisor` / `system` / `external` against `Access Assignment Log`), and four whitelisted endpoints. Nothing writes; nothing existing changes.

**Tech Stack:** Frappe v16, Python 3.14, `frappe.tests.UnitTestCase` / `IntegrationTestCase`, vanilla JS for the UI section.

**Spec:** `docs/specs/2026-08-22-audit-trail-design.md`

## Global Constraints

- Site for all test runs: `kaitet.local`. Bench root: `~/frappe-v16-bench`.
- Test runner: `bench --site kaitet.local run-tests --module role_advisor.tests.test_audit_trail`
- `_delta` MUST stay pure — no `frappe.db`, no `frappe.get_*`, no I/O. All its tests run with `UnitTestCase` and fixtures.
- Access doctypes, exactly: `User`, `Role`, `Role Profile`, `Module Profile`, `Property Setter`. (`Custom DocPerm` has `track_changes = 0` and is knowingly uncovered; `DocPerm` and `Has Role` are child tables covered via their parents.)
- Scalar fields of interest, exactly: `role_profile_name`, `module_profile`, `user_type`, `enabled`, `api_key`, `api_secret`.
- Child tables of interest and their value keys, exactly: `roles` → `role`, `role_profiles` → `role_profile`, `block_modules` → `module`.
- `MAX_UNTARGETED_DAYS = 90`, `MAX_PAGE_SIZE = 500`, `DEFAULT_DAYS = 30`, `ATTRIBUTION_WINDOW_SECONDS = 2`, `HISTORY_FLOOR = "2025-10-08"` — module constants, not settings fields.
- Guard every endpoint with `dashboard._guard()` and scope with `dashboard._scoped_users()`. Never add a privileged path of its own.
- Commit messages: no AI attribution, no `Co-Authored-By`, no "Generated with". Author is `ghost-mann <ghost-mann@users.noreply.github.com>` (already set as branch-local git config).
- Branch: `audit-trail`. Do not push.
- Copyright header on every new file: `# Copyright (c) 2026, ghost-mann and contributors` / `# For license information, please see license.txt`
- Tabs for indentation in Python, matching the rest of the app.

---

### Task 1: The parser — scalar field changes

**Files:**
- Create: `role_advisor/audit_trail.py`
- Test: `role_advisor/tests/test_audit_trail.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `_delta(data: str, ref_doctype: str) -> dict | None`. Return dict keys used by every later task: `roles_gained`, `roles_lost`, `modules_blocked`, `modules_unblocked`, `profile_before`, `profile_after`, `fields`. Module constants `INTEREST_FIELDS`, `CHILD_VALUE_KEY`, `ACCESS_DOCTYPES`.

- [ ] **Step 1: Write the failing test**

```python
# Copyright (c) 2026, ghost-mann and contributors
# For license information, please see license.txt

import json

from frappe.tests import UnitTestCase

from role_advisor import audit_trail


class TestDeltaScalarFields(UnitTestCase):
	def test_v15_profile_change_becomes_before_and_after(self):
		data = json.dumps({"changed": [["role_profile_name", "Clerk", "Agriculture Supervisor"]]})

		delta = audit_trail._delta(data, "User")

		self.assertEqual(delta["profile_before"], "Clerk")
		self.assertEqual(delta["profile_after"], "Agriculture Supervisor")
		self.assertEqual(delta["fields"], [])

	def test_interesting_scalars_are_kept(self):
		data = json.dumps({"changed": [["enabled", 1, 0], ["user_type", "System User", "Website User"]]})

		delta = audit_trail._delta(data, "User")

		self.assertIn(("enabled", 1, 0), delta["fields"])
		self.assertIn(("user_type", "System User", "Website User"), delta["fields"])

	def test_ordinary_churn_is_dropped_entirely(self):
		data = json.dumps(
			{"changed": [["birth_date", "1990-01-01", "1990-01-02"], ["last_active", "a", "b"]]}
		)

		self.assertIsNone(audit_trail._delta(data, "User"))

	def test_malformed_json_is_none_not_an_exception(self):
		self.assertIsNone(audit_trail._delta("{not json", "User"))
		self.assertIsNone(audit_trail._delta("", "User"))
		self.assertIsNone(audit_trail._delta(None, "User"))

	def test_a_list_payload_is_rejected(self):
		self.assertIsNone(audit_trail._delta(json.dumps([1, 2, 3]), "User"))
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd ~/frappe-v16-bench && bench --site kaitet.local run-tests --module role_advisor.tests.test_audit_trail
```

Expected: FAIL — `ModuleNotFoundError: No module named 'role_advisor.audit_trail'`

- [ ] **Step 3: Write minimal implementation**

```python
# Copyright (c) 2026, ghost-mann and contributors
# For license information, please see license.txt

"""The audit trail: every real access change, whoever made it.

`Access Assignment Log` records what this app did. It holds 13 rows. `Version`
holds 75,768 access-relevant rows the app cannot see, so the trail worth having
is mostly of changes made outside it - which is exactly the thing worth knowing.

Derived, never stored. Nothing here writes, so the trail can never itself be
the thing that is wrong.
"""

import json

ACCESS_DOCTYPES = ("User", "Role", "Role Profile", "Module Profile", "Property Setter")

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

	if not (fields or profile_before or profile_after):
		return None

	return {
		"doctype": ref_doctype,
		"roles_gained": [],
		"roles_lost": [],
		"modules_blocked": [],
		"modules_unblocked": [],
		"profile_before": profile_before,
		"profile_after": profile_after,
		"fields": fields,
	}
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd ~/frappe-v16-bench && bench --site kaitet.local run-tests --module role_advisor.tests.test_audit_trail
```

Expected: PASS, 5 tests.

- [ ] **Step 5: Commit**

```bash
cd ~/frappe-v16-bench/apps/role_advisor
git add role_advisor/audit_trail.py role_advisor/tests/test_audit_trail.py
git commit -m "feat: read the access-relevant scalar changes out of a version row"
```

---

### Task 2: The parser — child-table netting

The governing fact from the spec: 75,226 `User` version rows carry 4,573,372 `roles` events and 2,017,447 `block_modules` events, ~61 per row, because Frappe rewrites the whole child table on save. Most cancel exactly. Netting is what makes the trail readable.

**Files:**
- Modify: `role_advisor/audit_trail.py`
- Test: `role_advisor/tests/test_audit_trail.py`

**Interfaces:**
- Consumes: `_delta` from Task 1.
- Produces: `_delta` now populates `roles_gained`, `roles_lost`, `modules_blocked`, `modules_unblocked`, and resolves `profile_before`/`profile_after` from the v16 `role_profiles` child table. Adds `_child_multisets(blob) -> tuple[dict, dict]`.

- [ ] **Step 1: Write the failing test**

```python
class TestDeltaChildTables(UnitTestCase):
	def _roles(self, added, removed):
		def rows(names):
			return [["roles", {"doctype": "Has Role", "role": name}] for name in names]

		return json.dumps({"added": rows(added), "removed": rows(removed)})

	def test_a_full_rewrite_that_cancels_is_dropped(self):
		"""One save rewrites every role row. Netting to nothing means nothing happened."""
		data = self._roles(["Employee", "Stock User"], ["Employee", "Stock User"])

		self.assertIsNone(audit_trail._delta(data, "User"))

	def test_only_the_real_delta_survives(self):
		data = self._roles(["Employee", "Stock User", "Expense Approver"], ["Employee", "Stock User"])

		delta = audit_trail._delta(data, "User")

		self.assertEqual(delta["roles_gained"], ["Expense Approver"])
		self.assertEqual(delta["roles_lost"], [])

	def test_a_loss_is_reported(self):
		data = self._roles(["Employee"], ["Employee", "Stock User"])

		delta = audit_trail._delta(data, "User")

		self.assertEqual(delta["roles_gained"], [])
		self.assertEqual(delta["roles_lost"], ["Stock User"])

	def test_blocked_modules_are_tracked_separately_from_roles(self):
		data = json.dumps(
			{"added": [["block_modules", {"module": "Selling"}]], "removed": [["block_modules", {"module": "Buying"}]]}
		)

		delta = audit_trail._delta(data, "User")

		self.assertEqual(delta["modules_blocked"], ["Selling"])
		self.assertEqual(delta["modules_unblocked"], ["Buying"])

	def test_v16_child_profile_change_reads_like_the_v15_scalar(self):
		"""439 rows use the v15 shape and 52 the v16 one. Both must render alike."""
		data = json.dumps(
			{
				"added": [["role_profiles", {"role_profile": "Agriculture Supervisor"}]],
				"removed": [["role_profiles", {"role_profile": "Clerk"}]],
			}
		)

		delta = audit_trail._delta(data, "User")

		self.assertEqual(delta["profile_before"], "Clerk")
		self.assertEqual(delta["profile_after"], "Agriculture Supervisor")

	def test_a_payload_missing_its_value_key_is_skipped_not_fatal(self):
		data = json.dumps({"added": [["roles", {"doctype": "Has Role"}]]})

		self.assertIsNone(audit_trail._delta(data, "User"))

	def test_uninteresting_child_tables_are_ignored(self):
		data = json.dumps({"added": [["user_emails", {"email_id": "x@y.z"}]]})

		self.assertIsNone(audit_trail._delta(data, "User"))

	def test_row_changed_inside_a_child_row_is_reported(self):
		data = json.dumps({"row_changed": [["roles", 1, "abc123", [["role", "Old", "New"]]]]})

		delta = audit_trail._delta(data, "User")

		self.assertIn(("roles.role", "Old", "New"), delta["fields"])
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd ~/frappe-v16-bench && bench --site kaitet.local run-tests --module role_advisor.tests.test_audit_trail
```

Expected: FAIL — `test_only_the_real_delta_survives` returns `None` (child tables not read yet).

- [ ] **Step 3: Write minimal implementation**

Add `import collections` at the top, then insert `_child_multisets` above `_delta`:

```python
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
```

Then in `_delta`, replace everything from `if not (fields or profile_before or profile_after):` to the end with:

```python
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
	}
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd ~/frappe-v16-bench && bench --site kaitet.local run-tests --module role_advisor.tests.test_audit_trail
```

Expected: PASS, 13 tests.

- [ ] **Step 5: Commit**

```bash
cd ~/frappe-v16-bench/apps/role_advisor
git add role_advisor/audit_trail.py role_advisor/tests/test_audit_trail.py
git commit -m "feat: net child-row churn down to the change that actually happened"
```

---

### Task 3: Fetching and the trail endpoint

**Files:**
- Modify: `role_advisor/audit_trail.py`
- Test: `role_advisor/tests/test_audit_trail.py`

**Interfaces:**
- Consumes: `_delta` (Tasks 1-2), `dashboard._guard`, `dashboard._scoped_users`.
- Produces: `_window(start, end, target) -> tuple[str, str]`, `_fetch(...) -> tuple[list[dict], bool]`, and the whitelisted `trail(target=None, actor=None, doctype=None, start=None, end=None, page=1, page_size=50) -> dict` returning keys `rows`, `page`, `page_size`, `has_more`, `scanned`, `surfaced`, `unparsed`, `attribution`, `limits`.

- [ ] **Step 1: Write the failing test**

```python
import frappe
from frappe.tests import IntegrationTestCase

from role_advisor.tests.fixtures import ensure_user


class TestTrailEndpoint(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")

	def test_it_returns_the_reporting_envelope(self):
		out = audit_trail.trail(page_size=5)

		for key in (
			"rows", "page", "page_size", "has_more",
			"scanned", "surfaced", "unparsed", "attribution", "limits",
		):
			self.assertIn(key, out)
		self.assertEqual(out["attribution"], "heuristic")

	def test_scanned_is_at_least_surfaced(self):
		"""Most version rows drop. A page of few rows from many scanned is correct."""
		out = audit_trail.trail(page_size=5)

		self.assertGreaterEqual(out["scanned"], out["surfaced"])
		self.assertEqual(out["surfaced"], len(out["rows"]))

	def test_page_size_is_clamped(self):
		out = audit_trail.trail(page_size=99999)

		self.assertEqual(out["page_size"], audit_trail.MAX_PAGE_SIZE)

	def test_an_untargeted_range_wider_than_the_cap_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			audit_trail.trail(start="2025-10-08", end="2026-08-22")

	def test_a_wide_range_is_allowed_when_targeted(self):
		out = audit_trail.trail(target="Administrator", start="2025-10-08", end="2026-08-22")

		self.assertIn("rows", out)

	def test_limits_are_always_declared(self):
		out = audit_trail.trail(page_size=1)

		self.assertEqual(out["limits"]["history_floor"], audit_trail.HISTORY_FLOOR)
		self.assertIn("Custom DocPerm", " ".join(out["limits"]["uncovered"]))

	def test_a_non_privileged_caller_is_refused(self):
		ensure_user("_ra_trail_nobody@example.com")
		frappe.set_user("_ra_trail_nobody@example.com")
		try:
			with self.assertRaises(frappe.PermissionError):
				audit_trail.trail()
		finally:
			frappe.set_user("Administrator")
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd ~/frappe-v16-bench && bench --site kaitet.local run-tests --module role_advisor.tests.test_audit_trail
```

Expected: FAIL — `AttributeError: module 'role_advisor.audit_trail' has no attribute 'trail'`

- [ ] **Step 3: Write minimal implementation**

Extend the imports and constants:

```python
import collections
import json

import frappe
from frappe.utils import add_days, cint, getdate, nowdate

from role_advisor import dashboard

MAX_PAGE_SIZE = 500
DEFAULT_DAYS = 30
MAX_UNTARGETED_DAYS = 90
HISTORY_FLOOR = "2025-10-08"
UNCOVERED = (
	"Custom DocPerm changes are not versioned and cannot appear here.",
	f"No history exists before {HISTORY_FLOOR}.",
)
```

Then append:

```python
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


def _is_parseable(data: str) -> bool:
	try:
		json.loads(data)
	except (ValueError, TypeError):
		return False
	return True
```

Add a placeholder `_attribute` so Task 3 runs standalone; Task 4 replaces its body:

```python
def _attribute(rows: list[dict]) -> list[dict]:
	for row in rows:
		row["source"] = "external"
	return rows
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd ~/frappe-v16-bench && bench --site kaitet.local run-tests --module role_advisor.tests.test_audit_trail
```

Expected: PASS, 20 tests.

- [ ] **Step 5: Commit**

```bash
cd ~/frappe-v16-bench/apps/role_advisor
git add role_advisor/audit_trail.py role_advisor/tests/test_audit_trail.py
git commit -m "feat: page the trail, and report what was scanned as well as shown"
```

---

### Task 4: Attribution

**Files:**
- Modify: `role_advisor/audit_trail.py`
- Test: `role_advisor/tests/test_audit_trail.py`

**Interfaces:**
- Consumes: `trail` (Task 3), `audit.log_assignment` for building fixtures.
- Produces: `_attribute(rows: list[dict]) -> list[dict]` adding `source` (`"role_advisor"` / `"system"` / `"external"`) and, when matched, `assignment_log`, `trigger`, `outcome`.

- [ ] **Step 1: Write the failing test**

```python
class TestAttribution(IntegrationTestCase):
	def test_an_unmatched_human_change_is_external(self):
		rows = audit_trail._attribute(
			[{"document": "_ra_attr_nobody@example.com", "when": frappe.utils.now_datetime(), "updater_reference": None}]
		)

		self.assertEqual(rows[0]["source"], "external")

	def test_a_change_matching_an_assignment_log_is_ours(self):
		from role_advisor import audit

		target = ensure_user("_ra_attr_target@example.com")
		name = audit.log_assignment(
			target,
			{"profiles": [], "module_profile": None, "roles": set()},
			{"profiles": ["X"], "module_profile": None, "roles": set()},
			audit.TRIGGER_MANUAL,
		)
		when = frappe.db.get_value("Access Assignment Log", name, "creation")

		rows = audit_trail._attribute([{"document": target, "when": when, "updater_reference": None}])

		self.assertEqual(rows[0]["source"], "role_advisor")
		self.assertEqual(rows[0]["assignment_log"], name)
		self.assertEqual(rows[0]["trigger"], audit.TRIGGER_MANUAL)

	def test_a_code_driven_change_is_system(self):
		rows = audit_trail._attribute(
			[
				{
					"document": "_ra_attr_nobody@example.com",
					"when": frappe.utils.now_datetime(),
					"updater_reference": {"doctype": "Patch Log", "label": "some.patch"},
				}
			]
		)

		self.assertEqual(rows[0]["source"], "system")

	def test_a_change_outside_the_window_is_not_claimed(self):
		from role_advisor import audit

		target = ensure_user("_ra_attr_far@example.com")
		audit.log_assignment(
			target,
			{"profiles": [], "module_profile": None, "roles": set()},
			{"profiles": ["X"], "module_profile": None, "roles": set()},
			audit.TRIGGER_MANUAL,
		)
		long_ago = frappe.utils.add_to_date(frappe.utils.now_datetime(), hours=-6)

		rows = audit_trail._attribute([{"document": target, "when": long_ago, "updater_reference": None}])

		self.assertEqual(rows[0]["source"], "external")
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd ~/frappe-v16-bench && bench --site kaitet.local run-tests --module role_advisor.tests.test_audit_trail
```

Expected: FAIL — `test_a_change_matching_an_assignment_log_is_ours` gets `external` from the placeholder.

- [ ] **Step 3: Write minimal implementation**

Add `ATTRIBUTION_WINDOW_SECONDS = 2` to the constants, then replace the placeholder `_attribute` entirely:

```python
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
	logs = frappe.get_all(
		"Access Assignment Log",
		filters={"target_user": ("in", list(targets))},
		fields=["name", "target_user", "trigger", "outcome", "creation"],
		limit_page_length=0,
	) if targets else []

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
```

`trail` must now pass `updater_reference` through. In `_delta`'s return dict add `"updater_reference": blob.get("updater_reference")`, and in the Task 1 test `test_v15_profile_change_becomes_before_and_after` no assertion changes — the key is additive.

- [ ] **Step 4: Run test to verify it passes**

```bash
cd ~/frappe-v16-bench && bench --site kaitet.local run-tests --module role_advisor.tests.test_audit_trail
```

Expected: PASS, 24 tests.

- [ ] **Step 5: Commit**

```bash
cd ~/frappe-v16-bench/apps/role_advisor
git add role_advisor/audit_trail.py role_advisor/tests/test_audit_trail.py
git commit -m "feat: mark whether a change went through the gates or around them"
```

---

### Task 5: Drill-down and summary

**Files:**
- Modify: `role_advisor/audit_trail.py`
- Test: `role_advisor/tests/test_audit_trail.py`

**Interfaces:**
- Consumes: `_delta`, `_attribute`, `dashboard._guard`.
- Produces: whitelisted `event(version: str) -> dict` (keys `version`, `when`, `actor`, `doctype`, `document`, `delta`, `raw`, `logins`) and `summary(start=None, end=None) -> dict` (keys `by_actor`, `by_doctype`, `window`).

- [ ] **Step 1: Write the failing test**

```python
class TestEventAndSummary(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")

	def test_event_returns_the_raw_blob_behind_a_row(self):
		name = frappe.db.get_value(
			"Version", {"ref_doctype": "User"}, "name", order_by="creation desc"
		)
		if not name:
			self.skipTest("no User versions on this site")

		out = audit_trail.event(name)

		self.assertEqual(out["version"], name)
		self.assertIn("raw", out)
		self.assertIsInstance(out["raw"], dict)

	def test_event_refuses_a_doctype_outside_the_access_set(self):
		name = frappe.db.get_value(
			"Version", {"ref_doctype": ("not in", audit_trail.ACCESS_DOCTYPES)}, "name"
		)
		if not name:
			self.skipTest("no non-access versions on this site")

		with self.assertRaises(frappe.PermissionError):
			audit_trail.event(name)

	def test_summary_groups_by_actor_and_doctype(self):
		out = audit_trail.summary()

		self.assertIn("by_actor", out)
		self.assertIn("by_doctype", out)
		self.assertIn("window", out)
		self.assertIsInstance(out["by_actor"], list)

	def test_summary_is_guarded(self):
		ensure_user("_ra_summary_nobody@example.com")
		frappe.set_user("_ra_summary_nobody@example.com")
		try:
			with self.assertRaises(frappe.PermissionError):
				audit_trail.summary()
		finally:
			frappe.set_user("Administrator")
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd ~/frappe-v16-bench && bench --site kaitet.local run-tests --module role_advisor.tests.test_audit_trail
```

Expected: FAIL — `AttributeError: ... has no attribute 'event'`

- [ ] **Step 3: Write minimal implementation**

```python
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

	logins = frappe.db.sql(
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
	) if row.ref_doctype == "User" else []

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
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd ~/frappe-v16-bench && bench --site kaitet.local run-tests --module role_advisor.tests.test_audit_trail
```

Expected: PASS, 28 tests.

- [ ] **Step 5: Commit**

```bash
cd ~/frappe-v16-bench/apps/role_advisor
git add role_advisor/audit_trail.py role_advisor/tests/test_audit_trail.py
git commit -m "feat: drill into one change, and see who has been changing access"
```

---

### Task 6: Point-in-time reconstruction

**Files:**
- Modify: `role_advisor/audit_trail.py`
- Test: `role_advisor/tests/test_audit_trail.py`

**Interfaces:**
- Consumes: `_delta`, `_fetch`, `capability.get_user_role_profiles`, `dashboard._guard`.
- Produces: whitelisted `as_of(user: str, date: str) -> dict` with keys `user`, `date`, `state` (`{roles, profiles, module_profile}`), `chain`, `limits`, `exact`.

- [ ] **Step 1: Write the failing test**

```python
class TestReconstruction(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")

	def test_today_reconstructs_to_current_state(self):
		target = ensure_user("_ra_asof_target@example.com")

		out = audit_trail.as_of(target, frappe.utils.nowdate())

		self.assertEqual(out["user"], target)
		self.assertEqual(set(out["state"]["roles"]), set(audit_trail._current_roles(target)))
		self.assertEqual(out["chain"], [])

	def test_a_gained_role_is_removed_walking_backwards(self):
		"""Replaying a gain backwards must take the role away again."""
		state = {"roles": {"Employee", "Expense Approver"}, "profiles": [], "module_profile": None}
		chain = [{"roles_gained": ["Expense Approver"], "roles_lost": [], "profile_before": None}]

		audit_trail._rewind(state, chain)

		self.assertNotIn("Expense Approver", state["roles"])
		self.assertIn("Employee", state["roles"])

	def test_a_lost_role_is_restored_walking_backwards(self):
		state = {"roles": {"Employee"}, "profiles": [], "module_profile": None}
		chain = [{"roles_gained": [], "roles_lost": ["Stock User"], "profile_before": None}]

		audit_trail._rewind(state, chain)

		self.assertIn("Stock User", state["roles"])

	def test_the_profile_is_rolled_back_to_before(self):
		state = {"roles": set(), "profiles": ["Agriculture Supervisor"], "module_profile": None}
		chain = [{"roles_gained": [], "roles_lost": [], "profile_before": "Clerk"}]

		audit_trail._rewind(state, chain)

		self.assertEqual(state["profiles"], ["Clerk"])

	def test_a_date_before_the_floor_is_flagged_not_extrapolated(self):
		target = ensure_user("_ra_asof_floor@example.com")

		out = audit_trail.as_of(target, "2024-01-01")

		self.assertFalse(out["exact"])
		self.assertIn("floor", " ".join(out["limits"]["notes"]).lower())

	def test_reconstruction_is_guarded(self):
		ensure_user("_ra_asof_nobody@example.com")
		frappe.set_user("_ra_asof_nobody@example.com")
		try:
			with self.assertRaises(frappe.PermissionError):
				audit_trail.as_of("Administrator", frappe.utils.nowdate())
		finally:
			frappe.set_user("Administrator")
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd ~/frappe-v16-bench && bench --site kaitet.local run-tests --module role_advisor.tests.test_audit_trail
```

Expected: FAIL — `AttributeError: ... has no attribute 'as_of'`

- [ ] **Step 3: Write minimal implementation**

Add `from role_advisor import capability, dashboard` to the imports, then append:

```python
def _current_roles(user: str) -> list[str]:
	return frappe.get_all(
		"Has Role", filters={"parent": user, "parenttype": "User"}, pluck="role"
	)


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
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd ~/frappe-v16-bench && bench --site kaitet.local run-tests --module role_advisor.tests.test_audit_trail
```

Expected: PASS, 34 tests.

- [ ] **Step 5: Commit**

```bash
cd ~/frappe-v16-bench/apps/role_advisor
git add role_advisor/audit_trail.py role_advisor/tests/test_audit_trail.py
git commit -m "feat: work a user's access back to what it was on a given date"
```

---

### Task 7: Smoke run against real data

Nothing here changes code. The parser is right on fixtures; this proves it is right on 12.19M rows, and records the numbers so a later regression is visible.

**Files:**
- Create: `docs/plans/2026-08-22-audit-trail-smoke.md`

- [ ] **Step 1: Run the trail unfiltered and time it**

```bash
cd ~/frappe-v16-bench && cat > /tmp/ra_smoke.py <<'PY'
import time
import frappe
from role_advisor import audit_trail

def run():
    frappe.set_user("Administrator")
    for label, kwargs in [
        ("default 30d", {"page_size": 50}),
        ("90d untargeted", {"start": frappe.utils.add_days(frappe.utils.nowdate(), -90), "page_size": 50}),
    ]:
        t = time.time()
        out = audit_trail.trail(**kwargs)
        print("%-16s %5.2fs scanned=%-5s surfaced=%-4s unparsed=%-3s has_more=%s"
              % (label, time.time() - t, out["scanned"], out["surfaced"], out["unparsed"], out["has_more"]))
    t = time.time()
    s = audit_trail.summary()
    print("summary          %5.2fs actors=%s doctypes=%s" % (time.time() - t, len(s["by_actor"]), len(s["by_doctype"])))
PY
cp /tmp/ra_smoke.py apps/role_advisor/role_advisor/ra_smoke.py
bench --site kaitet.local execute role_advisor.ra_smoke.run
rm apps/role_advisor/role_advisor/ra_smoke.py
```

Expected: each call returns in under ~5s; `surfaced` is far below `scanned`; `unparsed` is 0 or tiny.

- [ ] **Step 2: Reconstruct a real user who has actual history**

Pick a user with the most access-relevant versions and reconstruct them 90 days back, confirming the chain is non-empty and `exact` is true.

- [ ] **Step 3: Record the numbers**

Write the observed timings and counts into `docs/plans/2026-08-22-audit-trail-smoke.md`.

- [ ] **Step 4: Commit**

```bash
cd ~/frappe-v16-bench/apps/role_advisor
git add docs/plans/2026-08-22-audit-trail-smoke.md
git commit -m "docs: record what the trail costs against the real table"
```

---

### Task 8: The UI section

**Files:**
- Modify: `~/frappe-v16-bench/apps/upande_core/upande_core/public/js/access.js` — nav list near line 200, and a new `view_audit_trail()` beside `view_audit()` near line 3508.

**Interfaces:**
- Consumes: `role_advisor.audit_trail.trail`, `.event`, `.summary`, `.as_of` via `frappe.xcall`.
- Produces: a nav item `{ id: "trail", label: "Audit Trail", icon: "clock", count: null }` and `view_trail()` on the same `App` class.

**Note:** this lands in `upande_core`, a repo with no push rights (`upandeltd/Upande-Core` → `push: false`). Commit locally on its own branch; it ships with the fork + PR that already has 4 commits waiting.

- [ ] **Step 1: Branch upande_core and pin the commit identity**

```bash
cd ~/frappe-v16-bench/apps/upande_core
git config --local user.email ghost-mann@users.noreply.github.com
git config --local user.name ghost-mann
git checkout -b audit-trail
```

- [ ] **Step 2: Add the nav entry**

In the nav array (beside `{ id: "audit", label: "Assignment Log", ... }`), add immediately after it:

```javascript
			{ id: "trail", label: "Audit Trail", icon: "clock", count: null },
```

`Assignment Log` stays. Two entries, two meanings: what Role Advisor did, and what happened.

- [ ] **Step 3: Add the view**

Add a `view_trail()` method following the existing `view_audit()` shape: render filter inputs (target link field, actor, doctype select, day-range buttons 7/30/90), call `frappe.xcall("role_advisor.audit_trail.trail", filters)`, and render rows with columns **When · Target · Change · By · Source**. The `Change` cell composes from the delta: `+role` / `−role` chips, `profile before → after`, and `field: old → new`. Footer line renders `surfaced of scanned scanned · unparsed skipped`, and a caption states the two limits from `limits.uncovered`. Clicking a row calls `role_advisor.audit_trail.event` and shows the raw blob in a dialog.

- [ ] **Step 4: Build assets and check it renders**

```bash
cd ~/frappe-v16-bench && bench build --app upande_core
curl -sS -o /dev/null -w '%{http_code}\n' http://localhost:8002/it-dashboard
```

Expected: 200. Then load `http://localhost:8002/it-dashboard`, open **Audit Trail**, confirm rows render and a row expands.

- [ ] **Step 5: Commit**

```bash
cd ~/frappe-v16-bench/apps/upande_core
git add upande_core/public/js/access.js
git commit -m "feat: an audit trail section beside the assignment log"
```

---

## Self-Review

**Spec coverage:**

| Spec section | Task |
|---|---|
| §4 architecture — four units | 1-4 |
| §5 parser, fields of interest, netting, v15/v16 | 1, 2 |
| §6 attribution, 2s window, heuristic flag | 4 |
| §7 endpoints, pagination, scanned/surfaced, scan guard | 3, 5 |
| §8 reconstruction, floor behaviour, limits block | 6 |
| §10 UI section | 8 |
| §11 error handling — every row | 1 (malformed), 3 (clamp, default, refuse), 5 (missing version), 6 (floor) |
| §12 testing | tests in 1-6, real data in 7 |
| §13 performance | 7 |

§9 is exclusions — no task, correctly.

**Type consistency:** `_delta` returns the same key set in Tasks 1, 2 and 4 (`updater_reference` added in 4 and used only there and in `_attribute`). `_attribute` is defined as a placeholder in Task 3 and replaced in Task 4 — deliberate, so Task 3 is independently testable. `_fetch` returns `(rows, has_more)` in Tasks 3 and 6. `_window` is used by `trail` and `summary` with the same signature.

**One known wrinkle:** Task 6's `as_of` calls `_fetch` with `doctype="User"`, so reconstruction covers role and profile changes on the User doc but not changes to the *content* of a Role Profile the user holds. That is a real limitation of reconstructing from `Version` and is already covered by the spec's §3 limits — it is not a plan defect, but it should be named in the smoke doc.
