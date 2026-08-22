# Audit Trail — Design

**Date:** 2026-08-22
**App:** `role_advisor`
**Reference site:** `kaitet.local` — a v15 restore of Kaitet production, migrated to v16 on 2026-08-21
**Status:** Design approved in discussion; implementation authorised

---

## 1. Purpose

Answer, for any user, **how their access came to be what it is** — who changed it, when,
and whether the change went through Role Advisor's gates or around them.

`Access Assignment Log` already records what Role Advisor itself did. It holds **13 rows**.
`Version` holds **75,768** access-relevant rows the app cannot see. The trail people need is
therefore mostly *outside* Role Advisor, and the existing log is shallow because it is nearly
empty, not because its shape is wrong — its net-delta shape is in fact the right one, and this
design reuses it.

Three deliverables, in priority order:

1. **The trail** — one row per real access change, from any source, newest first.
2. **Attribution** — for each change, whether Role Advisor made it or someone bypassed it.
3. **Reconstruction** — a user's access as of any past date, with its own limits stated on screen.

Derived, never stored: no new doctypes, no hooks, no writes. The trail cannot itself become the
thing that is wrong.

---

## 2. Measured starting state

All figures from `kaitet.local`, 2026-08-22.

| Metric | Value |
|---|---|
| `tabVersion` total rows | 12,190,124 |
| ─ access-relevant (`ref_doctype` in the seven below) | 75,768 (0.62%) |
| ─ of which `User` | 75,226 |
| ─ `Role Profile` / `Property Setter` / `Module Profile` / `Role` | 405 / 123 / 13 / 1 |
| ─ `Custom DocPerm` / `DocPerm` | **0** |
| Version coverage window (access doctypes) | 2025-10-08 → 2026-08-21 |
| `tabActivity Log` rows | 28,569 — `Logout` 12,299, `Login Success` 11,697, `Login Failed` 4,513, **`Impersonate Success` 56** |
| `Access Assignment Log` rows | 13 (8 `Manual`, 5 `Bulk Sweep`, all `Applied`) |

### 2.1 Child-row churn — the governing fact

Across those 75,226 `User` version rows:

| Child table | Events |
|---|---|
| `roles` | 4,573,372 |
| `block_modules` | 2,017,447 |
| `role_profiles` | 64 |
| `user_emails` | 48 |

≈61 role events per version row. Frappe rewrites the whole `roles` child table on save, so one
profile application emits hundreds of `added` + `removed` pairs that largely cancel. A sampled row
carries `Expense Approver` in **both** `added` and `removed` — a net change of nothing.

**Consequence:** `it_dashboard.auditTrail`'s `version_flat` mode — one output row per field event —
is the wrong model for this data. Flat-expanding a single user-week yields five- to six-figure row
counts describing almost no real change. Net delta per version row is the unit.

### 2.2 Version tracking coverage

`track_changes` decides whether a doctype produces `Version` rows at all.

| Doctype | track_changes | istable | Covered |
|---|---|---|---|
| `User` | 1 | 0 | yes |
| `Role` | 1 | 0 | yes |
| `Role Profile` | 1 | 0 | yes |
| `Module Profile` | 1 | 0 | yes |
| `Property Setter` | 1 | 0 | yes |
| `Custom DocPerm` | **0** | 0 | **no** |
| `DocPerm` | — | 1 | via parent `DocType` |
| `Has Role` | — | 1 | via parent `User` |

`Has Role` is covered in practice: role grants appear inside the User's own version as
`added`/`removed` entries carrying the role name.

### 2.3 The v15/v16 split

The site is a v15 restore migrated to v16 on 2026-08-21, so both shapes sit in one table:

| Shape | Rows | Range |
|---|---|---|
| `role_profile_name` — v15 scalar field | 439 | 2025-10-09 → 2026-08-21 |
| `role_profiles` — v16 child table | 52 | 2026-08-21 |

A parser that knows only v16 sees 52 of 491 profile changes. `live_export.py` already documents
this split; the audit parser needs the same treatment.

---

## 3. Accepted limits

Stated here because they are properties of reusing the existing doctypes, not defects to fix later.

1. **`Custom DocPerm` changes are invisible.** `track_changes = 0`, and no derived query can
   recover them. Capturing them needs a doc hook and a store — out of scope, see §9.
2. **History begins 2025-10-08.** Nothing earlier is recoverable by any means.
3. **Attribution is heuristic.** Matching a version row to an `Access Assignment Log` row uses
   target and timestamp proximity, not a stamped identifier. §6 sets the window and the failure mode.

Every surface that presents reconstructed or complete-looking data must render limits 1 and 2
inline. A reconstruction that looks authoritative while being silently partial is worse than none.

---

## 4. Architecture

