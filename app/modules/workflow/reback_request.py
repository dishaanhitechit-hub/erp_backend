"""
Reback requests — ask for a fully approved record to be sent back.

  1. Someone on the record (its creator, anyone in that module's approval path
     for the project, or an admin) raises a request with a comment.
  2. The final approver of that module for the project — or an admin — accepts
     or declines it. The person who raised it (or an admin) can cancel it.
  3. Accept undoes the approval (unapprove._apply: accounts / stock / bank line,
     record back to the creator). The "used further on?" check runs again at
     that moment, so a record that got used meanwhile can't be sent back.

One PENDING request per record. Nothing is undone while a request is pending.
"""

from app.utils.date_utils import created_ts
from datetime import datetime

from flask import current_app
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models.rebackRequest import RebackRequest
from app.response import res
from app.utils.pagination import get_page_params, set_pagination

from . import unapprove as U

STATUSES = ("PENDING", "ACCEPTED", "DECLINED", "CANCELLED")


# ==========================================
# WHO
# ==========================================

def _approval_code(key, record):
    from app.alias_helper import get_approval_module
    return get_approval_module(U._value(U.UNAPPROVE_MODULES[key]["history"], record))


def final_approvers(project_code, approval_code):
    """Users at the highest APPROVER level of this module for this project."""
    from app.models.approval_path import ApprovalPath
    rows = ApprovalPath.query.filter_by(project_code=project_code, module_code=approval_code,
                                        path_type="APPROVER").all()
    if not rows:
        return []
    top = max(r.level_no for r in rows)
    return [r.user_id for r in rows if r.level_no == top]


def _is_final_approver(user_id, project_code, approval_code):
    return user_id is not None and user_id in final_approvers(project_code, approval_code)


def _can_raise(user_id, key, record):
    if U.is_admin():
        return True
    if user_id is None:
        return False
    if getattr(record, "created_by", None) == user_id:
        return True
    from app.models.approval_path import ApprovalPath
    return ApprovalPath.query.filter_by(project_code=U._project(U.UNAPPROVE_MODULES[key], record),
                                        module_code=_approval_code(key, record),
                                        user_id=user_id).first() is not None


def _can_decide(user_id, req):
    return U.is_admin() or _is_final_approver(user_id, req.project_code, req.approval_module)


def _names(user_ids):
    from app.models.user import User
    if not user_ids:
        return {}
    return {u.id: u.username for u in User.query.filter(User.id.in_(list(user_ids))).all()}


# ==========================================
# OUTPUT
# ==========================================

def _payload(req, names=None, user_id=None):
    names = names if names is not None else _names({req.requested_by, req.decided_by} - {None})
    label = U._labels().get(req.module, req.module)
    return {
        "createdTs": created_ts(req.requested_at),
        "id":              req.id,
        "module":          req.module,
        "moduleLabel":     label,
        "recordId":        req.record_id,
        "recordNo":        req.record_no,
        "projectCode":     req.project_code,
        "status":          req.status,
        "reason":          req.reason,
        "requestedBy":     req.requested_by,
        "requestedByName": names.get(req.requested_by),
        "requestedAt":     req.requested_at.isoformat() if req.requested_at else None,
        "decidedBy":       req.decided_by,
        "decidedByName":   names.get(req.decided_by),
        "decidedAt":       req.decided_at.isoformat() if req.decided_at else None,
        "decisionComment": req.decision_comment,
        "pageUrl":         req.page_url,
        "canDecide":       req.status == "PENDING" and user_id is not None and _can_decide(user_id, req),
        "canCancel":       req.status == "PENDING" and (U.is_admin() or req.requested_by == user_id),
    }


def _log(key, record, action, user_id, comments):
    """Request events go into the record's own approval history, so the
    Timeline / History sheet of every module shows them."""
    from app.modules.work_flow import create_history
    create_history(
        project_code=U._project(U.UNAPPROVE_MODULES[key], record),
        module_code=U._value(U.UNAPPROVE_MODULES[key]["history"], record),
        record_id=record.id,
        level_no=None,
        action=action,
        action_by=user_id,
        comments=comments,
    )


def _record_of(req):
    return U._load(U.UNAPPROVE_MODULES[req.module]["model"]).query.get(req.record_id)


def _pending(key, record_id):
    return RebackRequest.query.filter_by(module=key, record_id=record_id, status="PENDING").first()


# ==========================================
# RECORD STATUS — what the view page shows
# ==========================================

