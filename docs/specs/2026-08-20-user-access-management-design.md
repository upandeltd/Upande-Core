# User Access Management — Design

**Date:** 2026-08-20
**App:** `role_advisor` (rebuilt)
**Reference site:** `kaitet.local` — a restore of Kaitet production as of 2026-07-13
**Status:** Design approved in discussion; awaiting spec review before implementation planning

---

## 1. Purpose

Give Kaitet's own staff the ability to manage users — assign role profiles, module
profiles and scope — without routing every change through Upande, and without any
delegated administrator being able to grant more than they were authorised to grant.

Three deliverables, in priority order:

1. **Assignment** — a `Designation → Role Profile` mapping that can be applied in
   bulk, so every login user with a designation has a deliberate profile.
2. **Delegation** — a bounded administrator role: manages only users inside their
   company scope, grants only profiles on their explicit allowlist.
3. **Visibility** — read-only reports that state what users can actually do today.

The app ships Kaitet's conventions as defaults but is configured entirely through
`User Access Settings`, so it re-targets to any Frappe project without code changes.

---

## 2. Measured starting state

All figures from `kaitet.local`, 2026-07-13 snapshot. **Re-verify against live before
seeding** — module profiles and the unprofiled-user list are the most likely to have moved.

| Metric | Value |
|---|---|
| Enabled System Users | 374 |
| ─ linked to an active Employee | 265 |
| ─ with an active Employee **and** a designation | 254 |
| ─ with **no** Employee link | 109 |
| Users holding ≥1 Role Profile | 333 |
| Users holding **no** Role Profile | 41 (24 with a designation, 17 without) |
| Role Profiles defined / in use | 87 / 72 |
| Distinct designations among login users | 80 (of 186 total) |
| Roles defined | 207 |
| Module Profiles | 15 (2 block nothing → 13 usable) |
| Users with no `block_modules` at all | 240 |
| Users with hand-set blocks but no profile | 38 |
| Companies | 8 |
| User Permission rows | Company 290/244 users · Farm 188/94 · Business Unit 86/59 · Employee 102/102 |
| System Managers | 23 — all `@upande.com`, none with an Employee record |
| `User Manager` holders | 23 — but **20 also hold System Manager**; only **3** are bounded |
| ─ the 3 bounded ones | `mbundotich@` (IT), `elangat@` (IT), `bob@` (no profile) — all Karen Roses |

### 2.1 The existing data is not a specification

Kaitet's current assignments were made ad hoc, without consistent regard to
designation, company or branch. Confirmed in the data:

- `Irrigator` → `Agriculture Production Supervisor-Approver (Restricted)` — an
  approver profile for a non-approving role.
- Three `Task Worker`s at Kaitet Ltd. → `scout`.
- `kimanthi@endebesscoffee.com` and `elizabeth@westwooddairies.com` both carry
  `Employee.company = Karen Roses`.
- The same designation maps to up to 4 different profiles
  (`Section Head`, `Store Clerk`, `Section Head Post Harvest`).

**Therefore:** the seeded map records *observed* state, never *endorsed* state. Every
seeded row carries its evidence and a confidence tier, and low-confidence rows cannot
drive assignment until a human activates them. `User Access Settings.seed_mode` allows
`Author from intent` for projects where existing data should not be trusted at all.

### 2.2 The real business case

No client-side user — Karen Roses, Lokitela Orchards, Westwood Dairies, Endebess
Coffee — holds System Manager. All 23 System Managers are Upande staff, and 20 of
them hold `Upande Team`, a profile carrying **133 roles**. Every role change for 374
users currently requires Upande. Delegation is the point of this work; tidiness is a
by-product.

---

## 3. Frappe v16 mechanics this design depends on

Each verified against `apps/frappe` at 16.27.0. These are the constraints that shaped
the design; a core change to any of them breaks a specific component named below.

### 3.1 Everything that matters on `User` is permlevel 1

`roles`, `role_profiles`, `role_profile_name`, `block_modules`, `user_type`, `api_key`,
`api_secret`, `user_emails`. Only System Manager holds permlevel-1 write.

**Consequence:** a `User Manager` holder can create and edit users but **cannot assign a
role profile**. This is the exact gap the app closes — and it is live today for
`mbundotich@karenroses.com` and `elangat@karenroses.com`, Karen Roses IT staff who hold
`User Manager` without System Manager and therefore cannot complete a task they are
plainly meant to perform. Because
permlevel is all-or-nothing, there is no way to grant `role_profiles` while withholding
`api_secret` and `user_type` through permissions — hence §5, an API rather than form
access.

