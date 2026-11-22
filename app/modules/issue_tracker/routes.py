# app/modules/issue_tracker/routes.py
"""
Issues & Feature Requests — /issue-tracker

Who can do what:
  * super admin  — everything, manages members, flips the kill switch.
  * member with can_edit     — create / edit / delete items.
  * member with is_developer — tick items done (comment + pictures), untick.
  * member with no flag      — view only.
  * everyone else            — no access.

Kill switch: app_setting 'issue_tracker.enabled'. While it is off every
endpoint except GET /status and the super-admin settings / member endpoints
answers 403, and /status tells the frontend to hide the menu entry.
"""

import json
import uuid
from datetime import datetime

from flask import Blueprint, request, g

from app.extensions import db
from app.middleware.auth_middleware import login_required
from app.models.issueTracker import AppSetting, IssueTrackerItem, IssueTrackerMember
from app.models.user import User
from app.response import res
from app.utils.html_sanitize import sanitize_html, html_to_text

issue_tracker_bp = Blueprint("issue_tracker", __name__)

ENABLED_KEY = "issue_tracker.enabled"
KINDS = ("ISSUE", "FEATURE")
IMAGE_EXT = {"png", "jpg", "jpeg", "gif", "webp"}
MAX_IMAGES = 6
MAX_IMAGE_BYTES = 5 * 1024 * 1024
MAX_BODY = 50_000


# ── helpers ─────────────────────────────────────────────────────

def _uid():
    return g.current_user.get("id")


def _is_super(uid):
    u = User.query.get(uid) if uid else None
    return bool(u and u.global_role and u.global_role.name == "super_admin")


def _enabled():
    row = AppSetting.query.get(ENABLED_KEY)
    return True if row is None else bool(row.value)  # on until switched off


def _access(uid):
    sup = _is_super(uid)
    m = IssueTrackerMember.query.get(uid) if uid else None
    return {
        "isSuperAdmin": sup,
        "canView": sup or m is not None,
        "canEdit": sup or bool(m and m.can_edit),
        "isDeveloper": sup or bool(m and m.is_developer),
    }


def _gate(need=None):
    """(access, None) when allowed, else (None, error response)."""
    if not _enabled():
        return None, res("Issues & Requests is turned off", None, 403)
    a = _access(_uid())
    if not a["canView"] or (need and not a[need]):
        return None, res("You don't have permission for this", None, 403)
    return a, None


def _names(ids):
    ids = {i for i in ids if i}
    if not ids:
        return {}
    return {u.id: u.username for u in User.query.filter(User.id.in_(ids)).all()}


def _iso(d):
    return d.isoformat() + "Z" if d else None  # stored as naive UTC


def _item_json(it, names):
    return {
        "id": it.id,
        "kind": it.kind,
        "bodyHtml": it.body_html,
        "createdBy": it.created_by, "createdByName": names.get(it.created_by), "createdAt": _iso(it.created_at),
        "updatedBy": it.updated_by, "updatedByName": names.get(it.updated_by), "updatedAt": _iso(it.updated_at),
        "isDone": bool(it.is_done),
        "doneBy": it.done_by, "doneByName": names.get(it.done_by), "doneAt": _iso(it.done_at),
        "doneComment": it.done_comment or "",
        "doneImages": list(it.done_images or []),
    }


def _clean_body(data):
    raw = data.get("bodyHtml") or ""
    if len(raw) > MAX_BODY:
        return None, "Text is too long"
    body = sanitize_html(raw)
    if not html_to_text(body):
        return None, "Write something first"
    return body, None


def _kind(data, default="ISSUE"):
    k = str(data.get("kind") or default).upper()
    return k if k in KINDS else None


def _delete_files(urls):
    from app.cloudinary_uploader import delete_file_from_storage
    for u in urls or []:
        delete_file_from_storage(u)


# ── status / kill switch ────────────────────────────────────────

@issue_tracker_bp.route("/status", methods=["GET"])
@login_required
def api_status():
    enabled = _enabled()
    a = _access(_uid())
    if not enabled and not a["isSuperAdmin"]:
        a = {"isSuperAdmin": False, "canView": False, "canEdit": False, "isDeveloper": False}
    # menu entry: super admin always (to switch it back on), others only while on
    return res("ok", {"enabled": enabled, "showMenu": a["isSuperAdmin"] or (enabled and a["canView"]), **a})


