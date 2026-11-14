# Copyright (c) 2026, Upande and contributors
# For license information, please see license.txt
"""Devices as the IT dashboard shows them: physical devices, not installs, and who they belong to.

A Mobile App Install is one app on one device. A physical device is a set of installs, joined when they share

  * a device key (the hashed Android ID the app sends), or a raw Android ID, or
  * a `device_group`, the id IT gives when it says "these are the same device" (a factory reset, an app signed with another
    key, a shared handheld that reports several ids).

Android scopes the Android ID per app-signing key and per user profile, and resets it on a factory reset, so the id alone
does not always tell one phone from two. Expo Go (the development container) reports the runtime "exposdk:<n>" and gets its
own id: those installs are "test builds" and are left out of the count unless asked for.

A device is linked to an Asset by writing the device's group id into `Asset.custom_device_id` (one device to one asset), and
to a custodian (an Employee) directly on its installs. An Asset also has a custodian of its own, which a linked device shows
when it has none of its own.
"""

import json

import frappe
from frappe import _
from frappe.utils import cint

from upande_core.it_dashboard import mobile as it

INSTALL = it.INSTALL
ASSET = "Asset"
HEALTH_FLAGS = ("low_battery", "low_storage", "offline", "outdated_os", "outdated_app")


def _has_links():
	"""Whether this site has been migrated to carry the device links."""
	return frappe.db.has_column(INSTALL, "device_group") and frappe.db.has_column(ASSET, "custom_device_id")


# --------------------------------------------------------------------------- #
# grouping
# --------------------------------------------------------------------------- #


def group_installs(items):
	"""Lists of install rows that are one physical device: rows joined by a shared device key, Android ID or device group."""
	parent = {r["id"]: r["id"] for r in items}

	def find(x):
		while parent[x] != x:
			parent[x] = parent[parent[x]]
			x = parent[x]
		return x

	seen = {}
	for r in items:
		for kind, value in (("key", r.get("device_key")), ("android", (r.get("android_id") or "").strip().lower()), ("group", r.get("device_group"))):
			if not value:
				continue
			k = (kind, value)
			if k in seen:
				parent[find(r["id"])] = find(seen[k])
			else:
				seen[k] = r["id"]
	out = {}
	for r in items:
		out.setdefault(find(r["id"]), []).append(r)
	return list(out.values())


def _person_rows(installs):
	"""The people who used one device, across all its installs: first and last use, sign-ins and the apps they used."""
	people = {}
	for r in installs:
		for u in r["users"] or [{"user": r["owner"], "name": r["owner_name"], "first_seen": "", "last_seen": r["last_seen"], "version": r["app_version"], "logins": 0, "app": r["app"]}]:
			if not u["user"]:
				continue
			p = people.setdefault(u["user"], {"user": u["user"], "name": u["name"], "first_seen": u["first_seen"], "last_seen": u["last_seen"], "logins": 0, "uses": []})
			if u["first_seen"] and (not p["first_seen"] or u["first_seen"] < p["first_seen"]):
				p["first_seen"] = u["first_seen"]
			if (u["last_seen"] or "") > (p["last_seen"] or ""):
				p["last_seen"] = u["last_seen"]
			p["logins"] += u["logins"]
			p["uses"].append({"app": u["app"], "version": u["version"]})
	return sorted(people.values(), key=lambda p: p["last_seen"] or "", reverse=True)


def _ids_on(installs):
	"""The distinct ids behind one device (one per device key), so IT can see, and split off, what was merged."""
	by = {}
	for r in installs:
		k = r.get("device_key") or "install:" + r["id"]
		g = by.setdefault(k, {"key": k, "id": (r.get("android_id") or "") or (r.get("device_key") or "")[:12], "apps": [], "install_ids": [], "test": True, "last_seen": ""})
		if r["app"] not in g["apps"]:
			g["apps"].append(r["app"])
		g["install_ids"].append(r["id"])
		g["test"] = g["test"] and bool(r.get("test_build"))
		if (r["last_seen"] or "") > g["last_seen"]:
			g["last_seen"] = r["last_seen"]
	return sorted(by.values(), key=lambda g: g["last_seen"], reverse=True)


