# Copyright (c) 2026, Upande and contributors
# For license information, please see license.txt

"""Noticing that somebody lacks access, at the place Frappe decides it.

Every permission decision in Frappe ends in `frappe.permissions.has_permission`: Desk lists and forms, the REST API,
reports, link searches, print and export. Frappe has no hook there, so this wraps it (once per process, from the
`before_request` and `before_job` hooks) and notes each *refusal for the person making the request* - which doctype, which
permission (select, read, write, create, delete, submit, cancel, amend, print, email, report, import, export, share) and
which document. Masked values are different: Frappe never asks `has_permission` about them, it hides the fields through
`Meta.get_masked_fields`, so that is wrapped the same way and a hidden field counts as a missing "mask" permission.

A refusal on its own is not an error (Frappe asks many questions it expects to be answered "no": which menu items to show,
which links to offer). It becomes one when the request itself is blocked. `after_request` then:

  * for a page load, replaces the 403 with a redirect to /access-request, which shows the access that is missing and lets the
    person ask IT for it;
  * for a Desk or API call, adds `_access_denied` to the JSON error, which `public/js/access_request.js` turns into the same
    offer in place of Frappe's bare "Not permitted" box;
  * either way remembers it for the person, so /access-request can say what they were last blocked on.

Nothing here grants anything, and none of it can fail a request: every step is wrapped.
"""

import functools
import json
from urllib.parse import urlencode

import frappe

PTYPES = (
	"select",
	"read",
	"write",
	"create",
	"delete",
	"submit",
	"cancel",
	"amend",
	"print",
	"email",
	"report",
	"import",
	"export",
	"share",
	"mask",
)
SKIP_USERS = ("Administrator", "Guest")
MAX_DENIALS = 40
PAGE = "/access-request"
REMEMBER_FOR = 24 * 3600
MAX_REMEMBERED = 15


# --------------------------------------------------------------------------- #
# installing the watchers
# --------------------------------------------------------------------------- #


def install(*args, **kwargs):
	"""Wrap the permission check and the mask lookup. Safe to call any number of times."""
	import frappe.permissions as perms

	if not getattr(perms.has_permission, "_upande_watch", False):
		original = perms.has_permission

		@functools.wraps(original)
		def watched(*a, **k):
			result = original(*a, **k)
			if not result:
				try:
					note_refusal(a, k)
				except Exception:
					pass
			return result

		watched._upande_watch = True
		perms.has_permission = watched

	# A refusal only matters when it ends in an error. Frappe asks many questions it expects to be answered "no", and other code
	# (the website router, Builder) probes permissions it then ignores, so the hint is cut at the moment a PermissionError is
	# raised: it is the refusals since the previous PermissionError, and a 403 with none behind it (no desk access at all, say)
	# carries no hint.
	error = frappe.exceptions.PermissionError
	if not getattr(error.__init__, "_upande_watch", False):
		original_init = error.__init__

		@functools.wraps(original_init)
		def init(self, *a, **k):
			original_init(self, *a, **k)
			try:
				cut_at_error(" ".join(str(x) for x in a))
			except Exception:
				pass

		init._upande_watch = True
		error.__init__ = init

	from frappe.model.meta import Meta

	if not getattr(Meta.get_masked_fields, "_upande_watch", False):
		original_masked = Meta.get_masked_fields

		@functools.wraps(original_masked)
		def masked(self, *a, **k):
			fields = original_masked(self, *a, **k)
			if fields:
				try:
					note_masked(self.name, [f.get("fieldname") for f in fields])
				except Exception:
					pass
			return fields

		masked._upande_watch = True
		Meta.get_masked_fields = masked


# --------------------------------------------------------------------------- #
# noting what happened (per request)
# --------------------------------------------------------------------------- #


def _real_user():
	user = getattr(frappe.session, "user", None)
	return user if user and user not in SKIP_USERS else None


def parse_check(args, kwargs):
	"""(doctype, ptype, docname, user) from the arguments of a has_permission call."""
	names = ("doctype", "ptype", "doc", "user")
	values = dict(zip(names, args))
	values.update({k: v for k, v in kwargs.items() if k in names})
	doctype, doc = values.get("doctype"), values.get("doc")
	if doctype is not None and hasattr(doctype, "doctype") and doc is None:
		doc, doctype = doctype, doctype.doctype
	docname = None
	if doc is not None:
		docname = doc if isinstance(doc, str) else getattr(doc, "name", None)
	return doctype, values.get("ptype") or "read", docname, values.get("user")


def note_refusal(args, kwargs):
	user = _real_user()
	if not user:
		return
	doctype, ptype, docname, asked_about = parse_check(args, kwargs)
	if not isinstance(doctype, str) or not doctype or ptype not in PTYPES:
		return
	if asked_about and asked_about != user:
		return  # somebody else's permissions were being looked up
	log = getattr(frappe.local, "access_denials", None)
	if log is None:
		log = frappe.local.access_denials = []
	if len(log) < MAX_DENIALS:
		log.append({"doctype": doctype, "ptype": ptype, "document": docname if isinstance(docname, str) else None})


