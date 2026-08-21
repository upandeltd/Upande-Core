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
	{ id: "request", label: "Request Access", icon: "search" },
	{ id: "queue", label: "Incoming Requests", icon: "inbox", count: "open_requests" },
	{ id: "assign", label: "Assign Access", icon: "check" },
	{ id: "map", label: "Designation Map", icon: "map", count: "map_rows" },
	{ id: "sweep", label: "Bulk Sweep", icon: "zap" },
	{ id: "reports", label: "Reports", icon: "file" },
	{ id: "audit", label: "Audit Trail", icon: "clock", count: "assignments" },
	{ id: "admin", label: "Delegates & Policy", icon: "shield", count: "delegates" },
];

const ICONS = {
	grid: '<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/>',
	users: '<path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/>',
	layers: '<polygon points="12 2 2 7 12 12 22 7 12 2"/><polyline points="2 17 12 22 22 17"/><polyline points="2 12 12 17 22 12"/>',
	box: '<path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"/>',
	check: '<path d="M9 11l3 3L22 4"/><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"/>',
	clock: '<circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/>',
	map: '<polygon points="1 6 8 3 16 6 23 3 23 18 16 21 8 18 1 21 1 6"/><line x1="8" y1="3" x2="8" y2="18"/><line x1="16" y1="6" x2="16" y2="21"/>',
	zap: '<polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/>',
	file: '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/>',
	inbox: '<polyline points="22 12 16 12 14 15 10 15 8 12 2 12"/><path d="M5.45 5.11L2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z"/>',
	search: '<circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/>',
	shield: '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>',
	refresh: '<polyline points="23 4 23 10 17 10"/><polyline points="1 20 1 14 7 14"/><path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"/>',
};

