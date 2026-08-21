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

### Reports

`Designation Gap`, `Module Exposure`, `Role Drift`, `System Manager Audit`,
`Role Profile Overgrant`. All read-only.

### Workbooks

Two, for two audiences. Both read-only; both import into Google Sheets via
File → Import.

**Audit workbook** — for whoever owns access overall.

```bash
bench --site <site> execute role_advisor.workbook.build
```

`docs/user-access-workbook-<date>.xlsx`. Four sheets: users, role profiles (with
duplicate and subset analysis plus proposed canonical names from
`taxonomy.py`), roles, and the full profile-by-doctype permission matrix.

**Module-owner workbook** — for the person who owns a module.

```bash
bench --site <site> execute role_advisor.module_workbook.build
```

`docs/module-owner-workbook-<date>.xlsx`. An `Overview` tab, a `Profile Index`
tab, then one tab per module. Inside each module tab, one block per role profile
touching that module, and within each block two grouped areas — the **ROLES**
composing the profile, and the **PERMISSIONS** they grant on that module's
doctypes — with `+ ADD` rows for the owner to extend.

Columns marked `(EDITABLE)` are inert, parked for a future importer.

> **A role profile spans a median of 35 modules**, so the same profile appears on
> many module tabs. The `also_on_sheets` column on every PROFILE row names the
> others, so two owners editing the same profile can see they are about to
> disagree. Reconciling that is a human step before anything is applied — the
> workbook surfaces the conflict rather than resolving it.

> **Applying a module sheet is not yet implemented, and is not trivial.** If any
> `Custom DocPerm` row exists for a doctype, Frappe discards that doctype's
> standard `DocPerm`s for *every* role. Any importer must therefore write the
> complete permission set for each doctype it touches, not just the module
> owner's additions, or roles nobody considered will silently lose access.

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
