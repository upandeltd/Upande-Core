# Copyright (c) 2026, Upande and contributors
# For license information, please see license.txt
#
# Unit tests for the IT dashboard's pure helpers (buckets, waiting, wording, roles). No site needed:
#   ../../env/bin/python -W ignore -m unittest upande_core.tests.test_it_mobile

import unittest
from datetime import datetime

from upande_core.it_dashboard import devicelink as dl
from upande_core.it_dashboard import mobile as it

NOW = datetime(2026, 11, 5, 12, 0, 0)


class TestBuckets(unittest.TestCase):
	def test_behind_ota_is_forgot(self):
		self.assertEqual(it.person_bucket("behind_ota"), "forgot")

	def test_needs_apk_is_cant_update(self):
		self.assertEqual(it.person_bucket("needs_apk"), "cant_update")

	def test_current_ahead_dormant_unknown(self):
		self.assertEqual(it.person_bucket("current"), "current")
		self.assertEqual(it.person_bucket("ahead"), "current")
		self.assertEqual(it.person_bucket("dormant"), "away")
		self.assertEqual(it.person_bucket("unknown"), "unknown")


class TestWaiting(unittest.TestCase):
	def test_person_wrote_last(self):
		self.assertEqual(it.wait_state("Open", "2026-11-04 10:00:00", "2026-11-03 10:00:00", "2026-11-01 00:00:00"), (True, "2026-11-04 10:00:00"))

	def test_staff_answered_last(self):
		self.assertEqual(it.wait_state("Replied", "2026-11-03 10:00:00", "2026-11-04 10:00:00", "2026-11-01 00:00:00"), (False, None))

	def test_never_answered_waits_since_creation(self):
		self.assertEqual(it.wait_state("Open", None, None, "2026-11-01 00:00:00"), (True, "2026-11-01 00:00:00"))

	def test_resolved_never_waits(self):
		self.assertEqual(it.wait_state("Resolved", "2026-11-04 10:00:00", None, "2026-11-01"), (False, None))


class TestWording(unittest.TestCase):
	def test_reminder_text(self):
		title, text = it.reminder_text("Sales", "forgot", "2.1.0")
		self.assertIn("Sales", title)
		self.assertIn("2.1.0", text)
		self.assertIn("reopen", text)
		self.assertIn("install", it.reminder_text("Sales", "cant_update", "2.1.0")[1])

	def test_cooldown(self):
		self.assertTrue(it.reminder_allowed(None, NOW))
		self.assertFalse(it.reminder_allowed("2026-11-05 03:00:00", NOW))
		self.assertTrue(it.reminder_allowed("2026-11-04 03:00:00", NOW))
		self.assertTrue(it.reminder_allowed("2026-11-01 03:00:00", NOW, 72))

	def test_days_between(self):
		self.assertEqual(it.days_between("2026-11-01 00:00:00", NOW), 4)
		self.assertIsNone(it.days_between(None, NOW))

	def test_problem_view_keeps_event_ids_for_developers_only(self):
		row = {"name": "x", "app": "A", "kind": "crash", "users_affected": 3, "title": "TypeError", "culprit": "f.js", "last_event": "e1"}
		plain = it.problem_view(row, False)
		self.assertNotIn("developer", plain)
		self.assertEqual(plain["title"], "TypeError")
		self.assertEqual(plain["kind"], "crash")
		self.assertEqual(plain["people"], 3)
		self.assertEqual(it.problem_view(row, True)["developer"]["last_event"], "e1")


class TestRoles(unittest.TestCase):
	def test_access(self):
		self.assertTrue(it.is_developer(["System Manager"]))
		self.assertFalse(it.is_developer(["IT Support"]))



