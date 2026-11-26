"""
MIS Boards — backlog & sprint planning.

  * Backlog order   — backlog_rank (float, per project). Reorder puts an item between two
                      neighbours; ranks are renumbered when the gap gets too small.
  * Bulk edit       — many items at once (sprint, state, assignee, priority, blocked); all or nothing.
  * Capacity        — hours per working day per member, minus days off (mis_sprint_capacity).
                      Working days: MIS_WORK_DAYS (0 = Mon … 6 = Sun, default Mon–Sat).
  * Snapshots       — one row per sprint per day (nightly job + on close) → burndown, velocity, CFD.
  * Sprint close    — unfinished work items move to the backlog or the next sprint.
Managing sprints / capacity: can_manage_sprints (task_tracker.EDIT or sprint_admin.EDIT).
"""
import os
from collections import defaultdict
from datetime import date, datetime, timedelta

from sqlalchemy import func

from app.extensions import db
from app.response import res
from app.models.misTask import (
    MisTask, MisSprintCapacity, MisSprintSnapshot, OPEN_STATUSES, TASK_PRIORITIES, APP_TZ,
)
from app.models.misFollowup import MisSprint
from app.models.user import User
from app.modules.mis.common import (
    MisError, api, uid, parse_int, parse_date, choice, project_by_code, is_member, is_super,
    can_manage_sprints, project_member_ids, log_activity,
)
from app.modules.mis.workitem import service as wi

POINT_TYPES = wi.POINT_TYPES
BULK_KEYS = ("sprintId", "state", "assignedTo", "priority", "isBlocked", "blockedReason")
MIN_GAP = 1e-3
DEFAULT_HOURS_PER_DAY = 6.0


def _work_days():
    raw = os.getenv("MIS_WORK_DAYS") or "0,1,2,3,4,5"
    try:
        days = {int(x) for x in raw.split(",") if x.strip() != ""}
    except ValueError:
        days = {0, 1, 2, 3, 4, 5}
    return days or {0, 1, 2, 3, 4, 5}


def _local_today():
    return datetime.now(APP_TZ).date()


def _sprint(sprint_id, user_id):
    from app.modules.mis.sprint.service import _get
    return _get(sprint_id, user_id)


def _require_manager(user_id, s):
    if not can_manage_sprints(user_id, s.project_id):
        raise MisError("Only a sprint manager (Task Tracker edit or Sprint Admin) can do this", 403)


def _sprint_days(s):
    wd = _work_days()
    return [s.start_date + timedelta(days=i) for i in range((s.end_date - s.start_date).days + 1)
            if (s.start_date + timedelta(days=i)).weekday() in wd]


# ─────────────────────────────── backlog order ─────────────────────────

def _project_q(project_id):
    q = MisTask.query.filter(MisTask.is_deleted.is_(False))
    return q.filter(MisTask.project_id.is_(None) if project_id is None else MisTask.project_id == project_id)


def _renumber(project_id):
    rows = _project_q(project_id).order_by(MisTask.backlog_rank.asc().nullslast(), MisTask.id.asc()).all()
    for i, t in enumerate(rows, start=1):
        t.backlog_rank = i * 1000.0
    db.session.flush()


def _rank_between(t, before, after):
    """New rank for `t` placed after `after` and before `before` (either may be None)."""
    pid = t.project_id
    if after is not None and before is None:
        nxt = (_project_q(pid).filter(MisTask.id != t.id, MisTask.backlog_rank > after.backlog_rank)
               .order_by(MisTask.backlog_rank.asc()).first())
        return (after.backlog_rank + nxt.backlog_rank) / 2 if nxt else after.backlog_rank + 1000.0, nxt
    if before is not None and after is None:
        prv = (_project_q(pid).filter(MisTask.id != t.id, MisTask.backlog_rank < before.backlog_rank)
               .order_by(MisTask.backlog_rank.desc()).first())
        return (prv.backlog_rank + before.backlog_rank) / 2 if prv else before.backlog_rank - 1000.0, prv
    if after.backlog_rank >= before.backlog_rank:
        raise MisError("afterId must be above beforeId on the backlog")
    return (after.backlog_rank + before.backlog_rank) / 2, None


