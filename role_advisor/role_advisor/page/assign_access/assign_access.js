// Copyright (c) 2026, ghost-mann and contributors
// For license information, please see license.txt

/* Delegated user administration.
 *
 * Route is `assign-access`, deliberately not `user-access`: the Workspace is
 * labelled "User Access", which Frappe slugifies to `user-access`. A workspace
 * beats a page on a route collision, so the page silently never opens.
 *
 * Every field on User that matters sits at permlevel 1, and permlevel is
 * all-or-nothing, so a delegate gets no permlevel-1 write and comes through
 * role_advisor.api instead. This page is a thin client over those four methods:
 * it never writes a document directly, and it always previews before it acts.
 */

frappe.pages["assign-access"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("User Access Console"),
		single_column: true,
	});

	new UserAccessConsole(page);
};

class UserAccessConsole {
	constructor(page) {
		this.page = page;
		this.selected_user = null;
		this.profiles = [];

		this.render_layout();
		this.load_profiles();
	}

	render_layout() {
		this.page.main.append(`
			<div class="ra-console">
				<div class="ra-scope text-muted small mb-3"></div>
				<div class="row">
					<div class="col-md-5 ra-pick"></div>
					<div class="col-md-7 ra-detail">
						<div class="text-muted">${__("Choose a user to see what they hold.")}</div>
					</div>
				</div>
			</div>
		`);

		this.$scope = this.page.main.find(".ra-scope");
		this.$pick = this.page.main.find(".ra-pick");
		this.$detail = this.page.main.find(".ra-detail");

		this.user_field = frappe.ui.form.make_control({
			parent: this.$pick,
			df: {
				fieldtype: "Autocomplete",
				label: __("User"),
				fieldname: "user",
				placeholder: __("Search the users you administer"),
				// Options are the server's scoped list. Never a plain User link:
				// that would offer names the caller cannot actually manage.
				get_data: () => this.user_options || [],
				change: () => this.on_user_change(),
			},
			render_input: true,
		});

		this.$pick.append(`<div class="ra-grantable mt-4"></div>`);
		this.$grantable = this.$pick.find(".ra-grantable");
	}

	async load_profiles() {
		try {
			const [users, profiles] = await Promise.all([
				frappe.xcall("role_advisor.api.get_manageable_users", { limit: 500 }),
				frappe.xcall("role_advisor.api.get_grantable_profiles"),
			]);

			this.users = users;
			this.profiles = profiles;
			this.user_options = users.map((row) => ({
				value: row.name,
				label: row.full_name || row.name,
				description: (row.role_profiles || []).join(", ") || __("no profile"),
			}));

			this.$scope.html(
				__("You administer {0} users and may grant {1} role profiles.", [
					`<b>${users.length}</b>`,
					`<b>${profiles.length}</b>`,
				])
			);
			this.render_grantable();
		} catch (error) {
			// A non-delegate is the common case here, not a fault: the page is
			// visible to every User Manager, but only a Delegated User Admin
			// record grants the API.
			this.$scope.html(
				`<div class="alert alert-warning">${frappe.utils.escape_html(
					error.message || __("You are not configured as a delegated user administrator.")
				)}</div>`
			);
			this.$pick.empty();
		}
	}

	render_grantable() {
		if (!this.profiles.length) {
			this.$grantable.html(
				`<div class="text-muted small">${__("Your allowlist is empty. A System Manager sets it on your Delegated User Admin record.")}</div>`
			);
			return;
		}

		// Tightest first, so the least-privilege option reads as the default.
		const rows = this.profiles
			.map(
				(profile) => `
				<tr>
					<td>${frappe.utils.escape_html(profile.role_profile)}</td>
					<td class="text-right text-muted">${profile.doctype_count}</td>
					<td class="text-right text-muted">${profile.perm_count}</td>
					<td class="text-right">
						<button class="btn btn-xs btn-default ra-assign"
							data-profile="${frappe.utils.escape_html(profile.role_profile)}">
							${__("Preview")}
						</button>
					</td>
				</tr>`
			)
			.join("");

		this.$grantable.html(`
			<div class="text-muted small mb-2">${__("Profiles you may grant, least access first")}</div>
			<table class="table table-bordered table-sm">
				<thead>
					<tr>
						<th>${__("Role Profile")}</th>
						<th class="text-right">${__("Doctypes")}</th>
						<th class="text-right">${__("Grants")}</th>
						<th></th>
					</tr>
				</thead>
				<tbody>${rows}</tbody>
			</table>
		`);

		this.$grantable.find(".ra-assign").on("click", (event) => {
			const profile = $(event.currentTarget).data("profile");
			this.preview(profile);
		});
	}

	on_user_change() {
		const user = this.user_field.get_value();
		if (!user || user === this.selected_user) {
			return;
		}

		this.selected_user = user;
		const row = (this.users || []).find((candidate) => candidate.name === user);
		if (!row) {
			return;
		}

		this.$detail.html(`
			<h5>${frappe.utils.escape_html(row.full_name || row.name)}</h5>
			<div class="text-muted small mb-3">${frappe.utils.escape_html(row.name)}</div>
			${this.field_row(__("Role profile"), (row.role_profiles || []).join(", ") || __("none"))}
			${this.field_row(__("Module profile"), row.module_profile || __("none"))}
			${this.field_row(__("User type"), row.user_type)}
			<div class="text-muted small mt-3">${__("Pick a profile on the left to preview the change.")}</div>
		`);
	}

	field_row(label, value) {
		return `<div class="row mb-1">
			<div class="col-5 text-muted">${label}</div>
			<div class="col-7">${frappe.utils.escape_html(String(value))}</div>
		</div>`;
	}

	async preview(role_profile) {
		if (!this.selected_user) {
			frappe.show_alert({ message: __("Choose a user first."), indicator: "orange" });
			return;
		}

		const diff = await frappe.xcall("role_advisor.api.preview_assignment", {
			user: this.selected_user,
			role_profile: role_profile,
		});

		const list = (items, empty) =>
			items.length
				? items.map((item) => frappe.utils.escape_html(item)).join(", ")
				: `<span class="text-muted">${empty}</span>`;

		frappe.confirm(
			`<div>
				${this.field_row(__("User"), this.selected_user)}
				${this.field_row(__("Profile before"), diff.profiles_before.join(", ") || __("none"))}
				${this.field_row(__("Profile after"), diff.profiles_after.join(", "))}
				<hr>
				<div class="mb-1"><b>${__("Roles gained")}</b> (${diff.roles_gained.length})</div>
				<div class="mb-3 small">${list(diff.roles_gained, __("none"))}</div>
				<div class="mb-1"><b>${__("Roles lost")}</b> (${diff.roles_lost.length})</div>
				<div class="small">${list(diff.roles_lost, __("none"))}</div>
			</div>`,
			() => this.assign(role_profile),
			__("Confirm assignment")
		);
	}

	async assign(role_profile) {
		const result = await frappe.xcall("role_advisor.api.assign_access", {
			user: this.selected_user,
			role_profile: role_profile,
		});

		frappe.show_alert({
			message: __("{0} now holds {1}", [
				this.selected_user,
				result.profiles.join(", ") || __("no profile"),
			]),
			indicator: result.outcome === "Applied" ? "green" : "blue",
		});

		// Refresh so the panel reflects what was actually written, not what was
		// requested - the two differ if core pruned or added roles on save.
		const row = (this.users || []).find((candidate) => candidate.name === this.selected_user);
		if (row) {
			row.role_profiles = result.profiles;
			row.module_profile = result.module_profile;
		}
		this.selected_user = null;
		this.user_field.set_value(result.user);
	}
}
