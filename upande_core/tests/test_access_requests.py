"""Doctype access requests (access_requests/, it_dashboard/access.py).

The first class is pure. The second builds a throwaway submittable doctype with a masked field, one role per permission level and
a test user for each, then simulates real refusals - select, read, write, create, delete, submit, cancel, amend, print, email,
report, import, export, share and mask - and walks the whole life of a request: noticed, redirected, asked for, shown to IT,
granted or declined. The doctype, roles, users and issues are removed again afterwards.
"""

import json
import unittest

import frappe
from frappe.tests import IntegrationTestCase
from werkzeug.test import EnvironBuilder
from werkzeug.wrappers import Request, Response

from upande_core.access_requests import ask, detect, setup
from upande_core.it_dashboard import access as acc

PROBE = "AR Probe"
PTYPES = detect.PTYPES

# role -> the permissions it holds on the probe (permission level 0)
ROLES = {
	"ARS Select": {"select"},
	"ARS Read": {"read"},
	"ARS Write": {"read", "write"},
	"ARS Create": {"read", "create"},
	"ARS Delete": {"read", "delete"},
	"ARS Submit": {"read", "write", "submit"},
	"ARS Cancel": {"read", "write", "submit", "cancel"},
	"ARS Amend": {"read", "write", "create", "submit", "cancel", "amend"},
	"ARS Print": {"read", "print"},
	"ARS Email": {"read", "email"},
	"ARS Report": {"read", "report"},
	"ARS Export": {"read", "export"},
	"ARS Import": {"read", "create", "import"},
	"ARS Share": {"read", "share"},
	"ARS Mask": {"read", "mask"},
}


def perm(doctype, ptype, **kw):
	"""frappe.has_permission, but quiet (it has no print_logs; the function behind it does)."""
	return frappe.permissions.has_permission(doctype, ptype, print_logs=False, **kw)


def email_for(role):
	return role.lower().replace(" ", ".") + "@example.com"


NOBODY = "ars.nobody@example.com"
IT = "ars.it@example.com"


# --------------------------------------------------------------------------- #
# pure
# --------------------------------------------------------------------------- #


class TestPure(unittest.TestCase):
	def test_summarise_asks_for_the_last_doctype_and_drops_select_under_read(self):
		hit = detect.summarise(
			[
				{"doctype": "Item", "ptype": "select", "document": None},
				{"doctype": "Item", "ptype": "read", "document": "ITM-1"},
				{"doctype": "Bin", "ptype": "write", "document": None},
				{"doctype": "Bin", "ptype": "select", "document": None},
				{"doctype": "Bin", "ptype": "read", "document": None},
			]
		)
		self.assertEqual(hit, {"doctype": "Bin", "ptypes": ["read", "write"], "document": None})
		self.assertIsNone(detect.summarise([]))

	def test_summarise_keeps_a_named_document(self):
		hit = detect.summarise([{"doctype": "Item", "ptype": "read", "document": "A"}, {"doctype": "Item", "ptype": "read", "document": None}])
		self.assertEqual(hit["document"], "A")

	def test_parse_check_reads_positional_and_keyword_arguments(self):
		self.assertEqual(detect.parse_check(("Item", "write"), {}), ("Item", "write", None, None))
		self.assertEqual(detect.parse_check(("Item",), {"ptype": "print", "doc": "ITM-1", "user": "a@b.c"}), ("Item", "print", "ITM-1", "a@b.c"))

		class Doc:
			doctype, name = "Item", "ITM-2"

		self.assertEqual(detect.parse_check((Doc(), "read"), {}), ("Item", "read", "ITM-2", None))

	def test_ptypes_are_cleaned(self):
		self.assertEqual(ask.clean_ptypes("write, read ,nonsense,read"), ["read", "write"])
		self.assertEqual(ask.clean_ptypes(["mask", "select"]), ["select", "mask"])
		self.assertEqual(ask.clean_ptypes(None), [])

	def test_only_meaningful_permissions_are_offered(self):
		plain = ask.applicable_ptypes(False, False, False)
		self.assertNotIn("submit", plain)
		self.assertNotIn("import", plain)
		self.assertNotIn("mask", plain)
		full = ask.applicable_ptypes(True, True, True)
		self.assertEqual(tuple(full), PTYPES)

	def test_writing_needs_reading_but_select_and_mask_stand_alone(self):
		self.assertEqual(acc.with_dependencies(["write"]), ["read", "write"])
		self.assertEqual(acc.with_dependencies(["select"]), ["select"])
		self.assertEqual(acc.with_dependencies(["mask"]), ["mask"])
		self.assertEqual(acc.with_dependencies(["delete", "submit"]), ["read", "delete", "submit"])

	def test_a_role_covers_what_its_level_zero_rows_give(self):
		rows = [{"permlevel": 0, "read": 1, "write": 0}, {"permlevel": 1, "write": 1}]
		self.assertEqual(acc.role_covers(rows, ["read", "write"]), ["read"])

	def test_role_name_is_cut_to_what_frappe_allows(self):
		self.assertTrue(acc.role_name_for("X" * 200).startswith("Access - "))
		self.assertLessEqual(len(acc.role_name_for("X" * 200)), 60)

	def test_the_profile_for_a_grant_is_its_own(self):
		self.assertEqual(acc.profile_name_for("Access - Item"), "Access - Item")
		self.assertEqual(acc.profile_name_for("Sales Manager"), "Access via Sales Manager")

	def test_the_reason_is_only_what_the_person_typed(self):
		html = ask.describe("a@b.c", "Item", ["read"], "ITM-1", "/app/item", "to check stock")
		self.assertEqual(acc.reason_of(html), "to check stock")
		self.assertEqual(acc.reason_of(ask.describe("a@b.c", "Item", ["read"], "", "", "")), "")
		self.assertEqual(acc.reason_of(None), "")

	def test_wants_html_only_for_page_loads(self):
		def req(path, accept, xhr=False):
			headers = {"Accept": accept}
			if xhr:
				headers["X-Requested-With"] = "XMLHttpRequest"
			return Request(EnvironBuilder(path=path, headers=headers).get_environ())

		self.assertTrue(detect.wants_html(req("/app/item", "text/html,application/xhtml+xml")))
		self.assertFalse(detect.wants_html(req("/api/method/x", "text/html")))
		self.assertFalse(detect.wants_html(req("/app/item", "application/json")))
		self.assertFalse(detect.wants_html(req("/app/item", "text/html", xhr=True)))


