from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity, get_jwt

from app.modules.resources.machinery_mgmt.service import (
    # log book
    get_pw_orders_for_log_book,
    create_log_book,
    get_log_book_list,
    get_log_book_details,
    edit_log_book,
    submit_log_book,
    approve_log_book,
    reback_log_book,
    reject_log_book,
    get_log_book_history,
    # log entry
    create_log_entry,
    get_log_entry_list,
    get_log_entry_details,
    edit_log_entry,
    submit_log_entry,
    approve_log_entry,
    reback_log_entry,
    reject_log_entry,
    get_log_entry_history,
)

machinery_bp = Blueprint("machinery_mgmt", __name__)

_PAGE = "log_sheet"


def _can_view():
    perms = {k.lower(): v for k, v in get_jwt().get("permissions", {}).items()}
    return perms.get(f"{_PAGE}.view") or perms.get(f"{_PAGE}.edit")


def _no_access():
    return jsonify({"message": "Access denied", "data": [], "status": 403}), 403


# ══════════════════════════════════════════════════════════════════
# LOG BOOK
# ══════════════════════════════════════════════════════════════════

@machinery_bp.route("/log-book/pw-orders", methods=["GET"])
@jwt_required()
def api_pw_orders_for_log_book():
    if not _can_view():
        return _no_access()
    data = {"projectCode": request.args.get("projectCode")}
    return get_pw_orders_for_log_book(data)


@machinery_bp.route("/log-book/create", methods=["POST"])
@jwt_required()
def api_create_log_book():
    user_id = get_jwt_identity()
    return create_log_book(data=request.get_json() or {}, user_id=user_id)


@machinery_bp.route("/log-book/list", methods=["GET"])
@jwt_required()
def api_log_book_list():
    if not _can_view():
        return _no_access()
    data = {
        "projectCode":    request.args.get("projectCode"),
        "workflowStatus": request.args.get("workflowStatus"),
        "search":         request.args.get("search"),
    }
    return get_log_book_list(data)


@machinery_bp.route("/log-book/details/<int:log_book_id>", methods=["GET"])
@jwt_required()
def api_log_book_details(log_book_id):
    if not _can_view():
        return _no_access()
    return get_log_book_details(log_book_id)


@machinery_bp.route("/log-book/edit/<int:log_book_id>", methods=["PUT"])
@jwt_required()
def api_edit_log_book(log_book_id):
    user_id = get_jwt_identity()
    return edit_log_book(log_book_id=log_book_id, data=request.get_json() or {}, user_id=user_id)


@machinery_bp.route("/log-book/submit/<int:log_book_id>", methods=["POST"])
@jwt_required()
def api_submit_log_book(log_book_id):
    user_id = get_jwt_identity()
    return submit_log_book(log_book_id=log_book_id, submitted_by=user_id)


@machinery_bp.route("/log-book/approve/<int:log_book_id>", methods=["POST"])
@jwt_required()
def api_approve_log_book(log_book_id):
    user_id = get_jwt_identity()
    data    = request.json or {}
    return approve_log_book(log_book_id=log_book_id, approved_by=user_id, comments=data.get("comments"))


@machinery_bp.route("/log-book/reback/<int:log_book_id>", methods=["POST"])
@jwt_required()
def api_reback_log_book(log_book_id):
    user_id = get_jwt_identity()
    data    = request.json or {}
    return reback_log_book(log_book_id=log_book_id, reback_by=user_id, comments=data.get("comments"))


@machinery_bp.route("/log-book/reject/<int:log_book_id>", methods=["POST"])
@jwt_required()
def api_reject_log_book(log_book_id):
    user_id = get_jwt_identity()
    data    = request.json or {}
    return reject_log_book(log_book_id=log_book_id, rejected_by=user_id, comments=data.get("comments"))


@machinery_bp.route("/log-book/history/<int:log_book_id>", methods=["GET"])
@jwt_required()
def api_log_book_history(log_book_id):
    if not _can_view():
        return _no_access()
    return get_log_book_history(log_book_id)


# ══════════════════════════════════════════════════════════════════
# LOG BOOK ENTRY
# ══════════════════════════════════════════════════════════════════

@machinery_bp.route("/log-entry/create", methods=["POST"])
@jwt_required()
def api_create_log_entry():
    user_id = get_jwt_identity()
    return create_log_entry(data=request.get_json() or {}, user_id=user_id)


@machinery_bp.route("/log-entry/list", methods=["GET"])
@jwt_required()
def api_log_entry_list():
    if not _can_view():
        return _no_access()
    data = {
        "projectCode":    request.args.get("projectCode"),
        "logBookId":      request.args.get("logBookId"),
        "workflowStatus": request.args.get("workflowStatus"),
        "search":         request.args.get("search"),
    }
    return get_log_entry_list(data)


@machinery_bp.route("/log-entry/details/<int:entry_id>", methods=["GET"])
@jwt_required()
def api_log_entry_details(entry_id):
    if not _can_view():
        return _no_access()
    return get_log_entry_details(entry_id)


@machinery_bp.route("/log-entry/edit/<int:entry_id>", methods=["PUT"])
@jwt_required()
def api_edit_log_entry(entry_id):
    user_id = get_jwt_identity()
    return edit_log_entry(entry_id=entry_id, data=request.get_json() or {}, user_id=user_id)


@machinery_bp.route("/log-entry/submit/<int:entry_id>", methods=["POST"])
@jwt_required()
def api_submit_log_entry(entry_id):
    user_id = get_jwt_identity()
    return submit_log_entry(entry_id=entry_id, submitted_by=user_id)


@machinery_bp.route("/log-entry/approve/<int:entry_id>", methods=["POST"])
@jwt_required()
def api_approve_log_entry(entry_id):
    user_id = get_jwt_identity()
    data    = request.json or {}
    return approve_log_entry(entry_id=entry_id, approved_by=user_id, comments=data.get("comments"))


@machinery_bp.route("/log-entry/reback/<int:entry_id>", methods=["POST"])
@jwt_required()
def api_reback_log_entry(entry_id):
    user_id = get_jwt_identity()
    data    = request.json or {}
    return reback_log_entry(entry_id=entry_id, reback_by=user_id, comments=data.get("comments"))


@machinery_bp.route("/log-entry/reject/<int:entry_id>", methods=["POST"])
@jwt_required()
def api_reject_log_entry(entry_id):
    user_id = get_jwt_identity()
    data    = request.json or {}
    return reject_log_entry(entry_id=entry_id, rejected_by=user_id, comments=data.get("comments"))


@machinery_bp.route("/log-entry/history/<int:entry_id>", methods=["GET"])
@jwt_required()
def api_log_entry_history(entry_id):
    if not _can_view():
        return _no_access()
    return get_log_entry_history(entry_id)
