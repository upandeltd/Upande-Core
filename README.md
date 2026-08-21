## Role Advisor

Delegated user access management for Frappe v16.

Lets an organisation's own staff manage users — assigning role profiles, module
profiles and scope — without any delegated administrator being able to grant
more than they were authorised to grant.

Repository: <https://github.com/ghost-mann/role-advisor>

### What it does

| | |
|---|---|
| **Assignment** | A `Designation → Role Profile` map, resolved most-specific-wins on designation → company → branch, applied in bulk with a dry-run first. |
| **Delegation** | A bounded administrator: manages only users inside their company scope, grants only profiles on their explicit allowlist. |
| **Visibility** | Five read-only reports plus an Excel workbook describing what users can actually do today. |

### Doctypes

- **User Access Settings** (Single) — every threshold and policy, so the app
  re-targets to another project without code changes.
- **Designation Access Map** — the mapping. Scope fields are prefixed `for_*`
  because Frappe stamps `frappe.defaults` onto any Link field named exactly
  `company`, which would make an "applies to every company" row impossible.
- **Delegated User Admin** — one record per administrator: company scope plus
  the profiles they may hand out. Deliberately *not* "the profiles they hold",
  so administering access does not inflate the administrator's own access.
- **Access Assignment Log** — immutable. No role holds write or delete.

### Delegation

Every field that matters on `User` — `roles`, `role_profiles`, `block_modules`,
`user_type`, `api_key`, `api_secret` — sits at **permlevel 1**, and permlevel is
all-or-nothing. There is no way to grant `role_profiles` while withholding
`api_secret` through permissions, so delegates get no permlevel-1 write at all
and go through `role_advisor.api` instead. `assign_access` takes three arguments
and can therefore change exactly three things.

Enforcement is **opt-in**: restrictions apply only to a delegate-role holder who
also has an enabled `Delegated User Admin` record. Installing the app changes
nothing until such a record exists.

A profile that grants write on `User`, `Role`, `Role Profile`, `Module Profile`,
`Custom DocPerm`, `DocPerm` or `Property Setter` can never be delegated, even if
allowlisted. That check is **computed from the capability index**, not matched on
role names — a name list rots the moment someone creates `Site Admin Copy`.

### Using it

Everything lives under the **User Access** workspace in the desk.

- **User Access Console** (`/app/user-access`) — the page a delegated
  administrator works in. Pick a user from the scoped list, pick a profile from
  your allowlist, preview the exact roles gained and lost, confirm. It is a thin
  client over `role_advisor.api` and never writes a document directly.
- Shortcuts to `Designation Access Map` (filtered to inactive rows, which are
  the ones awaiting a decision), `Delegated User Admin` and
  `Access Assignment Log`.
- Cards linking the five reports, the three configuration doctypes, and the core
  permission records this app reads but never seeds.

The console is visible to every `User Manager`, but the API refuses anyone
without an enabled `Delegated User Admin` record — so a non-delegate sees a
plain explanation rather than an error.

### Reports

`Designation Gap`, `Module Exposure`, `Role Drift`, `System Manager Audit`,
`Role Profile Overgrant`. All read-only.

### Workbook

One file, every sheet. Imports into Google Sheets via File → Import.

```bash
bench --site <site> execute role_advisor.workbook.build_combined
```

`docs/access-workbook-<date>.xlsx` — 71 sheets, ~102k rows.

Seven cross-cutting tabs, widest to narrowest:

| Tab | Rows | What it answers |
|---|---|---|
| `Overview` | one per module | how exposed is each module, and who owns it |
| `Users` | **every** user | what does each person hold |
| `Users by Module` | module × user × profile | who can reach my module |
| `Role Profiles` | one per profile | duplicates, subsets, proposed canonical names |
| `Roles` | one per role | what grants it, including the ones in no profile |
| `Profile Index` | one per profile | which module tabs a profile appears on |
| `Permissions` | profile × doctype | the full matrix |

Then **one tab per module**. Inside each, one block per role profile touching
that module, and within each block three grouped areas:

- **USERS** — who holds the profile, with company, designation and `enabled`
- **ROLES** — the roles composing it that reach this module
- **PERMISSIONS** — what those roles grant on this module's doctypes

`+ ADD` rows let an owner extend each area. Columns marked `(EDITABLE)` are
inert, parked for a future importer.

**Disabled users are included throughout**, with an `enabled` column to filter
on. A disabled account still holds its roles and profile, and re-enabling it
restores every grant silently — so leaving them out understates real exposure.
`Overview` reports `users_with_access` and `enabled_with_access` side by side.

> **A role profile spans a median of 35 modules**, so the same profile appears on
> many module tabs. The `also_on_sheets` column on every PROFILE row names the
> others, so two owners editing the same profile can see they are about to
> disagree. Reconciling that is a human step before anything is applied.

> **Applying a filled-in module sheet is not implemented, and is not trivial.**
> If any `Custom DocPerm` row exists for a doctype, Frappe discards that
> doctype's standard `DocPerm`s for *every* role. An importer must therefore
> write the complete permission set for each doctype it touches, not just the
> owner's additions, or roles nobody considered will silently lose access.

`workbook.build` and `module_workbook.build` still produce the two narrower
files if you want to hand someone only their part.

### User guide

A plain-language guide for the people administering access — concepts, how to
assign, what is refused and why, and what the review has already found.

```bash
python3 role_advisor/user_guide.py
```

`docs/Role Advisor - User Guide.docx`, six pages. Regenerate it after any change
to the workflow it describes.

### Exporting from a remote site

The site holding the real data may not be the site this app runs on — Kaitet's
production is v15 while the app targets v16, so a local `frappe.get_all` reports
a stale copy. `live_export` reads a remote site over the REST API instead.

```bash
export KAITET_HOST=https://kaitet-group.upande.com
export KAITET_TOKEN=api_key:api_secret
bench --site <site> execute role_advisor.live_export.run
```

Writes `~/kaitet-live-users.csv` — **every** user, enabled and disabled, with
company, branch, department, designation, grade, role profile, module profile,
role count, user-permission count, permitted companies, admin-role flags and
`roles_outside_profile` (precisely what v16 prunes on the next save).

Credentials come from the environment and are never read from code or a
committed file. The output lands outside the repository by default because it is
PII, and `*.csv` is gitignored.

Works against v15 and v16: `role_profile_name` is the real field on v15 and a
read-only mirror of `role_profiles[0]` on v16.

### v16 notes

- `User.role_profile_name` is deprecated; write the `role_profiles` child table.
  Always via `capability.set_user_role_profiles`, which clears the stale mirror —
  otherwise the *next* save silently turns a replace into an append.
- `populate_role_profile_roles` prunes roles to the union of the user's profiles
  on every save. HRMS re-adds `Leave Approver`/`Expense Approver` afterwards via
  a `User.validate` hook, so those survive; anything else granted outside a
  profile does not.
- **`block_modules` is not a permission boundary.** `frappe/permissions.py` never
  consults modules; `block_modules` is read only by the Workspace sidebar and by
  Dashboards/Charts/Number Cards. Module profiles are navigation hygiene.
- If any `Custom DocPerm` row exists for a doctype, core discards that doctype's
  standard DocPerms for **every** role. Never seed Custom DocPerm against a real
  doctype.
- Seed from `after_install`, never `patches.txt`: `install_app` marks every patch
  as already run.

### Tests

```bash
bench --site <site> run-tests --app role_advisor
```

`IntegrationTestCase` rolls back once per **class**, not per test, so tests clear
their own rows. `sweep.apply` commits, so that suite purges explicitly.

### License

MIT