# --------------------------------------------------------------------------- #
# simulation
# --------------------------------------------------------------------------- #


def make_user(email, roles=(), profiles=()):
	if frappe.db.exists("User", email):
		frappe.delete_doc("User", email, force=True, ignore_permissions=True)
	doc = frappe.get_doc({"doctype": "User", "email": email, "first_name": email.split("@")[0], "send_welcome_email": 0, "enabled": 1})
	for r in roles:
		doc.append("roles", {"role": r})
	for p in profiles:
		doc.append("role_profiles", {"role_profile": p})
	doc.insert(ignore_permissions=True)
	return doc


class TestSimulation(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")
		detect.install()
		setup.ensure()
		for role in list(ROLES) + ["ARS Base"]:
			if not frappe.db.exists("Role", role):
				frappe.get_doc({"doctype": "Role", "role_name": role, "desk_access": 1}).insert(ignore_permissions=True)
		if frappe.db.exists("DocType", PROBE):
			frappe.delete_doc("DocType", PROBE, force=True, ignore_permissions=True)
		perms = [{"role": "System Manager", **{p: int(p != "mask") for p in PTYPES}}]
		for role, held in ROLES.items():
			# every permission is set, 0 or 1: a DocPerm row defaults write, create and delete to on
			perms.append({"role": role, "permlevel": 0, **{p: int(p in held) for p in PTYPES}})
		frappe.get_doc(
			{
				"doctype": "DocType",
				"name": PROBE,
				"module": "Upande Core",
				"custom": 1,
				"is_submittable": 1,
				"allow_import": 1,
				"naming_rule": "Random",
				"autoname": "hash",
				"fields": [
					{"fieldname": "title", "fieldtype": "Data", "label": "Title", "mask": 1, "in_list_view": 1},
					{"fieldname": "amount", "fieldtype": "Currency", "label": "Amount"},
				],
				"permissions": perms,
			}
		).insert(ignore_permissions=True)
		for role in ROLES:
			make_user(email_for(role), roles=["ARS Base", role])
		make_user(NOBODY, roles=["ARS Base"])
		if not frappe.db.exists("Role Profile", "IT Team"):
			frappe.get_doc({"doctype": "Role Profile", "role_profile": "IT Team", "roles": [{"role": "ARS Base"}]}).insert(ignore_permissions=True)
		make_user(IT, roles=["ARS Base"], profiles=["IT Team"])
		frappe.db.commit()

	@classmethod
	def tearDownClass(cls):
		frappe.set_user("Administrator")
		frappe.db.rollback()
		for issue in frappe.get_all("Issue", filters={"issue_type": setup.ISSUE_TYPE, "raised_by": ["like", "ars.%"]}, pluck="name"):
			frappe.delete_doc("Issue", issue, force=True, ignore_permissions=True)
		for email in [email_for(r) for r in ROLES] + [NOBODY, IT]:
			frappe.delete_doc("User", email, force=True, ignore_permissions=True)
		made = f"Access - {PROBE}"
		via = [f"Access via {r}" for r in ROLES]
		for dt, name in [("Role Profile", made), ("DocType", PROBE)] + [("Role Profile", v) for v in via]:
			if frappe.db.exists(dt, name):
				frappe.delete_doc(dt, name, force=True, ignore_permissions=True)
		for dt, filters in (("Custom DocPerm", {"parent": PROBE}), ("Has Role", {"role": ["in", list(ROLES) + [made, "ARS Base"]]})):
			for n in frappe.get_all(dt, filters=filters, pluck="name"):
				frappe.delete_doc(dt, n, force=True, ignore_permissions=True)
		for role in list(ROLES) + [made, "ARS Base"]:
			if frappe.db.exists("Role", role):
				frappe.delete_doc("Role", role, force=True, ignore_permissions=True)
		frappe.db.commit()
		super().tearDownClass()

	def setUp(self):
		frappe.set_user("Administrator")
		doc = frappe.get_doc({"doctype": PROBE, "title": "secret title", "amount": 5}).insert(ignore_permissions=True)
		self.name = doc.name

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback()

	# -- helpers --------------------------------------------------------------

	def as_(self, email):
		frappe.set_user(email)
		frappe.local.access_denials = []
		frappe.local.access_hit = None
		frappe.local.access_masked = {}

	def refused(self):
		"""What the last PermissionError was about, or what has been refused so far when none was raised."""
		return detect.current_hit() or detect.summarise(getattr(frappe.local, "access_denials", None))

	def expect_blocked(self, fn, doctype, ptype):
		with self.assertRaises(frappe.PermissionError):
			fn()
		hit = self.refused()
		self.assertIsNotNone(hit, "the refusal was not noticed")
		self.assertEqual(hit["doctype"], doctype)
		self.assertIn(ptype, hit["ptypes"])
		return hit

	# -- every permission, as Frappe answers it -------------------------------

	def test_every_permission_is_answered_and_every_refusal_is_noticed(self):
		for role, held in ROLES.items():
			self.as_(email_for(role))
			implied = set(held) | ({"select"} if "read" in held else set())
			for ptype in PTYPES:
				if ptype == "mask":
					continue  # not a has_permission question; see the mask tests
				frappe.local.access_denials = []
				allowed = perm(PROBE, ptype)
				self.assertEqual(allowed, ptype in implied, f"{role}: {ptype}")
				seen = {d["ptype"] for d in frappe.local.access_denials if d["doctype"] == PROBE}
				if allowed:
					self.assertNotIn(ptype, seen, f"{role} was allowed {ptype} but a refusal was noted")
				else:
					self.assertIn(ptype, seen, f"{role} was refused {ptype} and it was not noticed")

	def test_a_person_with_no_role_on_the_doctype_is_refused_everything(self):
		self.as_(NOBODY)
		for ptype in PTYPES:
			if ptype == "mask":
				continue
			self.assertFalse(perm(PROBE, ptype), ptype)
		hit = self.refused()
		self.assertEqual(hit["doctype"], PROBE)
		self.assertNotIn("select", hit["ptypes"])  # read implies it
		self.assertIn("read", hit["ptypes"])

	def test_other_peoples_permissions_are_not_noticed_as_my_refusals(self):
		self.as_(email_for("ARS Read"))
		self.assertFalse(perm(PROBE, "write", user=NOBODY))
		self.assertEqual(frappe.local.access_denials, [])

	def test_the_administrator_and_guests_are_never_noticed(self):
		frappe.set_user("Administrator")
		frappe.local.access_denials = []
		perm(PROBE, "read")
		self.assertEqual(frappe.local.access_denials, [])

	# -- real operations ------------------------------------------------------

	def test_opening_a_document_without_read(self):
		self.as_(NOBODY)
		self.expect_blocked(lambda: frappe.get_doc(PROBE, self.name).check_permission("read"), PROBE, "read")

	def test_listing_without_select_or_read(self):
		self.as_(NOBODY)
		self.expect_blocked(lambda: frappe.get_list(PROBE, limit=1), PROBE, "read")

	def test_listing_with_only_select_is_allowed_to_find_but_not_to_read(self):
		self.as_(email_for("ARS Select"))
		self.assertTrue(perm(PROBE, "select"))
		self.assertFalse(perm(PROBE, "read"))
		self.assertIn("read", {d["ptype"] for d in frappe.local.access_denials})

	def test_editing_without_write(self):
		self.as_(email_for("ARS Read"))

		def edit():
			doc = frappe.get_doc(PROBE, self.name)
			doc.amount = 99
			doc.save()

		self.expect_blocked(edit, PROBE, "write")

	def test_creating_without_create(self):
		self.as_(email_for("ARS Read"))
		self.expect_blocked(lambda: frappe.get_doc({"doctype": PROBE, "title": "x"}).insert(), PROBE, "create")

	def test_deleting_without_delete(self):
		self.as_(email_for("ARS Read"))
		self.expect_blocked(lambda: frappe.delete_doc(PROBE, self.name), PROBE, "delete")

	def test_submitting_without_submit(self):
		self.as_(email_for("ARS Write"))
		self.expect_blocked(lambda: frappe.get_doc(PROBE, self.name).submit(), PROBE, "submit")

	def test_cancelling_without_cancel(self):
		frappe.set_user("Administrator")
		frappe.get_doc(PROBE, self.name).submit()
		self.as_(email_for("ARS Submit"))
		self.expect_blocked(lambda: frappe.get_doc(PROBE, self.name).cancel(), PROBE, "cancel")

	def test_amending_without_amend(self):
		self.as_(email_for("ARS Cancel"))
		self.expect_blocked(lambda: frappe.has_permission(PROBE, "amend", throw=True), PROBE, "amend")

	def test_the_rest_without_their_permission(self):
		cases = [("print", "ARS Read"), ("email", "ARS Read"), ("report", "ARS Read"), ("export", "ARS Read"), ("import", "ARS Read"), ("share", "ARS Read")]
		for ptype, role in cases:
			self.as_(email_for(role))
			self.expect_blocked(lambda p=ptype: frappe.has_permission(PROBE, p, doc=self.name, throw=True), PROBE, ptype)

	def test_a_person_who_has_a_permission_is_not_refused_it(self):
		for ptype, role in (("print", "ARS Print"), ("email", "ARS Email"), ("report", "ARS Report"), ("export", "ARS Export"), ("share", "ARS Share"), ("delete", "ARS Delete")):
			self.as_(email_for(role))
			self.assertTrue(perm(PROBE, ptype), f"{role}: {ptype}")
			self.assertNotIn(ptype, {d["ptype"] for d in frappe.local.access_denials})

	# -- mask -----------------------------------------------------------------

	def test_masked_values_are_noticed_and_counted_as_a_missing_mask_permission(self):
		self.as_(email_for("ARS Read"))
		fields = [f.fieldname for f in frappe.get_meta(PROBE).get_masked_fields()]
		self.assertEqual(fields, ["title"])
		self.assertEqual(detect.masked_now(), {PROBE: ["title"]})
		self.assertFalse(ask.current_access(PROBE)["mask"])
		shown = frappe.get_list(PROBE, filters={"name": self.name}, fields=["title"])[0].title
		self.assertNotEqual(shown, "secret title")
		self.assertEqual(shown.strip("X*•"), "")

	def test_a_person_with_mask_sees_the_value_and_is_not_noticed(self):
		self.as_(email_for("ARS Mask"))
		self.assertEqual(frappe.get_meta(PROBE).get_masked_fields(), [])
		self.assertEqual(detect.masked_now(), {})
		self.assertTrue(ask.current_access(PROBE)["mask"])
		self.assertEqual(frappe.get_list(PROBE, filters={"name": self.name}, fields=["title"])[0].title, "secret title")

	# -- the end of the request ----------------------------------------------

	def _response(self, status, body=None):
		return Response(json.dumps(body if body is not None else {"exc_type": "PermissionError"}), status=status, mimetype="application/json")

	def _request(self, path, accept):
		return Request(EnvironBuilder(path=path, headers={"Accept": accept}).get_environ())

	def test_a_blocked_page_load_is_redirected_to_the_request_page(self):
		self.as_(NOBODY)
		with self.assertRaises(frappe.PermissionError):
			frappe.get_doc(PROBE, self.name).check_permission("read")
		response = self._response(403)
		detect.after_request(response, self._request("/app/ar-probe/" + self.name, "text/html"))
		self.assertEqual(response.status_code, 302)
		location = response.headers["Location"]
		self.assertTrue(location.startswith("/access-request?"), location)
		self.assertIn("doctype=AR+Probe", location)
		self.assertIn("ptype=read", location)
		self.assertEqual(detect.recent(NOBODY)[0]["doctype"], PROBE)

	def test_a_blocked_desk_call_carries_the_offer_in_its_json(self):
		self.as_(email_for("ARS Read"))
		with self.assertRaises(frappe.PermissionError):
			frappe.get_doc(PROBE, self.name).check_permission("write")
		response = self._response(403)
		detect.after_request(response, self._request("/api/method/frappe.client.save", "application/json"))
		self.assertEqual(response.status_code, 403)
		body = json.loads(response.get_data(as_text=True))
		self.assertEqual(body["_access_denied"]["doctype"], PROBE)
		self.assertIn("write", body["_access_denied"]["ptypes"])
		self.assertTrue(body["_access_denied"]["page"].startswith("/access-request?"))

	def test_a_403_with_no_noticed_refusal_is_left_alone(self):
		self.as_(NOBODY)
		response = self._response(403, {"exc_type": "PermissionError"})
		detect.after_request(response, self._request("/app/anything", "text/html"))
		self.assertEqual(response.status_code, 403)

	def test_a_swallowed_probe_is_not_blamed_for_an_unrelated_403(self):
		self.as_(NOBODY)
		perm("Builder Page", "write")  # somebody's probe, ignored
		with self.assertRaises(frappe.PermissionError):
			frappe.throw("No desk access", frappe.PermissionError)  # the real cause: nothing to do with a doctype
		response = self._response(403)
		detect.after_request(response, self._request("/desk/sales-order", "text/html"))
		self.assertEqual(response.status_code, 403)
		self.assertIsNone(detect.current_hit())

	def test_the_refusals_behind_the_error_are_the_ones_reported(self):
		self.as_(NOBODY)
		perm("Builder Page", "write")  # earlier, unrelated
		with self.assertRaises(frappe.PermissionError):
			frappe.get_doc(PROBE, self.name).check_permission("read")
		hit = detect.current_hit()
		self.assertEqual(hit["doctype"], PROBE)

	def test_the_request_page_is_never_redirected_to_itself(self):
		self.as_(NOBODY)
		perm(PROBE, "read")
		response = self._response(403)
		detect.after_request(response, self._request("/access-request?doctype=X", "text/html"))
		self.assertEqual(response.status_code, 403)

	def test_hidden_values_are_flagged_on_a_successful_response(self):
		self.as_(email_for("ARS Read"))
		frappe.get_meta(PROBE).get_masked_fields()
		response = self._response(200, {"message": 1})
		detect.after_request(response, self._request("/api/method/frappe.desk.form.load.getdoc", "application/json"))
		self.assertEqual(response.headers.get("X-Access-Masked"), PROBE)

	# -- asking ---------------------------------------------------------------

	def test_asking_raises_an_issue_in_the_persons_name(self):
		self.as_(email_for("ARS Read"))
		res = ask.ask(PROBE, ["write", "delete"], reason="monthly clean-up", document=self.name, route="/app/ar-probe")
		issue = frappe.get_doc("Issue", res["name"])
		self.assertEqual(issue.issue_type, setup.ISSUE_TYPE)
		self.assertEqual(issue.raised_by, email_for("ARS Read"))
		self.assertEqual(issue.custom_access_doctype, PROBE)
		self.assertEqual(issue.custom_access_ptypes, "write, delete")
		self.assertIn("monthly clean-up", issue.description)
		self.assertEqual(res["already_open"], 0)

	def test_asking_again_extends_the_open_request_instead_of_opening_a_second(self):
		self.as_(email_for("ARS Read"))
		first = ask.ask(PROBE, ["write"])
		second = ask.ask(PROBE, ["delete"], reason="and delete too")
		self.assertEqual(second["name"], first["name"])
		self.assertEqual(second["already_open"], 1)
		self.assertEqual(second["ptypes"], ["write", "delete"])
		self.assertEqual(frappe.db.count("Issue", {"issue_type": setup.ISSUE_TYPE, "raised_by": email_for("ARS Read"), "custom_access_doctype": PROBE}), 1)

	def test_asking_for_what_you_already_have_is_refused(self):
		self.as_(email_for("ARS Write"))
		with self.assertRaises(frappe.ValidationError):
			ask.ask(PROBE, ["read", "write"])

	def test_asking_for_nothing_or_nonsense_is_refused(self):
		self.as_(NOBODY)
		for bad in ([], ["fly"], None):
			with self.assertRaises(frappe.ValidationError):
				ask.ask(PROBE, bad)
		with self.assertRaises(frappe.DoesNotExistError):
			ask.ask("No Such Doctype", ["read"])

	def test_a_guest_cannot_ask(self):
		frappe.set_user("Guest")
		with self.assertRaises(frappe.PermissionError):
			ask.ask(PROBE, ["read"])

	def test_what_i_have_shows_current_access_and_the_open_request(self):
		self.as_(email_for("ARS Write"))
		ask.ask(PROBE, ["submit"])
		info = ask.what_i_have(PROBE)
		self.assertTrue(info["have"]["write"])
		self.assertFalse(info["have"]["submit"])
		self.assertIn("submit", info["lacking"])
		self.assertEqual(info["open_request"].custom_access_ptypes, "submit")
		self.assertEqual(info["masked_fields"], ["title"])

	# -- IT's side ------------------------------------------------------------

	def _ask_as(self, role, ptypes, **kw):
		self.as_(email_for(role))
		res = ask.ask(PROBE, ptypes, **kw)
		frappe.set_user(IT)
		return res["name"]

	def test_it_sees_the_request_in_the_support_inbox_as_an_access_request(self):
		name = self._ask_as("ARS Read", ["write"])
		from upande_core.it_dashboard import mobile

		rows = [r for r in mobile._inbox_rows(None, None) if r["id"] == name]
		self.assertEqual(len(rows), 1)
		self.assertEqual(rows[0]["kind"], "access")
		self.assertEqual(rows[0]["doctype"], PROBE)
		self.assertEqual(rows[0]["ptypes"], "write")

	def test_the_panel_shows_who_what_and_which_roles_already_give_it(self):
		name = self._ask_as("ARS Read", ["submit"])
		d = acc.detail(name)
		self.assertEqual(d["doctype"], PROBE)
		self.assertEqual(d["asked"], ["submit"])
		self.assertEqual(d["lacking"], ["submit"])
		self.assertTrue(d["have"]["read"])
		self.assertFalse(d["refusal"])
		roles = {r["role"]: r for r in d["suggested"]}
		self.assertIn("ARS Submit", roles)
		self.assertIn("read", roles["ARS Submit"]["gives"])
		self.assertEqual(d["new_role"], f"Access - {PROBE}")

	def test_granting_through_an_existing_role(self):
		name = self._ask_as("ARS Read", ["submit"])
		self.assertFalse(perm(PROBE, "submit", user=email_for("ARS Read")))
		out = acc.grant(name, role="ARS Submit")
		self.assertTrue(frappe.db.exists("Role Profile", "Access via ARS Submit"))
		self.assertTrue(out["closed"])
		self.assertEqual(out["status"], "Resolved")
		self.assertTrue(perm(PROBE, "submit", user=email_for("ARS Read")))
		self.assertIn("ARS Submit", frappe.get_roles(email_for("ARS Read")))

	def test_a_grant_never_widens_a_role_profile_that_is_not_its_own(self):
		frappe.get_doc({"doctype": "Role Profile", "role_profile": "Access via ARS Submit", "roles": [{"role": "ARS Print"}, {"role": "ARS Email"}]}).insert(ignore_permissions=True)
		name = self._ask_as("ARS Read", ["submit"])
		with self.assertRaises(frappe.ValidationError):
			acc.grant(name, role="ARS Submit")
		self.assertEqual(sorted(r.role for r in frappe.get_doc("Role Profile", "Access via ARS Submit").roles), ["ARS Email", "ARS Print"])

	def test_roles_named_by_rules_but_deleted_are_not_offered(self):
		"""A permission rule can name a role that no longer exists (the role was deleted, the rule was not)."""
		frappe.set_user("Administrator")
		rule = frappe.new_doc("DocPerm")
		rule.update({"parent": PROBE, "parenttype": "DocType", "parentfield": "permissions", "role": "ARS Ghost", "permlevel": 0, "read": 1, "delete": 1, "idx": 99})
		rule.name = frappe.generate_hash(length=10)
		rule.db_insert()  # no link check: that is how such a rule comes to exist
		frappe.clear_cache(doctype=PROBE)
		self.assertFalse(frappe.db.exists("Role", "ARS Ghost"))
		self.assertNotIn("ARS Ghost", [r["role"] for r in acc.roles_that_give(PROBE, ["delete"])])
		self.assertIn("ARS Delete", [r["role"] for r in acc.roles_that_give(PROBE, ["delete"])])

	def test_granting_through_a_role_that_does_not_give_it_is_refused(self):
		name = self._ask_as("ARS Read", ["delete"])
		with self.assertRaises(frappe.ValidationError):
			acc.grant(name, role="ARS Print")

	def test_granting_through_a_new_role_made_for_the_doctype(self):
		name = self._ask_as("ARS Read", ["write", "delete"])
		who = email_for("ARS Read")
		self.assertFalse(perm(PROBE, "write", user=who))
		out = acc.grant(name)
		made = f"Access - {PROBE}"
		self.assertTrue(frappe.db.exists("Role", made))
		self.assertTrue(frappe.db.exists("Role Profile", made))
		self.assertEqual(out["status"], "Resolved")
		for p in ("read", "write", "delete"):
			self.assertTrue(perm(PROBE, p, user=who), p)
		self.assertFalse(perm(PROBE, "submit", user=who))
		# everyone else is untouched
		self.assertFalse(perm(PROBE, "write", user=email_for("ARS Print")))

	def test_granting_write_also_gives_read(self):
		self.as_(NOBODY)
		res = ask.ask(PROBE, ["write"])
		frappe.set_user(IT)
		acc.grant(res["name"])
		self.assertTrue(perm(PROBE, "read", user=NOBODY))
		self.assertTrue(perm(PROBE, "write", user=NOBODY))

	def test_granting_mask_shows_the_value(self):
		name = self._ask_as("ARS Read", ["mask"])
		who = email_for("ARS Read")
		acc.grant(name)
		frappe.set_user(who)
		frappe.local.access_masked = {}
		self.assertEqual(frappe.get_meta(PROBE).get_masked_fields(), [])
		self.assertEqual(frappe.get_list(PROBE, filters={"name": self.name}, fields=["title"])[0].title, "secret title")

	def test_a_request_can_be_declined_with_a_reason(self):
		name = self._ask_as("ARS Read", ["delete"])
		out = acc.decline(name, "Ask your manager first")
		self.assertEqual(out["status"], "Closed")
		comments = frappe.get_all("Comment", filters={"reference_doctype": "Issue", "reference_name": name, "comment_type": "Comment"}, pluck="content")
		self.assertTrue(any("Ask your manager first" in c for c in comments))
		self.assertFalse(perm(PROBE, "delete", user=email_for("ARS Read")))

	def test_a_closed_request_cannot_be_granted_again(self):
		name = self._ask_as("ARS Read", ["delete"])
		acc.decline(name)
		with self.assertRaises(frappe.ValidationError):
			acc.grant(name)

	def test_doctypes_that_hold_users_or_permissions_are_not_granted_from_here(self):
		self.as_(NOBODY)
		res = ask.ask("Server Script", ["read"])
		frappe.set_user(IT)
		d = acc.detail(res["name"])
		self.assertTrue(d["refusal"])
		with self.assertRaises(frappe.PermissionError):
			acc.grant(res["name"])

	def test_only_the_it_team_can_see_or_grant(self):
		name = self._ask_as("ARS Read", ["delete"])
		self.as_(email_for("ARS Read"))
		for fn in (lambda: acc.detail(name), lambda: acc.grant(name), lambda: acc.decline(name)):
			with self.assertRaises(frappe.PermissionError):
				fn()

	def test_an_ordinary_issue_is_not_an_access_request(self):
		frappe.set_user(IT)
		issue = frappe.get_doc({"doctype": "Issue", "subject": "printer", "raised_by": IT}).insert(ignore_permissions=True)
		with self.assertRaises(frappe.ValidationError):
			acc.detail(issue.name)


if __name__ == "__main__":
	unittest.main()