@api
def reorder(data, user_id):
    """{ itemId, afterId?, beforeId? } — put the item right after `afterId` / right before `beforeId`."""
    user_id = uid(user_id)
    t = wi._get(parse_int(data.get("itemId"), "itemId", allow_none=False), user_id, edit=True)
    if data.get("afterId") in (None, "") and data.get("beforeId") in (None, ""):
        raise MisError("Give afterId or beforeId")

    def neighbour(key):
        if data.get(key) in (None, ""):
            return None
        n = wi._get(parse_int(data[key], key), user_id)
        if n.id == t.id:
            raise MisError(f"{key} cannot be the item itself")
        if n.project_id != t.project_id:
            raise MisError("Items can only be reordered within one project")
        if n.backlog_rank is None:
            _renumber(t.project_id)
        return n

    after, before = neighbour("afterId"), neighbour("beforeId")
    rank, other = _rank_between(t, before, after)
    lo = after.backlog_rank if after else (other.backlog_rank if other else None)
    hi = before.backlog_rank if before else (other.backlog_rank if other else None)
    if lo is not None and hi is not None and abs(hi - lo) < MIN_GAP:
        _renumber(t.project_id)
        rank, _ = _rank_between(t, before, after)
    t.backlog_rank = rank
    db.session.commit()
    return res("Reordered", {"id": t.id, "backlogRank": t.backlog_rank})


# ─────────────────────────────── bulk edit ─────────────────────────────

@api
def bulk_update(data, user_id):
    """{ ids: [..], changes: { sprintId?, state?, assignedTo?, priority?, isBlocked?, blockedReason? } }"""
    user_id = uid(user_id)
    ids = data.get("ids") or []
    if not isinstance(ids, list) or not ids:
        raise MisError("ids must be a non-empty list")
    if len(ids) > 200:
        raise MisError("At most 200 items at a time")
    changes = data.get("changes") or {}
    if not isinstance(changes, dict) or not changes:
        raise MisError("changes is required")
    bad = [k for k in changes if k not in BULK_KEYS]
    if bad:
        raise MisError(f"Cannot bulk-change: {', '.join(bad)}")
    if "priority" in changes:
        choice(changes["priority"], TASK_PRIORITIES, "priority")

    items, notify = [], []
    for raw in dict.fromkeys(ids):                    # keep order, drop duplicates
        t = wi._get(parse_int(raw, "ids"), user_id, edit=True)
        try:
            if wi._apply_update(t, dict(changes), user_id):
                notify.append(t)
        except MisError as e:
            raise MisError(f"{t.task_code}: {e.msg}", e.code)
        items.append(t)
    db.session.commit()
    for t in notify:
        wi._notify_assigned(t, user_id)
    return res(f"{len(items)} item(s) updated", [wi._out(t, user_id) for t in items])


# ─────────────────────────────── capacity ──────────────────────────────

def _open_task_hours(sprint_id):
    """{owner_user_id: remaining hours} of the sprint's unfinished Tasks."""
    rows = (db.session.query(MisTask.owner_user_id, func.coalesce(func.sum(MisTask.remaining_hours), 0))
            .filter(MisTask.sprint_id == sprint_id, MisTask.is_deleted.is_(False),
                    MisTask.work_item_type == "Task", MisTask.status.in_(OPEN_STATUSES))
            .group_by(MisTask.owner_user_id).all())
    return {u: float(h or 0) for u, h in rows}


@api
def get_capacity(sprint_id, user_id):
    user_id = uid(user_id)
    s = _sprint(sprint_id, user_id)
    days = _sprint_days(s)
    today = _local_today()
    left_days = [d for d in days if d >= today]
    saved = {c.user_id: c for c in MisSprintCapacity.query.filter_by(sprint_id=s.id).all()}
    work = _open_task_hours(s.id)

    member_ids = set(project_member_ids(s.project_id)) if s.project_id else set()
    member_ids |= set(saved) | {u for u in work if u}
    users = {u.id: u for u in User.query.filter(User.id.in_(member_ids or {-1})).all()}

    rows = []
    for mid in sorted(member_ids, key=lambda i: (users[i].username or "").lower() if i in users else ""):
        u = users.get(mid)
        if not u:
            continue
        c = saved.get(mid)
        hpd = float(c.hours_per_day) if c else DEFAULT_HOURS_PER_DAY
        off = set(c.days_off or []) if c else set()
        avail = [d for d in days if d.isoformat() not in off]
        avail_left = [d for d in left_days if d.isoformat() not in off]
        cap = round(hpd * len(avail), 2)
        cap_left = round(hpd * len(avail_left), 2)
        assigned = round(work.get(mid, 0.0), 2)
        rows.append({
            "userId": mid, "name": u.username, "empCode": u.emp_code, "isSet": c is not None,
            "hoursPerDay": hpd, "daysOff": sorted(off), "workingDays": len(avail),
            "capacityHours": cap, "remainingCapacityHours": cap_left, "assignedHours": assigned,
            "overAllocated": assigned > cap_left if s.status != "Closed" else False,
        })
    return res("ok", {
        "sprintId": s.id, "sprintName": s.name, "status": s.status,
        "workingDays": [d.isoformat() for d in days],
        "members": rows,
        "totals": {
            "capacityHours": round(sum(r["capacityHours"] for r in rows), 2),
            "remainingCapacityHours": round(sum(r["remainingCapacityHours"] for r in rows), 2),
            "assignedHours": round(sum(r["assignedHours"] for r in rows), 2),
            "unassignedHours": round(sum(h for u, h in work.items() if u not in {r["userId"] for r in rows}), 2),
        },
        "canManage": can_manage_sprints(user_id, s.project_id),
    })


