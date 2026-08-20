## Role Advisor

Works out the minimum-redundancy Role Profile to assign a user, based on the
transactions they need to perform — and shows the administrator exactly what a
suggested profile would over-grant before they approve it.

### Console

`/app/role-advisor-console` (System Manager only). Pick a user, pick the
transactions they need, hit **Resolve**. One of four outcomes:

| Status | Meaning | Next step |
|---|---|---|
| `Covered` | The profiles the user already holds cover every requested transaction. | Nothing to do. |
| `Fit Found` | An existing profile covers the request. The console shows the full over-grant diff. | **Apply** replaces the user's profiles with it. |
| `Gap - New Profile Needed` | Every requirement exists in some role, but no single profile bundles them. | Create a profile from the existing roles. |
| `Gap - New Role Needed` | Some requirement is granted by no role on the site. | Create or extend a role first. |

Every resolve writes an **Access Request Log** row, including `Covered` — the
audit trail has no holes.

### Tightest fit

When several profiles cover the request they differ only in what *else* they
hand over, so the smallest total permission count wins: least authority beyond
the ask, smallest blast radius. Ties break on fewer distinct doctypes, then on
profile name so the suggestion is stable across runs.

### v16 notes

- `User.role_profile_name` is deprecated. `User.move_role_profile_name_to_role_profiles`
  moves any value written to it into the `role_profiles` child table and nulls
  it, keeping it only as a mirror of `role_profiles[0]`. A user may hold several
  profiles, so **coverage is judged on the union of all of them**, and
  `apply_suggestion` writes `role_profiles`.
- `apply_suggestion` **replaces** rather than appends. Appending would leave the
  broader profile in place, keeping every grant the tighter one was chosen to
  avoid. The replaced profile list is recorded in the log's `decision_notes`.

### Capability index

`build_capability_index()` returns `{role_profile: {doctype: {perm, ...}}}`,
cached in `frappe.cache()` for ten minutes and invalidated by `doc_events` on
Role Profile, Custom DocPerm and DocPerm.

Three rows are deliberately not counted as grants:

- **permlevel > 0** — a field-group grant, not a grant on the document.
- **`if_owner`** — cannot authorise a transaction against an arbitrary record.
- rights outside `TRACKED_PERMS` (`email`, `print`, `share`) — noise in the diff.

`demo_data` sets every tracked right explicitly, including the denied ones:
`Custom DocPerm` defaults **both `read` and `export` to 1**, so listing only the
granted rights silently hands every seeded role an `export` permission.

Custom DocPerm overrides are applied **per doctype, not per role**: if any Custom
DocPerm row exists for a doctype, core discards that doctype's standard DocPerms
for every role. `_perm_rows_for_roles` is a batched form of
`frappe.permissions.get_all_perms` (which is per-role, and so costs hundreds of
round trips on a large site); a test asserts the two agree, so a change in core
fails loudly instead of producing wrong advice.

### Demo data

`role_advisor/demo_data.py::seed()` is idempotent and runs from the
`after_install` hook and from the test suite, so the console and the tests
exercise identical data. It creates 7 `RA *` roles, 4 `RA *` role profiles, 13
Transaction Catalog rows, and 2 `@example.com` demo users.

It has to be an `after_install` hook, **not** a patch: `install_app` calls
`set_all_patches_as_completed(app)`, which marks every entry in `patches.txt` as
run without executing it — so a seed patch never fires on a fresh install, and
`bench migrate` then skips it forever. The `v1_0.seed_demo_data` patch is kept
only for sites that installed the app before the patch existed. To seed a site
that is already installed:

    bench --site <site> execute role_advisor.install.after_install

Permissions attach only to the app's own `RA Demo *` doctypes — never to real
ones, because a Custom DocPerm row would discard their standard permissions
site-wide. `role_advisor.demo_data.teardown()` removes it all again.

Note that `RA Demo Pick List` deliberately grants System Manager no `delete`
right: the `Gap - New Role Needed` scenario needs one pair that no role grants.

### Tests

```bash
bench --site webstore.localhost run-tests --app role_advisor
```

Covers the four scenarios from the brief, both Gap kinds, the union-of-profiles
read model, replace-not-append on apply, the System Manager gate, the audit
trail, and core parity of the batched permission query.

#### License

mit
