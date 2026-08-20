# Copyright (c) 2026, Upande and contributors
# For license information, please see license.txt
#
# IT Dashboard — Helpdesk, Assets, Access, Audit, Shifts, System Health API
# Ported from Frappe Server Scripts (API type) into version-controlled
# whitelisted methods. Each function preserves the original request/response
# contract (frappe.form_dict / frappe.request / frappe.response["message"]).

import frappe
import json  # noqa: F401  (used by several ported handlers)


@frappe.whitelist()
def assignShift():
    shift_type = frappe.form_dict.get("shift_type")
    start_date = frappe.form_dict.get("start_date") or frappe.utils.today()

    # Accept either a single ?employee= or a JSON list ?employees=[...]
    employees_raw = frappe.form_dict.get("employees")
    if employees_raw:
        try:
            emp_list = json.loads(employees_raw)
        except Exception:
            emp_list = [e.strip() for e in str(employees_raw).split(",") if e.strip()]
    else:
        single = frappe.form_dict.get("employee")
        emp_list = [single] if single else []

    if not emp_list or not shift_type:
        frappe.throw("employee(s) and shift_type are required")

    created = []
    replaced_total = 0
    errors = []

    for employee in emp_list:
        try:
            emp = frappe.db.get_value("Employee", employee, ["company", "employee_name", "status"], as_dict=True)
            if not emp:
                errors.append(str(employee) + ": not found")
                continue
            if emp.status != "Active":
                errors.append(str(emp.employee_name or employee) + ": not active")
                continue

            # Replace any existing active assignment (works for assign + change).
            existing = frappe.get_all("Shift Assignment",
                filters={"employee": employee, "status": "Active", "docstatus": 1}, pluck="name")
            for nm in existing:
                frappe.get_doc("Shift Assignment", nm).cancel()
            replaced_total += len(existing)

            doc = frappe.get_doc({
                "doctype":    "Shift Assignment",
                "employee":   employee,
                "shift_type": shift_type,
                "company":    emp.company,
                "start_date": start_date,
                "status":     "Active",
            })
            doc.insert()
            doc.submit()
            created.append(doc.name)
        except Exception as e:
            errors.append(str(employee) + ": " + str(e))

    # If nothing succeeded and everything errored, surface it as a failure.
    if not created and errors:
        frappe.throw("<br>".join(errors))

    frappe.response["message"] = {
        "created":  len(created),
        "replaced": replaced_total,
        "errors":   errors,
    }


