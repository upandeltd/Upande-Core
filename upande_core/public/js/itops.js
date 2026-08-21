/* Copyright (c) 2026, Upande and contributors
 * For license information, please see license.txt
 *
 * IT Operations - the operations half.
 *
 * The eleven sections that used to live in /it-dashboard's own panels and in
 * three separate portal pages (/it-operations, /it-workforce,
 * /it-operations-admin), rebuilt as views on the access dashboard so there is
 * one page, one sidebar and one design.
 *
 * Every endpoint and every field name below was read off the live site rather
 * than inferred from the old markup - `shiftOverview` and `auditTrail` in
 * particular read `frappe.request.args` directly and cannot be called in
 * process, so their shapes were confirmed over HTTP.
 *
 * No charts. The old page drew Chart.js donuts and bars; these use the same
 * CSS-only heat bars and tiles as the rest of the dashboard, so there is no
 * third-party script on the page and nothing to fail to load.
 */

(function () {
	"use strict";

	const { App, GROUPS, ICONS, indexViews, picker, getJSON, esc, num, cint } = window.UpandeAccess;

	/* --------------------------------------------------------------------- *
	 * Sidebar
	 * --------------------------------------------------------------------- */
	GROUPS.push(
		{
			label: "Support",
			views: [{ id: "helpdesk", label: "Helpdesk", icon: "headset", count: "open_issues" }],
		},
		{
			label: "People",
			views: [
				{ id: "workforce", label: "Workforce", icon: "users" },
				{ id: "shifts", label: "Shifts", icon: "hourglass" },
				{ id: "biometric", label: "Biometric Status", icon: "fingerprint" },
			],
		},
		{
			label: "Infrastructure",
			views: [
				{ id: "assets", label: "Assets", icon: "server" },
				{ id: "devices", label: "Devices", icon: "cpu" },
			],
		},
		{
			label: "Monitoring",
			views: [
				{ id: "health", label: "System Health", icon: "pulse" },
				{ id: "activity", label: "System Activity", icon: "zap" },
				{ id: "activitylog", label: "Activity Log", icon: "list" },
				{ id: "errors", label: "Error Messages", icon: "bug" },
			],
		},
		{
			label: "Configuration",
			views: [{ id: "monitor", label: "Monitor Config", icon: "cog" }],
		}
	);
	indexViews();

	/* --------------------------------------------------------------------- *
	 * Helpers
	 * --------------------------------------------------------------------- */
	const UC = "upande_core.api.";

	/** A tile row: label, value, optional note. Used by most of these views. */
	function stats(rows, columns) {
		return `<div class="ra-tile__stats" style="grid-template-columns:repeat(${
			columns || Math.min(rows.length, 4)
		},1fr)">${rows
			.map(
				(row) =>
					`<div><small>${esc(row[0])}</small><b style="font-size:${
						row[2] ? "14px" : "20px"
					}">${row[1]}</b>${row[2] ? `<small>${esc(row[2])}</small>` : ""}</div>`
			)
			.join("")}</div>`;
	}

	/** A table. `cols` is [[header, key, align?], …]; rows are plain objects. */
	function table(cols, rows, empty) {
		if (!rows || !rows.length) {
			return `<div class="ra-empty">${esc(empty || __("Nothing to show."))}</div>`;
		}
		return `
			<table class="ra-table">
				<thead><tr>${cols
					.map((c) => `<th${c[2] === "r" ? ' style="text-align:right"' : ""}>${esc(c[0])}</th>`)
					.join("")}</tr></thead>
				<tbody>${rows
					.map(
						(row) =>
							`<tr>${cols
								.map((c) => {
									const raw = typeof c[1] === "function" ? c[1](row) : row[c[1]];
									const val = raw == null || raw === "" ? "—" : raw;
									return `<td${c[2] === "r" ? ' style="text-align:right"' : ""}>${
										typeof c[1] === "function" ? val : esc(val)
									}</td>`;
								})
								.join("")}</tr>`
					)
					.join("")}</tbody>
			</table>`;
	}

	/** A CSS-only horizontal bar chart. No chart library, by design. */
	function bars(rows, { label, value, tone }) {
		const peak = Math.max(...rows.map((r) => Number(r[value]) || 0), 1);
		return `<div class="ra-bars">${rows
			.map((row) => {
				const n = Number(row[value]) || 0;
				return `
				<div class="ra-bar">
					<div class="ra-bar__name ra-ellipsis" title="${esc(row[label])}">${esc(row[label])}</div>
					<div class="ra-bar__lane"><div class="ra-bar__fill ${
						tone ? tone(row) : ""
					}" style="width:${(n / peak) * 100}%"></div></div>
					<div class="ra-bar__val">${num(n)}</div>
				</div>`;
			})
			.join("")}</div>`;
	}

	/** Twenty-four hour columns. Two series overlaid: today over yesterday. */
	function hours(today, yesterday) {
		const peak = Math.max(...today, ...yesterday, 1);
		return `<div class="ra-hours">${today
			.map(
				(n, h) => `
			<div class="ra-hour" title="${h}:00 — ${num(n)} ${__("today")}, ${num(
					yesterday[h] || 0
				)} ${__("yesterday")}">
				<div class="ra-hour__stack">
					<div class="ra-hour__prev" style="height:${((yesterday[h] || 0) / peak) * 100}%"></div>
					<div class="ra-hour__now" style="height:${(n / peak) * 100}%"></div>
				</div>
				<small>${h % 3 === 0 ? h : ""}</small>
			</div>`
			)
			.join("")}</div>`;
	}

	const ago = (value) =>
		value ? `${frappe.datetime.comment_when(value, true)}` : __("never");

	/* --------------------------------------------------------------------- *
	 * Support · Helpdesk
	 * --------------------------------------------------------------------- */
	App.prototype.view_helpdesk = async function () {
		this.$main.html(
			this.head(__("Helpdesk"), __("Open IT tickets, who they are with, and how long they have waited")) +
				`<div class="ra-mount"><div class="ra-empty"><span class="ra-spinner"></span></div></div>`
		);

		let rows;
		try {
			rows = await frappe.xcall("frappe.client.get_list", {
				doctype: "Issue",
				filters: { status: ["not in", ["Closed", "Resolved"]] },
				fields: [
					"name",
					"subject",
					"status",
					"priority",
					"issue_type",
					"raised_by",
					"opening_date",
					"first_responded_on",
					"company",
					"_assign",
				],
				limit_page_length: 500,
				order_by: "opening_date asc",
			});
		} catch (error) {
			this.$main.find(".ra-mount").html(`<div class="ra-card"><div class="ra-empty">${esc(error.message)}</div></div>`);
			return;
		}

		const owner = (row) => {
			try {
				return (JSON.parse(row._assign || "[]")[0] || "").trim();
			} catch (e) {
				return "";
			}
		};
		const unassigned = rows.filter((row) => !owner(row));
		const urgent = rows.filter((row) => ["High", "Urgent"].includes(row.priority));
		const unanswered = rows.filter((row) => !row.first_responded_on);

		const byType = {};
		rows.forEach((row) => {
			const key = row.issue_type || __("unclassified");
			byType[key] = (byType[key] || 0) + 1;
		});

		this.$main.find(".ra-mount").html(`
			<div class="ra-kpis">
				${this.kpi(__("Open"), num(rows.length), __("not closed or resolved"), rows.length ? "warn" : "good", __("live count"))}
				${this.kpi(__("High or urgent"), num(urgent.length), __("of the open tickets"), urgent.length ? "bad" : "good", urgent.length ? __("look first") : __("clear"))}
				${this.kpi(__("Never answered"), num(unanswered.length), __("no first response recorded"), unanswered.length ? "bad" : "good", unanswered.length ? __("nobody has replied") : __("all answered"))}
				${this.kpi(__("Nobody assigned"), num(unassigned.length), __("no owner on the ticket"), unassigned.length ? "warn" : "good", unassigned.length ? __("needs an owner") : __("all owned"))}
			</div>
			<div class="ra-row2">
				<div class="ra-card">
					<div class="ra-card__head"><h3>${__("By type")}</h3><div class="ra-meta">${__("open only")}</div></div>
					${bars(
						Object.keys(byType)
							.map((k) => ({ type: k, n: byType[k] }))
							.sort((a, b) => b.n - a.n),
						{ label: "type", value: "n" }
					)}
				</div>
				<div class="ra-card">
					<div class="ra-card__head"><h3>${__("Waiting longest")}</h3><div class="ra-meta">${__("oldest first")}</div></div>
					${table(
						[
							[__("Ticket"), (row) => `<b>${esc(row.name)}</b><br><small>${esc(row.subject || "")}</small>`],
							[__("Opened"), (row) => esc(ago(row.opening_date))],
							[__("Priority"), "priority"],
							[__("With"), (row) => esc(owner(row) || __("nobody"))],
						],
						rows.slice(0, 12),
						__("No open tickets.")
					)}
				</div>
			</div>
		`);
	};

	/* --------------------------------------------------------------------- *
	 * People · Workforce
	 * --------------------------------------------------------------------- */
	App.prototype.view_workforce = async function () {
		this.$main.html(
			this.head(
				__("Workforce & Access"),
				__(
					"Employee records against login accounts. An account that outlives the job is the one that gets used by somebody else."
				)
			) + `<div class="ra-mount"><div class="ra-empty"><span class="ra-spinner"></span></div></div>`
		);

		let d;
		try {
			d = await frappe.xcall(UC + "it_workforce.get_reconciliation");
		} catch (error) {
			this.$main.find(".ra-mount").html(`<div class="ra-card"><div class="ra-empty">${esc(error.message)}</div></div>`);
			return;
		}

		const t = d.totals || {};
		this.$main.find(".ra-mount").html(`
			<div class="ra-kpis">
				${this.kpi(__("Employees"), num(t.employees), __("{0} active · {1} not", [num(t.active_employees), num(t.inactive_employees)]), "flat", __("from Employee"))}
				${this.kpi(__("Enabled accounts"), num(t.enabled_accounts), __("can log in today"), "flat", __("from User"))}
				${this.kpi(__("Still enabled, no longer employed"), num(t.risk_count), __("account outlived the job"), t.risk_count ? "bad" : "good", t.risk_count ? __("disable these") : __("clear"))}
				${this.kpi(__("No employee record"), num(t.orphan_count), __("nothing links them to a person"), t.orphan_count ? "warn" : "good", __("service accounts live here too"))}
			</div>
			<div class="ra-card">
				<div class="ra-card__head">
					<h3>${__("Still enabled, no longer employed")}</h3>
					<div class="ra-meta">${__("the list worth acting on")}</div>
				</div>
				${table(
					[
						[__("Person"), (row) => `<b>${esc(row.employee_name || row.employee)}</b>`],
						[__("Login"), "user"],
						[__("Status"), "status"],
						[__("Department"), "department"],
					],
					d.risk,
					__("Every enabled account belongs to an active employee.")
				)}
			</div>
			<div class="ra-row2">
				<div class="ra-card">
					<div class="ra-card__head"><h3>${__("By employment status")}</h3></div>
					${bars(d.by_status || [], { label: "status", value: "count" })}
				</div>
				<div class="ra-card">
					<div class="ra-card__head">
						<h3>${__("Accounts with no employee")}</h3>
						<div class="ra-meta">${__("{0} in total", [num(t.orphan_count)])}</div>
					</div>
					${table(
						[
							[__("Login"), "user"],
							[__("Name"), "full_name"],
							[__("Last login"), (row) => esc(row.last_login ? ago(row.last_login) : __("never"))],
						],
						(d.orphan || []).slice(0, 12),
						__("Every account is linked to an employee.")
					)}
				</div>
			</div>
			${
				(d.blocked || []).length
					? `<div class="ra-card">
							<div class="ra-card__head"><h3>${__("Blocked")}</h3><div class="ra-meta">${__(
							"{0} accounts",
							[num(t.blocked_count)]
					  )}</div></div>
							${table(
								[
									[__("Person"), (row) => `<b>${esc(row.employee_name || row.employee)}</b>`],
									[__("Login"), "user"],
									[__("Department"), "department"],
								],
								d.blocked
							)}
						</div>`
					: ""
			}
		`);
	};

	/* --------------------------------------------------------------------- *
	 * People · Shifts
	 * --------------------------------------------------------------------- */
	App.prototype.view_shifts = async function () {
		this.$main.html(
			this.head(__("Shifts"), __("Shift assignment and whether attendance is still syncing for each one")) +
				`<div class="ra-mount"><div class="ra-empty"><span class="ra-spinner"></span></div></div>`
		);

		let out;
		try {
			out = await getJSON(UC + "it_dashboard.shiftOverview");
		} catch (error) {
			this.$main.find(".ra-mount").html(`<div class="ra-card"><div class="ra-empty">${esc(error.message)}</div></div>`);
			return;
		}
		const d = (out && out.data) || {};
		const t = d.totals || {};

		this.$main.find(".ra-mount").html(`
			<div class="ra-kpis">
				${this.kpi(__("Active employees"), num(t.active_employees), __("eligible for a shift"), "flat", "")}
				${this.kpi(__("Assigned"), num(t.assigned), __("hold a shift assignment"), "good", __("{0}% of active", [Math.round(((t.assigned || 0) / (t.active_employees || 1)) * 100)]))}
				${this.kpi(__("Unassigned"), num(t.unassigned), __("no shift assignment"), t.unassigned ? "warn" : "good", t.unassigned ? __("no attendance for these") : __("all assigned"))}
				${this.kpi(__("Attendance stopped"), num(t.attendance_stopped), __("assigned but not syncing"), t.attendance_stopped ? "bad" : "good", t.attendance_stopped ? __("check the sync") : __("all syncing"))}
			</div>
			<div class="ra-card">
				<div class="ra-card__head">
					<h3>${__("Shifts")}</h3>
					<div class="ra-meta">${__("{0} defined", [num((d.shifts || []).length)])}</div>
				</div>
				${table(
					[
						[__("Shift"), (row) => `<b>${esc(row.shift)}</b>`],
						[__("Window"), (row) => esc(`${row.start_time || "—"} → ${row.end_time || "—"}`)],
						[__("Auto"), (row) => (cint(row.auto) ? __("yes") : __("no"))],
						[__("Last sync"), (row) => esc(ago(row.last_sync))],
						[__("Employees"), "employees", "r"],
					],
					d.shifts,
					__("No shift types defined.")
				)}
			</div>
			<div class="ra-row2">
				<div class="ra-card">
					<div class="ra-card__head"><h3>${__("Companies")}</h3></div>
					<div class="ra-badges">${(d.companies || [])
						.map((c) => `<span class="ra-badge">${esc(c)}</span>`)
						.join("")}</div>
				</div>
				<div class="ra-card">
					<div class="ra-card__head"><h3>${__("Farms")}</h3></div>
					<div class="ra-badges">${(d.farms || [])
						.map((f) => `<span class="ra-badge">${esc(f)}</span>`)
						.join("")}</div>
				</div>
			</div>
		`);
	};

	/* --------------------------------------------------------------------- *
	 * People · Biometric status
	 * --------------------------------------------------------------------- */
	App.prototype.view_biometric = async function () {
		this.$main.html(
			this.head(
				__("Biometric Status"),
				__("Whether each shift is still turning clock-ins into attendance. A shift that stopped syncing loses the day silently.")
			) + `<div class="ra-mount"><div class="ra-empty"><span class="ra-spinner"></span></div></div>`
		);

		let out;
		try {
			out = await getJSON(UC + "it_dashboard.shiftOverview");
		} catch (error) {
			this.$main.find(".ra-mount").html(`<div class="ra-card"><div class="ra-empty">${esc(error.message)}</div></div>`);
			return;
		}
		const d = (out && out.data) || {};
		const shifts = d.shifts || [];
		const stale = shifts.filter((s) => !s.last_sync);

		this.$main.find(".ra-mount").html(`
			<div class="ra-kpis">
				${this.kpi(__("Shifts syncing"), num(shifts.length - stale.length), __("have synced at least once"), "good", "")}
				${this.kpi(__("Never synced"), num(stale.length), __("no sync recorded at all"), stale.length ? "bad" : "good", stale.length ? __("attendance is not being written") : __("clear"))}
				${this.kpi(__("Attendance stopped"), num((d.totals || {}).attendance_stopped), __("assigned but not syncing"), "warn", "")}
			</div>
			<div class="ra-card">
				<div class="ra-card__head">
					<h3>${__("Sync by shift")}</h3>
					<div class="ra-meta">${__("least recent first")}</div>
				</div>
				${table(
					[
						[__("Shift"), (row) => `<b>${esc(row.shift)}</b>`],
						[__("Last sync"), (row) => esc(ago(row.last_sync))],
						[
							__("State"),
							(row) =>
								row.last_sync
									? `<span class="ra-badge gain">${__("syncing")}</span>`
									: `<span class="ra-badge loss">${__("never synced")}</span>`,
						],
						[__("Auto"), (row) => (cint(row.auto) ? __("yes") : __("no"))],
					],
					shifts.slice().sort((a, b) => String(a.last_sync || "").localeCompare(String(b.last_sync || ""))),
					__("No shifts to report.")
				)}
			</div>
		`);
	};

	/* --------------------------------------------------------------------- *
	 * Infrastructure · Assets
	 * --------------------------------------------------------------------- */
	App.prototype.view_assets = async function () {
		this.$main.html(
			this.head(__("Assets"), __("What the company owns, where it is, and who is holding it")) +
				`<div class="ra-mount"><div class="ra-empty"><span class="ra-spinner"></span></div></div>`
		);

		let rows;
		try {
			rows = await frappe.xcall("frappe.client.get_list", {
				doctype: "Asset",
				fields: ["name", "asset_name", "asset_category", "status", "custodian", "location", "company"],
				limit_page_length: 2000,
				order_by: "asset_category asc",
			});
		} catch (error) {
			this.$main.find(".ra-mount").html(`<div class="ra-card"><div class="ra-empty">${esc(error.message)}</div></div>`);
			return;
		}

		const tally = (key) => {
			const out = {};
			rows.forEach((row) => {
				const k = row[key] || __("unrecorded");
				out[k] = (out[k] || 0) + 1;
			});
			return Object.keys(out)
				.map((k) => ({ key: k, n: out[k] }))
				.sort((a, b) => b.n - a.n);
		};
		const nocustodian = rows.filter((row) => !row.custodian);

		this.$main.find(".ra-mount").html(`
			<div class="ra-kpis">
				${this.kpi(__("Assets"), num(rows.length), __("on the register"), "flat", "")}
				${this.kpi(__("Categories"), num(tally("asset_category").length), __("distinct"), "flat", "")}
				${this.kpi(__("No custodian"), num(nocustodian.length), __("nobody is accountable"), nocustodian.length ? "warn" : "good", nocustodian.length ? __("assign a holder") : __("all held"))}
				${this.kpi(__("Locations"), num(tally("location").length), __("distinct"), "flat", "")}
			</div>
			<div class="ra-row2">
				<div class="ra-card">
					<div class="ra-card__head"><h3>${__("By category")}</h3></div>
					${bars(tally("asset_category").slice(0, 12), { label: "key", value: "n" })}
				</div>
				<div class="ra-card">
					<div class="ra-card__head"><h3>${__("By status")}</h3></div>
					${bars(tally("status"), { label: "key", value: "n" })}
				</div>
			</div>
			<div class="ra-card">
				<div class="ra-card__head">
					<h3>${__("No custodian")}</h3>
					<div class="ra-meta">${__("{0} assets", [num(nocustodian.length)])}</div>
				</div>
				${table(
					[
						[__("Asset"), (row) => `<b>${esc(row.asset_name || row.name)}</b>`],
						[__("Category"), "asset_category"],
						[__("Location"), "location"],
						[__("Company"), "company"],
					],
					nocustodian.slice(0, 15),
					__("Every asset has a custodian.")
				)}
			</div>
		`);
	};

	/* --------------------------------------------------------------------- *
	 * Infrastructure · Devices
	 * --------------------------------------------------------------------- */
	App.prototype.view_devices = async function () {
		this.$main.html(
			this.head(__("Devices"), __("Handhelds reporting in, and what they are running")) +
				`<div class="ra-mount"><div class="ra-empty"><span class="ra-spinner"></span></div></div>`
		);

		let out;
		try {
			out = await frappe.xcall(UC + "it_dashboard.getDeviceTelemetry");
		} catch (error) {
			this.$main.find(".ra-mount").html(`<div class="ra-card"><div class="ra-empty">${esc(error.message)}</div></div>`);
			return;
		}
		const devices = (out && out.devices) || [];

		const tally = (key) => {
			const acc = {};
			devices.forEach((d) => {
				const k = d[key] || __("unknown");
				acc[k] = (acc[k] || 0) + 1;
			});
			return Object.keys(acc)
				.map((k) => ({ key: k, n: acc[k] }))
				.sort((a, b) => b.n - a.n);
		};

		this.$main.find(".ra-mount").html(`
			<div class="ra-kpis">
				${this.kpi(__("Devices"), num(out.count != null ? out.count : devices.length), __("have reported in"), "flat", "")}
				${this.kpi(__("Models"), num(tally("model").length), __("distinct"), "flat", "")}
				${this.kpi(__("OS versions"), num(tally("os_version").length), __("distinct"), tally("os_version").length > 3 ? "warn" : "good", tally("os_version").length > 3 ? __("a spread to keep patched") : __("consistent"))}
			</div>
			<div class="ra-row2">
				<div class="ra-card">
					<div class="ra-card__head"><h3>${__("By model")}</h3></div>
					${bars(tally("model"), { label: "key", value: "n" })}
				</div>
				<div class="ra-card">
					<div class="ra-card__head"><h3>${__("By OS version")}</h3></div>
					${bars(tally("os_version"), { label: "key", value: "n" })}
				</div>
			</div>
			<div class="ra-card">
				<div class="ra-card__head"><h3>${__("Every device")}</h3></div>
				${table(
					[
						[__("Device"), (row) => `<b>${esc(row.device_name || row.device_id)}</b>`],
						[__("Brand"), "brand"],
						[__("Model"), "model"],
						[__("OS"), (row) => esc(`${row.os || "—"} ${row.os_version || ""}`.trim())],
						[__("App"), "app_name"],
					],
					devices,
					__("No devices have reported in.")
				)}
			</div>
		`);
	};

	/* --------------------------------------------------------------------- *
	 * Monitoring · System health
	 * --------------------------------------------------------------------- */
	App.prototype.view_health = async function () {
		this.$main.html(
			this.head(__("System Health"), __("Scheduler, queues, storage and what is failing right now")) +
				`<div class="ra-mount"><div class="ra-empty"><span class="ra-spinner"></span></div></div>`
		);

		let d;
		try {
			d = await frappe.xcall(UC + "it_dashboard.getSystemHealth");
		} catch (error) {
			this.$main.find(".ra-mount").html(`<div class="ra-card"><div class="ra-empty">${esc(error.message)}</div></div>`);
			return;
		}

		const pending = (d.queues || []).reduce((n, q) => n + (Number(q.pending) || 0), 0);
		const scheduler = String(d.scheduler_status || "").toLowerCase() === "active";

		this.$main.find(".ra-mount").html(`
			<div class="ra-kpis">
				${this.kpi(__("Scheduler"), esc(d.scheduler_status || "—"), __("background work runs from here"), scheduler ? "good" : "bad", scheduler ? __("running") : __("nothing scheduled is running"))}
				${this.kpi(__("Queued jobs"), num(pending), __("waiting across all queues"), pending > 100 ? "bad" : pending ? "warn" : "good", pending > 100 ? __("backing up") : __("moving"))}
				${this.kpi(__("Failing jobs"), num(d.failing_jobs), __("scheduled jobs erroring"), d.failing_jobs ? "bad" : "good", d.failing_jobs ? __("look at these") : __("none failing"))}
				${this.kpi(__("Errors logged"), num(d.total_errors), __("in the error log"), d.total_errors > 1000 ? "bad" : "warn", __("see Error Messages"))}
			</div>
			<div class="ra-row2">
				<div class="ra-card">
					<div class="ra-card__head"><h3>${__("Queues")}</h3><div class="ra-meta">${__("{0} workers", [num(d.background_workers)])}</div></div>
					${bars(d.queues || [], {
						label: "queue",
						value: "pending",
						tone: (row) => (Number(row.pending) > 20 ? "lo" : "hi"),
					})}
				</div>
				<div class="ra-card">
					<div class="ra-card__head"><h3>${__("Most frequent errors")}</h3><div class="ra-meta">${__("by occurrence")}</div></div>
					${bars((d.top_errors || []).slice(0, 8), { label: "title", value: "occurrences" })}
				</div>
			</div>
			<div class="ra-row2">
				<div class="ra-card">
					<div class="ra-card__head"><h3>${__("Storage")}</h3></div>
					${stats(
						[
							[__("Database"), `${num(d.db_storage_mb)} MB`],
							[__("Private files"), `${num(d.private_files_mb)} MB`],
							[__("Public files"), `${num(d.public_files_mb)} MB`],
							[__("Backups"), `${num(d.backups_size_mb)} MB`],
						],
						4
					)}
					${stats(
						[
							[__("On-site backups"), num(d.onsite_backups)],
							[__("Cache"), esc(d.cache_memory || "—")],
							[__("Engine"), esc(String(d.database_version || "—").split(" from ")[0])],
							[__("Realtime"), esc(d.socketio || "—")],
						],
						4
					)}
				</div>
				<div class="ra-card">
					<div class="ra-card__head"><h3>${__("People and mail")}</h3></div>
					${stats(
						[
							[__("Users"), num(d.total_users)],
							[__("New this week"), num(d.new_users)],
							[__("Active sessions"), num(d.active_sessions)],
							[__("Failed logins"), num(d.failed_logins)],
						],
						4
					)}
					${stats(
						[
							[__("Email pending"), num(d.pending_emails)],
							[__("Email failed"), num(d.failed_emails)],
						],
						2
					)}
				</div>
			</div>
			${
				(d.failing_jobs_list || []).length
					? `<div class="ra-card">
							<div class="ra-card__head"><h3>${__("Failing scheduled jobs")}</h3></div>
							${table(
								[
									[__("Job"), (row) => `<b>${esc(row.job)}</b>`],
									[__("Detail"), "details"],
								],
								d.failing_jobs_list
							)}
						</div>`
					: ""
			}
		`);
	};

	/* --------------------------------------------------------------------- *
	 * Monitoring · System activity
	 * --------------------------------------------------------------------- */
	App.prototype.view_activity = async function () {
		this.$main.html(
			this.head(__("System Activity"), __("What was created and changed today, against yesterday and the weekly average")) +
				`<div class="ra-mount"><div class="ra-empty"><span class="ra-spinner"></span></div></div>`
		);

		let d;
		try {
			d = await frappe.xcall(UC + "it_operations.getItOperationsData");
		} catch (error) {
			this.$main.find(".ra-mount").html(`<div class="ra-card"><div class="ra-empty">${esc(error.message)}</div></div>`);
			return;
		}

		const t = d.totals || {};
		const up = (n) => (Number(n) >= 0 ? "good" : "bad");

		this.$main.find(".ra-mount").html(`
			<div class="ra-kpis">
				${this.kpi(__("Today"), num(t.today), __("documents touched"), "flat", esc(d.today || ""))}
				${this.kpi(__("Yesterday"), num(t.yesterday), __("same measure"), "flat", __("{0}% vs today", [num(t.pct_vs_yesterday)]))}
				${this.kpi(__("By this time yesterday"), num(t.yesterday_sametime), __("like for like"), up(t.pct_vs_sametime), __("{0}%", [num(t.pct_vs_sametime)]))}
				${this.kpi(__("Seven-day average"), num(t.avg7), __("baseline"), up(t.pct_vs_avg), __("{0}% vs average", [num(t.pct_vs_avg)]))}
			</div>
			<div class="ra-card">
				<div class="ra-card__head">
					<h3>${__("Activity by hour")}</h3>
					<div class="ra-meta">${__("solid is today · faint is yesterday · generated {0}", [
						esc(String(d.generated_at || "").slice(11, 16)),
					])}</div>
				</div>
				${hours(d.hourly_today || [], d.hourly_yesterday || [])}
			</div>
			<div class="ra-row2">
				<div class="ra-card">
					<div class="ra-card__head"><h3>${__("By category")}</h3><div class="ra-meta">${__("today")}</div></div>
					${bars((d.by_category || []).slice().sort((a, b) => b.today - a.today), {
						label: "category",
						value: "today",
					})}
				</div>
				<div class="ra-card">
					<div class="ra-card__head"><h3>${__("Busiest people")}</h3><div class="ra-meta">${__("today")}</div></div>
					${table(
						[
							[__("Who"), (row) => `<b>${esc(row.full_name || row.user || row.owner || "—")}</b>`],
							[__("Documents"), (row) => num(row.count || row.n || row.today || 0), "r"],
						],
						(d.top_users || []).slice(0, 12),
						__("Nothing recorded today.")
					)}
				</div>
			</div>
			${
				(d.items || []).length
					? `<div class="ra-card">
							<div class="ra-card__head"><h3>${__("Monitored documents")}</h3><div class="ra-meta">${__(
							"as configured in Monitor Config"
					  )}</div></div>
							${table(
								[
									[__("What"), (row) => `<b>${esc(row.label || row.document_type)}</b>`],
									[__("Category"), "category"],
									[__("Today"), (row) => num(row.today || row.count || 0), "r"],
								],
								d.items
							)}
						</div>`
					: ""
			}
		`);
	};

	/* --------------------------------------------------------------------- *
	 * Monitoring · Activity log
	 *
	 * The old page called this Audit Trail. Role Advisor already has an Audit
	 * Trail - the assignment log - so this one is named for what it holds.
	 * --------------------------------------------------------------------- */
	App.prototype.view_activitylog = async function () {
		const today = frappe.datetime.get_today();
		const weekAgo = frappe.datetime.add_days(today, -7);

		this.$main.html(
			this.head(
				__("Activity Log"),
				__("Logins and document changes, one person at a time. The change log holds 14.7 million rows, so it is read per person rather than in bulk."),
				`<div class="ra-pillgroup ra-alrange">
					<button data-days="1" class="on">${__("Today")}</button>
					<button data-days="7">${__("7 days")}</button>
					<button data-days="30">${__("30 days")}</button>
				</div>`
			) +
				`<div class="ra-card">
					<div class="ra-card__head"><h3>${__("Whose activity?")}</h3><div class="ra-meta">${__(
					"leave blank for everyone"
				)}</div></div>
					<div class="ra-alwho"></div>
				</div>
				<div class="ra-mount"></div>`
		);

		this.al = this.al || { user: "", days: 1 };

		const run = async () => {
			const $mount = this.$main.find(".ra-mount");

			// `auditTrail` reads tabVersion, which on this site is 10.4GB across
			// 14.7M rows. Asking it for every user over seven days does not come
			// back. So a person is required before anything is queried - which is
			// also how the page this replaced worked, for the same reason.
			if (!this.al.user) {
				$mount.html(`
					<div class="ra-card">
						<div class="ra-empty">${__(
							"Choose a person above. The change log is far too large to read for everybody at once."
						)}</div>
					</div>`);
				return;
			}

			$mount.html(`<div class="ra-empty"><span class="ra-spinner"></span> ${__(
				"Reading the change log…"
			)}</div>`);
			const end = frappe.datetime.get_today();
			const start = frappe.datetime.add_days(end, -this.al.days);

			let out;
			try {
				out = await getJSON(UC + "it_dashboard.auditTrail", {
					user: this.al.user,
					start_date: start,
					end_date: end,
					page: 1,
				});
			} catch (error) {
				$mount.html(`<div class="ra-card"><div class="ra-empty">${esc(error.message)}</div></div>`);
				return;
			}

			const d = (out && out.data) || {};
			const logins = d.activity_log || { count: 0, records: [] };
			const changes = d.version_log || { count: 0, records: [] };

			$mount.html(`
				<div class="ra-kpis">
					${this.kpi(__("Logins"), num(logins.count), __("in the window"), "flat", "")}
					${this.kpi(__("Document changes"), num(changes.count), __("in the window"), "flat", changes.has_more ? __("more than shown") : __("complete"))}
					${this.kpi(__("Window"), __("{0} days", [this.al.days]), __("{0} → {1}", [start, end]), "flat", esc(this.al.user))}
				</div>
				<div class="ra-row2">
					<div class="ra-card">
						<div class="ra-card__head"><h3>${__("Logins")}</h3></div>
						${table(
							[
								[__("Who"), (row) => `<b>${esc(row.full_name || row.user || row.owner || "—")}</b>`],
								[__("When"), (row) => esc(ago(row.creation || row.changed_on))],
								[__("What"), (row) => esc(row.operation || row.status || row.subject || "—")],
							],
							(logins.records || []).slice(0, 20),
							__("No logins in this window.")
						)}
					</div>
					<div class="ra-card">
						<div class="ra-card__head"><h3>${__("Document changes")}</h3></div>
						${table(
							[
								[__("Document"), (row) => `<b>${esc(row.doctype || "—")}</b><br><small>${esc(row.document || row.docname || "")}</small>`],
								[__("Who"), (row) => esc(row.full_name || row.changed_by || row.owner || "—")],
								[__("When"), (row) => esc(ago(row.changed_on || row.creation))],
							],
							(changes.records || []).slice(0, 20),
							__("No changes in this window.")
						)}
					</div>
				</div>
			`);
		};

		this.al_picker = picker_for(this, ".ra-alwho", (value) => {
			this.al.user = value || "";
			run();
		});

		this.$main.find(".ra-alrange button").on("click", (event) => {
			const $b = $(event.currentTarget);
			this.$main.find(".ra-alrange button").removeClass("on");
			$b.addClass("on");
			this.al.days = cint($b.data("days"));
			run();
		});

		run();
	};

	/* Any user, not only the ones the caller administers - reading a log is not
	   granting anything, and the endpoint applies its own permission rules. */
	function picker_for(app, selector, onPick) {
		return picker(app.$main.find(selector), {
			label: __("User"),
			placeholder: __("Search anyone, or leave blank"),
			query: "",
			onPick,
		});
	}

	/* --------------------------------------------------------------------- *
	 * Monitoring · Error messages
	 * --------------------------------------------------------------------- */
	App.prototype.view_errors = async function () {
		this.$main.html(
			this.head(__("Error Messages"), __("What the system has been failing at, and who was on the other end of it")) +
				`<div class="ra-mount"><div class="ra-empty"><span class="ra-spinner"></span></div></div>`
		);

		let d;
		try {
			d = await frappe.xcall(UC + "it_dashboard.it_error_logs");
		} catch (error) {
			this.$main.find(".ra-mount").html(`<div class="ra-card"><div class="ra-empty">${esc(error.message)}</div></div>`);
			return;
		}

		if (d && d.success === false) {
			this.$main.find(".ra-mount").html(
				`<div class="ra-card"><div class="ra-empty">${esc(d.error || __("Not permitted."))}</div></div>`
			);
			return;
		}

		this.$main.find(".ra-mount").html(`
			<div class="ra-kpis">
				${this.kpi(__("Errors"), num(d.total), __("in the last {0} days", [num(d.days)]), d.total > 1000 ? "bad" : "warn", "")}
				${this.kpi(__("Distinct owners"), num((d.owners || []).length), __("accounts the errors are attributed to"), "flat", "")}
				${this.kpi(__("Window"), __("{0} days", [num(d.days)]), __("as the endpoint returns it"), "flat", "")}
			</div>
			<div class="ra-row2">
				<div class="ra-card">
					<div class="ra-card__head"><h3>${__("By owner")}</h3></div>
					${bars((d.owners || []).slice(0, 10), { label: "owner", value: "n" })}
				</div>
				<div class="ra-card">
					<div class="ra-card__head"><h3>${__("Most recent")}</h3></div>
					${table(
						[
							[__("What failed"), (row) => `<b class="ra-ellipsis" title="${esc(row.method || "")}">${esc(row.method || "—")}</b>`],
							[__("When"), (row) => esc(ago(row.creation))],
							[__("Owner"), "owner"],
						],
						(d.rows || []).slice(0, 20),
						__("No errors logged.")
					)}
				</div>
			</div>
		`);
	};

	/* --------------------------------------------------------------------- *
	 * Configuration · Monitor config
	 * --------------------------------------------------------------------- */
	App.prototype.view_monitor = async function () {
		this.$main.html(
			this.head(
				__("Monitor Config"),
				__("Which documents System Activity counts. Adding one here makes it appear there.")
			) + `<div class="ra-mount"><div class="ra-empty"><span class="ra-spinner"></span></div></div>`
		);

		let rows = [];
		let categories = [];
		try {
			const [list, cats] = await Promise.all([
				frappe.xcall(UC + "it_operations.itMonitorList"),
				frappe.xcall(UC + "it_operations.itCategoryList"),
			]);
			rows = (list && list.data) || [];
			categories = (cats && cats.data) || [];
		} catch (error) {
			this.$main.find(".ra-mount").html(`<div class="ra-card"><div class="ra-empty">${esc(error.message)}</div></div>`);
			return;
		}

		const on = rows.filter((row) => cint(row.enabled));

		this.$main.find(".ra-mount").html(`
			<div class="ra-kpis">
				${this.kpi(__("Monitored"), num(rows.length), __("document types configured"), "flat", "")}
				${this.kpi(__("Enabled"), num(on.length), __("counted in System Activity"), on.length ? "good" : "warn", on.length ? "" : __("nothing is being counted"))}
				${this.kpi(__("Categories"), num(categories.length), __("used to group the counts"), "flat", esc(categories.join(", ")))}
			</div>
			<div class="ra-card">
				<div class="ra-card__head">
					<h3>${__("Monitored documents")}</h3>
					<button class="ra-btn ghost sm ra-monadd">${__("Add one")}</button>
				</div>
				${table(
					[
						[__("Label"), (row) => `<b>${esc(row.label || row.document_type)}</b>`],
						[__("Document type"), "document_type"],
						[__("Category"), "category"],
						[__("Dated by"), "date_field"],
						[
							__("State"),
							(row) =>
								cint(row.enabled)
									? `<span class="ra-badge gain">${__("enabled")}</span>`
									: `<span class="ra-badge loss">${__("off")}</span>`,
						],
					],
					rows,
					__("Nothing is being monitored yet.")
				)}
			</div>
		`);

		this.$main.find(".ra-monadd").on("click", () => this.add_monitor(categories));
	};

	App.prototype.add_monitor = function (categories) {
		const dialog = new frappe.ui.Dialog({
			title: __("Monitor a document type"),
			fields: [
				{
					fieldtype: "Data",
					fieldname: "document_type",
					label: __("Document type"),
					reqd: 1,
					description: __("Exactly as it is named in the system, e.g. Sales Invoice."),
				},
				{ fieldtype: "Data", fieldname: "label", label: __("Label"), reqd: 1 },
				{
					fieldtype: "Select",
					fieldname: "category",
					label: __("Category"),
					options: categories.join("\n"),
					reqd: 1,
				},
				{
					fieldtype: "Data",
					fieldname: "date_field",
					label: __("Date field"),
					default: "creation",
					description: __("Which field decides that a document belongs to a given day."),
				},
			],
			primary_action_label: __("Add"),
			primary_action: async (values) => {
				dialog.hide();
				try {
					const out = await frappe.xcall(UC + "it_operations.itMonitorSave", {
						...values,
						enabled: 1,
					});
					if (out && out.error) throw new Error(out.error);
					frappe.show_alert({ message: __("Added {0}", [values.label]), indicator: "green" });
					this.view_monitor();
				} catch (error) {
					frappe.msgprint({ title: __("Refused"), message: esc(error.message), indicator: "red" });
				}
			},
		});
		dialog.show();
	};
})();
