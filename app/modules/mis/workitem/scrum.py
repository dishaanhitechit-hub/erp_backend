"""
MIS Boards — Scrum ceremonies and saved queries.

  * Daily stand-up  — per person in a sprint: what moved since the previous working day,
                      what is in progress now, what is blocked.
  * Retrospective   — cards per sprint (went_well / improve / action); an action can become a
                      backlog PBI (linked back to the card). Any project member adds cards;
                      the author or a sprint manager removes them.
  * Saved queries   — named filters (same keys as GET /mis/work-items) + columns; private or
                      shared with the project. The owner edits / deletes.
"""
from collections import defaultdict
from datetime import datetime, timedelta, timezone, time as _time

from app.extensions import db
from app.response import res
from app.models.misTask import (
    MisTask, MisActivity, MisRetroItem, MisSavedQuery, RETRO_CATEGORIES, OPEN_STATUSES, APP_TZ,
)
from app.models.user import User
from app.modules.mis.common import (
    MisError, api, uid, parse_int, choice, project_by_code, is_all, is_member, is_super, can_manage_sprints,
    log_activity,
)
from app.modules.mis.workitem import service as wi
from app.modules.mis.workitem import planning

QUERY_KEYS = ("type", "state", "sprintId", "parentId", "assignedTo", "tag", "blocked", "search",
              "dueFrom", "dueTo", "openOnly")
QUERY_COLUMNS = ("code", "type", "title", "state", "assignedTo", "priority", "effort", "sprint",
                 "parent", "dueDate", "tags", "createdAt")


def _sprint(sprint_id, user_id):
    return planning._sprint(sprint_id, user_id)


def _utc(local_dt):
    """Naive local office datetime → naive UTC (how timestamps are stored)."""
    return local_dt.replace(tzinfo=APP_TZ).astimezone(timezone.utc).replace(tzinfo=None)


def _previous_work_day(day):
    wd = planning._work_days()
    d = day - timedelta(days=1)
    for _ in range(7):
        if d.weekday() in wd:
            return d
        d -= timedelta(days=1)
    return day - timedelta(days=1)


# ─────────────────────────────── stand-up ──────────────────────────────

STANDUP_ACTIONS = ("STATUS", "STARTED", "COMMENT", "REOPENED")


@api
def standup(sprint_id, args, user_id):
    """GET /mis/sprints/<id>/standup — per person: since (prev working day → now), now, blocked."""
    user_id = uid(user_id)
    s = _sprint(sprint_id, user_id)
    today = planning._local_today()
    since_day = _previous_work_day(today)
    since = _utc(datetime.combine(since_day, _time.min))

    items = MisTask.query.filter(MisTask.sprint_id == s.id, MisTask.is_deleted.is_(False)).all()
    by_id = {t.id: t for t in items}
    acts = (MisActivity.query.filter(MisActivity.entity_type == wi.ENTITY,
                                     MisActivity.entity_id.in_(list(by_id) or [-1]),
                                     MisActivity.action.in_(STANDUP_ACTIONS),
                                     MisActivity.created_at >= since)
            .order_by(MisActivity.created_at.asc()).all())

    people = defaultdict(lambda: {"done": [], "moved": [], "inProgress": [], "toDo": [], "blocked": [],
                                  "comments": 0, "remainingHours": 0.0})
    seen = defaultdict(set)
    for a in acts:
        t = by_id.get(a.entity_id)
        if not t or not a.user_id:
            continue
        p = people[a.user_id]
        if a.action == "COMMENT":
            p["comments"] += 1
            continue
        if a.action in ("STATUS", "STARTED") and a.new_value == "Done":
            if t.id not in seen[(a.user_id, "done")]:
                seen[(a.user_id, "done")].add(t.id)
                p["done"].append(wi._summary(t))
        elif a.action in ("STATUS", "STARTED", "REOPENED"):      # state changes only (a Kanban move logs one too)
            prev = next((m for m in p["moved"] if m["id"] == t.id), None)
            if prev:
                prev["to"] = a.new_value                     # earliest "from" → latest "to"
            else:
                p["moved"].append({**wi._summary(t), "from": a.old_value, "to": a.new_value})

    for t in items:
        p = people[t.owner_user_id]
        if t.is_blocked and t.status not in ("Done", "Removed", "Cancelled"):
            p["blocked"].append({**wi._summary(t), "reason": t.blocked_reason})
        if t.work_item_type == "Task":
            if t.status in ("In Progress", "On Hold"):
                p["inProgress"].append({**wi._summary(t), "remainingHours": float(t.remaining_hours or 0),
                                        "isRunning": t.run_started_at is not None})
            elif t.status == "To Do":
                p["toDo"].append(wi._summary(t))
            if t.status in OPEN_STATUSES:
                p["remainingHours"] += float(t.remaining_hours or 0)
        elif t.status in ("Approved", "Committed", "In Progress"):
            p["inProgress"].append(wi._summary(t))

    users = {u.id: u for u in User.query.filter(User.id.in_(list(people) or [-1])).all()}
    out = []
    for pid, p in people.items():
        u = users.get(pid)
        if not u:
            continue
        p["moved"] = [x for x in p["moved"] if x["id"] not in {d["id"] for d in p["done"]}]
        p["remainingHours"] = round(p["remainingHours"], 2)
        out.append({"userId": pid, "name": u.username, "empCode": u.emp_code, **p})
    out.sort(key=lambda x: (-len(x["blocked"]), (x["name"] or "").lower()))
    return res("ok", {"sprint": s.to_dict(), "since": since_day.isoformat(), "today": today.isoformat(),
                      "people": out})


