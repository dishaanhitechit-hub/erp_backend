from flask import Blueprint, request, g
from app.middleware.auth_middleware import login_required

from app.modules.resources.dlr.service import (
    create_dlr,
    get_dlr_list,
    get_dlr_details,
    edit_dlr,
    submit_dlr,
    approve_dlr,
    reback_dlr,
    reject_dlr,
    get_dlr_history,
    get_dlr_my_approval_status,
    get_dlr_summary,
    get_labour_by_supplier,
    get_pw_orders_by_supplier,
    _project_code,
    _current_user,
)

dlr_bp = Blueprint("dlr", __name__)


def _resolve_project_code():
    _, project_id = _current_user()
    return _project_code(project_id)


@dlr_bp.route("/create", methods=["POST"])
@login_required
def api_create_dlr():
    return create_dlr(request)


@dlr_bp.route("/list", methods=["GET"])
@login_required
def api_dlr_list():
    return get_dlr_list()


@dlr_bp.route("/details/<int:dlr_id>", methods=["GET"])
@login_required
def api_dlr_details(dlr_id):
    return get_dlr_details(dlr_id)


@dlr_bp.route("/edit/<int:dlr_id>", methods=["PUT"])
@login_required
def api_edit_dlr(dlr_id):
    return edit_dlr(dlr_id, request)


@dlr_bp.route("/submit/<int:dlr_id>", methods=["POST"])
@login_required
def api_submit_dlr(dlr_id):
    user_id, _ = _current_user()
    code = _resolve_project_code()
    return submit_dlr(dlr_id, user_id, code)


@dlr_bp.route("/approve/<int:dlr_id>", methods=["POST"])
@login_required
def api_approve_dlr(dlr_id):
    user_id, _ = _current_user()
    code = _resolve_project_code()
    data = request.get_json(silent=True) or {}
    return approve_dlr(dlr_id, user_id, code, data.get("comments"))


@dlr_bp.route("/reback/<int:dlr_id>", methods=["POST"])
@login_required
def api_reback_dlr(dlr_id):
    user_id, _ = _current_user()
    code = _resolve_project_code()
    data = request.get_json(silent=True) or {}
    return reback_dlr(dlr_id, user_id, code, data.get("comments"))


@dlr_bp.route("/reject/<int:dlr_id>", methods=["POST"])
@login_required
def api_reject_dlr(dlr_id):
    user_id, _ = _current_user()
    code = _resolve_project_code()
    data = request.get_json(silent=True) or {}
    return reject_dlr(dlr_id, user_id, code, data.get("comments"))


@dlr_bp.route("/history/<int:dlr_id>", methods=["GET"])
@login_required
def api_dlr_history(dlr_id):
    code = _resolve_project_code()
    return get_dlr_history(dlr_id, code)


@dlr_bp.route("/my-approval-status/<int:dlr_id>", methods=["GET"])
@login_required
def api_dlr_my_approval_status(dlr_id):
    user_id, _ = _current_user()
    code = _resolve_project_code()
    return get_dlr_my_approval_status(dlr_id, user_id, code)


@dlr_bp.route("/summary/<int:dlr_id>", methods=["GET"])
@login_required
def api_dlr_summary(dlr_id):
    return get_dlr_summary(dlr_id)


@dlr_bp.route("/labour-by-supplier/<int:supplier_id>", methods=["GET"])
@login_required
def api_dlr_labour_by_supplier(supplier_id):
    return get_labour_by_supplier(supplier_id)


@dlr_bp.route("/pw-orders-by-supplier/<int:supplier_id>", methods=["GET"])
@login_required
def api_dlr_pw_orders_by_supplier(supplier_id):
    return get_pw_orders_by_supplier(supplier_id)
