"""
MIS Boards — work items (Azure Boards style, Scrum process).

Hierarchy  Epic → Feature → PBI / Bug → Task   (rules: WI_PARENT_TYPES)
All types live in mis_tasks; Task rows are the same rows the Self Task page shows,
so a Task keeps the Self Task status flow (Start timer, Done lock, reopen request).

Access
  * Task            → Self Task rules (owner / creator, self_task_all VIEW/EDIT, super admin).
  * Epic/Feature/PBI/Bug (team items) → any member of the item's project may view and edit;
    company-level team items follow the Self Task rules. Delete: creator or self_task_all.EDIT.
  * Assigning a Task follows Self Task rules; a team item can go to any project member.

Follow-ups stay a separate flow; they are only *linked* (mis_work_item_links, target FOLLOWUP).
"""
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import or_, func

from app.extensions import db
from app.response import res
from app.utils.pagination import set_pagination
from app.models.misTask import (
    MisTask, MisActivity, MisWorkItemLink, TASK_PRIORITIES, WORK_ITEM_TYPES, WI_STATES,
    WI_DEFAULT_STATE, WI_PARENT_TYPES, WI_CODE_PREFIX, WI_LABEL, LINK_TARGET_TYPES, LINK_TYPES,
)
from app.models.misFollowup import MisSprint, MisFollowup
from app.models.user import User
from app.modules.mis.common import (
    MisError, api, uid, parse_int, parse_date, choice, project_by_code, is_member, is_super,
    member_project_ids, notify,
)
from app.modules.mis.task import service as task_svc

ENTITY = "task"                       # same activity stream as Self Task (one row = one item)
TEAM_TYPES = ("Epic", "Feature", "PBI", "Bug")
SPRINT_TYPES_OK = ("PBI", "Bug", "Task")
POINT_TYPES = ("PBI", "Bug")
LINK_PATH = "/task-management/boards?item={uuid}"
REVERSE_LINK = {"related": "related", "predecessor": "successor", "successor": "predecessor"}
_FIELDS = ("title", "description", "priority", "startDate", "startTime", "dueDate", "dueTime",
           "estimatedHours", "tags")


# ─────────────────────────────── access ────────────────────────────────

def _can_view(t, user_id):
    if t.work_item_type in TEAM_TYPES and t.project_id is not None:
        if is_super(user_id) or is_member(user_id, t.project_id):
            return True
    return task_svc._can(t, user_id, "VIEW")


def _can_edit(t, user_id):
    if t.work_item_type in TEAM_TYPES and t.project_id is not None:
        if is_super(user_id) or is_member(user_id, t.project_id):
            return True
    return task_svc._can(t, user_id, "EDIT")


def _can_delete(t, user_id):
    return t.created_by == user_id or task_svc._covers(task_svc._scope(user_id, "EDIT"), t)


def _get(item_id, user_id, edit=False):
    t = MisTask.query.filter_by(id=item_id, is_deleted=False).first()
    if not t or not _can_view(t, user_id):
        raise MisError("Work item not found", 404)
    if edit and not _can_edit(t, user_id):
        raise MisError("You do not have permission to edit this work item", 403)
    return t


def _visible_filter(q, user_id):
    """Rows the user may see: Self Task scope for everything + team items of member projects."""
    if is_super(user_id):
        return q
    scope = task_svc._scope(user_id, "VIEW")
    conds = [MisTask.owner_user_id == user_id, MisTask.created_by == user_id]
    if scope["users"]:
        conds.append(MisTask.owner_user_id.in_(scope["users"]))
    if scope["projects"]:
        conds.append(MisTask.project_id.in_(scope["projects"]))
    pids = member_project_ids(user_id)
    if pids:
        conds.append(db.and_(MisTask.work_item_type.in_(TEAM_TYPES), MisTask.project_id.in_(pids)))
    return q.filter(or_(*conds))


