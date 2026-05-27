from flask import Blueprint, request
from flask_jwt_extended import jwt_required, get_jwt_identity

from app.modules.resources.order.service import (
    create_order,
    get_indent_pending_qty_list,
    get_order_details,
    get_order_list,
    submit_order,
    approve_order,
    reback_order,
    reject_order,
    delete_order,
    get_order_history,
    edit_order
)

order_bp = Blueprint( "order",__name__)



# ==========================================
# CREATE ORDER
# ==========================================

@order_bp.route(
    "/create",
    methods=["POST"]
)
@jwt_required()
def api_create_order():

    user_id = get_jwt_identity()

    data = dict(
        request.form
    )

    response = create_order(
        data=data,
        user_id=user_id,
        files=request.files
    )

    return response


# ==========================================
# GET PENDING INDENT ITEMS
# ==========================================

@order_bp.route(
    "/indent-pending",
    methods=["GET"]
)
@jwt_required()
def api_indent_pending():

    project_code=request.args.get(
        "projectCode"
    )

    sub_code=request.args.get(
        "subCategoryCode"
    )

    return get_indent_pending_qty_list(
        project_code,
        sub_code
    )


# ==========================================
# GET ORDER DETAILS
# ==========================================

@order_bp.route(
    "/details/<int:order_id>",
    methods=["GET"]
)
@jwt_required()
def api_order_details(
        order_id
):

    return get_order_details(
        order_id
    )


# ==========================================
# LIST
# ==========================================

@order_bp.route(
    "/list",
    methods=["GET"]
)
@jwt_required()
def api_order_list():

    data={

        "projectCode":
        request.args.get(
            "projectCode"
        ),

        "subCategoryCode":
        request.args.get(
            "subCategoryCode"
        ),

        "categoryCode":
        request.args.get(
            "categoryCode"
        ),

        "workflowStatus":
        request.args.get(
            "workflowStatus"
        ),

        "search":
        request.args.get(
            "search"
        )
    }

    return get_order_list(
        data
    )


# ==========================================
# SUBMIT
# ==========================================

@order_bp.route(
    "/submit/<int:order_id>",
    methods=["POST"]
)
@jwt_required()
def api_submit_order(
        order_id
):

    user_id=get_jwt_identity()

    return submit_order(
        order_id,
        user_id
    )


# ==========================================
# APPROVE
# ==========================================

@order_bp.route(
    "/approve/<int:order_id>",
    methods=["POST"]
)
@jwt_required()
def api_approve_order(
        order_id
):

    user_id = get_jwt_identity()

    data = request.json or {}

    return approve_order(

        order_id=order_id,

        approved_by=user_id,

        comments=data.get("comments")
    )


# ==========================================
# REBACK
# ==========================================

@order_bp.route(
    "/reback/<int:order_id>",
    methods=["POST"]
)
@jwt_required()
def api_reback_order(
        order_id
):

    user_id=get_jwt_identity()

    data=request.json

    return reback_order(

        order_id=order_id,

        reback_by=user_id,

        comments=data.get(
            "comments"
        )
    )


# ==========================================
# REJECT
# ==========================================

@order_bp.route(
    "/reject/<int:order_id>",
    methods=["POST"]
)
@jwt_required()
def api_reject_order(
        order_id
):

    user_id=get_jwt_identity()

    data=request.json

    return reject_order(

        order_id=order_id,

        rejected_by=user_id,

        comments=data.get(
            "comments"
        )
    )


# ==========================================
# DELETE
# ==========================================

@order_bp.route(
    "/delete/<int:order_id>",
    methods=["DELETE"]
)
@jwt_required()
def api_delete_order(
        order_id
):

    return delete_order(
        order_id
    )


# ==========================================
# HISTORY
# ==========================================

@order_bp.route(
    "/history/<int:order_id>",
    methods=["GET"]
)
@jwt_required()
def api_order_history(
        order_id
):

    return get_order_history(
        order_id
    )


@order_bp.route(
    "/edit/<int:order_id>",
    methods=["PUT"]
)
@jwt_required()
def api_edit_order(
        order_id
):

    user_id = get_jwt_identity()

    data = dict(
        request.form
    )

    return edit_order(

        order_id=order_id,

        data=data,

        user_id=user_id,

        files=request.files
    )