@frappe.whitelist()
def auditTrail():

    if frappe.request.method == "GET":
        try:
            start_date_raw = frappe.request.args.get("start_date")
            end_date_raw   = frappe.request.args.get("end_date")

            if not start_date_raw or not end_date_raw:
                frappe.throw("Missing required query parameters: 'start_date' and 'end_date'")

            try:
                start_date = frappe.utils.getdate(start_date_raw)
                end_date   = frappe.utils.getdate(end_date_raw)
                if end_date < start_date:
                    frappe.throw(f"End date ({end_date}) cannot be before start date ({start_date})")
            except Exception as date_error:
                frappe.throw(f"Invalid date format: {str(date_error)}")

            start_dt = str(start_date) + " 00:00:00"
            end_dt   = str(end_date)   + " 23:59:59"

            user         = frappe.request.args.get("user")
            doctype      = frappe.request.args.get("doctype")
            operation    = frappe.request.args.get("operation")
            status       = frappe.request.args.get("status")
            summary_only = frappe.request.args.get("summary_only") in ("1", "true", "yes")
            dataset      = frappe.request.args.get("dataset")

            # ── Pagination ────────────────────────────────────────
            try:
                page = int(frappe.request.args.get("page") or 1)
            except Exception:
                page = 1
            if page < 1:
                page = 1
            try:
                page_size = int(frappe.request.args.get("page_size") or 500)
            except Exception:
                page_size = 500
            if page_size < 1:
                page_size = 500
            if page_size > 5000:
                page_size = 5000
            offset = (page - 1) * page_size

            # ════════════════════════════════════════════════════════
            # QLIK MODE — flat, fully pageable single-table datasets.
            # dataset = activity | version | version_flat | summary
            # Qlik pages until has_more == false to pull everything.
            # ════════════════════════════════════════════════════════
            if dataset in ("activity", "version", "version_flat", "summary"):

                if dataset == "activity":
                    a_filters = ""
                    a_params = {"start_dt": start_dt, "end_dt": end_dt,
                                "lim": page_size + 1, "off": offset}
                    if user:
                        a_filters += " AND al.user = %(user)s"
                        a_params["user"] = user
                    if operation:
                        a_filters += " AND al.operation = %(operation)s"
                        a_params["operation"] = operation
                    if status:
                        a_filters += " AND al.status = %(status)s"
                        a_params["status"] = status

                    rows = frappe.db.sql(f"""
                        SELECT al.name          AS activity_id,
                               al.user,
                               al.full_name,
                               al.operation,
                               al.status,
                               al.ip_address,
                               al.communication_date AS activity_date,
                               al.creation,
                               al.subject
                        FROM `tabActivity Log` al
                        WHERE al.modified >= %(start_dt)s
                          AND al.modified <= %(end_dt)s
                          AND al.user != 'Administrator'
                          AND al.user NOT LIKE '%%@upande.com'
                        {a_filters}
                        ORDER BY al.modified DESC
                        LIMIT %(lim)s OFFSET %(off)s
                    """, a_params, as_dict=True)
                    has_more = len(rows) > page_size
                    rows = rows[:page_size]
                    for r in rows:
                        r["activity_date"] = str(r["activity_date"]) if r.get("activity_date") else None
                        r["creation"] = str(r["creation"]) if r.get("creation") else None

                    data = {"records": rows, "count": len(rows),
                            "page": page, "page_size": page_size, "has_more": has_more}

                elif dataset == "summary":
                    rows = frappe.db.sql("""
                        SELECT v.owner                                     AS user,
                               COALESCE(NULLIF(u.full_name, ''), v.owner)  AS full_name,
                               v.ref_doctype                               AS doctype,
                               COUNT(*)                                    AS cnt
                        FROM `tabVersion` v
                        LEFT JOIN `tabUser` u ON u.name = v.owner
                        WHERE v.modified >= %(start_dt)s
                          AND v.modified <= %(end_dt)s
                          AND v.owner != 'Administrator'
                          AND v.owner NOT LIKE '%%@upande.com'
                          AND v.data IS NOT NULL
                          AND v.data != '{}'
                        GROUP BY v.owner, u.full_name, v.ref_doctype
                        ORDER BY cnt DESC
                    """, {"start_dt": start_dt, "end_dt": end_dt}, as_dict=True)
                    data = {"records": rows, "count": len(rows)}

                else:
                    # version / version_flat share the same base page of Version rows.
                    v_filters = ""
                    v_params = {"start_dt": start_dt, "end_dt": end_dt,
                                "lim": page_size + 1, "off": offset}
                    if user:
                        v_filters += " AND v.owner = %(vuser)s"
                        v_params["vuser"] = user
                    if doctype:
                        v_filters += " AND v.ref_doctype = %(vdoctype)s"
                        v_params["vdoctype"] = doctype

                    vrows = frappe.db.sql(f"""
                        SELECT v.name                                      AS version_id,
                               v.owner                                     AS changed_by,
                               COALESCE(NULLIF(u.full_name, ''), v.owner)  AS full_name,
                               v.creation                                  AS changed_on,
                               v.ref_doctype                               AS doctype,
                               v.docname                                   AS document,
                               v.data
                        FROM `tabVersion` v
                        LEFT JOIN `tabUser` u ON u.name = v.owner
                        WHERE v.modified >= %(start_dt)s
                          AND v.modified <= %(end_dt)s
                          AND v.owner != 'Administrator'
                          AND v.owner NOT LIKE '%%@upande.com'
                          AND v.data IS NOT NULL
                          AND v.data != '{{}}'
                        {v_filters}
                        ORDER BY v.modified DESC
                        LIMIT %(lim)s OFFSET %(off)s
                    """, v_params, as_dict=True)
                    has_more = len(vrows) > page_size
                    vrows = vrows[:page_size]

                    if dataset == "version":
                        for r in vrows:
                            r["changed_on"] = str(r["changed_on"]) if r.get("changed_on") else None
                        data = {"records": vrows, "count": len(vrows),
                                "page": page, "page_size": page_size, "has_more": has_more}
                    else:
                        # version_flat: one row per changed field -> Qlik-readable.
                        flat = []
                        for r in vrows:
                            changed_on = str(r["changed_on"]) if r.get("changed_on") else None
                            try:
                                blob = json.loads(r.get("data") or "{}")
                            except Exception:
                                blob = {}
                            base = {
                                "version_id": r.get("version_id"),
                                "changed_by": r.get("changed_by"),
                                "full_name":  r.get("full_name"),
                                "changed_on": changed_on,
                                "doctype":    r.get("doctype"),
                                "document":   r.get("document"),
                            }
                            # Field-level changes on the parent doc.
                            for ch in (blob.get("changed") or []):
                                row = dict(base)
                                row["change_type"] = "changed"
                                row["fieldname"]   = ch[0] if len(ch) > 0 else None
                                row["old_value"]   = ch[1] if len(ch) > 1 else None
                                row["new_value"]   = ch[2] if len(ch) > 2 else None
                                flat.append(row)
                            # Child-table row edits: [table_field, idx, rowname, [[f,old,new],...]]
                            for rc in (blob.get("row_changed") or []):
                                table_field = rc[0] if len(rc) > 0 else None
                                rowname     = rc[2] if len(rc) > 2 else None
                                for ch in (rc[3] if len(rc) > 3 else []):
                                    row = dict(base)
                                    row["change_type"] = "row_changed"
                                    row["child_table"] = table_field
                                    row["child_row"]   = rowname
                                    row["fieldname"]   = ch[0] if len(ch) > 0 else None
                                    row["old_value"]   = ch[1] if len(ch) > 1 else None
                                    row["new_value"]   = ch[2] if len(ch) > 2 else None
                                    flat.append(row)
                            # Added / removed child rows (record the event, no old/new).
                            for kind in ("added", "removed"):
                                for ad in (blob.get(kind) or []):
                                    row = dict(base)
                                    row["change_type"] = kind
                                    row["child_table"] = ad[0] if len(ad) > 0 else None
                                    flat.append(row)
                        data = {"records": flat, "count": len(flat),
                                "source_versions": len(vrows),
                                "page": page, "page_size": page_size, "has_more": has_more}

                frappe.response.pop("docs", None)
                frappe.response["status"] = "success"
                frappe.response["dataset"] = dataset
                frappe.response["data"] = data
                frappe.response.http_status_code = 200

            else:
                # ════════════════════════════════════════════════════
                # LEGACY MODE (unchanged) — feeds the IT dashboard.
                # ════════════════════════════════════════════════════
                activity_logs = []
                summary_rows  = []
                version_logs  = []
                has_more      = False

                if summary_only:
                    activity_filters = ""
                    activity_params = {"start_dt": start_dt, "end_dt": end_dt}
                    if user:
                        activity_filters += " AND al.user = %(user)s"
                        activity_params["user"] = user
                    if operation:
                        activity_filters += " AND al.operation = %(operation)s"
                        activity_params["operation"] = operation
                    if status:
                        activity_filters += " AND al.status = %(status)s"
                        activity_params["status"] = status

                    activity_logs = frappe.db.sql(f"""
                        SELECT al.user, al.full_name, al.operation, al.status,
                               al.ip_address, al.communication_date AS activity_date, al.subject
                        FROM `tabActivity Log` al
                        WHERE al.modified >= %(start_dt)s
                          AND al.modified <= %(end_dt)s
                          AND al.user != 'Administrator'
                          AND al.user NOT LIKE '%%@upande.com'
                        {activity_filters}
                        ORDER BY al.modified DESC
                        LIMIT 500
                    """, activity_params, as_dict=True)
                    for record in activity_logs:
                        record["activity_date"] = (
                            str(record["activity_date"]) if record.get("activity_date") else None
                        )

                    summary_rows = frappe.db.sql("""
                        SELECT v.owner                                     AS user,
                               COALESCE(NULLIF(u.full_name, ''), v.owner)  AS full_name,
                               v.ref_doctype                               AS doctype,
                               COUNT(*)                                    AS cnt
                        FROM `tabVersion` v
                        LEFT JOIN `tabUser` u ON u.name = v.owner
                        WHERE v.modified >= %(start_dt)s
                          AND v.modified <= %(end_dt)s
                          AND v.owner != 'Administrator'
                          AND v.owner NOT LIKE '%%@upande.com'
                          AND v.data IS NOT NULL
                          AND v.data != '{}'
                          AND v.data LIKE '%%"changed"%%'
                        GROUP BY v.owner, u.full_name, v.ref_doctype
                        ORDER BY cnt DESC
                    """, {"start_dt": start_dt, "end_dt": end_dt}, as_dict=True)

                else:
                    version_filters = ""
                    version_params = {"start_dt": start_dt, "end_dt": end_dt,
                                      "lim": page_size + 1, "off": offset}
                    if user:
                        version_filters += " AND v.owner = %(vuser)s"
                        version_params["vuser"] = user
                    if doctype:
                        version_filters += " AND v.ref_doctype = %(vdoctype)s"
                        version_params["vdoctype"] = doctype

                    version_logs = frappe.db.sql(f"""
                        SELECT v.owner                                     AS changed_by,
                               COALESCE(NULLIF(u.full_name, ''), v.owner)  AS full_name,
                               v.creation                                  AS changed_on,
                               v.ref_doctype                               AS doctype,
                               v.docname                                   AS document,
                               v.data
                        FROM `tabVersion` v
                        LEFT JOIN `tabUser` u ON u.name = v.owner
                        WHERE v.modified >= %(start_dt)s
                          AND v.modified <= %(end_dt)s
                          AND v.owner != 'Administrator'
                          AND v.owner NOT LIKE '%%@upande.com'
                          AND v.data IS NOT NULL
                          AND v.data != '{{}}'
                          AND v.data LIKE '%%"changed"%%'
                        {version_filters}
                        ORDER BY v.modified DESC
                        LIMIT %(lim)s OFFSET %(off)s
                    """, version_params, as_dict=True)

                    has_more = len(version_logs) > page_size
                    version_logs = version_logs[:page_size]
                    for record in version_logs:
                        record["changed_on"] = (
                            str(record["changed_on"]) if record.get("changed_on") else None
                        )

                frappe.response.pop("docs", None)
                frappe.response["status"] = "success"
                frappe.response["data"] = {
                    "activity_log": {"count": len(activity_logs), "records": activity_logs},
                    "summary":      {"count": len(summary_rows),  "records": summary_rows},
                    "version_log":  {"count": len(version_logs),  "records": version_logs,
                                     "page": page, "page_size": page_size, "has_more": has_more}
                }
                frappe.response.http_status_code = 200

        except Exception as e:
            frappe.log_error(title="Logs API Error", message=str(e))
            frappe.response["status"]  = "error"
            frappe.response["message"] = f"Failed to fetch logs: {str(e)}"
            frappe.response.http_status_code = 500

    else:
        frappe.response["status"]  = "error"
        frappe.response["message"] = "Method not allowed. Use GET."
        frappe.response.http_status_code = 405


