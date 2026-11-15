"""
MIS — Self Task service.

Access rules
  * Own tasks (owner or creator): always allowed, no permission needed.
  * `self_task_all.VIEW` in a project  → see tasks of every member of that
    project, and every task tagged with that project.
  * `self_task_all.EDIT` in a project  → the same, plus edit / assign / delete.
  * super_admin → everything, company-wide.
The permission is granted by super admin per project (Settings → Role & Designation).
"""
import logging
from datetime import date, datetime

from flask import g
from sqlalchemy import or_, func

from app.extensions import db
from app.response import res
from app.models.misTask import (
    MisTask, MisActivity, TASK_STATUSES, OPEN_STATUSES, TASK_PRIORITIES,
)
from app.models.user import User
from app.models.project import Project
from app.models.project_role import ProjectUserRole

log = logging.getLogger(__name__)

PERM_KEY = "self_task_all"
ENTITY = "task"
_EDITABLE = ("title", "description", "priority", "startDate", "dueDate",
             "estimatedHours", "actualHours", "tags")


class _Err(Exception):
    def __init__(self, msg, code=400):
        super().__init__(msg)
        self.msg, self.code = msg, code


def _wrap(fn):
    """Turn _Err into a JSON response and roll back on anything unexpected."""
    def inner(*a, **kw):
        try:
            return fn(*a, **kw)
        except _Err as e:
            db.session.rollback()
            return res(e.msg, [], e.code)
    inner.__name__ = fn.__name__
    inner.__doc__ = fn.__doc__
    return inner


# ─────────────────────────────── access ────────────────────────────────

def _uid(user_id):
    try:
        return int(user_id)
    except (TypeError, ValueError):
        raise _Err("Invalid user", 401)


def _is_super(user_id):
    u = User.query.get(user_id)
    return bool(u and u.global_role and u.global_role.name == "super_admin")


def _scope(user_id, action):
    """
    Users and projects whose tasks `user_id` may VIEW/EDIT through the permission.
    Returns None for super admin (= everything), else {"users": set, "projects": set}.
    Cached on flask.g for the request.
    """
    cache = g.setdefault("_mis_scope", {})
    key = (user_id, action)
    if key in cache:
        return cache[key]

    if _is_super(user_id):
        cache[key] = None
        return None

    from app.modules.setting.permission_service import get_user_permissions

    project_ids = {
        pid for (pid,) in db.session.query(ProjectUserRole.project_id)
        .filter(ProjectUserRole.user_id == user_id, ProjectUserRole.project_id.isnot(None))
        .distinct().all()
    }
    allowed = set()
    for pid in project_ids:
        try:
            perms = get_user_permissions(pid, user_id) or {}
        except Exception:
            db.session.rollback()
            log.warning("permission lookup failed for project %s", pid, exc_info=True)
            continue
        if perms.get(f"{PERM_KEY}.EDIT") or (action == "VIEW" and perms.get(f"{PERM_KEY}.VIEW")):
            allowed.add(pid)

    users = set()
    if allowed:
        users = {
            uid for (uid,) in db.session.query(ProjectUserRole.user_id)
            .filter(ProjectUserRole.project_id.in_(allowed), ProjectUserRole.user_id.isnot(None))
            .distinct().all()
        }
    out = {"users": users, "projects": allowed}
    cache[key] = out
    return out


def _covers(scope, task):
    if scope is None:
        return True
    return task.owner_user_id in scope["users"] or (task.project_id in scope["projects"])


def _can(task, user_id, action):
    if user_id in (task.owner_user_id, task.created_by):
        return True
    return _covers(_scope(user_id, action), task)


def _can_assign_to(user_id, target_id, project):
    """May `user_id` give a task to `target_id` (optionally inside `project`)?"""
    if target_id == user_id:
        return True
    scope = _scope(user_id, "EDIT")
    if scope is None:
        return True
    if project is not None:
        if project.id not in scope["projects"]:
            return False
        return _is_member(target_id, project.id)
    return target_id in scope["users"]


def _is_member(user_id, project_id):
    return db.session.query(ProjectUserRole.id).filter_by(
        user_id=user_id, project_id=project_id).first() is not None


