// Copyright (c) 2026, ghost-mann and contributors
// For license information, please see license.txt

/* Access Dashboard.
 *
 * Six views over one question: who can do what, and should they. Every number
 * is counted server-side by role_advisor.dashboard - nothing is estimated here,
 * and no trend is drawn that the stored data cannot support.
 *
 * Writes go through role_advisor.api only, which gates on the caller's
 * Delegated User Admin record. This page has no privileged path of its own.
 */

frappe.pages["access-dashboard"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Access Dashboard"),
		single_column: true,
	});
	page.main.addClass("ra-dash");
	new AccessDashboard(page);
};

const VIEWS = [
	{ id: "overview", label: "Overview", icon: "grid" },
	{ id: "users", label: "Users", icon: "users", count: "enabled" },
	{ id: "profiles", label: "Role Profiles", icon: "layers", count: "profiles" },
	{ id: "modules", label: "Modules", icon: "box", count: "modules" },
	{ id: "assign", label: "Assign Access", icon: "check" },
	{ id: "audit", label: "Audit Trail", icon: "clock", count: "assignments" },
];

const ICONS = {
	grid: '<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/>',
	users: '<path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/>',
	layers: '<polygon points="12 2 2 7 12 12 22 7 12 2"/><polyline points="2 17 12 22 22 17"/><polyline points="2 12 12 17 22 12"/>',
	box: '<path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"/>',
	check: '<path d="M9 11l3 3L22 4"/><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"/>',
	clock: '<circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/>',
	refresh: '<polyline points="23 4 23 10 17 10"/><polyline points="1 20 1 14 7 14"/><path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"/>',
};

const esc = (value) => frappe.utils.escape_html(String(value == null ? "" : value));
const num = (value) => Number(value || 0).toLocaleString();

class AccessDashboard {
	constructor(page) {
		this.page = page;
		this.view = (frappe.get_route() || [])[1] || "overview";
		this.cache = {};
		this.assign = { user: null, profile: null, preview: null };
		this.render_shell();
		this.load();
	}

	// ---------------------------------------------------------------- shell

	render_shell() {
		this.page.main.html(`
			<div class="ra-page">
				<aside class="ra-side">
					<div>
						<div class="ra-side__label">${__("Views")}</div>
						<nav class="ra-nav">
							${VIEWS.map(
								(view) => `
								<a data-view="${view.id}" class="${view.id === this.view ? "on" : ""}">
									<svg viewBox="0 0 24 24">${ICONS[view.icon]}</svg>
									${__(view.label)}
									${view.count ? `<span class="n" data-count="${view.count}">–</span>` : ""}
								</a>`
							).join("")}
						</nav>
					</div>
					<div>
						<div class="ra-side__label">${__("At a glance")}</div>
						<div class="ra-glance"></div>
					</div>
					<div>
						<div class="ra-side__label">${__("Exposure")}</div>
						<div class="ra-legend">
							<span><i style="background:rgba(196,48,43,0.40)"></i>${__("High · 75%+ of users")}</span>
							<span><i style="background:rgba(217,150,46,0.38)"></i>${__("Moderate · 40–75%")}</span>
							<span><i style="background:rgba(63,143,79,0.18)"></i>${__("Low · under 40%")}</span>
							<span><i style="background:rgba(10,10,10,0.04)"></i>${__("Unreachable")}</span>
						</div>
					</div>
					<div class="ra-side__user">
						<div class="ra-avatar">${esc((frappe.session.user_fullname || "?").slice(0, 2).toUpperCase())}</div>
						<div>
							<b>${esc(frappe.session.user_fullname || frappe.session.user)}</b>
							<small class="ra-role">${__("checking access…")}</small>
						</div>
					</div>
				</aside>
				<div class="ra-main"></div>
			</div>
		`);

		this.$main = this.page.main.find(".ra-main");
		this.$glance = this.page.main.find(".ra-glance");

		this.page.main.find(".ra-nav a").on("click", (event) => {
			const view = $(event.currentTarget).data("view");
			this.go(view);
		});
	}

	go(view) {
		this.view = view;
		this.page.main.find(".ra-nav a").removeClass("on");
		this.page.main.find(`.ra-nav a[data-view="${view}"]`).addClass("on");
		// Route so the browser back button and a shared link both work.
		frappe.set_route("access-dashboard", view);
		this.render();
		window.scrollTo({ top: 0 });
	}

