from flask import Blueprint, request, g
from app.middleware.auth_middleware import login_required
from app.modules.finance.credit_note.service import (
    create_credit_note,
    get_credit_note_list,
    get_credit_note_details,
    edit_credit_note,
    submit_credit_note,
    approve_credit_note,
    reback_credit_note,
    reject_credit_note,
    get_credit_note_history,
    get_cn_my_approval_status,
    get_credit_note_by_uuid,
)

credit_note_bp = Blueprint("credit_note", __name__)


# ── 1. CREATE ─────────────────────────────────────────────────────
@credit_note_bp.route("/create", methods=["POST"])
@login_required
def api_create_credit_note():
    data    = request.get_json() or {}
    user_id = g.current_user.get("id") if hasattr(g, "current_user") else None
    return create_credit_note(data, user_id)


# ── 2. LIST ───────────────────────────────────────────────────────
@credit_note_bp.route("/list", methods=["GET"])
@login_required
def api_credit_note_list():
    return get_credit_note_list(request.args.to_dict())


# ── 3. DETAILS ────────────────────────────────────────────────────
@credit_note_bp.route("/<int:cn_id>", methods=["GET"])
@login_required
def api_credit_note_details(cn_id):
    return get_credit_note_details(cn_id)


# ── 4. EDIT ───────────────────────────────────────────────────────
@credit_note_bp.route("/edit/<int:cn_id>", methods=["PUT"])
@login_required
def api_edit_credit_note(cn_id):
    data    = request.get_json() or {}
    user_id = g.current_user.get("id") if hasattr(g, "current_user") else None
    return edit_credit_note(cn_id, data, user_id)


# ── 5. SUBMIT ─────────────────────────────────────────────────────
@credit_note_bp.route("/submit/<int:cn_id>", methods=["POST"])
@login_required
def api_submit_credit_note(cn_id):
    user_id = g.current_user.get("id") if hasattr(g, "current_user") else None
    return submit_credit_note(cn_id, user_id)


# ── 6. APPROVE ────────────────────────────────────────────────────
@credit_note_bp.route("/approve/<int:cn_id>", methods=["POST"])
@login_required
def api_approve_credit_note(cn_id):
    data        = request.get_json() or {}
    approved_by = g.current_user.get("id") if hasattr(g, "current_user") else None
    return approve_credit_note(cn_id, approved_by, data.get("comments"))


# ── 7. REBACK ─────────────────────────────────────────────────────
@credit_note_bp.route("/reback/<int:cn_id>", methods=["POST"])
@login_required
def api_reback_credit_note(cn_id):
    data      = request.get_json() or {}
    reback_by = g.current_user.get("id") if hasattr(g, "current_user") else None
    return reback_credit_note(cn_id, reback_by, data.get("comments"))


# ── 8. REJECT ─────────────────────────────────────────────────────
@credit_note_bp.route("/reject/<int:cn_id>", methods=["POST"])
@login_required
def api_reject_credit_note(cn_id):
    data        = request.get_json() or {}
    rejected_by = g.current_user.get("id") if hasattr(g, "current_user") else None
    return reject_credit_note(cn_id, rejected_by, data.get("comments"))


# ── 9. HISTORY ────────────────────────────────────────────────────
@credit_note_bp.route("/history/<int:cn_id>", methods=["GET"])
@login_required
def api_credit_note_history(cn_id):
    return get_credit_note_history(cn_id)


# ── 10. MY APPROVAL STATUS ────────────────────────────────────────
@credit_note_bp.route("/my-approval-status/<int:cn_id>", methods=["GET"])
@login_required
def api_cn_my_approval_status(cn_id):
    user_id = g.current_user.get("id") if hasattr(g, "current_user") else None
    return get_cn_my_approval_status(cn_id, user_id)


# ── 11. UUID (public — no JWT) ────────────────────────────────────
@credit_note_bp.route("/uuid/<string:cn_uuid>", methods=["GET"])
def api_credit_note_by_uuid(cn_uuid):
    return get_credit_note_by_uuid(cn_uuid)