# ─────────────────────────────── retrospective ─────────────────────────

def _require_member(user_id, project_id):
    if project_id is not None and not is_super(user_id) and not is_member(user_id, project_id):
        raise MisError("You are not a member of this project", 403)


@api
def retro_list(sprint_id, user_id):
    user_id = uid(user_id)
    s = _sprint(sprint_id, user_id)
    rows = (MisRetroItem.query.filter_by(sprint_id=s.id, is_deleted=False)
            .order_by(MisRetroItem.created_at.asc(), MisRetroItem.id.asc()).all())
    manage = can_manage_sprints(user_id, s.project_id)
    items = []
    for r in rows:
        d = r.to_dict()
        w = MisTask.query.filter_by(id=r.work_item_id, is_deleted=False).first() if r.work_item_id else None
        d["workItem"] = wi._summary(w) if w else None
        d["canDelete"] = manage or r.author_id == user_id
        items.append(d)
    return res("ok", {"sprint": s.to_dict(), "items": items, "categories": list(RETRO_CATEGORIES)})


@api
def retro_add(sprint_id, data, user_id):
    user_id = uid(user_id)
    s = _sprint(sprint_id, user_id)
    _require_member(user_id, s.project_id)
    cat = choice(data.get("category"), RETRO_CATEGORIES, "category")
    text = (data.get("text") or "").strip()
    if not text:
        raise MisError("Write something")
    r = MisRetroItem(sprint_id=s.id, category=cat, text=text[:2000], author_id=user_id)
    db.session.add(r)
    db.session.commit()
    return res("Added", {**r.to_dict(), "workItem": None, "canDelete": True}, 201)


def _retro(item_id, sprint_id, user_id):
    s = _sprint(sprint_id, user_id)
    r = MisRetroItem.query.filter_by(id=item_id, sprint_id=s.id, is_deleted=False).first()
    if not r:
        raise MisError("Retro card not found", 404)
    return s, r


@api
def retro_delete(sprint_id, item_id, user_id):
    user_id = uid(user_id)
    s, r = _retro(item_id, sprint_id, user_id)
    if r.author_id != user_id and not can_manage_sprints(user_id, s.project_id):
        raise MisError("Only the author or a sprint manager can remove this card", 403)
    r.is_deleted = True
    db.session.commit()
    return res("Removed", [])


