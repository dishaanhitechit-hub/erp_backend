from flask import Blueprint, request
from app.middleware.auth_middleware import login_required
from .service import get_vendor_ledger, get_vendor_ledger_by_uuid

vendor_ledger_bp = Blueprint("vendor_ledger", __name__)


@vendor_ledger_bp.route("", methods=["GET"])
@login_required
def vendor_ledger_view():
    return get_vendor_ledger(request.args)


@vendor_ledger_bp.route("/uuid/<vendor_uuid>", methods=["GET"])
def vendor_ledger_public(vendor_uuid):
    return get_vendor_ledger_by_uuid(vendor_uuid, request.args)