@frappe.whitelist()
def getDeviceTelemetry():
    # Server Script (API), api_method = getDeviceTelemetry — latest row per device_id.
    # Reads via frappe.get_all (bypasses the doctype read-permission check) so an
    # IT User Admin can view telemetry without System Manager. Gated to
    # IT User Admin / System Manager.
    frappe.response["message"] = {"status": "error", "devices": []}
    try:
        my = frappe.get_all(
            "Has Role",
            filters={"parent": frappe.session.user, "parenttype": "User"},
            fields=["role"],
            limit_page_length=0,
        )
        roles = {}
        i = 0
        while i < len(my):
            roles[my[i].role] = 1
            i = i + 1
        if ("IT User Admin" not in roles) and ("System Manager" not in roles):
            frappe.response["message"] = {"status": "forbidden", "devices": []}
        else:
            rows = frappe.get_all(
                "Device Telemetry",
                fields=["device_id", "device_name", "model", "brand", "os", "os_version",
                        "app_name", "app_version", "build", "ota_update_id", "ota_channel", "battery_level",
                        "battery_state", "network_type", "cellular_generation", "is_connected",
                        "storage_free", "storage_total", "user", "user_full_name",
                        "captured_at", "creation"],
                order_by="creation desc",
                limit_page_length=2000,
            )
            seen = {}
            out = []
            j = 0
            while j < len(rows):
                r = rows[j]
                key = r.get("device_id") or str(r.get("creation"))
                if key not in seen:
                    seen[key] = 1
                    row = dict(r)
                    row["creation"] = str(r.get("creation"))
                    row["captured_at"] = str(r.get("captured_at"))
                    out = out + [row]
                j = j + 1
            frappe.response["message"] = {"status": "success", "devices": out, "count": len(out)}
    except Exception as e:
        frappe.response["message"] = {"status": "error", "message": str(e), "devices": []}


@frappe.whitelist()
def getSystemHealth():
    # Enriches the it-dashboard System Health tab with data from Frappe's
    # built-in System Health Report (frappe.get_doc computes it on load).
    try:
        d = frappe.get_doc("System Health Report").as_dict()

        def num(x):
            try:
                return round(float(x), 2)
            except Exception:
                return x

        queues = []
        for q in (d.get("queue_status") or []):
            queues.append({"queue": q.get("queue"), "pending": q.get("pending_jobs")})

        failing = []
        for j in (d.get("failing_scheduled_jobs") or []):
            failing.append({
                "job": j.get("scheduled_job_type") or j.get("name"),
                "details": j.get("details"),
            })

        top_errors = []
        for e in (d.get("top_errors") or []):
            top_errors.append({"title": e.get("title"), "occurrences": e.get("occurrences")})

        frappe.response["message"] = {
            "scheduler_status": d.get("scheduler_status"),
            "background_workers": d.get("total_background_workers"),
            "queues": queues,
            "failing_jobs": len(d.get("failing_scheduled_jobs") or []),
            "failing_jobs_list": failing,
            "total_errors": d.get("total_errors"),
            "top_errors": top_errors,
            "pending_emails": d.get("pending_emails"),
            "failed_emails": d.get("failed_emails"),
            "active_sessions": d.get("active_sessions"),
            "failed_logins": d.get("failed_logins"),
            "total_users": d.get("total_users"),
            "new_users": d.get("new_users"),
            "db_storage_mb": num(d.get("db_storage_usage")),
            "cache_memory": d.get("cache_memory_usage"),
            "public_files_mb": num(d.get("public_files_size")),
            "private_files_mb": num(d.get("private_files_size")),
            "onsite_backups": d.get("onsite_backups"),
            "backups_size_mb": num(d.get("backups_size")),
            "database_version": d.get("database_version"),
            "socketio": d.get("socketio_ping_check"),
        }
    except Exception as e:
        frappe.response["message"] = {"error": str(e)}


@frappe.whitelist()
def itAssignableRoles():
    # Server Script (API), api_method = itAssignableRoles
    # Returns assignable Role names for the IT Dashboard Role Manager, reading the
    # DB directly. frappe.get_all does NOT apply the doctype read-permission check
    # (unlike frappe.client.get_list), so an IT User Admin can list roles WITHOUT
    # holding System Manager / User Manager. Access is gated to IT User Admin /
    # System Manager so the endpoint isn't open to everyone.
    frappe.response["message"] = {"status": "error", "roles": []}
    try:
        my_role_rows = frappe.get_all(
            "Has Role",
            filters={"parent": frappe.session.user, "parenttype": "User"},
            fields=["role"],
            limit_page_length=0,
        )
        roles_of_user = {}
        n = 0
        while n < len(my_role_rows):
            roles_of_user[my_role_rows[n].role] = 1
            n = n + 1
        if ("IT User Admin" not in roles_of_user) and ("System Manager" not in roles_of_user):
            frappe.response["message"] = {"status": "forbidden", "roles": []}
        else:
            rows = frappe.get_all(
                "Role",
                filters={"disabled": 0},
                fields=["name"],
                order_by="name asc",
                limit_page_length=0,
            )
            names = []
            i = 0
            while i < len(rows):
                names = names + [rows[i].name]
                i = i + 1
            frappe.response["message"] = {"status": "success", "roles": names}
    except Exception as e:
        frappe.response["message"] = {"status": "error", "message": str(e), "roles": []}


@frappe.whitelist()
def it_access_data():
    me=frappe.session.user
    myroles=[x['role'] for x in frappe.db.sql("SELECT role FROM `tabHas Role` WHERE parent=%(u)s AND parenttype='User'", {'u':me}, as_dict=True)]
    if me!='Administrator' and 'System Manager' not in myroles and 'IT User Admin' not in myroles:
        frappe.response['message']={'success':False,'error':'System Manager only'}
    else:
        ws=frappe.db.sql("SELECT name,label,IFNULL(public,0) public,IFNULL(module,'') module,IFNULL(for_user,'') for_user FROM `tabWorkspace` WHERE IFNULL(for_user,'')='' ORDER BY label", as_dict=True)
        wr=frappe.db.sql("SELECT parent,role FROM `tabHas Role` WHERE parenttype='Workspace'", as_dict=True)
        rmap={}
        for r in wr: rmap.setdefault(r['parent'],[]).append(r['role'])
        for w in ws: w['roles']=sorted(rmap.get(w['name'],[]))
        allroles=[r['name'] for r in frappe.db.sql("SELECT name FROM `tabRole` WHERE IFNULL(disabled,0)=0 AND name NOT IN ('Administrator','All','Guest') ORDER BY name", as_dict=True)]
        profs=[r['name'] for r in frappe.db.sql("SELECT name FROM `tabRole Profile` ORDER BY name", as_dict=True)]
        pr=frappe.db.sql("SELECT parent,role FROM `tabHas Role` WHERE parenttype='Role Profile'", as_dict=True)
        pmap={}
        for r in pr: pmap.setdefault(r['parent'],[]).append(r['role'])
        uc=frappe.db.sql("SELECT role_profile_name rp, COUNT(*) n FROM `tabUser` WHERE IFNULL(enabled,0)=1 AND IFNULL(role_profile_name,'')<>'' GROUP BY role_profile_name", as_dict=True)
        umap={}
        for r in uc: umap[r['rp']]=r['n']
        role_profiles=[{'name':p,'roles':sorted(pmap.get(p,[])),'users':umap.get(p,0)} for p in profs]
        ur=frappe.db.sql("SELECT role, COUNT(*) n FROM `tabHas Role` WHERE parenttype='User' GROUP BY role", as_dict=True)
        urmap={}
        for r in ur: urmap[r['role']]=r['n']
        wscount={}
        for r in wr: wscount[r['role']]=wscount.get(r['role'],0)+1
        role_info=[{'role':rn,'users':urmap.get(rn,0),'workspaces':wscount.get(rn,0)} for rn in allroles]
        frappe.response['message']={'success':True,'workspaces':ws,'roles':allroles,'role_profiles':role_profiles,'role_info':role_info}


