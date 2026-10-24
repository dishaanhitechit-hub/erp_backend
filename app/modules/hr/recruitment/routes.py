from flask import Blueprint, request
from flask_jwt_extended import jwt_required
from .service import (
    get_job_openings, create_job_opening, update_job_opening,
    get_candidates, create_candidate, update_candidate_stage,
    get_pipeline_stats,
)

recruitment_bp = Blueprint("recruitment", __name__)


@recruitment_bp.route("/jobs", methods=["GET"])
@jwt_required()
def api_list_jobs():
    data = {
        "search": request.args.get("search", ""),
        "status": request.args.get("status", ""),
        "department": request.args.get("department", ""),
    }
    return get_job_openings(data)


@recruitment_bp.route("/jobs", methods=["POST"])
@jwt_required()
def api_create_job():
    return create_job_opening(request.get_json() or {})


@recruitment_bp.route("/jobs/<int:job_id>", methods=["PUT"])
@jwt_required()
def api_update_job(job_id):
    return update_job_opening(job_id, request.get_json() or {})


@recruitment_bp.route("/candidates", methods=["GET"])
@jwt_required()
def api_list_candidates():
    data = {
        "jobId": request.args.get("jobId"),
        "stage": request.args.get("stage", ""),
        "search": request.args.get("search", ""),
    }
    return get_candidates(data)


@recruitment_bp.route("/candidates", methods=["POST"])
@jwt_required()
def api_create_candidate():
    return create_candidate(request.get_json() or {})


@recruitment_bp.route("/candidates/<int:candidate_id>", methods=["PUT"])
@jwt_required()
def api_update_candidate(candidate_id):
    return update_candidate_stage(candidate_id, request.get_json() or {})


@recruitment_bp.route("/stats", methods=["GET"])
@jwt_required()
def api_pipeline_stats():
    return get_pipeline_stats()