	async load() {
		this.$main.html(`<div class="ra-empty"><span class="ra-spinner"></span> ${__("Counting…")}</div>`);
		try {
			this.summary = await frappe.xcall("role_advisor.dashboard.summary");
		} catch (error) {
			this.$main.html(
				`<div class="ra-card"><div class="ra-empty">${esc(
					error.message || __("You do not have access to this dashboard.")
				)}</div></div>`
			);
			return;
		}

		VIEWS.filter((view) => view.count).forEach((view) => {
			this.page.main
				.find(`.ra-nav a[data-view="${view.id}"] .n`)
				.text(num(this.summary[view.count]));
		});

		this.page.main.find(".ra-role").text(
			this.summary.scoped
				? __("Delegate · {0}", [this.summary.scope_companies.join(", ")])
				: __("Full access · all companies")
		);

		this.$glance.html(
			[
				[__("Users"), num(this.summary.users)],
				[__("With a profile"), num(this.summary.profiled)],
				[__("No profile"), num(this.summary.gap)],
				[__("Role profiles"), num(this.summary.profiles)],
				[__("Delegates"), num(this.summary.delegates)],
			]
				.map(([label, value]) => `<div class="ra-stat"><small>${label}</small><b>${value}</b></div>`)
				.join("")
		);

		this.render();
	}

	head(title, sub, tools = "") {
		return `
			<div class="ra-head">
				<div>
					<div class="ra-eyebrow">${__("Role Advisor")} · ${
						this.summary.scoped ? __("Delegated view") : __("Whole estate")
					}</div>
					<h1 class="ra-title">${title}</h1>
					<p class="ra-sub">${sub}</p>
				</div>
				<div class="ra-tools">
					${tools}
					<button class="ra-iconbtn ra-refresh" title="${__("Refresh")}">
						<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">${ICONS.refresh}</svg>
					</button>
				</div>
			</div>`;
	}

	render() {
		const method = `view_${this.view}`;
		if (!this[method]) {
			this.view = "overview";
		}
		this[`view_${this.view}`]();
		this.$main.find(".ra-refresh").on("click", () => {
			this.cache = {};
			this.load();
		});
	}

	async fetch(key, method, args) {
		if (!this.cache[key]) {
			this.cache[key] = await frappe.xcall(`role_advisor.dashboard.${method}`, args);
		}
		return this.cache[key];
	}

	// ------------------------------------------------------------- overview

