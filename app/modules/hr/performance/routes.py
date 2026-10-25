from flask import Blueprint, request
from flask_jwt_extended import jwt_required
from app.middleware.permission_middleware import page_permission
from .service import (
    get_reviews, get_review, create_review, update_review, get_review_stats,
    get_discipline_cases, create_discipline_case, update_discipline_case,
    get_discipline_stats,
)

performance_bp = Blueprint("performance", __name__)


@performance_bp.route("/reviews", methods=["GET"])
@jwt_required()
@page_permission("employee_master", "VIEW")
def api_list_reviews():
    data = {
        "search": request.args.get("search", ""),
        "status": request.args.get("status", ""),
        "department": request.args.get("department", ""),
        "employee_id": request.args.get("employee_id", ""),
    }
    return get_reviews(data)


@performance_bp.route("/reviews/<int:review_id>", methods=["GET"])
@jwt_required()
@page_permission("employee_master", "VIEW")
def api_get_review(review_id):
    return get_review(review_id)


@performance_bp.route("/reviews", methods=["POST"])
@jwt_required()
@page_permission("employee_master", "EDIT")
def api_create_review():
    return create_review(request.get_json() or {})


@performance_bp.route("/reviews/<int:review_id>", methods=["PUT"])
@jwt_required()
@page_permission("employee_master", "EDIT")
def api_update_review(review_id):
    return update_review(review_id, request.get_json() or {})


@performance_bp.route("/reviews/stats", methods=["GET"])
@jwt_required()
@page_permission("employee_master", "VIEW")
def api_review_stats():
    return get_review_stats()


@performance_bp.route("/discipline", methods=["GET"])
@jwt_required()
@page_permission("employee_master", "VIEW")
def api_list_discipline():
    data = {
        "search": request.args.get("search", ""),
        "severity": request.args.get("severity", ""),
        "status": request.args.get("status", ""),
        "employee_id": request.args.get("employee_id", ""),
    }
    return get_discipline_cases(data)


@performance_bp.route("/discipline", methods=["POST"])
@jwt_required()
@page_permission("employee_master", "EDIT")
def api_create_discipline():
    return create_discipline_case(request.get_json() or {})


@performance_bp.route("/discipline/<int:case_id>", methods=["PUT"])
@jwt_required()
@page_permission("employee_master", "EDIT")
def api_update_discipline(case_id):
    return update_discipline_case(case_id, request.get_json() or {})


@performance_bp.route("/discipline/stats", methods=["GET"])
@jwt_required()
@page_permission("employee_master", "VIEW")
def api_discipline_stats():
    return get_discipline_stats()