@issue_tracker_bp.route("/settings", methods=["PUT"])
@login_required
def api_settings():
    uid = _uid()
    if not _is_super(uid):
        return res("Only super admin can change this", None, 403)
    data = request.get_json() or {}
    if "enabled" not in data:
        return res("enabled is required", None, 400)
    row = AppSetting.query.get(ENABLED_KEY) or AppSetting(key=ENABLED_KEY)
    row.value = bool(data["enabled"])
    row.updated_by = uid
    row.updated_at = datetime.utcnow()
    db.session.add(row)
    db.session.commit()
    return res("Turned on" if row.value else "Turned off", {"enabled": row.value})


# ── members (super admin) ───────────────────────────────────────

@issue_tracker_bp.route("/members", methods=["GET"])
@login_required
def api_members():
    if not _is_super(_uid()):
        return res("Only super admin can manage users", None, 403)
    members = IssueTrackerMember.query.all()
    names = _names([m.user_id for m in members])
    users = (User.query.filter(User.is_active.isnot(False)).order_by(User.username).all())
    return res("ok", {
        "members": sorted(
            [{"userId": m.user_id, "name": names.get(m.user_id), "canEdit": bool(m.can_edit),
              "isDeveloper": bool(m.is_developer)} for m in members],
            key=lambda x: (x["name"] or "").lower()),
        "users": [{"id": u.id, "name": u.username, "empCode": u.emp_code} for u in users],
    })


@issue_tracker_bp.route("/members", methods=["POST"])
@login_required
def api_member_save():
    uid = _uid()
    if not _is_super(uid):
        return res("Only super admin can manage users", None, 403)
    data = request.get_json() or {}
    try:
        target = int(data.get("userId"))
    except (TypeError, ValueError):
        return res("userId is required", None, 400)
    if not User.query.get(target):
        return res("User not found", None, 404)
    m = IssueTrackerMember.query.get(target) or IssueTrackerMember(user_id=target, added_by=uid)
    m.can_edit = bool(data.get("canEdit"))
    m.is_developer = bool(data.get("isDeveloper"))
    db.session.add(m)
    db.session.commit()
    return res("Saved", {"userId": target, "canEdit": m.can_edit, "isDeveloper": m.is_developer})


@issue_tracker_bp.route("/members/<int:user_id>", methods=["DELETE"])
@login_required
def api_member_delete(user_id):
    if not _is_super(_uid()):
        return res("Only super admin can manage users", None, 403)
    m = IssueTrackerMember.query.get(user_id)
    if not m:
        return res("Not found", None, 404)
    db.session.delete(m)
    db.session.commit()
    return res("Removed")


# ── items ───────────────────────────────────────────────────────

@issue_tracker_bp.route("/items", methods=["GET"])
@login_required
def api_items():
    a, err = _gate()
    if err:
        return err
    q = IssueTrackerItem.query
    status = (request.args.get("status") or "all").lower()
    if status == "open":
        q = q.filter(IssueTrackerItem.is_done.is_(False))
    elif status == "done":
        q = q.filter(IssueTrackerItem.is_done.is_(True))
    kind = (request.args.get("kind") or "").upper()
    if kind in KINDS:
        q = q.filter(IssueTrackerItem.kind == kind)
    items = q.order_by(IssueTrackerItem.is_done.asc(), IssueTrackerItem.id.desc()).all()
    names = _names([i for it in items for i in (it.created_by, it.updated_by, it.done_by)])
    return res("ok", {"items": [_item_json(it, names) for it in items], "access": a})


@issue_tracker_bp.route("/items", methods=["POST"])
@login_required
def api_item_create():
    _, err = _gate("canEdit")
    if err:
        return err
    data = request.get_json() or {}
    body, msg = _clean_body(data)
    if msg:
        return res(msg, None, 400)
    kind = _kind(data)
    if not kind:
        return res("kind must be ISSUE or FEATURE", None, 400)
    it = IssueTrackerItem(kind=kind, body_html=body, created_by=_uid(), created_at=datetime.utcnow())
    db.session.add(it)
    db.session.commit()
    return res("Added", _item_json(it, _names([it.created_by])), 201)