@frappe.whitelist()
def it_add_role_to_profile():
    # script_type: API | api_method: it_add_role_to_profile
    # Roles are managed through role profiles. Adding a role to a profile grants it
    # to every user on that profile (existing users are updated immediately).
    caller = frappe.session.user
    is_sm = bool(frappe.db.exists("Has Role", {"parent": caller, "role": "System Manager"}))
    if not (is_sm or frappe.db.exists("Has Role", {"parent": caller, "role": "IT User Admin"})):
        frappe.throw("Not permitted")

    role_profile = (frappe.form_dict.get("role_profile") or "").strip()
    role = (frappe.form_dict.get("role") or "").strip()
    if not role_profile or not frappe.db.exists("Role Profile", role_profile):
        frappe.throw("Unknown role profile")
    if not role or not frappe.db.exists("Role", role):
        frappe.throw("Unknown role")

    FORBIDDEN = ("System Manager", "Script Manager", "Administrator", "Guest", "All")
    if role in FORBIDDEN:
        frappe.throw("This role cannot be granted from here")

    # 1) add the role to the role profile (idempotent)
    rp = frappe.get_doc("Role Profile", role_profile)
    if role not in [r.role for r in rp.roles]:
        rp.append("roles", {"role": role})
        rp.save(ignore_permissions=True)

    # 2) propagate to every user currently on this profile
    users = frappe.get_all("User", filters={"role_profile_name": role_profile}, pluck="name")
    updated = 0
    skipped = 0
    for u in users:
        lu = u.lower()
        if not is_sm and (("upande" in lu) or lu in ("administrator", "guest")):
            skipped = skipped + 1
            continue
        if not frappe.db.exists("Has Role", {"parent": u, "role": role, "parenttype": "User"}):
            ud = frappe.get_doc("User", u)
            ud.append("roles", {"role": role})
            ud.save(ignore_permissions=True)
            updated = updated + 1

    frappe.response["message"] = {"role_profile": role_profile, "role": role,
                                  "users_on_profile": len(users), "users_updated": updated, "skipped": skipped}


@frappe.whitelist()
def it_create_role_profile():
    # script_type: API | api_method: it_create_role_profile
    caller = frappe.session.user
    is_sm = bool(frappe.db.exists("Has Role", {"parent": caller, "role": "System Manager"}))
    if not (is_sm or frappe.db.exists("Has Role", {"parent": caller, "role": "IT User Admin"})):
        frappe.throw("Not permitted")

    name = (frappe.form_dict.get("role_profile") or "").strip()
    roles_raw = frappe.form_dict.get("roles") or "[]"
    roles = json.loads(roles_raw) if isinstance(roles_raw, str) else roles_raw
    if not isinstance(roles, list):
        frappe.throw("Roles must be a list")
    if not name:
        frappe.throw("Role profile name is required")
    if frappe.db.exists("Role Profile", name):
        frappe.throw("A role profile with this name already exists")

    FORBIDDEN = ("System Manager", "Script Manager", "Administrator", "Guest", "All")
    clean = [r for r in dict.fromkeys(roles) if r and r not in FORBIDDEN and frappe.db.exists("Role", r)]
    if not clean:
        frappe.throw("Select at least one assignable role")

    d = frappe.new_doc("Role Profile")
    d.role_profile = name
    for r in clean:
        d.append("roles", {"role": r})
    d.insert(ignore_permissions=True)
    frappe.response["message"] = {"name": d.name, "roles": clean}


@frappe.whitelist()
def it_create_user():
    # script_type: API | api_method: it_create_user
    caller = frappe.session.user
    is_sm = bool(frappe.db.exists("Has Role", {"parent": caller, "role": "System Manager"}))
    if not (is_sm or frappe.db.exists("Has Role", {"parent": caller, "role": "IT User Admin"})):
        frappe.throw("Not permitted")

    email = (frappe.form_dict.get("email") or "").strip().lower()
    full_name = (frappe.form_dict.get("full_name") or "").strip()
    password = frappe.form_dict.get("password") or ""
    role_profile = (frappe.form_dict.get("role_profile") or "").strip()
    roles_raw = frappe.form_dict.get("roles") or "[]"
    roles = json.loads(roles_raw) if isinstance(roles_raw, str) else roles_raw
    if not isinstance(roles, list):
        frappe.throw("Roles must be a list")

    if not email or not full_name or not password:
        frappe.throw("Email, full name and password are required")
    if "upande" in email or email in ("administrator", "guest"):
        frappe.throw("You cannot create this user")
    if frappe.db.exists("User", email):
        frappe.throw("A user with this email already exists")

    FORBIDDEN = ("System Manager", "Script Manager", "Administrator", "Guest", "All")
    clean = [r for r in roles if r not in FORBIDDEN]

    # Access is granted through a role profile; pull its roles too.
    if role_profile:
        if not frappe.db.exists("Role Profile", role_profile):
            frappe.throw("Unknown role profile")
        rows = frappe.db.sql("SELECT role FROM `tabHas Role` WHERE parent=%(p)s AND parenttype='Role Profile'", {"p": role_profile}, as_dict=True)
        clean = list(dict.fromkeys(clean + [r.role for r in rows if r.role not in FORBIDDEN]))

    parts = full_name.split(" ", 1)
    d = frappe.new_doc("User")
    d.email = email
    d.first_name = parts[0]
    if len(parts) > 1:
        d.last_name = parts[1]
    if role_profile:
        d.role_profile_name = role_profile
    d.send_welcome_email = 0
    d.new_password = password
    for r in clean:
        d.append("roles", {"role": r})
    d.insert(ignore_permissions=True)
    frappe.response["message"] = {"name": d.name, "role_profile": role_profile, "roles": clean}


@frappe.whitelist()
def it_doctype_detail():
    me=frappe.session.user
    myroles=[x['role'] for x in frappe.db.sql("SELECT role FROM `tabHas Role` WHERE parent=%(u)s AND parenttype='User'", {'u':me}, as_dict=True)]
    if me!='Administrator' and 'System Manager' not in myroles and 'IT User Admin' not in myroles:
        frappe.response['message']={'success':False,'error':'System Manager only'}
    else:

        dt=frappe.form_dict.get('doctype')
        hascust=frappe.db.sql("SELECT COUNT(*) n FROM `tabCustom DocPerm` WHERE parent=%(d)s", {'d':dt}, as_dict=True)
        src='Custom DocPerm' if (hascust and hascust[0]['n']>0) else 'DocPerm'
        perms=frappe.db.sql("SELECT role, `read` r, `write` w, `create` c, `delete` d, submit s, `report` rp, export ex, `import` im FROM `tab"+src+"` WHERE parent=%(d)s AND permlevel=0 ORDER BY role", {'d':dt}, as_dict=True)
        desc=frappe.db.get_value('DocType', dt, 'description') or ''
        mod=frappe.db.get_value('DocType', dt, 'module') or ''
        frappe.response['message']={'success':True,'doctype':dt,'module':mod,'description':desc,'source':src,'permissions':perms}