def record_status(module, record_id, path=None):
    if not module and path:
        module = U.module_for_path(path)
    if module not in U.UNAPPROVE_MODULES:
        return res(f"Unknown module: {module}", [], 400)
    rid = U._int(record_id)
    if not rid:
        return res("Invalid id", [], 400)

    entry = U.UNAPPROVE_MODULES[module]
    record = U._load(entry["model"]).query.get(rid)
    if not record:
        return res("Record not found", [], 404)

    user_id = U._user_id()
    approved = (record.workflow_status or "") == "Approved"
    out = {"module": module, "id": rid, "recordNo": U._doc_no(entry, record), "approved": approved,
           "blockedReason": None, "canRaise": False, "request": None, "lastRequest": None,
           "finalApprovers": []}
    pending = _pending(module, rid)
    if pending:
        out["request"] = _payload(pending, user_id=user_id)
    last = RebackRequest.query.filter(RebackRequest.module == module, RebackRequest.record_id == rid,
                                      RebackRequest.status != "PENDING") \
        .order_by(RebackRequest.id.desc()).first()
    if last:
        out["lastRequest"] = _payload(last, user_id=user_id)
    if not approved:
        return res("Not approved", out, 200)

    _, reason = U.check_record(module, rid)
    out["blockedReason"] = reason
    project = U._project(entry, record)
    ids = final_approvers(project, _approval_code(module, record))
    names = _names(set(ids))
    out["finalApprovers"] = [{"id": i, "name": names.get(i)} for i in ids]
    out["canRaise"] = not pending and reason is None and _can_raise(user_id, module, record)
    out["canDecide"] = bool(pending) and out["request"]["canDecide"]
    return res("OK", out, 200)


# ==========================================
# RAISE / ACCEPT / DECLINE / CANCEL
# ==========================================

def raise_request(data):
    data = data or {}
    module = data.get("module")
    if module not in U.UNAPPROVE_MODULES:
        return res(f"Unknown module: {module}", [], 400)
    rid = U._int(data.get("id"))
    if not rid:
        return res("Invalid id", [], 400)
    reason = str(data.get("reason") or data.get("remarks") or "").strip()
    if not reason:
        return res("Please write why it should be sent back", [], 400)

    record, blocked = U.check_record(module, rid)
    if record is None:
        return res(blocked, [], 404)
    if blocked:
        return res(blocked, [], 400)
    user_id = U._user_id()
    if not _can_raise(user_id, module, record):
        return res("Only people on this record's approval path can ask for a reback", [], 403)
    if _pending(module, rid):
        return res("A reback request for this record is already waiting", [], 409)

    entry = U.UNAPPROVE_MODULES[module]
    page_url = str(data.get("pageUrl") or "").strip()
    if not (page_url.startswith("/") and not page_url.startswith("//") and len(page_url) <= 255):
        page_url = None                 # app-internal links only
    req = RebackRequest(module=module, record_id=rid, record_no=U._doc_no(entry, record),
                        project_code=U._project(entry, record), approval_module=_approval_code(module, record),
                        requested_by=user_id, reason=reason, status="PENDING", page_url=page_url)
    db.session.add(req)
    _log(module, record, "REBACK_REQUEST", user_id, reason)
    try:
        db.session.commit()
    except IntegrityError:          # someone raised one at the same moment
        db.session.rollback()
        return res("A reback request for this record is already waiting", [], 409)
    return res(f"Reback request raised for {req.record_no}", _payload(req, user_id=user_id), 201)


def _get_pending(req_id):
    req = RebackRequest.query.get(req_id)
    if not req:
        return None, res("Request not found", [], 404)
    if req.status != "PENDING":
        return None, res(f"This request is already {req.status.lower()}", [], 400)
    return req, None


def accept_request(req_id, data):
    req, err = _get_pending(req_id)
    if err:
        return err
    user_id = U._user_id()
    if not _can_decide(user_id, req):
        return res("Only the final approver or an admin can accept this", [], 403)
    comment = str((data or {}).get("comment") or "").strip()

    try:
        record, blocked = U.check_record(req.module, req.record_id, lock=True)
        if record is None:
            return res(blocked, [], 404)
        if blocked:
            return res(blocked, [], 400)        # stays pending; can be declined
        names = _names({req.requested_by, user_id})
        history = (f"[Reback after approval] Requested by {names.get(req.requested_by)}: {req.reason}"
                   f" | Accepted by {names.get(user_id)}" + (f": {comment}" if comment else ""))
        _log(req.module, record, "REBACK_REQUEST_ACCEPTED", user_id, comment or None)
        U._apply(req.module, record, user_id, history)
        req.status = "ACCEPTED"
        req.decided_by = user_id
        req.decided_at = datetime.utcnow()
        req.decision_comment = comment or None
        db.session.commit()
    except Exception:
        db.session.rollback()
        current_app.logger.exception("Accept reback request %s failed", req_id)
        return res("Something went wrong", [], 500)

    U._send_whatsapp(U.UNAPPROVE_MODULES[req.module], record, user_id, comment or req.reason)
    return res(f"{req.record_no} sent back to the creator", _payload(req, user_id=user_id), 200)