const esc = (value) => frappe.utils.escape_html(String(value == null ? "" : value));
const num = (value) => Number(value || 0).toLocaleString();
const cint = (value) => parseInt(value, 10) || 0;

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
					<div>
						<div class="ra-side__label">${__("Yourself")}</div>
						<nav class="ra-nav">
							<a class="ra-tomine">
								<svg viewBox="0 0 24 24">${ICONS.search}</svg>
								${__("My Access")}
							</a>
						</nav>
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

		this.page.main.find(".ra-nav a[data-view]").on("click", (event) => {
			const view = $(event.currentTarget).data("view");
			this.go(view);
		});

		// Administrators are users too: the self-service page is where they see
		// their own access rather than the estate's.
		this.page.main.find(".ra-tomine").on("click", () => frappe.set_route("my-access"));
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

	// ------------------------------------------------------------- drawer

	drawer(title, subtitle, body) {
		$(".ra-scrim, .ra-drawer").remove();
		const $scrim = $('<div class="ra-scrim"></div>').appendTo("body");
		const $drawer = $(`
			<div class="ra-drawer ra-dash" role="dialog" aria-modal="true">
				<div class="ra-drawer__head">
					<div><h2>${title}</h2>${subtitle ? `<small>${subtitle}</small>` : ""}</div>
					<button class="ra-close" aria-label="${__("Close")}">✕</button>
				</div>
				<div class="ra-drawer__body">${body}</div>
			</div>`).appendTo("body");

		const close = () => {
			$drawer.removeClass("open");
			$scrim.removeClass("open");
			setTimeout(() => {
				$drawer.remove();
				$scrim.remove();
			}, 260);
			$(document).off("keydown.ra");
		};
		requestAnimationFrame(() => {
			$drawer.addClass("open");
			$scrim.addClass("open");
		});
		$scrim.on("click", close);
		$drawer.find(".ra-close").on("click", close);
		// Escape closes: a drawer you cannot dismiss by keyboard is a trap.
		$(document).on("keydown.ra", (event) => {
			if (event.key === "Escape") close();
		});

		return { $drawer, close };
	}

	loading_drawer(title) {
		return this.drawer(title, "", `<div class="ra-empty"><span class="ra-spinner"></span></div>`);
	}

	async open_user(user) {
		const { $drawer } = this.loading_drawer(esc(user));
		let d;
		try {
			d = await frappe.xcall("role_advisor.dashboard.user_detail", { user });
		} catch (error) {
			$drawer.find(".ra-drawer__body").html(`<div class="ra-empty">${esc(error.message)}</div>`);
			return;
		}

		const e = d.employee || {};
		$drawer.find("h2").text(d.user.full_name || d.user.name);
		$drawer.find("small").text(d.user.name);
		$drawer.find(".ra-drawer__body").html(`
			<div class="ra-card ra-sect">
				<b>${__("Access")}</b>
				<dl class="ra-kv">
					<dt>${__("Role profile")}</dt><dd>${esc(d.profiles.join(", ") || __("none"))}</dd>
					<dt>${__("Module profile")}</dt><dd>${esc(d.user.module_profile || __("none"))}</dd>
					<dt>${__("Roles held")}</dt><dd>${num(d.roles.length)}</dd>
					<dt>${__("Doctypes reachable")}</dt><dd>${num(d.doctypes)}</dd>
					<dt>${__("Total grants")}</dt><dd>${num(d.grants)}</dd>
					<dt>${__("User permissions")}</dt><dd>${num(d.permissions.length)}</dd>
					<dt>${__("Status")}</dt><dd>${d.user.enabled ? __("enabled") : __("disabled")} · ${esc(d.user.user_type)}</dd>
				</dl>
				${
					d.roles_outside_profile.length
						? `<div class="ra-tag bad" style="margin-top:12px">${__(
								"{0} roles sit outside every profile — the next save of this user revokes them: {1}",
								[d.roles_outside_profile.length, esc(d.roles_outside_profile.join(", "))]
						  )}</div>`
						: ""
				}
			</div>
			<div class="ra-card ra-sect">
				<b>${__("Employee")}</b>
				${
					d.employee
						? `<dl class="ra-kv">
								<dt>${__("Company")}</dt><dd>${esc(e.company || "—")}</dd>
								<dt>${__("Designation")}</dt><dd>${esc(e.designation || "—")}</dd>
								<dt>${__("Department")}</dt><dd>${esc(e.department || "—")}</dd>
								<dt>${__("Branch")}</dt><dd>${esc(e.branch || "—")}</dd>
								<dt>${__("Grade")}</dt><dd>${esc(e.grade || "—")}</dd>
						   </dl>`
						: `<div class="ra-meta">${__(
								"No active employee record — so no company, and no delegated administrator can reach this user."
						  )}</div>`
				}
			</div>
			<div class="ra-card ra-sect">
				<b>${__("Widest grants")}</b>
				<div class="ra-matrix"><table class="ra-table"><thead><tr><th>${__("Doctype")}</th><th>${__("Rights")}</th></tr></thead><tbody>
					${
						d.top_grants.length
							? d.top_grants
									.map(
										(row) =>
											`<tr><td><b>${esc(row.doctype)}</b></td><td>${row.rights
												.map((r) => `<span class="ra-badge">${esc(r)}</span>`)
												.join(" ")}</td></tr>`
									)
									.join("")
							: `<tr><td colspan="2" class="ra-meta">${__("This user's profile grants nothing.")}</td></tr>`
					}
				</tbody></table></div>
			</div>
			<div class="ra-card ra-sect">
				<b>${__("Assignment history")}</b>
				<div class="ra-list">
					${
						d.history.length
							? d.history
									.map(
										(row) => `<div class="ra-lrow"><div class="ra-rank">${esc(
											(row.actor || "?").slice(0, 2).toUpperCase()
										)}</div><div><div class="ra-name">${esc(row.profiles_before || __("none"))} → ${esc(
											row.profiles_after || __("none")
										)}</div><div class="ra-lmeta">${esc(row.trigger)} · ${esc(
											row.outcome
										)} · ${frappe.datetime.comment_when(row.creation)}</div></div><div></div></div>`
									)
									.join("")
							: `<div class="ra-meta">${__("Never assigned through Role Advisor.")}</div>`
					}
				</div>
			</div>
			<button class="ra-btn ra-assign-here">${__("Assign a profile to this user")}</button>
		`);

		$drawer.find(".ra-assign-here").on("click", () => {
			$(".ra-scrim").trigger("click");
			this.pending_user = d.user.name;
			this.go("assign");
		});
	}

	async open_profile(profile) {
		const { $drawer } = this.loading_drawer(esc(profile));
		const d = await frappe.xcall("role_advisor.dashboard.profile_detail", { profile });

		$drawer.find("h2").text(d.profile);
		$drawer
			.find("small")
			.text(__("{0} roles · {1} doctypes · {2} grants", [d.roles.length, d.doctypes, d.grants]));
		$drawer.find(".ra-drawer__body").html(`
			${
				d.privileged
					? `<div class="ra-card ra-sect"><div class="ra-tag bad">${__(
							"Cannot be delegated — grants {0}",
							[esc(d.privileged_grants)]
					  )}</div></div>`
					: ""
			}
			${
				d.duplicate_of.length
					? `<div class="ra-card ra-sect"><div class="ra-tag warn">${__(
							"Identical to {0} — same grants, different name",
							[esc(d.duplicate_of.join(", "))]
					  )}</div></div>`
					: ""
			}
			${
				d.subset_of
					? `<div class="ra-card ra-sect"><div class="ra-tag flat">${__(
							"A strict subset of {0}",
							[esc(d.subset_of)]
					  )}</div></div>`
					: ""
			}
			<div class="ra-card ra-sect">
				<b>${__("Roles that compose it")} · ${d.roles.length}</b>
				<div class="ra-badges">${
					d.roles.length
						? d.roles.map((r) => `<span class="ra-badge">${esc(r)}</span>`).join("")
						: `<span class="ra-meta">${__("none — this profile grants nothing")}</span>`
				}</div>
			</div>
			<div class="ra-card ra-sect">
				<b>${__("Reach by module")} · ${d.modules.length}</b>
				<div class="ra-badges">${d.modules
					.map((m) => `<span class="ra-badge">${esc(m.module)} · ${m.doctypes}</span>`)
					.join("")}</div>
			</div>
			<div class="ra-card ra-sect">
				<b>${__("Who holds it")} · ${d.holders.length}</b>
				<div class="ra-matrix"><table class="ra-table"><thead><tr><th>${__("User")}</th><th>${__(
					"Company"
				)}</th><th>${__("Designation")}</th></tr></thead><tbody>
					${
						d.holders.length
							? d.holders
									.map(
										(h) =>
											`<tr data-user="${esc(h.user)}"><td><b>${esc(
												h.full_name || h.user
											)}</b>${h.enabled ? "" : ` <span class="ra-chip mute">${__("disabled")}</span>`}</td><td>${esc(
												h.company || "—"
											)}</td><td>${esc(h.designation || "—")}</td></tr>`
									)
									.join("")
							: `<tr><td colspan="3" class="ra-meta">${__("Nobody holds this profile.")}</td></tr>`
					}
				</tbody></table></div>
			</div>
			<div class="ra-card ra-sect">
				<b>${__("Permission matrix")} · ${d.matrix.length} ${__("doctypes")}</b>
				<div class="ra-matrix"><table class="ra-table"><thead><tr><th>${__("Module")}</th><th>${__(
					"Doctype"
				)}</th><th>${__("Rights")}</th></tr></thead><tbody>
					${d.matrix
						.map(
							(row) =>
								`<tr><td>${esc(row.module)}</td><td><b>${esc(row.doctype)}</b></td><td>${row.rights
									.map((r) => `<span class="ra-badge">${esc(r)}</span>`)
									.join(" ")}</td></tr>`
						)
						.join("")}
				</tbody></table></div>
			</div>
		`);

		$drawer.find("tr[data-user]").css("cursor", "pointer").on("click", (event) => {
			this.open_user($(event.currentTarget).data("user"));
		});
	}

	async open_module(module) {
		const { $drawer } = this.loading_drawer(esc(module));
		const d = await frappe.xcall("role_advisor.dashboard.module_detail", { module });

		$drawer.find("small").text(
			__("{0} doctypes · {1} users can reach it via {2} profiles", [
				d.doctypes_total,
				d.users,
				d.profiles.length,
			])
		);
		$drawer.find(".ra-drawer__body").html(`
			<div class="ra-card ra-sect">
				<b>${__("Profiles that reach this module")}</b>
				<div class="ra-matrix"><table class="ra-table"><thead><tr><th>${__("Profile")}</th><th class="ra-num">${__(
					"Doctypes"
				)}</th><th class="ra-num">${__("Users")}</th></tr></thead><tbody>
					${d.profiles
						.map(
							(row) =>
								`<tr data-profile="${esc(row.profile)}"><td><b>${esc(
									row.profile
								)}</b></td><td class="ra-num">${row.doctypes}</td><td class="ra-num">${row.users}</td></tr>`
						)
						.join("")}
				</tbody></table></div>
			</div>
		`);
		$drawer.find("tr[data-profile]").css("cursor", "pointer").on("click", (event) => {
			this.open_profile($(event.currentTarget).data("profile"));
		});
	}

	async open_log(name) {
		const { $drawer } = this.loading_drawer(__("Assignment"));
		const d = await frappe.xcall("role_advisor.dashboard.log_detail", { name });
		const badges = (text, cls) =>
			text
				? text
						.split(", ")
						.map((item) => `<span class="ra-badge ${cls}">${esc(item)}</span>`)
						.join("")
				: `<span class="ra-meta">${__("none")}</span>`;

		$drawer.find("h2").text(d.target_user);
		$drawer.find("small").text(
			__("{0} · by {1} · {2}", [d.outcome, d.actor, frappe.datetime.str_to_user(d.creation)])
		);
		$drawer.find(".ra-drawer__body").html(`
			<div class="ra-card ra-sect">
				<dl class="ra-kv">
					<dt>${__("Trigger")}</dt><dd>${esc(d.trigger)}</dd>
					<dt>${__("Outcome")}</dt><dd>${esc(d.outcome)}</dd>
					<dt>${__("Profile before")}</dt><dd>${esc(d.profiles_before || __("none"))}</dd>
					<dt>${__("Profile after")}</dt><dd>${esc(d.profiles_after || __("none"))}</dd>
					<dt>${__("Module before")}</dt><dd>${esc(d.module_profile_before || __("none"))}</dd>
					<dt>${__("Module after")}</dt><dd>${esc(d.module_profile_after || __("none"))}</dd>
				</dl>
				${d.decision_notes ? `<div class="ra-meta" style="margin-top:12px">${esc(d.decision_notes)}</div>` : ""}
			</div>
			<div class="ra-card ra-sect"><b>${__("Roles gained")}</b><div class="ra-badges">${badges(
				d.roles_gained,
				"gain"
			)}</div></div>
			<div class="ra-card ra-sect"><b>${__("Roles lost")}</b><div class="ra-badges">${badges(
				d.roles_lost,
				"loss"
			)}</div></div>
		`);
	}

	async fetch(key, method, args) {
		// A bare name is a dashboard method; anything containing a dot is a full
		// path, so views can cache calls to other modules too.
		if (!this.cache[key]) {
			const path = method.includes(".") ? method : `role_advisor.dashboard.${method}`;
			this.cache[key] = await frappe.xcall(path, args);
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
		this.$main.find(".ra-overview-mods .ra-mod").on("click", (event) =>
			this.open_module($(event.currentTarget).data("module"))
		);

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
				this.open_user($(event.currentTarget).data("user"));
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
				this.open_profile($(event.currentTarget).data("profile"));
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
					<div class="ra-mod ${mod.severity}" data-module="${esc(mod.module)}" title="${esc(mod.module)} · ${num(
							mod.users
						)} ${__("users")} · ${mod.profiles} ${__("profiles")}">
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
		this.$main.on("click", ".ra-allmods .ra-mod", (event) =>
			this.open_module($(event.currentTarget).data("module"))
		);
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

		// Arrived here from a user drawer: pre-select them.
		if (this.pending_user) {
			this.user_field.set_value(this.pending_user);
			this.pending_user = null;
		}
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

	// ---------------------------------------------------------------- queue

	async view_queue() {
		this.$main.html(`
			${this.head(
				__("Incoming Requests"),
				__("What people have asked to be able to do, and what it would take"),
				`<div class="ra-pillgroup ra-qfilter">
					<button class="on" data-f="all">${__("All open")}</button>
					<button data-f="ready">${__("Ready to grant")}</button>
					<button data-f="gap">${__("Needs building")}</button>
				</div>`
			)}
			<div class="ra-queuebody"><div class="ra-empty"><span class="ra-spinner"></span></div></div>
		`);

		const rows = await this.fetch("queue", "role_advisor.requests.queue", { limit: 100 });
		this.$main.find(".ra-qfilter button").on("click", (event) => {
			this.$main.find(".ra-qfilter button").removeClass("on");
			$(event.currentTarget).addClass("on");
			draw();
		});

		const draw = () => {
			const filter = this.$main.find(".ra-qfilter button.on").data("f");
			const shown = rows.filter((row) => {
				if (filter === "ready") return Boolean(row.recommended_profile);
				if (filter === "gap") return !row.recommended_profile;
				return true;
			});

			if (!shown.length) {
				this.$main.find(".ra-queuebody").html(
					`<div class="ra-card"><div class="ra-empty">${
						rows.length
							? __("Nothing in this group.")
							: __(
									"No open requests. People raise them from My Access, or you can raise one under Request Access."
							  )
					}</div></div>`
				);
				return;
			}

			this.$main.find(".ra-queuebody").html(
				shown
					.map((row) => {
						const tone = row.recommended_profile
							? "ready"
							: row.resolution && row.resolution.startsWith("Gap")
							? "gap"
							: "open";
						return `
					<div class="ra-req ${tone}" data-req="${esc(row.name)}">
						<div class="ra-req__head">
							<div class="ra-req__who">
								<b class="ra-openuser" style="cursor:pointer">${esc(row.for_user)}</b>
								<small>${esc(row.name)} · ${esc(row.company || __("no company"))} · ${__(
							"raised by"
						)} ${esc(row.raised_by)} · ${frappe.datetime.comment_when(row.creation)}</small>
							</div>
							<div class="ra-req__acts">
								<span class="ra-chip ${
									row.recommended_profile ? "" : "bad"
								}">${esc(row.resolution || row.status)}</span>
								<button class="ra-btn ghost sm ra-recheck">${__("Re-check")}</button>
								${
									row.recommended_profile
										? `<button class="ra-btn sm ra-grant">${__("Grant {0}", [
												esc(row.recommended_profile),
										  ])}</button>`
										: ""
								}
								<button class="ra-btn ghost sm ra-refuse">${__("Refuse")}</button>
							</div>
						</div>
						<div class="ra-badges">${(row.transactions || [])
							.map(
								(line) =>
									`<span class="ra-badge">${esc(line.document_type)} · ${esc(
										line.right
									)}</span>`
							)
							.join("")}</div>
						${(() => {
							// The full over-grant list swamps the card. Show the
							// first few and the count; the rest is in the title.
							if (!row.over_grant) return "";
							const parts = row.over_grant.split("; ").filter(Boolean);
							const head = parts.slice(0, 3).join("; ");
							const rest = parts.length - 3;
							return `<div class="ra-meta ra-ellipsis" style="margin-top:10px;max-width:100%"
								title="${esc(row.over_grant)}">${__("Would also grant:")} ${esc(head)}${
								rest > 0 ? ` ${__("and {0} more areas", [rest])}` : ""
							}</div>`;
						})()}
						${row.reason ? `<div class="ra-req__why">“${esc(row.reason)}”</div>` : ""}
					</div>`;
					})
					.join("")
			);

			const $body = this.$main.find(".ra-queuebody");

			$body.find(".ra-openuser").on("click", (event) =>
				this.open_user($(event.currentTarget).closest(".ra-req").find(".ra-openuser").text())
			);

			$body.find(".ra-recheck").on("click", async (event) => {
				const name = $(event.currentTarget).closest(".ra-req").data("req");
				const $button = $(event.currentTarget).prop("disabled", true);
				try {
					const v = await frappe.xcall("role_advisor.requests.recheck", { request: name });
					frappe.show_alert({
						message: __("{0} · now {1}", [name, v.resolution]),
						indicator: v.profile ? "green" : "orange",
					});
					delete this.cache.queue;
					this.view_queue();
				} catch (error) {
					frappe.msgprint({ title: __("Failed"), message: esc(error.message), indicator: "red" });
					$button.prop("disabled", false);
				}
			});

			$body.find(".ra-grant").on("click", (event) => {
				const $req = $(event.currentTarget).closest(".ra-req");
				const name = $req.data("req");
				const row = rows.find((candidate) => candidate.name === name);

				frappe.confirm(
					__(
						"Grant {0} to {1}? Their current profile is replaced, and the change is logged.",
						[`<b>${esc(row.recommended_profile)}</b>`, `<b>${esc(row.for_user)}</b>`]
					),
					async () => {
						try {
							const result = await frappe.xcall("role_advisor.requests.fulfil", {
								request: name,
							});
							frappe.show_alert({
								message: __("{0} now holds {1}", [
									row.for_user,
									result.profiles.join(", "),
								]),
								indicator: "green",
							});
							this.cache = {};
							this.load();
						} catch (error) {
							frappe.msgprint({
								title: __("Refused"),
								message: esc(error.message),
								indicator: "red",
							});
						}
					}
				);
			});

			$body.find(".ra-refuse").on("click", (event) => {
				const name = $(event.currentTarget).closest(".ra-req").data("req");
				const dialog = new frappe.ui.Dialog({
					title: __("Refuse {0}", [name]),
					fields: [
						{
							fieldtype: "Small Text",
							fieldname: "note",
							label: __("Why"),
							reqd: 1,
							description: __("The requester can read this, so say something useful."),
						},
					],
					primary_action_label: __("Refuse"),
					primary_action: async (values) => {
						try {
							await frappe.xcall("role_advisor.requests.refuse", {
								request: name,
								note: values.note,
							});
							dialog.hide();
							frappe.show_alert({ message: __("{0} refused", [name]), indicator: "orange" });
							this.cache = {};
							this.load();
						} catch (error) {
							frappe.msgprint({
								title: __("Failed"),
								message: esc(error.message),
								indicator: "red",
							});
						}
					},
				});
				dialog.show();
			});
		};

		draw();
	}

	// -------------------------------------------------------------- request

	async view_request() {
		this.basket = this.basket || [];

		this.$main.html(`
			${this.head(
				__("Request Access"),
				__(
					"Name the documents someone needs to work with. The profile is worked out for you — nobody has to know the permission model."
				)
			)}
			<div class="ra-row2eq">
				<div class="ra-card">
					<div class="ra-card__head"><h3>${__("1 · Who needs it")}</h3><div class="ra-meta ra-whonote"></div></div>
					<div class="ra-reqwho"></div>
				</div>
				<div class="ra-card">
					<div class="ra-card__head">
						<h3>${__("2 · What they need to work with")}</h3>
						<div class="ra-meta">${__("search any document")}</div>
					</div>
					<input class="ra-input ra-docsearch" type="search" style="width:100%"
						placeholder="${__("Leave Application, Sales Invoice, Harvest…")}">
					<div class="ra-results" hidden></div>
					<div class="ra-basket" style="margin-top:14px"></div>
					<div class="ra-meta ra-bundlehint" style="margin-top:10px"></div>
				</div>
			</div>
			<div class="ra-card">
				<div class="ra-card__head">
					<h3>${__("3 · What that would take")}</h3>
					<div class="ra-meta">${__("resolved from live permissions — nothing is written yet")}</div>
				</div>
				<div class="ra-verdictbody"><div class="ra-empty">${__(
					"Pick a person and at least one document."
				)}</div></div>
			</div>
		`);

		// Anyone may ask for themselves; a delegate may ask for anyone in scope.
		const delegate = this.summary.delegates > 0 || this.summary.scoped;
		this.$main
			.find(".ra-whonote")
			.text(delegate ? __("yourself, or anyone you administer") : __("yourself"));

		this.req_user = frappe.ui.form.make_control({
			parent: this.$main.find(".ra-reqwho"),
			df: {
				fieldtype: "Link",
				options: "User",
				label: __("User"),
				fieldname: "ra_req_user",
				// The scoped query when the caller is a delegate; otherwise they
				// can still type their own login, which the server allows.
				get_query: "role_advisor.api.manageable_user_query",
				change: () => this.resolve_request(),
			},
			render_input: true,
		});
		this.req_user.set_value(frappe.session.user);

		let timer;
		this.$main.find(".ra-docsearch").on("input", (event) => {
			clearTimeout(timer);
			const txt = $(event.currentTarget).val();
			timer = setTimeout(() => this.search_docs(txt), 180);
		});

		this.draw_basket();
	}

	async search_docs(txt) {
		const $results = this.$main.find(".ra-results");
		if (!txt || txt.length < 2) {
			$results.attr("hidden", true);
			this.$main.find(".ra-bundlehint").text("");
			return;
		}

		const [docs, bundles] = await Promise.all([
			frappe.xcall("role_advisor.requests.search_documents", { txt, limit: 18 }),
			frappe.xcall("role_advisor.requests.search_bundles", { txt, limit: 5 }),
		]);

		$results.removeAttr("hidden").html(
			[
				...bundles.map(
					(bundle) => `
					<div class="ra-result" data-bundle="${esc(bundle.name)}">
						<div><b>${esc(bundle.transaction_name)}</b><small>${__("bundle")} · ${bundle.requirements
							.map((r) => esc(r.document_type))
							.join(", ")}</small></div>
						<span class="ra-chip">${__("bundle")}</span>
					</div>`
				),
				...docs.map(
					(doc) => `
					<div class="ra-result" data-doctype="${esc(doc.name)}">
						<div><b>${esc(doc.name)}</b><small>${esc(doc.module)}</small></div>
						${doc.is_submittable ? `<span class="ra-chip mute">${__("submittable")}</span>` : "<span></span>"}
					</div>`
				),
			].join("") || `<div class="ra-empty">${__("Nothing matches.")}</div>`
		);

		this.$main
			.find(".ra-bundlehint")
			.text(
				bundles.length
					? ""
					: __(
							"No bundles authored — one is only worth creating when a single ask spans several documents."
					  )
			);

		$results.find("[data-doctype]").on("click", (event) =>
			this.add_document($(event.currentTarget).data("doctype"))
		);
		$results.find("[data-bundle]").on("click", (event) =>
			this.add_bundle($(event.currentTarget).data("bundle"))
		);
	}

	async add_document(doctype) {
		if (this.basket.some((row) => row.doctype === doctype)) {
			frappe.show_alert({ message: __("{0} is already listed.", [doctype]), indicator: "orange" });
			return;
		}
		const rights = await frappe.xcall("role_advisor.requests.rights_for", { doctype });
		// Default to the narrowest useful ask; the person widens it deliberately.
		this.basket.push({ doctype, rights, chosen: ["read"] });
		this.after_basket_change();
	}

	async add_bundle(bundle) {
		const rows = await frappe.xcall("role_advisor.requests.expand_bundle", { bundle });
		for (const row of rows) {
			const existing = this.basket.find((item) => item.doctype === row.document_type);
			if (existing) {
				if (!existing.chosen.includes(row.right)) existing.chosen.push(row.right);
				continue;
			}
			const rights = await frappe.xcall("role_advisor.requests.rights_for", {
				doctype: row.document_type,
			});
			this.basket.push({
				doctype: row.document_type,
				rights,
				chosen: [row.right],
				bundle,
			});
		}
		this.after_basket_change();
	}

	after_basket_change() {
		this.$main.find(".ra-docsearch").val("");
		this.$main.find(".ra-results").attr("hidden", true);
		this.draw_basket();
		this.resolve_request();
	}

	draw_basket() {
		const $basket = this.$main.find(".ra-basket");
		if (!this.basket.length) {
			$basket.html(`<div class="ra-meta">${__("Nothing listed yet.")}</div>`);
			return;
		}

		$basket.html(
			this.basket
				.map(
					(row, index) => `
			<div class="ra-basketrow" data-i="${index}">
				<div><b>${esc(row.doctype)}</b>${
						row.bundle ? `<small>${__("from")} ${esc(row.bundle)}</small>` : ""
					}</div>
				<div class="ra-rights">${row.rights
					.map(
						(right) =>
							`<button class="ra-right ${
								row.chosen.includes(right) ? "on" : ""
							}" data-right="${esc(right)}">${esc(right)}</button>`
					)
					.join("")}</div>
				<button class="ra-drop" title="${__("Remove")}">✕</button>
			</div>`
				)
				.join("")
		);

		$basket.find(".ra-right").on("click", (event) => {
			const $button = $(event.currentTarget);
			const index = $button.closest(".ra-basketrow").data("i");
			const right = $button.data("right");
			const row = this.basket[index];
			row.chosen = row.chosen.includes(right)
				? row.chosen.filter((r) => r !== right)
				: [...row.chosen, right];
			if (!row.chosen.length) {
				// A document with no right selected is not an ask.
				this.basket.splice(index, 1);
			}
			this.draw_basket();
			this.resolve_request();
		});

		$basket.find(".ra-drop").on("click", (event) => {
			this.basket.splice($(event.currentTarget).closest(".ra-basketrow").data("i"), 1);
			this.draw_basket();
			this.resolve_request();
		});
	}

	requirements() {
		return this.basket.flatMap((row) =>
			row.chosen.map((right) => ({
				doctype: row.doctype,
				right,
				from_bundle: row.bundle || null,
			}))
		);
	}

	async resolve_request() {
		const user = this.req_user && this.req_user.get_value();
		const requirements = this.requirements();
		const $body = this.$main.find(".ra-verdictbody");

		if (!user || !requirements.length) {
			$body.html(`<div class="ra-empty">${__("Pick a person and at least one document.")}</div>`);
			return;
		}

		$body.html(`<div class="ra-empty"><span class="ra-spinner"></span> ${__("Working it out…")}</div>`);

		let v;
		try {
			v = await frappe.xcall("role_advisor.requests.resolve", { user, requirements });
		} catch (error) {
			$body.html(`<div class="ra-empty">${esc(error.message)}</div>`);
			return;
		}

		const tone =
			v.resolution === "Covered" ? "covered" : v.resolution === "Fit Found" ? "fit" : "gap";

		$body.html(`
			<div class="ra-verdict ${tone}">
				<h4>${esc(v.resolution)}</h4>
				<p>${esc(v.notes)}</p>
			</div>
			<div class="ra-sect">
				<b>${__("What was asked for")}</b>
				<div class="ra-badges">${v.requirements
					.map(
						(row) =>
							`<span class="ra-badge">${esc(row.document_type)} · ${esc(row.right)}</span>`
					)
					.join("")}</div>
			</div>
			${
				v.profile
					? `<div class="ra-sect">
							<b>${__("Recommended")}</b>
							<div class="ra-lrow clickable ra-openprof" data-profile="${esc(v.profile)}">
								<div class="ra-rank lead">✓</div>
								<div><div class="ra-name">${esc(v.profile)}</div><div class="ra-lmeta">${num(
							v.doctypes
						)} ${__("doctypes")} · ${num(v.grants)} ${__("grants")}</div></div>
								<div class="ra-qty">${v.over_grant.length}<small>${__("extras")}</small></div>
							</div>
						</div>
						<div class="ra-sect">
							<b>${__("What it would also hand over")} · ${v.over_grant.length}</b>
							<div class="ra-badges">${
								v.over_grant.length
									? v.over_grant
											.slice(0, 40)
											.map((line) => `<span class="ra-badge loss">${esc(line)}</span>`)
											.join("")
									: `<span class="ra-meta">${__("nothing beyond the ask")}</span>`
							}</div>
							${
								v.over_grant.length > 40
									? `<div class="ra-meta" style="margin-top:8px">${__(
											"and {0} more",
											[v.over_grant.length - 40]
									  )}</div>`
									: ""
							}
						</div>
						${
							v.alternatives && v.alternatives.length > 1
								? `<div class="ra-sect"><b>${__("Other profiles that would also cover it")}</b>
										<div class="ra-badges">${v.alternatives
											.filter((a) => a !== v.profile)
											.map((a) => `<span class="ra-badge">${esc(a)}</span>`)
											.join("")}</div></div>`
								: ""
						}`
					: ""
			}
			${
				v.unreachable
					? `<div class="ra-sect"><b>${__("Nothing on this site grants")}</b>
							<div class="ra-badges">${v.unreachable
								.map((line) => `<span class="ra-badge loss">${esc(line)}</span>`)
								.join("")}</div></div>`
					: ""
			}
			${
				v.suggested_roles
					? `<div class="ra-sect"><b>${__("A new profile from these roles would cover it")}</b>
							<div class="ra-badges">${v.suggested_roles
								.map((role) => `<span class="ra-badge gain">${esc(role)}</span>`)
								.join("")}</div></div>`
					: ""
			}
			<div style="margin-top:20px;display:flex;gap:10px;align-items:center;flex-wrap:wrap">
				<button class="ra-btn ra-logreq">${__("Record this request")}</button>
				${
					v.profile
						? `<button class="ra-btn ghost ra-assignreq">${__("Record and assign {0}", [
								esc(v.profile),
						  ])}</button>`
						: ""
				}
				<input class="ra-input ra-reason" placeholder="${__("Why is this needed? (optional)")}" style="flex:1;min-width:240px">
			</div>
		`);

		$body.find(".ra-openprof").on("click", () => this.open_profile(v.profile));
		$body.find(".ra-logreq").on("click", () => this.record_request(false));
		$body.find(".ra-assignreq").on("click", () => this.record_request(true));
	}

	async record_request(and_assign) {
		const user = this.req_user.get_value();
		const reason = this.$main.find(".ra-reason").val() || "";
		const $buttons = this.$main.find(".ra-logreq, .ra-assignreq").prop("disabled", true);

		try {
			const result = await frappe.xcall("role_advisor.requests.submit_request", {
				user,
				requirements: this.requirements(),
				reason,
			});

			if (and_assign && result.profile) {
				const outcome = await frappe.xcall("role_advisor.requests.fulfil", {
					request: result.request,
				});
				frappe.show_alert({
					message: __("{0} recorded and {1} assigned", [result.request, outcome.profiles.join(", ")]),
					indicator: "green",
				});
				this.basket = [];
				this.cache = {};
				this.load();
				return;
			}

			frappe.show_alert({
				message: __("{0} recorded — {1}", [result.request, result.resolution]),
				indicator: "blue",
			});
			this.basket = [];
			this.after_basket_change();
		} catch (error) {
			frappe.msgprint({ title: __("Refused"), message: esc(error.message), indicator: "red" });
			$buttons.prop("disabled", false);
		}
	}

	// ------------------------------------------------------------------ map

	async view_map() {
		this.$main.html(`
			${this.head(
				__("Designation Map"),
				__("The access level each job title should get, decided once and reused"),
				`<div class="ra-pillgroup ra-mapfilter">
					<button class="on" data-f="pending">${__("Awaiting review")}</button>
					<button data-f="active">${__("Active")}</button>
					<button data-f="all">${__("All")}</button>
				</div>`
			)}
			<div class="ra-card">
				<div class="ra-filters">
					<input class="ra-input ra-msearch" type="search" placeholder="${__("Search designation or profile…")}">
					<span class="ra-meta ra-mcount"></span>
					<span class="ra-meta">${__("seeded from observed assignments — evidence, not endorsement")}</span>
				</div>
				<div class="ra-tablewrap"><table class="ra-table">
					<thead><tr>
						<th>${__("Active")}</th><th>${__("Designation")}</th><th>${__("Company")}</th>
						<th>${__("Role Profile")}</th><th>${__("Confidence")}</th><th>${__("Evidence")}</th>
					</tr></thead>
					<tbody class="ra-maprows"><tr><td colspan="6"><div class="ra-empty"><span class="ra-spinner"></span></div></td></tr></tbody>
				</table></div>
			</div>
		`);

		const [rows, options] = await Promise.all([
			this.fetch("map", "map_list"),
			this.fetch("profileopts", "profile_options"),
		]);
		const editable = frappe.user.has_role("System Manager");

		const draw = () => {
			const term = (this.$main.find(".ra-msearch").val() || "").toLowerCase();
			const filter = this.$main.find(".ra-mapfilter button.on").data("f");
			const shown = rows.filter((row) => {
				if (filter === "pending" && row.is_active) return false;
				if (filter === "active" && !row.is_active) return false;
				if (!term) return true;
				return [row.designation, row.role_profile, row.for_company]
					.filter(Boolean)
					.some((field) => String(field).toLowerCase().includes(term));
			});

			this.$main.find(".ra-mcount").text(__("{0} of {1} rows", [shown.length, rows.length]));
			this.$main.find(".ra-maprows").html(
				shown.length
					? shown
							.map(
								(row) => `
					<tr data-name="${esc(row.name)}">
						<td><label class="ra-switch"><input type="checkbox" class="ra-mapactive" ${
							row.is_active ? "checked" : ""
						} ${editable ? "" : "disabled"}><span class="ra-slider"></span></label></td>
						<td><b>${esc(row.designation)}</b></td>
						<td>${esc(row.for_company || __("all"))}${
									row.for_branch ? ` · ${esc(row.for_branch)}` : ""
								}</td>
						<td>${
							editable
								? `<select class="ra-inlinesel ra-mapprofile">${options
										.map(
											(opt) =>
												`<option value="${esc(opt.profile)}" ${
													opt.profile === row.role_profile ? "selected" : ""
												}>${esc(opt.profile)}${opt.privileged ? " ⚠" : ""}</option>`
										)
										.join("")}</select>`
								: esc(row.role_profile)
						}</td>
						<td><span class="ra-conf ${esc(row.confidence || "None")}">${esc(
									row.confidence || "None"
								)}</span></td>
						<td class="ra-meta ra-ellipsis" title="${esc(row.evidence || "")}">${esc(
									row.evidence || "—"
								)}</td>
					</tr>`
							)
							.join("")
					: `<tr><td colspan="6"><div class="ra-empty">${__("No rows match.")}</div></td></tr>`
			);

			this.$main.find(".ra-mapactive").on("change", async (event) => {
				const $input = $(event.currentTarget);
				const name = $input.closest("tr").data("name");
				const value = $input.is(":checked") ? 1 : 0;
				$input.prop("disabled", true);
				try {
					await frappe.xcall("role_advisor.dashboard.map_update", {
						name,
						field: "is_active",
						value,
					});
					rows.find((row) => row.name === name).is_active = value;
					frappe.show_alert({
						message: value ? __("Row activated") : __("Row deactivated"),
						indicator: value ? "green" : "orange",
					});
					// The sweep and the summary both depend on this.
					delete this.cache.sweep;
					this.summary = await frappe.xcall("role_advisor.dashboard.summary");
				} catch (error) {
					$input.prop("checked", !value);
					frappe.msgprint({ title: __("Refused"), message: esc(error.message), indicator: "red" });
				}
				$input.prop("disabled", false);
			});

			this.$main.find(".ra-mapprofile").on("change", async (event) => {
				const $select = $(event.currentTarget);
				const name = $select.closest("tr").data("name");
				try {
					await frappe.xcall("role_advisor.dashboard.map_update", {
						name,
						field: "role_profile",
						value: $select.val(),
					});
					rows.find((row) => row.name === name).role_profile = $select.val();
					frappe.show_alert({ message: __("Profile updated"), indicator: "green" });
				} catch (error) {
					frappe.msgprint({ title: __("Refused"), message: esc(error.message), indicator: "red" });
				}
			});
		};

		this.$main.find(".ra-msearch").on("input", draw);
		this.$main.find(".ra-mapfilter button").on("click", (event) => {
			this.$main.find(".ra-mapfilter button").removeClass("on");
			$(event.currentTarget).addClass("on");
			draw();
		});
		draw();
	}

	// ---------------------------------------------------------------- sweep

	async view_sweep() {
		if (!frappe.user.has_role("System Manager")) {
			this.$main.html(`
				${this.head(__("Bulk Sweep"), __("Assign profiles in bulk from the map"))}
				<div class="ra-card"><div class="ra-empty">${__(
					"The sweep is System-Manager-only. Delegates assign one user at a time under Assign Access."
				)}</div></div>`);
			return;
		}

		this.$main.html(`
			${this.head(
				__("Bulk Sweep"),
				__("Assign every unprofiled user their mapped profile — dry run first, always")
			)}
			<div class="ra-kpis ra-sweepkpis"><div class="ra-empty"><span class="ra-spinner"></span></div></div>
			<div class="ra-card">
				<div class="ra-card__head">
					<h3>${__("Ready to assign")}</h3>
					<div class="ra-meta">${__("only users whose map row is active")}</div>
				</div>
				<div class="ra-tablewrap"><table class="ra-table">
					<thead><tr><th style="width:34px"><input type="checkbox" class="ra-sweepall"></th>
					<th>${__("User")}</th><th>${__("Designation")}</th><th>${__("Company")}</th><th>${__("Will receive")}</th></tr></thead>
					<tbody class="ra-sweeprows"></tbody>
				</table></div>
				<div style="margin-top:20px;display:flex;gap:10px;align-items:center">
					<button class="ra-btn ra-sweeprun" disabled>${__("Assign selected")}</button>
					<span class="ra-meta ra-sweepsel"></span>
				</div>
			</div>
			<div class="ra-card">
				<div class="ra-card__head"><h3>${__("Blocked")}</h3><div class="ra-meta">${__("why each user cannot be swept yet")}</div></div>
				<div class="ra-blocked"></div>
			</div>
		`);

		const data = await this.fetch("sweep", "sweep_preview");

		this.$main.find(".ra-sweepkpis").html(
			[
				[__("Candidates"), num(data.total), __("unprofiled enabled users")],
				[__("Ready now"), num(data.ready.length), __("map row active")],
				[__("Blocked"), num(data.blocked.length), __("need a decision first")],
			]
				.map(
					([label, value, unit]) =>
						`<div class="ra-kpi"><div class="ra-kpi__label">${label}</div><div class="ra-kpi__value">${value}</div><div class="ra-kpi__unit">${unit}</div></div>`
				)
				.join("")
		);

		this.$main.find(".ra-sweeprows").html(
			data.ready.length
				? data.ready
						.map(
							(row) => `
				<tr><td><input type="checkbox" class="ra-sweeppick" value="${esc(row.user)}" checked></td>
				<td><b>${esc(row.full_name || row.user)}</b><div class="ra-lmeta">${esc(row.user)}</div></td>
				<td>${esc(row.designation || "—")}</td><td>${esc(row.company || "—")}</td>
				<td><b>${esc(row.role_profile)}</b></td></tr>`
						)
						.join("")
				: `<tr><td colspan="5"><div class="ra-empty">${__(
						"Nothing is ready. Activate map rows under Designation Map first."
				  )}</div></td></tr>`
		);

		this.$main.find(".ra-blocked").html(
			Object.keys(data.reasons).length
				? Object.entries(data.reasons)
						.map(
							([reason, count]) => `
					<div class="ra-hb">
						<div class="ra-hb__name">${esc(reason)}</div>
						<div class="ra-hb__lane"><div class="ra-hb__fill mid" style="width:${
							(count / data.total) * 100
						}%"></div></div>
						<div class="ra-hb__pct">${count}</div>
					</div>`
						)
						.join("")
				: `<div class="ra-meta">${__("Nothing blocked.")}</div>`
		);

		const refresh_selection = () => {
			const picked = this.$main.find(".ra-sweeppick:checked").length;
			this.$main.find(".ra-sweeprun").prop("disabled", !picked);
			this.$main.find(".ra-sweepsel").text(picked ? __("{0} selected", [picked]) : "");
		};
		this.$main.on("change", ".ra-sweeppick", refresh_selection);
		this.$main.find(".ra-sweepall").on("change", (event) => {
			this.$main.find(".ra-sweeppick").prop("checked", $(event.currentTarget).is(":checked"));
			refresh_selection();
		});
		refresh_selection();

		this.$main.find(".ra-sweeprun").on("click", () => {
			const users = this.$main
				.find(".ra-sweeppick:checked")
				.map((_, el) => el.value)
				.get();

			frappe.confirm(
				__(
					"Assign mapped profiles to {0} users? Each one's current profile is replaced, and every change is logged.",
					[users.length]
				),
				async () => {
					const $button = this.$main.find(".ra-sweeprun").prop("disabled", true);
					$button.html(`<span class="ra-spinner"></span> ${__("Assigning…")}`);
					try {
						const result = await frappe.xcall("role_advisor.dashboard.sweep_apply", { users });
						frappe.msgprint({
							title: __("Sweep complete"),
							message: __("Applied {0} · no change {1} · skipped {2}", [
								result.applied,
								result.no_change,
								result.skipped,
							]),
							indicator: "green",
						});
						this.cache = {};
						this.load();
					} catch (error) {
						frappe.msgprint({ title: __("Failed"), message: esc(error.message), indicator: "red" });
						$button.prop("disabled", false).text(__("Assign selected"));
					}
				}
			);
		});
	}

	// -------------------------------------------------------------- reports

	async view_reports() {
		const names = [
			"Designation Gap",
			"Role Profile Overgrant",
			"Module Exposure",
			"System Manager Audit",
			"Role Drift",
		];
		this.report_name = this.report_name || names[0];

		this.$main.html(`
			${this.head(
				__("Reports"),
				__("Read-only. None of these changes anything."),
				`<div class="ra-pillgroup ra-repsel">${names
					.map(
						(name) =>
							`<button class="${name === this.report_name ? "on" : ""}" data-r="${esc(
								name
							)}">${__(name)}</button>`
					)
					.join("")}</div>`
			)}
			<div class="ra-card">
				<div class="ra-card__head"><h3 class="ra-reptitle">${esc(this.report_name)}</h3><div class="ra-meta ra-repmeta"></div></div>
				<div class="ra-filters"><input class="ra-input ra-repsearch" type="search" placeholder="${__(
					"Filter rows…"
				)}"></div>
				<div class="ra-tablewrap"><table class="ra-table">
					<thead class="ra-rephead"></thead>
					<tbody class="ra-repbody"><tr><td><div class="ra-empty"><span class="ra-spinner"></span></div></td></tr></tbody>
				</table></div>
			</div>
		`);

		const load = async () => {
			this.$main.find(".ra-reptitle").text(this.report_name);
			this.$main
				.find(".ra-repbody")
				.html(`<tr><td><div class="ra-empty"><span class="ra-spinner"></span></div></td></tr>`);

			const data = await this.fetch(`rep:${this.report_name}`, "report", { name: this.report_name });
			const columns = data.columns.map((column) => ({
				field: column.fieldname || column.field || column.label,
				label: column.label || column.fieldname,
			}));

			this.$main
				.find(".ra-rephead")
				.html(`<tr>${columns.map((c) => `<th>${esc(c.label)}</th>`).join("")}</tr>`);

			const draw = () => {
				const term = (this.$main.find(".ra-repsearch").val() || "").toLowerCase();
				const rows = data.rows.filter(
					(row) =>
						!term ||
						columns.some((c) => String(row[c.field] ?? "").toLowerCase().includes(term))
				);
				this.$main.find(".ra-repmeta").text(__("{0} of {1} rows", [rows.length, data.rows.length]));
				this.$main.find(".ra-repbody").html(
					rows.length
						? rows
								.slice(0, 300)
								.map(
									(row) =>
										`<tr>${columns
											.map((c) => {
												const value = row[c.field];
												return `<td style="white-space:normal">${
													value === 1 && String(c.field).match(/^(is_|has_|self_|privileged|from_map|used_here|orphan|in_no)/)
														? "✓"
														: esc(value ?? "")
												}</td>`;
											})
											.join("")}</tr>`
								)
								.join("")
						: `<tr><td colspan="${columns.length}"><div class="ra-empty">${__("No rows.")}</div></td></tr>`
				);
			};
			this.$main.find(".ra-repsearch").off("input").on("input", draw);
			draw();
		};

		this.$main.find(".ra-repsel button").on("click", (event) => {
			this.$main.find(".ra-repsel button").removeClass("on");
			$(event.currentTarget).addClass("on");
			this.report_name = $(event.currentTarget).data("r");
			load();
		});
		load();
	}

	// ---------------------------------------------------------------- admin

	async view_admin() {
		const sysadmin = frappe.user.has_role("System Manager");
		this.$main.html(`
			${this.head(
				__("Delegates & Policy"),
				__("Who may administer access, and the rules the app follows")
			)}
			<div class="ra-card">
				<div class="ra-card__head">
					<h3>${__("Delegated administrators")}</h3>
					<div class="ra-meta">${__("a record bounds a role holder — it does not replace one")}</div>
				</div>
				<div class="ra-delegates"><div class="ra-empty"><span class="ra-spinner"></span></div></div>
				${
					sysadmin
						? `<div style="margin-top:18px"><button class="ra-btn ra-newdelegate">${__(
								"Add a delegate"
						  )}</button></div>`
						: ""
				}
			</div>
			<div class="ra-card">
				<div class="ra-card__head"><h3>${__("Policy")}</h3><div class="ra-meta">${
					sysadmin ? __("editable") : __("read-only for you")
				}</div></div>
				<div class="ra-policy"><div class="ra-empty"><span class="ra-spinner"></span></div></div>
			</div>
		`);

		const [delegates, policy] = await Promise.all([
			frappe.xcall("role_advisor.dashboard.delegate_list"),
			frappe.xcall("role_advisor.dashboard.settings_read"),
		]);

		this.$main.find(".ra-delegates").html(
			delegates.length
				? `<div class="ra-tablewrap"><table class="ra-table"><thead><tr>
						<th>${__("Enabled")}</th><th>${__("User")}</th><th>${__("Companies")}</th>
						<th>${__("May grant")}</th><th>${__("Has the role")}</th></tr></thead><tbody>
					${delegates
						.map(
							(row) => `
						<tr data-user="${esc(row.user)}">
							<td><label class="ra-switch"><input type="checkbox" class="ra-deltoggle" ${
								row.enabled ? "checked" : ""
							} ${sysadmin ? "" : "disabled"}><span class="ra-slider"></span></label></td>
							<td><b>${esc(row.user)}</b></td>
							<td>${esc(row.companies.join(", ") || "—")}</td>
							<td>${
								row.profiles.length
									? row.profiles.map((p) => `<span class="ra-badge">${esc(p)}</span>`).join(" ")
									: `<span class="ra-chip bad">${__("empty")}</span>`
							}</td>
							<td>${
								row.has_role
									? `<span class="ra-chip">${__("yes")}</span>`
									: `<span class="ra-chip bad">${__("missing — record does nothing")}</span>`
							}</td>
						</tr>`
						)
						.join("")}
				</tbody></table></div>`
				: `<div class="ra-empty">${__(
						"No delegates yet — so nothing about this site's behaviour has changed."
				  )}</div>`
		);

		this.$main.find(".ra-deltoggle").on("change", async (event) => {
			const $input = $(event.currentTarget);
			const user = $input.closest("tr").data("user");
			const enabled = $input.is(":checked") ? 1 : 0;
			try {
				await frappe.xcall("role_advisor.dashboard.delegate_toggle", { user, enabled });
				frappe.show_alert({
					message: enabled ? __("{0} enabled", [user]) : __("{0} disabled", [user]),
					indicator: enabled ? "green" : "orange",
				});
			} catch (error) {
				$input.prop("checked", !enabled);
				frappe.msgprint({ title: __("Refused"), message: esc(error.message), indicator: "red" });
			}
		});

		const rows = [
			[__("Tie-break rule"), policy.tie_break_rule],
			[__("Min peers for High confidence"), policy.min_peers_high_confidence],
			[__("Seed mode"), policy.seed_mode],
			[__("Scope dimensions"), policy.scope_dimensions.join(" → ")],
			[__("Module profile strategy"), policy.module_profile_strategy],
			[__("Naming pattern"), policy.naming_pattern],
			[__("Delegate role"), policy.delegate_role],
			[__("Multiple profiles per user"), policy.allow_multiple_profiles ? __("allowed") : __("one only")],
			[__("Employee link required"), policy.require_employee_link ? __("yes") : __("no")],
			[__("Privileged doctypes"), policy.privileged_doctypes.join(", ")],
		];
		this.$main.find(".ra-policy").html(
			`<dl class="ra-kv" style="grid-template-columns:250px 1fr">${rows
				.map(([label, value]) => `<dt>${label}</dt><dd>${esc(value)}</dd>`)
				.join("")}</dl>` +
				(sysadmin
					? `<div style="margin-top:18px;display:flex;gap:10px;align-items:center">
							<select class="ra-select ra-tiebreak">
								${["Tightest by permission count", "Majority peer vote", "Always flag"]
									.map(
										(option) =>
											`<option ${option === policy.tie_break_rule ? "selected" : ""}>${option}</option>`
									)
									.join("")}
							</select>
							<input class="ra-input ra-minpeers" type="number" min="1" max="50" style="min-width:120px"
								value="${policy.min_peers_high_confidence}">
							<button class="ra-btn ra-savepolicy">${__("Save policy")}</button>
					   </div>`
					: "")
		);

		this.$main.find(".ra-savepolicy").on("click", async (event) => {
			const $button = $(event.currentTarget).prop("disabled", true);
			try {
				await frappe.xcall("role_advisor.dashboard.settings_write", {
					values: {
						tie_break_rule: this.$main.find(".ra-tiebreak").val(),
						min_peers_high_confidence: cint(this.$main.find(".ra-minpeers").val()),
					},
				});
				frappe.show_alert({ message: __("Policy saved"), indicator: "green" });
				this.cache = {};
			} catch (error) {
				frappe.msgprint({ title: __("Refused"), message: esc(error.message), indicator: "red" });
			}
			$button.prop("disabled", false);
		});

		this.$main.find(".ra-newdelegate").on("click", () => this.new_delegate());
	}

	new_delegate() {
		const dialog = new frappe.ui.Dialog({
			title: __("Add a delegated administrator"),
			fields: [
				{
					fieldtype: "Link",
					options: "User",
					fieldname: "user",
					label: __("User"),
					reqd: 1,
					description: __("They will also be granted the delegate role, since the record alone grants nothing."),
				},
				{
					fieldtype: "MultiSelectList",
					fieldname: "companies",
					label: __("Companies they administer"),
					reqd: 1,
					get_data: (txt) =>
						frappe.db.get_link_options("Company", txt).then((options) => options),
				},
				{
					fieldtype: "MultiSelectList",
					fieldname: "profiles",
					label: __("Profiles they may grant"),
					description: __("Privileged profiles are refused even if listed here."),
					get_data: (txt) =>
						frappe.db.get_link_options("Role Profile", txt).then((options) => options),
				},
			],
			primary_action_label: __("Create"),
			primary_action: async (values) => {
				try {
					const result = await frappe.xcall("role_advisor.dashboard.delegate_save", {
						user: values.user,
						companies: (values.companies || []).map((c) => c.value || c),
						profiles: (values.profiles || []).map((p) => p.value || p),
						enabled: 1,
					});
					dialog.hide();
					frappe.show_alert({
						message: __("{0} is now a delegate, with the {1} role", [
							result.user,
							result.granted_role,
						]),
						indicator: "green",
					});
					this.cache = {};
					this.load();
				} catch (error) {
					frappe.msgprint({ title: __("Refused"), message: esc(error.message), indicator: "red" });
				}
			},
		});
		dialog.show();
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
			this.open_log($(event.currentTarget).data("log"));
		});
	}
}