@frappe.whitelist()
def it_doctype_list():
    me=frappe.session.user
    myroles=[x['role'] for x in frappe.db.sql("SELECT role FROM `tabHas Role` WHERE parent=%(u)s AND parenttype='User'", {'u':me}, as_dict=True)]
    if me!='Administrator' and 'System Manager' not in myroles and 'IT User Admin' not in myroles:
        frappe.response['message']={'success':False,'error':'System Manager only'}
    else:

        EXMOD="'Core','Custom','Desk','Workflow','Email','Printing','Integrations','Automation','Website','Social','Geo','Contacts','Data Migration','Telephony','Build','Event Streaming','Recorder','Utilities','Bulk Transaction','Payment Gateways'"
        rows=frappe.db.sql("""SELECT name, module, IFNULL(description,'') description
            FROM `tabDocType`
            WHERE IFNULL(istable,0)=0 AND IFNULL(issingle,0)=0 AND IFNULL(is_virtual,0)=0
              AND module NOT IN ("""+EXMOD+""")
              AND name NOT LIKE '%%Settings%%' AND name NOT LIKE '%%Log%%' AND name NOT LIKE '%%Token%%'
              AND name NOT LIKE '%%Webhook%%' AND name NOT LIKE '%%Mpesa%%' AND name NOT LIKE '%%OAuth%%'
              AND name NOT LIKE '%%Script%%' AND name NOT LIKE '%%API%%' AND name NOT LIKE '%%Integration%%'
            ORDER BY name""", as_dict=True)
        hascust={}
        for r in frappe.db.sql("SELECT DISTINCT parent FROM `tabCustom DocPerm`", as_dict=True): hascust[r['parent']]=1
        cp={}
        for r in frappe.db.sql("SELECT parent, role FROM `tabCustom DocPerm` WHERE `read`=1 AND permlevel=0", as_dict=True): cp.setdefault(r['parent'],[]).append(r['role'])
        sp={}
        for r in frappe.db.sql("SELECT parent, role FROM `tabDocPerm` WHERE `read`=1 AND permlevel=0", as_dict=True): sp.setdefault(r['parent'],[]).append(r['role'])
        out=[]
        for d in rows:
            nm=d['name']
            roles=sorted(set(cp.get(nm,[]))) if nm in hascust else sorted(set(sp.get(nm,[])))
            out.append({'name':nm,'module':d['module'],'description':(d['description'] or '')[:300],'roles':roles})
        frappe.response['message']={'success':True,'doctypes':out}


@frappe.whitelist()
def it_error_logs():
    me=frappe.session.user
    myroles=[x['role'] for x in frappe.db.sql("SELECT role FROM `tabHas Role` WHERE parent=%(u)s AND parenttype='User'", {'u':me}, as_dict=True)]
    if me!='Administrator' and 'System Manager' not in myroles and 'IT User Admin' not in myroles:
        frappe.response['message']={'success':False,'error':'System Manager only'}
    else:

        days=frappe.form_dict.get('days') or '7'
        try: days=int(days)
        except: days=7
        user=(frappe.form_dict.get('user') or '').strip()
        P={'d':days,'u':user}
        where="creation >= DATE_SUB(NOW(), INTERVAL %(d)s DAY)"
        if user: where=where+" AND owner=%(u)s"
        rows=frappe.db.sql("SELECT name, creation, IFNULL(method,'') method, owner, LEFT(IFNULL(error,''),6000) error FROM `tabError Log` WHERE "+where+" ORDER BY creation DESC LIMIT 300", P, as_dict=True)
        owners=frappe.db.sql("SELECT owner, COUNT(*) n FROM `tabError Log` WHERE creation >= DATE_SUB(NOW(), INTERVAL %(d)s DAY) GROUP BY owner ORDER BY n DESC", {'d':days}, as_dict=True)
        total=frappe.db.sql("SELECT COUNT(*) n FROM `tabError Log` WHERE creation >= DATE_SUB(NOW(), INTERVAL %(d)s DAY)", {'d':days}, as_dict=True)
        frappe.response['message']={'success':True,'days':days,'user':user,'rows':rows,'owners':owners,'total':(total[0]['n'] if total else 0)}


@frappe.whitelist()
def it_reset_password():
    # script_type: API | api_method: it_reset_password
    caller = frappe.session.user
    is_sm = bool(frappe.db.exists("Has Role", {"parent": caller, "role": "System Manager"}))
    if not (is_sm or frappe.db.exists("Has Role", {"parent": caller, "role": "IT User Admin"})):
        frappe.throw("Not permitted")

    user = frappe.form_dict.get("user")
    password = frappe.form_dict.get("password") or ""
    if not user or not frappe.db.exists("User", user):
        frappe.throw("Unknown user")
    if not password:
        frappe.throw("Password required")

    lu = user.lower()
    if not is_sm:
        if ("upande" in lu) or lu in ("administrator", "guest") \
           or frappe.db.exists("Has Role", {"parent": user, "role": "System Manager"}) \
           or frappe.db.exists("Has Role", {"parent": user, "role": "Script Manager"}):
            frappe.throw("You cannot manage this user")

    d = frappe.get_doc("User", user)
    d.new_password = password
    d.save(ignore_permissions=True)
    frappe.response["message"] = {"name": user, "reset": True}


@frappe.whitelist()
def it_role_detail():
    me=frappe.session.user
    myroles=[x['role'] for x in frappe.db.sql("SELECT role FROM `tabHas Role` WHERE parent=%(u)s AND parenttype='User'", {'u':me}, as_dict=True)]
    if me!='Administrator' and 'System Manager' not in myroles and 'IT User Admin' not in myroles:
        frappe.response['message']={'success':False,'error':'System Manager only'}
    else:
        role=frappe.form_dict.get('role')
        cust=frappe.db.sql("SELECT parent dt, `read` r, `write` w, `create` c, `delete` d, submit s, cancel x FROM `tabCustom DocPerm` WHERE role=%(r)s AND permlevel=0", {'r':role}, as_dict=True)
        custset={}
        for x in cust: custset[x['dt']]=1
        std=frappe.db.sql("SELECT parent dt, `read` r, `write` w, `create` c, `delete` d, submit s, cancel x FROM `tabDocPerm` WHERE role=%(r)s AND permlevel=0", {'r':role}, as_dict=True)
        perms=cust+[row for row in std if row['dt'] not in custset]
        perms=sorted(perms, key=lambda z: z['dt'])
        wr=frappe.db.sql("SELECT parent FROM `tabHas Role` WHERE parenttype='Workspace' AND role=%(r)s", {'r':role}, as_dict=True)
        wsv=[x['parent'] for x in wr]
        pf=frappe.db.sql("SELECT parent FROM `tabHas Role` WHERE parenttype='Role Profile' AND role=%(r)s", {'r':role}, as_dict=True)
        profiles=sorted([x['parent'] for x in pf])
        uc=frappe.db.sql("SELECT COUNT(*) n FROM `tabHas Role` WHERE parenttype='User' AND role=%(r)s", {'r':role}, as_dict=True)
        frappe.response['message']={'success':True,'role':role,'permissions':perms,'workspaces':sorted(wsv),'profiles':profiles,'users':(uc[0]['n'] if uc else 0)}


