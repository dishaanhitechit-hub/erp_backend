from flask import Blueprint, request, g
from flask_jwt_extended import jwt_required, get_jwt_identity
from app.middleware.auth_middleware import login_required

from app.modules.logistics.bill_register.service import (
    get_eligible_dcs,
    create_lb,
    update_lb,
    get_lb_list,
    get_lb_detail,
    submit_lb,
    approve_lb,
    reback_lb,
    reject_lb,
    get_lb_history,
    get_lb_my_approval_status,
    delete_lb,
)

lb_bp = Blueprint("logistics_bill", __name__)


@lb_bp.route("/eligible-dcs", methods=["GET"])
@jwt_required()
def api_eligible_dcs():
    return get_eligible_dcs(request.args.get("projectCode"))


@lb_bp.route("/create", methods=["POST"])
@jwt_required()
def api_create_lb():
    user_id = int(get_jwt_identity())
    data = request.form.to_dict()
    files = request.files
    return create_lb(data, user_id, files)


@lb_bp.route("/edit/<int:lb_id>", methods=["PUT"])
@jwt_required()
def api_update_lb(lb_id):
    user_id = int(get_jwt_identity())
    data = request.form.to_dict()
    files = request.files
    return update_lb(lb_id, data, user_id, files)


@lb_bp.route("/list", methods=["GET"])
@jwt_required()
def api_lb_list():
    return get_lb_list(request.args.to_dict())


@lb_bp.route("/detail/<int:lb_id>", methods=["GET"])
@jwt_required()
def api_lb_detail(lb_id):
    return get_lb_detail(lb_id)


@lb_bp.route("/submit/<int:lb_id>", methods=["POST"])
@jwt_required()
def api_submit_lb(lb_id):
    user_id = int(get_jwt_identity())
    return submit_lb(lb_id, submitted_by=user_id)


@lb_bp.route("/approve/<int:lb_id>", methods=["POST"])
@jwt_required()
def api_approve_lb(lb_id):
    user_id = int(get_jwt_identity())
    body = request.get_json(silent=True) or {}
    return approve_lb(lb_id, approved_by=user_id, comments=body.get("comments"))


@lb_bp.route("/reback/<int:lb_id>", methods=["POST"])
@jwt_required()
def api_reback_lb(lb_id):
    user_id = int(get_jwt_identity())
    body = request.get_json(silent=True) or {}
    return reback_lb(lb_id, reback_by=user_id, comments=body.get("comments"))


@lb_bp.route("/reject/<int:lb_id>", methods=["POST"])
@jwt_required()
def api_reject_lb(lb_id):
    user_id = int(get_jwt_identity())
    body = request.get_json(silent=True) or {}
    return reject_lb(lb_id, rejected_by=user_id, comments=body.get("comments"))


@lb_bp.route("/history/<int:lb_id>", methods=["GET"])
@jwt_required()
def api_lb_history(lb_id):
    return get_lb_history(lb_id)


@lb_bp.route("/my-approval-status/<int:lb_id>", methods=["GET"])
@login_required
def api_lb_my_approval_status(lb_id):
    user = g.current_user
    return get_lb_my_approval_status(lb_id, user["id"])


@lb_bp.route("/<int:lb_id>", methods=["DELETE"])
@login_required
def api_delete_lb(lb_id):
    return delete_lb(lb_id)


@lb_bp.route("/print/<string:lb_uuid>", methods=["GET"])
@jwt_required()
def api_lb_print(lb_uuid):
    from app.models.logisticsBill import LogisticsBill as LBModel
    from app.response import res as _res
    lb = LBModel.query.filter_by(lb_uuid=lb_uuid).first()
    if not lb:
        return _res("Logistics Bill not found", {}, 404)
    return get_lb_detail(lb.id)
