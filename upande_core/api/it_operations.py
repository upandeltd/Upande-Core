# Copyright (c) 2026, Upande and contributors
# For license information, please see license.txt
#
# IT — System Activity & Monitor Config API
# Ported from Frappe Server Scripts (API type) into version-controlled
# whitelisted methods. Each function preserves the original request/response
# contract (frappe.form_dict / frappe.request / frappe.response["message"]).

import frappe
import json  # noqa: F401  (used by several ported handlers)


@frappe.whitelist()
def getItOperationsData():
    try:
        today = frappe.utils.today()
        yesterday = frappe.utils.add_days(today, -1)
        seven_start = frappe.utils.add_days(today, -6) + " 00:00:00"   # 7-day window incl today (for spark)
        avg_start = frappe.utils.add_days(today, -7) + " 00:00:00"     # for daily series back to day-7
        today_start = today + " 00:00:00"
        now_dt = frappe.utils.now_datetime()
        now_time = frappe.utils.nowtime()                 # "HH:MM:SS" clock time now
        yst_start = yesterday + " 00:00:00"
        yst_end = yesterday + " 23:59:59"
        yst_sametime = yesterday + " " + now_time         # yesterday up to the same clock time

        ALLOWED_OPS = ["=", "!=", ">", "<", ">=", "<=", "like", "not like", "in", "not in"]

        configs = frappe.get_all(
            "Monitored Doctype",
            filters={"enabled": 1},
            fields=["name", "document_type", "label", "category", "date_field", "filters_json", "sort_order"],
            order_by="sort_order asc, category asc, label asc",
            limit_page_length=0,
        )

        items = []
        hourly_total = [0] * 24
        hourly_yesterday = [0] * 24
        user_totals = {}
        cat_totals = {}
        grand_today = 0
        grand_yesterday = 0
        grand_avg = 0.0
        grand_yst_same = 0

        for cfg in configs:
            dt = cfg.get("document_type")
            if not dt or not frappe.db.exists("DocType", dt):
                continue

            date_field = cfg.get("date_field") or "creation"
            meta = frappe.get_meta(dt)
            valid_cols = set(f.fieldname for f in meta.fields)
            valid_cols = valid_cols | {"creation", "modified", "owner", "modified_by", "name", "docstatus", "idx"}
            if date_field not in valid_cols:
                date_field = "creation"

            table = "`tab" + dt + "`"

            # ---- build validated, parameterized filter WHERE ----
            filt_parts = []
            filt_params = []
            raw = cfg.get("filters_json")
            parsed = []
            if raw:
                try:
                    parsed = json.loads(raw)
                except Exception:
                    parsed = []
            for f in parsed:
                if not isinstance(f, (list, tuple)) or len(f) < 3:
                    continue
                if len(f) >= 4:
                    field = f[1]; op = f[2]; val = f[3]
                else:
                    field = f[0]; op = f[1]; val = f[2]
                if field not in valid_cols:
                    continue
                op = str(op).lower()
                if op not in ALLOWED_OPS:
                    continue
                col = "`" + field + "`"
                if op in ("in", "not in"):
                    vals = val if isinstance(val, (list, tuple)) else [val]
                    if not vals:
                        continue
                    marks = ", ".join(["%s"] * len(vals))
                    filt_parts.append(col + " " + op + " (" + marks + ")")
                    for v in vals:
                        filt_params.append(v)
                else:
                    filt_parts.append(col + " " + op + " %s")
                    filt_params.append(val)
            filt_where = "".join(" AND " + p for p in filt_parts)

            # Human-readable filter summary (distinguishes multiple monitors of the
            # same doctype, e.g. "stock_entry_type = Harvesting").
            summ_parts = []
            for f in parsed:
                if isinstance(f, (list, tuple)) and len(f) >= 3:
                    if len(f) >= 4:
                        sfld = f[1]; sop = f[2]; sval = f[3]
                    else:
                        sfld = f[0]; sop = f[1]; sval = f[2]
                    if isinstance(sval, (list, tuple)):
                        sval = ", ".join(str(x) for x in sval)
                    summ_parts.append(str(sfld) + " " + str(sop) + " " + str(sval))
            filter_summary = " · ".join(summ_parts)

            dcol = "`" + date_field + "`"

            # ---- Q1: daily series over the last 8 days ----
            by_day = {}
            try:
                rows = frappe.db.sql(
                    "SELECT DATE(" + dcol + ") d, COUNT(*) c FROM " + table +
                    " WHERE " + dcol + " >= %s" + filt_where + " GROUP BY DATE(" + dcol + ")",
                    tuple([avg_start] + filt_params),
                )
                for r in rows:
                    by_day[str(r[0])[:10]] = r[1] or 0
            except Exception:
                by_day = {}

            today_count = by_day.get(today, 0)
            yesterday_count = by_day.get(yesterday, 0)
            avg_sum = 0
            for i in range(1, 8):
                avg_sum = avg_sum + by_day.get(frappe.utils.add_days(today, -i), 0)
            avg7 = avg_sum / 7.0
            spark = []
            for i in range(6, -1, -1):
                spark.append(by_day.get(frappe.utils.add_days(today, -i), 0))

            # ---- Q2: today detail (hour + owner) ----
            try:
                trows = frappe.db.sql(
                    "SELECT owner, HOUR(" + dcol + ") h, COUNT(*) c FROM " + table +
                    " WHERE " + dcol + " >= %s" + filt_where + " GROUP BY owner, HOUR(" + dcol + ")",
                    tuple([today_start] + filt_params),
                )
            except Exception:
                trows = []
            for r in trows:
                owner = r[0] or "Unknown"
                hr = int(r[1] or 0)
                cnt = r[2] or 0
                if 0 <= hr <= 23:
                    hourly_total[hr] = hourly_total[hr] + cnt
                user_totals[owner] = user_totals.get(owner, 0) + cnt

            # ---- Q3: last activity ----
            last_activity = None
            minutes_since = None
            try:
                mrow = frappe.db.sql(
                    "SELECT MAX(" + dcol + ") FROM " + table + " WHERE 1=1" + filt_where,
                    tuple(filt_params),
                )
                if mrow and mrow[0][0]:
                    last_activity = str(mrow[0][0])
                    delta = frappe.utils.time_diff_in_seconds(now_dt, mrow[0][0])
                    minutes_since = int(delta / 60) if delta and delta > 0 else 0
            except Exception:
                last_activity = None

            # ---- Q5: yesterday's full-day hourly (for the today-vs-yesterday chart) ----
            try:
                yhrows = frappe.db.sql(
                    "SELECT HOUR(" + dcol + ") h, COUNT(*) c FROM " + table +
                    " WHERE " + dcol + " >= %s AND " + dcol + " <= %s" + filt_where +
                    " GROUP BY HOUR(" + dcol + ")",
                    tuple([yst_start, yst_end] + filt_params),
                )
                for r in yhrows:
                    yhr = int(r[0] or 0)
                    if 0 <= yhr <= 23:
                        hourly_yesterday[yhr] = hourly_yesterday[yhr] + (r[1] or 0)
            except Exception:
                pass

            # ---- Q4: same time yesterday (yesterday 00:00 -> same clock time as now) ----
            yst_same = 0
            try:
                srow = frappe.db.sql(
                    "SELECT COUNT(*) FROM " + table + " WHERE " + dcol + " >= %s AND " + dcol + " <= %s" + filt_where,
                    tuple([yst_start, yst_sametime] + filt_params),
                )
                if srow and srow[0][0]:
                    yst_same = srow[0][0]
            except Exception:
                yst_same = 0

            cat = cfg.get("category") or "Other"
            grand_today = grand_today + today_count
            grand_yesterday = grand_yesterday + yesterday_count
            grand_avg = grand_avg + avg7
            grand_yst_same = grand_yst_same + yst_same
            cat_totals[cat] = cat_totals.get(cat, 0) + today_count

            pct_y = None
            if yesterday_count:
                pct_y = round((today_count - yesterday_count) * 100.0 / yesterday_count, 1)
            pct_a = None
            if avg7:
                pct_a = round((today_count - avg7) * 100.0 / avg7, 1)
            pct_st = None
            if yst_same:
                pct_st = round((today_count - yst_same) * 100.0 / yst_same, 1)

            items.append({
                "name": cfg.get("name"),
                "doctype": dt,
                "label": cfg.get("label") or dt,
                "filter_summary": filter_summary,
                "category": cat,
                "today": today_count,
                "yesterday": yesterday_count,
                "yesterday_sametime": yst_same,
                "avg7": round(avg7, 1),
                "pct_vs_yesterday": pct_y,
                "pct_vs_avg": pct_a,
                "pct_vs_sametime": pct_st,
                "spark": spark,
                "last_activity": last_activity,
                "minutes_since": minutes_since,
            })

        top_users = sorted(
            [{"user": u, "count": c} for u, c in user_totals.items()],
            key=lambda x: x["count"], reverse=True,
        )[:15]

        g_pct_y = None
        if grand_yesterday:
            g_pct_y = round((grand_today - grand_yesterday) * 100.0 / grand_yesterday, 1)
        g_pct_a = None
        if grand_avg:
            g_pct_a = round((grand_today - grand_avg) * 100.0 / grand_avg, 1)
        g_pct_st = None
        if grand_yst_same:
            g_pct_st = round((grand_today - grand_yst_same) * 100.0 / grand_yst_same, 1)

        frappe.response["message"] = {
            "generated_at": str(now_dt),
            "today": today,
            "now_time": now_time,
            "totals": {
                "today": grand_today,
                "yesterday": grand_yesterday,
                "yesterday_sametime": grand_yst_same,
                "avg7": round(grand_avg, 1),
                "pct_vs_yesterday": g_pct_y,
                "pct_vs_avg": g_pct_a,
                "pct_vs_sametime": g_pct_st,
                "active_users": len([1 for u, c in user_totals.items() if c > 0]),
                "monitored": len(items),
            },
            "hourly_today": hourly_total,
            "hourly_yesterday": hourly_yesterday,
            "by_category": [{"category": k, "today": v} for k, v in sorted(cat_totals.items())],
            "top_users": top_users,
            "items": items,
        }
    except Exception as e:
        frappe.response["message"] = {"error": str(e)}


