"""
Employee Performance Score (0–100) — worked out from real work, not filled in by hand.

Parts (weights in WEIGHTS; a part with no data for the person is left out and
the remaining weights are scaled up, so nobody is punished for missing data):

  onTime      30  items due in the period finished on or before their due date
  quality     25  "error-less": 100 − share of completed items that were reopened
                  (self task Done → open again) or sent back (follow-up step Rejected)
  throughput  15  items completed vs the company median for the same period
  backlog     10  100 − share of due work still open past its due date
  pickup       5  hours from being assigned a follow-up step to starting it
                  (≤ 4 h = 100, ≥ 72 h = 0)
  appraisal   15  latest HR performance review rating × 20
  discipline  −0…10 points for open discipline cases (by severity)

"Items" = MIS self tasks (owner) + follow-up relay steps (assignee).
Everyone is a "subject": an Employee (matched to a login User by emp_code),
or a login User with MIS work but no Employee record.
"""
import calendar
import statistics
from collections import defaultdict
from datetime import date, datetime, time, timedelta

from sqlalchemy import or_, and_

from app.extensions import db
from app.models.user import User
from app.models.employee import Employee
from app.models.performanceModel import PerformanceReview, DisciplineCase, EmployeePerformanceScore
from app.models.misTask import MisTask, MisActivity
from app.models.misFollowup import MisFollowup, MisFollowupStep

WEIGHTS = {"onTime": 30, "quality": 25, "throughput": 15, "backlog": 10, "pickup": 5, "appraisal": 15}
LABELS = {
    "onTime": "On-time delivery", "quality": "Quality (error-less)", "throughput": "Work completed",
    "backlog": "Overdue backlog", "pickup": "Pick-up speed", "appraisal": "Manager appraisal",
}
DISCIPLINE_POINTS = {"Low": 2, "Medium": 4, "High": 7, "Critical": 10}
DISCIPLINE_CAP = 10
PICKUP_BEST_H, PICKUP_WORST_H = 4, 72
LOW_DATA_ITEMS = 3

GRADES = [(85, "Excellent"), (70, "Good"), (50, "Average"), (0, "Needs Improvement")]
PERIODS = ("month", "week")


# ─────────────────────────────── periods ───────────────────────────────

def period_bounds(period, anchor=None):
    anchor = anchor or date.today()
    if period == "week":
        start = anchor - timedelta(days=anchor.weekday())
        return start, start + timedelta(days=6)
    if period == "month":
        start = anchor.replace(day=1)
        return start, start.replace(day=calendar.monthrange(start.year, start.month)[1])
    raise ValueError("period must be month or week")


def previous_period(period, start):
    return period_bounds(period, start - timedelta(days=1))


def period_label(period, start):
    return start.strftime("%b %Y") if period == "month" else f"Wk {start.isocalendar()[1]} · {start.strftime('%d %b')}"


def grade_for(score):
    if score is None:
        return "No data"
    for floor, name in GRADES:
        if score >= floor:
            return name
    return GRADES[-1][1]


# ─────────────────────────────── subjects ──────────────────────────────

def _subjects():
    """{key: {...}} for every employee (+ linked user) and every active user without an employee record."""
    users = User.query.all()
    by_code = {}
    for u in users:
        if u.emp_code:
            by_code.setdefault(u.emp_code.strip().upper(), u)
    out, linked = {}, set()
    for e in Employee.query.filter(or_(Employee.employee_status.is_(None), Employee.employee_status != "Inactive")).all():
        u = by_code.get((e.emp_code or "").strip().upper())
        if u:
            linked.add(u.id)
        out[f"e{e.id}"] = {
            "key": f"e{e.id}", "employeeId": e.id, "userId": u.id if u else None,
            "name": e.full_name, "empCode": e.emp_code, "department": e.department, "designation": e.designation,
        }
    for u in users:
        if u.id in linked or u.is_active is False:
            continue
        out[f"u{u.id}"] = {
            "key": f"u{u.id}", "employeeId": None, "userId": u.id,
            "name": u.username, "empCode": u.emp_code, "department": None, "designation": None,
        }
    return out


# ─────────────────────────────── raw metrics ───────────────────────────

def _blank():
    return {"due": 0, "onTime": 0, "done": 0, "errors": 0, "reopened": 0, "rejected": 0,
            "backlogBase": 0, "overdueOpen": 0, "pickupHours": []}


