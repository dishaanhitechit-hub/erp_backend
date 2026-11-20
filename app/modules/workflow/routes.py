from flask import Blueprint, g, request

from app.middleware.auth_middleware import login_required
from app.modules.workflow.service import get_my_pending_approvals
from app.modules.workflow.bulk import find_eligible, list_bulk_modules, run_bulk_action

workflow_bp = Blueprint("workflow", __name__)


# ==========================================
# MY PENDING APPROVALS
# GET /workflow/my-approvals/<module_code>
# ==========================================

@workflow_bp.route(
    "/my-approvals/<string:module_code>",
    methods=["GET"]
)
@login_required
def api_my_approvals(module_code):

    user = g.current_user

    return get_my_pending_approvals(
        module_code=module_code,
        project_code=user["projectId"],
        user_id=user["id"]
    )


# ==========================================
# BULK APPROVE / REBACK / REJECT
# POST /workflow/bulk-action          {module, action, ids, remarks}
# POST /workflow/bulk-action/eligible {module, ids}  -> ids pending at my level
# GET  /workflow/bulk-action/modules
# ==========================================

@workflow_bp.route("/bulk-action", methods=["POST"])
@login_required
def api_bulk_action():
    return run_bulk_action(request.get_json(silent=True))


@workflow_bp.route("/bulk-action/eligible", methods=["POST"])
@login_required
def api_bulk_action_eligible():
    return find_eligible(request.get_json(silent=True))


@workflow_bp.route("/bulk-action/modules", methods=["GET"])
@login_required
def api_bulk_action_modules():
    return list_bulk_modules()