def _get_task(task_id):
    t = MisTask.query.filter_by(id=task_id, is_deleted=False).first()
    if not t:
        raise _Err("Task not found", 404)
    return t


# ─────────────────────────────── parsing ───────────────────────────────

def _date(v, field):
    if v in (None, ""):
        return None
    try:
        return datetime.strptime(str(v)[:10], "%Y-%m-%d").date()
    except ValueError:
        raise _Err(f"{field} must be YYYY-MM-DD")


def _num(v, field):
    if v in (None, ""):
        return None
    try:
        n = float(v)
    except (TypeError, ValueError):
        raise _Err(f"{field} must be a number")
    if n < 0:
        raise _Err(f"{field} cannot be negative")
    return n


def _project(code):
    if not code:
        return None
    p = Project.query.filter_by(project_code=code).first()
    if not p:
        raise _Err("Project not found", 404)
    return p


def _apply_fields(task, data):
    if "title" in data:
        title = (data.get("title") or "").strip()
        if not title:
            raise _Err("Title is required")
        if len(title) > 200:
            raise _Err("Title is too long (max 200)")
        task.title = title
    if "description" in data:
        task.description = data.get("description") or None
    if "priority" in data:
        if data["priority"] not in TASK_PRIORITIES:
            raise _Err(f"priority must be one of {', '.join(TASK_PRIORITIES)}")
        task.priority = data["priority"]
    if "startDate" in data:
        task.start_date = _date(data["startDate"], "startDate")
    if "dueDate" in data:
        task.due_date = _date(data["dueDate"], "dueDate")
    if task.start_date and task.due_date and task.due_date < task.start_date:
        raise _Err("Due date cannot be before start date")
    if "estimatedHours" in data:
        task.estimated_hours = _num(data["estimatedHours"], "estimatedHours")
    if "actualHours" in data:
        task.actual_hours = _num(data["actualHours"], "actualHours")
    if "tags" in data:
        tags = data.get("tags") or []
        if not isinstance(tags, list):
            raise _Err("tags must be a list")
        task.tags = [str(t)[:40] for t in tags][:20]


def _log(task_id, user_id, action, old=None, new=None, comment=None):
    db.session.add(MisActivity(entity_type=ENTITY, entity_id=task_id, user_id=user_id,
                               action=action, old_value=old, new_value=new, comment=comment))


def _set_status(task, new_status):
    if new_status not in TASK_STATUSES:
        raise _Err(f"status must be one of {', '.join(TASK_STATUSES)}")
    old = task.status
    if old == new_status:
        return None
    if new_status == "Done":
        task.completed_at = datetime.utcnow()
    elif old == "Done":
        # reopened after completion → counts against quality in the performance score
        task.completed_at = None
        if new_status in OPEN_STATUSES:
            task.reopen_count = (task.reopen_count or 0) + 1
    task.status = new_status
    return old


# ─────────────────────────────── WhatsApp ──────────────────────────────

def _notify_assigned(task, assigner_id):
    """Fire-and-forget WhatsApp to the new owner. Never raises."""
    try:
        import os
        from app.modules.communication.whatsapp_service import send_template
        owner = User.query.get(task.owner_user_id)
        phone = owner and (owner.wp_mobile or owner.mobile)
        if not phone:
            return
        assigner = User.query.get(assigner_id)
        base = (os.getenv("FRONTEND_BASE_URL") or "").rstrip("/")
        link = f"{base}/task-management/todo?task={task.task_uuid}"
        due = task.due_date.strftime("%d-%m-%Y") if task.due_date else "No due date"
        send_template(
            phone=phone,
            template_name=os.getenv("WA_TEMPLATE_TASK_ASSIGNED", "erp_action_required"),
            body_params={
                "module_name": f"Task ({task.priority}) – {task.title[:60]}",
                "doc_no": f"{task.task_code} · Due {due}",
                "project_code": task.project.project_code if task.project else "Company",
                "actor_name": assigner.username if assigner else "ERP",
                "current_level": task.status,
                "pdf_url": link,
                "action_url": link,
            },
            doc_no=task.task_code,
            module_code="mis_task",
            record_id=task.id,
            project_code=task.project.project_code if task.project else None,
            event="ASSIGNED",
        )
    except Exception:
        log.warning("Task WhatsApp notify failed for %s", getattr(task, "id", None), exc_info=True)


