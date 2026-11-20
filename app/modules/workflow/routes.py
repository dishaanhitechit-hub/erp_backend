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


# ==========================================
# REBACK REQUESTS — send back a fully approved record
# (raised by someone on the record; final approver or admin accepts)
# GET  /workflow/reback-requests                ?status=&module=&projectCode=&page=&limit=
# GET  /workflow/reback-requests/record         ?path=<my-approval-status url>&id=   (or ?module=&id=)
# GET  /workflow/reback-requests/pending-count
# GET  /workflow/reback-requests/modules
# POST /workflow/reback-requests                {module, id, reason}
# POST /workflow/reback-requests/<id>/accept    {comment?}
# POST /workflow/reback-requests/<id>/decline   {comment}
# POST /workflow/reback-requests/<id>/cancel
# ==========================================

@workflow_bp.route("/reback-requests", methods=["GET"])
@login_required
def api_reback_requests():
    from app.modules.workflow.reback_request import list_requests
    return list_requests(request.args)


@workflow_bp.route("/reback-requests", methods=["POST"])
@login_required
def api_reback_request_raise():
    from app.modules.workflow.reback_request import raise_request
    return raise_request(request.get_json(silent=True))


@workflow_bp.route("/reback-requests/record", methods=["GET"])
@login_required
def api_reback_request_record():
    from app.modules.workflow.reback_request import record_status
    a = request.args
    return record_status(a.get("module"), a.get("id"), a.get("path"))


@workflow_bp.route("/reback-requests/pending-count", methods=["GET"])
@login_required
def api_reback_request_count():
    from app.modules.workflow.reback_request import pending_count
    return pending_count()


@workflow_bp.route("/reback-requests/modules", methods=["GET"])
@login_required
def api_reback_request_modules():
    from app.modules.workflow.reback_request import list_modules
    return list_modules()


@workflow_bp.route("/reback-requests/<int:req_id>/accept", methods=["POST"])
@login_required
def api_reback_request_accept(req_id):
    from app.modules.workflow.reback_request import accept_request
    return accept_request(req_id, request.get_json(silent=True))


@workflow_bp.route("/reback-requests/<int:req_id>/decline", methods=["POST"])
@login_required
def api_reback_request_decline(req_id):
    from app.modules.workflow.reback_request import decline_request
    return decline_request(req_id, request.get_json(silent=True))


@workflow_bp.route("/reback-requests/<int:req_id>/cancel", methods=["POST"])
@login_required
def api_reback_request_cancel(req_id):
    from app.modules.workflow.reback_request import cancel_request
    return cancel_request(req_id)