def _links(devices):
	"""Fill in each device's asset and custodian, with one query for the assets and one for the employees."""
	groups = {d["group"] for d in devices if d["group"]}
	assets = {}
	if groups and _has_links():
		for a in frappe.get_all(ASSET, filters={"custom_device_id": ["in", list(groups)]}, fields=["name", "asset_name", "custodian", "location", "custom_device_id"], limit_page_length=0):
			assets[a.custom_device_id] = a
	employees = {d["custodian_direct"] for d in devices if d["custodian_direct"]} | {a.custodian for a in assets.values() if a.custodian}
	names = {}
	if employees:
		names = {e.name: e.employee_name for e in frappe.get_all("Employee", filters={"name": ["in", list(employees)]}, fields=["name", "employee_name"], limit_page_length=0)}
	for d in devices:
		a = assets.get(d["group"]) if d["group"] else None
		d["asset"] = {"name": a.name, "asset_name": a.asset_name or a.name, "location": a.location or ""} if a else None
		who, via = (d["custodian_direct"], "direct") if d["custodian_direct"] else ((a.custodian, "asset") if a and a.custodian else ("", ""))
		d["custodian"] = {"id": who, "name": names.get(who) or who, "via": via} if who else None
	return devices


def build_devices(app=None, state=None, search=None, tests=False, developer=False):
	"""Every physical device with its people, ids, health and links. Test builds are left out unless `tests`."""
	items = it._device_items(app, state, search, developer)
	if not tests:
		items = [r for r in items if not r.get("test_build")]
	devices = []
	for installs in group_installs(items):
		installs = sorted(installs, key=lambda r: r["last_seen"] or "", reverse=True)
		latest = installs[0]
		apps = []
		for r in installs:
			if r["app"] not in apps:
				apps.append(r["app"])
		group = next((r["device_group"] for r in installs if r.get("device_group")), "")
		ids = _ids_on(installs)
		d = {
			**latest,
			"key": group or ids[0]["key"],
			"group": group,
			"apps": apps,
			"installs": len(installs),
			"install_ids": [r["id"] for r in installs],
			"people": _person_rows(installs),
			"ids": ids,
			"merged": len(ids) > 1,
			"has_id": any(r.get("android_id") or r.get("device_key") for r in installs),
			"device_id": group or (latest.get("android_id") or "") or (latest.get("device_key") or "")[:12],
			"test": all(r.get("test_build") for r in installs),
			"custodian_direct": next((r["custodian_direct"] for r in installs if r.get("custodian_direct")), ""),
		}
		for k in ("users", "device_key", "device_group", "test_build"):
			d.pop(k, None)
		devices.append(d)
	return _links(devices)


# --------------------------------------------------------------------------- #
# reading
# --------------------------------------------------------------------------- #


@frappe.whitelist(methods=["GET"])
def device_tree(app=None, state=None, health=None, search=None, tests=None):
	"""The device inventory as a drill-down: model -> device -> the people who used it.

	`health` and the health counts are per device (its most recent install). `tests` includes Expo Go test builds."""
	it._require_it()
	developer = it.is_developer()
	devices = build_devices(app, state, search, bool(cint(tests)), developer)
	counts = {k: 0 for k in HEALTH_FLAGS}
	for d in devices:
		for f in d["flags"]:
			if f in counts:
				counts[f] += 1
	if health:
		devices = [d for d in devices if health in d["flags"]]
	models = {}
	for d in devices:
		m = models.setdefault(d["device"], {"name": d["device"], "devices": [], "people": set(), "installs": 0, "issues": 0, "last_seen": ""})
		m["devices"].append(d)
		m["people"].update(p["user"] for p in d["people"])
		m["installs"] += d["installs"]
		m["issues"] += 1 if d["flags"] else 0
		if (d["last_seen"] or "") > m["last_seen"]:
			m["last_seen"] = d["last_seen"]
	out = []
	for m in models.values():
		m["devices"].sort(key=lambda d: d["last_seen"] or "", reverse=True)
		m["people"] = len(m["people"])
		out.append(m)
	out.sort(key=lambda m: (-len(m["devices"]), m["name"]))
	everyone = {p["user"] for d in devices for p in d["people"]}
	return {
		"models": out,
		"totals": {
			"devices": len(devices),
			"models": len(out),
			"people": len(everyone),
			"installs": sum(d["installs"] for d in devices),
			"no_id": sum(1 for d in devices if not d["has_id"]),
			"test": sum(1 for d in devices if d["test"]),
			"with_asset": sum(1 for d in devices if d["asset"]),
			"with_custodian": sum(1 for d in devices if d["custodian"]),
		},
		"health": counts,
		"links_ready": _has_links(),
		"developer": developer,
	}