# ─────────────────────────────── queries ───────────────────────────────

def _scoped_query(user_id, scope_name, project_code=None):
    q = MisTask.query.filter(MisTask.is_deleted.is_(False))
    if scope_name == "mine":
        q = q.filter(MisTask.owner_user_id == user_id)
    elif scope_name == "assigned_by_me":
        q = q.filter(MisTask.created_by == user_id, MisTask.owner_user_id != user_id)
    elif scope_name in ("team", "all"):
        scope = _scope(user_id, "VIEW")
        if scope is not None:
            if not scope["users"] and not scope["projects"]:
                raise _Err("You do not have permission to view other users' tasks", 403)
            conds = [MisTask.owner_user_id == user_id, MisTask.created_by == user_id]
            if scope["users"]:
                conds.append(MisTask.owner_user_id.in_(scope["users"]))
            if scope["projects"]:
                conds.append(MisTask.project_id.in_(scope["projects"]))
            q = q.filter(or_(*conds))
    else:
        raise _Err("scope must be mine, assigned_by_me, team or all")

    if project_code:
        if project_code.lower() == "company":
            q = q.filter(MisTask.project_id.is_(None))
        else:
            q = q.filter(MisTask.project_id == _project(project_code).id)
    return q


@_wrap
def list_tasks(args, user_id):
    user_id = _uid(user_id)
    q = _scoped_query(user_id, (args.get("scope") or "mine").strip(), args.get("projectCode"))
    today = date.today()

    status = args.get("status")
    if status:
        statuses = [s for s in status.split(",") if s]
        q = q.filter(MisTask.status.in_(statuses))
    if args.get("priority"):
        q = q.filter(MisTask.priority.in_([p for p in args["priority"].split(",") if p]))
    if args.get("ownerUserId"):
        try:
            q = q.filter(MisTask.owner_user_id == int(args["ownerUserId"]))
        except ValueError:
            raise _Err("ownerUserId must be a number")
    if args.get("fromDate"):
        q = q.filter(MisTask.due_date >= _date(args["fromDate"], "fromDate"))
    if args.get("toDate"):
        q = q.filter(MisTask.due_date <= _date(args["toDate"], "toDate"))
    if str(args.get("overdue", "")).lower() in ("1", "true"):
        q = q.filter(MisTask.status.in_(OPEN_STATUSES), MisTask.due_date < today)
    search = (args.get("search") or "").strip()
    if search:
        like = f"%{search}%"
        q = q.filter(or_(MisTask.title.ilike(like), MisTask.task_code.ilike(like),
                         MisTask.description.ilike(like)))

    try:
        page = max(int(args.get("page") or 1), 1)
        per_page = min(max(int(args.get("perPage") or 50), 1), 200)
    except ValueError:
        raise _Err("page/perPage must be numbers")

    total = q.count()
    rows = (q.order_by(
                # open first, then by due date (no due date last), newest first
                db.case((MisTask.status.in_(OPEN_STATUSES), 0), else_=1),
                MisTask.due_date.is_(None), MisTask.due_date.asc(), MisTask.id.desc())
            .offset((page - 1) * per_page).limit(per_page).all())
    return res("ok", {
        "items": [t.to_dict(today) for t in rows],
        "total": total, "page": page, "perPage": per_page,
    })


@_wrap
def get_task(task_id, user_id):
    user_id = _uid(user_id)
    t = _get_task(task_id)
    if not _can(t, user_id, "VIEW"):
        raise _Err("You do not have access to this task", 403)
    acts = (MisActivity.query.filter_by(entity_type=ENTITY, entity_id=t.id)
            .order_by(MisActivity.created_at.desc(), MisActivity.id.desc()).all())
    out = t.to_dict()
    out["activity"] = [a.to_dict() for a in acts]
    out["canEdit"] = _can(t, user_id, "EDIT")
    return res("ok", out)