### 3.2 `role_profile_name` is deprecated

`User.move_role_profile_name_to_role_profiles()` (`user.py:280`) moves any programmatic
write into the `role_profiles` child table and nulls the field;
`sync_role_profile_name()` (`user.py:306`) keeps it as a read-only mirror of
`role_profiles[0]` for list view. **Always write `role_profiles`.**

### 3.3 Role profiles prune roles — but HRMS heals it

`populate_role_profile_roles()` (`user.py:263`) runs on every save:

```python
self.roles = [r for r in self.roles if r.role in new_roles]
self.append_roles(*new_roles)
```

Any role granted outside a profile is stripped. **However**, `compose(fn, *hooks)`
(`frappe/model/document.py:1625`) runs the controller's `validate()` *before* the
`doc_events` hooks, and HRMS registers `update_approver_user_roles` on `User.validate`
(`hrms/hooks.py`), which re-adds `Leave Approver`/`Expense Approver` from the Employee
records naming that user (`hrms/overrides/employee_master.py:101`).

Measured: **20 drifted role rows across 16 users, all of them `Leave Approver` or
`Expense Approver`** — every one self-healing. No approval rights are at risk in the
sweep. The Drift report (§6.4) is retained as the canary for a future role granted
outside a profile with no such hook.

### 3.4 Module profiles overwrite block_modules wholesale — and are cosmetic

`validate_allowed_modules()` (called at `user.py:241`) does
`self.set("block_modules", [])` then repopulates from the profile. Nothing re-adds
hand-set blocks, so assigning a module profile to any of the **38** hand-blocked users
discards their tuning — a silent *widening* where their blocks were tighter.

More importantly: **`frappe/permissions.py` contains no reference to modules.**
`block_modules` is read in exactly two places — `frappe/desk/desktop.py:358` (Workspace
sidebar) and `frappe/utils/modules.py:9` (Dashboards, Charts, Number Cards). A blocked
module does **not** deny access to its doctypes; the user can still reach them by URL,
awesome bar, or REST API if a role grants it.