def _check_assignee(user_id, assignee, item_type, project):
    if item_type == "Task":
        if not task_svc._can_assign_to(user_id, assignee.id, project):
            raise MisError("You can only assign tasks to users you manage in this project", 403)
        return
    if assignee.id == user_id or is_super(user_id):
        return
    if project is not None and not is_member(assignee.id, project.id):
        raise MisError(f"{assignee.username} is not a member of this project", 403)
    if project is None and not task_svc._can_assign_to(user_id, assignee.id, None):
        raise MisError("You can only assign company-level items to users you manage", 403)


# ─────────────────────────────── parsing / rules ───────────────────────

def _num(v, field):
    if v in (None, ""):
        return None
    try:
        n = float(v)
    except (TypeError, ValueError):
        raise MisError(f"{field} must be a number")
    if n < 0:
        raise MisError(f"{field} cannot be negative")
    return n


def _apply_common(t, data):
    """Fields shared with Self Task (title, dates, priority, tags, estimate)."""
    try:
        task_svc._apply_fields(t, {k: data[k] for k in _FIELDS if k in data})
    except task_svc._Err as e:
        raise MisError(e.msg, e.code)


def _apply_board_fields(t, data):
    typ = t.work_item_type
    if "storyPoints" in data:
        if typ not in POINT_TYPES and data["storyPoints"] not in (None, ""):
            raise MisError("Effort points are only for an Activity or a Snag")
        t.story_points = _num(data["storyPoints"], "storyPoints")
    if "remainingHours" in data:
        if typ != "Task" and data["remainingHours"] not in (None, ""):
            raise MisError("Remaining work is only for Tasks")
        t.remaining_hours = _num(data["remainingHours"], "remainingHours")
    if "acceptanceCriteria" in data:
        if typ not in POINT_TYPES and data["acceptanceCriteria"]:
            raise MisError("Acceptance criteria are only for an Activity or a Snag")
        t.acceptance_criteria = (data.get("acceptanceCriteria") or "").strip() or None
    if "isBlocked" in data:
        t.is_blocked = bool(data["isBlocked"])
        t.blocked_reason = ((data.get("blockedReason") or "").strip() or None) if t.is_blocked else None
    elif "blockedReason" in data and t.is_blocked:
        t.blocked_reason = (data.get("blockedReason") or "").strip() or None


def _parent_for(parent_id, typ, project_id):
    if parent_id in (None, ""):
        return None
    p = MisTask.query.filter_by(id=parse_int(parent_id, "parentId"), is_deleted=False).first()
    if not p:
        raise MisError("Parent work item not found", 404)
    allowed = WI_PARENT_TYPES.get(typ, ())
    if p.work_item_type not in allowed:
        if not allowed:
            raise MisError(f"A {WI_LABEL[typ]} is the top level and cannot have a parent")
        raise MisError(f"A {WI_LABEL[typ]} can only sit under a {' or '.join(WI_LABEL[a] for a in allowed)} "
                       f"(not a {WI_LABEL[p.work_item_type]})")
    if p.project_id != project_id:
        raise MisError("The parent belongs to a different project")
    return p


def _sprint_for(sprint_id, typ, project_id):
    if sprint_id in (None, "", "backlog"):
        return None
    if typ not in SPRINT_TYPES_OK:
        raise MisError(f"A {WI_LABEL[typ]} is not planned into a sprint — plan its Activities instead")
    s = MisSprint.query.filter_by(id=parse_int(sprint_id, "sprintId"), is_deleted=False).first()
    if not s:
        raise MisError("Sprint not found", 404)
    if s.status == "Closed":
        raise MisError("That sprint is closed")
    if s.project_id != project_id:
        raise MisError("The sprint belongs to a different project")
    return s


def _next_rank(project_id):
    q = db.session.query(func.max(MisTask.backlog_rank)).filter(MisTask.is_deleted.is_(False))
    q = q.filter(MisTask.project_id.is_(None) if project_id is None else MisTask.project_id == project_id)
    return (q.scalar() or 0) + 1000.0


def _norm(v):
    """Decimal column vs float just assigned → compare as float."""
    return float(v) if isinstance(v, (Decimal, float)) else v


def _live_children(t):
    return t.children.filter(MisTask.is_deleted.is_(False))


