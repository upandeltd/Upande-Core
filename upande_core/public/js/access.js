/* Copyright (c) 2026, Upande and contributors
 * For license information, please see license.txt
 *
 * Access views for the IT dashboard.
 *
 * The IT dashboard used to manage users, roles, role profiles, workspace access
 * and doctype access itself, through `upande_core.api.it_dashboard`. Those are
 * replaced by the views registered here, which are bounded by company scope and
 * an allowlist, refuse to hand over anything that could change permissions, and
 * write an immutable log row for every change. The old endpoints were gated on
 * `System Manager` or `IT User Admin` and, past that gate, unbounded.
 *
 * The dashboard owns the page: its sidebar is the navigation, its `switchPanel`
 * shows and hides `section.panel`, and its `LOADERS` map decides what to fetch.
 * Every view here therefore does one thing - render into the `section.panel`
 * it is given - and registers a loader under the same name.
 *
 * On desk pages these views had `frappe.ui.form.make_control` for the scoped
 * user picker. The website bundle does not carry form controls, but it does
 * carry Awesomplete, which is what that control uses underneath, so `picker()`
 * below rebuilds the one control that was needed. Everything else the views
 * used - frappe.xcall, frappe.confirm, frappe.ui.Dialog, frappe.msgprint,
 * frappe.datetime, jQuery, __() - is present on a website page already.
 */

(function () {
	"use strict";

	const esc = (v) => frappe.utils.escape_html(String(v == null ? "" : v));
	const num = (v) => Number(v || 0).toLocaleString();

	/* ------------------------------------------------------------------ *
	 * Scoped user picker
	 *
	 * The server query is the security boundary: it only ever returns users
	 * the caller may administer, so the picker cannot suggest somebody the
	 * write would then refuse. Rebuilt on Awesomplete because the website
	 * bundle has no form controls.
	 * ------------------------------------------------------------------ */
	function picker(mount, { placeholder, query, onPick }) {
		const $wrap = $(`
			<div class="ra-picker">
				<input type="search" class="ra-input" autocomplete="off" spellcheck="false"
					placeholder="${esc(placeholder || __("Search"))}">
			</div>`).appendTo(mount);

		const input = $wrap.find("input")[0];
		const complete = new Awesomplete(input, {
			minChars: 1,
			maxItems: 12,
			autoFirst: false,
			// The label carries the full name; the value is the login we submit.
			data: (item) => item,
			replace: function (suggestion) {
				this.input.value = suggestion.value;
			},
		});

		let timer;
		let chosen = null;

		input.addEventListener("input", () => {
			clearTimeout(timer);
			const txt = input.value.trim();
			if (!txt) {
				complete.list = [];
				return;
			}
			timer = setTimeout(async () => {
				let rows = [];
				try {
					rows = await frappe.xcall("frappe.desk.search.search_link", {
						doctype: "User",
						txt,
						query,
					});
				} catch (error) {
					// A refused search is not worth a dialog; the empty list says it.
					rows = [];
				}
				complete.list = (rows || []).map((row) => ({
					label: row.description ? `${row.description} · ${row.value}` : row.value,
					value: row.value,
				}));
				complete.evaluate();
			}, 220);
		});

		input.addEventListener("awesomplete-selectcomplete", () => {
			chosen = input.value;
			onPick(chosen);
		});
		// Typing a full login and leaving the field counts as picking it.
		input.addEventListener("change", () => {
			if (input.value && input.value !== chosen) {
				chosen = input.value;
				onPick(chosen);
			}
		});

		return {
			get value() {
				return chosen || input.value || null;
			},
			set(value) {
				input.value = value || "";
				chosen = value || null;
				if (chosen) onPick(chosen);
			},
		};
	}

	/* ------------------------------------------------------------------ *
	 * Anomalies
	 * ------------------------------------------------------------------ */
	async function renderAnomalies($panel) {
		const $body = $panel.find(".ra-mount");
		$body.html(
			`<div class="ra-empty"><span class="ra-spinner"></span> ${__(
				"Reading every user, profile and permission row…"
			)}</div>`
		);

		let data;
		try {
			data = await frappe.xcall("role_advisor.anomalies.overview");
		} catch (error) {
			$body.html(`<div class="ra-card"><div class="ra-empty">${esc(error.message)}</div></div>`);
			return;
		}

		const c = data.counts;
		const kpis = [
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
		];

		$body.html(`
			<div class="ra-kpis">
				${kpis
					.map(
						(k) => `
					<div class="ra-kpi">
						<div class="ra-kpi__label">${k.label}</div>
						<div class="ra-kpi__value">${num(k.value)}</div>
						<div class="ra-kpi__unit">${k.unit}</div>
						<div class="ra-tag ${k.tag}">${k.note}</div>
					</div>`
					)
					.join("")}
			</div>
			<div class="ra-pillgroup ra-anomfilter" style="margin-bottom:18px">
				<button data-filter="all" class="on">${__("Everything")}</button>
				<button data-filter="discrepancy">${__("Discrepancies")}</button>
				<button data-filter="high">${__("High only")}</button>
			</div>
			<div class="ra-anomlist"></div>
		`);

		const draw = (filter) => {
			const rows = data.anomalies.filter((row) =>
				filter === "discrepancy"
					? row.discrepancy
					: filter === "high"
					? row.severity === "high"
					: true
			);

			$body.find(".ra-anomlist").html(
				rows.length
					? rows
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
							<div class="ra-anom__row">
								<b class="ra-ellipsis" title="${esc(entry.label)}">${esc(entry.label)}</b>
								<span class="ra-ellipsis" title="${esc(entry.meta || "")}">${esc(entry.meta || "")}</span>
								<i class="ra-ellipsis" title="${esc(entry.extra || "")}">${esc(entry.extra || "")}</i>
							</div>`
							)
							.join("")}
						${
							row.truncated
								? `<div class="ra-meta" style="padding:6px 8px">${__(
										"and {0} more",
										[num(row.truncated)]
								  )}</div>`
								: ""
						}
					</div>
					${row.fix ? `<div class="ra-anom__fix">${esc(row.fix)}</div>` : ""}
				</div>`
							)
							.join("")
					: `<div class="ra-card"><div class="ra-empty">${__(
							"Nothing in this category."
					  )}</div></div>`
			);
		};

		draw("all");
		$body.find(".ra-anomfilter button").on("click", function () {
			$body.find(".ra-anomfilter button").removeClass("on");
			$(this).addClass("on");
			draw($(this).data("filter"));
		});
	}

	/* ------------------------------------------------------------------ *
	 * Registry
	 *
	 * The dashboard calls LOADERS[panel]. Each view is registered under the
	 * same name as its `data-panel`, so adding a view is: markup, nav item,
	 * one entry here.
	 * ------------------------------------------------------------------ */
	const VIEWS = {
		"ra-anomalies": renderAnomalies,
	};

	window.UpandeAccess = {
		picker,
		esc,
		num,
		views: VIEWS,
		load(panel) {
			const render = VIEWS[panel];
			if (!render) return;
			const $panel = $(`section.panel[data-panel="${panel}"]`);
			if (!$panel.length) return;
			return render($panel);
		},
	};
})();