**Consequence:** module profiles are navigation hygiene, not a permission boundary.
They are worth doing (73 modules in a Scouter's sidebar is confusing and unprofessional)
and they are sequenced **last**. Containment is delivered by role profiles and User
Permissions.

### 3.5 Custom DocPerm overrides per doctype, not per role

If any `Custom DocPerm` row exists for a doctype, core discards that doctype's standard
DocPerms for **every** role. The site has 2,393 such rows. **Never seed Custom DocPerm
against a real doctype.**

### 3.6 Permission hooks compose as deny-only filters

- `permission_query_conditions`: `hooks.get(doctype, [])` is a **list**, joined with
  `" and "` (`frappe/model/db_query.py:1157`). Signature `(user, doctype=None)`.
- `has_permission`: any falsy return denies; *"Controllers can only deny permission,
  they can not explicitly grant any permission that wasn't already present"*
  (`frappe/permissions.py:480`). Signature `(doc, ptype, user, debug)`.

Core already registers both for `User`. Our hooks AND onto core's rather than replacing
them. **`User Permission` has no core hooks at all** — see §5.4.

---

## 4. Data model

Four new doctypes. Salvaged from the existing `role_advisor`: `build_capability_index()`
and its cache-invalidation `doc_events`. **Deleted:** the five `RA Demo *` doctypes,
`demo_data.py`, the transaction-catalog console, `Access Request Transaction Row`,
`Transaction Catalog`, and all `patches.txt` seeding (seed via `after_install`).

### 4.1 `Designation Access Map`

```
designation      Link Designation    (reqd)
company          Link Company        (optional — empty means all companies)
branch           Link Branch         (optional — narrower than company)
role_profile     Link Role Profile   (reqd)
module_profile   Link Module Profile
is_active        Check
confidence       Select: High | Medium | Low | None
source           Select: Seeded from existing users | Authored from intent
evidence         Small Text (read-only)
```

Unique on `(designation, company, branch)`. Resolution is **most-specific-wins**:
`(designation, company, branch)` beats `(designation, company)` beats `(designation)`.
That covers the farm/branch splits without needing 186 × 8 rows — one bare-designation
row handles clean cases such as `Production - KR Supervisor` (40 users, 1 profile), and
company/branch rows are added only where the data genuinely diverges.

**No `authority_level` field.** The Restricted / Approver / Can Purchase variants track
approval rights, but `Employee` carries no field that populates them — it would be a
dimension nothing can fill. Those variants remain distinct `role_profile` values chosen
per company/branch row. Revisit only if the variants are confirmed to follow
`Employee.grade`.

**Confidence tiers** (thresholds from settings, default 5):

| Tier | Rule | Auto-applies |
|---|---|---|
| High | ≥ `min_peers_high_confidence` agreeing peers | Yes |
| Medium | 2–4 peers, or a majority against a competing candidate | No |
| Low | 1 peer | No |
| None | no peer — designation×company unprecedented | No |

Seeded rows below High are created `is_active = 0`.

### 4.2 `Delegated User Admin`

```
user                     Link User (reqd, unique)
enabled                  Check
companies                Table MultiSelect Company        — scope
branches                 Table MultiSelect Branch         — optional narrower scope
allowed_role_profiles    Table MultiSelect Role Profile   — the grantable set
allowed_module_profiles  Table MultiSelect Module Profile
can_create_users         Check
can_disable_users        Check
```

The grantable set is an **explicit allowlist**, not "profiles the admin holds" — a Farm
Manager grants `Guard` and `Irrigator` without holding either, so administering access
does not inflate the administrator's own access.

`companies` defaults at creation to the Company values on that admin's existing User
Permissions, then is **stored explicitly**. A later change to their User Permissions
cannot silently widen what they administer.

Writable by System Manager only. Delegates get read on their own record — otherwise
they would widen their own allowlist.

### 4.3 `Access Assignment Log`

Reshaped from role_advisor's `Access Request Log`: actor, target user, profiles before →
after, module profile before → after, roles gained, roles lost, trigger
(`Manual` | `Designation Map` | `Bulk Sweep`), outcome. Written on **every** assignment
including no-ops, so the audit trail has no holes.

### 4.4 `User Access Settings` (Single)

```
Map resolution
  seed_mode                 Select: Seed from existing users | Author from intent
  scope_dimensions          Check: company / branch / department / grade   [Kaitet: company + branch]
  tie_break_rule            Select: Tightest by permission count | Majority peer vote | Always flag
  min_peers_high_confidence Int                                           [5]

Module profiles
  strategy                  Select: Derive from Role Profile | Manual | Per Company
  never_block_modules       Table MultiSelect Module Def                  [empty]
  naming_pattern            Data                                          ["{role_profile}"]

Delegation
  delegate_role             Link Role                                     [User Manager]
  allow_multiple_profiles   Check                                         [0]
  require_employee_link     Check                                         [1]
  privileged_doctypes       Table MultiSelect DocType                     [see §5.3]
```

`privileged_doctypes` as configuration rather than a constant is what keeps the computed
denylist portable across projects.

---

## 5. Delegation

### 5.1 Reuse the `User Manager` role

It already has the right permlevel-0 shape: create/read/write/delete on `User`, full
CRUD on `User Permission`, **read-only** on `Role`, `Role Profile` and `Module Profile`.
Read-only on Role Profile matters — a delegate who can *grant* a profile cannot *widen*
it by adding `System Manager` to it. That door is already shut; inventing a parallel
role risks opening a new one.

**Enforcement is opt-in per admin.** Restrictions apply only to a `delegate_role` holder
who also has an enabled `Delegated User Admin` record. Without one, behaviour is exactly
as today. Rollout is therefore one person at a time, and no migration step can lock
anyone out.

### 5.2 Three layers

| Layer | Mechanism | Job |
|---|---|---|
| 1 — Visibility | `permission_query_conditions` on `User` | Delegate's list view shows only users whose `Employee.company` ∈ scope. ANDs onto core's `STANDARD_USERS` guard. |
| 2 — Document access | `has_permission` on `User` | Blocks typing `/app/user/someone@else.com` directly. Deny-only, composes with core's Administrator guard. |
| 3 — Writes | Whitelisted API only | Delegate has no permlevel-1 write, so the stock form cannot show or save `roles`, `role_profiles`, `block_modules`, `user_type`, `api_key`, `api_secret`. |

```python
get_manageable_users(search=None, limit=50)             # scope-filtered
get_grantable_profiles()                                # allowlist + what each grants
preview_assignment(user, role_profile, module_profile)  # the diff, no write
assign_access(user, role_profile, module_profile=None)  # gated write + log
```

Every method resolves the caller's `Delegated User Admin` record first, or throws.

```python
_assert_can_manage(target)          # target's company ∈ caller's scope
_assert_can_grant(role_profile)     # ∈ allowlist, and not privileged
doc = frappe.get_doc("User", target)
before = _snapshot(doc)
doc.role_profiles = [{"role_profile": role_profile}]   # replace, per allow_multiple_profiles = 0
if module_profile:
    doc.module_profile = module_profile
doc.save(ignore_permissions=True)   # unavoidable: role_profiles is permlevel 1
_log(before, _snapshot(doc), trigger="Manual")
```

`ignore_permissions=True` is reached only after explicit gating, and the function's whole
surface is three arguments. `user_type` is never assignable, so a delegate can never
promote a Website User to a System User.

**Single profile per user.** There are 399 `User Role Profile` rows across all users
(enabled, disabled and website), and the per-user distribution shows **every** profiled
user holding exactly one — no user anywhere on the site holds two. Single-profile is
therefore the site's de facto model, and it keeps the over-grant diff readable.
Stacking profiles remains a System Manager action, gated by `allow_multiple_profiles`.

### 5.3 The privileged denylist is computed, not hardcoded

`assign_access` independently refuses any profile granting **write** on a
`privileged_doctypes` member — default `User`, `Role`, `Role Profile`, `Module Profile`,
`Custom DocPerm`, `DocPerm`, `Property Setter` — read from `build_capability_index()`.

A name-based denylist (`{"System Manager", …}`) rots the moment someone creates
`Site Admin Copy`. A capability check catches it whatever it is called. Enforced twice:
on `Delegated User Admin` save, so a System Manager sees the error immediately; and again
at assign time, because a profile's contents can change after being allowlisted.

### 5.4 Closing the User Permission hole

`User Permission` has **no permission hooks in core**, and `User Manager` holds full
create/write/delete on it. A User Manager can therefore delete their own Company user
permission and see every company's data.

**Current exposure is 3 users, not 23** — for the 20 who also hold System Manager the
hole is moot, since they can do anything regardless. The fix matters because *every
future delegate* created by this app inherits the same hole, and company scope is what
Layers 1 and 2 rest on. Load-bearing rather than incidental cleanup: without it the
delegation boundary is advisory. Same deny-only
pattern on `User Permission` — a delegate may touch rows only for users inside their
scope, and **never their own row**. No data changes; System Managers unaffected.

### 5.5 Reserved to System Managers

Creating and editing role profiles; creating `Delegated User Admin` and
`Designation Access Map` records; the bulk sweep; and the **109 users with no Employee
link** — having no company, they are unreachable by any delegate by construction.

---

## 6. Reports

All read-only, each producing a reviewable artifact before anything is written.

### 6.1 Designation Gap

The 41 unprofiled users. 17 have no Employee link (outside the map's reach); 24 have a
designation. Measured against the snapshot: **11 High**, **5 Low**, **8 None**.

Tie-break is **tightest by permission count**, not majority — majority systematically
drifts toward over-granting, because broad profiles spread faster. Demonstrated by
`jonah@karenroses.com` (`Grader`, Karen Roses), whose peers split between `Sales` and
`Sales (Restricted)` with the majority favouring the broader `Sales`. Rows where
tightest and majority disagree are flagged.

Also reports designation/company integrity conflicts (§2.1).

### 6.2 Module Exposure

240 users with no blocks at all; 38 with hand-set blocks and no profile. For the 38,
diffs current blocks against the proposed profile's, **separating widening from
tightening rows** (§3.4). Labelled navigation hygiene, not containment.

### 6.3 System Manager Audit

Report-only, no automatic revocation. Per System Manager: profile, last active, Employee
link. Flags `user@api.com` — a **service account holding System Manager**, last active
2025-08-30 — and `moses@upande.com`, last active 2025-10-30 with no profile.

### 6.4 Drift

Roles held outside any of the user's profiles. Currently **0 genuine cases** (all 20 are
HRMS-managed, §3.3). Retained as the canary.

### 6.5 Role Profile Over-grant

The only report describing what people can actually *do*. Per role profile, from
`build_capability_index()`: every doctype granted, every right, and flags for grants on
`privileged_doctypes`, broad `delete`, and rights inconsistent with the profile's
apparent purpose. `Upande Team` — 133 roles, held by 20 System Managers — is the first
case to examine.

Three row types are deliberately **not** counted as grants: `permlevel > 0` (a field-group
grant, not a document grant), `if_owner` (cannot authorise a transaction against an
arbitrary record), and rights outside `TRACKED_PERMS` (`email`, `print`, `share` — noise).

### 6.6 The sweep

Dry-run → human marks rows approved → apply writes only approved rows, one
`Access Assignment Log` entry each. **System-Manager-only, never available to delegates.**
Idempotent, batched with commits per chunk, and refuses to run while any required
`Designation Access Map` row is still `is_active = 0`.

---

## 7. Module profile derivation

Sequenced last, being cosmetic. Default strategy `Derive from Role Profile`: for each
role profile, use the capability index to find the modules its granted doctypes belong
to, block the rest, emit a draft `Module Profile` named by `naming_pattern`. Drafts are
reviewed before any is assigned.

The Kaitet frame supports this. Its best profiles are a deliberate ladder of strict
supersets — `Roses Production Supervisor` allows 8 of 73 modules, `… (Purchasing)` 9
(+`Buying`), `Roses Production Manager` 11 (+`Accounts`, +`Upande Accounting
Customizations`) — mirroring the authority variants seen in role profiles. Department
profiles sit at 21–32 (`Manufacturing` 21, `Roses Department Modules` 26, `Agriculture`
27, `POULTRY` 31, `DAIRY` 32); broad functional ones at 36–39. `ASSET MODULE PROFILE`
and `Clinic` block nothing and are unusable.

Two observations shape the default:

- `Roses Production Supervisor` blocks `Core` **and** `Desk` and works in production,
  so there is no mandatory safe-list. `never_block_modules` defaults to empty.
- `cgi`, `Domain Enrichment`, `Kenya Etims Compliance`, `Loan Origination` and
  `TagMeter Control` are allowed by *every* existing profile — not by intent, but
  because the hand-built profiles work by blocking what the author thought of.
  Derivation is tighter and more consistent than the hand-built result.

---

## 8. Testing

Frappe rollback tests on `kaitet.local` (`allow_tests` is already enabled;
`kaitet.tester` carries 5 apps against 30 and is unusable). Synthetic users, profiles and
companies per test.

Security tests, each failing differently and therefore tested separately:

- `assign_access` refuses an out-of-scope target
- refuses a non-allowlisted profile
- refuses a **privileged profile even when allowlisted**
- a delegate cannot read an out-of-scope User (Layer 1)
- a delegate cannot open an out-of-scope User by name (Layer 2)
- a delegate cannot edit or delete **their own** User Permission
- `user_type` cannot be changed through any delegate path

Behavioural tests:

- map resolution is most-specific-wins
- tie-break selects tightest, not majority
- the sweep is idempotent
- module derivation honours `never_block_modules`
- **retained:** `build_capability_index()` agrees with `frappe.permissions.get_all_perms`
  — the canary for a core change breaking the batched query

---

## 9. Rollout

| Step | Action | Reversible |
|---|---|---|
| 1 | Install; seed settings and map from live. Dry-run only. | Yes — no behaviour change |
| 2 | Human review of ~80 map rows and 24 gap proposals | Yes |
| 3 | Fix the User Permission hole (§5.4) | Code only, no data |
| 4 | Pilot: `Delegated User Admin` records for `mbundotich@karenroses.com` and `elangat@karenroses.com` — Karen Roses IT, already holding bounded `User Manager` and already blocked by §3.1 | Yes — disable the record |
| 5 | Broaden to remaining companies | Yes |
| 6 | Module profile derivation | Yes |

Nothing before step 3 changes what any of the 374 users can do.

---

## 10. Known issues, recorded but out of scope

- **`Cold Room Alert Receiver` holds create/read/write/delete on `User`** (with
  `if_owner = 1`). An alert-recipient role should not touch user records. Almost
  certainly unintended privilege.
- **Duplicate `Custom DocPerm` rows** for System Manager on `User` — two at permlevel 0,
  two at permlevel 1. Harmless, but evidence of hand-editing.
- **`ASSET MODULE PROFILE` and `Clinic`** block zero modules and have no effect.
- **Designation/company integrity**: `kimanthi@endebesscoffee.com` and
  `elizabeth@westwooddairies.com` both carry `Employee.company = Karen Roses`. Because
  delegation scopes on company, Karen Roses' delegate would administer both.
- **`user@api.com`** — service account holding System Manager (reported by §6.3, not
  acted on).
- **`bob@karenroses.com`** — Executive Director holding `User Manager` with **no role
  profile at all**, and simultaneously one of the 24 gap users in §6.1 whose designation
  has no precedent. Needs a human decision, not a derived one.

---

## 11. Open items

- Live-site verification of §2 figures once `claude.ai Kaitet` OAuth is completed.
  Module profiles and the 41-user gap are the most likely to have moved.
- Whether the Restricted / Approver / Can Purchase variants follow `Employee.grade`. If
  confirmed, `authority_level` becomes a viable fourth map dimension (§4.1).
- Whether `Farm` and `Business Unit` User Permissions (188 and 86 rows) should ever be
  managed by this app. `Employee` has no field for either, so they cannot be derived and
  currently remain hand-managed.
