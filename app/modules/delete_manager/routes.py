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
    check_delete_status,
    list_notifications,
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


# ── NEW ROUTES (frontend helpers — existing routes above are unchanged) ──────


@delete_manager_bp.route(
    "/delete-manager/check/<string:module_code>/<int:record_id>",
    methods=["GET"],
)
@login_required
def check_delete(module_code: str, record_id: int):
    """
    Frontend button helper.
    Returns whether the record can be deleted now or is blocked.

    Response:
      {
        "can_delete_now": bool,
        "blocked_by": [...],
        "pending_request": {...} | null,
        "record_no": "..."
      }

    Usage: call this before rendering the delete button.
    If can_delete_now == true  → show plain "Delete" button → call DELETE on the module's own route.
    If can_delete_now == false → show "Request Delete" button → POST /delete-manager/request/<module>/<id>.
    If pending_request != null  → delete request already raised; show its status instead.
    """
    result, status_code = check_delete_status(
        module_code = module_code.upper(),
        record_id   = record_id,
    )
    return res(result.get("message", "Delete status fetched."), result, status_code)


@delete_manager_bp.route("/delete-manager/notifications", methods=["GET"])
@login_required
def notifications_list():
    """
    Notification centre — lists WhatsApp delete-request notifications sent.

    Query params:
      module_code    — filter by module
      project_code   — filter by project
      status         — PENDING | COMPLETED | CANCELLED
      wa_sent_only   — 1 (default) or 0 to include records with no WA sent
      page, per_page
    """
    module_code  = request.args.get("module_code")
    project_code = request.args.get("project_code")
    status       = request.args.get("status")
    wa_sent_only = request.args.get("wa_sent_only", "1") != "0"
    page         = int(request.args.get("page", 1))
    per_page     = int(request.args.get("per_page", 20))

    data = list_notifications(
        module_code  = module_code.upper() if module_code else None,
        project_code = project_code,
        status       = status,
        wa_sent_only = wa_sent_only,
        page         = page,
        per_page     = per_page,
    )
    return res("Notifications fetched.", data, 200)


@delete_manager_bp.route("/delete-manager/my-requests", methods=["GET"])
@login_required
def my_requests():
    """
    Returns delete requests raised by the currently logged-in user.

    Query params: status, module_code, page, per_page
    """
    user_id      = g.current_user["id"]
    status       = request.args.get("status")
    module_code  = request.args.get("module_code")
    page         = int(request.args.get("page", 1))
    per_page     = int(request.args.get("per_page", 20))

    data = list_delete_requests(
        module_code  = module_code.upper() if module_code else None,
        status       = status,
        requested_by = user_id,
        page         = page,
        per_page     = per_page,
    )
    return res("Your delete requests fetched.", data, 200)
