from flask import Blueprint, request, g
from app.middleware.auth_middleware import login_required
from app.modules.finance.journal_entry.journal_voucher.service import (
    get_available_dockets,
    create_journal_voucher,
    get_journal_voucher_list,
    get_journal_voucher_detail,
    edit_journal_voucher,
    submit_journal_voucher,
    approve_journal_voucher,
    reback_journal_voucher,
    reject_journal_voucher,
    get_journal_voucher_history,
    get_journal_voucher_my_status,
)

journal_voucher_bp = Blueprint("journal_voucher", __name__)


@journal_voucher_bp.route("/available-dockets", methods=["GET"])
@login_required
def api_available_dockets():
    return get_available_dockets(request.args.to_dict())


@journal_voucher_bp.route("/create", methods=["POST"])
@login_required
def api_create():
    return create_journal_voucher(dict(request.form), g.current_user["id"])


@journal_voucher_bp.route("/list", methods=["GET"])
@login_required
def api_list():
    return get_journal_voucher_list(request.args.to_dict())


@journal_voucher_bp.route("/<int:journal_id>", methods=["GET"])
@login_required
def api_detail(journal_id):
    return get_journal_voucher_detail(journal_id)


@journal_voucher_bp.route("/<int:journal_id>/edit", methods=["PUT"])
@login_required
def api_edit(journal_id):
    return edit_journal_voucher(journal_id, dict(request.form), g.current_user["id"])


@journal_voucher_bp.route("/<int:journal_id>/submit", methods=["POST"])
@login_required
def api_submit(journal_id):
    return submit_journal_voucher(journal_id, g.current_user["id"])


@journal_voucher_bp.route("/<int:journal_id>/approve", methods=["POST"])
@login_required
def api_approve(journal_id):
    body = request.get_json() or {}
    return approve_journal_voucher(journal_id, g.current_user["id"], body.get("comments"))


@journal_voucher_bp.route("/<int:journal_id>/reback", methods=["POST"])
@login_required
def api_reback(journal_id):
    body = request.get_json() or {}
    return reback_journal_voucher(journal_id, g.current_user["id"], body.get("comments"))


@journal_voucher_bp.route("/<int:journal_id>/reject", methods=["POST"])
@login_required
def api_reject(journal_id):
    body = request.get_json() or {}
    return reject_journal_voucher(journal_id, g.current_user["id"], body.get("comments"))


@journal_voucher_bp.route("/<int:journal_id>/history", methods=["GET"])
@login_required
def api_history(journal_id):
    return get_journal_voucher_history(journal_id)


@journal_voucher_bp.route("/<int:journal_id>/my-status", methods=["GET"])
@login_required
def api_my_status(journal_id):
    return get_journal_voucher_my_status(journal_id, g.current_user["id"])