@issue_tracker_bp.route("/items/<int:item_id>", methods=["PUT"])
@login_required
def api_item_update(item_id):
    _, err = _gate("canEdit")
    if err:
        return err
    it = IssueTrackerItem.query.get(item_id)
    if not it:
        return res("Not found", None, 404)
    data = request.get_json() or {}
    if "bodyHtml" in data:
        body, msg = _clean_body(data)
        if msg:
            return res(msg, None, 400)
        it.body_html = body
    if "kind" in data:
        kind = _kind(data)
        if not kind:
            return res("kind must be ISSUE or FEATURE", None, 400)
        it.kind = kind
    it.updated_by = _uid()
    it.updated_at = datetime.utcnow()
    db.session.commit()
    return res("Saved", _item_json(it, _names([it.created_by, it.updated_by, it.done_by])))


@issue_tracker_bp.route("/items/<int:item_id>", methods=["DELETE"])
@login_required
def api_item_delete(item_id):
    _, err = _gate("canEdit")
    if err:
        return err
    it = IssueTrackerItem.query.get(item_id)
    if not it:
        return res("Not found", None, 404)
    files = list(it.done_images or [])
    db.session.delete(it)
    db.session.commit()
    _delete_files(files)
    return res("Deleted")


# ── done tick (developers) ──────────────────────────────────────

@issue_tracker_bp.route("/items/<int:item_id>/done", methods=["POST"])
@login_required
def api_item_done(item_id):
    """multipart: comment, keepImages (JSON list of existing URLs to keep), images[] (new files)."""
    _, err = _gate("isDeveloper")
    if err:
        return err
    it = IssueTrackerItem.query.get(item_id)
    if not it:
        return res("Not found", None, 404)

    form = request.form
    current = list(it.done_images or [])
    try:
        keep = json.loads(form.get("keepImages") or "null")
    except ValueError:
        return res("keepImages must be a JSON list", None, 400)
    keep = current if keep is None else [u for u in keep if u in current]

    files = [f for f in request.files.getlist("images") if f and f.filename]
    if len(keep) + len(files) > MAX_IMAGES:
        return res(f"Up to {MAX_IMAGES} pictures", None, 400)
    for f in files:
        ext = f.filename.rsplit(".", 1)[-1].lower() if "." in f.filename else ""
        if ext not in IMAGE_EXT:
            return res(f"{f.filename}: only picture files ({', '.join(sorted(IMAGE_EXT))})", None, 400)
        f.stream.seek(0, 2)
        size = f.stream.tell()
        f.stream.seek(0)
        if size > MAX_IMAGE_BYTES:
            return res(f"{f.filename}: bigger than 5 MB", None, 400)

    from app.cloudinary_uploader import upload_file_to_bunny
    added = []
    for f in files:
        url = upload_file_to_bunny(f, "issue_tracker", str(it.id), uuid.uuid4().hex)
        if not url:
            _delete_files(added)
            return res("Picture upload failed", None, 500)
        added.append(url)

    removed = [u for u in current if u not in keep]
    it.done_comment = (form.get("comment") or "").strip()[:5000] or None
    it.done_images = keep + added
    if not it.is_done:
        it.is_done = True
        it.done_by = _uid()
        it.done_at = datetime.utcnow()
    db.session.commit()
    _delete_files(removed)
    return res("Marked done", _item_json(it, _names([it.created_by, it.updated_by, it.done_by])))


@issue_tracker_bp.route("/items/<int:item_id>/done", methods=["DELETE"])
@login_required
def api_item_undone(item_id):
    """Untick. Comment and pictures are kept so a re-tick starts from them."""
    _, err = _gate("isDeveloper")
    if err:
        return err
    it = IssueTrackerItem.query.get(item_id)
    if not it:
        return res("Not found", None, 404)
    it.is_done = False
    it.done_by = None
    it.done_at = None
    db.session.commit()
    return res("Marked not done", _item_json(it, _names([it.created_by, it.updated_by])))
