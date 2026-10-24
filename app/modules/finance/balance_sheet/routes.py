from flask import Blueprint, request
from flask_jwt_extended import jwt_required

from app.modules.finance.balance_sheet.service import get_balance_sheet

balance_sheet_bp = Blueprint("balance_sheet", __name__)


@balance_sheet_bp.route("", methods=["GET"])
@jwt_required()
def balance_sheet():
    return get_balance_sheet(request.args)