	async view_overview() {
		const s = this.summary;
		const kpis = [
			{
				label: __("Users"),
				value: num(s.users),
				unit: __("{0} enabled · {1} system users", [num(s.enabled), num(s.system_users)]),
				tag: s.scoped ? { cls: "flat", text: __("your scope only") } : { cls: "flat", text: __("all companies") },
				go: "users",
			},
			{
				label: __("Profile Coverage"),
				value: `${s.coverage}%`,
				unit: __("{0} of {1} enabled users", [num(s.profiled), num(s.enabled)]),
				tag:
					s.gap > 0
						? { cls: "warn", text: __("{0} without a profile", [num(s.gap)]) }
						: { cls: "good", text: __("everyone covered") },
				go: "users",
			},
			{
				label: __("Role Profiles"),
				value: num(s.profiles),
				unit: __("{0} roles across the site", [num(s.roles)]),
				tag:
					s.privileged_profiles > 0
						? { cls: "bad", text: __("{0} cannot be delegated", [s.privileged_profiles]) }
						: { cls: "good", text: __("none privileged") },
				go: "profiles",
			},
			{
				label: __("Modules"),
				value: num(s.modules),
				unit: __("{0} users see every menu item", [num(s.no_module_profile)]),
				tag: { cls: "flat", text: __("navigation only, not access") },
				go: "modules",
			},
			{
				label: __("Designation Map"),
				value: num(s.map_rows),
				unit: __("{0} active · {1} awaiting review", [num(s.map_active), num(s.map_rows - s.map_active)]),
				tag:
					s.map_rows - s.map_active > 0
						? { cls: "warn", text: __("review needed") }
						: { cls: "good", text: __("all reviewed") },
			},
		];

		this.$main.html(`
			${this.head(
				__("Who can do what"),
				__(
					"{0} users · {1} role profiles · {2} roles · {3} modules — counted from this site, nothing estimated",
					[num(s.users), num(s.profiles), num(s.roles), num(s.modules)]
				)
			)}
			<div class="ra-kpis">
				${kpis
					.map(
						(kpi) => `
					<div class="ra-kpi ${kpi.go ? "clickable" : ""}" ${kpi.go ? `data-go="${kpi.go}"` : ""}>
						<div class="ra-kpi__label">${kpi.label}</div>
						<div class="ra-kpi__value">${kpi.value}</div>
						<div class="ra-kpi__unit">${kpi.unit}</div>
						<div class="ra-tag ${kpi.tag.cls}">${kpi.tag.text}</div>
					</div>`
					)
					.join("")}
			</div>
			<div class="ra-card">
				<div class="ra-card__head">
					<h3>${__("Module Exposure")}</h3>
					<div class="ra-meta">${__("each tile is a module · shade is the share of users who can reach it")}</div>
				</div>
				<div class="ra-modgrid ra-overview-mods"><div class="ra-empty"><span class="ra-spinner"></span></div></div>
				<div class="ra-clegend">
					<span><i style="background:rgba(196,48,43,0.40)"></i>${__("High")}</span>
					<span><i style="background:rgba(217,150,46,0.38)"></i>${__("Moderate")}</span>
					<span><i style="background:rgba(63,143,79,0.18)"></i>${__("Low")}</span>
					<span><i style="background:rgba(10,10,10,0.04)"></i>${__("Unreachable")}</span>
				</div>
			</div>
			<div class="ra-row2">
				<div class="ra-card">
					<div class="ra-card__head"><h3>${__("Needs a decision")}</h3><div class="ra-meta">${__("worst first")}</div></div>
					<div class="ra-findings"><div class="ra-empty"><span class="ra-spinner"></span></div></div>
				</div>
				<div class="ra-card">
					<div class="ra-card__head"><h3>${__("Most-held profiles")}</h3><div class="ra-meta">${__("by headcount")}</div></div>
					<div class="ra-list ra-topprofiles"><div class="ra-empty"><span class="ra-spinner"></span></div></div>
				</div>
			</div>
			<div class="ra-card">
				<div class="ra-card__head">
					<h3>${__("Coverage by Designation")}</h3>
					<div class="ra-meta">${__("largest gaps first · a gap is someone doing the job with no profile")}</div>
				</div>
				<div class="ra-desig"><div class="ra-empty"><span class="ra-spinner"></span></div></div>
			</div>
		`);

		this.$main.find("[data-go]").on("click", (event) => this.go($(event.currentTarget).data("go")));

		const [mods, finds, profiles, desig] = await Promise.all([
			this.fetch("modules", "module_exposure"),
			this.fetch("findings", "findings"),
			this.fetch("leaderboard", "profile_leaderboard", { limit: 8 }),
			this.fetch("designations", "designation_coverage", { limit: 12 }),
		]);

		this.$main.find(".ra-overview-mods").html(
			mods
				.slice(0, 24)
				.map(
					(mod) => `
				<div class="ra-mod ${mod.severity}" data-module="${esc(mod.module)}"
					title="${esc(mod.module)} · ${num(mod.users)} users · ${mod.doctypes_granted} of ${mod.doctypes_total} doctypes granted">
					<b>${esc(mod.module)}</b>
					<small>${num(mod.users)} ${__("users")} · ${mod.share}%</small>
				</div>`
				)
				.join("")
		);
		this.$main.find(".ra-overview-mods .ra-mod").on("click", () => this.go("modules"));

		this.$main.find(".ra-findings").html(
			finds.length
				? finds
						.map(
							(find) => `
					<div class="ra-find ${find.severity}">
						<i></i>
						<div><b>${esc(find.title)}</b><p>${esc(find.detail)}</p></div>
					</div>`
						)
						.join("")
				: `<div class="ra-empty">${__("Nothing outstanding.")}</div>`
		);

		this.$main.find(".ra-topprofiles").html(
			profiles
				.map(
					(row, index) => `
				<div class="ra-lrow clickable" data-profile="${esc(row.profile)}">
					<div class="ra-rank ${index === 0 ? "lead" : ""}">${index + 1}</div>
					<div>
						<div class="ra-name">${esc(row.profile)}</div>
						<div class="ra-lmeta">${row.roles} ${__("roles")} · ${num(row.doctypes)} ${__("doctypes")}${
							row.privileged ? ` · <b style="color:#c4302b">${__("privileged")}</b>` : ""
						}${row.empty ? ` · <b style="color:#c4302b">${__("grants nothing")}</b>` : ""}</div>
					</div>
					<div class="ra-qty">${num(row.users)}<small>${__("users")}</small></div>
				</div>`
				)
				.join("")
		);
		this.$main.find(".ra-topprofiles .ra-lrow").on("click", () => this.go("profiles"));

		const worst = Math.max(...desig.map((row) => row.users), 1);
		this.$main.find(".ra-desig").html(
			desig
				.map((row) => {
					const cls = row.coverage >= 90 ? "hi" : row.coverage >= 60 ? "mid" : "lo";
					return `
					<div class="ra-hb">
						<div class="ra-hb__name" title="${esc(row.designation)} · ${esc(row.company || "—")}">${esc(
							row.designation
						)} <span style="color:#8a8780;font-weight:500">${esc(row.company || "")}</span></div>
						<div class="ra-hb__lane">
							<div class="ra-hb__fill ${cls}" style="width:${(row.users / worst) * row.coverage}%"></div>
						</div>
						<div class="ra-hb__pct">${row.gap ? `−${row.gap}` : "✓"}</div>
					</div>`;
				})
				.join("")
		);
	}