@_wrap
def get_task_by_uuid(task_uuid, user_id):
    t = MisTask.query.filter_by(task_uuid=task_uuid, is_deleted=False).first()
    if not t:
        return res("Task not found", [], 404)
    return get_task(t.id, user_id)


@_wrap
def create_task(data, user_id):
    user_id = _uid(user_id)
    project = _project(data.get("projectCode"))
    owner_id = data.get("ownerUserId") or user_id
    try:
        owner_id = int(owner_id)
    except (TypeError, ValueError):
        raise _Err("ownerUserId must be a number")
    owner = User.query.get(owner_id)
    if not owner or owner.is_active is False:
        raise _Err("Assignee not found or inactive", 404)
    if not _can_assign_to(user_id, owner_id, project):
        raise _Err("You can only assign tasks to users you manage in this project", 403)

    t = MisTask(owner_user_id=owner_id, created_by=user_id,
                project_id=project.id if project else None,
                priority=data.get("priority") or "Medium", status="To Do")
    if "title" not in data:
        raise _Err("Title is required")
    _apply_fields(t, {k: data[k] for k in _EDITABLE if k in data})
    if data.get("status") and data["status"] != "To Do":
        _set_status(t, data["status"])

    db.session.add(t)
    db.session.flush()
    t.task_code = f"TSK-{date.today().year}-{t.id:05d}"
    _log(t.id, user_id, "CREATED", new=t.title)
    if owner_id != user_id:
        _log(t.id, user_id, "ASSIGNED", new=owner.username)
    db.session.commit()

    if owner_id != user_id:
        _notify_assigned(t, user_id)
    return res("Task created", t.to_dict(), 201)


@_wrap
def update_task(task_id, data, user_id):
    user_id = _uid(user_id)
    t = _get_task(task_id)
    if not _can(t, user_id, "EDIT"):
        raise _Err("You do not have permission to edit this task", 403)

    changes = []
    before = {k: getattr(t, k) for k in ("title", "priority", "due_date")}
    _apply_fields(t, {k: data[k] for k in _EDITABLE if k in data})

    if "projectCode" in data:
        project = _project(data.get("projectCode"))
        new_pid = project.id if project else None
        if new_pid != t.project_id:
            if project and not _can_assign_to(user_id, t.owner_user_id, project):
                raise _Err("Owner is not a member of that project, or you cannot manage it", 403)
            t.project_id = new_pid
            changes.append(("UPDATED", "project", project.project_code if project else "Company"))

    reassigned = False
    new_owner_id = None
    if data.get("ownerUserId") not in (None, ""):
        try:
            new_owner_id = int(data["ownerUserId"])
        except (TypeError, ValueError):
            raise _Err("ownerUserId must be a number")
    if new_owner_id is not None and new_owner_id != t.owner_user_id:
        new_owner = User.query.get(new_owner_id)
        if not new_owner or new_owner.is_active is False:
            raise _Err("Assignee not found or inactive", 404)
        if not _can_assign_to(user_id, new_owner.id, t.project):
            raise _Err("You can only assign tasks to users you manage in this project", 403)
        old_name = t.owner.username if t.owner else None
        t.owner_user_id = new_owner.id
        _log(t.id, user_id, "ASSIGNED", old=old_name, new=new_owner.username)
        reassigned = new_owner.id != user_id

    if data.get("status"):
        old = _set_status(t, data["status"])
        if old:
            _log(t.id, user_id, "STATUS", old=old, new=t.status)

    for k, v in before.items():
        if getattr(t, k) != v:
            changes.append(("UPDATED", k, getattr(t, k)))
    for action, field, val in changes:
        _log(t.id, user_id, action, old=field, new=str(val) if val is not None else None)

    db.session.commit()
    if reassigned:
        _notify_assigned(t, user_id)
    return res("Task updated", t.to_dict())


@_wrap
def change_status(task_id, data, user_id):
    user_id = _uid(user_id)
    t = _get_task(task_id)
    if not _can(t, user_id, "EDIT"):
        raise _Err("You do not have permission to change this task", 403)
    if not data.get("status"):
        raise _Err("status is required")
    old = _set_status(t, data["status"])
    if old:
        _log(t.id, user_id, "STATUS", old=old, new=t.status, comment=data.get("comment") or None)
        db.session.commit()
    return res("Status updated", t.to_dict())