class TestOverviewHelpers(unittest.TestCase):
	def test_android_versions(self):
		rows = [
			{"platform": "android", "os_major": 14}, {"platform": "Android", "os_version": "Android 14"},
			{"platform": "android", "os_major": 9}, {"platform": "ios", "os_major": 17}, {"platform": "android"},
		]
		out = it.android_versions(rows, 10)
		self.assertEqual([(r["label"], r["count"], r["old"]) for r in out], [("Android 14", 2, False), ("Android 9", 1, True)])

	def test_app_mix(self):
		out = it._app_mix([{"app": "A", "bucket": "current"}, {"app": "A", "bucket": "forgot"}, {"app": "A", "bucket": "cant_update"}, {"app": "B", "bucket": "away"}, {"app": "B", "bucket": "unknown"}])
		self.assertEqual(out["A"], {"current": 1, "behind": 2, "away": 0, "unknown": 0})
		self.assertEqual(out["B"], {"current": 0, "behind": 0, "away": 1, "unknown": 1})


if __name__ == "__main__":
	unittest.main()


class TestScrub(unittest.TestCase):
	def test_github_addresses_are_removed(self):
		for raw in (
			"GET /repos/mark-judah/upande-production/releases → Network request failed",
			"fetch https://api.github.com/repos/mark-judah/upande-production/releases?per_page=100 failed",
			"see https://github.com/mark-judah/x/releases",
		):
			out = it.scrub(raw)
			self.assertNotIn("mark-judah", out)
			self.assertNotIn("github", out.lower())
		self.assertEqual(it.scrub(None), None)
		self.assertEqual(it.scrub("Network request failed"), "Network request failed")

	def test_github_headers_are_removed(self):
		out = it.scrub('{"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}')
		self.assertNotIn("github", out.lower())


class TestUniqueDevices(unittest.TestCase):
	def _row(self, i, app, android_id, seen):
		return {"id": i, "app": app, "android_id": android_id, "last_seen": seen}

	def test_installs_sharing_an_android_id_fold_into_the_latest(self):
		rows = [
			self._row("a", "Quality", "ABC123", "2026-11-01"),
			self._row("b", "Packhouse", "abc123", "2026-11-05"),
			self._row("c", "Security", "", "2026-11-02"),
			self._row("d", "Security", "", "2026-11-03"),
			self._row("e", "Quality", "XYZ", "2026-11-04"),
		]
		out = it.unique_by_android_id(rows)
		self.assertEqual(sorted(r["id"] for r in out), ["b", "c", "d", "e"])
		by = {r["id"]: r for r in out}
		self.assertEqual(by["b"]["installs"], 2)
		self.assertEqual(sorted(by["b"]["apps"]), ["Packhouse", "Quality"])
		self.assertEqual(by["c"]["installs"], 1)


class TestErrorLogFilters(unittest.TestCase):
	def test_payload_is_hidden_unless_the_reader_says_otherwise(self):
		self.assertEqual(it.hidden_terms(None), ["payload"])
		self.assertEqual(it.hidden_terms("-"), [])
		self.assertEqual(it.hidden_terms("Payload, timeout ,payload"), ["payload", "timeout"])

	def test_clauses_and_params_line_up(self):
		where, hidden, params = it._log_where("Quality", "a@b.c", "error", "boom", ["payload", "x"])
		self.assertEqual(len(params), 1 + 1 + 1 + 3 + 3 * 2)
		self.assertEqual(sum(c.count("%s") for c in where + hidden), len(params))


