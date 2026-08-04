from flask import Blueprint, request, g
from app.middleware.auth_middleware import login_required
from app.modules.finance.contra_entry.service import (
    create_contra_entry,
    get_contra_entry_list,
    get_contra_entry_details,
    edit_contra_entry,
    submit_contra_entry,
    approve_contra_entry,
    reback_contra_entry,
    reject_contra_entry,
    get_contra_entry_history,
    get_contra_entry_my_approval_status,
    get_contra_entry_by_uuid,
)

contra_entry_bp = Blueprint("contra_entry", __name__)


# ── 1. CREATE ─────────────────────────────────────────────────────
@contra_entry_bp.route("/create", methods=["POST"])
@login_required
def api_create_contra_entry():
    data    = request.get_json() or {}
    user_id = g.current_user.get("id") if hasattr(g, "current_user") else None
    return create_contra_entry(data, user_id)


# ── 2. LIST ───────────────────────────────────────────────────────
@contra_entry_bp.route("/list", methods=["GET"])
@login_required
def api_contra_entry_list():
    return get_contra_entry_list(request.args.to_dict())


# ── 3. DETAILS ────────────────────────────────────────────────────
@contra_entry_bp.route("/<int:entry_id>", methods=["GET"])
@login_required
def api_contra_entry_details(entry_id):
    return get_contra_entry_details(entry_id)


# ── 4. EDIT ───────────────────────────────────────────────────────
@contra_entry_bp.route("/edit/<int:entry_id>", methods=["PUT"])
@login_required
def api_edit_contra_entry(entry_id):
    data    = request.get_json() or {}
    user_id = g.current_user.get("id") if hasattr(g, "current_user") else None
    return edit_contra_entry(entry_id, data, user_id)


# ── 5. SUBMIT ─────────────────────────────────────────────────────
@contra_entry_bp.route("/submit/<int:entry_id>", methods=["POST"])
@login_required
def api_submit_contra_entry(entry_id):
    user_id = g.current_user.get("id") if hasattr(g, "current_user") else None
    return submit_contra_entry(entry_id, user_id)


# ── 6. APPROVE ────────────────────────────────────────────────────
@contra_entry_bp.route("/approve/<int:entry_id>", methods=["POST"])
@login_required
def api_approve_contra_entry(entry_id):
    data        = request.get_json() or {}
    approved_by = g.current_user.get("id") if hasattr(g, "current_user") else None
    return approve_contra_entry(entry_id, approved_by, data.get("comments"))


# ── 7. REBACK ─────────────────────────────────────────────────────
@contra_entry_bp.route("/reback/<int:entry_id>", methods=["POST"])
@login_required
def api_reback_contra_entry(entry_id):
    data      = request.get_json() or {}
    reback_by = g.current_user.get("id") if hasattr(g, "current_user") else None
    return reback_contra_entry(entry_id, reback_by, data.get("comments"))


# ── 8. REJECT ─────────────────────────────────────────────────────
@contra_entry_bp.route("/reject/<int:entry_id>", methods=["POST"])
@login_required
def api_reject_contra_entry(entry_id):
    data        = request.get_json() or {}
    rejected_by = g.current_user.get("id") if hasattr(g, "current_user") else None
    return reject_contra_entry(entry_id, rejected_by, data.get("comments"))


# ── 9. HISTORY ────────────────────────────────────────────────────
@contra_entry_bp.route("/history/<int:entry_id>", methods=["GET"])
@login_required
def api_contra_entry_history(entry_id):
    return get_contra_entry_history(entry_id)


# ── 10. MY APPROVAL STATUS ────────────────────────────────────────
@contra_entry_bp.route("/my-approval-status/<int:entry_id>", methods=["GET"])
@login_required
def api_contra_entry_my_approval_status(entry_id):
    user_id = g.current_user.get("id") if hasattr(g, "current_user") else None
    return get_contra_entry_my_approval_status(entry_id, user_id)


# ── 11. UUID (public — no JWT) ────────────────────────────────────
@contra_entry_bp.route("/uuid/<string:entry_uuid>", methods=["GET"])
def api_contra_entry_by_uuid(entry_uuid):
    return get_contra_entry_by_uuid(entry_uuid)
