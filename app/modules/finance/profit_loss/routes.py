from flask import Blueprint, request
from flask_jwt_extended import jwt_required

from app.modules.finance.profit_loss.service import get_pl_report

profit_loss_bp = Blueprint("profit_loss", __name__)


@profit_loss_bp.route("", methods=["GET"])
@jwt_required()
def pl_report():
    return get_pl_report(request.args)
