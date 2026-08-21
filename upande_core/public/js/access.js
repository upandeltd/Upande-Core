/* Copyright (c) 2026, Upande and contributors
 * For license information, please see license.txt
 *
 * IT Operations - the access half.
 *
 * This is Role Advisor's dashboard, moved from a desk page onto the portal. The
 * views are unchanged; what changed is the four things a desk page gave it for
 * free:
 *
 *   the page shell   frappe.ui.make_app_page is desk-only, so App() builds its
 *                    own root, topbar and sidebar into the element it is given.
 *   the user picker  frappe.ui.form.make_control is desk-only. Awesomplete is
 *                    not, and it is what that control uses underneath, so
 *                    picker() rebuilds the one control the views needed. The
 *                    server query is still the boundary: it only returns users
 *                    the caller may administer.
 *   routing          frappe.router is desk-only; the view lives in the hash.
 *   translation      __() and frappe.xcall are both on a website page already.
 *
 * The IT sections - helpdesk, workforce, assets, devices, biometric, system
 * health, activity, audit, errors, shifts, monitor config - are in itops.js,
 * which extends this class. Both are needed; neither works alone.
 */

(function () {
"use strict";


/* ------------------------------------------------------------------------- *
 * Scoped user picker
 *
 * Rebuilt on Awesomplete because the website bundle carries no form controls.
 * The security property is unchanged and lives on the server: `query` only
 * ever returns users the caller may administer, so the picker cannot offer
 * somebody the write would then refuse.
 * ------------------------------------------------------------------------- */
function picker(mount, { label, placeholder, query, onPick }) {
	const $wrap = $(`
		<div class="ra-pick">
			${label ? `<label>${esc(label)}</label>` : ""}
			<input type="search" class="ra-input" autocomplete="off" spellcheck="false"
				role="combobox" aria-expanded="false" aria-autocomplete="list"
				placeholder="${esc(placeholder || __("Search"))}">
			<ul class="ra-pick__list" role="listbox" hidden></ul>
		</div>`).appendTo(mount);

	const input = $wrap.find("input")[0];
	const $list = $wrap.find(".ra-pick__list");
	let chosen = null;
	let rows = [];
	let active = -1;
	let timer;

	const close = () => {
		$list.attr("hidden", true).empty();
		input.setAttribute("aria-expanded", "false");
		active = -1;
	};

	const announce = (value) => {
		if (value === chosen) return;
		chosen = value;
		onPick(value);
	};

	const choose = (index) => {
		const row = rows[index];
		if (!row) return;
		input.value = row.value;
		close();
		announce(row.value);
	};

	const draw = () => {
		if (!rows.length) return close();
		$list
			.html(
				rows
					.map(
						(row, index) => `
				<li role="option" data-i="${index}" class="${index === active ? "on" : ""}"
					aria-selected="${index === active}">
					<b>${esc(row.label)}</b><small>${esc(row.value)}</small>
				</li>`
					)
					.join("")
			)
			.removeAttr("hidden");
		input.setAttribute("aria-expanded", "true");
	};

	input.addEventListener("input", () => {
		clearTimeout(timer);
		const txt = input.value.trim();
		if (!txt) {
			rows = [];
			return close();
		}
		timer = setTimeout(async () => {
			try {
				const found = await frappe.xcall("frappe.desk.search.search_link", {
					doctype: "User",
					txt,
					// An empty query means the plain User search; the scoped views
					// pass `role_advisor.api.manageable_user_query` instead.
					...(query ? { query } : {}),
				});
				// The description carries the full name, so show that and submit
				// the login.
				rows = (found || []).map((row) => ({
					label: row.description || row.value,
					value: row.value,
				}));
			} catch (error) {
				// A refused search does not deserve a dialog; the empty list says it.
				rows = [];
			}
			active = -1;
			draw();
		}, 220);
	});

	input.addEventListener("keydown", (event) => {
		if ($list.attr("hidden")) return;
		if (event.key === "ArrowDown" || event.key === "ArrowUp") {
			event.preventDefault();
			active = Math.max(
				0,
				Math.min(rows.length - 1, active + (event.key === "ArrowDown" ? 1 : -1))
			);
			draw();
		} else if (event.key === "Enter") {
			event.preventDefault();
			choose(active >= 0 ? active : 0);
		} else if (event.key === "Escape") {
			close();
		}
	});

	$list.on("mousedown", "li", (event) => choose(cint($(event.currentTarget).data("i"))));
	// Typing a full login and leaving the field counts as choosing it.
	input.addEventListener("change", () => input.value && announce(input.value));
	$(document).on("click", (event) => {
		if (!$wrap[0].contains(event.target)) close();
	});

	return {
		get value() {
			return chosen || input.value || null;
		},
		set(value) {
			input.value = value || "";
			announce(value || null);
		},
	};
}

/* Two of the IT endpoints read `frappe.request.args` and refuse anything but
 * GET - shiftOverview answers a POST with "Method not allowed. Use GET." -
 * so they cannot go through frappe.xcall, which posts. */
async function getJSON(method, params) {
	const query = new URLSearchParams(params || {}).toString();
	const response = await fetch(
		`/api/method/${method}${query ? "?" + query : ""}`,
		{ headers: { Accept: "application/json" }, credentials: "same-origin" }
	);
	const body = await response.json();
	if (body.exc || body.exception) throw new Error(body.exception || __("Request failed"));
	return body.message;
}


/* Sidebar groups. itops.js pushes its own onto this, so the order here is the
   order on screen: the estate first, then access, then the IT sections. */
const GROUPS = [
	{
		label: "Overview",
		views: [
			{ id: "overview", label: "Overview", icon: "grid" },
			{ id: "anomalies", label: "Anomalies", icon: "alert" },
		],
	},
	{
		label: "Access",
		views: [
			{ id: "users", label: "Users", icon: "users", count: "enabled" },
			{ id: "profiles", label: "Role Profiles", icon: "layers", count: "profiles" },
			{ id: "modules", label: "Modules", icon: "box", count: "modules" },
			{ id: "request", label: "Request Access", icon: "search" },
			{ id: "queue", label: "Incoming Requests", icon: "inbox", count: "open_requests" },
			{ id: "assign", label: "Grant Access", icon: "check" },
			{ id: "map", label: "Designation Map", icon: "map", count: "map_rows" },
			{ id: "sweep", label: "Bulk Sweep", icon: "zap" },
		],
	},
	{
		label: "Governance",
		views: [
			{ id: "reports", label: "Reports", icon: "file" },
			{ id: "audit", label: "Assignment Log", icon: "clock", count: "assignments" },
			{ id: "admin", label: "Delegates & Policy", icon: "shield", count: "delegates" },
		],
	},
];

/* Flat view list, derived. Nothing should maintain this by hand. */
const VIEWS = [];
function indexViews() {
	VIEWS.length = 0;
	GROUPS.forEach((group) => group.views.forEach((view) => VIEWS.push(view)));
	return VIEWS;
}

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
	alert: '<path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/>',
	desk: '<rect x="2" y="3" width="20" height="14" rx="2"/><line x1="8" y1="21" x2="16" y2="21"/><line x1="12" y1="17" x2="12" y2="21"/>',
	out: '<path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><polyline points="16 17 21 12 16 7"/><line x1="21" y1="12" x2="9" y2="12"/>',
	sliders: '<line x1="4" y1="21" x2="4" y2="14"/><line x1="4" y1="10" x2="4" y2="3"/><line x1="12" y1="21" x2="12" y2="12"/><line x1="12" y1="8" x2="12" y2="3"/><line x1="20" y1="21" x2="20" y2="16"/><line x1="20" y1="12" x2="20" y2="3"/><line x1="1" y1="14" x2="7" y2="14"/><line x1="9" y1="8" x2="15" y2="8"/><line x1="17" y1="16" x2="23" y2="16"/>',
	headset: '<path d="M4 14v-2a8 8 0 0 1 16 0v2"/><path d="M4 14h2a1 1 0 0 1 1 1v4a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1z"/><path d="M20 14h-2a1 1 0 0 0-1 1v4a1 1 0 0 0 1 1h1a1 1 0 0 0 1-1z"/><path d="M17 20v1a2 2 0 0 1-2 2h-3"/>',
	server: '<rect x="2" y="3" width="20" height="7" rx="2"/><rect x="2" y="14" width="20" height="7" rx="2"/><line x1="6" y1="6.5" x2="6.01" y2="6.5"/><line x1="6" y1="17.5" x2="6.01" y2="17.5"/>',
	cpu: '<rect x="6" y="6" width="12" height="12" rx="2"/><path d="M10 2v3M14 2v3M10 19v3M14 19v3M2 10h3M2 14h3M19 10h3M19 14h3"/>',
	fingerprint: '<path d="M12 2a10 10 0 0 0-10 10"/><path d="M12 6a6 6 0 0 0-6 6v4"/><path d="M12 10a2 2 0 0 0-2 2v8"/><path d="M14 22v-8a2 2 0 0 0-.6-1.4"/><path d="M18 20v-8a6 6 0 0 0-3-5.2"/><path d="M22 14v-2a10 10 0 0 0-5-8.7"/>',
	pulse: '<path d="M22 12h-4l-3 8-4-16-3 8H2"/>',
	list: '<line x1="8" y1="6" x2="21" y2="6"/><line x1="8" y1="12" x2="21" y2="12"/><line x1="8" y1="18" x2="21" y2="18"/><line x1="3" y1="6" x2="3.01" y2="6"/><line x1="3" y1="12" x2="3.01" y2="12"/><line x1="3" y1="18" x2="3.01" y2="18"/>',
	bug: '<path d="M8 2l1.5 2.5M16 2l-1.5 2.5"/><rect x="7" y="6" width="10" height="12" rx="5"/><path d="M7 11H3M21 11h-4M7 15H4M20 15h-3M12 18v4"/>',
	hourglass: '<path d="M6 2h12M6 22h12"/><path d="M6 2v4a6 6 0 0 0 6 6 6 6 0 0 0-6 6v4"/><path d="M18 2v4a6 6 0 0 1-6 6 6 6 0 0 1 6 6v4"/>',
	cog: '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.9l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.9-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.9.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.9 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.9l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.9.3H10a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.9-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.9V10a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/>',
	refresh: '<polyline points="23 4 23 10 17 10"/><polyline points="1 20 1 14 7 14"/><path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"/>',
};

const esc = (value) => frappe.utils.escape_html(String(value == null ? "" : value));
const num = (value) => Number(value || 0).toLocaleString();
const cint = (value) => parseInt(value, 10) || 0;
// A bare count reads as "the 1 actions asked for". Agree the noun.
const plural = (n, one, many) => (Number(n) === 1 ? __(one) : __(many, [num(n)]));
const actions = (n) => plural(n, "1 action", "{0} actions");

class App {
	constructor(root) {
		indexViews();
		// The desk gave this a page object with a `main` jQuery handle; the
		// portal gives an element, so `main` is synthesised to keep every
		// `this.page.main.find(...)` in the views below working unchanged.
		this.root = root;
		this.page = { main: $(root) };
		this.view = (location.hash || "").replace(/^#\/?/, "") || "overview";
		this.cache = {};
		// Grant state survives a view switch so a half-built selection is not
		// lost by glancing at the anomalies list.
		this.grant = { user: null, needs: [], module: null, mode: "needs" };
		// The website template keeps a navbar, a footer and a 1290px cap. This
		// page is an application, so it takes the viewport - see the rules
		// scoped to body.ra-portal in access.css.
		document.body.classList.add("ra-portal");
		this.render_shell();
		this.watch_hash();
		this.load();
	}

	// ---------------------------------------------------------------- shell

	render_shell() {
		this.page.main.html(`
			<header class="ra-top">
				<a class="ra-brand" href="/apps" title="${__("All apps")}">
					<img src="/assets/role_advisor/images/role-advisor-logo.svg" alt="" width="34" height="34">
					<span>
						<b>${__("Role Advisor")}</b>
						<small>${__("IT Operations")}</small>
					</span>
				</a>
				<div class="ra-top__right">
					<button class="ra-topbtn ra-rescan" title="${__("Re-count everything")}">
						<svg viewBox="0 0 24 24">${ICONS.refresh}</svg>${__("Re-count")}
					</button>
					<a class="ra-topbtn" href="/desk" title="${__("Back to the desk")}">
						<svg viewBox="0 0 24 24">${ICONS.desk}</svg>${__("Desk")}
					</a>
					<div class="ra-whoami">
						<div class="ra-avatar">${esc((frappe.session.user_fullname || "?").slice(0, 2).toUpperCase())}</div>
						<span>${esc(frappe.session.user_fullname || frappe.session.user)}</span>
					</div>
				</div>
			</header>
			<div class="ra-page">
				<aside class="ra-side">
					<div>
						${GROUPS.map(
							(group) => `
							<div class="ra-side__label">${__(group.label)}</div>
							<nav class="ra-nav">
								${group.views
									.map(
										(view) => `
									<a data-view="${view.id}" class="${view.id === this.view ? "on" : ""}">
										<svg viewBox="0 0 24 24">${ICONS[view.icon] || ICONS.grid}</svg>
										${__(view.label)}
										${view.count ? `<span class="n" data-count="${view.count}">–</span>` : ""}
									</a>`
									)
									.join("")}
							</nav>`
						).join("")}
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
					<div>
						<div class="ra-side__label">${__("Elsewhere")}</div>
						<nav class="ra-nav">
							<a class="ra-todesk">
								<svg viewBox="0 0 24 24">${ICONS.out}</svg>
								${__("Frappe desk")}
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
		this.page.main.find(".ra-tomine").on("click", () => (window.location = "/my-access"));

		// Hiding the desk chrome removes the only way out, so the way out is
		// put back explicitly - in the sidebar and in the topbar.
		this.page.main.find(".ra-todesk").on("click", () => (window.location = "/app"));

		this.page.main.find(".ra-rescan").on("click", () => {
			this.cache = {};
			frappe.show_alert({ message: __("Re-counting from the database…"), indicator: "blue" });
			frappe
				.xcall("role_advisor.anomalies.overview", { force: 1 })
				.then(() => this.load());
		});
	}

	watch_hash() {
		window.addEventListener("hashchange", () => {
			const view = (location.hash || "").replace(/^#\/?/, "") || "overview";
			if (view !== this.view) this.go(view);
		});
	}

	go(view) {
		this.view = view;
		this.page.main.find(".ra-nav a").removeClass("on");
		this.page.main.find(`.ra-nav a[data-view="${view}"]`).addClass("on");
		// The hash is the route, so the back button and a shared link both work.
		if (location.hash.replace(/^#\/?/, "") !== view) location.hash = view;
		this.render();
		window.scrollTo({ top: 0 });
	}

	async load() {
		this.$main.html(`<div class="ra-empty"><span class="ra-spinner"></span> ${__("Counting…")}</div>`);
		try {
			this.summary = await frappe.xcall("role_advisor.dashboard.summary");
			// Presentation only; every write is re-checked on the server.
			this.is_sysmgr = !!this.summary.is_system_manager;
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

	/* One KPI tile. Same markup the overview emits inline, factored out so the
	   IT views in itops.js render identically rather than approximately. */
	kpi(label, value, unit, tone, note) {
		return `
			<div class="ra-kpi">
				<div class="ra-kpi__label">${label}</div>
				<div class="ra-kpi__value">${value}</div>
				<div class="ra-kpi__unit">${unit || ""}</div>
				${note ? `<div class="ra-tag ${tone || "flat"}">${note}</div>` : ""}
			</div>`;
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

	// ------------------------------------------------------------ anomalies

	async view_anomalies() {
		this.$main.html(`
			${this.head(
				__("Anomalies & Discrepancies"),
				__(
					"An anomaly is a grant that is wrong on its own terms. A discrepancy is a grant that disagrees with something else that is also true — the same job held differently, roles a profile does not account for, an account that contradicts policy."
				),
				`<div class="ra-pillgroup ra-anomfilter">
					<button data-filter="all" class="on">${__("Everything")}</button>
					<button data-filter="discrepancy">${__("Discrepancies")}</button>
					<button data-filter="high">${__("High only")}</button>
				</div>`
			)}
			<div class="ra-kpis ra-anomkpis"></div>
			<div class="ra-anomlist"><div class="ra-empty"><span class="ra-spinner"></span> ${__(
				"Reading every user, profile and permission row…"
			)}</div></div>
		`);

		let data;
		try {
			data = await this.fetch("anomalies", "role_advisor.anomalies.overview");
		} catch (error) {
			this.$main.find(".ra-anomlist").html(`<div class="ra-card"><div class="ra-empty">${esc(
				error.message
			)}</div></div>`);
			return;
		}

		const c = data.counts;
		this.$main.find(".ra-anomkpis").html(
			[
				{
					label: __("Discrepancies"),
					value: c.discrepancies,
					unit: __("a grant that contradicts another fact"),
					tag: c.discrepancies ? "bad" : "good",
					note: c.discrepancies ? __("start here") : __("nothing contradicts"),
				},
				{
					label: __("People affected"),
					value: c.people,
					unit: __("named in at least one discrepancy"),
					tag: c.people ? "warn" : "good",
					note: c.people ? __("each needs a decision") : __("nobody"),
				},
				{
					label: __("High severity"),
					value: c.high,
					unit: __("someone can do more than they should"),
					tag: c.high ? "bad" : "good",
					note: c.high ? __("act on these") : __("clear"),
				},
				{
					label: __("Everything else"),
					value: c.moderate + c.low,
					unit: __("{0} moderate · {1} low", [num(c.moderate), num(c.low)]),
					tag: "flat",
					note: __("tidy-up, not risk"),
				},
			]
				.map(
					(kpi) => `
				<div class="ra-kpi">
					<div class="ra-kpi__label">${kpi.label}</div>
					<div class="ra-kpi__value">${num(kpi.value)}</div>
					<div class="ra-kpi__unit">${kpi.unit}</div>
					<div class="ra-tag ${kpi.tag}">${kpi.note}</div>
				</div>`
				)
				.join("")
		);

		this.anomalies = data.anomalies;
		this.anom_filter = "all";
		this.render_anomalies();

		this.$main.find(".ra-anomfilter button").on("click", (event) => {
			const $button = $(event.currentTarget);
			this.$main.find(".ra-anomfilter button").removeClass("on");
			$button.addClass("on");
			this.anom_filter = $button.data("filter");
			this.render_anomalies();
		});

		// The sidebar badge is only known once the scan has run, so it is filled
		// here rather than being counted a second time in summary().
		this.page.main
			.find('.ra-nav a[data-view="anomalies"]')
			.append(`<span class="n">${num(data.anomalies.length)}</span>`)
			.find(".n:not(:last)")
			.remove();
	}

	render_anomalies() {
		const rows = (this.anomalies || []).filter((row) =>
			this.anom_filter === "discrepancy"
				? row.discrepancy
				: this.anom_filter === "high"
				? row.severity === "high"
				: true
		);

		if (!rows.length) {
			this.$main.find(".ra-anomlist").html(
				`<div class="ra-card"><div class="ra-empty">${__("Nothing in this category.")}</div></div>`
			);
			return;
		}

		this.$main.find(".ra-anomlist").html(
			rows
				.map(
					(row) => `
			<div class="ra-anom ${row.severity}">
				<div class="ra-anom__head">
					<div>
						<div class="ra-anom__title">
							${esc(row.title)}
							<span class="ra-badge ${row.discrepancy ? "disc" : "anom"}">${
								row.discrepancy ? __("discrepancy") : __("anomaly")
							}</span>
						</div>
						<p class="ra-anom__detail">${esc(row.detail)}</p>
					</div>
					<div class="ra-anom__count">${num(row.count)}<small>${__("affected")}</small></div>
				</div>
				<div class="ra-anom__rows">
					${row.rows
						.map(
							(entry) => `
						<div class="ra-anom__row${entry.users && entry.users.length === 1 ? " clickable" : ""}"
							${entry.users && entry.users.length === 1 ? `data-user="${esc(entry.users[0])}"` : ""}
							${entry.profile ? `data-profile="${esc(entry.profile)}"` : ""}>
							<b class="ra-ellipsis" title="${esc(entry.label)}">${esc(entry.label)}</b>
							<span class="ra-ellipsis" title="${esc(entry.meta || "")}">${esc(entry.meta || "")}</span>
							<i class="ra-ellipsis" title="${esc(entry.extra || "")}">${esc(entry.extra || "")}</i>
						</div>`
						)
						.join("")}
					${
						row.truncated
							? `<button class="ra-btn ghost sm ra-anommore" data-kind="${esc(row.kind)}">${__(
									"Show the other {0}",
									[num(row.truncated)]
							  )}</button>`
							: ""
					}
				</div>
				${row.fix ? `<div class="ra-anom__fix">${esc(row.fix)}</div>` : ""}
			</div>`
				)
				.join("")
		);

		this.$main.find(".ra-anom__row[data-user]").on("click", (event) =>
			this.open_user($(event.currentTarget).data("user"))
		);
		this.$main.find(".ra-anom__row[data-profile]:not([data-user])").on("click", (event) =>
			this.open_profile($(event.currentTarget).data("profile"))
		);
		this.$main.find(".ra-anommore").on("click", (event) => {
			event.stopPropagation();
			this.open_anomaly($(event.currentTarget).data("kind"));
		});
	}

	async open_anomaly(kind) {
		if (!kind) return;
		const { $drawer } = this.loading_drawer(__("Anomaly"));

		let d;
		try {
			d = await frappe.xcall("role_advisor.anomalies.detail", { kind });
		} catch (error) {
			$drawer.find(".ra-drawer__body").html(`<div class="ra-empty">${esc(error.message)}</div>`);
			return;
		}

		$drawer.find("h2").text(d.title);
		$drawer
			.find("small")
			.text(
				`${d.discrepancy ? __("discrepancy") : __("anomaly")} · ${__("{0} rows", [
					num(d.rows.length),
				])}`
			);
		$drawer.find(".ra-drawer__body").html(`
			<div class="ra-card ra-sect">
				<p class="ra-sub" style="margin:0">${esc(d.detail)}</p>
				${d.fix ? `<div class="ra-anom__fix" style="margin-top:14px">${esc(d.fix)}</div>` : ""}
			</div>
			<div class="ra-card ra-sect">
				<b>${__("Every row")}</b>
				<div class="ra-anom__rows" style="margin-top:12px">
					${d.rows
						.map(
							(entry) => `
						<div class="ra-anom__row${entry.users && entry.users.length === 1 ? " clickable" : ""}"
							${entry.users && entry.users.length === 1 ? `data-user="${esc(entry.users[0])}"` : ""}>
							<b class="ra-ellipsis" title="${esc(entry.label)}">${esc(entry.label)}</b>
							<span class="ra-ellipsis" title="${esc(entry.meta || "")}">${esc(entry.meta || "")}</span>
							<i class="ra-ellipsis" title="${esc(entry.extra || "")}">${esc(entry.extra || "")}</i>
						</div>`
						)
						.join("")}
				</div>
			</div>
		`);

		$drawer.find(".ra-anom__row[data-user]").on("click", (event) =>
			this.open_user($(event.currentTarget).data("user"))
		);
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
					<div class="ra-card__head">
						<h3>${__("Needs a decision")}</h3>
						<button class="ra-btn ghost sm" data-go="anomalies">${__("All anomalies")}</button>
					</div>
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
					<div class="ra-find ${find.severity} clickable" data-kind="${esc(find.kind)}">
						<i></i>
						<div>
							<b>${esc(find.title)}</b>
							${find.discrepancy ? `<span class="ra-badge disc">${__("discrepancy")}</span>` : ""}
							<p>${esc(find.detail)}</p>
						</div>
					</div>`
						)
						.join("")
				: `<div class="ra-empty">${__("Nothing outstanding.")}</div>`
		);
		this.$main.find(".ra-findings .ra-find").on("click", (event) =>
			this.open_anomaly($(event.currentTarget).data("kind"))
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

	// --------------------------------------------------------------- assign
	//
	// Frappe is role-based: a role carries permission rows, a permission row
	// grants rights on a doctype, and nothing else decides whether an action is
	// allowed. So the question this view asks is the one the model can actually
	// answer - which documents must this person work with, and what must they do
	// to them - and derives the profile from the answer.
	//
	// The alternative, asking an administrator to pick a profile out of ninety-
	// two by name, is how people end up holding Accounts because it was next to
	// Agriculture in the list.

	async view_assign() {
		this.grant = this.grant || { user: null, needs: [], module: null, mode: "needs" };

		this.$main.html(`
			${this.head(
				__("Grant Access"),
				__(
					"Name what the person has to be able to do. The profile that covers it — and nothing more than it — is worked out from the live permission rows."
				),
				`<div class="ra-pillgroup ra-grantmode">
					<button data-mode="needs" class="${this.grant.mode === "needs" ? "on" : ""}">${__(
						"By what they do"
					)}</button>
					<button data-mode="profile" class="${this.grant.mode === "profile" ? "on" : ""}">${__(
						"By profile"
					)}</button>
				</div>`
			)}
			<div class="ra-card">
				<div class="ra-card__head">
					<h3>${__("1 · Who")}</h3>
					<div class="ra-meta ra-scopenote"></div>
				</div>
				<div class="ra-whorow">
					<div class="ra-userpick"></div>
					<div class="ra-current"><div class="ra-meta">${__(
						"Pick someone to see what they can do today."
					)}</div></div>
				</div>
			</div>
			<div class="ra-grantbody"></div>
		`);

		this.$main.find(".ra-grantmode button").on("click", (event) => {
			this.grant.mode = $(event.currentTarget).data("mode");
			this.$main.find(".ra-grantmode button").removeClass("on");
			$(event.currentTarget).addClass("on");
			this.render_grant_body();
		});

		this.$main
			.find(".ra-scopenote")
			.text(
				this.summary.scoped
					? __("scoped to {0}", [this.summary.scope_companies.join(", ")])
					: __("every user on the site")
			);

		// Scoped server query, so the picker cannot suggest someone the caller
		// would then be refused for.
		this.user_field = picker(this.$main.find(".ra-userpick"), {
			label: __("User"),
			placeholder: __("Search by name or login"),
			query: "role_advisor.api.manageable_user_query",
			onPick: () => this.on_pick_user(),
		});

		this.render_grant_body();

		// Arrived here from a user drawer or an anomaly row: pre-select them.
		if (this.pending_user) {
			this.user_field.set(this.pending_user);
			this.pending_user = null;
		}
	}

	render_grant_body() {
		if (this.grant.mode === "profile") {
			this.render_profile_mode();
		} else {
			this.render_needs_mode();
		}
	}

	// ----------------------------------------------------- mode: what they do

	async render_needs_mode() {
		this.$main.find(".ra-grantbody").html(`
			<div class="ra-row2eq">
				<div class="ra-card">
					<div class="ra-card__head">
						<h3>${__("2 · What they must be able to do")}</h3>
						<div class="ra-meta">${__("module, then document, then action")}</div>
					</div>
					<div class="ra-modchips"><div class="ra-empty"><span class="ra-spinner"></span></div></div>
					<input class="ra-input ra-docfilter" type="search" style="width:100%;margin:14px 0 0"
						placeholder="${__("or search every document…")}">
					<div class="ra-doclist"><div class="ra-meta" style="padding:14px 2px">${__(
						"Choose a module above, or search."
					)}</div></div>
				</div>
				<div class="ra-card">
					<div class="ra-card__head">
						<h3>${__("Selected")}</h3>
						<button class="ra-btn ghost sm ra-clearneeds">${__("Clear")}</button>
					</div>
					<div class="ra-needlist"></div>
					<div class="ra-meta" style="margin-top:12px">${__(
						"Only actions some role on this site actually grants are offered — an ask nothing can satisfy is not worth making."
					)}</div>
				</div>
			</div>
			<div class="ra-card">
				<div class="ra-card__head">
					<h3>${__("3 · What that takes")}</h3>
					<div class="ra-meta">${__("resolved live · nothing is written until you say so")}</div>
				</div>
				<div class="ra-verdict"><div class="ra-empty">${__(
					"Pick a person and at least one action."
				)}</div></div>
			</div>
		`);

		this.render_needs();

		let modules;
		try {
			modules = await this.fetch("grant_modules", "role_advisor.grant.modules");
		} catch (error) {
			this.$main.find(".ra-modchips").html(`<div class="ra-empty">${esc(error.message)}</div>`);
			return;
		}

		this.$main.find(".ra-modchips").html(
			modules
				.map(
					(row) => `
			<button class="ra-chip ${row.module === this.grant.module ? "on" : ""}" data-module="${esc(row.module)}"
				title="${esc(row.module)} · ${num(row.doctypes)} ${__("grantable documents")}">
				${esc(row.module)}<span>${num(row.doctypes)}</span>
			</button>`
				)
				.join("")
		);

		this.$main.find(".ra-modchips .ra-chip").on("click", (event) => {
			const module = $(event.currentTarget).data("module");
			this.grant.module = this.grant.module === module ? null : module;
			this.$main.find(".ra-modchips .ra-chip").removeClass("on");
			if (this.grant.module) $(event.currentTarget).addClass("on");
			this.$main.find(".ra-docfilter").val("");
			this.load_documents();
		});

		let timer;
		this.$main.find(".ra-docfilter").on("input", (event) => {
			const txt = event.target.value.trim();
			clearTimeout(timer);
			timer = setTimeout(() => this.load_documents(txt), 220);
		});

		this.$main.find(".ra-clearneeds").on("click", () => {
			this.grant.needs = [];
			this.render_needs();
			this.resolve_grant();
		});

		if (this.grant.module) this.load_documents();
	}

	async load_documents(txt = "") {
		if (!this.grant.module && !txt) {
			this.$main.find(".ra-doclist").html(
				`<div class="ra-meta" style="padding:14px 2px">${__("Choose a module above, or search.")}</div>`
			);
			return;
		}

		this.$main.find(".ra-doclist").html(`<div class="ra-empty"><span class="ra-spinner"></span></div>`);

		let docs;
		try {
			docs = await frappe.xcall("role_advisor.grant.documents", {
				module: txt ? null : this.grant.module,
				txt,
				limit: 200,
			});
		} catch (error) {
			this.$main.find(".ra-doclist").html(`<div class="ra-empty">${esc(error.message)}</div>`);
			return;
		}

		if (!docs.length) {
			this.$main.find(".ra-doclist").html(
				`<div class="ra-empty">${__("No grantable document matches that.")}</div>`
			);
			return;
		}

		const has = (doctype, right) =>
			this.grant.needs.some((need) => need.doctype === doctype && need.right === right);

		this.$main.find(".ra-doclist").html(
			docs
				.map(
					(row) => `
			<div class="ra-docrow">
				<div class="ra-docrow__name">
					<b class="ra-ellipsis" title="${esc(row.doctype)}">${esc(row.doctype)}</b>
					<small>${esc(row.module)}${row.submittable ? ` · ${__("submittable")}` : ""}</small>
				</div>
				<div class="ra-rights">
					${row.rights
						.map(
							(right) => `
						<button class="ra-right ${has(row.doctype, right) ? "on" : ""}"
							data-doctype="${esc(row.doctype)}" data-right="${esc(right)}">${esc(right)}</button>`
						)
						.join("")}
				</div>
			</div>`
				)
				.join("")
		);

		this.$main.find(".ra-right").on("click", (event) => {
			const $button = $(event.currentTarget);
			this.toggle_need($button.data("doctype"), $button.data("right"));
			$button.toggleClass("on");
		});
	}

	toggle_need(doctype, right) {
		const at = this.grant.needs.findIndex(
			(need) => need.doctype === doctype && need.right === right
		);
		if (at >= 0) {
			this.grant.needs.splice(at, 1);
		} else {
			this.grant.needs.push({ doctype, right });
		}
		this.render_needs();
		this.resolve_grant();
	}

	render_needs() {
		const grouped = {};
		this.grant.needs.forEach((need) => {
			(grouped[need.doctype] = grouped[need.doctype] || []).push(need.right);
		});

		const doctypes = Object.keys(grouped).sort();
		this.$main.find(".ra-needlist").html(
			doctypes.length
				? doctypes
						.map(
							(doctype) => `
				<div class="ra-needrow">
					<b class="ra-ellipsis" title="${esc(doctype)}">${esc(doctype)}</b>
					<div class="ra-badges">
						${grouped[doctype]
							.map(
								(right) => `
							<span class="ra-badge gain ra-needdrop" data-doctype="${esc(doctype)}" data-right="${esc(
									right
								)}" title="${__("Remove")}">${esc(right)} ✕</span>`
							)
							.join("")}
					</div>
				</div>`
						)
						.join("")
				: `<div class="ra-empty">${__("Nothing selected yet.")}</div>`
		);

		this.$main.find(".ra-needdrop").on("click", (event) => {
			const $badge = $(event.currentTarget);
			this.toggle_need($badge.data("doctype"), $badge.data("right"));
			this.$main
				.find(`.ra-right[data-doctype="${$badge.data("doctype")}"][data-right="${$badge.data("right")}"]`)
				.removeClass("on");
		});
	}

	async resolve_grant() {
		const user = this.user_field && this.user_field.value;
		const $verdict = this.$main.find(".ra-verdict");

		if (!user || !this.grant.needs.length) {
			$verdict.html(`<div class="ra-empty">${__("Pick a person and at least one action.")}</div>`);
			return;
		}

		$verdict.html(
			`<div class="ra-empty"><span class="ra-spinner"></span> ${__("Checking every profile…")}</div>`
		);

		// Each keystroke-driven change fires this, so a slow answer for an old
		// selection must not overwrite a fast answer for the current one.
		const token = (this.grant.token = (this.grant.token || 0) + 1);

		let verdict;
		try {
			verdict = await frappe.xcall("role_advisor.grant.resolve", {
				user,
				needs: this.grant.needs,
			});
		} catch (error) {
			if (token !== this.grant.token) return;
			$verdict.html(`<div class="ra-empty">${esc(error.message)}</div>`);
			return;
		}
		if (token !== this.grant.token) return;

		this.grant.verdict = verdict;
		const tone =
			verdict.resolution === "Covered"
				? "good"
				: verdict.resolution === "Fit Found"
				? verdict.grantable
					? "warn"
					: "bad"
				: "bad";

		const over = verdict.over_grant || [];
		const asked = this.grant.needs.length;

		$verdict.html(`
			<div class="ra-verdicthead">
				<div>
					<div class="ra-eyebrow" style="margin:0 0 6px">${esc(verdict.resolution)}</div>
					<h2 class="ra-title" style="font-size:26px">${
						verdict.profile
							? esc(verdict.profile)
							: verdict.resolution === "Covered"
							? __("Already covered")
							: __("Nothing covers this")
					}</h2>
					<p class="ra-sub">${esc(verdict.notes || "")}</p>
				</div>
				<div class="ra-tag ${tone}">${__("{0} asked for", [actions(asked)])}</div>
			</div>
			${
				verdict.profile
					? `<div class="ra-tile__stats" style="grid-template-columns:repeat(4,1fr);margin:18px 0">
							<div><small>${__("Holds now")}</small><b style="font-size:14px">${esc(
								(verdict.holds || []).join(", ") || __("no profile")
							)}</b></div>
							<div><small>${__("Would hold")}</small><b style="font-size:14px">${esc(verdict.profile)}</b></div>
							<div><small>${__("Total grants")}</small><b style="font-size:14px">${num(
								verdict.grants
							)}</b></div>
							<div><small>${__("Beyond the ask")}</small><b style="font-size:14px">${num(
								over.length
							)} ${__("documents")}</b></div>
						</div>`
					: ""
			}
			${
				over.length
					? `<details class="ra-details"><summary>${__(
							"What else {0} would grant · {1} documents",
							[esc(verdict.profile), num(over.length)]
					  )}</summary><div class="ra-overlist">${over
							.map((line) => `<div class="ra-ellipsis" title="${esc(line)}">${esc(line)}</div>`)
							.join("")}</div></details>`
					: ""
			}
			${
				(verdict.unreachable || []).length
					? `<div class="ra-card ra-sect" style="background:rgba(196,48,43,0.05)">
							<b>${__("No role on this site grants these")}</b>
							<div class="ra-badges" style="margin-top:10px">${verdict.unreachable
								.map((line) => `<span class="ra-badge loss">${esc(line)}</span>`)
								.join("")}</div>
							<div class="ra-meta" style="margin-top:10px">${__(
								"A role has to be created or a permission row added before this can be granted to anyone."
							)}</div>
						</div>`
					: ""
			}
			${
				(verdict.suggested_roles || []).length
					? `<div class="ra-card ra-sect">
							<b>${__("A new profile from these roles would cover it")}</b>
							<div class="ra-badges" style="margin-top:10px">${verdict.suggested_roles
								.map((role) => `<span class="ra-badge gain">${esc(role)}</span>`)
								.join("")}</div>
						</div>`
					: ""
			}
			${
				verdict.blocked_reason
					? `<div class="ra-tag bad" style="margin-top:14px">${esc(verdict.blocked_reason)}</div>`
					: ""
			}
			<div class="ra-verdictactions">
				${
					verdict.profile && verdict.grantable
						? `<button class="ra-btn ra-dogrant">${__("Replace with {0}", [esc(verdict.profile)])}</button>`
						: ""
				}
				<button class="ra-btn ghost ra-doadd">${__("Add to what they have")}</button>
				${
					(verdict.grantable_alternatives || []).length > 1
						? `<button class="ra-btn ghost ra-altgrant">${__("Other profiles that cover it · {0}", [
								verdict.grantable_alternatives.length,
						  ])}</button>`
						: ""
				}
				${
					verdict.resolution !== "Covered"
						? `<button class="ra-btn ghost ra-asrequest">${__("Record as a request instead")}</button>`
						: ""
				}
			</div>
		`);

		$verdict.find(".ra-dogrant").on("click", () => this.do_grant(verdict.profile));
		$verdict.find(".ra-doadd").on("click", () => this.do_add());
		$verdict.find(".ra-altgrant").on("click", () => this.show_alternatives(verdict));
		$verdict.find(".ra-asrequest").on("click", () => this.record_grant_as_request(user));
	}

	show_alternatives(verdict) {
		const rows = verdict.grantable_alternatives || [];
		const { $drawer, close } = this.drawer(
			__("Profiles that cover this"),
			__("tightest first"),
			`<div class="ra-list">${rows
				.map(
					(profile, index) => `
				<div class="ra-lrow clickable" data-profile="${esc(profile)}">
					<div class="ra-rank ${index === 0 ? "lead" : ""}">${index + 1}</div>
					<div><div class="ra-name">${esc(profile)}</div>
					<div class="ra-lmeta">${profile === verdict.profile ? __("the tightest fit") : __("also covers it")}</div></div>
					<button class="ra-btn ghost sm">${__("Grant")}</button>
				</div>`
				)
				.join("")}</div>`
		);

		$drawer.find(".ra-lrow").on("click", (event) => {
			close();
			this.do_grant($(event.currentTarget).data("profile"));
		});
	}

	async do_grant(profile) {
		const user = this.user_field.value;
		if (!user || !profile) return;

		const asked = this.grant.needs
			.map((need) => `${need.doctype} · ${need.right}`)
			.join("<br>");

		frappe.confirm(
			__(
				"Assign <b>{0}</b> to <b>{1}</b>?<br><br>Assigning replaces the profile they hold — it does not add to it.<br><br><small>Asked for:<br>{2}</small>",
				[frappe.utils.escape_html(profile), frappe.utils.escape_html(user), asked]
			),
			async () => {
				const $button = this.$main.find(".ra-dogrant").prop("disabled", true);
				$button.html(`<span class="ra-spinner"></span> ${__("Assigning…")}`);

				try {
					const result = await frappe.xcall("role_advisor.grant.apply", {
						user,
						role_profile: profile,
						needs: this.grant.needs,
					});

					// "A profile was assigned" is not the outcome anyone wanted.
					// "They can now do the thing" is, so it is re-checked and said.
					if (result.covered) {
						frappe.msgprint({
							title: __("Granted"),
							indicator: "green",
							message: __(
								"{0} now holds {1} and can do every one of the {2} asked for.",
								[
									frappe.utils.escape_html(user),
									frappe.utils.escape_html(result.profiles.join(", ")),
									actions(this.grant.needs.length),
								]
							),
						});
					} else {
						frappe.msgprint({
							title: __("Granted, but not everything asked for"),
							indicator: "orange",
							message: __("Still not permitted: {0}", [
								frappe.utils.escape_html((result.still_missing || []).join(", ")),
							]),
						});
					}

					this.cache = {};
					this.summary = await frappe.xcall("role_advisor.dashboard.summary");
					// The grant moved the audit count and may have cleared an
					// anomaly; both are shown in the sidebar.
					this.page.main
						.find('.ra-nav a[data-view="audit"] .n')
						.text(num(this.summary.assignments));
					this.on_pick_user();
					this.resolve_grant();
				} catch (error) {
					frappe.msgprint({ title: __("Refused"), message: esc(error.message), indicator: "red" });
					$button.prop("disabled", false).text(__("Grant {0}", [profile]));
				}
			}
		);
	}

	// Assigning a profile replaces what someone holds. That is right when the
	// job changed and wrong when the job merely grew, so the additive path keeps
	// their roles and adds the smallest set that covers the new ask.
	async do_add() {
		const user = this.user_field && this.user_field.value;
		if (!user || !this.grant.needs.length) return;

		const { $drawer } = this.loading_drawer(__("Add to their access"));

		let plan;
		try {
			plan = await frappe.xcall("role_advisor.compose.preview", {
				user,
				requirements: this.grant.needs,
			});
		} catch (error) {
			$drawer.find(".ra-drawer__body").html(`<div class="ra-empty">${esc(error.message)}</div>`);
			return;
		}

		// When there is nothing to add, the answer is the reason and nothing
		// else. Showing a proposed name, an empty role list and three unchanged
		// counters reads as an offer, which is the opposite of what it is.
		if (!plan.allowed) {
			$drawer.find("h2").text(__("Nothing to add"));
			$drawer.find("small").text(esc(user));
			$drawer.find(".ra-drawer__body").html(`
				<div class="ra-card ra-sect">
					<p class="ra-sub" style="margin:0">${esc(plan.refusal)}</p>
				</div>
				${
					plan.holds.length
						? `<div class="ra-card ra-sect">
								<b>${__("Holds today")}</b>
								<div class="ra-badges" style="margin-top:10px">${plan.holds
									.map((p) => `<span class="ra-badge">${esc(p)}</span>`)
									.join("")}</div>
							</div>`
						: ""
				}
			`);
			return;
		}

		$drawer.find("h2").text(plan.name);
		$drawer
			.find("small")
			.text(
				plan.reuses
					? __("an existing profile already carries exactly this")
					: __("a new profile would be created")
			);

		const badges = (items, cls) =>
			items.length
				? items.map((item) => `<span class="ra-badge ${cls}">${esc(item)}</span>`).join("")
				: `<span class="ra-meta">${__("none")}</span>`;

		$drawer.find(".ra-drawer__body").html(`
			<div class="ra-card ra-sect">
				<div class="ra-tile__stats" style="grid-template-columns:repeat(3,1fr)">
					<div><small>${__("Roles")}</small><b style="font-size:14px">${num(
						plan.roles_before
					)} → ${num(plan.roles_after.length)}</b></div>
					<div><small>${__("Documents reachable")}</small><b style="font-size:14px">${num(
						plan.doctypes_before
					)} → ${num(plan.doctypes_after)}</b></div>
					<div><small>${__("Total grants")}</small><b style="font-size:14px">${num(
						plan.grants_before
					)} → ${num(plan.grants_after)}</b></div>
				</div>
				<div class="ra-tag good" style="margin-top:14px">${__(
					"Nothing they hold today is taken away"
				)}</div>
			</div>
			<div class="ra-card ra-sect">
				<b>${__("Roles added")} · ${plan.added_roles.length}</b>
				<div class="ra-badges" style="margin-top:10px">${badges(plan.added_roles, "gain")}</div>
				<div class="ra-meta" style="margin-top:12px">${__(
					"The smallest set that covers the ask — not another job's whole profile."
				)}</div>
			</div>
			<div class="ra-card ra-sect">
				<b>${__("Keeps")}</b>
				<div class="ra-badges" style="margin-top:10px">${badges(
					plan.holds,
					""
				)}</div>
			</div>
			${
				plan.privileged
					? `<div class="ra-card ra-sect" style="background:rgba(196,48,43,0.05)">
							<b>${__("This would let them change permissions")}</b>
							<p class="ra-sub" style="margin:8px 0 0">${esc(plan.privileged)}</p>
						</div>`
					: ""
			}
			<div class="ra-verdictactions">
				<button class="ra-btn ra-addgo">${
					plan.reuses ? __("Assign {0}", [esc(plan.reuses)]) : __("Create and assign")
				}</button>
			</div>
		`);

		$drawer.find(".ra-addgo").on("click", () => this.commit_add(plan, user));
	}

	async commit_add(plan, user) {
		const $button = this.$main.find(".ra-addgo").add($(".ra-addgo")).prop("disabled", true);
		$button.html(`<span class="ra-spinner"></span> ${__("Working…")}`);

		try {
			const result = await frappe.xcall("role_advisor.compose.apply", {
				user,
				requirements: this.grant.needs,
				// A privileged result is refused for a delegate outright; a System
				// Manager was shown it above and clicking is the confirmation.
				confirm_privileged: plan.privileged ? 1 : 0,
			});

			$(".ra-scrim, .ra-drawer").remove();
			frappe.msgprint({
				title: result.covered ? __("Added") : __("Added, but not everything asked for"),
				indicator: result.covered ? "green" : "orange",
				message: result.covered
					? __(
							"{0} now holds {1} — everything they had, plus the {2} asked for.",
							[
								frappe.utils.escape_html(user),
								frappe.utils.escape_html(result.composed),
								actions(this.grant.needs.length),
							]
					  )
					: __("Still not permitted: {0}", [
							frappe.utils.escape_html((result.still_missing || []).join(", ")),
					  ]),
			});

			this.cache = {};
			this.summary = await frappe.xcall("role_advisor.dashboard.summary");
			this.page.main
				.find('.ra-nav a[data-view="audit"] .n')
				.text(num(this.summary.assignments));
			this.on_pick_user();
			this.resolve_grant();
		} catch (error) {
			frappe.msgprint({ title: __("Refused"), message: esc(error.message), indicator: "red" });
			$button.prop("disabled", false).text(__("Create and assign"));
		}
	}

	async record_grant_as_request(user) {
		const dialog = new frappe.ui.Dialog({
			title: __("Record as a request"),
			fields: [
				{
					fieldtype: "Small Text",
					fieldname: "reason",
					label: __("Why is this needed?"),
					reqd: 1,
					description: __("Goes on the record with the resolution as it stands today."),
				},
			],
			primary_action_label: __("Record"),
			primary_action: async ({ reason }) => {
				dialog.hide();
				try {
					const out = await frappe.xcall("role_advisor.requests.submit_request", {
						user,
						requirements: this.grant.needs,
						reason,
					});
					frappe.show_alert({
						message: __("Recorded as {0}", [out.request]),
						indicator: "green",
					});
					this.cache = {};
				} catch (error) {
					frappe.msgprint({ title: __("Refused"), message: esc(error.message), indicator: "red" });
				}
			},
		});
		dialog.show();
	}

	// ------------------------------------------------------- mode: by profile

	async render_profile_mode() {
		this.$main.find(".ra-grantbody").html(`
			<div class="ra-card">
				<div class="ra-card__head">
					<h3>${__("2 · Which profile")}</h3>
					<div class="ra-meta">${__("least access first")}</div>
				</div>
				<div class="ra-grantable"><div class="ra-empty"><span class="ra-spinner"></span></div></div>
			</div>
			<div class="ra-card ra-previewcard" hidden>
				<div class="ra-card__head">
					<h3>${__("3 · Confirm")}</h3>
					<div class="ra-meta">${__("assigning replaces the current profile — it does not add to it")}</div>
				</div>
				<div class="ra-previewbody"></div>
			</div>
		`);

		let profiles;
		try {
			profiles = await this.fetch("grantable", "role_advisor.api.get_grantable_profiles");
		} catch (error) {
			this.$main.find(".ra-grantable").html(
				`<div class="ra-empty">${esc(
					error.message || __("You are not a delegated administrator.")
				)}</div>`
			);
			return;
		}

		this.$main.find(".ra-grantable").html(
			profiles.length
				? `<div class="ra-list">${profiles
						.map(
							(row, index) => `
					<div class="ra-lrow clickable" data-profile="${esc(row.role_profile)}">
						<div class="ra-rank ${index === 0 ? "lead" : ""}">${index + 1}</div>
						<div>
							<div class="ra-name">${esc(row.role_profile)}${
								row.privileged
									? ` <span class="ra-badge loss">${__("privileged")}</span>`
									: ""
							}</div>
							<div class="ra-lmeta">${num(row.doctype_count)} ${__("documents")} · ${num(
								row.perm_count
							)} ${__("grants")}</div>
						</div>
						<button class="ra-btn ghost sm">${__("Preview")}</button>
					</div>`
						)
						.join("")}</div>`
				: `<div class="ra-empty">${__("Your allowlist is empty.")}</div>`
		);

		this.$main.find(".ra-grantable .ra-lrow").on("click", (event) => {
			this.preview($(event.currentTarget).data("profile"));
		});
	}

	async on_pick_user() {
		const user = this.user_field.value;
		if (!user) return;
		this.grant.user = user;
		this.$main.find(".ra-previewcard").attr("hidden", true);

		this.$main
			.find(".ra-current")
			.html(`<div class="ra-empty"><span class="ra-spinner"></span></div>`);

		let cov;
		try {
			cov = await frappe.xcall("role_advisor.grant.coverage", { user });
		} catch (error) {
			this.$main.find(".ra-current").html(`<div class="ra-empty">${esc(error.message)}</div>`);
			return;
		}

		this.$main.find(".ra-current").html(`
			<div class="ra-tile__stats" style="grid-template-columns:repeat(4,1fr)">
				<div><small>${__("Holds now")}</small><b style="font-size:14px">${esc(
					cov.profiles.join(", ") || __("no profile")
				)}</b></div>
				<div><small>${__("Documents reachable")}</small><b style="font-size:14px">${num(
					cov.doctypes
				)}</b></div>
				<div><small>${__("Total grants")}</small><b style="font-size:14px">${num(cov.rights)}</b></div>
				<div><small>${__("Menu profile")}</small><b style="font-size:14px">${esc(
					cov.module_profile || __("none")
				)}</b></div>
			</div>
			${
				cov.modules.length
					? `<div class="ra-badges" style="margin-top:12px">${cov.modules
							.slice(0, 10)
							.map(
								(row) =>
									`<span class="ra-badge" title="${num(row.rights)} ${__("grants")}">${esc(
										row.module
									)} · ${num(row.doctypes)}</span>`
							)
							.join("")}${
							cov.modules.length > 10
								? `<span class="ra-badge">+${cov.modules.length - 10}</span>`
								: ""
					  }</div>`
					: `<div class="ra-tag bad" style="margin-top:12px">${__(
							"This account cannot reach a single document today."
					  )}</div>`
			}
		`);

		if (this.grant.mode === "needs") this.resolve_grant();
	}

	async preview(profile) {
		const user = this.user_field && this.user_field.value;
		if (!user) {
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
				user,
				role_profile: profile,
			});
		} catch (error) {
			this.$main.find(".ra-previewbody").html(`<div class="ra-empty">${esc(error.message)}</div>`);
			return;
		}

		this.grant.profile = profile;
		const badges = (items, cls) =>
			items.length
				? items.map((item) => `<span class="ra-badge ${cls}">${esc(item)}</span>`).join("")
				: `<span class="ra-meta">${__("none")}</span>`;

		this.$main.find(".ra-previewbody").html(`
			<div class="ra-tile__stats" style="grid-template-columns:repeat(3,1fr);margin-bottom:20px">
				<div><small>${__("User")}</small><b style="font-size:14px">${esc(user)}</b></div>
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
				user: this.user_field.value,
				role_profile: this.grant.profile,
			});
			frappe.show_alert({
				message: __("{0} now holds {1}", [
					this.user_field.value,
					result.profiles.join(", "),
				]),
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
			$button.prop("disabled", false).text(__("Assign {0}", [this.grant.profile]));
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

		// The scoped query when the caller is a delegate; otherwise they can
		// still type their own login, which the server allows.
		this.req_user = picker(this.$main.find(".ra-reqwho"), {
			label: __("User"),
			placeholder: __("Search by name or login"),
			query: "role_advisor.api.manageable_user_query",
			onPick: () => this.resolve_request(),
		});
		this.req_user.set(frappe.session.user);

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
		const user = this.req_user && this.req_user.value;
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
		const user = this.req_user.value;
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
		const editable = this.is_sysmgr;

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
		if (!this.is_sysmgr) {
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
		const sysadmin = this.is_sysmgr;
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


/* ------------------------------------------------------------------------- *
 * Exported surface. itops.js adds its groups and its `view_*` methods to this.
 * ------------------------------------------------------------------------- */
window.UpandeAccess = { App, GROUPS, ICONS, VIEWS, indexViews, picker, getJSON, esc, num, cint };
})();