	// ---------------------------------------------------------------- users

	async view_users() {
		this.$main.html(`
			${this.head(
				__("Users"),
				__("Everyone who can log in, what they hold, and where they sit"),
				`<div class="ra-pillgroup ra-userfilter">
					<button class="on" data-f="all">${__("All")}</button>
					<button data-f="gap">${__("No profile")}</button>
					<button data-f="disabled">${__("Disabled")}</button>
					<button data-f="admin">${__("Admins")}</button>
				</div>`
			)}
			<div class="ra-card">
				<div class="ra-filters">
					<input class="ra-input ra-search" type="search" placeholder="${__("Search name, login, designation…")}">
					<select class="ra-select ra-company"><option value="">${__("All companies")}</option></select>
					<span class="ra-meta ra-usercount"></span>
				</div>
				<div class="ra-tablewrap"><table class="ra-table">
					<thead><tr>
						<th>${__("User")}</th><th>${__("Company")}</th><th>${__("Designation")}</th>
						<th>${__("Role Profile")}</th><th class="ra-num">${__("Roles")}</th>
						<th>${__("Status")}</th>
					</tr></thead>
					<tbody class="ra-userrows"><tr><td colspan="6"><div class="ra-empty"><span class="ra-spinner"></span></div></td></tr></tbody>
				</table></div>
			</div>
		`);

		const rows = await this.fetch("users", "user_table");
		this.users = rows;

		const companies = [...new Set(rows.map((row) => row.company).filter(Boolean))].sort();
		this.$main
			.find(".ra-company")
			.append(companies.map((c) => `<option value="${esc(c)}">${esc(c)}</option>`).join(""));

		const draw = () => {
			const term = (this.$main.find(".ra-search").val() || "").toLowerCase();
			const company = this.$main.find(".ra-company").val();
			const filter = this.$main.find(".ra-userfilter button.on").data("f");

			const shown = rows.filter((row) => {
				if (company && row.company !== company) return false;
				if (filter === "gap" && (row.profile || !row.enabled)) return false;
				if (filter === "disabled" && row.enabled) return false;
				if (filter === "admin" && !row.is_system_manager && !row.is_user_manager) return false;
				if (!term) return true;
				return [row.user, row.full_name, row.designation, row.profile]
					.filter(Boolean)
					.some((field) => String(field).toLowerCase().includes(term));
			});

			this.$main.find(".ra-usercount").text(__("{0} of {1} users", [num(shown.length), num(rows.length)]));
			this.$main.find(".ra-userrows").html(
				shown.length
					? shown
							.slice(0, 400)
							.map(
								(row) => `
						<tr data-user="${esc(row.user)}">
							<td><b>${esc(row.full_name || row.user)}</b><div class="ra-lmeta">${esc(row.user)}</div></td>
							<td>${esc(row.company || "—")}</td>
							<td>${esc(row.designation || "—")}</td>
							<td>${row.profile ? esc(row.profile) : `<span class="ra-chip bad">${__("none")}</span>`}</td>
							<td class="ra-num">${num(row.roles)}</td>
							<td>${
								!row.enabled
									? `<span class="ra-chip mute">${__("disabled")}</span>`
									: row.is_system_manager
									? `<span class="ra-chip bad">${__("System Manager")}</span>`
									: row.is_user_manager
									? `<span class="ra-chip warn">${__("User Manager")}</span>`
									: `<span class="ra-chip">${__("active")}</span>`
							}</td>
						</tr>`
							)
							.join("") +
					  (shown.length > 400
							? `<tr><td colspan="6" class="ra-meta" style="padding:14px 10px">${__(
									"Showing the first 400 of {0} — narrow the search to see the rest.",
									[num(shown.length)]
							  )}</td></tr>`
							: "")
					: `<tr><td colspan="6"><div class="ra-empty">${__("No users match.")}</div></td></tr>`
			);

			this.$main.find(".ra-userrows tr[data-user]").on("click", (event) => {
				frappe.set_route("Form", "User", $(event.currentTarget).data("user"));
			});
		};

		this.$main.find(".ra-search, .ra-company").on("input change", draw);
		this.$main.find(".ra-userfilter button").on("click", (event) => {
			this.$main.find(".ra-userfilter button").removeClass("on");
			$(event.currentTarget).addClass("on");
			draw();
		});
		draw();
	}