def _count_item(m, due, comp, created, start, end, cutoff):
    # judged only once it is finished or its due date has passed — work due later (or today) is not "late" yet
    if due and start <= due <= end and (comp is not None or due < cutoff):
        m["due"] += 1
        if comp and comp <= due:
            m["onTime"] += 1
    if comp and start <= comp <= end:
        m["done"] += 1
    # backlog: due by the cut-off and still relevant in this period
    if due and due <= cutoff and (due >= start or comp is None or comp >= start) and (created is None or created <= cutoff):
        m["backlogBase"] += 1
        if due < cutoff and (comp is None or comp > cutoff):
            m["overdueOpen"] += 1


def _collect(start, end, project_id=None):
    """{user_id: raw counts} for the period (one pass over tasks, steps, reopen events).
    project_id narrows it to one project (used by the Schedule Compliance report)."""
    cutoff = min(end, date.today())
    s_dt = datetime.combine(start, time.min)
    e_dt = datetime.combine(end + timedelta(days=1), time.min)
    m = defaultdict(_blank)

    tasks = MisTask.query.filter(
        MisTask.is_deleted.is_(False), MisTask.status != "Cancelled",
        or_(and_(MisTask.due_date <= end, or_(MisTask.completed_at.is_(None), MisTask.completed_at >= s_dt)),
            and_(MisTask.completed_at >= s_dt, MisTask.completed_at < e_dt)),
        *([MisTask.project_id == project_id] if project_id else []),
    ).all()
    for t in tasks:
        _count_item(m[t.owner_user_id], t.due_date, t.completed_at.date() if t.completed_at else None,
                    t.created_at.date() if t.created_at else None, start, end, cutoff)

    # reopen = a Done task moved back to an open status in this period (owner's error)
    reopens = (db.session.query(MisTask.owner_user_id)
               .join(MisActivity, and_(MisActivity.entity_type == "task", MisActivity.entity_id == MisTask.id))
               .filter(MisActivity.action == "STATUS", MisActivity.old_value == "Done",
                       MisActivity.created_at >= s_dt, MisActivity.created_at < e_dt,
                       *([MisTask.project_id == project_id] if project_id else [])).all())
    for (uid,) in reopens:
        m[uid]["reopened"] += 1
        m[uid]["errors"] += 1

    steps = (MisFollowupStep.query.join(MisFollowup, MisFollowup.id == MisFollowupStep.followup_id)
             .filter(MisFollowup.is_deleted.is_(False), MisFollowupStep.status.notin_(("Reassigned", "Cancelled")),
                     or_(and_(MisFollowupStep.due_date <= end,
                              or_(MisFollowupStep.completed_at.is_(None), MisFollowupStep.completed_at >= s_dt)),
                         and_(MisFollowupStep.completed_at >= s_dt, MisFollowupStep.completed_at < e_dt),
                         and_(MisFollowupStep.assigned_at >= s_dt, MisFollowupStep.assigned_at < e_dt)),
                     *([MisFollowup.project_id == project_id] if project_id else []))
             .all())
    for st in steps:
        r = m[st.assignee_user_id]
        comp = st.completed_at.date() if st.completed_at else None
        _count_item(r, st.due_date, comp, st.assigned_at.date() if st.assigned_at else None, start, end, cutoff)
        if st.status == "Rejected" and comp and start <= comp <= end:
            r["rejected"] += 1
            r["errors"] += 1
        if st.started_at and st.assigned_at and s_dt <= st.assigned_at < e_dt:
            r["pickupHours"].append(max(0.0, (st.started_at - st.assigned_at).total_seconds() / 3600))
    return m


def _appraisals(employee_ids):
    """{employee_id: (rating, cycle)} — latest rated review."""
    out = {}
    if not employee_ids:
        return out
    rows = (PerformanceReview.query.filter(PerformanceReview.employee_id.in_(employee_ids),
                                           PerformanceReview.rating.isnot(None))
            .order_by(PerformanceReview.created_at.desc(), PerformanceReview.id.desc()).all())
    for r in rows:
        out.setdefault(r.employee_id, (float(r.rating), r.cycle_name))
    return out


def _discipline(employee_ids):
    out = defaultdict(lambda: {"points": 0, "cases": 0})
    if not employee_ids:
        return out
    for c in DisciplineCase.query.filter(DisciplineCase.employee_id.in_(employee_ids),
                                         or_(DisciplineCase.status.is_(None), DisciplineCase.status != "Resolved")).all():
        d = out[c.employee_id]
        d["cases"] += 1
        d["points"] = min(DISCIPLINE_CAP, d["points"] + DISCIPLINE_POINTS.get(c.severity, 2))
    return out


