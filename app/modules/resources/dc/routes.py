from flask import Blueprint, request, g
from flask_jwt_extended import jwt_required, get_jwt_identity
from app.middleware.auth_middleware import login_required

from app.modules.resources.dc.service import (
    get_approved_orders_for_dc,
    get_order_items_for_dc,
    get_from_details,
    create_dc,
    update_dc,
    get_dc_list,
    get_dc_detail,
    submit_dc,
    approve_dc,
    reject_dc,
    reback_dc,
    get_dc_history,
    get_dc_my_approval_status,
    get_dc_print_detail,
    update_dc_transit_status,
    upload_dc_pod,
    verify_dc_pod,
)

dc_bp = Blueprint("dc", __name__)


# ── GET approved orders for DC order selection ─────────────────────
# Query params: projectCode, orderType
@dc_bp.route("/approved-orders", methods=["GET"])
@jwt_required()
def api_approved_orders():
    return get_approved_orders_for_dc(
        project_code=request.args.get("projectCode"),
        order_type=request.args.get("orderType")
    )


# ── GET order items for a selected order ───────────────────────────
@dc_bp.route("/order-items/<int:order_id>", methods=["GET"])
@jwt_required()
def api_order_items(order_id):
    return get_order_items_for_dc(order_id)


# ── GET from-side auto-fill details ────────────────────────────────
# Query params: currentProjectCode
@dc_bp.route("/from-details/<int:order_id>", methods=["GET"])
@jwt_required()
def api_from_details(order_id):
    return get_from_details(
        order_id=order_id,
        current_project_code=request.args.get("currentProjectCode")
    )


# ── CREATE DC ──────────────────────────────────────────────────────
@dc_bp.route("/create", methods=["POST"])
@jwt_required()
def api_create_dc():
    user_id = int(get_jwt_identity())
    data = request.form.to_dict()
    files = request.files
    return create_dc(data, user_id, files)


# ── DC LIST ────────────────────────────────────────────────────────
# Query params: projectCode, orderType, workflowStatus, search
@dc_bp.route("/list", methods=["GET"])
@jwt_required()
def api_dc_list():
    return get_dc_list(request.args.to_dict())


# ── DC DETAIL ──────────────────────────────────────────────────────
@dc_bp.route("/detail/<int:dc_id>", methods=["GET"])
@jwt_required()
def api_dc_detail(dc_id):
    return get_dc_detail(dc_id)


# ── SUBMIT DC ──────────────────────────────────────────────────────
@dc_bp.route("/submit/<int:dc_id>", methods=["POST"])
@jwt_required()
def api_submit_dc(dc_id):
    user_id = int(get_jwt_identity())
    return submit_dc(dc_id, submitted_by=user_id)


# ── APPROVE DC ─────────────────────────────────────────────────────
@dc_bp.route("/approve/<int:dc_id>", methods=["POST"])
@jwt_required()
def api_approve_dc(dc_id):
    user_id = int(get_jwt_identity())
    body = request.get_json(silent=True) or {}
    return approve_dc(dc_id, approved_by=user_id, comments=body.get("comments"))


# ── REJECT DC ──────────────────────────────────────────────────────
@dc_bp.route("/reject/<int:dc_id>", methods=["POST"])
@jwt_required()
def api_reject_dc(dc_id):
    user_id = int(get_jwt_identity())
    body = request.get_json(silent=True) or {}
    return reject_dc(dc_id, rejected_by=user_id, comments=body.get("comments"))


# ── REBACK DC (send for correction) ────────────────────────────────
@dc_bp.route("/reback/<int:dc_id>", methods=["POST"])
@jwt_required()
def api_reback_dc(dc_id):
    user_id = int(get_jwt_identity())
    body = request.get_json(silent=True) or {}
    return reback_dc(dc_id, reback_by=user_id, comments=body.get("comments"))


# ── DC HISTORY ─────────────────────────────────────────────────────
@dc_bp.route("/history/<int:dc_id>", methods=["GET"])
@jwt_required()
def api_dc_history(dc_id):
    return get_dc_history(dc_id)


@dc_bp.route("/my-approval-status/<int:dc_id>", methods=["GET"])
@login_required
def api_dc_my_approval_status(dc_id):
    user = g.current_user
    return get_dc_my_approval_status(dc_id, user["id"])


@dc_bp.route("/edit/<int:dc_id>", methods=["PUT"])
@jwt_required()
def api_update_dc(dc_id):
    user_id = int(get_jwt_identity())
    data = request.form.to_dict()
    files = request.files
    return update_dc(dc_id, data, user_id, files)


@dc_bp.route("/print/<string:dc_uuid>", methods=["GET"])
@jwt_required()
def api_dc_print(dc_uuid):
    return get_dc_print_detail(dc_uuid)


@dc_bp.route("/<int:dc_id>", methods=["DELETE"])
@login_required
def api_delete_dc(dc_id):
    from .service import delete_dc
    return delete_dc(dc_id)


# ── Transit status (operational, no approval) ──────────────────────
@dc_bp.route("/update-transit-status/<int:dc_id>", methods=["POST"])
@login_required
def api_update_dc_transit_status(dc_id):
    user = g.current_user
    body = request.get_json(silent=True) or {}
    return update_dc_transit_status(dc_id, body.get("transitStatus"), user["id"])


# ── POD upload / verify ───────────────────────────────────────────
@dc_bp.route("/upload-pod/<int:dc_id>", methods=["POST"])
@login_required
def api_upload_dc_pod(dc_id):
    user = g.current_user
    pod_file = request.files.get("podFile")
    return upload_dc_pod(dc_id, pod_file, user["id"])


@dc_bp.route("/verify-pod/<int:dc_id>", methods=["POST"])
@login_required
def api_verify_dc_pod(dc_id):
    user = g.current_user
    return verify_dc_pod(dc_id, user["id"])