	// ------------------------------------------------------------- profiles

	async view_profiles() {
		this.$main.html(`
			${this.head(
				__("Role Profiles"),
				__("What each profile actually grants — the real permission boundary"),
				`<div class="ra-pillgroup ra-proffilter">
					<button class="on" data-f="all">${__("All")}</button>
					<button data-f="flagged">${__("Flagged")}</button>
					<button data-f="unused">${__("Unused")}</button>
				</div>`
			)}
			<div class="ra-card">
				<div class="ra-filters">
					<input class="ra-input ra-psearch" type="search" placeholder="${__("Search profiles…")}">
					<span class="ra-meta ra-pcount"></span>
				</div>
				<div class="ra-tiles ra-proftiles"><div class="ra-empty"><span class="ra-spinner"></span></div></div>
			</div>
		`);

		const rows = await this.fetch("allprofiles", "profile_leaderboard", { limit: 500 });

		const draw = () => {
			const term = (this.$main.find(".ra-psearch").val() || "").toLowerCase();
			const filter = this.$main.find(".ra-proffilter button.on").data("f");
			const shown = rows.filter((row) => {
				if (filter === "flagged" && !row.privileged && !row.empty) return false;
				if (filter === "unused" && row.users > 0) return false;
				return !term || row.profile.toLowerCase().includes(term);
			});

			this.$main.find(".ra-pcount").text(__("{0} of {1} profiles", [shown.length, rows.length]));
			this.$main.find(".ra-proftiles").html(
				shown.length
					? shown
							.map(
								(row) => `
						<div class="ra-tile ${row.privileged || row.empty ? "flagged" : ""}" data-profile="${esc(row.profile)}">
							<div class="ra-tile__head">
								<div class="ra-tile__name" title="${esc(row.profile)}">${esc(row.profile)}</div>
								${
									row.empty
										? `<span class="ra-chip bad">${__("grants nothing")}</span>`
										: row.privileged
										? `<span class="ra-chip bad">${__("privileged")}</span>`
										: row.users === 0
										? `<span class="ra-chip mute">${__("unused")}</span>`
										: `<span class="ra-chip">${__("in use")}</span>`
								}
							</div>
							<div class="ra-tile__stats">
								<div><small>${__("Users")}</small><b>${num(row.users)}</b></div>
								<div><small>${__("Roles")}</small><b>${num(row.roles)}</b></div>
								<div><small>${__("Doctypes")}</small><b>${num(row.doctypes)}</b></div>
								<div><small>${__("Grants")}</small><b>${num(row.grants)}</b></div>
							</div>
						</div>`
							)
							.join("")
					: `<div class="ra-empty">${__("No profiles match.")}</div>`
			);

			this.$main.find(".ra-proftiles .ra-tile").on("click", (event) => {
				frappe.set_route("Form", "Role Profile", $(event.currentTarget).data("profile"));
			});
		};

		this.$main.find(".ra-psearch").on("input", draw);
		this.$main.find(".ra-proffilter button").on("click", (event) => {
			this.$main.find(".ra-proffilter button").removeClass("on");
			$(event.currentTarget).addClass("on");
			draw();
		});
		draw();
	}