One new module, `role_advisor/audit_trail.py`. Reads `Version`, `Activity Log`, `User`. Nothing else
in the app changes; `Access Assignment Log`, `dashboard.py` and `audit.py` are untouched.

```
 Version ─┐
          ├─► _fetch ──► _delta ──► _attribute ──► endpoints ──► UI
 User ────┘   (SQL)      (pure)      (+ Assignment Log)
 Activity Log ─────────────────────────────────► login/impersonation stream
```

Four units, each independently testable:

| Unit | Responsibility | Depends on |
|---|---|---|
| `_fetch` | paginated, scoped SQL over `Version` | DB |
| `_delta` | one version row's `data` JSON → net access delta, or `None` | nothing (pure) |
| `_attribute` | tag each delta `role_advisor` / `external` / `system` | `Access Assignment Log` |
| endpoints | guard, scope, assemble, paginate | the three above |

`_delta` holds all the risk and none of the I/O, which is why it is pure: every shape in §2.1–2.3
is a fixture test with no database.

---

## 5. The parser

`_delta(data: str, ref_doctype: str) -> dict | None`

**Fields of interest** — scalar `changed` entries are kept only for:
`role_profile_name` (v15), `module_profile`, `user_type`, `enabled`, `api_key`, `api_secret`.
Everything else is dropped: `birth_date`, `gender`, `full_name`, `last_active`, `user_image`,
`reset_password_key`, `login_after`, `login_before`, and the rest of ordinary profile churn.

**Child tables of interest** — `roles`, `role_profiles`, `block_modules`. For each, `added` and
`removed` payloads are reduced to multisets of their meaningful value (`role`, `role_profile`,
`module`) and cancelled against each other:

```
gained = Counter(added) - Counter(removed)
lost   = Counter(removed) - Counter(added)
```

The value is extracted from the payload dict, not inferred from the table name — recording only
"the roles table changed" is the specific defect in `version_flat` that makes it useless here.

**`row_changed`** entries are read for edits inside a child row, filtered to the same field list.

**v15/v16 normalisation.** A `role_profile_name` scalar change and a `role_profiles` child
add/remove both collapse to canonical `profile_before` / `profile_after`. This is what makes the
439 historical rows legible beside the 52 new ones.

**Return `None` when the net delta is empty.** Most rows return `None`. That is the feature, not a
silent drop — §7 makes the scanned-versus-surfaced counts visible.

**Return shape:**

```python
{
  "version": str,            # Version.name, for drill-down
  "when": datetime,          # Version.creation
  "actor": str,              # Version.owner
  "actor_name": str | None,  # joined from User
  "doctype": str,            # ref_doctype
  "document": str,           # docname — the affected user/profile/role
  "roles_gained": list[str],
  "roles_lost": list[str],
  "modules_blocked": list[str],
  "modules_unblocked": list[str],
  "profile_before": str | None,
  "profile_after": str | None,
  "fields": list[tuple[str, str, str]],   # (fieldname, old, new) for scalar changes
  "updater_reference": dict | None,       # which code path made the change
}
```

---

## 6. Attribution

For each delta, look for an `Access Assignment Log` row where `target_user == document` and
`abs(creation - when) <= 2s`, then tag:

- **`role_advisor`** — matched; carries the log's `name`, `trigger`, `outcome`, `actor`.
- **`system`** — unmatched, but `updater_reference` names a code path rather than a desk action.
- **`external`** — unmatched and human. The interesting case: access changed while bypassing the gates.

The 2-second window is a heuristic, and its failure mode is stated rather than hidden: a bulk sweep
touching many users inside one second can mis-attribute a *concurrent* external edit to Role
Advisor. The response therefore carries `attribution: "heuristic"` and the UI labels the tag as an
inference. A stamped identifier on the write path would remove the guesswork; that changes
`api.assign_access` and is deliberately out of scope.

Given 13 log rows against 75,768 version rows, essentially the whole trail will read `external`
today. That is the finding, not a bug.

---

## 7. Endpoints

All `@frappe.whitelist()`, all behind the existing `dashboard._guard()` (`System Manager` or the
delegate role), all scoped through `_scoped_users()` so a delegate sees only users in their company.

| Endpoint | Signature | Returns |
|---|---|---|
| `trail` | `(target=None, actor=None, doctype=None, start=None, end=None, page=1, page_size=50)` | rows, `page`, `page_size`, `has_more`, `scanned`, `surfaced`, `unparsed` |
| `event` | `(version)` | one row's full raw `data`, including the events that cancelled |
| `as_of` | `(user, date)` | reconstruction, see §8 |
| `summary` | `(start=None, end=None)` | counts grouped by actor and by doctype |