@frappe.whitelist()
def itCategoryList():
    try:
        rows = frappe.get_all("Monitored Category", fields=["category_name"], order_by="category_name asc", limit_page_length=0)
        frappe.response["message"] = {"data": [r["category_name"] for r in rows if r["category_name"]]}
    except Exception as e:
        frappe.response["message"] = {"error": str(e), "data": []}


@frappe.whitelist()
def itMonitorDelete():
    try:
        name = frappe.form_dict.get("name")
        if name and frappe.db.exists("Monitored Doctype", name):
            frappe.delete_doc("Monitored Doctype", name, ignore_permissions=True, force=True)
            frappe.db.commit()
            frappe.response["message"] = {"ok": True}
        else:
            frappe.response["message"] = {"error": "Not found"}
    except Exception as e:
        frappe.response["message"] = {"error": str(e)}


@frappe.whitelist()
def itMonitorDoctypeFields():
    try:
        dt = frappe.form_dict.get("doctype")
        if not dt or not frappe.db.exists("DocType", dt):
            frappe.response["message"] = {"error": "Invalid doctype", "date_fields": [], "fields": []}
        else:
            meta = frappe.get_meta(dt)
            date_fields = ["creation", "modified"]
            fields = [{"fieldname": "owner", "label": "Created By (owner)", "fieldtype": "Link", "options": "User"},
                      {"fieldname": "docstatus", "label": "Docstatus (0/1/2)", "fieldtype": "Int", "options": None}]
            keep = ("Data", "Select", "Link", "Check", "Int", "Float", "Currency", "Date", "Datetime", "Small Text")
            for f in meta.fields:
                if f.fieldtype in ("Date", "Datetime"):
                    date_fields.append(f.fieldname)
                if f.fieldtype in keep:
                    fields.append({"fieldname": f.fieldname, "label": f.label or f.fieldname, "fieldtype": f.fieldtype, "options": f.options})
            frappe.response["message"] = {"date_fields": date_fields, "fields": fields}
    except Exception as e:
        frappe.response["message"] = {"error": str(e), "date_fields": [], "fields": []}


