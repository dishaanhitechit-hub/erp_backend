from flask import Blueprint, request, send_from_directory
from flask_jwt_extended import jwt_required, get_jwt_identity

# MAINTENANCE: tracks which user is in the middle of a write operation
from app.utils.txn_tracker import TransactionTracker

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
    edit_order,
    get_order_by_uuid,
)

# [PDF] — ReportLab direct-PDF service (pixel-perfect, no DOCX/LibreOffice needed)
from app.modules.resources.order.order_pdf_rl_service import (
    generate_order_pdf,
    verify_order_pdf,
    serve_pdf_file,
    serve_pdf_for_token,
)
# [END PDF]

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

    # MAINTENANCE: mark this user as having an open (incomplete) operation
    # so the 11:30 PM sweep knows they were in the middle of creating an order
    TransactionTracker.mark_open(user_id, "order_create")

    data = dict(
        request.form
    )

    response = create_order(
        data=data,
        user_id=user_id,
        files=request.files
    )

    # MAINTENANCE: work is done — remove from open transaction list
    TransactionTracker.mark_closed(user_id)

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
    asset_only = (
            request.args.get(
                "assetOnly",
                "false"
            ).lower() == "true"
    )

    return get_indent_pending_qty_list(
        project_code,
        sub_code,
        asset_only
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

    # MAINTENANCE: mark open — user is editing an existing order
    TransactionTracker.mark_open(user_id, "order_edit")

    data = dict(
        request.form
    )

    response = edit_order(

        order_id=order_id,

        data=data,

        user_id=user_id,

        files=request.files
    )

    # MAINTENANCE: edit complete — mark closed
    TransactionTracker.mark_closed(user_id)

    return response

# ==========================================
# [PDF] — Generate Order PDF
# Remove @jwt_required() if you want this publicly accessible
# ==========================================
@order_bp.route("/generate-pdf/<int:order_id>", methods=["GET"])
@jwt_required()
def api_generate_pdf(order_id):
    from flask import current_app
    # Use PUBLIC_BASE_URL from config so QR links point to the reachable server.
    # Falls back to request.host_url for local development.
    base_url = (current_app.config.get("PUBLIC_BASE_URL") or request.host_url).rstrip("/") + "/"
    force    = request.args.get("force", "0") == "1"
    return generate_order_pdf(order_id, base_url, force=force)


# ==========================================
# [PDF] — Verify QR (public — no JWT, scanned by anyone)
# Returns HTML page with verification status + embedded PDF viewer
# ==========================================
@order_bp.route("/verify/<token>", methods=["GET"])
def api_verify_pdf(token):
    return verify_order_pdf(token)


# ==========================================
# [PDF] — Serve raw PDF via token (used by iframe inside verify page)
# Public — no JWT, token itself is the auth. Real file path never exposed.
# ==========================================
@order_bp.route("/verify-pdf/<token>", methods=["GET"])
def api_verify_pdf_raw(token):
    return serve_pdf_for_token(token)


# ==========================================
# [PDF] [STORAGE] — Serve local PDF file
# Remove this route entirely when switching to BunnyCDN
# ==========================================
@order_bp.route("/pdf-file/<path:relative_path>", methods=["GET"])
def api_serve_pdf(relative_path):
    return serve_pdf_file(relative_path)


# ==========================================
# GET FULL ORDER DETAILS BY UUID
# GET /api/order/uuid/<order_uuid>
# ==========================================

@order_bp.route("/uuid/<string:order_uuid>", methods=["GET"])
def api_order_by_uuid(order_uuid):
    return get_order_by_uuid(order_uuid)