	// -------------------------------------------------------------- modules

	async view_modules() {
		this.$main.html(`
			${this.head(
				__("Modules"),
				__("Which parts of the system each population can reach"),
				`<div class="ra-pillgroup ra-modsort">
					<button class="on" data-s="users">${__("By users")}</button>
					<button data-s="name">${__("A–Z")}</button>
				</div>`
			)}
			<div class="ra-card">
				<div class="ra-card__head">
					<h3>${__("Exposure Grid")}</h3>
					<div class="ra-meta">${__("shade is the share of enabled users who can reach the module")}</div>
				</div>
				<div class="ra-modgrid ra-allmods"><div class="ra-empty"><span class="ra-spinner"></span></div></div>
			</div>
			<div class="ra-card">
				<div class="ra-card__head"><h3>${__("Module Detail")}</h3><div class="ra-meta">${__("granted doctypes of the total each module contains")}</div></div>
				<div class="ra-moddetail"></div>
			</div>
		`);

		const rows = await this.fetch("modules", "module_exposure");
		const worst = Math.max(...rows.map((row) => row.users), 1);

		const draw = () => {
			const sort = this.$main.find(".ra-modsort button.on").data("s");
			const shown = [...rows].sort((a, b) =>
				sort === "name" ? a.module.localeCompare(b.module) : b.users - a.users
			);

			this.$main.find(".ra-allmods").html(
				shown
					.map(
						(mod) => `
					<div class="ra-mod ${mod.severity}" title="${esc(mod.module)} · ${num(mod.users)} ${__("users")} · ${
							mod.profiles
						} ${__("profiles")}">
						<b>${esc(mod.module)}</b>
						<small>${num(mod.users)} · ${mod.share}%</small>
					</div>`
					)
					.join("")
			);

			this.$main.find(".ra-moddetail").html(
				shown
					.slice(0, 30)
					.map((mod) => {
						const cls = mod.severity === "high" ? "lo" : mod.severity === "moderate" ? "mid" : "hi";
						return `
						<div class="ra-hb">
							<div class="ra-hb__name" title="${esc(mod.module)}">${esc(mod.module)}</div>
							<div class="ra-hb__lane"><div class="ra-hb__fill ${cls}" style="width:${
								(mod.users / worst) * 100
							}%"></div></div>
							<div class="ra-hb__pct">${num(mod.users)}</div>
						</div>`;
					})
					.join("")
			);
		};

		this.$main.find(".ra-modsort button").on("click", (event) => {
			this.$main.find(".ra-modsort button").removeClass("on");
			$(event.currentTarget).addClass("on");
			draw();
		});
		draw();
	}

	// --------------------------------------------------------------- assign

