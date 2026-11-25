from flask import Blueprint, request, g
from app.middleware.auth_middleware import login_required
from app.modules.finance.advance_adjustment.service import (
    get_register,
    get_adjustable_bills,
    get_bill_advances,
    get_adjustment_rows,
    get_adjustment_list,
    get_adjustment,
    create_adjustment,
    cancel_adjustment,
)

advance_adjustment_bp = Blueprint("advance_adjustment", __name__)


def _user_id():
    return g.current_user.get("id") if hasattr(g, "current_user") else None


# ── Vendor Advance Register: vendor-wise paid / adjusted / outstanding ──
#    ?projectCode= [&vendorId=] [&outstandingOnly=1]
@advance_adjustment_bp.route("/register", methods=["GET"])
@login_required
def api_register():
    return get_register(request.args.to_dict(), _user_id())


# ── Bills an advance can be adjusted against  ?paymentRequestId= ──
@advance_adjustment_bp.route("/bills", methods=["GET"])
@login_required
def api_bills():
    return get_adjustable_bills(request.args.to_dict(), _user_id())


# ── Notice on a bill: vendor's outstanding advances ───────────────
#    ?purchaseBillId= | ?journalId=&vendorId=
@advance_adjustment_bp.route("/bill-advances", methods=["GET"])
@login_required
def api_bill_advances():
    return get_bill_advances(request.args.to_dict(), _user_id())


# ── Product / CC rows of a bill, auto-filled ──────────────────────
#    ?paymentRequestId=&purchaseBillId=|journalId=[&amount=]
@advance_adjustment_bp.route("/rows", methods=["GET"])
@login_required
def api_rows():
    return get_adjustment_rows(request.args.to_dict(), _user_id())


@advance_adjustment_bp.route("/list", methods=["GET"])
@login_required
def api_list():
    return get_adjustment_list(request.args.to_dict(), _user_id())


@advance_adjustment_bp.route("/<int:adj_id>", methods=["GET"])
@login_required
def api_get(adj_id):
    return get_adjustment(adj_id, _user_id())


@advance_adjustment_bp.route("/create", methods=["POST"])
@login_required
def api_create():
    return create_adjustment(request.get_json(silent=True) or {}, _user_id())


@advance_adjustment_bp.route("/cancel/<int:adj_id>", methods=["POST"])
@login_required
def api_cancel(adj_id):
    return cancel_adjustment(adj_id, request.get_json(silent=True) or {}, _user_id())