@frappe.whitelist()
def it_set_user_enabled():
    # script_type: API | api_method: it_set_user_enabled
    caller = frappe.session.user
    is_sm = bool(frappe.db.exists("Has Role", {"parent": caller, "role": "System Manager"}))
    if not (is_sm or frappe.db.exists("Has Role", {"parent": caller, "role": "IT User Admin"})):
        frappe.throw("Not permitted")

    user = frappe.form_dict.get("user")
    enabled = 1 if frappe.utils.cint(frappe.form_dict.get("enabled")) else 0
    if not user or not frappe.db.exists("User", user):
        frappe.throw("Unknown user")

    lu = user.lower()
    if not is_sm:
        if ("upande" in lu) or lu in ("administrator", "guest") \
           or frappe.db.exists("Has Role", {"parent": user, "role": "System Manager"}) \
           or frappe.db.exists("Has Role", {"parent": user, "role": "Script Manager"}):
            frappe.throw("You cannot manage this user")

    frappe.db.set_value("User", user, "enabled", enabled)
    frappe.response["message"] = {"name": user, "enabled": enabled}


@frappe.whitelist()
def it_set_user_role_profile():
    # script_type: API | api_method: it_set_user_role_profile
    caller = frappe.session.user
    is_sm = bool(frappe.db.exists("Has Role", {"parent": caller, "role": "System Manager"}))
    if not (is_sm or frappe.db.exists("Has Role", {"parent": caller, "role": "IT User Admin"})):
        frappe.throw("Not permitted")

    user = frappe.form_dict.get("user")
    role_profile = (frappe.form_dict.get("role_profile") or "").strip()
    if not user or not frappe.db.exists("User", user):
        frappe.throw("Unknown user")

    lu = user.lower()
    if not is_sm:
        if ("upande" in lu) or lu in ("administrator", "guest") \
           or frappe.db.exists("Has Role", {"parent": user, "role": "System Manager"}) \
           or frappe.db.exists("Has Role", {"parent": user, "role": "Script Manager"}):
            frappe.throw("You cannot manage this user")

    FORBIDDEN = ("System Manager", "Script Manager", "Administrator", "Guest", "All")

    profile_roles = []
    if role_profile:
        if not frappe.db.exists("Role Profile", role_profile):
            frappe.throw("Unknown role profile")
        rows = frappe.db.sql("SELECT role FROM `tabHas Role` WHERE parent=%(p)s AND parenttype='Role Profile'", {"p": role_profile}, as_dict=True)
        profile_roles = [r.role for r in rows if r.role not in FORBIDDEN]

    d = frappe.get_doc("User", user)
    # never silently strip code/admin roles the user already holds
    preserved = list(dict.fromkeys(x.role for x in d.roles if x.role in ("System Manager", "Script Manager")))
    d.role_profile_name = role_profile or None
    d.set("roles", [])
    for r in list(dict.fromkeys(profile_roles + preserved)):
        d.append("roles", {"role": r})
    d.save(ignore_permissions=True)
    frappe.response["message"] = {"name": d.name, "role_profile": role_profile, "roles": [x.role for x in d.roles]}


@frappe.whitelist()
def it_set_user_roles():
    # script_type: API | api_method: it_set_user_roles
    caller = frappe.session.user
    is_sm = bool(frappe.db.exists("Has Role", {"parent": caller, "role": "System Manager"}))
    if not (is_sm or frappe.db.exists("Has Role", {"parent": caller, "role": "IT User Admin"})):
        frappe.throw("Not permitted")

    user = frappe.form_dict.get("user")
    roles_raw = frappe.form_dict.get("roles") or "[]"
    roles = json.loads(roles_raw) if isinstance(roles_raw, str) else roles_raw
    if not isinstance(roles, list):
        frappe.throw("Roles must be a list")
    if not user or not frappe.db.exists("User", user):
        frappe.throw("Unknown user")

    lu = user.lower()
    if not is_sm:
        if ("upande" in lu) or lu in ("administrator", "guest") \
           or frappe.db.exists("Has Role", {"parent": user, "role": "System Manager"}) \
           or frappe.db.exists("Has Role", {"parent": user, "role": "Script Manager"}):
            frappe.throw("You cannot manage this user")

    FORBIDDEN = ("System Manager", "Script Manager", "Administrator", "Guest", "All")
    clean = [r for r in roles if r not in FORBIDDEN]
    d = frappe.get_doc("User", user)
    existing_forbidden = list(dict.fromkeys(x.role for x in d.roles if x.role in ("System Manager", "Script Manager")))
    d.set("roles", [])
    for r in (clean + existing_forbidden):
        d.append("roles", {"role": r})
    d.save(ignore_permissions=True)
    frappe.response["message"] = {"name": d.name, "roles": clean}


@frappe.whitelist()
def it_set_workspace_roles():
    me=frappe.session.user
    myroles=[x['role'] for x in frappe.db.sql("SELECT role FROM `tabHas Role` WHERE parent=%(u)s AND parenttype='User'", {'u':me}, as_dict=True)]
    if me!='Administrator' and 'System Manager' not in myroles and 'IT User Admin' not in myroles:
        frappe.response['message']={'success':False,'error':'System Manager only'}
    else:
        ws_name=frappe.form_dict.get('workspace')
        raw=frappe.form_dict.get('roles') or ''
        rolelist=[x for x in raw.split('|||') if x]
        if not ws_name or not frappe.db.exists('Workspace', ws_name):
            frappe.response['message']={'success':False,'error':'Workspace not found'}
        else:
            doc=frappe.get_doc('Workspace', ws_name)
            doc.set('roles', [])
            seen={}
            for r in rolelist:
                if r and r not in seen:
                    seen[r]=1
                    doc.append('roles', {'role': r})
            doc.save()
            frappe.db.commit()
            frappe.response['message']={'success':True,'workspace':ws_name,'roles':sorted(seen.keys())}


@frappe.whitelist()
def latestRoutes():

    if frappe.request.method == "GET":
        try:
            since = frappe.utils.add_to_date(frappe.utils.now_datetime(), hours=-12)
            rows = frappe.db.sql("""
                SELECT rh.user, rh.route, rh.modified
                FROM `tabRoute History` rh
                INNER JOIN (
                    SELECT user, MAX(modified) AS mx
                    FROM `tabRoute History`
                    WHERE modified >= %(since)s
                    GROUP BY user
                ) t ON t.user = rh.user AND rh.modified = t.mx
                WHERE rh.modified >= %(since)s
            """, {"since": since}, as_dict=True)

            seen = {}
            deduped = []
            for r in rows:
                if r["user"] in seen:
                    continue
                seen[r["user"]] = 1
                deduped.append({"user": r["user"], "route": r["route"],
                                "modified": str(r["modified"]) if r.get("modified") else None})
            rows = deduped

            frappe.response.pop("docs", None)
            frappe.response["status"] = "success"
            frappe.response["data"] = {"routes": rows, "count": len(rows)}
            frappe.response.http_status_code = 200
        except Exception as e:
            frappe.log_error(title="Latest Routes API Error", message=str(e))
            frappe.response["status"] = "error"
            frappe.response["message"] = f"Failed: {str(e)}"
            frappe.response.http_status_code = 500
    else:
        frappe.response["status"] = "error"
        frappe.response["message"] = "Method not allowed. Use GET."
        frappe.response.http_status_code = 405