	async view_assign() {
		this.$main.html(`
			${this.head(
				__("Assign Access"),
				__("Pick a person, see exactly what changes, then confirm — nothing is written before you do")
			)}
			<div class="ra-row2eq">
				<div class="ra-card">
					<div class="ra-card__head"><h3>${__("1 · Who")}</h3><div class="ra-meta ra-scopenote"></div></div>
					<div class="ra-userpick"></div>
					<div class="ra-current" style="margin-top:18px"></div>
				</div>
				<div class="ra-card">
					<div class="ra-card__head"><h3>${__("2 · What")}</h3><div class="ra-meta">${__("least access first")}</div></div>
					<div class="ra-grantable"><div class="ra-empty"><span class="ra-spinner"></span></div></div>
				</div>
			</div>
			<div class="ra-card ra-previewcard" hidden>
				<div class="ra-card__head"><h3>${__("3 · Confirm")}</h3><div class="ra-meta">${__("assigning replaces the current profile — it does not add to it")}</div></div>
				<div class="ra-previewbody"></div>
			</div>
		`);

		let profiles;
		try {
			profiles = await frappe.xcall("role_advisor.api.get_grantable_profiles");
		} catch (error) {
			this.$main.find(".ra-userpick").html(
				`<div class="ra-empty">${esc(error.message || __("You are not a delegated administrator."))}</div>`
			);
			this.$main.find(".ra-grantable").html(
				`<div class="ra-empty">${__("A System Manager sets your scope and allowlist on a Delegated User Admin record.")}</div>`
			);
			return;
		}

		this.$main
			.find(".ra-scopenote")
			.text(
				this.summary.scope_companies.length
					? __("scoped to {0}", [this.summary.scope_companies.join(", ")])
					: __("your scope")
			);

		this.user_field = frappe.ui.form.make_control({
			parent: this.$main.find(".ra-userpick"),
			df: {
				fieldtype: "Link",
				options: "User",
				label: __("User"),
				fieldname: "ra_user",
				placeholder: __("Search the users you administer"),
				// Scoped server query, so the picker cannot suggest someone the
				// caller would then be refused for.
				get_query: "role_advisor.api.manageable_user_query",
				change: () => this.on_pick_user(),
			},
			render_input: true,
		});

		this.$main.find(".ra-grantable").html(
			profiles.length
				? profiles
						.map(
							(row, index) => `
					<div class="ra-lrow clickable" data-profile="${esc(row.role_profile)}">
						<div class="ra-rank ${index === 0 ? "lead" : ""}">${index + 1}</div>
						<div>
							<div class="ra-name">${esc(row.role_profile)}</div>
							<div class="ra-lmeta">${num(row.doctype_count)} ${__("doctypes")} · ${num(row.perm_count)} ${__("grants")}</div>
						</div>
						<button class="ra-btn ghost sm">${__("Preview")}</button>
					</div>`
						)
						.join("")
				: `<div class="ra-empty">${__("Your allowlist is empty.")}</div>`
		);

		this.$main.find(".ra-grantable .ra-lrow").on("click", (event) => {
			this.preview($(event.currentTarget).data("profile"));
		});
	}

	async on_pick_user() {
		const user = this.user_field.get_value();
		if (!user || user === this.assign.user) return;
		this.assign.user = user;
		this.$main.find(".ra-previewcard").attr("hidden", true);

		const rows = await frappe.xcall("role_advisor.api.get_manageable_users", {
			search: user,
			limit: 1,
		});
		const row = (rows || [])[0];
		if (!row) return;

		this.$main.find(".ra-current").html(`
			<div class="ra-tile__stats" style="grid-template-columns:repeat(2,1fr)">
				<div><small>${__("Holds now")}</small><b style="font-size:14px">${esc(
					(row.role_profiles || []).join(", ") || __("no profile")
				)}</b></div>
				<div><small>${__("Module profile")}</small><b style="font-size:14px">${esc(
					row.module_profile || __("none")
				)}</b></div>
				<div><small>${__("User type")}</small><b style="font-size:14px">${esc(row.user_type)}</b></div>
				<div><small>${__("Login")}</small><b style="font-size:14px">${esc(row.name)}</b></div>
			</div>
			<div class="ra-meta" style="margin-top:12px">${__("Pick a profile on the right to see the exact change.")}</div>
		`);
	}

	async preview(profile) {
		if (!this.assign.user) {
			frappe.show_alert({ message: __("Choose a user first."), indicator: "orange" });
			return;
		}

		const $card = this.$main.find(".ra-previewcard");
		$card.removeAttr("hidden");
		this.$main
			.find(".ra-previewbody")
			.html(`<div class="ra-empty"><span class="ra-spinner"></span> ${__("Working out the change…")}</div>`);

		let diff;
		try {
			diff = await frappe.xcall("role_advisor.api.preview_assignment", {
				user: this.assign.user,
				role_profile: profile,
			});
		} catch (error) {
			this.$main.find(".ra-previewbody").html(`<div class="ra-empty">${esc(error.message)}</div>`);
			return;
		}

		this.assign.profile = profile;
		const badges = (items, cls) =>
			items.length
				? items.map((item) => `<span class="ra-badge ${cls}">${esc(item)}</span>`).join("")
				: `<span class="ra-meta">${__("none")}</span>`;

		this.$main.find(".ra-previewbody").html(`
			<div class="ra-tile__stats" style="grid-template-columns:repeat(3,1fr);margin-bottom:20px">
				<div><small>${__("User")}</small><b style="font-size:14px">${esc(this.assign.user)}</b></div>
				<div><small>${__("From")}</small><b style="font-size:14px">${esc(
					diff.profiles_before.join(", ") || __("no profile")
				)}</b></div>
				<div><small>${__("To")}</small><b style="font-size:14px">${esc(diff.profiles_after.join(", "))}</b></div>
			</div>
			<div class="ra-diff">
				<div class="ra-diffcol">
					<b>${__("Roles gained")} · ${diff.roles_gained.length}</b>
					<div class="ra-badges">${badges(diff.roles_gained, "gain")}</div>
				</div>
				<div class="ra-diffcol">
					<b>${__("Roles lost")} · ${diff.roles_lost.length}</b>
					<div class="ra-badges">${badges(diff.roles_lost, "loss")}</div>
				</div>
			</div>
			<div style="margin-top:22px;display:flex;gap:10px;align-items:center">
				<button class="ra-btn ra-confirm">${__("Assign {0}", [esc(profile)])}</button>
				<button class="ra-btn ghost ra-cancel">${__("Cancel")}</button>
				${
					diff.roles_lost.length
						? `<span class="ra-tag bad">${__("{0} roles will be revoked", [diff.roles_lost.length])}</span>`
						: ""
				}
			</div>
		`);

		this.$main.find(".ra-cancel").on("click", () => $card.attr("hidden", true));
		this.$main.find(".ra-confirm").on("click", () => this.commit());
	}