def _set_state(t, new_state):
    """Task → Self Task status machine (timer / lock). Team items → any state of their type."""
    if t.work_item_type == "Task":
        try:
            old = task_svc._set_status(t, new_state)
        except task_svc._Err as e:
            raise MisError(e.msg, e.code)
        if old and t.status == "Done":
            t.remaining_hours = 0
        return old
    choice(new_state, WI_STATES[t.work_item_type], "state")
    old = t.status
    if old == new_state:
        return None
    t.status = new_state
    t.completed_at = datetime.utcnow() if new_state == "Done" else None
    return old


def _log(t, user_id, action, old=None, new=None, comment=None):
    db.session.add(MisActivity(entity_type=ENTITY, entity_id=t.id, user_id=user_id,
                               action=action, old_value=old, new_value=new, comment=comment))


def _notify_assigned(t, actor_id, user_id=None, state=None, event="ASSIGNED"):
    notify(user_id or t.owner_user_id, title=t.title, code=t.task_code, priority=t.priority,
           project=t.project, actor_id=actor_id, state=state or t.status,
           link_path=LINK_PATH.format(uuid=t.task_uuid), module_code="mis_work_item",
           record_id=t.id, event=event, label=WI_LABEL.get(t.work_item_type, t.work_item_type))


# ─────────────────────────────── output ────────────────────────────────

def _summary(t):
    return {"id": t.id, "uuid": t.task_uuid, "code": t.task_code, "title": t.title,
            "workItemType": t.work_item_type, "state": t.status,
            "ownerName": t.owner.username if t.owner else None}


def _out(t, user_id, today=None):
    d = t.to_dict(today)
    d["state"] = t.status
    d["childCount"] = _live_children(t).count()
    d["canEdit"] = _can_edit(t, user_id) and not (t.work_item_type == "Task" and t.is_locked)
    return d


def _link_out(link):
    d = link.to_dict()
    if link.target_type == "WORK_ITEM":
        w = MisTask.query.filter_by(id=link.target_id, is_deleted=False).first()
        d["target"] = _summary(w) if w else None
    elif link.target_type == "FOLLOWUP":
        f = MisFollowup.query.filter_by(id=link.target_id, is_deleted=False).first()
        d["target"] = ({"id": f.id, "uuid": f.fu_uuid, "code": f.fu_code, "title": f.title,
                        "boardStatus": f.board_status} if f else None)
    else:
        d["target"] = {"ref": link.target_ref}
    return d


# ─────────────────────────────── endpoints ─────────────────────────────

@api
def meta(user_id):
    return res("ok", {
        "types": list(WORK_ITEM_TYPES),
        "states": {k: list(v) for k, v in WI_STATES.items()},
        "defaultState": WI_DEFAULT_STATE,
        "parentTypes": {k: list(v) for k, v in WI_PARENT_TYPES.items()},
        "priorities": list(TASK_PRIORITIES),
        "linkTargetTypes": list(LINK_TARGET_TYPES),
        "linkTypes": list(LINK_TYPES),
        "sprintTypes": list(SPRINT_TYPES_OK),
        "pointTypes": list(POINT_TYPES),
    })