@frappe.whitelist()
def itMonitorDoctypeSearch():
    try:
        q = frappe.form_dict.get("q") or ""
        rows = frappe.get_all(
            "DocType",
            filters={"name": ["like", "%" + q + "%"], "istable": 0, "issingle": 0},
            fields=["name"],
            order_by="name asc",
            limit_page_length=25,
        )
        frappe.response["message"] = {"data": [r["name"] for r in rows]}
    except Exception as e:
        frappe.response["message"] = {"error": str(e), "data": []}


@frappe.whitelist()
def itMonitorFieldValues():
    try:
        dt = frappe.form_dict.get("doctype")
        fn = frappe.form_dict.get("fieldname")
        if not dt or not fn or not frappe.db.exists("DocType", dt):
            frappe.response["message"] = {"values": []}
        else:
            vals = []
            if fn == "docstatus":
                vals = ["0", "1", "2"]
            elif fn in ("owner", "modified_by"):
                rows = frappe.db.sql("SELECT DISTINCT `" + fn + "` FROM `tab" + dt + "` WHERE `" + fn + "` IS NOT NULL ORDER BY `" + fn + "` LIMIT 50")
                vals = [r[0] for r in rows if r[0]]
            else:
                meta = frappe.get_meta(dt)
                fmap = {}
                for f in meta.fields:
                    fmap[f.fieldname] = f
                if fn in fmap:
                    f = fmap[fn]
                    if f.fieldtype == "Check":
                        vals = ["0", "1"]
                    elif f.fieldtype == "Select" and f.options:
                        vals = [o for o in f.options.split("\n") if o.strip() != ""]
                    else:
                        rows = frappe.db.sql("SELECT DISTINCT `" + fn + "` FROM `tab" + dt + "` WHERE `" + fn + "` IS NOT NULL AND `" + fn + "` != '' ORDER BY `" + fn + "` LIMIT 50")
                        vals = [str(r[0]) for r in rows if r[0] is not None]
            frappe.response["message"] = {"values": vals}
    except Exception as e:
        frappe.response["message"] = {"error": str(e), "values": []}