@api
def retro_to_backlog(sprint_id, item_id, data, user_id):
    """Turn an action card into a backlog PBI (owner = caller unless assignedTo)."""
    user_id = uid(user_id)
    s, r = _retro(item_id, sprint_id, user_id)
    _require_member(user_id, s.project_id)
    if r.category != "action":
        raise MisError("Only an action card becomes a backlog item")
    if r.work_item_id:
        raise MisError("This action is already on the backlog", 409)
    from app.models.project import Project
    proj = Project.query.get(s.project_id) if s.project_id else None
    body = {"workItemType": "PBI", "title": (data.get("title") or r.text)[:200],
            "description": f"From the retrospective of {s.name}:\n{r.text}",
            "projectCode": proj.project_code if proj else None, "tags": ["retro"]}
    if data.get("assignedTo"):
        body["assignedTo"] = data["assignedTo"]
    payload, code = wi.create_item(body, user_id)     # same rules / code / notify as a normal create
    if code != 201:
        return payload, code
    item = payload["data"]
    r.work_item_id = item["id"]
    log_activity(wi.ENTITY, item["id"], user_id, "CREATED", comment=f"From retro of {s.name}")
    db.session.commit()
    return res("Added to the backlog", {**r.to_dict(), "workItem": {"id": item["id"], "code": item["taskCode"],
                                                                    "title": item["title"],
                                                                    "workItemType": "PBI", "state": item["state"]}}, 201)


# ─────────────────────────────── saved queries ─────────────────────────

def _clean_query(data):
    name = (data.get("name") or "").strip()
    if not name or len(name) > 120:
        raise MisError("Name must be 1–120 characters")
    filters = data.get("filters") or {}
    if not isinstance(filters, dict):
        raise MisError("filters must be an object")
    bad = [k for k in filters if k not in QUERY_KEYS]
    if bad:
        raise MisError(f"Unknown filter(s): {', '.join(bad)}")
    filters = {k: v for k, v in filters.items() if v not in (None, "", [])}
    columns = data.get("columns") or []
    if not isinstance(columns, list) or any(c not in QUERY_COLUMNS for c in columns):
        raise MisError(f"columns must be from: {', '.join(QUERY_COLUMNS)}")
    return name, filters, columns


def _visible_queries(user_id, project_id):
    q = MisSavedQuery.query.filter(MisSavedQuery.is_deleted.is_(False))
    scope = MisSavedQuery.project_id.is_(None) if project_id is None else MisSavedQuery.project_id == project_id
    return q.filter(scope, db.or_(MisSavedQuery.owner_user_id == user_id, MisSavedQuery.is_shared.is_(True)))


@api
def queries_list(args, user_id):
    user_id = uid(user_id)
    p = None if is_all(args.get("projectCode")) else project_by_code(args.get("projectCode"))
    pid = p.id if p else None
    _require_member(user_id, pid)
    rows = _visible_queries(user_id, pid).order_by(MisSavedQuery.name.asc()).all()
    return res("ok", [{**r.to_dict(), "canEdit": r.owner_user_id == user_id} for r in rows])


@api
def query_save(data, user_id, query_id=None):
    user_id = uid(user_id)
    name, filters, columns = _clean_query(data)
    if query_id:
        r = MisSavedQuery.query.filter_by(id=query_id, is_deleted=False).first()
        if not r or r.owner_user_id != user_id:
            raise MisError("Query not found", 404)
    else:
        p = None if is_all(data.get("projectCode")) else project_by_code(data.get("projectCode"))
        pid = p.id if p else None
        _require_member(user_id, pid)
        r = MisSavedQuery(owner_user_id=user_id, project_id=pid)
        db.session.add(r)
    r.name, r.filters, r.columns, r.is_shared = name, filters, columns, bool(data.get("isShared"))
    db.session.commit()
    return res("Query saved", {**r.to_dict(), "canEdit": True}, 200 if query_id else 201)


@api
def query_delete(query_id, user_id):
    user_id = uid(user_id)
    r = MisSavedQuery.query.filter_by(id=query_id, is_deleted=False).first()
    if not r or r.owner_user_id != user_id:
        raise MisError("Query not found", 404)
    r.is_deleted = True
    db.session.commit()
    return res("Query deleted", [])