@frappe.whitelist()
def runShiftAttendance():
    shift = frappe.form_dict.get("shift")
    if not shift:
        frappe.throw("shift is required")

    doc = frappe.get_doc("Shift Type", shift)
    before_sync = doc.last_sync_of_checkin

    # Attendance snapshot BEFORE.
    att_before = frappe.db.count("Attendance", {"shift": shift, "docstatus": ("<", 2)})

    # THE FIX: advance the watermark FORWARD to NOW. HRMS get_employee_checkins() only
    # returns check-ins whose shift_actual_end < last_sync_of_checkin. These shifts have a
    # long check-out buffer (shift_actual_end ~23:10 = 16:10 + grace), and the LAST check-in
    # time (~19:11) sits INSIDE that buffer — so seeding to MAX(check-in) leaves the most
    # recent completed day permanently unmarked. Seeding to now clears every completed day.
    seed = frappe.utils.now_datetime()
    doc.db_set("last_sync_of_checkin", seed)
    doc.reload()

    run_error = None
    try:
        doc.process_auto_attendance()
        frappe.db.commit()
    except Exception:
        run_error = frappe.get_traceback()

    doc.reload()
    after_sync = doc.last_sync_of_checkin

    att_after = frappe.db.count("Attendance", {"shift": shift, "docstatus": ("<", 2)})

    # Status breakdown of the shift's attendance after the run.
    status_rows = frappe.db.sql(
        "SELECT status, COUNT(*) FROM `tabAttendance` WHERE shift=%s AND docstatus < 2 GROUP BY status",
        shift)
    status_counts = {}
    for r in status_rows:
        status_counts[str(r[0])] = r[1]

    emps = frappe.get_all("Shift Assignment",
        filters={"shift_type": shift, "status": "Active", "docstatus": 1}, pluck="employee")
    rows = []
    for emp in emps:
        en = frappe.db.get_value("Employee", emp, "employee_name")
        pend = frappe.db.sql("""SELECT COUNT(*) FROM `tabEmployee Checkin`
            WHERE employee=%s AND shift=%s AND (attendance IS NULL OR attendance='') AND skip_auto_attendance=0""", (emp, shift))
        lci = frappe.db.sql("SELECT MAX(time) FROM `tabEmployee Checkin` WHERE employee=%s AND shift=%s", (emp, shift))
        lat = frappe.db.sql("SELECT MAX(attendance_date) FROM `tabAttendance` WHERE employee=%s AND shift=%s AND docstatus < 2", (emp, shift))
        rows.append({
            "employee": emp,
            "employee_name": en,
            "pending": (pend[0][0] if pend else 0),
            "last_checkin": (str(lci[0][0]) if lci and lci[0][0] else None),
            "last_attendance": (str(lat[0][0]) if lat and lat[0][0] else None),
        })

    frappe.response["message"] = {
        "shift":          shift,
        "before_sync":    (str(before_sync) if before_sync else None),
        "after_sync":     (str(after_sync) if after_sync else None),
        "att_before":     att_before,
        "att_after":      att_after,
        "att_created":    att_after - att_before,
        "status_counts":  status_counts,
        "error":          run_error,
        "employees":      rows,
    }


@frappe.whitelist()
def shiftDiag():
    shift = frappe.form_dict.get("shift")
    company = frappe.form_dict.get("company")
    if not shift:
        frappe.throw("shift is required")

    cfg = frappe.db.get_value("Shift Type", shift,
        ["enable_auto_attendance", "last_sync_of_checkin", "process_attendance_after"], as_dict=True) or {}

    comp = ""
    params = {"shift": shift}
    if company:
        comp = " AND e.company = %(company)s"
        params["company"] = company

    emps = frappe.db.sql(f"""
        SELECT e.name, e.employee_name
        FROM `tabShift Assignment` sa JOIN `tabEmployee` e ON e.name = sa.employee
        WHERE sa.status='Active' AND sa.docstatus=1 AND e.status='Active' AND sa.shift_type=%(shift)s {comp}
        GROUP BY e.name ORDER BY e.employee_name
    """, params, as_dict=True)

    rows = []
    for e in emps:
        emp = e.name
        tot = frappe.db.sql("SELECT COUNT(*) FROM `tabEmployee Checkin` WHERE employee=%s AND shift=%s", (emp, shift))[0][0]
        pend = frappe.db.sql("""SELECT COUNT(*) FROM `tabEmployee Checkin`
            WHERE employee=%s AND shift=%s AND (attendance IS NULL OR attendance='') AND skip_auto_attendance=0""", (emp, shift))[0][0]
        lci = frappe.db.sql("SELECT MAX(time) FROM `tabEmployee Checkin` WHERE employee=%s AND shift=%s", (emp, shift))[0][0]
        lat = frappe.db.sql("SELECT MAX(attendance_date) FROM `tabAttendance` WHERE employee=%s AND docstatus < 2", emp)[0][0]
        rows.append({
            "employee": emp, "employee_name": e.employee_name,
            "total": tot, "pending": pend,
            "last_checkin": (str(lci) if lci else None),
            "last_attendance": (str(lat) if lat else None),
        })

    errs = frappe.db.sql("""SELECT name, method, creation, LEFT(error, 500) AS snippet
        FROM `tabError Log` WHERE error LIKE %(k)s ORDER BY creation DESC LIMIT 15""",
        {"k": "%" + shift + "%"}, as_dict=True)
    for r in errs:
        r["creation"] = str(r["creation"])

    frappe.response["message"] = {
        "config": {
            "auto":          cfg.get("enable_auto_attendance"),
            "last_sync":     (str(cfg.get("last_sync_of_checkin")) if cfg.get("last_sync_of_checkin") else None),
            "process_after": (str(cfg.get("process_attendance_after")) if cfg.get("process_attendance_after") else None),
        },
        "employees": rows,
        "errors":    errs,
    }


