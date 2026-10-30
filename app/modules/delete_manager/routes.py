"""
Routes for the delete manager module.

Endpoints:
  POST   /delete-manager/request/<module_code>/<int:record_id>
         → Raise a delete request for any record

  GET    /delete-manager/requests
         → List delete requests (filterable by module, project, status)

  GET    /delete-manager/requests/<int:dr_id>
         → Get status of one delete request

  DELETE /delete-manager/requests/<int:dr_id>
         → Cancel a pending delete request
"""

from flask import Blueprint, request, g

from app.middleware.auth_middleware import login_required
from app.response import res
from .service import (
    raise_delete_request,
    get_delete_request,
    list_delete_requests,
    cancel_delete_request,
)

delete_manager_bp = Blueprint("delete_manager", __name__)


@delete_manager_bp.route(
    "/delete-manager/request/<string:module_code>/<int:record_id>",
    methods=["POST"],
)
@login_required
def request_delete(module_code: str, record_id: int):
    """
    Raise a delete request for a record in any module.
    Body (optional): { "reason": "..." }
    """
    body   = request.get_json(silent=True) or {}
    reason = body.get("reason", "")

    result, status_code = raise_delete_request(
        module_code  = module_code.upper(),
        record_id    = record_id,
        requested_by = g.current_user["id"],
        reason       = reason,
    )
    return res(result.get("message", ""), result, status_code)


@delete_manager_bp.route("/delete-manager/requests", methods=["GET"])
@login_required
def list_requests():
    """
    List delete requests.
    Query params: module_code, project_code, status, page, per_page
    """
    module_code  = request.args.get("module_code")
    project_code = request.args.get("project_code")
    status       = request.args.get("status")
    page         = int(request.args.get("page", 1))
    per_page     = int(request.args.get("per_page", 20))

    data = list_delete_requests(
        module_code  = module_code.upper() if module_code else None,
        project_code = project_code,
        status       = status,
        page         = page,
        per_page     = per_page,
    )
    return res("Delete requests fetched.", data, 200)


@delete_manager_bp.route("/delete-manager/requests/<int:dr_id>", methods=["GET"])
@login_required
def get_request(dr_id: int):
    """Get status of a single delete request."""
    data = get_delete_request(dr_id)
    if not data:
        return res("Delete request not found.", {}, 404)
    return res("Delete request fetched.", data, 200)


@delete_manager_bp.route("/delete-manager/requests/<int:dr_id>", methods=["DELETE"])
@login_required
def cancel_request(dr_id: int):
    """Cancel a pending delete request."""
    result, status_code = cancel_delete_request(
        delete_request_id = dr_id,
        cancelled_by      = g.current_user["id"],
    )
    return res(result.get("message", ""), result, status_code)
