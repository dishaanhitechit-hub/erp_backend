from flask import Blueprint, request, g
from flask_jwt_extended import jwt_required

from .ledger_service import (
    get_general_ledger,
    get_trial_balance,
    get_profit_loss,
    get_balance_sheet_report,
    get_vendor_ledger_central,
    get_customer_ledger,
    get_bank_ledger,
    get_cc_ledger,
    get_day_book,
    get_voucher_register,
    get_outstanding_payables,
    get_outstanding_receivables,
    get_gst_summary,
    get_project_summary,
    get_group_ledger,
    list_financial_years,
    create_financial_year,
)
from .historical_posting import run_historical_posting, get_posting_status
from .opening_balance_service import list_opening_balances, save_opening_balance, delete_opening_balance
from .cancellation_service import cancel_posted_document, get_cancellation_info

accounting_bp = Blueprint("accounting", __name__)


# ── General Ledger ────────────────────────────────────────────────────────

@accounting_bp.route("/ledger", methods=["GET"])
@jwt_required()
def general_ledger():
    return get_general_ledger(request.args)


# ── Trial Balance ─────────────────────────────────────────────────────────

@accounting_bp.route("/trial-balance", methods=["GET"])
@jwt_required()
def trial_balance():
    return get_trial_balance(request.args)


# ── Profit & Loss ─────────────────────────────────────────────────────────

@accounting_bp.route("/profit-loss", methods=["GET"])
@jwt_required()
def profit_loss():
    return get_profit_loss(request.args)


# ── Balance Sheet ─────────────────────────────────────────────────────────

@accounting_bp.route("/balance-sheet", methods=["GET"])
@jwt_required()
def balance_sheet():
    return get_balance_sheet_report(request.args)


# ── Vendor Ledger ─────────────────────────────────────────────────────────

@accounting_bp.route("/vendor-ledger", methods=["GET"])
@jwt_required()
def vendor_ledger():
    return get_vendor_ledger_central(request.args)


# ── Customer Ledger ───────────────────────────────────────────────────────

@accounting_bp.route("/customer-ledger", methods=["GET"])
@jwt_required()
def customer_ledger():
    return get_customer_ledger(request.args)


# ── Bank Ledger ───────────────────────────────────────────────────────────

@accounting_bp.route("/bank-ledger", methods=["GET"])
@jwt_required()
def bank_ledger():
    return get_bank_ledger(request.args)


# ── CC-Code Ledger ────────────────────────────────────────────────────────

@accounting_bp.route("/cc-ledger", methods=["GET"])
@jwt_required()
def cc_ledger():
    return get_cc_ledger(request.args)


# ── Day Book ──────────────────────────────────────────────────────────────

@accounting_bp.route("/day-book", methods=["GET"])
@jwt_required()
def day_book():
    return get_day_book(request.args)


# ── Voucher Register ──────────────────────────────────────────────────────

@accounting_bp.route("/voucher-register", methods=["GET"])
@jwt_required()
def voucher_register():
    return get_voucher_register(request.args)


# ── Outstanding Payables ──────────────────────────────────────────────────

@accounting_bp.route("/outstanding-payables", methods=["GET"])
@jwt_required()
def outstanding_payables():
    return get_outstanding_payables(request.args)


# ── Outstanding Receivables ───────────────────────────────────────────────

@accounting_bp.route("/outstanding-receivables", methods=["GET"])
@jwt_required()
def outstanding_receivables():
    return get_outstanding_receivables(request.args)


# ── GST Summary ───────────────────────────────────────────────────────────

@accounting_bp.route("/gst-summary", methods=["GET"])
@jwt_required()
def gst_summary():
    return get_gst_summary(request.args)


# ── Project Financial Summary ─────────────────────────────────────────────

@accounting_bp.route("/project-summary", methods=["GET"])
@jwt_required()
def project_summary():
    return get_project_summary(request.args)


# ── Group-wise Ledger ─────────────────────────────────────────────────────

@accounting_bp.route("/group-ledger", methods=["GET"])
@jwt_required()
def group_ledger():
    return get_group_ledger(request.args)


# ── Financial Year ────────────────────────────────────────────────────────

@accounting_bp.route("/financial-year", methods=["GET"])
@jwt_required()
def financial_years():
    return list_financial_years()


@accounting_bp.route("/financial-year", methods=["POST"])
@jwt_required()
def create_fy():
    return create_financial_year(request.json, g.current_user["id"])


# ── Historical Posting ────────────────────────────────────────────────────

@accounting_bp.route("/historical-posting", methods=["POST"])
@jwt_required()
def historical_posting():
    try:
        return run_historical_posting(g.current_user["id"], request.json or {})
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {"message": f"Historical posting failed: {str(e)}"}, 500