	async commit() {
		const $button = this.$main.find(".ra-confirm").prop("disabled", true);
		$button.html(`<span class="ra-spinner"></span> ${__("Assigning…")}`);

		try {
			const result = await frappe.xcall("role_advisor.api.assign_access", {
				user: this.assign.user,
				role_profile: this.assign.profile,
			});
			frappe.show_alert({
				message: __("{0} now holds {1}", [this.assign.user, result.profiles.join(", ")]),
				indicator: result.outcome === "Applied" ? "green" : "blue",
			});
			// The audit count and the user's current holding both moved.
			this.cache = {};
			this.summary = await frappe.xcall("role_advisor.dashboard.summary");
			this.$main.find(".ra-previewcard").attr("hidden", true);
			this.on_pick_user();
			this.page.main
				.find('.ra-nav a[data-view="audit"] .n')
				.text(num(this.summary.assignments));
		} catch (error) {
			frappe.msgprint({ title: __("Refused"), message: esc(error.message), indicator: "red" });
			$button.prop("disabled", false).text(__("Assign {0}", [this.assign.profile]));
		}
	}

	// ---------------------------------------------------------------- audit

	async view_audit() {
		this.$main.html(`
			${this.head(
				__("Audit Trail"),
				__("Every assignment ever made, including the ones that changed nothing")
			)}
			<div class="ra-card">
				<div class="ra-card__head"><h3>${__("Assignments")}</h3><div class="ra-meta">${__("newest first · rows cannot be edited or deleted")}</div></div>
				<div class="ra-list ra-auditrows"><div class="ra-empty"><span class="ra-spinner"></span></div></div>
			</div>
		`);

		const rows = await this.fetch("audit", "recent_assignments", { limit: 50 });

		this.$main.find(".ra-auditrows").html(
			rows.length
				? rows
						.map((row) => {
							const cls =
								row.outcome === "Applied" ? "" : row.outcome === "Refused" ? "bad" : "mute";
							return `
						<div class="ra-lrow clickable" data-log="${esc(row.name)}">
							<div class="ra-rank">${esc((row.actor || "?").slice(0, 2).toUpperCase())}</div>
							<div>
								<div class="ra-name">${esc(row.target_user)} <span class="ra-chip ${cls}">${esc(row.outcome)}</span></div>
								<div class="ra-lmeta">${esc(row.profiles_before || __("no profile"))} → ${esc(
									row.profiles_after || __("no profile")
								)} · ${esc(row.trigger)} · ${__("by")} ${esc(row.actor)} · ${frappe.datetime.comment_when(
									row.creation
								)}</div>
							</div>
							<div class="ra-qty">${row.roles_gained ? `+${row.roles_gained.split(",").length}` : "0"}<small>${
								row.roles_lost ? `−${row.roles_lost.split(",").length} ${__("lost")}` : __("no loss")
							}</small></div>
						</div>`;
						})
						.join("")
				: `<div class="ra-empty">${__("Nothing assigned yet.")}</div>`
		);

		this.$main.find(".ra-auditrows .ra-lrow").on("click", (event) => {
			frappe.set_route("Form", "Access Assignment Log", $(event.currentTarget).data("log"));
		});
	}
}