@api
def set_capacity(sprint_id, data, user_id):
    """{ members: [{ userId, hoursPerDay, daysOff: ["YYYY-MM-DD"] }] } — upsert per member."""
    user_id = uid(user_id)
    s = _sprint(sprint_id, user_id)
    _require_manager(user_id, s)
    if s.status == "Closed":
        raise MisError("A closed sprint's capacity cannot be changed")
    members = data.get("members")
    if not isinstance(members, list) or not members:
        raise MisError("members must be a non-empty list")

    for m in members:
        if not isinstance(m, dict):
            raise MisError("Each member must be an object")
        u = User.query.get(parse_int(m.get("userId"), "userId", allow_none=False))
        if not u or u.is_active is False:
            raise MisError("User not found or inactive", 404)
        if s.project_id is not None and not is_member(u.id, s.project_id) and not is_super(u.id):
            raise MisError(f"{u.username} is not a member of this project")
        try:
            hpd = float(m.get("hoursPerDay"))
        except (TypeError, ValueError):
            raise MisError("hoursPerDay must be a number")
        if not 0 <= hpd <= 24:
            raise MisError("hoursPerDay must be between 0 and 24")
        off = []
        for d in m.get("daysOff") or []:
            dd = parse_date(d, "daysOff")
            if not s.start_date <= dd <= s.end_date:
                raise MisError(f"Day off {dd.isoformat()} is outside the sprint")
            off.append(dd.isoformat())
        c = MisSprintCapacity.query.filter_by(sprint_id=s.id, user_id=u.id).first()
        if not c:
            c = MisSprintCapacity(sprint_id=s.id, user_id=u.id)
            db.session.add(c)
        c.hours_per_day, c.days_off, c.updated_by = hpd, sorted(set(off)), user_id
    log_activity("sprint", s.id, user_id, "CAPACITY", new=f"{len(members)} member(s)")
    db.session.commit()
    return get_capacity(s.id, user_id)


# ─────────────────────────────── snapshots ─────────────────────────────

def compute_snapshot(sprint_id):
    rows = (MisTask.query.filter(MisTask.sprint_id == sprint_id, MisTask.is_deleted.is_(False)).all())
    counts = defaultdict(lambda: defaultdict(int))
    remaining = committed = done = 0.0
    for t in rows:
        counts[t.work_item_type][t.status] += 1
        if t.work_item_type == "Task" and t.status in OPEN_STATUSES:
            remaining += float(t.remaining_hours or 0)
        if t.work_item_type in POINT_TYPES and t.status != "Removed":
            committed += float(t.story_points or 0)
            if t.status == "Done":
                done += float(t.story_points or 0)
    return {"remaining_hours": round(remaining, 2), "committed_points": round(committed, 1),
            "done_points": round(done, 1), "state_counts": {k: dict(v) for k, v in counts.items()}}


def save_snapshot(s, day=None):
    day = day or _local_today()
    snap = MisSprintSnapshot.query.filter_by(sprint_id=s.id, snap_date=day).first()
    if not snap:
        snap = MisSprintSnapshot(sprint_id=s.id, snap_date=day)
        db.session.add(snap)
    for k, v in compute_snapshot(s.id).items():
        setattr(snap, k, v)
    return snap


def nightly_snapshots():
    """Scheduler: today's snapshot for every Active sprint."""
    day = _local_today()
    n = 0
    for s in MisSprint.query.filter_by(status="Active", is_deleted=False).all():
        save_snapshot(s, day)
        n += 1
    db.session.commit()
    return n


