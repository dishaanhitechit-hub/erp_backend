from flask import Blueprint, request, g
from flask_jwt_extended import jwt_required, get_jwt_identity
from app.middleware.auth_middleware import login_required

from app.modules.logistics.transit_request.service import (
    get_approved_orders_for_tr,
    get_order_items_for_tr,
    get_approved_trs_for_dc,
    create_tr,
    update_tr,
    get_tr_list,
    get_tr_detail,
    submit_tr,
    approve_tr,
    reback_tr,
    reject_tr,
    get_tr_history,
    get_tr_my_approval_status,
    delete_tr,
    update_transit_status,
)

tr_bp = Blueprint("transit_request", __name__)


@tr_bp.route("/approved-orders", methods=["GET"])
@jwt_required()
def api_approved_orders():
    return get_approved_orders_for_tr(
        project_code=request.args.get("projectCode"),
        order_type=request.args.get("orderType"),
    )


@tr_bp.route("/order-items/<int:order_id>", methods=["GET"])
@jwt_required()
def api_order_items(order_id):
    return get_order_items_for_tr(order_id)


@tr_bp.route("/approved-for-dc", methods=["GET"])
@jwt_required()
def api_approved_for_dc():
    return get_approved_trs_for_dc(
        project_code=request.args.get("projectCode"),
        order_id=request.args.get("orderId"),
    )


@tr_bp.route("/create", methods=["POST"])
@jwt_required()
def api_create_tr():
    user_id = int(get_jwt_identity())
    data = request.form.to_dict()
    files = request.files
    return create_tr(data, user_id, files)


@tr_bp.route("/edit/<int:tr_id>", methods=["PUT"])
@jwt_required()
def api_update_tr(tr_id):
    user_id = int(get_jwt_identity())
    data = request.form.to_dict()
    files = request.files
    return update_tr(tr_id, data, user_id, files)


@tr_bp.route("/list", methods=["GET"])
@jwt_required()
def api_tr_list():
    return get_tr_list(request.args.to_dict())


@tr_bp.route("/detail/<int:tr_id>", methods=["GET"])
@jwt_required()
def api_tr_detail(tr_id):
    return get_tr_detail(tr_id)


@tr_bp.route("/submit/<int:tr_id>", methods=["POST"])
@jwt_required()
def api_submit_tr(tr_id):
    user_id = int(get_jwt_identity())
    return submit_tr(tr_id, submitted_by=user_id)


@tr_bp.route("/approve/<int:tr_id>", methods=["POST"])
@jwt_required()
def api_approve_tr(tr_id):
    user_id = int(get_jwt_identity())
    body = request.get_json(silent=True) or {}
    return approve_tr(tr_id, approved_by=user_id, comments=body.get("comments"))


@tr_bp.route("/reback/<int:tr_id>", methods=["POST"])
@jwt_required()
def api_reback_tr(tr_id):
    user_id = int(get_jwt_identity())
    body = request.get_json(silent=True) or {}
    return reback_tr(tr_id, reback_by=user_id, comments=body.get("comments"))


@tr_bp.route("/reject/<int:tr_id>", methods=["POST"])
@jwt_required()
def api_reject_tr(tr_id):
    user_id = int(get_jwt_identity())
    body = request.get_json(silent=True) or {}
    return reject_tr(tr_id, rejected_by=user_id, comments=body.get("comments"))


@tr_bp.route("/history/<int:tr_id>", methods=["GET"])
@jwt_required()
def api_tr_history(tr_id):
    return get_tr_history(tr_id)


@tr_bp.route("/my-approval-status/<int:tr_id>", methods=["GET"])
@login_required
def api_tr_my_approval_status(tr_id):
    user = g.current_user
    return get_tr_my_approval_status(tr_id, user["id"])


@tr_bp.route("/<int:tr_id>", methods=["DELETE"])
@login_required
def api_delete_tr(tr_id):
    return delete_tr(tr_id)


@tr_bp.route("/update-transit-status/<int:tr_id>", methods=["POST"])
@login_required
def api_update_transit_status(tr_id):
    user = g.current_user
    body = request.get_json(silent=True) or {}
    return update_transit_status(tr_id, body.get("transitStatus"), user["id"])


@tr_bp.route("/print/<string:tr_uuid>", methods=["GET"])
@jwt_required()
def api_tr_print(tr_uuid):
    from app.models.transitRequest import TransitRequest as TRModel
    from app.response import res as _res
    tr = TRModel.query.filter_by(tr_uuid=tr_uuid).first()
    if not tr:
        return _res("Transit Request not found", {}, 404)
    return get_tr_detail(tr.id)
