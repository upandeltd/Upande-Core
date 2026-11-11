# Copyright (c) 2026, Upande and contributors
# For license information, please see license.txt

"""Asking for access to a doctype.

A request is an Issue of type "Doctype Access" raised in the person's name. The person who lacks access usually cannot create
an Issue, so it is inserted for them here, after checking who they are and what they asked for. One open request per person and
doctype: asking again adds the new permissions to it instead of opening a second one.

Pure helpers come first so they are unit tested without a site.
"""

import json

import frappe
from frappe import _
from frappe.utils import cint

from upande_core.access_requests import detect, setup

OPEN = ("Open", "Replied", "On Hold")
IMPLIED = {"read": ("select",), "write": ("select",)}
REASON_MAX = 500


# --------------------------------------------------------------------------- #
# pure helpers
# --------------------------------------------------------------------------- #


def clean_ptypes(values):
	"""The permissions asked for: known ones only, once each, in the usual order."""
	if isinstance(values, str):
		values = [v.strip() for v in values.replace(";", ",").split(",")]
	chosen = {v for v in (values or []) if v in detect.PTYPES}
	return [p for p in detect.PTYPES if p in chosen]


def applicable_ptypes(is_submittable, allow_import, has_masked_fields):
	"""The permissions that mean something for a doctype: no submit/cancel/amend on one that cannot be submitted, no import
	where importing is off, no mask where nothing is masked."""
	out = []
	for p in detect.PTYPES:
		if p in ("submit", "cancel", "amend") and not is_submittable:
			continue
		if p == "import" and not allow_import:
			continue
		if p == "mask" and not has_masked_fields:
			continue
		out.append(p)
	return out


def subject_for(doctype, ptypes):
	return f"[Access] {doctype}: {', '.join(ptypes)}"[:140]


def describe(person, doctype, ptypes, document, route, reason):
	rows = [
		("Person", person),
		("Doctype", doctype),
		("Access asked for", ", ".join(ptypes)),
		("Document", document or ""),
		("Where it happened", route or ""),
	]
	body = "".join(f"<tr><td><b>{frappe.utils.escape_html(k)}</b></td><td>{frappe.utils.escape_html(v)}</td></tr>" for k, v in rows if v)
	why = f"<p>{frappe.utils.escape_html(reason)}</p>" if reason else ""
	return f"<table>{body}</table>{why}"


# --------------------------------------------------------------------------- #
# what the person has now
# --------------------------------------------------------------------------- #


def current_access(doctype, user=None):
	"""{ptype: bool} for the person on the doctype, as Frappe sees it (roles, user permissions aside)."""
	user = user or frappe.session.user
	meta = frappe.get_meta(doctype)
	masked = _masked_for(meta, user)
	have = {}
	for p in applicable_ptypes(cint(meta.is_submittable), cint(meta.allow_import), bool(masked) or _has_mask_fields(meta)):
		if p == "mask":
			have[p] = not masked
		else:
			have[p] = bool(frappe.permissions.has_permission(doctype, p, user=user, print_logs=False))
	return have


def _has_mask_fields(meta):
	return any(df.get("mask") for df in meta.fields)


def _masked_for(meta, user):
	if user == "Administrator":
		return []
	roles = set(frappe.get_roles(user))
	levels = {p.permlevel for p in meta.get("permissions", []) if p.role in roles and p.get("mask")}
	return [df.fieldname for df in meta.fields if df.get("mask") and df.permlevel not in levels]


def open_request(user, doctype):
	if not frappe.db.exists("DocType", "Issue"):
		return None
	return frappe.db.get_value(
		"Issue",
		{"issue_type": setup.ISSUE_TYPE, "raised_by": user, "custom_access_doctype": doctype, "status": ["in", OPEN]},
		["name", "custom_access_ptypes", "status", "creation"],
		as_dict=True,
	)


# --------------------------------------------------------------------------- #
# the person's side
# --------------------------------------------------------------------------- #