class TestDeviceTree(unittest.TestCase):
	"""Model -> device -> people, and which installs are one physical device."""

	@staticmethod
	def _install(id_, android_id, app, user, seen, device="Samsung A05", flags=(), key="", group="", test=False, custodian=""):
		return {
			"id": id_, "app": app, "owner": user, "owner_name": user, "device": device, "platform": "android",
			"os_version": "14", "app_version": "1.0", "status": "current", "flags": list(flags), "state": "Active",
			"notes": "", "last_seen": seen, "battery": None, "storage_free_gb": None, "network": "", "serial_number": "",
			"android_id": android_id, "mac_address": "", "local_ip": "", "build_number": "", "ip_seen": "",
			"device_key": key, "device_group": group, "test_build": test, "custodian_direct": custodian,
			"users": [{"user": user, "name": user, "first_seen": "2026-10-01 08:00:00", "last_seen": seen, "version": "1.0", "logins": 2, "app": app}],
		}

	def _tree(self, items, **kw):
		from unittest import mock

		def links(devices):
			for d in devices:
				d["asset"], d["custodian"] = None, None
			return devices

		with mock.patch.object(it, "_require_it"), mock.patch.object(dl, "_has_links", return_value=True), mock.patch.object(dl, "_links", side_effect=links), mock.patch.object(it, "is_developer", return_value=False), mock.patch.object(it, "_device_items", return_value=items):
			return dl.device_tree(**kw)

	def test_one_android_id_is_one_device_with_everyone_who_used_it(self):
		out = self._tree([
			self._install("a", "AAA", "Packhouse", "ann@x.com", "2026-11-05 10:00:00"),
			self._install("b", "aaa", "Quality", "bob@x.com", "2026-11-06 10:00:00"),
			self._install("c", "BBB", "Packhouse", "ann@x.com", "2026-11-04 10:00:00", device="Honeywell EDA51"),
		])
		self.assertEqual({k: out["totals"][k] for k in ("devices", "models", "people", "installs", "no_id")}, {"devices": 2, "models": 2, "people": 2, "installs": 3, "no_id": 0})
		samsung = next(m for m in out["models"] if m["name"] == "Samsung A05")
		self.assertEqual(len(samsung["devices"]), 1)
		dev = samsung["devices"][0]
		self.assertEqual(dev["installs"], 2)
		self.assertEqual(sorted(dev["apps"]), ["Packhouse", "Quality"])
		self.assertEqual([p["user"] for p in dev["people"]], ["bob@x.com", "ann@x.com"])  # newest use first
		self.assertEqual(sorted(dev["install_ids"]), ["a", "b"])

	def test_the_device_key_joins_installs_when_there_is_no_android_id(self):
		out = self._tree([self._install("a", "", "Packhouse", "ann@x.com", "2026-11-05 10:00:00", key="K1"), self._install("b", "", "Quality", "ann@x.com", "2026-11-05 11:00:00", key="K1"), self._install("c", "", "Quality", "bob@x.com", "2026-11-05 11:00:00", key="K2")])
		self.assertEqual(out["totals"]["devices"], 2)
		self.assertEqual(out["totals"]["no_id"], 0)  # a key is an id

	def test_an_install_with_no_id_at_all_counts_alone(self):
		out = self._tree([self._install("a", "", "Packhouse", "ann@x.com", "2026-11-05 10:00:00"), self._install("b", "", "Packhouse", "bob@x.com", "2026-11-05 11:00:00")])
		self.assertEqual(out["totals"]["devices"], 2)
		self.assertEqual(out["totals"]["no_id"], 2)

	def test_a_merged_group_joins_installs_with_different_keys(self):
		out = self._tree([self._install("a", "", "Packhouse", "ann@x.com", "2026-11-05 10:00:00", key="K1", group="DEV-1"), self._install("b", "", "Security", "ann@x.com", "2026-11-06 10:00:00", key="K2", group="DEV-1")])
		self.assertEqual(out["totals"]["devices"], 1)
		dev = out["models"][0]["devices"][0]
		self.assertTrue(dev["merged"])
		self.assertEqual(len(dev["ids"]), 2)
		self.assertEqual(dev["device_id"], "DEV-1")

	def test_test_builds_are_left_out_unless_asked_for(self):
		items = [self._install("a", "", "Packhouse", "ann@x.com", "2026-11-05 10:00:00", key="K1"), self._install("b", "", "Packhouse", "ann@x.com", "2026-11-05 10:30:00", key="K2", test=True)]
		self.assertEqual(self._tree(items)["totals"]["devices"], 1)
		withtests = self._tree(items, tests=1)
		self.assertEqual(withtests["totals"]["devices"], 2)
		self.assertEqual(withtests["totals"]["test"], 1)

	def test_health_filter_keeps_the_health_counts(self):
		items = [self._install("a", "AAA", "P", "ann@x.com", "2026-11-05 10:00:00", flags=["low_battery"]), self._install("b", "BBB", "P", "bob@x.com", "2026-11-05 10:00:00")]
		out = self._tree(items, health="low_battery")
		self.assertEqual(out["totals"]["devices"], 1)
		self.assertEqual(out["health"]["low_battery"], 1)
		self.assertEqual(self._tree(items, health="offline")["totals"]["devices"], 0)
