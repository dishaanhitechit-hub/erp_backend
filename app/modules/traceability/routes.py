# app/modules/traceability/routes.py
#
# Read-only traceability endpoints.

from flask import Blueprint, g, request

from app.middleware.auth_middleware import login_required
from app.response import res
from app.modules.traceability.service import get_indent_item_trace
from app.modules.traceability.flow_service import get_document_flow
from app.modules.traceability.workbench_service import (
    get_workbench_context, search_documents, get_document_detail,
)

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


# ═════════════════════════════════════════════════════════════════
# Traceability Workbench (Master module)
# Every endpoint checks project + document-type access per document.
# ═════════════════════════════════════════════════════════════════

# GET /traceability/workbench/context
@traceability_bp.route("/workbench/context", methods=["GET"])
@login_required
def workbench_context():
    return get_workbench_context(g.current_user["id"])


# GET /traceability/workbench/search?q=&type=&projectCode=
@traceability_bp.route("/workbench/search", methods=["GET"])
@login_required
def workbench_search():
    return search_documents(
        g.current_user["id"],
        request.args.get("q"),
        request.args.get("type"),
        request.args.get("projectCode"),
    )


# GET /traceability/workbench/flow?type=GRN&id=12&mode=LINEAGE|FULL
#   type may also be INDENT_ITEM (id = indent_items.id)
@traceability_bp.route("/workbench/flow", methods=["GET"])
@login_required
def workbench_flow():
    doc_id = request.args.get("id", type=int)
    if not doc_id:
        return res("id is required", [], 400)
    return get_document_flow(
        g.current_user["id"], request.args.get("type"), doc_id, request.args.get("mode"),
    )


# GET /traceability/workbench/document/<type>/<id>
@traceability_bp.route("/workbench/document/<string:doc_type>/<int:doc_id>", methods=["GET"])
@login_required
def workbench_document(doc_type, doc_id):
    return get_document_detail(g.current_user["id"], doc_type, doc_id)