def _require_person():
	user = frappe.session.user
	if user == "Guest":
		frappe.throw(_("Log in to ask for access."), frappe.PermissionError)
	return user


@frappe.whitelist(methods=["GET"])
def recent_denials():
	"""What the person was last blocked on, newest first."""
	return detect.recent(_require_person())


@frappe.whitelist(methods=["GET"])
def doctype_for_route(slug):
	"""The doctype a Desk address such as `sales-order` stands for, when the person cannot read it. Desk does not treat a
	doctype the person cannot read as a doctype at all: it looks for a page of that name and fails with no doctype in the
	error, so the Desk script asks here before showing its generic box. None when it is not a doctype, or they can read it."""
	_require_person()
	slug = (slug or "").strip().lower()[:140]
	if not slug or "/" in slug:
		return None
	name = frappe.db.get_value("DocType", slug.replace("-", " "), "name")
	if not name or frappe.permissions.has_permission(name, "read", print_logs=False):
		return None
	return {"doctype": name, "ptypes": ["read"]}


@frappe.whitelist(methods=["GET"])
def what_i_have(doctype):
	"""The person's current access to a doctype and what is still open for it."""
	user = _require_person()
	if not doctype or not frappe.db.exists("DocType", doctype):
		frappe.throw(_("Unknown doctype."), frappe.DoesNotExistError)
	have = current_access(doctype, user)
	asked = open_request(user, doctype)
	return {
		"doctype": doctype,
		"have": have,
		"lacking": [p for p, ok in have.items() if not ok],
		"open_request": asked,
		"masked_fields": _masked_for(frappe.get_meta(doctype), user),
	}


@frappe.whitelist(methods=["POST"])
def ask(doctype, ptypes, reason=None, document=None, route=None):
	"""Raise (or extend) the person's request for access to a doctype."""
	user = _require_person()
	if not frappe.db.exists("DocType", "Issue"):
		frappe.throw(_("This site has no support desk to send the request to. Ask IT directly."), frappe.ValidationError)
	if not doctype or not frappe.db.exists("DocType", doctype):
		frappe.throw(_("Unknown doctype."), frappe.DoesNotExistError)
	wanted = clean_ptypes(frappe.parse_json(ptypes) if isinstance(ptypes, str) and ptypes[:1] == "[" else ptypes)
	if not wanted:
		frappe.throw(_("Choose what you need to do."), frappe.ValidationError)
	have = current_access(doctype, user)
	wanted = [p for p in wanted if not have.get(p, False)]
	if not wanted:
		frappe.throw(_("You already have that access to {0}.").format(doctype), frappe.ValidationError)
	reason = (reason or "").strip()[:REASON_MAX]
	document = (document or "").strip()[:140]
	route = (route or "").strip()[:500]
	existing = open_request(user, doctype)
	if existing:
		merged = clean_ptypes(set(clean_ptypes(existing.custom_access_ptypes)) | set(wanted))
		issue = frappe.get_doc("Issue", existing.name)
		issue.flags.ignore_permissions = True
		if merged != clean_ptypes(existing.custom_access_ptypes):
			issue.custom_access_ptypes = ", ".join(merged)
			issue.subject = subject_for(doctype, merged)
			issue.save()
		issue.add_comment("Comment", f"{user} asked again: {', '.join(wanted)}" + (f" - {reason}" if reason else ""))
		return {"name": issue.name, "status": issue.status, "ptypes": merged, "already_open": 1}
	issue = frappe.get_doc(
		{
			"doctype": "Issue",
			"issue_type": setup.ISSUE_TYPE,
			"subject": subject_for(doctype, wanted),
			"raised_by": user,
			"status": "Open",
			"priority": "Medium",
			"description": describe(user, doctype, wanted, document, route, reason),
			"custom_access_doctype": doctype,
			"custom_access_ptypes": ", ".join(wanted),
			"custom_access_document": document,
			"custom_access_route": route,
		}
	)
	issue.flags.ignore_permissions = True
	issue.insert()
	return {"name": issue.name, "status": issue.status, "ptypes": wanted, "already_open": 0}
