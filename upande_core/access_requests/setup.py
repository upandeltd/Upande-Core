# Copyright (c) 2026, Upande and contributors
# For license information, please see license.txt

"""What a doctype access request needs on the site: the Issue Type and four fields on Issue. Run from after_migrate;
idempotent. Sites without the Issue doctype (no ERPNext support module) are left alone, and asking for access there says so."""

import frappe

ISSUE_TYPE = "Doctype Access"
FIELDS = {
	"Issue": [
		{"fieldname": "custom_access_doctype", "label": "Doctype", "fieldtype": "Data", "insert_after": "issue_type", "read_only": 1, "depends_on": "eval:doc.issue_type=='Doctype Access'"},
		{"fieldname": "custom_access_ptypes", "label": "Access asked for", "fieldtype": "Data", "insert_after": "custom_access_doctype", "read_only": 1, "depends_on": "eval:doc.issue_type=='Doctype Access'"},
		{"fieldname": "custom_access_document", "label": "Document", "fieldtype": "Data", "insert_after": "custom_access_ptypes", "read_only": 1, "depends_on": "eval:doc.issue_type=='Doctype Access'"},
		{"fieldname": "custom_access_route", "label": "Where it happened", "fieldtype": "Small Text", "insert_after": "custom_access_document", "read_only": 1, "depends_on": "eval:doc.issue_type=='Doctype Access'"},
	]
}


def ensure():
	if not frappe.db.exists("DocType", "Issue"):
		return
	if not frappe.db.exists("Issue Type", ISSUE_TYPE):
		frappe.get_doc({"doctype": "Issue Type", "name": ISSUE_TYPE, "description": "A person asked for access to a doctype."}).insert(ignore_permissions=True)
	from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

	create_custom_fields(FIELDS, ignore_validate=True)
