"""
MIS — Sprints (weekly / monthly time boxes, per project or company-level).

  * Anyone who can see the project (member / super admin) sees its sprints;
    company-level sprints are visible to everyone.
  * Supervisors (task_tracker.EDIT) create / start / close them.
  * One Active sprint per project + type at a time.
"""
import calendar
from collections import defaultdict
from datetime import date, datetime, timedelta

from sqlalchemy import or_

from app.extensions import db
from app.response import res
from app.models.misFollowup import MisSprint, MisFollowup, SPRINT_TYPES
from app.modules.mis.common import (
    MisError, api, uid, parse_date, choice, project_by_code, is_super, member_project_ids,
    can_supervise_project, can_manage_sprints, log_activity,
)

ENTITY = "sprint"


def _visible_q(user_id):
    q = MisSprint.query.filter(MisSprint.is_deleted.is_(False))
    if is_super(user_id):
        return q
    pids = member_project_ids(user_id)
    return q.filter(or_(MisSprint.project_id.is_(None), MisSprint.project_id.in_(pids or {-1})))


def _get(sprint_id, user_id):
    s = _visible_q(user_id).filter(MisSprint.id == sprint_id).first()
    if not s:
        raise MisError("Sprint not found", 404)
    return s


def _require_supervisor(user_id, project_id):
    if not can_manage_sprints(user_id, project_id):
        raise MisError("Only a supervisor (Task Tracker edit or Sprint Admin permission) can manage sprints here", 403)


def _default_window(sprint_type, start):
    if sprint_type == "Monthly":
        start = start.replace(day=1)
        return start, start.replace(day=calendar.monthrange(start.year, start.month)[1])
    start = start - timedelta(days=start.weekday())          # Monday
    return start, start + timedelta(days=6)


def _default_name(sprint_type, start):
    if sprint_type == "Monthly":
        return start.strftime("%b %Y")
    return f"Week {start.isocalendar()[1]} · {start.strftime('%d %b %Y')}"


def _counts(sprint_ids):
    """{sprint_id: {agendaCount, doneCount, points, donePoints}}"""
    out = defaultdict(lambda: {"agendaCount": 0, "doneCount": 0, "points": 0, "donePoints": 0})
    if not sprint_ids:
        return out
    rows = (db.session.query(MisFollowup.sprint_id, MisFollowup.board_status, MisFollowup.story_points)
            .filter(MisFollowup.sprint_id.in_(sprint_ids), MisFollowup.is_deleted.is_(False)).all())
    for sid, st, pts in rows:
        c = out[sid]
        c["agendaCount"] += 1
        c["points"] += pts or 0
        if st == "Done":
            c["doneCount"] += 1
            c["donePoints"] += pts or 0
    return out


@api
def list_sprints(args, user_id):
    user_id = uid(user_id)
    q = _visible_q(user_id)
    code = args.get("projectCode")
    if code:
        p = project_by_code(code)
        q = q.filter(MisSprint.project_id == (p.id if p else None)) if p else q.filter(MisSprint.project_id.is_(None))
    if args.get("status"):
        q = q.filter(MisSprint.status.in_([s for s in args["status"].split(",") if s]))
    if args.get("sprintType"):
        q = q.filter(MisSprint.sprint_type == choice(args["sprintType"], SPRINT_TYPES, "sprintType"))
    rows = q.order_by(MisSprint.start_date.desc(), MisSprint.id.desc()).limit(200).all()
    counts = _counts([s.id for s in rows])
    return res("ok", [s.to_dict(counts[s.id]) for s in rows])


@api
def get_sprint(sprint_id, user_id):
    user_id = uid(user_id)
    s = _get(sprint_id, user_id)
    out = s.to_dict(_counts([s.id])[s.id])
    out["canManage"] = can_manage_sprints(user_id, s.project_id)
    return res("ok", out)