@api
def list_items(args, user_id):
    """?projectCode=<code>|company &type=a,b &state=a,b &sprintId=<id>|backlog &parentId=<id>|none
    &assignedTo=me|<id> &tag= &blocked=1 &search= &page= &limit="""
    user_id = uid(user_id)
    q = _visible_filter(MisTask.query.filter(MisTask.is_deleted.is_(False)), user_id)

    pc = args.get("projectCode")
    if pc:
        p = project_by_code(pc)
        q = q.filter(MisTask.project_id.is_(None) if p is None else MisTask.project_id == p.id)
    if args.get("type"):
        types = [x for x in args["type"].split(",") if x]
        for x in types:
            choice(x, WORK_ITEM_TYPES, "type")
        q = q.filter(MisTask.work_item_type.in_(types))
    if args.get("state"):
        q = q.filter(MisTask.status.in_([x for x in args["state"].split(",") if x]))
    sid = args.get("sprintId")
    if sid == "backlog":
        q = q.filter(MisTask.sprint_id.is_(None))
    elif sid:
        q = q.filter(MisTask.sprint_id == parse_int(sid, "sprintId"))
    pid = args.get("parentId")
    if pid == "none":
        q = q.filter(MisTask.parent_id.is_(None))
    elif pid:
        q = q.filter(MisTask.parent_id == parse_int(pid, "parentId"))
    at = args.get("assignedTo")
    if at == "me":
        q = q.filter(MisTask.owner_user_id == user_id)
    elif at:
        q = q.filter(MisTask.owner_user_id == parse_int(at, "assignedTo"))
    if str(args.get("blocked", "")).lower() in ("1", "true"):
        q = q.filter(MisTask.is_blocked.is_(True))
    search = (args.get("search") or "").strip()
    if search:
        like = f"%{search}%"
        q = q.filter(or_(MisTask.title.ilike(like), MisTask.task_code.ilike(like),
                         MisTask.description.ilike(like)))
    if args.get("dueFrom"):
        q = q.filter(MisTask.due_date >= parse_date(args["dueFrom"], "dueFrom"))
    if args.get("dueTo"):
        q = q.filter(MisTask.due_date <= parse_date(args["dueTo"], "dueTo"))
    if str(args.get("openOnly", "")).lower() in ("1", "true"):
        q = q.filter(MisTask.status.notin_(("Done", "Removed", "Cancelled")))
    tag = (args.get("tag") or "").strip()

    try:
        page = max(int(args.get("page") or 1), 1)
        per_page = min(max(int(args.get("limit") or args.get("perPage") or 100), 1), 500)
    except ValueError:
        raise MisError("page/limit must be numbers")

    q = q.order_by(MisTask.backlog_rank.asc().nullslast(), MisTask.id.asc())
    if tag:                                           # JSON list — filter in Python, keeps it DB-agnostic
        rows = [t for t in q.all() if tag in (t.tags or [])]
        total = len(rows)
        rows = rows[(page - 1) * per_page: page * per_page]
    else:
        total = q.count()
        rows = q.offset((page - 1) * per_page).limit(per_page).all()
    set_pagination(total, page, per_page)
    today = date.today()
    return res("ok", {"items": [_out(t, user_id, today) for t in rows],
                      "total": total, "page": page, "perPage": per_page})


@api
def tree(args, user_id):
    """Backlog tree for one project: Epic > Feature > PBI/Bug > Task, ordered by rank.
    ?projectCode= (required, 'company' allowed) &sprintId=<id>|backlog &includeDone=1"""
    user_id = uid(user_id)
    if not args.get("projectCode"):
        raise MisError("projectCode is required")
    p = project_by_code(args["projectCode"])
    q = _visible_filter(MisTask.query.filter(MisTask.is_deleted.is_(False)), user_id)
    q = q.filter(MisTask.project_id.is_(None) if p is None else MisTask.project_id == p.id)
    if str(args.get("includeDone", "")).lower() not in ("1", "true"):
        q = q.filter(MisTask.status.notin_(("Done", "Removed", "Cancelled")))
    rows = q.order_by(MisTask.backlog_rank.asc().nullslast(), MisTask.id.asc()).all()

    sid = args.get("sprintId")
    if sid:
        want = None if sid == "backlog" else parse_int(sid, "sprintId")
        keep = {t.id for t in rows if t.work_item_type in SPRINT_TYPES_OK and t.sprint_id == want}
        by_id = {t.id: t for t in rows}
        for t in list(rows):                          # keep the ancestors so the tree still nests
            if t.id in keep:
                pid = t.parent_id
                while pid and pid in by_id and pid not in keep:
                    keep.add(pid)
                    pid = by_id[pid].parent_id
        # tasks under a kept PBI follow it
        keep |= {t.id for t in rows if t.work_item_type == "Task" and t.parent_id in keep
                 and (sid == "backlog" or t.sprint_id == want)}
        rows = [t for t in rows if t.id in keep]

    today = date.today()
    nodes = {t.id: {**_out(t, user_id, today), "children": []} for t in rows}
    roots = []
    for t in rows:
        n = nodes[t.id]
        if t.parent_id and t.parent_id in nodes:
            nodes[t.parent_id]["children"].append(n)
        else:
            roots.append(n)
    return res("ok", roots)