@accounting_bp.route("/posting-status", methods=["GET"])
@jwt_required()
def posting_status():
    try:
        return get_posting_status()
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {"message": f"Posting status failed: {str(e)}"}, 500


# ── Opening Balances ─────────────────────────────────────────────────────

@accounting_bp.route("/opening-balance", methods=["GET"])
@jwt_required()
def opening_balances():
    return list_opening_balances(request.args)


@accounting_bp.route("/opening-balance", methods=["POST"])
@jwt_required()
def create_opening_balance():
    return save_opening_balance(request.json, g.current_user["id"])


@accounting_bp.route("/opening-balance/<int:posting_id>", methods=["DELETE"])
@jwt_required()
def remove_opening_balance(posting_id):
    return delete_opening_balance(posting_id, g.current_user["id"])


# ── Export endpoints ──────────────────────────────────────────────────────

@accounting_bp.route("/export/ledger", methods=["GET"])
@jwt_required()
def export_ledger():
    from .export_service import export_general_ledger
    return export_general_ledger(request.args)


@accounting_bp.route("/export/trial-balance", methods=["GET"])
@jwt_required()
def export_trial_balance():
    from .export_service import export_trial_balance
    return export_trial_balance(request.args)


@accounting_bp.route("/export/profit-loss", methods=["GET"])
@jwt_required()
def export_profit_loss():
    from .export_service import export_profit_loss
    return export_profit_loss(request.args)


@accounting_bp.route("/export/balance-sheet", methods=["GET"])
@jwt_required()
def export_balance_sheet():
    from .export_service import export_balance_sheet
    return export_balance_sheet(request.args)


# ── Cancellation / Reversal ──────────────────────────────────────────────

@accounting_bp.route("/cancel", methods=["POST"])
@jwt_required()
def cancel_document():
    body = request.get_json(silent=True) or {}
    source_type = body.get("source_type")
    source_id = body.get("source_id")
    reason = body.get("reason")
    if not source_type or not source_id:
        return {"message": "source_type and source_id are required"}, 400
    result, status = cancel_posted_document(source_type, int(source_id), g.user_id, reason)
    return result, status


@accounting_bp.route("/cancellation-status", methods=["GET"])
@jwt_required()
def cancellation_status():
    source_type = request.args.get("source_type")
    source_id = request.args.get("source_id")
    if not source_type or not source_id:
        return {"message": "source_type and source_id are required"}, 400
    result, status = get_cancellation_info(source_type, int(source_id))
    return result, status


# ── Stock Balance ───────────────────────────────────────────────────
@accounting_bp.route("/stock-balance", methods=["GET"])
@jwt_required()
def stock_balance():
    try:
        from .stock_ledger_service import get_stock_balance
        item_id = request.args.get("item_id")
        project_code = request.args.get("project_code")
        location_id = request.args.get("location_id")
        if not item_id:
            return {"message": "item_id is required"}, 400
        qty, value, wac = get_stock_balance(
            int(item_id), project_code, location_id
        )
        return {
            "message": "OK",
            "data": {
                "runningQty": float(qty),
                "runningValue": float(value),
                "wacRate": float(wac),
            },
        }, 200
    except Exception as e:
        return {"message": str(e)}, 500


@accounting_bp.route("/stock-summary", methods=["GET"])
@jwt_required()
def stock_summary():
    """Aggregate stock balances by project, optionally filtered by project_code."""
    try:
        from app.models.stockLedger import StockLedger
        from sqlalchemy import func as sqlfunc
        project_code = request.args.get("project_code")

        sub = (
            db.session.query(
                StockLedger.item_id,
                StockLedger.item_code,
                StockLedger.project_code,
                StockLedger.location_id,
                sqlfunc.max(StockLedger.id).label("max_id"),
            )
            .filter(StockLedger.is_reversal == False)
            .group_by(
                StockLedger.item_id,
                StockLedger.item_code,
                StockLedger.project_code,
                StockLedger.location_id,
            )
        )
        if project_code:
            sub = sub.filter(StockLedger.project_code == project_code)
        sub = sub.subquery()

        rows = (
            db.session.query(
                StockLedger.item_id,
                StockLedger.item_code,
                StockLedger.project_code,
                StockLedger.location_id,
                StockLedger.running_qty,
                StockLedger.running_value,
            )
            .join(sub, StockLedger.id == sub.c.max_id)
            .all()
        )

        items = []
        for r in rows:
            rq = float(r.running_qty or 0)
            rv = float(r.running_value or 0)
            wac = round(rv / rq, 2) if rq > 0 else 0
            items.append({
                "itemId": r.item_id,
                "itemCode": r.item_code,
                "projectCode": r.project_code,
                "locationId": r.location_id,
                "runningQty": rq,
                "runningValue": rv,
                "wacRate": wac,
            })
        return {"message": "OK", "data": items}, 200
    except Exception as e:
        return {"message": str(e)}, 500
