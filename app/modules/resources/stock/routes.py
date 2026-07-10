from flask import Blueprint, request
from flask_jwt_extended import jwt_required

from app.response import res
from app.modules.resources.stock.service import (
    get_stock_list,
    get_stock_item_detail,
)

stock_bp = Blueprint("stock", __name__)


# ══════════════════════════════════════════════════════════════════
# GET /resource/stock/list
# Query params:
#   project_code  (required)
#   item_category (optional)
# ══════════════════════════════════════════════════════════════════

@stock_bp.route("/list", methods=["GET"])
@jwt_required()
def stock_list():
    project_code  = request.args.get("project_code", "").strip()
    item_category = request.args.get("item_category", "").strip() or None
    page          = int(request.args.get("page", 1))
    limit         = int(request.args.get("limit", 10))

    if not project_code:
        return res("project_code is required", [], 400)

    return get_stock_list(project_code, item_category, page, limit)


# ══════════════════════════════════════════════════════════════════
# GET /resource/stock/item-detail
# Query params:
#   project_code (required)
#   item_code    (required)
# ══════════════════════════════════════════════════════════════════

@stock_bp.route("/item-detail", methods=["GET"])
@jwt_required()
def stock_item_detail():
    project_code  = request.args.get("project_code", "").strip()
    item_code     = request.args.get("item_code", "").strip() or None
    search        = request.args.get("search", "").strip() or None
    from_date     = request.args.get("from_date", "").strip() or None
    to_date       = request.args.get("to_date", "").strip() or None
    grn_page      = int(request.args.get("grn_page", 1))
    gin_page      = int(request.args.get("gin_page", 1))
    entries_limit = int(request.args.get("entries_limit", 10))

    if not project_code:
        return res("project_code is required", [], 400)

    if not item_code and not search:
        return res("item_code or search is required", [], 400)

    return get_stock_item_detail(
        project_code,
        item_code=item_code,
        search=search,
        from_date=from_date,
        to_date=to_date,
        grn_page=grn_page,
        gin_page=gin_page,
        entries_limit=entries_limit,
    )
