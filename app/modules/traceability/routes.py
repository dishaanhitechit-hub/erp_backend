# app/modules/traceability/routes.py
#
# Read-only item traceability endpoints.

from flask import Blueprint, g

from app.middleware.auth_middleware import login_required
from app.modules.traceability.service import get_indent_item_trace

traceability_bp = Blueprint("traceability", __name__)


#
# GET /traceability/indent-item/<indent_item_id>
#
# Full downstream lifecycle of one indent item. Access requires the
# Indent page permission on the indent's own project (checked in service).
#
@traceability_bp.route("/indent-item/<int:indent_item_id>", methods=["GET"])
@login_required
def indent_item_trace(indent_item_id):
    return get_indent_item_trace(indent_item_id, g.current_user["id"])