# ─────────────────────────────── scoring ───────────────────────────────

def _pickup_score(hours):
    if hours <= PICKUP_BEST_H:
        return 100.0
    if hours >= PICKUP_WORST_H:
        return 0.0
    return 100.0 * (PICKUP_WORST_H - hours) / (PICKUP_WORST_H - PICKUP_BEST_H)


def _score_one(raw, median_done, appraisal, disc):
    parts = {}

    def put(k, v, detail):
        parts[k] = {"label": LABELS[k], "weight": WEIGHTS[k], "score": None if v is None else round(max(0.0, min(100.0, v)), 1),
                    "detail": detail}

    put("onTime", 100.0 * raw["onTime"] / raw["due"] if raw["due"] else None,
        f"{raw['onTime']} of {raw['due']} on time" if raw["due"] else "Nothing was due")
    if raw["done"]:
        q = 100.0 * (1 - raw["errors"] / raw["done"])
    else:
        q = 0.0 if raw["errors"] else None
    put("quality", q, f"{raw['errors']} error(s) in {raw['done']} completed"
        + (f" · {raw['reopened']} reopened, {raw['rejected']} sent back" if raw["errors"] else ""))
    active = raw["due"] or raw["done"] or raw["backlogBase"]
    if active and median_done:
        tp = 100.0 * raw["done"] / median_done
    elif active:
        tp = 100.0 if raw["done"] else None
    else:
        tp = None
    put("throughput", tp, f"{raw['done']} completed (team median {median_done:g})" if active else "No work recorded")
    put("backlog", 100.0 * (1 - raw["overdueOpen"] / raw["backlogBase"]) if raw["backlogBase"] else None,
        f"{raw['overdueOpen']} overdue of {raw['backlogBase']}" if raw["backlogBase"] else "No due work")
    ph = raw["pickupHours"]
    avg = sum(ph) / len(ph) if ph else None
    put("pickup", _pickup_score(avg) if ph else None, f"avg {avg:.1f} h to start" if ph else "No hand-offs received")
    put("appraisal", appraisal[0] * 20 if appraisal else None,
        f"Rating {appraisal[0]:g}/5{f' ({appraisal[1]})' if appraisal and appraisal[1] else ''}" if appraisal else "No rated review")

    avail = [p for p in parts.values() if p["score"] is not None]
    base = (sum(p["score"] * p["weight"] for p in avail) / sum(p["weight"] for p in avail)) if avail else None
    deduction = disc["points"] if disc else 0
    score = None if base is None else round(max(0.0, min(100.0, base - deduction)), 1)
    items = raw["due"] + raw["done"]
    return {
        "score": score,
        "grade": grade_for(score),
        "components": parts,
        "deduction": {"points": deduction, "openCases": disc["cases"] if disc else 0},
        "counts": {k: raw[k] for k in ("due", "onTime", "done", "errors", "reopened", "rejected", "overdueOpen")},
        "lowData": score is not None and items < LOW_DATA_ITEMS and not appraisal,
    }


def compute_period(period, start, end, subjects=None):
    """Score every subject for one period. Returns {key: row}."""
    subjects = subjects or _subjects()
    raw = _collect(start, end)
    emp_ids = [s["employeeId"] for s in subjects.values() if s["employeeId"]]
    apps, disc = _appraisals(emp_ids), _discipline(emp_ids)

    done_counts = [r["done"] for r in raw.values() if r["done"] > 0]
    median_done = statistics.median(done_counts) if done_counts else 0

    out = {}
    for key, s in subjects.items():
        r = raw.get(s["userId"]) if s["userId"] else None
        if s["employeeId"] is None and r is None:
            continue                                     # plain login user with no MIS work → not listed
        res = _score_one(r or _blank(), median_done, apps.get(s["employeeId"]), disc.get(s["employeeId"]))
        out[key] = {**s, **res, "period": period, "periodStart": start.isoformat(), "periodEnd": end.isoformat(),
                    "periodLabel": period_label(period, start)}
    return out


# ─────────────────────────────── snapshots ─────────────────────────────

