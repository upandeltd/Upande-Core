// Copyright (c) 2026, ghost-mann and contributors
// For license information, please see license.txt

/* My Access — self-service.
 *
 * Available to any desk user. Every server call it makes is about the caller
 * and takes no user argument, so there is nothing here to point at somebody
 * else. Nobody has to know the permission model: they name the documents they
 * need and the app works out the rest.
 */

frappe.pages["my-access"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("My Access"),
		single_column: true,
	});
	page.main.addClass("ra-self");
	new MyAccess(page);
};

frappe.pages["my-access"].on_page_show = function () {
	standalone(true);
};

/* Both Role Advisor pages wear the app's own chrome rather than the desk's -
 * see the same function in access_dashboard.js. The class has to come off again
 * on the way out, or every other desk page is served with no sidebar.
 */
const RA_ROUTES = ["access-dashboard", "my-access"];
let watching_route = false;

function standalone(on) {
	$("body").toggleClass("ra-standalone", !!on);

	if (!on || watching_route) return;
	watching_route = true;
	frappe.router.on("change", () => {
		const route = frappe.get_route() || [];
		$("body").toggleClass("ra-standalone", RA_ROUTES.includes(route[0]));
	});
}

const sesc = (value) => frappe.utils.escape_html(String(value == null ? "" : value));
const snum = (value) => Number(value || 0).toLocaleString();

class MyAccess {
	constructor(page) {
		this.page = page;
		this.basket = [];
		this.render();
		this.load();
	}

	render() {
		this.page.main.html(`
			<header class="ra-top">
				<a class="ra-brand" href="/desk/my-access" title="${__("My Access")}">
					<img src="/assets/role_advisor/images/role-advisor-logo.svg" alt="" width="34" height="34">
					<span>
						<b>${__("Role Advisor")}</b>
						<small>${__("your access")}</small>
					</span>
				</a>
				<div class="ra-top__right">
					<a class="ra-topbtn" href="/desk">${__("Desk")}</a>
					<div class="ra-whoami">
						<div class="ra-avatar">${sesc(
							(frappe.session.user_fullname || "?").slice(0, 2).toUpperCase()
						)}</div>
						<span>${sesc(frappe.session.user_fullname || frappe.session.user)}</span>
					</div>
				</div>
			</header>
			<div class="ra-self__page">
				<div class="ra-self__head">
					<div class="ra-self__eyebrow">${__("Role Advisor")}</div>
					<h1 class="ra-self__title">${__("My Access")}</h1>
					<p class="ra-self__sub">${__(
						"What you can do today, and how to ask for something you cannot."
					)}</p>
				</div>
				<div class="ra-adminslot"></div>
				<div class="card ra-current">
					<div class="empty"><span class="spin"></span></div>
				</div>
				<div class="card">
					<h3>${__("Need to do something you cannot?")}</h3>
					<div class="hint">${__(
						"Name the documents you need to work with. You do not need to know which access level that is — we work it out."
					)}</div>
					<input class="input ra-search" type="search"
						placeholder="${__("Leave Application, Purchase Order, Harvest…")}">
					<div class="results" hidden></div>
					<div class="basket ra-basket"></div>
					<div class="ra-verdict"></div>
				</div>
				<div class="card">
					<h3>${__("My requests")}</h3>
					<div class="hint">${__("Everything you have asked for, and where it got to.")}</div>
					<div class="ra-requests"><div class="empty"><span class="spin"></span></div></div>
				</div>
			</div>
		`);

		let timer;
		this.page.main.find(".ra-search").on("input", (event) => {
			clearTimeout(timer);
			const txt = $(event.currentTarget).val();
			timer = setTimeout(() => this.search(txt), 180);
		});
	}