@frappe.whitelist()
def itMonitorList():
    try:
        rows = frappe.get_all(
            "Monitored Doctype",
            fields=["name", "document_type", "label", "category", "date_field", "filters_json", "enabled", "sort_order"],
            order_by="sort_order asc, category asc, label asc",
            limit_page_length=0,
        )
        frappe.response["message"] = {"data": rows}
    except Exception as e:
        frappe.response["message"] = {"error": str(e), "data": []}


@frappe.whitelist()
def itMonitorSave():
    try:
        data = frappe.request.get_json() or {}
        dt = data.get("document_type")
        err = None
        if not dt or not frappe.db.exists("DocType", dt):
            err = "Invalid or missing Document Type"
        filters_json = data.get("filters_json") or ""
        if not err and filters_json:
            try:
                parsed = json.loads(filters_json)
                if not isinstance(parsed, list):
                    err = "Filters must be a JSON array like [[\"docstatus\",\"=\",1]]"
            except Exception:
                err = "Filters is not valid JSON"
        if err:
            frappe.response["message"] = {"error": err}
        else:
            date_field = data.get("date_field") or "creation"
            meta = frappe.get_meta(dt)
            valid = set(f.fieldname for f in meta.fields) | {"creation", "modified", "owner", "modified_by", "name"}
            if date_field not in valid:
                date_field = "creation"
            # Edit an existing monitor by its name; otherwise create a NEW one so a
            # single doctype can be tracked multiple times with different filters.
            rec_name = data.get("name")
            if rec_name and frappe.db.exists("Monitored Doctype", rec_name):
                doc = frappe.get_doc("Monitored Doctype", rec_name)
            else:
                doc = frappe.new_doc("Monitored Doctype")
            doc.document_type = dt
            cat = (data.get("category") or "Other").strip() or "Other"
            # Persist the category in the Monitored Category store so new categories
            # are remembered (the admin dropdown reads from there, not a hardcoded list).
            if not frappe.db.exists("Monitored Category", cat):
                cdoc = frappe.new_doc("Monitored Category")
                cdoc.category_name = cat
                cdoc.flags.ignore_permissions = True
                cdoc.insert()
            doc.label = data.get("label") or dt
            doc.category = cat
            doc.date_field = date_field
            doc.filters_json = filters_json
            doc.enabled = 1 if data.get("enabled") else 0
            so = data.get("sort_order")
            doc.sort_order = int(so) if (so is not None and so != "") else 0
            doc.flags.ignore_permissions = True
            doc.save()
            frappe.db.commit()
            frappe.response["message"] = {"ok": True, "name": doc.name}
    except Exception as e:
        frappe.response["message"] = {"error": str(e)}
