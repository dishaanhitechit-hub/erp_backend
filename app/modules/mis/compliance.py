"""
MIS — Schedule Compliance: how much work was finished by its due date.

Counts the same items as the performance score (self tasks + follow-up relay
steps) using the same rules — work that is not due yet is never "late":

  due      items whose due date fell in the period and were finished, or whose date has passed
  onTime   of those, finished on or before the due date
  late     finished, but after the due date
  missed   still open past the due date (at period end, or today for the live period;
           includes older work carried into the period)
  pct      onTime / due × 100

Who can open it: super admin, schedule_compliance VIEW/EDIT in the current
project, or HR (performance_appraisal / employee_management / employee_master).
"""
from datetime import date, datetime

from flask import Blueprint, request
from flask_jwt_extended import jwt_required, get_jwt_identity, get_jwt

from app.response import res
from app.models.project import Project
from app.modules.hr.performance.score_service import (
    _collect, _subjects, period_bounds, previous_period, period_label, PERIODS, _is_super,
)

mis_compliance_bp = Blueprint("mis_compliance", __name__)

_KEYS = ("schedule_compliance", "performance_appraisal", "employee_management", "employee_master")


def _allowed(user_id):
    if _is_super(user_id):
        return True
    perms = (get_jwt() or {}).get("permissions") or {}
    return any(perms.get(f"{k}.VIEW") or perms.get(f"{k}.EDIT") for k in _KEYS)


def _pct(on_time, due):
    return round(100.0 * on_time / due, 1) if due else None


def _row(raw):
    due, on = raw["due"], raw["onTime"]
    return {"due": due, "onTime": on, "late": raw["lateDone"], "missed": raw["overdueOpen"], "pct": _pct(on, due),
            "done": raw["done"]}


def compliance(args, user_id):
    user_id = int(user_id)
    if not _allowed(user_id):
        return res("You do not have permission to view schedule compliance", [], 403)
    period = (args.get("period") or "month").lower()
    if period not in PERIODS:
        return res("period must be month or week", [], 400)
    anchor = None
    if args.get("date"):
        try:
            anchor = datetime.strptime(args["date"][:10], "%Y-%m-%d").date()
        except ValueError:
            return res("date must be YYYY-MM-DD", [], 400)
    project = None
    code = args.get("projectCode")
    if code and code.lower() not in ("all", "company"):
        project = Project.query.filter_by(project_code=code).first()
        if not project:
            return res("Project not found", [], 404)
    pid = project.id if project else None
    dept_filter = (args.get("department") or "").strip()

    start, end = period_bounds(period, anchor)
    raw = _collect(start, end, pid)
    subjects = _subjects()
    by_user = {s["userId"]: s for s in subjects.values() if s["userId"]}

    people, depts = [], {}
    for uid, r in raw.items():
        if not (r["due"] or r["overdueOpen"]):
            continue                                    # nothing was due → not part of compliance
        s = by_user.get(uid) or {"name": f"User {uid}", "empCode": None, "department": None, "designation": None,
                                 "key": f"u{uid}"}
        dept = s.get("department") or "Unassigned"
        if dept_filter and dept != dept_filter:
            continue
        row = {"userId": uid, "key": s.get("key"), "name": s.get("name"), "empCode": s.get("empCode"),
               "department": dept, "designation": s.get("designation"), **_row(r)}
        people.append(row)
        d = depts.setdefault(dept, {"department": dept, "due": 0, "onTime": 0, "late": 0, "missed": 0, "people": 0})
        d["due"] += r["due"]
        d["onTime"] += r["onTime"]
        d["late"] += r["lateDone"]
        d["missed"] += r["overdueOpen"]
        d["people"] += 1

    for d in depts.values():
        d["pct"] = _pct(d["onTime"], d["due"])
    people.sort(key=lambda x: (x["pct"] is None, x["pct"] if x["pct"] is not None else 0, -x["missed"], x["name"] or ""))
    dept_rows = sorted(depts.values(), key=lambda x: (x["pct"] is None, x["pct"] or 0))

    tot_due = sum(p["due"] for p in people)
    tot_on = sum(p["onTime"] for p in people)

    # company trend: this + 5 previous periods (same project / department filter)
    trend, st = [], start
    for _ in range(6):
        s_, e_ = period_bounds(period, st)
        rr = raw if s_ == start else _collect(s_, e_, pid)
        due = on = 0
        for uid, r in rr.items():
            if dept_filter:
                sub = by_user.get(uid)
                if ((sub or {}).get("department") or "Unassigned") != dept_filter:
                    continue
            due += r["due"]
            on += r["onTime"]
        trend.append({"periodStart": s_.isoformat(), "periodLabel": period_label(period, s_), "due": due,
                      "onTime": on, "pct": _pct(on, due)})
        st = previous_period(period, s_)[0]
    trend.reverse()

    return res("ok", {
        "period": period, "periodStart": start.isoformat(), "periodEnd": end.isoformat(),
        "periodLabel": period_label(period, start), "isLive": start <= date.today() <= end,
        "projectCode": project.project_code if project else None,
        "summary": {"due": tot_due, "onTime": tot_on, "late": sum(p["late"] for p in people),
                    "missed": sum(p["missed"] for p in people), "pct": _pct(tot_on, tot_due),
                    "people": len(people),
                    "below80": sum(1 for p in people if p["pct"] is not None and p["pct"] < 80)},
        "departments": dept_rows,
        "people": people,
        "trend": trend,
    })


@mis_compliance_bp.route("", methods=["GET"])
@jwt_required()
def api_compliance():
    # ?period=month|week &date=YYYY-MM-DD &projectCode=<code>|all &department=
    return compliance(request.args, get_jwt_identity())