def decline_request(req_id, data):
    req, err = _get_pending(req_id)
    if err:
        return err
    user_id = U._user_id()
    if not _can_decide(user_id, req):
        return res("Only the final approver or an admin can decline this", [], 403)
    comment = str((data or {}).get("comment") or "").strip()
    if not comment:
        return res("Please write why it is declined", [], 400)
    req.status = "DECLINED"
    req.decided_by = user_id
    req.decided_at = datetime.utcnow()
    req.decision_comment = comment
    record = _record_of(req)
    if record is not None:
        _log(req.module, record, "REBACK_REQUEST_DECLINED", user_id, comment)
    db.session.commit()
    return res("Reback request declined", _payload(req, user_id=user_id), 200)


def cancel_request(req_id):
    req, err = _get_pending(req_id)
    if err:
        return err
    user_id = U._user_id()
    if not (U.is_admin() or req.requested_by == user_id):
        return res("Only the person who raised it (or an admin) can cancel it", [], 403)
    req.status = "CANCELLED"
    req.decided_by = user_id
    req.decided_at = datetime.utcnow()
    record = _record_of(req)
    if record is not None:
        _log(req.module, record, "REBACK_REQUEST_CANCELLED", user_id, None)
    db.session.commit()
    return res("Reback request cancelled", _payload(req, user_id=user_id), 200)


# ==========================================
# LIST — admin: all · final approver: waiting on them · everyone: raised by them
# ==========================================

def _my_final_scopes(user_id):
    """{(project_code, approval_module)} where this user is at the top APPROVER level."""
    from app.models.approval_path import ApprovalPath
    mine = ApprovalPath.query.filter_by(user_id=user_id, path_type="APPROVER").all()
    scopes = set()
    for p in mine:
        if user_id in final_approvers(p.project_code, p.module_code):
            scopes.add((p.project_code, p.module_code))
    return scopes


def list_requests(args):
    user_id = U._user_id()
    q = RebackRequest.query
    status = (args.get("status") or "").upper()
    if status:
        if status not in STATUSES:
            return res("Bad status", [], 400)
        q = q.filter(RebackRequest.status == status)
    if args.get("module"):
        q = q.filter(RebackRequest.module == args.get("module"))
    if args.get("projectCode"):
        q = q.filter(RebackRequest.project_code == args.get("projectCode"))

    if not U.is_admin():
        scopes = _my_final_scopes(user_id)
        cond = [RebackRequest.requested_by == user_id]
        for project_code, approval_module in scopes:
            cond.append(db.and_(RebackRequest.project_code == project_code,
                                RebackRequest.approval_module == approval_module))
        q = q.filter(db.or_(*cond))

    q = q.order_by((RebackRequest.status == "PENDING").desc(), RebackRequest.id.desc())
    paging = get_page_params(args)
    if paging:
        page, limit = paging
        total = q.count()
        rows = q.offset((page - 1) * limit).limit(limit).all() if limit else q.all()
        set_pagination(total, page, limit)
    else:
        rows = q.limit(2000).all()

    names = _names({r.requested_by for r in rows} | {r.decided_by for r in rows if r.decided_by})
    data = [_payload(r, names=names, user_id=user_id) for r in rows]
    return res("Reback requests", data, 200)


def list_modules():
    return res("Modules", [{"module": k, "label": v} for k, v in U._labels().items()], 200)


def pending_count():
    """How many requests wait on me (admin: all pending) — for a menu badge."""
    user_id = U._user_id()
    q = RebackRequest.query.filter_by(status="PENDING")
    if not U.is_admin():
        scopes = _my_final_scopes(user_id)
        if not scopes:
            return res("Count", {"count": 0}, 200)
        q = q.filter(db.or_(*[db.and_(RebackRequest.project_code == p, RebackRequest.approval_module == m)
                              for p, m in scopes]))
    return res("Count", {"count": q.count()}, 200)