@api
def get_item(item_id, user_id):
    user_id = uid(user_id)
    t = _get(item_id, user_id)
    out = _out(t, user_id)
    out["parent"] = _summary(t.parent) if t.parent and not t.parent.is_deleted else None
    out["children"] = [_summary(c) for c in _live_children(t).order_by(MisTask.backlog_rank.asc().nullslast())]
    out["links"] = [_link_out(l) for l in MisWorkItemLink.query.filter_by(work_item_id=t.id)
                    .order_by(MisWorkItemLink.id.asc()).all()]
    out["activity"] = [a.to_dict() for a in MisActivity.query.filter_by(entity_type=ENTITY, entity_id=t.id)
                       .order_by(MisActivity.created_at.desc(), MisActivity.id.desc()).all()]
    out["canDelete"] = _can_delete(t, user_id)
    return res("ok", out)


@api
def get_by_uuid(item_uuid, user_id):
    t = MisTask.query.filter_by(task_uuid=item_uuid, is_deleted=False).first()
    if not t:
        raise MisError("Work item not found", 404)
    return get_item(t.id, user_id)


@api
def create_item(data, user_id):
    user_id = uid(user_id)
    typ = choice(data.get("workItemType") or data.get("type") or "Task", WORK_ITEM_TYPES, "workItemType")
    project = project_by_code(data.get("projectCode"))
    pid = project.id if project else None
    if project is not None and not is_super(user_id) and not is_member(user_id, pid):
        raise MisError("You are not a member of this project", 403)
    if "title" not in data:
        raise MisError("Title is required")

    owner = User.query.get(parse_int(data.get("ownerUserId") or data.get("assignedTo") or user_id, "assignedTo"))
    if not owner or owner.is_active is False:
        raise MisError("Assignee not found or inactive", 404)
    _check_assignee(user_id, owner, typ, project)

    parent = _parent_for(data.get("parentId"), typ, pid)
    sprint = _sprint_for(data.get("sprintId"), typ, pid)
    if sprint is None and parent is not None and typ == "Task" and "sprintId" not in data:
        sprint = parent.sprint                        # a task follows its PBI's sprint by default

    state = data.get("state") or WI_DEFAULT_STATE[typ]
    if typ == "Task" and state != "To Do":
        raise MisError("A new task starts as To Do — press Start when work begins")
    choice(state, WI_STATES[typ], "state")

    t = MisTask(work_item_type=typ, owner_user_id=owner.id, created_by=user_id, project_id=pid,
                priority=data.get("priority") or "Medium", status=state,
                parent_id=parent.id if parent else None, sprint_id=sprint.id if sprint else None,
                backlog_rank=_next_rank(pid))
    _apply_common(t, data)
    _apply_board_fields(t, data)
    if typ == "Task" and t.remaining_hours is None and t.estimated_hours is not None:
        t.remaining_hours = t.estimated_hours

    db.session.add(t)
    db.session.flush()
    t.task_code = f"{WI_CODE_PREFIX[typ]}-{date.today().year}-{t.id:05d}"
    _log(t, user_id, "CREATED", new=f"{typ}: {t.title}")
    if parent:
        _log(t, user_id, "PARENT", new=parent.task_code)
    if owner.id != user_id:
        _log(t, user_id, "ASSIGNED", new=owner.username)
    db.session.commit()
    if owner.id != user_id:
        _notify_assigned(t, user_id)
    return res(f"{WI_LABEL[typ]} created", _out(t, user_id), 201)


@api
def update_item(item_id, data, user_id):
    user_id = uid(user_id)
    t = _get(item_id, user_id, edit=True)
    reassigned = _apply_update(t, data, user_id)
    db.session.commit()
    if reassigned:
        _notify_assigned(t, user_id)
    return res("Work item updated", _out(t, user_id))


