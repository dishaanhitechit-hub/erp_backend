from flask import Blueprint, request, g
from app.middleware.auth_middleware import login_required
from app.modules.finance.journal_entry.service import (
    create_journal_entry,
    get_journal_entry_list,
    get_journal_entry_details,
    get_journal_entry_by_uuid,
    edit_journal_entry,
    submit_journal_entry,
    approve_journal_entry,
    reback_journal_entry,
    reject_journal_entry,
    get_journal_entry_history,
    get_journal_entry_my_approval_status,
)

journal_entry_bp = Blueprint("journal_entry", __name__)


# ── 1. CREATE ─────────────────────────────────────────────────────
@journal_entry_bp.route("/create", methods=["POST"])
@login_required
def api_create_journal_entry():
    data    = request.get_json() or {}
    user_id = g.current_user.get("id") if hasattr(g, "current_user") else None
    return create_journal_entry(data, user_id)


# ── 2. LIST ───────────────────────────────────────────────────────
@journal_entry_bp.route("/list", methods=["GET"])
@login_required
def api_journal_entry_list():
    return get_journal_entry_list(request.args.to_dict())


# ── 3. GET BY ID ──────────────────────────────────────────────────
@journal_entry_bp.route("/<int:entry_id>", methods=["GET"])
@login_required
def api_journal_entry_details(entry_id):
    return get_journal_entry_details(entry_id)


# ── 4. GET BY UUID (no-auth) ──────────────────────────────────────
@journal_entry_bp.route("/uuid/<string:entry_uuid>", methods=["GET"])
def api_journal_entry_by_uuid(entry_uuid):
    return get_journal_entry_by_uuid(entry_uuid)


# ── 5. EDIT ───────────────────────────────────────────────────────
@journal_entry_bp.route("/edit/<int:entry_id>", methods=["PUT"])
@login_required
def api_edit_journal_entry(entry_id):
    data    = request.get_json() or {}
    user_id = g.current_user.get("id") if hasattr(g, "current_user") else None
    return edit_journal_entry(entry_id, data, user_id)


# ── 6. SUBMIT ─────────────────────────────────────────────────────
@journal_entry_bp.route("/submit/<int:entry_id>", methods=["POST"])
@login_required
def api_submit_journal_entry(entry_id):
    user_id = g.current_user.get("id") if hasattr(g, "current_user") else None
    return submit_journal_entry(entry_id, user_id)


# ── 7. APPROVE ────────────────────────────────────────────────────
@journal_entry_bp.route("/approve/<int:entry_id>", methods=["POST"])
@login_required
def api_approve_journal_entry(entry_id):
    data        = request.get_json() or {}
    approved_by = g.current_user.get("id") if hasattr(g, "current_user") else None
    return approve_journal_entry(entry_id, approved_by, data.get("comments"))


# ── 8. REBACK ─────────────────────────────────────────────────────
@journal_entry_bp.route("/reback/<int:entry_id>", methods=["POST"])
@login_required
def api_reback_journal_entry(entry_id):
    data      = request.get_json() or {}
    reback_by = g.current_user.get("id") if hasattr(g, "current_user") else None
    return reback_journal_entry(entry_id, reback_by, data.get("comments"))


# ── 9. REJECT ─────────────────────────────────────────────────────
@journal_entry_bp.route("/reject/<int:entry_id>", methods=["POST"])
@login_required
def api_reject_journal_entry(entry_id):
    data        = request.get_json() or {}
    rejected_by = g.current_user.get("id") if hasattr(g, "current_user") else None
    return reject_journal_entry(entry_id, rejected_by, data.get("comments"))


# ── 10. HISTORY ───────────────────────────────────────────────────
@journal_entry_bp.route("/history/<int:entry_id>", methods=["GET"])
@login_required
def api_journal_entry_history(entry_id):
    return get_journal_entry_history(entry_id)


# ── 11. MY APPROVAL STATUS ────────────────────────────────────────
@journal_entry_bp.route("/my-approval-status/<int:entry_id>", methods=["GET"])
@login_required
def api_journal_entry_my_approval_status(entry_id):
    user_id = g.current_user.get("id") if hasattr(g, "current_user") else None
    return get_journal_entry_my_approval_status(entry_id, user_id)
