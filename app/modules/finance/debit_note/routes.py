from flask import Blueprint, request, g
from app.middleware.auth_middleware import login_required
from app.modules.finance.debit_note.service import (
    create_debit_note,
    get_debit_note_list,
    get_debit_note_details,
    edit_debit_note,
    submit_debit_note,
    approve_debit_note,
    reback_debit_note,
    reject_debit_note,
    get_debit_note_history,
    get_dn_my_approval_status,
    get_debit_note_by_uuid,
)

debit_note_bp = Blueprint("debit_note", __name__)


# ── 1. CREATE ─────────────────────────────────────────────────────
@debit_note_bp.route("/create", methods=["POST"])
@login_required
def api_create_debit_note():
    data    = request.get_json() or {}
    user_id = g.current_user.get("id") if hasattr(g, "current_user") else None
    return create_debit_note(data, user_id)


# ── 2. LIST ───────────────────────────────────────────────────────
@debit_note_bp.route("/list", methods=["GET"])
@login_required
def api_debit_note_list():
    return get_debit_note_list(request.args.to_dict())


# ── 3. DETAILS ────────────────────────────────────────────────────
@debit_note_bp.route("/<int:dn_id>", methods=["GET"])
@login_required
def api_debit_note_details(dn_id):
    return get_debit_note_details(dn_id)


# ── 4. EDIT ───────────────────────────────────────────────────────
@debit_note_bp.route("/edit/<int:dn_id>", methods=["PUT"])
@login_required
def api_edit_debit_note(dn_id):
    data    = request.get_json() or {}
    user_id = g.current_user.get("id") if hasattr(g, "current_user") else None
    return edit_debit_note(dn_id, data, user_id)


# ── 5. SUBMIT ─────────────────────────────────────────────────────
@debit_note_bp.route("/submit/<int:dn_id>", methods=["POST"])
@login_required
def api_submit_debit_note(dn_id):
    user_id = g.current_user.get("id") if hasattr(g, "current_user") else None
    return submit_debit_note(dn_id, user_id)


# ── 6. APPROVE ────────────────────────────────────────────────────
@debit_note_bp.route("/approve/<int:dn_id>", methods=["POST"])
@login_required
def api_approve_debit_note(dn_id):
    data        = request.get_json() or {}
    approved_by = g.current_user.get("id") if hasattr(g, "current_user") else None
    return approve_debit_note(dn_id, approved_by, data.get("comments"))


# ── 7. REBACK ─────────────────────────────────────────────────────
@debit_note_bp.route("/reback/<int:dn_id>", methods=["POST"])
@login_required
def api_reback_debit_note(dn_id):
    data      = request.get_json() or {}
    reback_by = g.current_user.get("id") if hasattr(g, "current_user") else None
    return reback_debit_note(dn_id, reback_by, data.get("comments"))


# ── 8. REJECT ─────────────────────────────────────────────────────
@debit_note_bp.route("/reject/<int:dn_id>", methods=["POST"])
@login_required
def api_reject_debit_note(dn_id):
    data        = request.get_json() or {}
    rejected_by = g.current_user.get("id") if hasattr(g, "current_user") else None
    return reject_debit_note(dn_id, rejected_by, data.get("comments"))


# ── 9. HISTORY ────────────────────────────────────────────────────
@debit_note_bp.route("/history/<int:dn_id>", methods=["GET"])
@login_required
def api_debit_note_history(dn_id):
    return get_debit_note_history(dn_id)


# ── 10. MY APPROVAL STATUS ────────────────────────────────────────
@debit_note_bp.route("/my-approval-status/<int:dn_id>", methods=["GET"])
@login_required
def api_dn_my_approval_status(dn_id):
    user_id = g.current_user.get("id") if hasattr(g, "current_user") else None
    return get_dn_my_approval_status(dn_id, user_id)


# ── 11. UUID (public — no JWT) ────────────────────────────────────
@debit_note_bp.route("/uuid/<string:dn_uuid>", methods=["GET"])
def api_debit_note_by_uuid(dn_uuid):
    return get_debit_note_by_uuid(dn_uuid)
