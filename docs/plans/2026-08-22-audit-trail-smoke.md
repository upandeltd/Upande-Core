# Audit Trail — measured against real data

**Date:** 2026-08-22
**Site:** `kaitet.local` — v15 restore of Kaitet production, migrated to v16 on 2026-08-21
**Table:** `tabVersion`, 12,190,124 rows; 75,768 access-relevant; blobs average **64.8 KB**
**MariaDB:** 11.8.6

Recorded so a later regression is visible. Re-measure after any change to `_fetch`.

## Endpoint timings

| Call | Time | Scanned | Surfaced | Notes |
|---|---|---|---|---|
| `trail()` — default 30 days | **0.12s** | 50 | 5 | 90% of rows carry no net change |
| `trail(start=-90d)` — untargeted | **0.04s** | 50 | 5 | was 10.8s before the index hint |
| `trail(page=2)` | **0.07s** | 50 | 11 | |
| `summary()` | **0.23s** | — | — | 144 User changes in 30 days, 1 actor |
| `as_of(busiest, -90d)` | **8.38s** | 3,764 | chain of 1 | was 34.8s |

The netting works: `surfaced` is consistently ~10% of `scanned`, and the rows that survive
carry real deltas — `+Scouting & Crop Protection User −Gate Guard, Spray Supervisor` — rather
than the 61-events-per-row churn the raw table holds.

## Two performance defects found and fixed

### 1. The optimiser picks the wrong index past ~30 days

`EXPLAIN` on the untargeted query, same statement, only the range differing:

| Range | Index chosen | Rows examined | Extra |
|---|---|---|---|
| 30 days | `creation` | 4,158 | Using where |
| 90 days | `ref_doctype_docname_index` | **175,062** | Using index condition; **Using filesort** |

Left alone that is 10.8s against 0.15s. Since the access doctypes are 0.62% of the table,
walking `creation` newest-first and filtering is always the cheaper plan, so `_fetch` now
carries `use index (creation)` whenever there is no target. **10.8s → 0.04s.**

With a target the unhinted plan is correct — `ref_doctype_docname_index` is the right index
for `docname = ?` — so the hint is applied only in the untargeted case.

### 2. Pagination cost far more than the bytes it moved

For the busiest user (`mutinda@karenroses.com`, 17,745 versions total, 3,764 in a 90-day window):

| Approach | Time | Bytes |
|---|---|---|
| 8 pages of 500, growing `OFFSET` | **30.4s** | 166 MB |
| One unpaginated query | **4.73s** | 166 MB |
| `JSON_EXTRACT` projection, one query | 14.89s | 9.4 MB |

Parsing was never the problem: 500 rows parse in 0.39s. The paged walk was.

The obvious-looking fix — project the JSON server-side to cut 166 MB to 9.4 MB — is **worse**,
because MariaDB spends more time parsing the JSON than the smaller transfer saves. Measured and
rejected; do not retry it without new evidence.

`as_of` now issues one bounded query instead of a paged walk. **34.8s → 8.38s.**
`_fetch` also gained a `before` parameter for keyset pagination, so any future caller that must
page through everything can do so without deep offsets.

## Known limits, unchanged by this work

- **`Custom DocPerm` is invisible** — `track_changes = 0`, zero `Version` rows. Only a doc hook
  and a stored event log would capture it; both were deliberately out of scope.
- **History starts 2025-10-08.** `as_of` before that returns the floor state with `exact: false`.
- **`as_of` reconstructs the User doc only.** Changes to the *contents* of a Role Profile the user
  holds are not replayed, so a user whose profile silently gained a role reads as unchanged. This
  is inherent to reconstructing from `Version` and is recorded in the spec's §3.
- **`MAX_REWIND_VERSIONS = 4000`.** The busiest user needs 3,764 for 90 days, so a full-history
  rewind for them will truncate and say so. Raising the cap raises latency roughly linearly:
  ~8s per 3,700 rows.
- **Attribution is heuristic** — a 2-second window against `Access Assignment Log`. With 13 log
  rows against 75,768 version rows, almost everything reads `external`, which is the finding
  rather than a defect.
