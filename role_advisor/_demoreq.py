import frappe
from role_advisor import requests as rq

TARGETS = [
    ("bob@karenroses.com", [{"doctype": "Purchase Order", "right": "submit"}],
     "Needs to approve site purchase orders while the GM is away"),
    ("jonah@karenroses.com", [{"doctype": "Stock Entry", "right": "create"},
                              {"doctype": "Delivery Note", "right": "submit"}],
     "Taking over dispatch from Monday"),
    ("hillarylel22@gmail.com", [{"doctype": "Access Assignment Log", "right": "delete"}],
     "Wants to tidy old audit rows"),
]

def make():
    for user, reqs, why in TARGETS:
        if not frappe.db.exists("User", user):
            print("skip (no such user):", user); continue
        r = rq.submit_request(user, reqs, why)
        print(f"{r['request']} · {user} · {r['resolution']} · {r.get('profile') or '—'}")

def drop():
    for name in frappe.get_all("Access Request", pluck="name"):
        frappe.delete_doc("Access Request", name, force=True)
    frappe.db.commit()
    print("demo requests removed")
