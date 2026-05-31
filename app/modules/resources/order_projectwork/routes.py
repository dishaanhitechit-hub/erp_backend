# app/modules/resources/order_projectwork/routes.py
#
# Project-Work Order Routes
# Blueprint prefix recommended: /api/pw-order
# ──────────────────────────────────────────────────────────────────

from flask import Blueprint, request
from flask_jwt_extended import jwt_required, get_jwt_identity

from app.modules.resources.order_projectwork.service import (
    get_item_list_by_subcategories,
    create_pw_order,
    edit_pw_order,
    get_pw_order_details,
    get_pw_order_list,
    submit_pw_order,
    approve_pw_order,
    reback_pw_order,
    reject_pw_order,
    delete_pw_order,
    get_pw_order_history,
)

pw_order_bp = Blueprint("pw_order", __name__)


# ══════════════════════════════════════════════════════════════════
# ITEM LIST  (multi-subcategory)
# ══════════════════════════════════════════════════════════════════

@pw_order_bp.route("/item-list", methods=["GET"])
@jwt_required()
def api_pw_item_list():
    """
    GET /api/pw-order/item-list
        ?projectCode=PRJ001
        &subCodes=SVC,COMP          ← comma-separated; one or many
    """
    project_code = request.args.get("projectCode")
    sub_codes    = request.args.get("subCodes", "")   # "SVC,COMP"

    return get_item_list_by_subcategories(project_code, sub_codes)


# ══════════════════════════════════════════════════════════════════
# CREATE ORDER
# ══════════════════════════════════════════════════════════════════

@pw_order_bp.route("/create", methods=["POST"])
@jwt_required()
def api_create_pw_order():
    """
    POST /api/pw-order/create
    Content-Type: multipart/form-data
    Body fields:
        projectCode, subCategoryCode, categoryCode,
        vendorId, orderDate, validityDate,
        quotationNo, quotationDate,
        billingAddress, shippingAddress, orderMessage,
        items   (JSON string)   – list of item rows
        terms   (JSON string)   – list of term rows
    Files:
        orderFile   – supporting document
    """
    user_id = get_jwt_identity()
    data    = dict(request.form)

    return create_pw_order(
        data    = data,
        user_id = user_id,
        files   = request.files,
    )


# ══════════════════════════════════════════════════════════════════
# EDIT ORDER
# ══════════════════════════════════════════════════════════════════

@pw_order_bp.route("/edit/<int:order_id>", methods=["PUT"])
@jwt_required()
def api_edit_pw_order(order_id):
    """
    PUT /api/pw-order/edit/<order_id>
    Same body structure as create.  Only Draft / Reback orders allowed.
    """
    user_id = get_jwt_identity()
    data    = dict(request.form)

    return edit_pw_order(
        order_id = order_id,
        data     = data,
        user_id  = user_id,
        files    = request.files,
    )


# ══════════════════════════════════════════════════════════════════
# ORDER DETAILS
# ══════════════════════════════════════════════════════════════════

@pw_order_bp.route("/details/<int:order_id>", methods=["GET"])
@jwt_required()
def api_pw_order_details(order_id):
    """GET /api/pw-order/details/<order_id>"""
    return get_pw_order_details(order_id)


# ══════════════════════════════════════════════════════════════════
# ORDER LIST
# ══════════════════════════════════════════════════════════════════

@pw_order_bp.route("/list", methods=["GET"])
@jwt_required()
def api_pw_order_list():
    """
    GET /api/pw-order/list
        ?projectCode=PRJ001
        &subCategoryCode=SVC        (optional)
        &categoryCode=CAT01         (optional)
        &workflowStatus=Approved    (optional)
        &search=55                  (optional – matches order_no)
    """
    data = {
        "projectCode":    request.args.get("projectCode"),
        "subCategoryCode":request.args.get("subCategoryCode"),
        "categoryCode":   request.args.get("categoryCode"),
        "workflowStatus": request.args.get("workflowStatus"),
        "search":         request.args.get("search"),
    }
    return get_pw_order_list(data)


# ══════════════════════════════════════════════════════════════════
# SUBMIT
# ══════════════════════════════════════════════════════════════════

@pw_order_bp.route("/submit/<int:order_id>", methods=["POST"])
@jwt_required()
def api_submit_pw_order(order_id):
    """POST /api/pw-order/submit/<order_id>"""
    user_id = get_jwt_identity()
    return submit_pw_order(order_id, user_id)


# ══════════════════════════════════════════════════════════════════
# APPROVE
# ══════════════════════════════════════════════════════════════════

@pw_order_bp.route("/approve/<int:order_id>", methods=["POST"])
@jwt_required()
def api_approve_pw_order(order_id):
    """
    POST /api/pw-order/approve/<order_id>
    Body JSON: { "comments": "..." }
    """
    user_id = get_jwt_identity()
    data    = request.json or {}

    return approve_pw_order(
        order_id    = order_id,
        approved_by = user_id,
        comments    = data.get("comments"),
    )


# ══════════════════════════════════════════════════════════════════
# REBACK
# ══════════════════════════════════════════════════════════════════

@pw_order_bp.route("/reback/<int:order_id>", methods=["POST"])
@jwt_required()
def api_reback_pw_order(order_id):
    """
    POST /api/pw-order/reback/<order_id>
    Body JSON: { "comments": "Reason for reback" }
    """
    user_id = get_jwt_identity()
    data    = request.json or {}

    return reback_pw_order(
        order_id  = order_id,
        reback_by = user_id,
        comments  = data.get("comments"),
    )


# ══════════════════════════════════════════════════════════════════
# REJECT
# ══════════════════════════════════════════════════════════════════

@pw_order_bp.route("/reject/<int:order_id>", methods=["POST"])
@jwt_required()
def api_reject_pw_order(order_id):
    """
    POST /api/pw-order/reject/<order_id>
    Body JSON: { "comments": "Reason for rejection" }
    """
    user_id = get_jwt_identity()
    data    = request.json or {}

    return reject_pw_order(
        order_id    = order_id,
        rejected_by = user_id,
        comments    = data.get("comments"),
    )


# ══════════════════════════════════════════════════════════════════
# DELETE
# ══════════════════════════════════════════════════════════════════

@pw_order_bp.route("/delete/<int:order_id>", methods=["DELETE"])
@jwt_required()
def api_delete_pw_order(order_id):
    """DELETE /api/pw-order/delete/<order_id>"""
    return delete_pw_order(order_id)


# ══════════════════════════════════════════════════════════════════
# HISTORY
# ══════════════════════════════════════════════════════════════════

@pw_order_bp.route("/history/<int:order_id>", methods=["GET"])
@jwt_required()
def api_pw_order_history(order_id):
    """GET /api/pw-order/history/<order_id>"""
    return get_pw_order_history(order_id)
