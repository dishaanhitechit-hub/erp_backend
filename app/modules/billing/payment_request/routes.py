from flask import Blueprint, request, g
from flask_jwt_extended import jwt_required, get_jwt_identity
from app.middleware.auth_middleware import login_required

from app.utils.txn_tracker import TransactionTracker

from app.modules.billing.payment_request.service import (
    get_eligible_brrs,
    get_brr_payment_summary,
    create_payment_request,
    get_payment_request_list,
    get_payment_request_details,
    get_payment_request_by_uuid,
    edit_payment_request,
    submit_payment_request,
    approve_payment_request,
    reback_payment_request,
    reject_payment_request,
    get_payment_request_history,
    get_payment_request_my_approval_status,
    delete_payment_request,
)

payment_request_bp = Blueprint("payment_request", __name__)


# ── BRR picker: approved BRRs with balance > 0 ─────────────────────
@payment_request_bp.route("/eligible-brrs", methods=["GET"])
@jwt_required()
def api_pr_eligible_brrs():
    return get_eligible_brrs({
        "projectCode": request.args.get("projectCode"),
        "vendorId":    request.args.get("vendorId"),
    })


# ── Bill / requested / balance for one BRR ─────────────────────────
@payment_request_bp.route("/brr-summary/<int:brr_id>", methods=["GET"])
@jwt_required()
def api_pr_brr_summary(brr_id):
    return get_brr_payment_summary(brr_id, request.args.get("excludeId", type=int))


@payment_request_bp.route("/create", methods=["POST"])
@jwt_required()
def api_create_pr():
    user_id = get_jwt_identity()
    TransactionTracker.mark_open(user_id, "payment_request_create")
    response = create_payment_request(data=dict(request.form), user_id=user_id, files=request.files)
    TransactionTracker.mark_closed(user_id)
    return response


@payment_request_bp.route("/list", methods=["GET"])
@jwt_required()
def api_pr_list():
    return get_payment_request_list({
        "projectCode":    request.args.get("projectCode"),
        "brrId":          request.args.get("brrId"),
        "vendorId":       request.args.get("vendorId"),
        "workflowStatus": request.args.get("workflowStatus"),
        "search":         request.args.get("search"),
    })


@payment_request_bp.route("/details/<int:pr_id>", methods=["GET"])
@jwt_required()
def api_pr_details(pr_id):
    return get_payment_request_details(pr_id)


@payment_request_bp.route("/edit/<int:pr_id>", methods=["PUT"])
@jwt_required()
def api_edit_pr(pr_id):
    user_id = get_jwt_identity()
    TransactionTracker.mark_open(user_id, "payment_request_edit")
    response = edit_payment_request(pr_id=pr_id, data=dict(request.form), user_id=user_id, files=request.files)
    TransactionTracker.mark_closed(user_id)
    return response


@payment_request_bp.route("/submit/<int:pr_id>", methods=["POST"])
@jwt_required()
def api_submit_pr(pr_id):
    return submit_payment_request(pr_id=pr_id, submitted_by=get_jwt_identity())


@payment_request_bp.route("/approve/<int:pr_id>", methods=["POST"])
@jwt_required()
def api_approve_pr(pr_id):
    data = request.json or {}
    return approve_payment_request(pr_id=pr_id, approved_by=get_jwt_identity(), comments=data.get("comments"))


@payment_request_bp.route("/reback/<int:pr_id>", methods=["POST"])
@jwt_required()
def api_reback_pr(pr_id):
    data = request.json or {}
    return reback_payment_request(pr_id=pr_id, reback_by=get_jwt_identity(), comments=data.get("comments"))


@payment_request_bp.route("/reject/<int:pr_id>", methods=["POST"])
@jwt_required()
def api_reject_pr(pr_id):
    data = request.json or {}
    return reject_payment_request(pr_id=pr_id, rejected_by=get_jwt_identity(), comments=data.get("comments"))


@payment_request_bp.route("/history/<int:pr_id>", methods=["GET"])
@jwt_required()
def api_pr_history(pr_id):
    return get_payment_request_history(pr_id)


@payment_request_bp.route("/my-approval-status/<int:pr_id>", methods=["GET"])
@login_required
def api_pr_my_approval_status(pr_id):
    return get_payment_request_my_approval_status(pr_id, g.current_user["id"])


# ── no auth (print page) ───────────────────────────────────────────
@payment_request_bp.route("/uuid/<string:pr_uuid>", methods=["GET"])
def api_pr_by_uuid(pr_uuid):
    return get_payment_request_by_uuid(pr_uuid)


@payment_request_bp.route("/<int:pr_id>", methods=["DELETE"])
@jwt_required()
def api_delete_pr(pr_id):
    return delete_payment_request(pr_id)
