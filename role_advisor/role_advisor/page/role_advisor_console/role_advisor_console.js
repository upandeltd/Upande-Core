// Copyright (c) 2026, Upande and contributors
// For license information, please see license.txt

frappe.pages["role-advisor-console"].on_page_load = function (wrapper) {
	new RoleAdvisorConsole(wrapper);
};

const STATUS_INDICATOR = {
	Covered: "green",
	"Fit Found": "blue",
	"Gap - New Role Needed": "red",
	"Gap - New Profile Needed": "orange",
};

class RoleAdvisorConsole {
	constructor(wrapper) {
		this.page = frappe.ui.make_app_page({
			parent: wrapper,
			title: __("Role Advisor Console"),
			single_column: true,
		});

		this.catalog = [];
		this.resolution = null;

		this.make_form();
		this.make_result_area();
		this.load_catalog();
	}

	make_form() {
		this.page.main.append(`
			<div class="frappe-card p-3 mb-4">
				<div class="row">
					<div class="col-sm-5 ra-user-field"></div>
					<div class="col-sm-7 ra-transactions-field"></div>
				</div>
				<div class="mt-3 text-muted small ra-hint">
					${__("Pick the transactions this user needs to perform, then resolve.")}
				</div>
			</div>
		`);

		this.user_field = frappe.ui.form.make_control({
			parent: this.page.main.find(".ra-user-field"),
			df: {
				fieldtype: "Link",
				fieldname: "user",
				label: __("User"),
				options: "User",
				reqd: 1,
				get_query: () => ({ filters: { enabled: 1 } }),
			},
			render_input: true,
		});

		this.transactions_field = frappe.ui.form.make_control({
			parent: this.page.main.find(".ra-transactions-field"),
			df: {
				fieldtype: "MultiSelectList",
				fieldname: "transactions",
				label: __("Required Transactions"),
				// Filtering happens client-side against the cached catalogue, so
				// typing in the picker costs no round trips.
				get_data: (txt) => this.filter_catalog(txt),
			},
			render_input: true,
		});

		this.page.set_primary_action(__("Resolve"), () => this.resolve());
	}

	make_result_area() {
		this.$result = $('<div class="ra-result"></div>').appendTo(this.page.main);
	}

	load_catalog() {
		frappe.call({
			method: "role_advisor.api.get_transaction_catalog",
			callback: (r) => {
				this.catalog = r.message || [];
				if (!this.catalog.length) {
					this.page.main
						.find(".ra-hint")
						.text(
							__(
								"No transactions are catalogued yet. Add Transaction Catalog records first."
							)
						);
				}
			},
		});
	}

	filter_catalog(txt) {
		const needle = (txt || "").toLowerCase();

		return this.catalog
			.filter((row) => {
				if (!needle) return true;
				return [row.transaction_name, row.module, row.keywords, row.reference_doctype]
					.filter(Boolean)
					.some((field) => field.toLowerCase().includes(needle));
			})
			.map((row) => ({
				value: row.name,
				label: frappe.utils.escape_html(row.transaction_name || row.name),
				description: `${frappe.utils.escape_html(row.reference_doctype)} · ${
					row.required_perm
				}${row.module ? " · " + frappe.utils.escape_html(row.module) : ""}`,
			}));
	}

	resolve() {
		const user = this.user_field.get_value();
		const transactions = this.transactions_field.get_value() || [];

		if (!user) {
			frappe.msgprint({
				title: __("User Required"),
				message: __("Select the user whose access you are resolving."),
				indicator: "orange",
			});
			return;
		}

		if (!transactions.length) {
			frappe.msgprint({
				title: __("Nothing Selected"),
				message: __("Select at least one transaction."),
				indicator: "orange",
			});
			return;
		}

		frappe.call({
			method: "role_advisor.api.resolve_access",
			args: { user: user, transaction_names: transactions },
			freeze: true,
			freeze_message: __("Resolving access…"),
			callback: (r) => {
				if (!r.message) return;
				this.resolution = r.message;
				this.render_result(r.message);
			},
		});
	}

	render_result(res) {
		const indicator = STATUS_INDICATOR[res.status] || "gray";
		const profiles = (res.current_profiles || []).length
			? res.current_profiles.map((p) => frappe.utils.escape_html(p)).join(", ")
			: __("None assigned");

		this.$result.empty().append(`
			<div class="frappe-card p-3">
				<div class="d-flex justify-content-between align-items-center mb-3">
					<h5 class="mb-0">${__("Resolution")}</h5>
					<span class="indicator-pill ${indicator}">
						${frappe.utils.escape_html(res.status)}
					</span>
				</div>
				<div class="row mb-3">
					<div class="col-sm-6">
						<div class="text-muted small">${__("Current Role Profiles")}</div>
						<div>${profiles}</div>
					</div>
					<div class="col-sm-6">
						<div class="text-muted small">${__("Suggested Role Profile")}</div>
						<div>${
							res.suggested_profile
								? frappe.utils.escape_html(res.suggested_profile)
								: "&mdash;"
						}</div>
					</div>
				</div>
				<div class="ra-detail"></div>
				<div class="ra-actions mt-3"></div>
				<div class="text-muted small mt-3">
					${__("Logged as")}
					${
						// Core's helper, so the route stays correct: v16 serves the
						// Desk at /desk, and a hand-written /app link only reaches it
						// through a 301 that reloads out of the SPA.
						frappe.utils.get_form_link(
							"Access Request Log",
							res.access_request_log,
							true,
							frappe.utils.escape_html(res.access_request_log)
						)
					}
				</div>
			</div>
		`);

		const $detail = this.$result.find(".ra-detail");

		if (res.status === "Covered") {
			$detail.append(
				`<div class="alert alert-success mb-0">
					${__("The user's current role profiles already cover every requested transaction. No change needed.")}
				</div>`
			);
		} else if (res.status === "Fit Found") {
			$detail.append(this.render_extra_perms(res));
			this.render_apply_button(res);
		} else {
			$detail.append(this.render_unmet(res));
		}
	}

