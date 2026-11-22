from flask import Blueprint, request
from flask_jwt_extended import jwt_required, get_jwt_identity

from app.modules.project_mgmt.custom_billing.og_sale_order.service import (
    create_og_sale_order,
    get_og_sale_order_list,
    get_og_sale_order_details,
    edit_og_sale_order,
    submit_og_sale_order,
    approve_og_sale_order,
    reback_og_sale_order,
    reject_og_sale_order,
    get_og_sale_order_history,
    get_og_sale_order_my_approval_status,
    get_og_sale_order_by_uuid,
)

og_sale_order_bp = Blueprint("og_sale_order", __name__)


# ── List & Create ───────────────────────────────────────────────
@og_sale_order_bp.route("/list", methods=["GET"])
@jwt_required()
def list_og_sale_orders():
    return get_og_sale_order_list(request.args)


@og_sale_order_bp.route("/create", methods=["POST"])
@jwt_required()
def create():
    user_id = get_jwt_identity()
    return create_og_sale_order(request, user_id)


# ── Bulk upload (Excel: Orders + Items sheets) ──────────────────
@og_sale_order_bp.route("/bulk/reference", methods=["GET"])
@jwt_required()
def bulk_reference():
    from .bulk_import import get_bulk_sale_order_reference
    return get_bulk_sale_order_reference(request.args.to_dict(), get_jwt_identity())


@og_sale_order_bp.route("/bulk/validate", methods=["POST"])
@jwt_required()
def bulk_validate():
    from .bulk_import import validate_bulk_sale_order
    return validate_bulk_sale_order(request.get_json(silent=True) or {}, get_jwt_identity())


@og_sale_order_bp.route("/bulk/import", methods=["POST"])
@jwt_required()
def bulk_import():
    from .bulk_import import import_bulk_sale_order
    return import_bulk_sale_order(request.get_json(silent=True) or {}, get_jwt_identity())


# ── Amendments (extra items on an Approved order) ───────────────
@og_sale_order_bp.route("/<int:so_id>/amendments", methods=["GET"])
@jwt_required()
def amendments_of_order(so_id):
    from .amendment import list_amendments
    return list_amendments(so_id, get_jwt_identity())


@og_sale_order_bp.route("/<int:so_id>/amendment/create", methods=["POST"])
@jwt_required()
def amendment_create(so_id):
    from .amendment import create_amendment
    return create_amendment(so_id, request.form, request.files, get_jwt_identity())


@og_sale_order_bp.route("/amendment/<int:amd_id>", methods=["GET"])
@jwt_required()
def amendment_detail(amd_id):
    from .amendment import get_amendment
    return get_amendment(amd_id)


@og_sale_order_bp.route("/amendment/edit/<int:amd_id>", methods=["PUT"])
@jwt_required()
def amendment_edit(amd_id):
    from .amendment import edit_amendment
    return edit_amendment(amd_id, request.form, request.files, get_jwt_identity())


@og_sale_order_bp.route("/amendment/<int:amd_id>", methods=["DELETE"])
@jwt_required()
def amendment_delete(amd_id):
    from .amendment import delete_amendment
    return delete_amendment(amd_id, get_jwt_identity())


@og_sale_order_bp.route("/amendment/submit/<int:amd_id>", methods=["POST"])
@jwt_required()
def amendment_submit(amd_id):
    from .amendment import submit_amendment
    return submit_amendment(amd_id, get_jwt_identity())


@og_sale_order_bp.route("/amendment/approve/<int:amd_id>", methods=["POST"])
@jwt_required()
def amendment_approve(amd_id):
    from .amendment import approve_amendment
    comments = request.json.get("comments") if request.is_json else None
    return approve_amendment(amd_id, get_jwt_identity(), comments)


@og_sale_order_bp.route("/amendment/reback/<int:amd_id>", methods=["POST"])
@jwt_required()
def amendment_reback(amd_id):
    from .amendment import reback_amendment
    comments = request.json.get("comments") if request.is_json else None
    return reback_amendment(amd_id, get_jwt_identity(), comments)


@og_sale_order_bp.route("/amendment/reject/<int:amd_id>", methods=["POST"])
@jwt_required()
def amendment_reject(amd_id):
    from .amendment import reject_amendment
    comments = request.json.get("comments") if request.is_json else None
    return reject_amendment(amd_id, get_jwt_identity(), comments)


@og_sale_order_bp.route("/amendment/history/<int:amd_id>", methods=["GET"])
@jwt_required()
def amendment_history_route(amd_id):
    from .amendment import amendment_history
    return amendment_history(amd_id)


@og_sale_order_bp.route("/amendment/my-approval-status/<int:amd_id>", methods=["GET"])
@jwt_required()
def amendment_my_status(amd_id):
    from .amendment import amendment_my_approval_status
    return amendment_my_approval_status(amd_id, get_jwt_identity())


# ── Single record ───────────────────────────────────────────────
@og_sale_order_bp.route("/<int:so_id>", methods=["GET"])
@jwt_required()
def details(so_id):
    return get_og_sale_order_details(so_id)


@og_sale_order_bp.route("/edit/<int:so_id>", methods=["PUT"])
@jwt_required()
def edit(so_id):
    user_id = get_jwt_identity()
    return edit_og_sale_order(so_id, request, user_id)


# ── Workflow ────────────────────────────────────────────────────
@og_sale_order_bp.route("/submit/<int:so_id>", methods=["POST"])
@jwt_required()
def submit(so_id):
    user_id = get_jwt_identity()
    return submit_og_sale_order(so_id, user_id)


@og_sale_order_bp.route("/approve/<int:so_id>", methods=["POST"])
@jwt_required()
def approve(so_id):
    user_id  = get_jwt_identity()
    comments = request.json.get("comments") if request.is_json else None
    return approve_og_sale_order(so_id, user_id, comments)


@og_sale_order_bp.route("/reback/<int:so_id>", methods=["POST"])
@jwt_required()
def reback(so_id):
    user_id  = get_jwt_identity()
    comments = request.json.get("comments") if request.is_json else None
    return reback_og_sale_order(so_id, user_id, comments)


@og_sale_order_bp.route("/reject/<int:so_id>", methods=["POST"])
@jwt_required()
def reject(so_id):
    user_id  = get_jwt_identity()
    comments = request.json.get("comments") if request.is_json else None
    return reject_og_sale_order(so_id, user_id, comments)


# ── History & approval status ───────────────────────────────────
@og_sale_order_bp.route("/history/<int:so_id>", methods=["GET"])
@jwt_required()
def history(so_id):
    return get_og_sale_order_history(so_id)


@og_sale_order_bp.route("/my-approval-status/<int:so_id>", methods=["GET"])
@jwt_required()
def my_approval_status(so_id):
    user_id = get_jwt_identity()
    return get_og_sale_order_my_approval_status(so_id, user_id)


# ── Public UUID endpoint (no JWT) ───────────────────────────────
@og_sale_order_bp.route("/uuid/<so_uuid>", methods=["GET"])
def get_by_uuid(so_uuid):
    return get_og_sale_order_by_uuid(so_uuid)


@og_sale_order_bp.route("/<int:order_id>", methods=["DELETE"])
@jwt_required()
def api_delete_og_sale_order(order_id):
    from .service import delete_og_sale_order
    return delete_og_sale_order(order_id)