	async load() {
		const [me, requests] = await Promise.all([
			frappe.xcall("role_advisor.requests.my_access"),
			frappe.xcall("role_advisor.requests.my_requests", { limit: 15 }),
		]);
		this.me = me;

		const e = me.employee || {};
		this.page.main.find(".ra-current").html(`
			<h3>${__("What you can do today")}</h3>
			<div class="hint">${
				me.profiles.length
					? __("Your access level is {0}.", [`<b>${sesc(me.profiles.join(", "))}</b>`])
					: me.unrestricted
					? __(
							"You hold <b>System Manager</b>, so nothing restricts you. The counts below only describe what a role profile would grant — you have none, and do not need one."
					  )
					: __("You have no access level set — which is why you may be unable to do very much.")
			}</div>
			<div class="stats">
				<div><small>${__("Documents")}</small><b>${snum(me.doctypes)}</b></div>
				<div><small>${__("Roles")}</small><b>${snum(me.roles)}</b></div>
				<div><small>${__("Company")}</small><b style="font-size:15px">${sesc(e.company || "—")}</b></div>
				<div><small>${__("Job title")}</small><b style="font-size:15px">${sesc(e.designation || "—")}</b></div>
			</div>
			${
				me.areas.length
					? `<div style="margin-top:20px">
							<div class="hint" style="margin-bottom:8px">${__("Areas you can reach")}</div>
							<div class="badges">${me.areas
								.map(
									(area) =>
										`<span class="badge">${sesc(area.module)} · ${area.doctypes}</span>`
								)
								.join("")}</div>
					   </div>`
					: ""
			}
		`);

		// Only offer the full dashboard to someone who can actually open it.
		if (me.is_administrator) {
			this.page.main.find(".ra-adminslot").html(`
				<div class="adminlink">
					<div>
						<b>${__("You administer access for others")}</b>
						<small>${__(
							"Assign profiles, review the designation map, run reports and read the audit trail."
						)}</small>
					</div>
					<button class="ra-goadmin">${__("Open Role Advisor")}</button>
				</div>
			`);
			this.page.main.find(".ra-goadmin").on("click", () => {
				frappe.set_route("access-dashboard");
			});
		}

		this.draw_requests(requests);
		this.draw_basket();
	}

	draw_requests(rows) {
		this.page.main.find(".ra-requests").html(
			rows.length
				? rows
						.map((row) => {
							const tone =
								row.status === "Fulfilled"
									? "done"
									: row.status === "Refused"
									? "no"
									: "open";
							const lines = (row.reason || "").trim();
							return `
					<div class="row">
						<span class="chip ${tone}">${sesc(row.status)}</span>
						<div>
							<b>${sesc(row.name)}</b>
							<small>${
								row.assigned_profile
									? __("granted {0}", [sesc(row.assigned_profile)])
									: row.recommended_profile
									? __("recommended {0} — waiting for an administrator", [
											sesc(row.recommended_profile),
									  ])
									: sesc(row.resolution || __("being looked at"))
							}${lines ? ` · ${sesc(lines)}` : ""}</small>
						</div>
						<small style="color:#8a8780">${frappe.datetime.comment_when(row.creation)}</small>
					</div>`;
						})
						.join("")
				: `<div class="empty">${__("You have not asked for anything yet.")}</div>`
		);
	}

	async search(txt) {
		const $results = this.page.main.find(".results");
		if (!txt || txt.length < 2) {
			$results.attr("hidden", true);
			return;
		}

		const [docs, bundles] = await Promise.all([
			frappe.xcall("role_advisor.requests.search_documents", { txt, limit: 15 }),
			frappe.xcall("role_advisor.requests.search_bundles", { txt, limit: 4 }),
		]);

		$results.removeAttr("hidden").html(
			[
				...bundles.map(
					(bundle) =>
						`<div class="result" data-bundle="${sesc(bundle.name)}">
							<div><b>${sesc(bundle.transaction_name)}</b><small>${bundle.requirements
							.map((r) => sesc(r.document_type))
							.join(", ")}</small></div>
							<span class="chip">${__("bundle")}</span>
						</div>`
				),
				...docs.map(
					(doc) =>
						`<div class="result" data-doctype="${sesc(doc.name)}">
							<div><b>${sesc(doc.name)}</b><small>${sesc(doc.module)}</small></div>
							${doc.is_submittable ? `<span class="chip">${__("submittable")}</span>` : "<span></span>"}
						</div>`
				),
			].join("") || `<div class="empty">${__("Nothing matches.")}</div>`
		);

		$results.find("[data-doctype]").on("click", (event) =>
			this.add($(event.currentTarget).data("doctype"))
		);
		$results.find("[data-bundle]").on("click", (event) =>
			this.add_bundle($(event.currentTarget).data("bundle"))
		);
	}

	async add(doctype) {
		if (this.basket.some((row) => row.doctype === doctype)) {
			frappe.show_alert({ message: __("{0} is already listed.", [doctype]), indicator: "orange" });
			return;
		}
		const rights = await frappe.xcall("role_advisor.requests.rights_for", { doctype });
		this.basket.push({ doctype, rights, chosen: ["read"] });
		this.reset_search();
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
		this.reset_search();
	}