@api
def burndown(sprint_id, user_id):
    """Stored daily snapshots + today's live numbers + an ideal line over the working days."""
    user_id = uid(user_id)
    s = _sprint(sprint_id, user_id)
    snaps = {x.snap_date: x for x in MisSprintSnapshot.query.filter_by(sprint_id=s.id)
             .order_by(MisSprintSnapshot.snap_date.asc()).all()}
    today = _local_today()
    live = compute_snapshot(s.id)
    days = _sprint_days(s) or [s.start_date]
    start_rem = float(snaps[min(snaps)].remaining_hours) if snaps else live["remaining_hours"]

    out = []
    for i, d in enumerate(days):
        row = {"date": d.isoformat(),
               # full work on the first working day, straight down to 0 on the last
               "idealHours": round(start_rem * (1 - i / (len(days) - 1)), 2) if len(days) > 1 else 0}
        snap = snaps.get(d)
        if snap is not None:
            row.update(snap.to_dict())
        elif d == today and s.status != "Closed":
            row.update({"remainingHours": live["remaining_hours"], "committedPoints": live["committed_points"],
                        "donePoints": live["done_points"], "stateCounts": live["state_counts"], "live": True})
        out.append(row)
    return res("ok", {"sprint": s.to_dict(), "days": out,
                      "current": {"remainingHours": live["remaining_hours"],
                                  "committedPoints": live["committed_points"],
                                  "donePoints": live["done_points"], "stateCounts": live["state_counts"]}})


@api
def velocity(args, user_id):
    """Last N closed sprints of a project (final snapshot) + the active one live. ?projectCode= &count=6"""
    user_id = uid(user_id)
    if not args.get("projectCode"):
        raise MisError("projectCode is required")
    p = project_by_code(args["projectCode"])
    pid = p.id if p else None
    if pid is not None and not is_super(user_id) and not is_member(user_id, pid):
        raise MisError("You are not a member of this project", 403)
    count = min(max(parse_int(args.get("count"), "count") or 6, 1), 24)
    q = MisSprint.query.filter(MisSprint.is_deleted.is_(False),
                               MisSprint.project_id.is_(None) if pid is None else MisSprint.project_id == pid)
    closed = q.filter(MisSprint.status == "Closed").order_by(MisSprint.end_date.desc()).limit(count).all()
    rows = []
    for s in reversed(closed):
        last = (MisSprintSnapshot.query.filter_by(sprint_id=s.id)
                .order_by(MisSprintSnapshot.snap_date.desc()).first())
        rows.append({"sprintId": s.id, "name": s.name, "status": s.status,
                     "startDate": s.start_date.isoformat(), "endDate": s.end_date.isoformat(),
                     "committedPoints": float(last.committed_points) if last else 0.0,
                     "donePoints": float(last.done_points) if last else 0.0})
    for s in q.filter(MisSprint.status == "Active").all():
        live = compute_snapshot(s.id)
        rows.append({"sprintId": s.id, "name": s.name, "status": s.status,
                     "startDate": s.start_date.isoformat(), "endDate": s.end_date.isoformat(),
                     "committedPoints": live["committed_points"], "donePoints": live["done_points"]})
    done = [r["donePoints"] for r in rows if r["status"] == "Closed"]
    return res("ok", {"sprints": rows, "averageVelocity": round(sum(done) / len(done), 1) if done else None})


# ─────────────────────────────── sprint close ──────────────────────────

def carry_over(s, target, user_id):
    """Close helper: final snapshot, then unfinished PBIs/Bugs (with their open tasks) and open
    Tasks go to `target` (another open sprint) or the backlog. Done work stays. No commit."""
    save_snapshot(s)
    new_sid = target.id if target else None
    label = target.name if target else "Backlog"
    moved = 0
    rows = (MisTask.query.filter(MisTask.sprint_id == s.id, MisTask.is_deleted.is_(False)).all())
    for t in rows:
        unfinished = (t.status not in ("Done", "Removed") if t.work_item_type in POINT_TYPES
                      else t.status in OPEN_STATUSES)
        if not unfinished:
            continue
        t.sprint_id = new_sid
        log_activity(wi.ENTITY, t.id, user_id, "SPRINT", old=s.name, new=label)
        moved += 1
    return moved


def sprint_has_work_items(sprint_id):
    return MisTask.query.filter(MisTask.sprint_id == sprint_id, MisTask.is_deleted.is_(False)).count() > 0
