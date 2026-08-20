import frappe

no_cache = 1


def get_context(context):
    """Workforce & Access — inactive employees vs active accounts. Desk login required."""
    if frappe.session.user == "Guest":
        frappe.local.flags.redirect_location = "/login?redirect-to=/it-workforce"
        raise frappe.Redirect
    context.no_cache = 1
