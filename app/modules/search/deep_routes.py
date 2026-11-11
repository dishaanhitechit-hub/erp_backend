# app/modules/search/deep_routes.py
#
# Deep search — read-only. Access rules are in deep_service.py.

from flask import Blueprint, g, request

from app.middleware.auth_middleware import login_required
from app.modules.search.deep_service import (
    quick_search, get_overview, get_documents, get_table, get_vendor_ledger,
)

deep_search_bp = Blueprint("deep_search", __name__)


# GET /search/quick?type=vendor|item|asset|project|bank|cc|employee&q=&limit=
@deep_search_bp.route("/quick", methods=["GET"])
@login_required
def quick():
    return quick_search(
        g.current_user["id"], request.args.get("type"), request.args.get("q"), request.args.get("limit"),
    )


# GET /search/360/vendor/12   |   /search/360/item/40
@deep_search_bp.route("/360/<string:kind>/<int:subject_id>", methods=["GET"])
@login_required
def overview(kind, subject_id):
    return get_overview(g.current_user["id"], kind.lower(), subject_id)


# GET /search/360/vendor/12/docs?type=ORDER&limit=
@deep_search_bp.route("/360/<string:kind>/<int:subject_id>/docs", methods=["GET"])
@login_required
def documents(kind, subject_id):
    return get_documents(
        g.current_user["id"], kind.lower(), subject_id,
        request.args.get("type"), request.args.get("limit"),
    )


# GET /search/360/employee/5/table?key=PAYROLL
@deep_search_bp.route("/360/<string:kind>/<int:subject_id>/table", methods=["GET"])
@login_required
def table(kind, subject_id):
    return get_table(g.current_user["id"], kind.lower(), subject_id, request.args.get("key"))


# GET /search/360/vendor/12/ledger?fromDate=YYYY-MM-DD&toDate=YYYY-MM-DD
@deep_search_bp.route("/360/vendor/<int:vendor_id>/ledger", methods=["GET"])
@login_required
def vendor_ledger(vendor_id):
    return get_vendor_ledger(
        g.current_user["id"], vendor_id,
        request.args.get("fromDate"), request.args.get("toDate"),
    )
