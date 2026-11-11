# Copyright (c) 2026, Upande and contributors
# For license information, please see license.txt

"""Doctype access requests, IT's side (the Support screen of /it-dashboard).

A person blocked from a doctype asks for access (access_requests/ask.py), which raises an Issue of type "Doctype Access".
Opening one of those on the Support screen shows a panel instead of a chat: who asked, what they asked for, what they have now,
and which roles already give it. IT then either gives one of those roles or makes a role just for this doctype, and the person
is given the role through a role profile of the same name - the same route the User management screen uses, with the same
guards: system and code roles are never handed out, the IT Team profile is never handed out, and doctypes that hold code,
users or permissions are changed in Desk.

Nothing here weakens those guards; it only joins the existing tools into one step.
"""

import frappe
from frappe import _
from frappe.utils import cint

from upande_core.access_requests import ask, detect, setup
from upande_core.it_dashboard import permmgmt as pm
from upande_core.it_dashboard import rolemgmt as rm
from upande_core.it_dashboard import usermgmt as um

CLOSED = ("Resolved", "Closed")
ROLE_PREFIX = "Access - "


# --------------------------------------------------------------------------- #
# pure helpers
# --------------------------------------------------------------------------- #


def role_name_for(doctype):
	"""The role made for a doctype: `Access - Item`, cut to the length Frappe allows."""
	return (ROLE_PREFIX + doctype)[: rm.MAX_NAME].strip()


def with_dependencies(ptypes):
	"""Everything that has to be on for the asked permissions to work: write, create, delete and the rest need read."""
	out = set(ptypes)
	if out - {"select", "mask"}:
		out.add("read")
	return [p for p in detect.PTYPES if p in out]


def reason_of(description):
	"""What the person typed: the paragraph after the table of facts (ask.describe), or nothing."""
	tail = (description or "").split("</table>", 1)[-1] if "</table>" in (description or "") else ""
	return frappe.utils.strip_html_tags(tail).strip()[:600]


def role_covers(rule_rows, ptypes):
	"""Which of `ptypes` a role already gives, from its permission rows at level 0 (dicts with a truthy value per ptype)."""
	return [p for p in ptypes if any(r.get(p) for r in rule_rows if not r.get("permlevel"))]


# --------------------------------------------------------------------------- #
# reading
# --------------------------------------------------------------------------- #


def _require():
	um._require_admin()


def _access_issue(name, allow_closed=True):
	if not name or not frappe.db.exists("Issue", name):
		frappe.throw(_("Unknown request."), frappe.DoesNotExistError)
	issue = frappe.get_doc("Issue", name)
	if issue.issue_type != setup.ISSUE_TYPE or not issue.custom_access_doctype:
		frappe.throw(_("That is not a doctype access request."), frappe.ValidationError)
	if not allow_closed and issue.status in CLOSED:
		frappe.throw(_("That request is already closed."), frappe.ValidationError)
	return issue


def _rules(doctype):
	"""{role: [permission rows]} for a doctype, custom rules where there are any, else the standard ones."""
	rows = frappe.get_all("Custom DocPerm", filters={"parent": doctype}, fields=["*"], limit_page_length=0)
	if not rows:
		rows = frappe.get_all("DocPerm", filters={"parent": doctype}, fields=["*"], limit_page_length=0)
	out = {}
	for r in rows:
		out.setdefault(r.role, []).append(r)
	return out


def roles_that_give(doctype, ptypes):
	"""Manageable roles that already give some of `ptypes` on the doctype: {role, gives:[...], all: bool}, best first."""
	want = with_dependencies(ptypes)
	out = []
	for role, rows in _rules(doctype).items():
		# Permission rules can name a role that has since been deleted; there is nothing to give then.
		if not rm.is_manageable(role) or not frappe.db.exists("Role", role) or frappe.db.get_value("Role", role, "disabled"):
			continue
		gives = role_covers(rows, want)
		if gives:
			out.append({"role": role, "gives": gives, "all": len(gives) == len(want)})
	out.sort(key=lambda r: (not r["all"], -len(r["gives"]), r["role"]))
	return out


@frappe.whitelist(methods=["GET"])
def detail(name):
	"""Everything the panel shows for one request."""
	_require()
	issue = _access_issue(name)
	doctype, user = issue.custom_access_doctype, issue.raised_by
	asked = ask.clean_ptypes(issue.custom_access_ptypes)
	exists = bool(frappe.db.exists("DocType", doctype))
	refusal = None
	if exists and not pm.doctype_allowed(doctype):
		refusal = _("{0} holds code, users or permissions, so access to it is given in Desk by a System Manager.").format(doctype)
	have = ask.current_access(doctype, user) if exists and frappe.db.exists("User", user) else {}
	roles = roles_that_give(doctype, asked) if exists else []
	person = frappe.db.get_value("User", user, ["full_name", "enabled"], as_dict=True) or {}
	return {
		"id": issue.name,
		"status": issue.status,
		"closed": issue.status in CLOSED,
		"person": person.get("full_name") or user,
		"user": user,
		"enabled": bool(person.get("enabled", 1)),
		"doctype": doctype,
		"doctype_exists": exists,
		"document": issue.custom_access_document or "",
		"route": issue.custom_access_route or "",
		"asked": asked,
		"lacking": [p for p in asked if not have.get(p, False)],
		"have": have,
		"reason": reason_of(issue.description),
		"roles_now": sorted(frappe.get_roles(user)) if frappe.db.exists("User", user) else [],
		"profiles_now": [r.role_profile for r in frappe.get_doc("User", user).role_profiles] if frappe.db.exists("User", user) else [],
		"suggested": roles,
		"new_role": role_name_for(doctype),
		"new_role_exists": bool(frappe.db.exists("Role", role_name_for(doctype))),
		"refusal": refusal,
		"applicable": ask.applicable_ptypes(
			cint(frappe.get_meta(doctype).is_submittable) if exists else 0,
			cint(frappe.get_meta(doctype).allow_import) if exists else 0,
			True,
		),
	}


