from flask import Blueprint, request, g
from app.middleware.auth_middleware import login_required
from app.modules.finance.journal_entry.journal_voucher.service import (
    get_available_dockets,
    create_journal_voucher,
    get_journal_voucher_list,
    get_journal_voucher_detail,
    get_journal_voucher_by_uuid,
    edit_journal_voucher,
    submit_journal_voucher,
    approve_journal_voucher,
    reback_journal_voucher,
    reject_journal_voucher,
    get_journal_voucher_history,
    get_journal_voucher_my_status,
)

journal_voucher_bp = Blueprint("journal_voucher", __name__)


# ── 0. AVAILABLE DOCKETS ──────────────────────────────────────────
@journal_voucher_bp.route("/available-dockets", methods=["GET"])
@login_required
def api_available_dockets():
    return get_available_dockets(request.args.to_dict())


# ── 1. CREATE ─────────────────────────────────────────────────────
@journal_voucher_bp.route("/create", methods=["POST"])
@login_required
def api_create():
    return create_journal_voucher(dict(request.form), g.current_user["id"])


# ── 2. LIST ───────────────────────────────────────────────────────
@journal_voucher_bp.route("/list", methods=["GET"])
@login_required
def api_list():
    return get_journal_voucher_list(request.args.to_dict())


# ── 3. GET BY UUID (no-auth) ──────────────────────────────────────
@journal_voucher_bp.route("/uuid/<string:voucher_uuid>", methods=["GET"])
def api_detail_by_uuid(voucher_uuid):
    return get_journal_voucher_by_uuid(voucher_uuid)


# ── 4. GET BY ID ──────────────────────────────────────────────────
@journal_voucher_bp.route("/<int:journal_id>", methods=["GET"])
@login_required
def api_detail(journal_id):
    return get_journal_voucher_detail(journal_id)


# ── 5. EDIT ───────────────────────────────────────────────────────
@journal_voucher_bp.route("/edit/<int:journal_id>", methods=["PUT"])
@login_required
def api_edit(journal_id):
    return edit_journal_voucher(journal_id, dict(request.form), g.current_user["id"])


# ── 6. SUBMIT ─────────────────────────────────────────────────────
@journal_voucher_bp.route("/submit/<int:journal_id>", methods=["POST"])
@login_required
def api_submit(journal_id):
    return submit_journal_voucher(journal_id, g.current_user["id"])


# ── 7. APPROVE ────────────────────────────────────────────────────
@journal_voucher_bp.route("/approve/<int:journal_id>", methods=["POST"])
@login_required
def api_approve(journal_id):
    body = request.get_json() or {}
    return approve_journal_voucher(journal_id, g.current_user["id"], body.get("comments"))


# ── 8. REBACK ─────────────────────────────────────────────────────
@journal_voucher_bp.route("/reback/<int:journal_id>", methods=["POST"])
@login_required
def api_reback(journal_id):
    body = request.get_json() or {}
    return reback_journal_voucher(journal_id, g.current_user["id"], body.get("comments"))


# ── 9. REJECT ─────────────────────────────────────────────────────
@journal_voucher_bp.route("/reject/<int:journal_id>", methods=["POST"])
@login_required
def api_reject(journal_id):
    body = request.get_json() or {}
    return reject_journal_voucher(journal_id, g.current_user["id"], body.get("comments"))


# ── 10. HISTORY ───────────────────────────────────────────────────
@journal_voucher_bp.route("/history/<int:journal_id>", methods=["GET"])
@login_required
def api_history(journal_id):
    return get_journal_voucher_history(journal_id)


# ── 11. MY APPROVAL STATUS ────────────────────────────────────────
@journal_voucher_bp.route("/my-approval-status/<int:journal_id>", methods=["GET"])
@login_required
def api_my_status(journal_id):
    return get_journal_voucher_my_status(journal_id, g.current_user["id"])
