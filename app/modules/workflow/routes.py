from flask import Blueprint, g

from app.middleware.auth_middleware import login_required
from app.modules.workflow.service import get_my_pending_approvals

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