@api
def create_sprint(data, user_id):
    user_id = uid(user_id)
    project = project_by_code(data.get("projectCode"))
    _require_supervisor(user_id, project.id if project else None)
    stype = choice(data.get("sprintType") or "Weekly", SPRINT_TYPES, "sprintType")

    start = parse_date(data.get("startDate"), "startDate") or date.today()
    end = parse_date(data.get("endDate"), "endDate")
    if end is None:
        start, end = _default_window(stype, start)
    if end < start:
        raise MisError("End date cannot be before start date")
    if (end - start).days > 92:
        raise MisError("A sprint can be at most 3 months long")

    name = (data.get("name") or "").strip() or _default_name(stype, start)
    s = MisSprint(name=name[:120], sprint_type=stype, start_date=start, end_date=end,
                  goal=data.get("goal") or None, project_id=project.id if project else None,
                  created_by=user_id, status="Planned")
    db.session.add(s)
    db.session.flush()
    s.sprint_code = f"SPR-{start.year}-{s.id:05d}"
    log_activity(ENTITY, s.id, user_id, "CREATED", new=s.name)
    if data.get("start"):
        _start(s, user_id)
    db.session.commit()
    return res("Sprint created", s.to_dict(_counts([s.id])[s.id]), 201)


@api
def update_sprint(sprint_id, data, user_id):
    user_id = uid(user_id)
    s = _get(sprint_id, user_id)
    _require_supervisor(user_id, s.project_id)
    if s.status == "Closed":
        raise MisError("A closed sprint cannot be changed")
    if "name" in data:
        name = (data.get("name") or "").strip()
        if not name:
            raise MisError("Name is required")
        s.name = name[:120]
    if "goal" in data:
        s.goal = data.get("goal") or None
    if "startDate" in data:
        s.start_date = parse_date(data["startDate"], "startDate", required=True)
    if "endDate" in data:
        s.end_date = parse_date(data["endDate"], "endDate", required=True)
    if s.end_date < s.start_date:
        raise MisError("End date cannot be before start date")
    log_activity(ENTITY, s.id, user_id, "UPDATED")
    db.session.commit()
    return res("Sprint updated", s.to_dict(_counts([s.id])[s.id]))


def _start(s, user_id):
    if s.status != "Planned":
        raise MisError("Only a planned sprint can be started")
    clash = MisSprint.query.filter(
        MisSprint.id != s.id, MisSprint.is_deleted.is_(False), MisSprint.status == "Active",
        MisSprint.sprint_type == s.sprint_type,
        MisSprint.project_id.is_(None) if s.project_id is None else MisSprint.project_id == s.project_id,
    ).first()
    if clash:
        raise MisError(f"{clash.name} is already active. Close it first.", 409)
    s.status = "Active"
    log_activity(ENTITY, s.id, user_id, "STATUS", old="Planned", new="Active")


@api
def start_sprint(sprint_id, user_id):
    user_id = uid(user_id)
    s = _get(sprint_id, user_id)
    _require_supervisor(user_id, s.project_id)
    _start(s, user_id)
    db.session.commit()
    return res("Sprint started", s.to_dict(_counts([s.id])[s.id]))


@api
def close_sprint(sprint_id, data, user_id):
    """Close and move unfinished agendas to the backlog (default) or another open sprint."""
    user_id = uid(user_id)
    s = _get(sprint_id, user_id)
    _require_supervisor(user_id, s.project_id)
    if s.status == "Closed":
        raise MisError("Sprint is already closed")

    move_to = data.get("moveTo") or "backlog"
    target = None
    if move_to != "backlog":
        target = _get(int(move_to) if str(move_to).isdigit() else -1, user_id)
        if target.id == s.id or target.status == "Closed" or target.project_id != s.project_id:
            raise MisError("Unfinished items can only move to another open sprint of the same project")

    moved = 0
    for f in MisFollowup.query.filter(MisFollowup.sprint_id == s.id, MisFollowup.is_deleted.is_(False),
                                      MisFollowup.board_status != "Done").all():
        f.sprint_id = target.id if target else None
        if not target and f.board_status == "To Do" and f.active_step is None:
            f.board_status = "Backlog"
        log_activity("followup", f.id, user_id, "SPRINT", old=s.name, new=target.name if target else "Backlog")
        moved += 1

    # Boards work items: final burndown snapshot, then unfinished PBIs / Bugs / Tasks carry over
    from app.modules.mis.workitem import planning
    moved_wi = planning.carry_over(s, target, user_id)

    old = s.status
    s.status = "Closed"
    s.closed_at = datetime.utcnow()
    log_activity(ENTITY, s.id, user_id, "STATUS", old=old, new="Closed",
                 comment=f"{moved} unfinished item(s) and {moved_wi} work item(s) moved to "
                         f"{target.name if target else 'Backlog'}")
    db.session.commit()
    out = s.to_dict(_counts([s.id])[s.id])
    out["movedCount"] = moved
    out["movedWorkItems"] = moved_wi
    return res("Sprint closed", out)