@frappe.whitelist()
def shiftOverview():

    if frappe.request.method == "GET":
        try:
            company = frappe.request.args.get("company")
            farm    = frappe.request.args.get("farm")
            action  = frappe.request.args.get("action")
            shift   = frappe.request.args.get("shift")

            emp_company = ""
            params = {}
            if company:
                emp_company += " AND e.company = %(company)s"
                params["company"] = company
            if farm:
                emp_company += " AND e.custom_farm = %(farm)s"
                params["farm"] = farm

            # ── Employees assigned to a specific shift (+ farm) ──
            if action == "shift_employees":
                params["shift"] = shift
                rows = frappe.db.sql(f"""
                    SELECT e.name, e.employee_name, e.company,
                           e.custom_farm AS farm, e.designation
                    FROM `tabShift Assignment` sa
                    JOIN `tabEmployee` e ON e.name = sa.employee
                    WHERE sa.status = 'Active' AND sa.docstatus = 1
                      AND e.status = 'Active' AND sa.shift_type = %(shift)s {emp_company}
                    GROUP BY e.name
                    ORDER BY e.custom_farm, e.employee_name
                """, params, as_dict=True)
                frappe.response.pop("docs", None)
                frappe.response["status"] = "success"
                frappe.response["data"] = {"employees": rows, "count": len(rows)}
                frappe.response.http_status_code = 200

            # ── Active employees NOT assigned to any shift (+ farm) ──
            elif action == "unassigned":
                rows = frappe.db.sql(f"""
                    SELECT e.name, e.employee_name, e.company,
                           e.custom_farm AS farm, e.designation, e.default_shift AS shift
                    FROM `tabEmployee` e
                    WHERE e.status = 'Active' {emp_company}
                      AND e.name NOT IN (
                        SELECT sa.employee FROM `tabShift Assignment` sa
                        WHERE sa.status = 'Active' AND sa.docstatus = 1 AND sa.employee IS NOT NULL
                      )
                    ORDER BY e.custom_farm, e.employee_name
                    LIMIT 8000
                """, params, as_dict=True)
                frappe.response.pop("docs", None)
                frappe.response["status"] = "success"
                frappe.response["data"] = {"employees": rows, "count": len(rows)}
                frappe.response.http_status_code = 200

            # ── All assigned employees (+ the shift(s) they hold) ──
            elif action == "assigned":
                rows = frappe.db.sql(f"""
                    SELECT e.name, e.employee_name, e.company, e.custom_farm AS farm, e.designation,
                           GROUP_CONCAT(DISTINCT sa.shift_type ORDER BY sa.shift_type SEPARATOR ', ') AS shift
                    FROM `tabShift Assignment` sa
                    JOIN `tabEmployee` e ON e.name = sa.employee
                    WHERE sa.status='Active' AND sa.docstatus=1 AND e.status='Active' {emp_company}
                    GROUP BY e.name
                    ORDER BY e.custom_farm, e.employee_name
                    LIMIT 8000
                """, params, as_dict=True)
                frappe.response.pop("docs", None)
                frappe.response["status"] = "success"
                frappe.response["data"] = {"employees": rows, "count": len(rows)}
                frappe.response.http_status_code = 200

            # ── Assigned employees whose attendance stopped (none since yesterday) ──
            elif action == "attendance_stopped":
                rows = frappe.db.sql(f"""
                    SELECT e.name, e.employee_name, e.company, e.custom_farm AS farm, e.designation,
                           MAX(sa.shift_type) AS shift,
                           (SELECT MAX(a.attendance_date) FROM `tabAttendance` a
                            WHERE a.employee = e.name AND a.docstatus < 2) AS last_attendance
                    FROM `tabShift Assignment` sa
                    JOIN `tabEmployee` e ON e.name = sa.employee
                    WHERE sa.status='Active' AND sa.docstatus=1 AND e.status='Active' {emp_company}
                      AND sa.employee NOT IN (
                        SELECT employee FROM `tabAttendance`
                        WHERE docstatus < 2 AND employee IS NOT NULL
                          AND attendance_date >= DATE_SUB(CURDATE(), INTERVAL 1 DAY)
                      )
                    GROUP BY e.name
                    ORDER BY last_attendance
                    LIMIT 8000
                """, params, as_dict=True)
                for r in rows:
                    r["last_attendance"] = str(r["last_attendance"]) if r.get("last_attendance") else None
                frappe.response.pop("docs", None)
                frappe.response["status"] = "success"
                frappe.response["data"] = {"employees": rows, "count": len(rows)}
                frappe.response.http_status_code = 200

            # ── Overview: companies, totals, per-shift ──
            else:
                companies = frappe.db.sql("SELECT name FROM `tabCompany` ORDER BY name", as_dict=True)

                farm_filter = ""
                fparams = {}
                if company:
                    farm_filter = " AND company = %(company)s"
                    fparams["company"] = company
                farms = frappe.db.sql(f"""
                    SELECT DISTINCT custom_farm AS farm FROM `tabEmployee`
                    WHERE status='Active' AND custom_farm IS NOT NULL AND TRIM(custom_farm) <> '' {farm_filter}
                    ORDER BY custom_farm
                """, fparams, as_dict=True)

                active_employees = frappe.db.sql(
                    f"SELECT COUNT(*) c FROM `tabEmployee` e WHERE e.status='Active' {emp_company}",
                    params, as_dict=True)[0]["c"]

                assigned = frappe.db.sql(f"""
                    SELECT COUNT(DISTINCT sa.employee) c
                    FROM `tabShift Assignment` sa
                    JOIN `tabEmployee` e ON e.name = sa.employee
                    WHERE sa.status='Active' AND sa.docstatus=1 AND e.status='Active' {emp_company}
                """, params, as_dict=True)[0]["c"]

                stopped = frappe.db.sql(f"""
                    SELECT COUNT(DISTINCT sa.employee) c
                    FROM `tabShift Assignment` sa
                    JOIN `tabEmployee` e ON e.name = sa.employee
                    WHERE sa.status='Active' AND sa.docstatus=1 AND e.status='Active' {emp_company}
                      AND sa.employee NOT IN (
                        SELECT employee FROM `tabAttendance`
                        WHERE docstatus < 2 AND employee IS NOT NULL
                          AND attendance_date >= DATE_SUB(CURDATE(), INTERVAL 1 DAY)
                      )
                """, params, as_dict=True)[0]["c"]

                shift_types = frappe.db.sql("""
                    SELECT name, start_time, end_time, last_sync_of_checkin, enable_auto_attendance
                    FROM `tabShift Type` ORDER BY name
                """, as_dict=True)

                per = frappe.db.sql(f"""
                    SELECT sa.shift_type AS shift, COUNT(DISTINCT sa.employee) AS employees
                    FROM `tabShift Assignment` sa
                    JOIN `tabEmployee` e ON e.name = sa.employee
                    WHERE sa.status='Active' AND sa.docstatus=1 AND e.status='Active' {emp_company}
                    GROUP BY sa.shift_type
                """, params, as_dict=True)

                att_company = ""
                aparams = {}
                if company:
                    att_company = " AND company = %(company)s"
                    aparams["company"] = company
                att = frappe.db.sql(f"""
                    SELECT shift, MAX(attendance_date) AS last_attendance, COUNT(*) AS att_count
                    FROM `tabAttendance`
                    WHERE shift IS NOT NULL AND docstatus < 2 {att_company}
                    GROUP BY shift
                """, aparams, as_dict=True)

                pmap = {p["shift"]: p for p in per}
                tmap = {a["shift"]: a for a in att}
                rows = []
                for s in shift_types:
                    nm = s["name"]
                    p = pmap.get(nm) or {}
                    t = tmap.get(nm) or {}
                    rows.append({
                        "shift":           nm,
                        "start_time":      str(s.get("start_time")) if s.get("start_time") else None,
                        "end_time":        str(s.get("end_time")) if s.get("end_time") else None,
                        "auto":            s.get("enable_auto_attendance"),
                        "last_sync":       str(s.get("last_sync_of_checkin")) if s.get("last_sync_of_checkin") else None,
                        "employees":       p.get("employees") or 0,
                        "last_attendance": str(t.get("last_attendance")) if t.get("last_attendance") else None,
                        "att_count":       t.get("att_count") or 0,
                    })

                frappe.response.pop("docs", None)
                frappe.response["status"] = "success"
                frappe.response["data"] = {
                    "companies": [c["name"] for c in companies],
                    "farms": [f["farm"] for f in farms],
                    "totals": {
                        "active_employees": active_employees,
                        "assigned":         assigned,
                        "unassigned":       max(0, active_employees - assigned),
                        "attendance_stopped": stopped,
                    },
                    "shifts": rows,
                }
                frappe.response.http_status_code = 200

        except Exception as e:
            frappe.log_error(title="Shift Overview API Error", message=str(e))
            frappe.response["status"] = "error"
            frappe.response["message"] = f"Failed: {str(e)}"
            frappe.response.http_status_code = 500

    else:
        frappe.response["status"] = "error"
        frappe.response["message"] = "Method not allowed. Use GET."
        frappe.response.http_status_code = 405
