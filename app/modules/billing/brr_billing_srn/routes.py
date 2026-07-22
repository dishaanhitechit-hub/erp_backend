from flask import Blueprint, request
from flask_jwt_extended import jwt_required, get_jwt_identity

from app.utils.txn_tracker import TransactionTracker

from app.modules.billing.brr_billing_srn.service import (
    get_srns_by_brr,
    create_brs,
    get_brs_list,
    get_brs_details,
    edit_brs,
    submit_brs,
    approve_brs,
    reback_brs,
    reject_brs,
    get_brs_history,
)

brs_bp = Blueprint("brs", __name__)


# ==========================================
# GET SRNs BY BRR  (selection grid)
# ==========================================

@brs_bp.route("/srns-by-brr/<int:brr_id>", methods=["GET"])
@jwt_required()
def api_srns_by_brr(brr_id):
    return get_srns_by_brr(brr_id)


# ==========================================
# CREATE BRS
# ==========================================

@brs_bp.route("/create", methods=["POST"])
@jwt_required()
def api_create_brs():
    user_id = get_jwt_identity()
    TransactionTracker.mark_open(user_id, "brs_create")
    response = create_brs(data=request.get_json() or {}, user_id=user_id)
    TransactionTracker.mark_closed(user_id)
    return response


# ==========================================
# LIST
# ==========================================

@brs_bp.route("/list", methods=["GET"])
@jwt_required()
def api_brs_list():
    data = {
        "projectCode":    request.args.get("projectCode"),
        "vendorId":       request.args.get("vendorId"),
        "brrId":          request.args.get("brrId"),
        "orderId":        request.args.get("orderId"),
        "workflowStatus": request.args.get("workflowStatus"),
        "search":         request.args.get("search"),
    }
    return get_brs_list(data)


# ==========================================
# DETAILS
# ==========================================

@brs_bp.route("/details/<int:brs_id>", methods=["GET"])
@jwt_required()
def api_brs_details(brs_id):
    return get_brs_details(brs_id)


# ==========================================
# EDIT
# ==========================================

@brs_bp.route("/edit/<int:brs_id>", methods=["PUT"])
@jwt_required()
def api_edit_brs(brs_id):
    user_id = get_jwt_identity()
    TransactionTracker.mark_open(user_id, "brs_edit")
    response = edit_brs(brs_id=brs_id, data=request.get_json() or {}, user_id=user_id)
    TransactionTracker.mark_closed(user_id)
    return response


# ==========================================
# SUBMIT
# ==========================================

@brs_bp.route("/submit/<int:brs_id>", methods=["POST"])
@jwt_required()
def api_submit_brs(brs_id):
    user_id = get_jwt_identity()
    return submit_brs(brs_id=brs_id, submitted_by=user_id)


# ==========================================
# APPROVE
# ==========================================

@brs_bp.route("/approve/<int:brs_id>", methods=["POST"])
@jwt_required()
def api_approve_brs(brs_id):
    user_id = get_jwt_identity()
    data    = request.json or {}
    return approve_brs(brs_id=brs_id, approved_by=user_id, comments=data.get("comments"))


# ==========================================
# REBACK
# ==========================================

@brs_bp.route("/reback/<int:brs_id>", methods=["POST"])
@jwt_required()
def api_reback_brs(brs_id):
    user_id = get_jwt_identity()
    data    = request.json or {}
    return reback_brs(brs_id=brs_id, reback_by=user_id, comments=data.get("comments"))


# ==========================================
# REJECT
# ==========================================

@brs_bp.route("/reject/<int:brs_id>", methods=["POST"])
@jwt_required()
def api_reject_brs(brs_id):
    user_id = get_jwt_identity()
    data    = request.json or {}
    return reject_brs(brs_id=brs_id, rejected_by=user_id, comments=data.get("comments"))


# ==========================================
# HISTORY
# ==========================================

@brs_bp.route("/history/<int:brs_id>", methods=["GET"])
@jwt_required()
def api_brs_history(brs_id):
    return get_brs_history(brs_id)
