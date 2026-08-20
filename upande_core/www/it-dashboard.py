import frappe

no_cache = 1


def get_context(context):
    """IT Dashboard — internal IT portal page. Requires an authenticated Desk user."""
    if frappe.session.user == "Guest":
        frappe.local.flags.redirect_location = "/login?redirect-to=/it-dashboard"
        raise frappe.Redirect
    context.no_cache = 1
