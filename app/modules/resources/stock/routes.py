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
    project_code = request.args.get("project_code", "").strip()
    item_category = request.args.get("item_category", "").strip() or None

    if not project_code:
        return res("project_code is required", [], 400)

    return get_stock_list(project_code, item_category)


# ══════════════════════════════════════════════════════════════════
# GET /resource/stock/item-detail
# Query params:
#   project_code (required)
#   item_code    (required)
# ══════════════════════════════════════════════════════════════════

@stock_bp.route("/item-detail", methods=["GET"])
@jwt_required()
def stock_item_detail():
    project_code = request.args.get("project_code", "").strip()
    item_code = request.args.get("item_code", "").strip()

    if not project_code or not item_code:
        return res("project_code and item_code are required", [], 400)

    return get_stock_item_detail(project_code, item_code)