@frappe.whitelist(methods=["GET"])
def device_links(kind, app=None, search=None):
	"""Devices linked to an asset (`kind` "asset") or to a custodian ("custodian"), test builds included: a link is deliberate."""
	it._require_it()
	if kind not in ("asset", "custodian"):
		frappe.throw(_("Unknown kind."), frappe.ValidationError)
	term = (search or "").strip().lower()[:60]
	rows = []
	for d in build_devices(app, None, None, True, False):
		link = d["asset"] if kind == "asset" else d["custodian"]
		if not link:
			continue
		text = " ".join([d["device"], d["device_id"], d["asset"]["asset_name"] if d["asset"] else "", d["asset"]["name"] if d["asset"] else "", d["custodian"]["name"] if d["custodian"] else ""] + [p["name"] + " " + p["user"] for p in d["people"]])
		if term and term not in text.lower():
			continue
		rows.append(d)
	rows.sort(key=lambda d: ((d["asset"]["asset_name"] if kind == "asset" else d["custodian"]["name"]) or "").lower())
	return {"rows": rows, "total": len(rows), "links_ready": _has_links()}


def _match(term, *texts):
	term = (term or "").strip().lower()
	return not term or any(term in (t or "").lower() for t in texts)


@frappe.whitelist(methods=["GET"])
def find_assets(search=None):
	it._require_it()
	if not frappe.db.exists("DocType", ASSET):
		return {"rows": []}
	term = "%" + (search or "").strip()[:60] + "%"
	rows = frappe.db.sql(
		"""SELECT name, asset_name, custodian, location, custom_device_id AS device_id FROM `tabAsset`
		WHERE docstatus < 2 AND (name LIKE %(t)s OR asset_name LIKE %(t)s)
		ORDER BY (custom_device_id IS NOT NULL AND custom_device_id != ''), modified DESC LIMIT 12""",
		{"t": term},
		as_dict=True,
	) if frappe.db.has_column(ASSET, "custom_device_id") else []
	return {"rows": rows}


@frappe.whitelist(methods=["GET"])
def find_custodians(search=None):
	it._require_it()
	term = "%" + (search or "").strip()[:60] + "%"
	rows = frappe.db.sql(
		"""SELECT name, employee_name, department FROM `tabEmployee`
		WHERE status = 'Active' AND (name LIKE %(t)s OR employee_name LIKE %(t)s) ORDER BY employee_name LIMIT 12""",
		{"t": term},
		as_dict=True,
	)
	return {"rows": rows}


@frappe.whitelist(methods=["GET"])
def find_devices(search=None, exclude=None):
	"""Devices to merge into: by model, id or person. `exclude` is the install ids of the device being edited."""
	it._require_it()
	skip = set(_ids(exclude))
	out = []
	for d in build_devices(None, None, search, True, False):
		if skip & set(d["install_ids"]):
			continue
		out.append(d)
		if len(out) >= 12:
			break
	return {"rows": [{"label": d["device"] + " · " + (d["device_id"] or "no id"), "sub": ", ".join(p["name"] for p in d["people"][:3]), "install_ids": d["install_ids"], "apps": d["apps"]} for d in out]}


# --------------------------------------------------------------------------- #
# changing
# --------------------------------------------------------------------------- #


def _ids(value):
	if isinstance(value, str):
		try:
			value = json.loads(value)
		except ValueError:
			value = [v for v in value.split(",") if v.strip()]
	return [str(v).strip() for v in (value or []) if str(v).strip()]


def _names(install_ids):
	names = _ids(install_ids)
	if not names:
		frappe.throw(_("Pick a device."), frappe.ValidationError)
	known = set(frappe.get_all(INSTALL, filters={"name": ["in", names]}, pluck="name", limit_page_length=0))
	if known != set(names):
		frappe.throw(_("Unknown device."), frappe.DoesNotExistError)
	return names


def _require_ready():
	if not _has_links():
		frappe.throw(_("Run a migrate on this site first: the device links are not set up yet."), frappe.ValidationError)


def _new_group():
	return "DEV-" + frappe.generate_hash(length=8).upper()


def ensure_group(names):
	"""One group id for these installs: the one they already carry (the one linked to an asset, when they carry two), or a new one."""
	have = [g for g in frappe.get_all(INSTALL, filters={"name": ["in", names], "device_group": ["!=", ""]}, pluck="device_group", limit_page_length=0) if g]
	distinct = sorted(set(have))
	if len(distinct) > 1:
		linked = frappe.get_all(ASSET, filters={"custom_device_id": ["in", distinct]}, pluck="custom_device_id", limit_page_length=0)
		if len(set(linked)) > 1:
			frappe.throw(_("Both devices are linked to an asset. Unlink one of them first."), frappe.ValidationError)
		chosen = linked[0] if linked else distinct[0]
	else:
		chosen = distinct[0] if distinct else _new_group()
	for g in distinct:
		if g != chosen:
			frappe.db.sql("UPDATE `tabMobile App Install` SET device_group = %s WHERE device_group = %s", (chosen, g))
	for n in names:
		frappe.db.set_value(INSTALL, n, "device_group", chosen, update_modified=False)
	return chosen