# --------------------------------------------------------------------------- #
# granting
# --------------------------------------------------------------------------- #


def profile_name_for(role):
	"""The role profile an access grant goes through: its own, so nobody else's profile is ever widened. The role made for a
	doctype ("Access - Item") is the profile's name too; any other role goes through "Access via <role>"."""
	return role if role.startswith(ROLE_PREFIX) else f"Access via {role}"[:140]


def _ensure_profile(role):
	"""A role profile holding just this role, made for access grants. One that exists with anything else in it is not ours to
	change, so it is refused rather than widened."""
	name = profile_name_for(role)
	if not frappe.db.exists("Role Profile", name):
		doc = frappe.get_doc({"doctype": "Role Profile", "role_profile": name, "roles": [{"role": role}]})
		doc.flags.ignore_permissions = True
		doc.insert()
	elif [r.role for r in frappe.get_doc("Role Profile", name).roles] != [role]:
		frappe.throw(_("A role profile called {0} already exists with other roles in it, so it is not used here.").format(name), frappe.ValidationError)
	return name


def _make_role_for(doctype, ptypes):
	role = role_name_for(doctype)
	if not frappe.db.exists("Role", role):
		rm.create_role(role, desk_access=1)
	have = frappe.db.get_value("Custom DocPerm", {"parent": doctype, "role": role, "permlevel": 0, "if_owner": 0}, "name")
	if not have:
		pm.add_rule(doctype, role, 0)  # starts with read
	row = frappe.db.get_value("Custom DocPerm", {"parent": doctype, "role": role, "permlevel": 0, "if_owner": 0}, ["name"], as_dict=True)
	current = frappe.db.get_value("Custom DocPerm", row.name, list(detect.PTYPES), as_dict=True) or {}
	for p in ptypes:
		if not cint(current.get(p)):
			pm.set_permission(doctype, role, 0, p, 1)
	return role


@frappe.whitelist(methods=["POST"])
def grant(name, ptypes=None, role=None):
	"""Give the person what they asked for (or the permissions chosen), through `role` when it is one that already gives it,
	else through a role made for the doctype. Closes the request as Resolved, with a note the person sees."""
	_require()
	issue = _access_issue(name, allow_closed=False)
	doctype, user = issue.custom_access_doctype, issue.raised_by
	if not frappe.db.exists("DocType", doctype):
		frappe.throw(_("{0} no longer exists.").format(doctype), frappe.DoesNotExistError)
	pm._check_doctype(doctype)
	# Everything that can refuse the person comes before anything is made: creating a role profile locks it until a background
	# job has run, so a refusal after that would leave it locked for ten minutes.
	person = um._get_user(user)
	if person.name == frappe.session.user:
		frappe.throw(_("You cannot change your own access."), frappe.ValidationError)
	chosen = with_dependencies(ask.clean_ptypes(frappe.parse_json(ptypes) if isinstance(ptypes, str) and ptypes[:1] == "[" else (ptypes or issue.custom_access_ptypes)))
	if not chosen:
		frappe.throw(_("Choose what to give."), frappe.ValidationError)
	meta = frappe.get_meta(doctype)
	chosen = [p for p in chosen if p in ask.applicable_ptypes(cint(meta.is_submittable), cint(meta.allow_import), True)]
	if role:
		if not rm.is_manageable(role) or not frappe.db.exists("Role", role):
			frappe.throw(_("{0} cannot be given from here.").format(role), frappe.PermissionError)
		missing = [p for p in chosen if p not in role_covers(_rules(doctype).get(role, []), chosen)]
		if missing:
			frappe.throw(_("{0} does not give {1} on {2}. Pick another role, or let a new one be made.").format(role, ", ".join(missing), doctype), frappe.ValidationError)
		used = role
	else:
		used = _make_role_for(doctype, chosen)
	profile = _ensure_profile(used)
	um.add_role_profile(user, profile)
	frappe.clear_cache(user=user)
	# Frappe remembers which fields are masked for a person, per doctype; forget it so the new access shows at once.
	frappe.cache.delete_keys(f"masked_fields::{doctype}")
	_close(issue, "Resolved", _("Access given: {0} on {1}, through {2}. Reload the page to see it.").format(", ".join(chosen), doctype, used))
	frappe.logger("it_user_admin").info(f"{frappe.session.user} gave {user} {chosen} on {doctype} through {used}")
	return detail(issue.name)


@frappe.whitelist(methods=["POST"])
def decline(name, note=None):
	"""Close the request without giving access, saying why."""
	_require()
	issue = _access_issue(name, allow_closed=False)
	note = (note or "").strip()[:500]
	_close(issue, "Closed", _("Access was not given.") + (" " + note if note else ""))
	return detail(issue.name)


def _close(issue, status, text):
	issue.flags.ignore_permissions = True
	issue.status = status
	issue.save()
	issue.add_comment("Comment", text)