@_wrap
def add_comment(task_id, data, user_id):
    user_id = _uid(user_id)
    t = _get_task(task_id)
    if not _can(t, user_id, "VIEW"):
        raise _Err("You do not have access to this task", 403)
    text = (data.get("comment") or "").strip()
    if not text:
        raise _Err("comment is required")
    _log(t.id, user_id, "COMMENT", comment=text[:2000])
    db.session.commit()
    return res("Comment added", [], 201)


@_wrap
def delete_task(task_id, user_id):
    user_id = _uid(user_id)
    t = _get_task(task_id)
    own = t.created_by == user_id
    if not own and not _covers(_scope(user_id, "EDIT"), t):
        raise _Err("Only the creator or a permitted manager can delete this task", 403)
    t.is_deleted = True
    _log(t.id, user_id, "DELETED")
    db.session.commit()
    return res("Task deleted", [])


@_wrap
def task_stats(args, user_id):
    user_id = _uid(user_id)
    q = _scoped_query(user_id, (args.get("scope") or "mine").strip(), args.get("projectCode"))
    today = date.today()
    sub = q.with_entities(MisTask.id, MisTask.status, MisTask.due_date, MisTask.completed_at).subquery()

    by_status = dict(db.session.query(sub.c.status, func.count()).group_by(sub.c.status).all())
    overdue = db.session.query(func.count()).select_from(sub).filter(
        sub.c.status.in_(OPEN_STATUSES), sub.c.due_date < today).scalar() or 0
    due_today = db.session.query(func.count()).select_from(sub).filter(
        sub.c.status.in_(OPEN_STATUSES), sub.c.due_date == today).scalar() or 0
    week_start = today.toordinal() - today.weekday()
    done_week = db.session.query(func.count()).select_from(sub).filter(
        sub.c.status == "Done",
        sub.c.completed_at >= datetime.fromordinal(week_start)).scalar() or 0

    return res("ok", {
        "byStatus": {s: by_status.get(s, 0) for s in TASK_STATUSES},
        "open": sum(by_status.get(s, 0) for s in OPEN_STATUSES),
        "overdue": overdue,
        "dueToday": due_today,
        "doneThisWeek": done_week,
    })


@_wrap
def my_access(user_id):
    """What the frontend needs to decide which tabs/filters to show."""
    user_id = _uid(user_id)
    view = _scope(user_id, "VIEW")
    edit = _scope(user_id, "EDIT")
    return res("ok", {
        "isSuperAdmin": view is None,
        "canViewOthers": view is None or bool(view["users"] or view["projects"]),
        "canEditOthers": edit is None or bool(edit["users"] or edit["projects"]),
    })


@_wrap
def assignable_users(args, user_id):
    """Users the caller may assign a task to (optionally within a project)."""
    user_id = _uid(user_id)
    project = _project(args.get("projectCode"))
    scope = _scope(user_id, "EDIT")

    q = User.query.filter(or_(User.is_active.is_(True), User.is_active.is_(None)))
    if project is not None:
        if scope is not None and project.id not in scope["projects"]:
            q = q.filter(User.id == user_id)
        else:
            members = db.session.query(ProjectUserRole.user_id).filter(
                ProjectUserRole.project_id == project.id)
            q = q.filter(or_(User.id.in_(members), User.id == user_id))
    elif scope is not None:
        q = q.filter(or_(User.id.in_(scope["users"] or {-1}), User.id == user_id))

    users = q.order_by(User.username.asc()).all()
    return res("ok", [{"id": u.id, "name": u.username, "empCode": u.emp_code} for u in users])


@_wrap
def viewable_owners(args, user_id):
    """Users whose tasks the caller can see — for the Employee filter."""
    user_id = _uid(user_id)
    scope = _scope(user_id, "VIEW")
    q = User.query
    if scope is not None:
        q = q.filter(or_(User.id.in_(scope["users"] or {-1}), User.id == user_id))
    users = q.order_by(User.username.asc()).all()
    return res("ok", [{"id": u.id, "name": u.username, "empCode": u.emp_code} for u in users])