def _apply_update(t, data, user_id):
    """Apply an edit (no commit). Returns True when the item went to someone else (→ WhatsApp)."""
    if t.work_item_type == "Task" and t.is_locked:
        raise MisError(task_svc.LOCKED_MSG, 409)

    # type: only PBI ↔ Bug (same level, same rules)
    if data.get("workItemType") and data["workItemType"] != t.work_item_type:
        new_type = choice(data["workItemType"], WORK_ITEM_TYPES, "workItemType")
        if {t.work_item_type, new_type} != {"PBI", "Bug"}:
            raise MisError("Only an Activity and a Snag can be changed into each other")
        _log(t, user_id, "UPDATED", old="type", new=new_type)
        t.work_item_type = new_type

    before = {k: getattr(t, k) for k in ("title", "priority", "due_date", "story_points",
                                          "remaining_hours", "is_blocked")}
    _apply_common(t, data)
    _apply_board_fields(t, data)

    if "projectCode" in data:
        project = project_by_code(data.get("projectCode"))
        new_pid = project.id if project else None
        if new_pid != t.project_id:
            if _live_children(t).count():
                raise MisError("Move or remove the child items first")
            if project is not None and not is_super(user_id) and not is_member(user_id, new_pid):
                raise MisError("You are not a member of that project", 403)
            t.project_id, t.parent_id, t.sprint_id = new_pid, None, None
            _log(t, user_id, "UPDATED", old="project", new=project.project_code if project else "Company")

    if "parentId" in data:
        parent = _parent_for(data.get("parentId"), t.work_item_type, t.project_id)
        new_parent = parent.id if parent else None
        if new_parent != t.parent_id:
            _log(t, user_id, "PARENT", old=t.parent.task_code if t.parent else None,
                 new=parent.task_code if parent else None)
            t.parent_id = new_parent

    if "sprintId" in data:
        sprint = _sprint_for(data.get("sprintId"), t.work_item_type, t.project_id)
        new_sid = sprint.id if sprint else None
        if new_sid != t.sprint_id:
            old_sid = t.sprint_id
            _log(t, user_id, "SPRINT", old=t.sprint.name if t.sprint else "Backlog",
                 new=sprint.name if sprint else "Backlog")
            t.sprint_id = new_sid
            if t.work_item_type in POINT_TYPES:       # open child tasks move with their PBI
                for c in _live_children(t).filter(MisTask.work_item_type == "Task",
                                                  MisTask.status.notin_(("Done", "Cancelled"))):
                    if c.sprint_id == old_sid:
                        c.sprint_id = new_sid

    reassigned = False
    if data.get("ownerUserId") not in (None, "") or data.get("assignedTo") not in (None, ""):
        new_owner = User.query.get(parse_int(data.get("ownerUserId") or data.get("assignedTo"), "assignedTo"))
        if not new_owner or new_owner.is_active is False:
            raise MisError("Assignee not found or inactive", 404)
        if new_owner.id != t.owner_user_id:
            _check_assignee(user_id, new_owner, t.work_item_type, t.project)
            _log(t, user_id, "ASSIGNED", old=t.owner.username if t.owner else None, new=new_owner.username)
            t.owner_user_id = new_owner.id
            reassigned = new_owner.id != user_id

    if data.get("state"):
        old = _set_state(t, data["state"])
        if old:
            _log(t, user_id, "STATUS", old=old, new=t.status)

    for k, v in before.items():
        nv = getattr(t, k)
        if _norm(nv) != _norm(v):
            _log(t, user_id, "UPDATED", old=k, new=str(nv) if nv is not None else None)
    return reassigned


@api
def change_state(item_id, data, user_id):
    user_id = uid(user_id)
    t = _get(item_id, user_id, edit=True)
    if not data.get("state"):
        raise MisError("state is required")
    old = _set_state(t, data["state"])
    if old:
        _log(t, user_id, "STATUS", old=old, new=t.status, comment=(data.get("comment") or None))
        db.session.commit()
    return res("State updated", _out(t, user_id))