def _everyone(names):
	"""The installs with these names plus every install sharing their group, so a change reaches the whole device."""
	groups = [g for g in frappe.get_all(INSTALL, filters={"name": ["in", names]}, pluck="device_group", limit_page_length=0) if g]
	more = frappe.get_all(INSTALL, filters={"device_group": ["in", groups]}, pluck="name", limit_page_length=0) if groups else []
	return sorted(set(names) | set(more))


@frappe.whitelist(methods=["POST"])
def link_asset(install_ids, asset):
	"""Make this device that asset: one device to one asset, so a device or asset linked before is let go."""
	it._require_it()
	_require_ready()
	names = _names(install_ids)
	if not frappe.db.exists(ASSET, asset):
		frappe.throw(_("Unknown asset."), frappe.DoesNotExistError)
	group = ensure_group(names)
	current = frappe.db.get_value(ASSET, asset, "custom_device_id")
	if current and current != group:
		frappe.throw(_("{0} is already linked to another device. Unlink it there first.").format(asset), frappe.ValidationError)
	for other in frappe.get_all(ASSET, filters={"custom_device_id": group, "name": ["!=", asset]}, pluck="name", limit_page_length=0):
		frappe.db.set_value(ASSET, other, "custom_device_id", "", update_modified=False)
	frappe.db.set_value(ASSET, asset, "custom_device_id", group, update_modified=False)
	return {"group": group, "asset": asset}


@frappe.whitelist(methods=["POST"])
def unlink_asset(install_ids):
	it._require_it()
	_require_ready()
	names = _everyone(_names(install_ids))
	groups = {g for g in frappe.get_all(INSTALL, filters={"name": ["in", names]}, pluck="device_group", limit_page_length=0) if g}
	for a in frappe.get_all(ASSET, filters={"custom_device_id": ["in", list(groups)]}, pluck="name", limit_page_length=0) if groups else []:
		frappe.db.set_value(ASSET, a, "custom_device_id", "", update_modified=False)
	return {"ok": 1}


@frappe.whitelist(methods=["POST"])
def link_custodian(install_ids, employee):
	"""The person who has this device, for a device that is not an asset (an asset has its own custodian)."""
	it._require_it()
	_require_ready()
	names = _everyone(_names(install_ids))
	if not frappe.db.exists("Employee", employee):
		frappe.throw(_("Unknown employee."), frappe.DoesNotExistError)
	for n in names:
		frappe.db.set_value(INSTALL, n, "custodian", employee, update_modified=False)
	return {"employee": employee}


@frappe.whitelist(methods=["POST"])
def unlink_custodian(install_ids):
	it._require_it()
	_require_ready()
	for n in _everyone(_names(install_ids)):
		frappe.db.set_value(INSTALL, n, "custodian", "", update_modified=False)
	return {"ok": 1}


@frappe.whitelist(methods=["POST"])
def merge_devices(install_ids, into_ids):
	"""Say these installs and those are one device. Both sides share a group id from then on, and so does the asset
	(if either side has one). Two different custodians: the target's wins."""
	it._require_it()
	_require_ready()
	names = _everyone(_names(install_ids))
	target = _everyone(_names(into_ids))
	if set(names) & set(target):
		frappe.throw(_("That is the same device."), frappe.ValidationError)
	everyone = sorted(set(names) | set(target))
	group = ensure_group(everyone)
	rows = frappe.get_all(INSTALL, filters={"name": ["in", everyone]}, fields=["name", "custodian"], limit_page_length=0)
	mine = {r.name: r.custodian for r in rows}
	keep = next((mine[n] for n in target if mine.get(n)), "") or next((c for c in mine.values() if c), "")
	if keep:
		for n in everyone:
			frappe.db.set_value(INSTALL, n, "custodian", keep, update_modified=False)
	return {"group": group, "installs": len(everyone)}


@frappe.whitelist(methods=["POST"])
def split_device(install_ids):
	"""Take these installs out of a merged device. They stand on their own again (by their own device key)."""
	it._require_it()
	_require_ready()
	names = _names(install_ids)
	for n in names:
		frappe.db.set_value(INSTALL, n, {"device_group": "", "custodian": ""}, update_modified=False)
	return {"ok": 1}