@api
def delete_sprint(sprint_id, user_id):
    user_id = uid(user_id)
    s = _get(sprint_id, user_id)
    _require_supervisor(user_id, s.project_id)
    from app.modules.mis.workitem import planning
    if MisFollowup.query.filter(MisFollowup.sprint_id == s.id, MisFollowup.is_deleted.is_(False)).count() \
            or planning.sprint_has_work_items(s.id):
        raise MisError("Move or remove this sprint's items before deleting it")
    s.is_deleted = True
    log_activity(ENTITY, s.id, user_id, "DELETED")
    db.session.commit()
    return res("Sprint deleted", [])


@api
def sprint_report(sprint_id, user_id):
    """Planned vs done, daily burndown (items + points), per-person relay stats."""
    user_id = uid(user_id)
    s = _get(sprint_id, user_id)
    items = MisFollowup.query.filter(MisFollowup.sprint_id == s.id, MisFollowup.is_deleted.is_(False)).all()
    today = date.today()

    total_items = len(items)
    total_pts = sum(f.story_points or 0 for f in items)
    done = [f for f in items if f.board_status == "Done"]

    # burndown: remaining at the end of each day of the sprint
    days = (s.end_date - s.start_date).days + 1
    burndown = []
    for i in range(days):
        d = s.start_date + timedelta(days=i)
        ideal_items = round(total_items * (1 - (i + 1) / days), 2)
        ideal_pts = round(total_pts * (1 - (i + 1) / days), 2)
        row = {"date": d.isoformat(), "idealItems": ideal_items, "idealPoints": ideal_pts}
        if d <= today:
            open_items = [f for f in items if not (f.closed_at and f.closed_at.date() <= d)]
            row["remainingItems"] = len(open_items)
            row["remainingPoints"] = sum(f.story_points or 0 for f in open_items)
        burndown.append(row)

    # per person (steps inside this sprint)
    people = {}
    for f in items:
        for st in f.steps:
            if st.status in ("Reassigned", "Cancelled"):
                continue
            p = people.setdefault(st.assignee_user_id, {
                "userId": st.assignee_user_id,
                "name": st.assignee.username if st.assignee else None,
                "assigned": 0, "done": 0, "open": 0, "onTime": 0, "late": 0, "rework": 0,
                "pickupHours": [],
            })
            p["assigned"] += 1
            if st.is_rework:
                p["rework"] += 1
            if st.status == "Done":
                p["done"] += 1
                if st.on_time is True:
                    p["onTime"] += 1
                elif st.on_time is False:
                    p["late"] += 1
            elif st.status in ("Pending", "In Progress"):
                p["open"] += 1
            if st.started_at and st.assigned_at:
                p["pickupHours"].append((st.started_at - st.assigned_at).total_seconds() / 3600)
    per_person = []
    for p in people.values():
        hrs = p.pop("pickupHours")
        judged = p["onTime"] + p["late"]
        p["onTimePct"] = round(100 * p["onTime"] / judged) if judged else None
        p["avgPickupHours"] = round(sum(hrs) / len(hrs), 1) if hrs else None
        per_person.append(p)
    per_person.sort(key=lambda x: (-x["done"], x["name"] or ""))

    return res("ok", {
        "sprint": s.to_dict(),
        "summary": {
            "items": total_items, "doneItems": len(done),
            "points": total_pts, "donePoints": sum(f.story_points or 0 for f in done),
            "byStatus": {st: sum(1 for f in items if f.board_status == st)
                         for st in ("Backlog", "To Do", "In Progress", "Review", "Done")},
            "overdue": sum(1 for f in items if f.is_overdue(today)),
            "completionPct": round(100 * len(done) / total_items) if total_items else 0,
        },
        "burndown": burndown,
        "people": per_person,
    })