@api
def add_comment(item_id, data, user_id):
    """{ comment, mentions?: [userId] } — each mentioned user gets a WhatsApp."""
    user_id = uid(user_id)
    t = _get(item_id, user_id)
    text = (data.get("comment") or "").strip()
    if not text:
        raise MisError("comment is required")
    mentions = data.get("mentions") or []
    if not isinstance(mentions, list):
        raise MisError("mentions must be a list of user ids")
    users = []
    for m in mentions[:20]:
        u = User.query.get(parse_int(m, "mentions"))
        if u and u.is_active is not False and u.id != user_id and u.id not in {x.id for x in users}:
            if t.project_id is None or is_member(u.id, t.project_id) or is_super(u.id):
                users.append(u)
    _log(t, user_id, "COMMENT", new=",".join(str(u.id) for u in users) or None, comment=text[:2000])
    db.session.commit()
    for u in users:
        _notify_assigned(t, user_id, user_id=u.id, state="Mentioned", event="MENTIONED")
    return res("Comment added", {"mentioned": [{"id": u.id, "name": u.username} for u in users]}, 201)


@api
def delete_item(item_id, user_id):
    user_id = uid(user_id)
    t = _get(item_id, user_id)
    if not _can_delete(t, user_id):
        raise MisError("Only the creator or a permitted manager can delete this work item", 403)
    if t.work_item_type == "Task" and t.is_locked:
        raise MisError(task_svc.LOCKED_MSG, 409)
    if _live_children(t).count():
        raise MisError("This item has child items — move or delete them first", 409)
    t.is_deleted = True
    _log(t, user_id, "DELETED")
    db.session.commit()
    return res("Work item deleted", [])


# ─────────────────────────────── links ─────────────────────────────────

@api
def list_links(item_id, user_id):
    user_id = uid(user_id)
    t = _get(item_id, user_id)
    return res("ok", [_link_out(l) for l in MisWorkItemLink.query.filter_by(work_item_id=t.id)
                      .order_by(MisWorkItemLink.id.asc()).all()])


@api
def add_link(item_id, data, user_id):
    """{ targetType: WORK_ITEM|FOLLOWUP|ERP_DOC, targetId? , targetRef?, linkType? }"""
    user_id = uid(user_id)
    t = _get(item_id, user_id, edit=True)
    ttype = choice(data.get("targetType"), LINK_TARGET_TYPES, "targetType")
    ltype = choice(data.get("linkType") or "related", LINK_TYPES, "linkType")
    target_id, target_ref = None, None

    if ttype == "WORK_ITEM":
        target_id = parse_int(data.get("targetId"), "targetId", allow_none=False)
        if target_id == t.id:
            raise MisError("An item cannot link to itself")
        other = MisTask.query.filter_by(id=target_id, is_deleted=False).first()
        if not other or not _can_view(other, user_id):
            raise MisError("Linked work item not found", 404)
        if target_id in (t.parent_id,) or other.parent_id == t.id:
            raise MisError("Parent / child is already a link — use the parent field")
    elif ttype == "FOLLOWUP":
        from app.modules.mis.followup.service import _can_view as fu_can_view
        target_id = parse_int(data.get("targetId"), "targetId", allow_none=False)
        f = MisFollowup.query.filter_by(id=target_id, is_deleted=False).first()
        if not f or not fu_can_view(f, user_id):
            raise MisError("Follow-up not found", 404)
        if ltype != "related":
            raise MisError("A follow-up link is always 'related'")
    else:
        target_ref = (data.get("targetRef") or "").strip()
        if not target_ref:
            raise MisError("targetRef is required for an ERP document (e.g. 'SO:SO-2026-00012')")
        target_ref = target_ref[:120]

    exists = MisWorkItemLink.query.filter_by(work_item_id=t.id, target_type=ttype, target_id=target_id,
                                             target_ref=target_ref, link_type=ltype).first()
    if exists:
        raise MisError("This link already exists", 409)
    link = MisWorkItemLink(work_item_id=t.id, target_type=ttype, target_id=target_id,
                           target_ref=target_ref, link_type=ltype, created_by=user_id)
    db.session.add(link)
    if ttype == "WORK_ITEM":                          # mirror on the other side, like Azure Boards
        rev = REVERSE_LINK[ltype]
        if not MisWorkItemLink.query.filter_by(work_item_id=target_id, target_type="WORK_ITEM",
                                               target_id=t.id, link_type=rev).first():
            db.session.add(MisWorkItemLink(work_item_id=target_id, target_type="WORK_ITEM",
                                           target_id=t.id, link_type=rev, created_by=user_id))
    _log(t, user_id, "LINKED", new=f"{ltype} {ttype} {target_id or target_ref}")
    db.session.commit()
    return res("Link added", _link_out(link), 201)