def save_snapshot(period, start, end, rows):
    now = datetime.utcnow()
    existing = {r.subject_key: r for r in EmployeePerformanceScore.query.filter_by(
        period_type=period, period_start=start).all()}
    for key, row in rows.items():
        snap = existing.get(key) or EmployeePerformanceScore(subject_key=key, period_type=period, period_start=start)
        snap.period_end = end
        snap.employee_id, snap.user_id = row["employeeId"], row["userId"]
        snap.score, snap.grade = row["score"], row["grade"]
        snap.components = {"components": row["components"], "deduction": row["deduction"],
                           "counts": row["counts"], "lowData": row["lowData"]}
        snap.computed_at = now
        db.session.add(snap)
    db.session.commit()


def _from_snapshot(snap, subject, period):
    c = snap.components or {}
    return {**subject, "score": float(snap.score) if snap.score is not None else None, "grade": snap.grade,
            "components": c.get("components", {}), "deduction": c.get("deduction", {}),
            "counts": c.get("counts", {}), "lowData": c.get("lowData", False),
            "period": period, "periodStart": snap.period_start.isoformat(), "periodEnd": snap.period_end.isoformat(),
            "periodLabel": period_label(period, snap.period_start)}


def scores_for(period, anchor=None, subjects=None):
    """All subjects for the period containing `anchor`. Live for the current period, cached for closed ones."""
    start, end = period_bounds(period, anchor)
    subjects = subjects or _subjects()
    if end < date.today():
        snaps = EmployeePerformanceScore.query.filter_by(period_type=period, period_start=start).all()
        if snaps:
            by_key = {s.subject_key: s for s in snaps}
            if all(k in by_key for k in subjects if subjects[k]["employeeId"]):
                return {k: _from_snapshot(by_key[k], subjects[k], period) for k in subjects if k in by_key}
        rows = compute_period(period, start, end, subjects)
        save_snapshot(period, start, end, rows)
        return rows
    return compute_period(period, start, end, subjects)


def trend_for(subject_key, period, count=6, anchor=None, subjects=None):
    """Last `count` periods for one subject, oldest first."""
    subjects = subjects or _subjects()
    start, _ = period_bounds(period, anchor)
    starts = [start]
    for _ in range(count - 1):
        starts.append(previous_period(period, starts[-1])[0])
    out = []
    for st in reversed(starts):
        row = scores_for(period, st, subjects).get(subject_key)
        out.append({"periodStart": st.isoformat(), "periodLabel": period_label(period, st),
                    "score": row["score"] if row else None, "grade": row["grade"] if row else "No data"})
    return out


def subject_for_user(user_id, subjects=None):
    subjects = subjects or _subjects()
    for s in subjects.values():
        if s["userId"] == user_id:
            return s
    u = User.query.get(user_id)
    if not u:
        return None
    return {"key": f"u{u.id}", "employeeId": None, "userId": u.id, "name": u.username, "empCode": u.emp_code,
            "department": None, "designation": None}


def nightly_refresh():
    """Scheduler job: save this and the previous month / week (late completions change last period too)."""
    subjects = _subjects()
    today = date.today()
    for period in PERIODS:
        cur = period_bounds(period, today)
        prev = previous_period(period, cur[0])
        for start, end in (prev, cur):
            save_snapshot(period, start, end, compute_period(period, start, end, subjects))


# ─────────────────────────────── API layer ─────────────────────────────

from flask_jwt_extended import get_jwt                      # noqa: E402
from app.response import res                                # noqa: E402

# performance_appraisal = HR → Performance Appraisal menu; employee_management = Employee Master menu;
# employee_master = key the older review/discipline endpoints check
_HR_KEYS = ("performance_appraisal", "employee_management", "employee_master")


def _is_super(user_id):
    u = User.query.get(user_id)
    return bool(u and u.global_role and u.global_role.name == "super_admin")


def can_view_all(user_id, action="VIEW"):
    """HR: super admin, or performance_appraisal / employee_master permission in the current project token."""
    if _is_super(user_id):
        return True
    perms = (get_jwt() or {}).get("permissions") or {}
    return any(perms.get(f"{k}.EDIT") or (action == "VIEW" and perms.get(f"{k}.VIEW")) for k in _HR_KEYS)


def _args(args):
    period = (args.get("period") or "month").lower()
    if period not in PERIODS:
        return None, None, res("period must be month or week", [], 400)
    anchor = None
    if args.get("date"):
        try:
            anchor = datetime.strptime(args["date"][:10], "%Y-%m-%d").date()
        except ValueError:
            return None, None, res("date must be YYYY-MM-DD", [], 400)
    return period, anchor, None