def cut_at_error(message=""):
	"""A PermissionError was just raised. What was refused since the last one is what it is about, unless it says otherwise:
	Frappe raises most permission errors bare (the explanation goes out as a separate message) or names the doctype ("Insufficient
	Permission for Item"), and either is taken as being about the refusal. An error with some other message ("no desk access")
	is not, however many probes ran before it."""
	if not _real_user():
		return
	hit = summarise(getattr(frappe.local, "access_denials", None))
	if hit and message.strip() and not names_doctype(message, hit["doctype"]):
		hit = None
	frappe.local.access_hit = hit
	frappe.local.access_denials = []


def names_doctype(message, doctype):
	text = frappe.utils.strip_html_tags(str(message or "")).lower()
	return bool(doctype) and doctype.lower() in text


def current_hit():
	"""What the last PermissionError of this request was about, or None."""
	return getattr(frappe.local, "access_hit", None)


def note_masked(doctype, fieldnames):
	if not _real_user():
		return
	seen = getattr(frappe.local, "access_masked", None)
	if seen is None:
		seen = frappe.local.access_masked = {}
	seen.setdefault(doctype, sorted({f for f in fieldnames if f}))


def summarise(denials):
	"""The one thing to ask for, from the refusals of a blocked request: the last doctype refused, with every permission
	refused on it. `select` is left out when `read` is there, as read implies it."""
	if not denials:
		return None
	last = denials[-1]
	doctype = last["doctype"]
	ptypes = []
	for d in denials:
		if d["doctype"] == doctype and d["ptype"] not in ptypes:
			ptypes.append(d["ptype"])
	if "read" in ptypes and "select" in ptypes:
		ptypes.remove("select")
	ptypes.sort(key=PTYPES.index)
	document = next((d["document"] for d in reversed(denials) if d["doctype"] == doctype and d.get("document")), None)
	return {"doctype": doctype, "ptypes": ptypes, "document": document}


# --------------------------------------------------------------------------- #
# remembering, per person
# --------------------------------------------------------------------------- #


def _key(user):
	return f"upande_access_denied::{user}"


def remember(user, hit, route=None):
	import time

	entry = {**hit, "route": route or "", "at": int(time.time())}
	recent = [e for e in (frappe.cache.get_value(_key(user)) or []) if e.get("doctype") != hit["doctype"]]
	recent.insert(0, entry)
	frappe.cache.set_value(_key(user), recent[:MAX_REMEMBERED], expires_in_sec=REMEMBER_FOR)


def recent(user):
	return frappe.cache.get_value(_key(user)) or []


# --------------------------------------------------------------------------- #
# the request is over
# --------------------------------------------------------------------------- #


def wants_html(request):
	if request is None:
		return False
	if (request.path or "").startswith(("/api/", "/assets/", "/files/", "/private/")):
		return False
	if request.headers.get("X-Requested-With") == "XMLHttpRequest":
		return False
	accept = request.accept_mimetypes
	return accept.best_match(["text/html", "application/json"]) == "text/html"


def page_address(hit, came_from):
	query = {"doctype": hit["doctype"], "ptype": ",".join(hit["ptypes"])}
	if hit.get("document"):
		query["document"] = hit["document"]
	if came_from:
		query["from"] = came_from
	return PAGE + "?" + urlencode(query)


def after_request(response=None, request=None):
	"""Turn a blocked request into an offer of access. Never raises."""
	try:
		_after_request(response, request)
	except Exception:
		frappe.logger("access_requests").exception("after_request failed")


def _after_request(response, request):
	if response is None:
		return
	user = _real_user()
	if not user or not frappe.db:
		return
	if response.status_code == 200:
		# Some values were hidden from this person (masked fields): say which doctype, so the desk can offer the request.
		hidden = masked_now()
		if hidden and not wants_html(request):
			response.headers["X-Access-Masked"] = ",".join(sorted(hidden))[:500]
		return
	if response.status_code != 403:
		return
	hit = current_hit()
	if not hit:
		return
	path = getattr(request, "full_path", "") or getattr(request, "path", "") or ""
	if path.startswith(PAGE):
		return
	came_from = path.rstrip("?") if wants_html(request) else (request.headers.get("Referer", "") if request else "")
	remember(user, hit, came_from)
	if wants_html(request):
		response.status_code = 302
		response.headers["Location"] = page_address(hit, came_from)
		response.headers.pop("Content-Type", None)
		response.set_data(b"")
		return
	if "json" in (response.mimetype or ""):
		body = json.loads(response.get_data(as_text=True) or "{}")
		body["_access_denied"] = {**hit, "page": page_address(hit, came_from)}
		response.set_data(json.dumps(body))


def masked_now():
	"""{doctype: [fieldnames]} hidden from the current user during this request."""
	return dict(getattr(frappe.local, "access_masked", None) or {})
