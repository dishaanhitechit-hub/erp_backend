from flask import Blueprint, request, g
from app.middleware.auth_middleware import login_required
from app.modules.finance.journal_entry.journal_accounting.service import (
    get_approved_vouchers,
    create_journal_accounting,
    get_journal_accounting_list,
    get_journal_accounting_detail,
    get_journal_accounting_by_uuid,
    edit_journal_accounting,
    submit_journal_accounting,
    approve_journal_accounting,
    reback_journal_accounting,
    reject_journal_accounting,
    get_journal_accounting_history,
    get_journal_accounting_my_status,
)

journal_accounting_bp = Blueprint("journal_accounting", __name__)


@journal_accounting_bp.route("/approved-vouchers", methods=["GET"])
@login_required
def api_approved_vouchers():
    return get_approved_vouchers(request.args.to_dict())


@journal_accounting_bp.route("/create", methods=["POST"])
@login_required
def api_create():
    return create_journal_accounting(dict(request.form), g.current_user["id"])


@journal_accounting_bp.route("/list", methods=["GET"])
@login_required
def api_list():
    return get_journal_accounting_list(request.args.to_dict())


@journal_accounting_bp.route("/uuid/<string:voucher_uuid>", methods=["GET"])
def api_detail_by_uuid(voucher_uuid):
    return get_journal_accounting_by_uuid(voucher_uuid)


@journal_accounting_bp.route("/<int:accounting_id>", methods=["GET"])
@login_required
def api_detail(accounting_id):
    return get_journal_accounting_detail(accounting_id)


@journal_accounting_bp.route("/<int:accounting_id>/edit", methods=["PUT"])
@login_required
def api_edit(accounting_id):
    return edit_journal_accounting(accounting_id, dict(request.form), g.current_user["id"])


@journal_accounting_bp.route("/<int:accounting_id>/submit", methods=["POST"])
@journal_accounting_bp.route("/submit/<int:accounting_id>", methods=["POST"])
@login_required
def api_submit(accounting_id):
    return submit_journal_accounting(accounting_id, g.current_user["id"])


@journal_accounting_bp.route("/<int:accounting_id>/approve", methods=["POST"])
@journal_accounting_bp.route("/approve/<int:accounting_id>", methods=["POST"])
@login_required
def api_approve(accounting_id):
    body = request.get_json() or {}
    return approve_journal_accounting(accounting_id, g.current_user["id"], body.get("comments"))


@journal_accounting_bp.route("/<int:accounting_id>/reback", methods=["POST"])
@journal_accounting_bp.route("/reback/<int:accounting_id>", methods=["POST"])
@login_required
def api_reback(accounting_id):
    body = request.get_json() or {}
    return reback_journal_accounting(accounting_id, g.current_user["id"], body.get("comments"))


@journal_accounting_bp.route("/<int:accounting_id>/reject", methods=["POST"])
@journal_accounting_bp.route("/reject/<int:accounting_id>", methods=["POST"])
@login_required
def api_reject(accounting_id):
    body = request.get_json() or {}
    return reject_journal_accounting(accounting_id, g.current_user["id"], body.get("comments"))


@journal_accounting_bp.route("/<int:accounting_id>/history", methods=["GET"])
@login_required
def api_history(accounting_id):
    return get_journal_accounting_history(accounting_id)


@journal_accounting_bp.route("/<int:accounting_id>/my-status", methods=["GET"])
@login_required
def api_my_status(accounting_id):
    return get_journal_accounting_my_status(accounting_id, g.current_user["id"])