def _row_for(subject, period, anchor, subjects):
    row = scores_for(period, anchor, subjects).get(subject["key"])
    if row:
        return row
    start, end = period_bounds(period, anchor)
    return {**subject, **_score_one(_blank(), 0, None, None), "period": period, "periodStart": start.isoformat(),
            "periodEnd": end.isoformat(), "periodLabel": period_label(period, start)}


def config():
    return res("ok", {"weights": WEIGHTS, "labels": LABELS, "grades": [{"min": f, "grade": g} for f, g in GRADES],
                      "disciplinePoints": DISCIPLINE_POINTS, "disciplineCap": DISCIPLINE_CAP,
                      "pickup": {"bestHours": PICKUP_BEST_H, "worstHours": PICKUP_WORST_H}})


def my_score(args, user_id):
    user_id = int(user_id)
    period, anchor, err = _args(args)
    if err:
        return err
    subjects = _subjects()
    subj = subject_for_user(user_id, subjects)
    if not subj:
        return res("User not found", [], 404)
    row = _row_for(subj, period, anchor, subjects)
    row["trend"] = trend_for(subj["key"], period, 6, anchor, subjects)
    return res("ok", row)


def list_scores(args, user_id):
    user_id = int(user_id)
    if not can_view_all(user_id):
        return res("You do not have permission to view performance scores", [], 403)
    period, anchor, err = _args(args)
    if err:
        return err
    subjects = _subjects()
    rows = list(scores_for(period, anchor, subjects).values())
    dept = (args.get("department") or "").strip()
    search = (args.get("search") or "").strip().lower()
    grade = (args.get("grade") or "").strip()
    if dept:
        rows = [r for r in rows if (r.get("department") or "") == dept]
    if search:
        rows = [r for r in rows if search in (r.get("name") or "").lower() or search in (r.get("empCode") or "").lower()]
    if grade:
        rows = [r for r in rows if r["grade"] == grade]
    rows.sort(key=lambda r: (r["score"] is None, -(r["score"] or 0), r.get("name") or ""))

    # previous period, for the ▲▼ change column
    prev_start, _ = previous_period(period, period_bounds(period, anchor)[0])
    prev = scores_for(period, prev_start, subjects)
    for r in rows:
        p = prev.get(r["key"])
        r["previousScore"] = p["score"] if p else None
        r["change"] = round(r["score"] - p["score"], 1) if p and p["score"] is not None and r["score"] is not None else None

    scored = [r["score"] for r in rows if r["score"] is not None]
    start, end = period_bounds(period, anchor)
    return res("ok", {
        "period": period, "periodStart": start.isoformat(), "periodEnd": end.isoformat(),
        "periodLabel": period_label(period, start),
        "summary": {
            "people": len(rows), "scored": len(scored),
            "average": round(sum(scored) / len(scored), 1) if scored else None,
            "byGrade": {g: sum(1 for r in rows if r["grade"] == g) for _, g in GRADES} | {"No data": sum(1 for r in rows if r["score"] is None)},
        },
        "items": rows,
    })


def subject_score(subject_key, args, user_id):
    """One person's score + 6-period trend. HR, or the person themself."""
    user_id = int(user_id)
    period, anchor, err = _args(args)
    if err:
        return err
    subjects = _subjects()
    subj = subjects.get(subject_key)
    if not subj and subject_key.startswith("u") and subject_key[1:].isdigit():
        subj = subject_for_user(int(subject_key[1:]), subjects)
    if not subj:
        return res("Not found", [], 404)
    if subj["userId"] != user_id and not can_view_all(user_id):
        return res("You do not have permission to view this score", [], 403)
    row = _row_for(subj, period, anchor, subjects)
    row["trend"] = trend_for(subj["key"], period, 6, anchor, subjects)
    return res("ok", row)


def recompute(args, user_id):
    user_id = int(user_id)
    if not can_view_all(user_id, "EDIT"):
        return res("You do not have permission to recalculate scores", [], 403)
    period, anchor, err = _args(args)
    if err:
        return err
    start, end = period_bounds(period, anchor)
    rows = compute_period(period, start, end)
    save_snapshot(period, start, end, rows)
    return res("Scores recalculated", {"period": period, "periodStart": start.isoformat(), "count": len(rows)})
