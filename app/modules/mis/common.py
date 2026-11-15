"""Shared helpers for MIS follow-ups and sprints (errors, parsing, permissions, WhatsApp)."""
import logging
import os
from datetime import datetime
from functools import wraps

from flask import g

from app.extensions import db
from app.response import res
from app.models.user import User
from app.models.project import Project
from app.models.project_role import ProjectUserRole
from app.models.misTask import MisActivity

log = logging.getLogger(__name__)

# Follow-up board permission (Settings → Role & Designation, set by super admin):
#   task_tracker.VIEW  → see every agenda of that project
#   task_tracker.EDIT  → supervisor: create agendas / sprints, assign, close, reject
BOARD_PERM = "task_tracker"


class MisError(Exception):
    def __init__(self, msg, code=400):
        super().__init__(msg)
        self.msg, self.code = msg, code


def api(fn):
    """MisError → JSON response (and roll back)."""
    @wraps(fn)
    def inner(*a, **kw):
        try:
            return fn(*a, **kw)
        except MisError as e:
            db.session.rollback()
            return res(e.msg, [], e.code)
    return inner


# ─────────────────────────────── parsing ───────────────────────────────

def uid(user_id):
    try:
        return int(user_id)
    except (TypeError, ValueError):
        raise MisError("Invalid user", 401)


def parse_date(v, field, required=False):
    if v in (None, ""):
        if required:
            raise MisError(f"{field} is required")
        return None
    try:
        return datetime.strptime(str(v)[:10], "%Y-%m-%d").date()
    except ValueError:
        raise MisError(f"{field} must be YYYY-MM-DD")


def parse_int(v, field, minimum=None, allow_none=True):
    if v in (None, ""):
        if allow_none:
            return None
        raise MisError(f"{field} is required")
    try:
        n = int(v)
    except (TypeError, ValueError):
        raise MisError(f"{field} must be a whole number")
    if minimum is not None and n < minimum:
        raise MisError(f"{field} must be at least {minimum}")
    return n


def choice(v, allowed, field):
    if v not in allowed:
        raise MisError(f"{field} must be one of {', '.join(allowed)}")
    return v


def project_by_code(code):
    """None for ''/None/'company'; 404 when unknown."""
    if not code or str(code).lower() == "company":
        return None
    p = Project.query.filter_by(project_code=code).first()
    if not p:
        raise MisError("Project not found", 404)
    return p


def active_user(user_id, field="User"):
    u = User.query.get(parse_int(user_id, field, allow_none=False))
    if not u or u.is_active is False:
        raise MisError(f"{field} not found or inactive", 404)
    return u


# ─────────────────────────────── permissions ───────────────────────────

def is_super(user_id):
    cache = g.setdefault("_mis_super", {})
    if user_id not in cache:
        u = User.query.get(user_id)
        cache[user_id] = bool(u and u.global_role and u.global_role.name == "super_admin")
    return cache[user_id]


def member_project_ids(user_id):
    return {
        pid for (pid,) in db.session.query(ProjectUserRole.project_id)
        .filter(ProjectUserRole.user_id == user_id, ProjectUserRole.project_id.isnot(None)).distinct()
    }


def is_member(user_id, project_id):
    return db.session.query(ProjectUserRole.id).filter_by(user_id=user_id, project_id=project_id).first() is not None


def project_member_ids(project_id):
    return {
        u for (u,) in db.session.query(ProjectUserRole.user_id)
        .filter(ProjectUserRole.project_id == project_id, ProjectUserRole.user_id.isnot(None)).distinct()
    }


def board_perm(user_id, project_id, action):
    """task_tracker.<action> in that project (EDIT implies VIEW). Super admin: always."""
    if is_super(user_id):
        return True
    if project_id is None:
        return False
    cache = g.setdefault("_mis_perms", {})
    key = (user_id, project_id)
    if key not in cache:
        from app.modules.setting.permission_service import get_user_permissions
        try:
            cache[key] = get_user_permissions(project_id, user_id) or {}
        except Exception:
            db.session.rollback()
            log.warning("permission lookup failed (project %s)", project_id, exc_info=True)
            cache[key] = {}
    perms = cache[key]
    if perms.get(f"{BOARD_PERM}.EDIT"):
        return True
    return action == "VIEW" and bool(perms.get(f"{BOARD_PERM}.VIEW"))


def board_projects(user_id, action):
    """Projects where the user holds task_tracker.<action>. None = super admin (all)."""
    if is_super(user_id):
        return None
    return {pid for pid in member_project_ids(user_id) if board_perm(user_id, pid, action)}


def can_supervise_project(user_id, project_id):
    """May create agendas / sprints here. Company level (None): anyone who supervises some project."""
    if is_super(user_id):
        return True
    if project_id is None:
        return bool(board_projects(user_id, "EDIT"))
    return board_perm(user_id, project_id, "EDIT")


def check_assignee(user, project_id):
    """Relay rule: any member of the same project (company level: any active user)."""
    if project_id is not None and not is_member(user.id, project_id):
        raise MisError(f"{user.username} is not a member of this project", 403)


# ─────────────────────────────── activity / WhatsApp ───────────────────

def log_activity(entity_type, entity_id, user_id, action, old=None, new=None, comment=None):
    db.session.add(MisActivity(entity_type=entity_type, entity_id=entity_id, user_id=user_id,
                               action=action, old_value=old, new_value=new, comment=comment))


def activity_for(entity_type, entity_id):
    return [a.to_dict() for a in MisActivity.query.filter_by(entity_type=entity_type, entity_id=entity_id)
            .order_by(MisActivity.created_at.desc(), MisActivity.id.desc()).all()]


def notify(user_id, *, title, code, priority, project, actor_id, state, link_path, module_code, record_id, event):
    """Fire-and-forget WhatsApp (same approved template as tasks). Never raises."""
    try:
        from app.modules.communication.whatsapp_service import send_template
        u = User.query.get(user_id)
        phone = u and (u.wp_mobile or u.mobile)
        if not phone:
            return
        actor = User.query.get(actor_id) if actor_id else None
        link = f"{(os.getenv('FRONTEND_BASE_URL') or '').rstrip('/')}{link_path}"
        send_template(
            phone=phone,
            template_name=os.getenv("WA_TEMPLATE_TASK_ASSIGNED", "erp_action_required"),
            body_params={
                "module_name": f"Follow-up ({priority}) – {title[:60]}",
                "doc_no": code,
                "project_code": project.project_code if project else "Company",
                "actor_name": actor.username if actor else "ERP",
                "current_level": state,
                "pdf_url": link,
                "action_url": link,
            },
            doc_no=code,
            module_code=module_code,
            record_id=record_id,
            project_code=project.project_code if project else None,
            event=event,
        )
    except Exception:
        log.warning("MIS WhatsApp notify failed (%s %s)", module_code, record_id, exc_info=True)