@api
def delete_link(item_id, link_id, user_id):
    user_id = uid(user_id)
    t = _get(item_id, user_id, edit=True)
    link = MisWorkItemLink.query.filter_by(id=link_id, work_item_id=t.id).first()
    if not link:
        raise MisError("Link not found", 404)
    if link.target_type == "WORK_ITEM":
        MisWorkItemLink.query.filter_by(work_item_id=link.target_id, target_type="WORK_ITEM",
                                        target_id=t.id, link_type=REVERSE_LINK[link.link_type]).delete()
    _log(t, user_id, "UNLINKED", old=f"{link.link_type} {link.target_type} {link.target_id or link.target_ref}")
    db.session.delete(link)
    db.session.commit()
    return res("Link removed", [])


@api
def linked_to(args, user_id):
    """Work items linked to something else — e.g. ?targetType=FOLLOWUP&targetId=12 (follow-up drawer)."""
    user_id = uid(user_id)
    ttype = choice(args.get("targetType"), LINK_TARGET_TYPES, "targetType")
    q = MisWorkItemLink.query.filter(MisWorkItemLink.target_type == ttype)
    if ttype == "ERP_DOC":
        ref = (args.get("targetRef") or "").strip()
        if not ref:
            raise MisError("targetRef is required")
        q = q.filter(MisWorkItemLink.target_ref == ref)
    else:
        q = q.filter(MisWorkItemLink.target_id == parse_int(args.get("targetId"), "targetId", allow_none=False))
    out = []
    for l in q.order_by(MisWorkItemLink.id.asc()).all():
        w = l.work_item
        if w and not w.is_deleted and _can_view(w, user_id):
            out.append({**_summary(w), "linkId": l.id, "linkType": l.link_type})
    return res("ok", out)


# ─────────────────────────────── UI helpers ────────────────────────────

@api
def my_access(user_id):
    """Projects the user works in + where they may manage sprints (for the Boards header)."""
    from app.models.project import Project
    from app.modules.mis.common import can_manage_sprints
    user_id = uid(user_id)
    sup = is_super(user_id)
    pids = member_project_ids(user_id)
    projects = Project.query.filter(Project.id.in_(pids or {-1})).order_by(Project.project_code.asc()).all()
    return res("ok", {
        "isSuperAdmin": sup,
        "projects": [{"code": p.project_code, "name": p.project_name} for p in projects],
        "manageSprintProjects": [p.project_code for p in projects if can_manage_sprints(user_id, p.id)],
        "canManageCompanySprints": can_manage_sprints(user_id, None),
        "canEditOthersTasks": bool(sup or task_svc._scope(user_id, "EDIT")["projects"]),
    })


@api
def assignable(args, user_id):
    """Who an item can be assigned to. ?projectCode= &type=Task|PBI|… (Task → Self Task rules)."""
    user_id = uid(user_id)
    typ = choice(args.get("type") or "PBI", WORK_ITEM_TYPES, "type")
    project = project_by_code(args.get("projectCode"))
    if typ == "Task" or project is None:
        # Self Task's helper knows no 'company' code → pass the real project code or nothing
        return task_svc.assignable_users({"projectCode": project.project_code} if project else {}, user_id)
    from app.modules.mis.common import project_member_ids
    ids = set(project_member_ids(project.id)) | {user_id}
    users = (User.query.filter(User.id.in_(ids), or_(User.is_active.is_(True), User.is_active.is_(None)))
             .order_by(User.username.asc()).all())
    return res("ok", [{"id": u.id, "name": u.username, "empCode": u.emp_code} for u in users])
