from flask import Blueprint, request
from app.middleware.auth_middleware import login_required
from .service import get_my_ledger

my_ledger_bp = Blueprint("my_ledger", __name__)


@my_ledger_bp.route("", methods=["GET"])
@login_required
def my_ledger_view():
    return get_my_ledger(request.args)
