# Copyright (c) 2026, Upande and contributors
# For license information, please see license.txt
#
# /access-request: where a person lands when Frappe blocks them (access_requests/detect.py redirects here), and where they ask
# IT for access to a doctype. Anyone signed in may open it; it shows only their own access.

import frappe

no_cache = 1


def get_context(context):
	if frappe.session.user == "Guest":
		frappe.local.flags.redirect_location = "/login?redirect-to=" + frappe.utils.quote(frappe.request.full_path or "/access-request")
		raise frappe.Redirect
	context.no_breadcrumbs = 1
	context.title = "Ask for access"
	context.csrf_token = frappe.sessions.get_csrf_token()
	return context
