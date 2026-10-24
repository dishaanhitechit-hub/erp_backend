from flask import Blueprint, request
from flask_jwt_extended import jwt_required
from app.middleware.permission_middleware import page_permission
from .service import (
    get_job_openings, create_job_opening, update_job_opening,
    get_candidates, create_candidate, update_candidate_stage,
    get_pipeline_stats, get_offer_letter_data,
    mark_offer_letter, mark_appointment_letter,
    get_interviews, create_interview, update_interview,
)

recruitment_bp = Blueprint("recruitment", __name__)


@recruitment_bp.route("/jobs", methods=["GET"])
@jwt_required()
@page_permission("recruitment", "VIEW")
def api_list_jobs():
    data = {
        "search": request.args.get("search", ""),
        "status": request.args.get("status", ""),
        "department": request.args.get("department", ""),
    }
    return get_job_openings(data)


@recruitment_bp.route("/jobs", methods=["POST"])
@jwt_required()
@page_permission("recruitment", "EDIT")
def api_create_job():
    return create_job_opening(request.get_json() or {})


@recruitment_bp.route("/jobs/<int:job_id>", methods=["PUT"])
@jwt_required()
@page_permission("recruitment", "EDIT")
def api_update_job(job_id):
    return update_job_opening(job_id, request.get_json() or {})


@recruitment_bp.route("/candidates", methods=["GET"])
@jwt_required()
@page_permission("recruitment", "VIEW")
def api_list_candidates():
    data = {
        "jobId": request.args.get("jobId"),
        "stage": request.args.get("stage", ""),
        "search": request.args.get("search", ""),
    }
    return get_candidates(data)


@recruitment_bp.route("/candidates", methods=["POST"])
@jwt_required()
@page_permission("recruitment", "EDIT")
def api_create_candidate():
    return create_candidate(request.get_json() or {})


@recruitment_bp.route("/candidates/<int:candidate_id>", methods=["PUT"])
@jwt_required()
@page_permission("recruitment", "EDIT")
def api_update_candidate(candidate_id):
    return update_candidate_stage(candidate_id, request.get_json() or {})


@recruitment_bp.route("/candidates/<int:candidate_id>/mark-offer-letter", methods=["PUT"])
@jwt_required()
@page_permission("offer_letter", "EDIT")
def api_mark_offer_letter(candidate_id):
    return mark_offer_letter(candidate_id)


@recruitment_bp.route("/candidates/<int:candidate_id>/mark-appointment-letter", methods=["PUT"])
@jwt_required()
@page_permission("appointment_letter", "EDIT")
def api_mark_appointment_letter(candidate_id):
    return mark_appointment_letter(candidate_id)


@recruitment_bp.route("/stats", methods=["GET"])
@jwt_required()
@page_permission("recruitment", "VIEW")
def api_pipeline_stats():
    return get_pipeline_stats()


@recruitment_bp.route("/offer-letter/<int:candidate_id>", methods=["GET"])
@jwt_required()
@page_permission("offer_letter", "VIEW")
def api_offer_letter_data(candidate_id):
    return get_offer_letter_data(candidate_id)


@recruitment_bp.route("/interviews", methods=["GET"])
@jwt_required()
@page_permission("recruitment", "VIEW")
def api_list_interviews():
    data = {
        "candidate_id": request.args.get("candidate_id"),
        "status": request.args.get("status", ""),
    }
    return get_interviews(data)


@recruitment_bp.route("/interviews", methods=["POST"])
@jwt_required()
@page_permission("recruitment", "EDIT")
def api_create_interview():
    return create_interview(request.get_json() or {})


@recruitment_bp.route("/interviews/<int:iv_id>", methods=["PUT"])
@jwt_required()
@page_permission("recruitment", "EDIT")
def api_update_interview(iv_id):
    return update_interview(iv_id, request.get_json() or {})
