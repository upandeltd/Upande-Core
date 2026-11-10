### Upande Core

Upande Core Functionalities

### Installation

You can install this app using the [bench](https://github.com/frappe/bench) CLI:

```bash
cd $PATH_TO_YOUR_BENCH
bench get-app $URL_OF_THIS_REPO --branch Core
bench install-app upande_core
```

### IT Dashboard

`https://your.site/it-dashboard` is the IT dashboard. It replaces the earlier Role Advisor / IT Operations portal page.

The **IT Dashboard** workspace follows the Upande CRM design: an animated apps-screen tile (a monitor's pulse line, then the Upande arrow rises out of the screen and rests as the Upande badge), a workspace body that is a tile grid with live record counts, and the **IT Dashboard** module's own sidebar (`it_dashboard/sidebar/`). The tile, workspace and navigation block are rebuilt from the files in this app on every migrate (`upande_core/it_workspace.py`), so edit those files, not the records.

**Who can open it:** people on the **IT Team** role profile, and no one else (Administrator always). Anyone else gets a page saying they cannot access it. If the site has no role profile with exactly that name, create one in Desk with the roles your IT staff need (not System Manager) and add the people.

**Screens**

| Screen | What it does |
|---|---|
| Overview | Headline numbers and charts for the mobile apps: people by update state, Android versions, events per day, tickets, device health |
| Updates | Who is behind, and for how long. Select people and press **Remind** to push a reminder |
| Devices | The device inventory; mark a device Active, Lost or Retired |
| Crashlytics | Crashes, errors and failed requests grouped into issues; resolve or ignore |
| Support | The inbox of problem reports and chat; answer in the page |
| Apps | One row per app: adoption, behind, problems, open tickets |
| User management | Add, edit, disable and delete people, assign role profiles and reset passwords, without System Manager |
| Role management | Add roles and add a role to a role profile |
| Doctype permissions | Grant or remove read, write, create, delete and the rest for a role on a doctype |
| User permissions | Limit a person to one Company, Farm, Warehouse, and so on |
| App store | `https://your.site/app-store`: every app's newest APK, for any signed-in user |

System Manager, Script Manager, Administrator, Guest and All are never given from the user, role or permission screens, so the IT team never needs System Manager. Every rule is enforced on the server as well as hidden in the page.

**The mobile screens read another app's data.** Overview, Updates, Devices, Crashlytics, Support, Apps and the app store read the doctypes of the `upande_mobile` app (Mobile App, Mobile App Install, Mobile Issue, Mobile Event, Mobile Report, Mobile Chat, Mobile Reminder). The code is in `upande_core/it_dashboard/mobile.py`; it imports `upande_mobile` only when a mobile screen asks for data. On a site without `upande_mobile` those screens say so and the three management screens still work.

**After deploying:** `bench --site your.site migrate` (the patch renames the old IT Operations workspace, sidebar and apps-screen tile to **IT Dashboard**), then `bench restart`. The old addresses `/mobile-monitor`, `/it-operations`, `/it-workforce`, `/it-operations-admin`, `/role-advisor` and `/access` all redirect to `/it-dashboard`.

**What the replacement removed.** The portal UI of Role Advisor and IT Operations: `public/js/access.js`, `public/js/itops.js` and `public/css/access.css`. Its views (anomalies, grant access, incoming requests, designation map, bulk sweep, delegates and policy, workforce, shifts, biometric status, system health, activity, error messages, monitor config) no longer have a page. The doctypes, reports, permission hooks, delegation rules and the endpoints in `upande_core/api/`, and the `access_dashboard` and `my_access` desk pages, are untouched and still work.

### Contributing

This app uses `pre-commit` for code formatting and linting. Please [install pre-commit](https://pre-commit.com/#installation) and enable it for this repository:

```bash
cd apps/upande_core
pre-commit install
```

Pre-commit is configured to use the following tools for checking and formatting your code:

- ruff
- eslint
- prettier
- pyupgrade
### CI

This app can use GitHub Actions for CI. The following workflows are configured:

- CI: Installs this app and runs unit tests on every push to `develop` branch.
- Linters: Runs [Frappe Semgrep Rules](https://github.com/frappe/semgrep-rules) and [pip-audit](https://pypi.org/project/pip-audit/) on every pull request.


### License

mit
