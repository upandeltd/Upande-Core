import frappe

DELEGATE = "Administrator"
COMPANY = "Karen Roses"
ALLOWLIST = ["scout", "Agriculture Supervisor", "HR Clerk", "Sales (Restricted)", "Guard"]

def setup():
    """Create a test delegate so the console has something to show."""
    if frappe.db.exists("Delegated User Admin", DELEGATE):
        frappe.delete_doc("Delegated User Admin", DELEGATE, force=True)

    profiles = [p for p in ALLOWLIST if frappe.db.exists("Role Profile", p)]
    doc = frappe.get_doc({
        "doctype": "Delegated User Admin",
        "user": DELEGATE,
        "enabled": 1,
        "companies": [{"company": COMPANY}],
        "allowed_role_profiles": [{"role_profile": p} for p in profiles],
        "can_create_users": 0,
        "can_disable_users": 0,
    }).insert(ignore_permissions=True)
    frappe.db.commit()

    from role_advisor import api, delegation
    delegation.clear_cache()
    users = api.get_manageable_users(limit=500)
    grantable = api.get_grantable_profiles()
    print(f"delegate: {doc.user}  scope: {COMPANY}")
    print(f"  manageable users: {len(users)}")
    print(f"  grantable profiles: {[g['role_profile'] for g in grantable]}")
    print(f"  sample targets: {[u['name'] for u in users[:4]]}")

def teardown():
    if frappe.db.exists("Delegated User Admin", DELEGATE):
        frappe.delete_doc("Delegated User Admin", DELEGATE, force=True)
        frappe.db.commit()
    print("delegate record removed; enforcement off again")