	reset_search() {
		this.page.main.find(".ra-search").val("");
		this.page.main.find(".results").attr("hidden", true);
		this.draw_basket();
		this.check();
	}

	draw_basket() {
		const $basket = this.page.main.find(".ra-basket");
		if (!this.basket.length) {
			$basket.html("");
			this.page.main.find(".ra-verdict").html("");
			return;
		}

		$basket.html(
			this.basket
				.map(
					(row, index) => `
			<div class="brow" data-i="${index}">
				<div><b>${sesc(row.doctype)}</b>${
						row.bundle ? `<small>${__("from")} ${sesc(row.bundle)}</small>` : ""
					}</div>
				<div class="rights">${row.rights
					.map(
						(right) =>
							`<button class="right ${
								row.chosen.includes(right) ? "on" : ""
							}" data-right="${sesc(right)}">${sesc(right)}</button>`
					)
					.join("")}</div>
				<button class="drop" title="${__("Remove")}">✕</button>
			</div>`
				)
				.join("")
		);

		$basket.find(".right").on("click", (event) => {
			const $button = $(event.currentTarget);
			const index = $button.closest(".brow").data("i");
			const right = $button.data("right");
			const row = this.basket[index];
			row.chosen = row.chosen.includes(right)
				? row.chosen.filter((r) => r !== right)
				: [...row.chosen, right];
			if (!row.chosen.length) this.basket.splice(index, 1);
			this.draw_basket();
			this.check();
		});

		$basket.find(".drop").on("click", (event) => {
			this.basket.splice($(event.currentTarget).closest(".brow").data("i"), 1);
			this.draw_basket();
			this.check();
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

	async check() {
		const $verdict = this.page.main.find(".ra-verdict");
		const requirements = this.requirements();
		if (!requirements.length) {
			$verdict.html("");
			return;
		}

		$verdict.html(`<div class="empty"><span class="spin"></span> ${__("Checking…")}</div>`);

		let v;
		try {
			v = await frappe.xcall("role_advisor.requests.check_for_me", { requirements });
		} catch (error) {
			$verdict.html(`<div class="empty">${sesc(error.message)}</div>`);
			return;
		}

		const covered = v.resolution === "Covered";
		const tone = covered ? "covered" : v.resolution === "Fit Found" ? "fit" : "gap";

		// A requester is told what they would gain, not what a profile
		// over-grants: the over-grant matters to whoever approves, not to them.
		$verdict.html(`
			<div class="verdict ${tone}">
				<h4>${
					covered
						? __("You can already do this")
						: v.resolution === "Fit Found"
						? __("This can be granted")
						: __("This needs setting up first")
				}</h4>
				<p>${
					covered
						? __("Nothing to ask for — your current access already covers it.")
						: v.resolution === "Fit Found"
						? __(
								"An administrator can grant this. Send the request and they will see exactly what it involves."
						  )
						: v.resolution === "Gap - New Role Needed"
						? __(
								"Nobody on this system can do this yet, so it has to be set up before it can be granted. Sending the request tells an administrator."
						  )
						: __(
								"The pieces exist but no single access level covers them, so one has to be built. Sending the request tells an administrator."
						  )
				}</p>
			</div>
			${
				covered
					? ""
					: `<div style="margin-top:16px;display:flex;gap:10px;align-items:center;flex-wrap:wrap">
							<input class="input ra-reason" style="flex:1;min-width:230px"
								placeholder="${__("Why do you need this? (helps whoever reviews it)")}">
							<button class="btn ra-send">${__("Send request")}</button>
					   </div>`
			}
		`);

		$verdict.find(".ra-send").on("click", () => this.send());
	}

	async send() {
		const $button = this.page.main.find(".ra-send").prop("disabled", true);
		$button.html(`<span class="spin"></span> ${__("Sending…")}`);

		try {
			const result = await frappe.xcall("role_advisor.requests.request_for_me", {
				requirements: this.requirements(),
				reason: this.page.main.find(".ra-reason").val() || "",
			});
			frappe.show_alert({
				message: __("{0} sent — an administrator will review it.", [result.request]),
				indicator: "green",
			});
			this.basket = [];
			this.draw_basket();
			this.draw_requests(
				await frappe.xcall("role_advisor.requests.my_requests", { limit: 15 })
			);
		} catch (error) {
			frappe.msgprint({ title: __("Could not send"), message: sesc(error.message), indicator: "red" });
			$button.prop("disabled", false).text(__("Send request"));
		}
	}
}
