from flask import Blueprint, request
from flask_jwt_extended import jwt_required, get_jwt_identity

from app.utils.txn_tracker import TransactionTracker

from app.modules.billing.brr_billing_grn.service import (
    get_grns_by_brr,
    create_brg,
    get_brg_list,
    get_brg_details,
    edit_brg,
    submit_brg,
    approve_brg,
    reback_brg,
    reject_brg,
    get_brg_history,
)

brg_bp = Blueprint("brg", __name__)


# ==========================================
# GET GRNs BY BRR  (selection grid)
# ==========================================

@brg_bp.route("/grns-by-brr/<int:brr_id>", methods=["GET"])
@jwt_required()
def api_grns_by_brr(brr_id):
    return get_grns_by_brr(brr_id)


# ==========================================
# CREATE BRG
# ==========================================

@brg_bp.route("/create", methods=["POST"])
@jwt_required()
def api_create_brg():
    user_id = get_jwt_identity()
    TransactionTracker.mark_open(user_id, "brg_create")
    response = create_brg(data=request.get_json() or {}, user_id=user_id)
    TransactionTracker.mark_closed(user_id)
    return response


# ==========================================
# LIST
# ==========================================

@brg_bp.route("/list", methods=["GET"])
@jwt_required()
def api_brg_list():
    data = {
        "projectCode":    request.args.get("projectCode"),
        "vendorId":       request.args.get("vendorId"),
        "brrId":          request.args.get("brrId"),
        "orderId":        request.args.get("orderId"),
        "workflowStatus": request.args.get("workflowStatus"),
        "search":         request.args.get("search"),
    }
    return get_brg_list(data)


# ==========================================
# DETAILS
# ==========================================

@brg_bp.route("/details/<int:brg_id>", methods=["GET"])
@jwt_required()
def api_brg_details(brg_id):
    return get_brg_details(brg_id)


# ==========================================
# EDIT
# ==========================================

@brg_bp.route("/edit/<int:brg_id>", methods=["PUT"])
@jwt_required()
def api_edit_brg(brg_id):
    user_id = get_jwt_identity()
    TransactionTracker.mark_open(user_id, "brg_edit")
    response = edit_brg(brg_id=brg_id, data=request.get_json() or {}, user_id=user_id)
    TransactionTracker.mark_closed(user_id)
    return response


# ==========================================
# SUBMIT
# ==========================================

@brg_bp.route("/submit/<int:brg_id>", methods=["POST"])
@jwt_required()
def api_submit_brg(brg_id):
    user_id = get_jwt_identity()
    return submit_brg(brg_id=brg_id, submitted_by=user_id)


# ==========================================
# APPROVE
# ==========================================

@brg_bp.route("/approve/<int:brg_id>", methods=["POST"])
@jwt_required()
def api_approve_brg(brg_id):
    user_id = get_jwt_identity()
    data    = request.json or {}
    return approve_brg(brg_id=brg_id, approved_by=user_id, comments=data.get("comments"))


# ==========================================
# REBACK
# ==========================================

@brg_bp.route("/reback/<int:brg_id>", methods=["POST"])
@jwt_required()
def api_reback_brg(brg_id):
    user_id = get_jwt_identity()
    data    = request.json or {}
    return reback_brg(brg_id=brg_id, reback_by=user_id, comments=data.get("comments"))


# ==========================================
# REJECT
# ==========================================

@brg_bp.route("/reject/<int:brg_id>", methods=["POST"])
@jwt_required()
def api_reject_brg(brg_id):
    user_id = get_jwt_identity()
    data    = request.json or {}
    return reject_brg(brg_id=brg_id, rejected_by=user_id, comments=data.get("comments"))


# ==========================================
# HISTORY
# ==========================================

@brg_bp.route("/history/<int:brg_id>", methods=["GET"])
@jwt_required()
def api_brg_history(brg_id):
    return get_brg_history(brg_id)