	render_extra_perms(res) {
		const extras = res.extra_perms || [];

		if (!extras.length) {
			return `<div class="alert alert-success mb-0">
				${__("This profile is an exact fit — it grants nothing beyond what was requested.")}
			</div>`;
		}

		const rows = extras
			.map(
				(perm) => `<tr>
					<td>${frappe.utils.escape_html(perm.doctype)}</td>
					<td><span class="indicator-pill orange">${frappe.utils.escape_html(perm.perm)}</span></td>
				</tr>`
			)
			.join("");

		// The over-grant is the tradeoff the admin is being asked to accept, so it
		// is shown in full rather than summarised behind a count.
		return `
			<div class="alert alert-warning">
				<strong>${__("Tradeoff:")}</strong>
				${__("{0} would also grant {1} permission(s) beyond this request.", [
					frappe.utils.escape_html(res.suggested_profile),
					extras.length,
				])}
			</div>
			<div class="table-responsive">
				<table class="table table-sm table-bordered mb-0">
					<thead>
						<tr>
							<th>${__("DocType")}</th>
							<th style="width: 30%">${__("Extra Permission")}</th>
						</tr>
					</thead>
					<tbody>${rows}</tbody>
				</table>
			</div>
		`;
	}

	render_unmet(res) {
		const unmet = res.unmet_requirements || [];

		const explanation =
			res.status === "Gap - New Role Needed"
				? __("At least one requirement is granted by no role on this site. A role must be created or extended before any profile can cover this request.")
				: __("Every requirement exists in some role, but no single role profile bundles them all. A new role profile would close this gap.");

		const rows = unmet
			.map(
				(req) => `<tr>
					<td>${frappe.utils.escape_html(req.transaction)}</td>
					<td>${frappe.utils.escape_html(req.doctype)}</td>
					<td><span class="indicator-pill red">${frappe.utils.escape_html(req.perm)}</span></td>
					<td>${
						req.granted_by_any_role
							? `<span class="text-muted">${__("Exists in a role")}</span>`
							: `<span class="text-danger">${__("No role grants this")}</span>`
					}</td>
				</tr>`
			)
			.join("");

		return `
			<div class="alert alert-danger">${explanation}</div>
			<div class="table-responsive">
				<table class="table table-sm table-bordered mb-0">
					<thead>
						<tr>
							<th>${__("Transaction")}</th>
							<th>${__("DocType")}</th>
							<th>${__("Permission")}</th>
							<th>${__("Availability")}</th>
						</tr>
					</thead>
					<tbody>${rows}</tbody>
				</table>
			</div>
		`;
	}

	render_apply_button(res) {
		// Apply is gated twice: here for the UI, and by frappe.only_for on the
		// server. The client check is convenience only.
		if (!frappe.user.has_role("System Manager")) {
			this.$result.find(".ra-actions").append(
				`<div class="text-muted small">
					${__("Only a System Manager can apply this suggestion.")}
				</div>`
			);
			return;
		}

		const $btn = $(
			`<button class="btn btn-primary btn-sm">
				${__("Apply {0}", [frappe.utils.escape_html(res.suggested_profile)])}
			</button>`
		);

		$btn.on("click", () => this.confirm_apply(res));
		this.$result.find(".ra-actions").append($btn);
	}

	confirm_apply(res) {
		const extras = (res.extra_perms || []).length;

		frappe.confirm(
			__(
				"Replace {0}'s role profiles with <strong>{1}</strong>?<br><br>This grants {2} permission(s) beyond the request and removes any profile they hold today.",
				[
					frappe.utils.escape_html(res.user),
					frappe.utils.escape_html(res.suggested_profile),
					extras,
				]
			),
			() => {
				frappe.call({
					method: "role_advisor.api.apply_suggestion",
					args: { access_request_log_name: res.access_request_log },
					freeze: true,
					freeze_message: __("Applying role profile…"),
					callback: (r) => {
						if (!r.message) return;
						frappe.show_alert({
							message: __("{0} now holds {1}", [
								r.message.user,
								r.message.role_profile,
							]),
							indicator: "green",
						});
						// Re-resolve so the panel reflects the new state and the
						// Apply button cannot be clicked twice.
						this.resolve();
					},
				});
			}
		);
	}
}