Pagination follows the IT dashboard's convention — `page` / `page_size` / `has_more`, `page_size`
capped at 500. Because `_delta` drops most rows, pagination is over *scanned* version rows, and the
response reports `scanned` and `surfaced` separately so a page of 3 visible rows from 400 scanned
reads as correct rather than broken.

`Activity Log` logins and impersonations for the target ride alongside as a **separate stream**, not
merged into change rows — they are not access changes, and the 56 `Impersonate Success` rows matter
forensically on their own terms.

**Guard against unbounded scans:** a request must supply either `target` or a range no wider than
`MAX_UNTARGETED_DAYS`, a module constant set to 90. Neither present → default to the last 30 days
rather than throw. Deliberately a constant, not a `User Access Settings` field: it is a query-cost
guard, not a policy anyone should tune per site. Promote it to settings only if a site proves it
needs to.

---

## 8. Reconstruction

`as_of(user, date)` takes the user's current access — `capability.get_user_role_profiles`,
`module_profile`, and `Has Role` — and replays net deltas backward to `date`:

```
state = current
for delta in deltas_after(date, newest_first):
    state.roles   -= delta.roles_gained
    state.roles   += delta.roles_lost
    state.profile  = delta.profile_before  (when set)
```

Returns the reconstructed state, the delta chain that produced it, and a mandatory `limits` block
naming: the 2025-10-08 floor, `Custom DocPerm` invisibility, and any `unparsed` rows encountered in
the walk. If `date` precedes the floor, it returns the floor state and says so — it does not
extrapolate.

---

## 9. Out of scope

- Doc hooks and a store to capture `Custom DocPerm` — needs a new doctype; separate decision.
- Qlik export datasets (`activity` / `version` / `version_flat` / `summary` flat modes).
- Alerting, or feeding `anomalies.py`.
- Any change to `Access Assignment Log`, `audit.py`, or `api.assign_access`.
- Retiring `role_advisor/.../page/access_dashboard/access_dashboard.js` (3,387 lines, currently
  neither maintained nor deleted). Its own decision.

---

## 10. UI

A new **Audit Trail** nav item in `upande_core/public/js/access.js`, beside the existing
**Assignment Log** — which stays, unchanged, as Role Advisor's own decision record.

This splits the work across two repos: the endpoints land in `role_advisor` (pushable), the section
in `upande_core` (no push rights on `upandeltd/Upande-Core`; 4 commits already await a fork + PR).
The `role_advisor` half is independently useful and independently shippable.

Columns: When · Target · Change · By · Source. Filters: target, actor, doctype, date range. A row
expands to `event()` detail. `scanned` / `surfaced` / `unparsed` are shown as a footer line, so the
drop rate is visible rather than mysterious.

---

## 11. Error handling

| Case | Behaviour |
|---|---|
| Malformed `data` JSON | skip the row, increment `unparsed`, surface it in the response |
| `page_size` over cap | clamp to 500 |
| No target and no range | default to last 30 days |
| Range wider than the configured cap without a target | refuse, naming the cap |
| `date` before 2025-10-08 in `as_of` | return floor state, flag it in `limits` |
| Version row for a deleted user | render `document` as-is; no join is required to be non-null |

Nothing is silently swallowed: every degradation is counted and reported in the payload.

---

## 12. Testing

`_delta` is pure, so it carries the bulk of the tests, all from fixtures with no database:

- v15 scalar `role_profile_name` change → `profile_before` / `profile_after`
- v16 `role_profiles` child add/remove → the same canonical fields
- full-churn row (identical roles in `added` and `removed`) → `None`
- add-only, remove-only, mixed with partial cancellation
- `block_modules` add/remove
- `row_changed` inside a child row
- noise-only row (`birth_date`, `last_active`) → `None`
- malformed JSON → `None`, counted
- payload missing its `role` key → skipped, not crashed

Then, against the database:

- `_attribute`: an RA-made change tags `role_advisor`; an unmatched one tags `external`
- `_guard`: an unprivileged caller is refused; a delegate sees only scoped users
- `as_of`: a known delta chain reconstructs to a known state; a pre-floor date flags `limits`
- pagination: `has_more` is honest when most rows drop

Finally a smoke run against `kaitet.local`: real row counts, real timing, and confirmation that
`trail()` with no arguments returns in reasonable time against 12.19M rows.

---

## 13. Performance

`EXPLAIN` on the access-doctype filter with `ORDER BY creation DESC LIMIT 50` uses the `creation`
index at ~4,213 estimated rows — the filter matches 0.62% of the table, so the index walk examines
roughly 8,000 rows to fill a 50-row page. With `target` supplied it uses
`ref_doctype_docname_index` instead.

Parse cost is the real budget: ~61 child events per row means a 400-row scan handles ~24,000 events.
`Counter` cancellation is linear, so this is CPU-cheap, but it is the reason `page_size` is capped
and an unbounded range is refused.
