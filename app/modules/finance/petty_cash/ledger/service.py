from sqlalchemy import func
from app.extensions import db
from datetime import datetime

from app.models.pettyCashBudget import (
    PettyCashBudget,
    PettyCashBudgetDetail,
    PettyCashBudgetRevision,
)
from app.models.pettyCashDocketVoucher import (
    PettyCashDocketVoucher,
    PettyCashDocketVoucherDetail,
)
from app.response import res
from app.modules.work_flow import get_history

_BUDGET_MODULE  = "petty_cash_budget"
_VOUCHER_MODULE = "petty_cash_docket_voucher"
_EXCLUDED       = ("Draft", "Rejected")


# ══════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════

def _fmt(d):
    if d is None:
        return None
    if isinstance(d, datetime):
        return d.strftime("%Y-%m-%d %H:%M")
    return d.strftime("%Y-%m-%d")


def _history_rows(module, record_id):
    rows = get_history(module, record_id)
    return [
        {
            "id":        r.id,
            "action":    r.action,
            "level":     r.level_no,
            "comments":  r.comments,
            "actionBy":  r.user.username if r.user else None,
            "createdAt": r.created_at.strftime("%Y-%m-%d %H:%M:%S") if r.created_at else None,
        }
        for r in rows
    ]


def _used_map_for_budget(budget_id):
    """Returns {budget_detail_id: used_amount} for all active vouchers under a budget."""
    rows = (
        db.session.query(
            PettyCashDocketVoucherDetail.budget_detail_id,
            func.coalesce(func.sum(PettyCashDocketVoucherDetail.amount), 0),
        )
        .join(PettyCashDocketVoucher,
              PettyCashDocketVoucher.id == PettyCashDocketVoucherDetail.voucher_id)
        .filter(
            PettyCashDocketVoucher.budget_id == budget_id,
            PettyCashDocketVoucherDetail.budget_detail_id.isnot(None),
            PettyCashDocketVoucher.workflow_status.notin_(_EXCLUDED),
        )
        .group_by(PettyCashDocketVoucherDetail.budget_detail_id)
        .all()
    )
    return {r[0]: float(r[1]) for r in rows}


def _total_used_for_budget(budget_id):
    """Total used across all CC codes for a budget (for list summary)."""
    result = (
        db.session.query(
            func.coalesce(func.sum(PettyCashDocketVoucherDetail.amount), 0)
        )
        .join(PettyCashDocketVoucher,
              PettyCashDocketVoucher.id == PettyCashDocketVoucherDetail.voucher_id)
        .filter(
            PettyCashDocketVoucher.budget_id == budget_id,
            PettyCashDocketVoucher.workflow_status.notin_(_EXCLUDED),
        )
        .scalar()
    )
    return float(result or 0)


def _voucher_count_for_budget(budget_id):
    return PettyCashDocketVoucher.query.filter_by(budget_id=budget_id).count()


# ══════════════════════════════════════════════════════════════════
# 1. LIST — budget summary cards for a project
# ══════════════════════════════════════════════════════════════════

def get_petty_cash_ledger_list(params):
    try:
        project_code = params.get("projectCode")
        if not project_code:
            return res("projectCode required", [], 400)

        query = PettyCashBudget.query.filter(PettyCashBudget.project_code == project_code)

        if params.get("workflowStatus"):
            query = query.filter(PettyCashBudget.workflow_status == params["workflowStatus"])

        if params.get("fromDate"):
            query = query.filter(PettyCashBudget.from_date >= params["fromDate"])

        if params.get("toDate"):
            query = query.filter(PettyCashBudget.to_date <= params["toDate"])

        budgets = query.order_by(PettyCashBudget.id.desc()).all()

        result = []
        for b in budgets:
            total_budget = float(b.total_budget_amount or 0)
            total_used   = _total_used_for_budget(b.id)
            result.append({
                "id":                 b.id,
                "budgetNo":           b.budget_no,
                "budgetDate":         _fmt(b.budget_date),
                "budgetFrequency":    b.budget_frequency,
                "fromDate":           _fmt(b.from_date),
                "toDate":             _fmt(b.to_date),
                "totalBudgetAmount":  total_budget,
                "totalUsed":          total_used,
                "totalRemaining":     round(total_budget - total_used, 2),
                "voucherCount":       _voucher_count_for_budget(b.id),
                "workflowStatus":     b.workflow_status,
                "createdBy":          b.creator.username if b.creator else None,
                "createdAt":          _fmt(b.created_at),
            })

        return res("Petty cash ledger list fetched", {"list": result}, 200)

    except Exception as e:
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 2. DETAIL — full ledger for one budget
# ══════════════════════════════════════════════════════════════════

def get_petty_cash_ledger_detail(budget_id):
    try:
        budget = PettyCashBudget.query.get(budget_id)
        if not budget:
            return res("Budget not found", [], 404)

        # ── Budget block ──────────────────────────────────────────
        budget_block = {
            "id":               budget.id,
            "budgetNo":         budget.budget_no,
            "budgetDate":       _fmt(budget.budget_date),
            "budgetFrequency":  budget.budget_frequency,
            "fromDate":         _fmt(budget.from_date),
            "toDate":           _fmt(budget.to_date),
            "attachment":       budget.attachment,
            "projectCode":      budget.project_code,
            "totalBudgetAmount":float(budget.total_budget_amount or 0),
            "workflowStatus":   budget.workflow_status,
            "currentLevel":     budget.current_level,
            "createdBy":        budget.creator.username   if budget.creator   else None,
            "createdAt":        _fmt(budget.created_at),
            "submittedBy":      budget.submitter.username if budget.submitter else None,
            "submittedAt":      _fmt(budget.submitted_at),
            "approvedBy":       budget.approver.username  if budget.approver  else None,
            "finalApprovedAt":  _fmt(budget.final_approved_at),
            "rejectedBy":       budget.rejector.username  if budget.rejector  else None,
            "rejectedAt":       _fmt(budget.rejected_at),
            "approvalHistory":  _history_rows(_BUDGET_MODULE, budget.id),
            "revisionHistory":  [
                {
                    "id":          r.id,
                    "ccName":      r.detail_row.cc_name if r.detail_row else None,
                    "oldAmount":   float(r.old_amount),
                    "newAmount":   float(r.new_amount),
                    "remark":      r.remark,
                    "revisedBy":   r.revisor.username if r.revisor else None,
                    "revisedAt":   r.revised_at.strftime("%Y-%m-%d %H:%M:%S") if r.revised_at else None,
                }
                for r in PettyCashBudgetRevision.query
                    .filter_by(budget_id=budget.id)
                    .order_by(PettyCashBudgetRevision.id.asc())
                    .all()
            ],
        }

        # ── CC-wise summary ───────────────────────────────────────
        used_map = _used_map_for_budget(budget.id)
        cc_summary = []
        for d in budget.details:
            budget_amt = float(d.budget_amount or 0)
            used_amt   = used_map.get(d.id, 0.0)
            cc_summary.append({
                "budgetDetailId":   d.id,
                "slNo":             d.sl_no,
                "ccCode":           d.cc_code,
                "ccName":           d.cc_name,
                "shortDescription": d.short_description,
                "budgetAmount":     budget_amt,
                "usedAmount":       used_amt,
                "remaining":        round(budget_amt - used_amt, 2),
            })

        # ── Vouchers ──────────────────────────────────────────────
        vouchers_q = (
            PettyCashDocketVoucher.query
            .filter_by(budget_id=budget.id)
            .order_by(PettyCashDocketVoucher.id.asc())
            .all()
        )

        vouchers = []
        status_counts = {"approvedVouchers": 0, "pendingVouchers": 0,
                         "draftVouchers": 0, "rejectedVouchers": 0, "rebackVouchers": 0}

        for v in vouchers_q:
            ws = v.workflow_status
            if ws == "Approved":
                status_counts["approvedVouchers"] += 1
            elif ws.startswith("Pending"):
                status_counts["pendingVouchers"] += 1
            elif ws == "Draft":
                status_counts["draftVouchers"] += 1
            elif ws == "Rejected":
                status_counts["rejectedVouchers"] += 1
            elif ws == "Reback":
                status_counts["rebackVouchers"] += 1

            vouchers.append({
                "id":              v.id,
                "voucherNo":       v.voucher_no,
                "voucherDate":     _fmt(v.voucher_date),
                "expensesBy":      v.expenses_by,
                "modeOfPayment":   v.mode_of_payment,
                "fundSource":      v.fund_source,
                "paymentRefId":    v.payment_ref_id,
                "attachment":      v.attachment,
                "totalAmount":     float(v.total_amount or 0),
                "workflowStatus":  v.workflow_status,
                "createdBy":       v.creator.username   if v.creator   else None,
                "createdAt":       _fmt(v.created_at),
                "submittedBy":     v.submitter.username if v.submitter else None,
                "submittedAt":     _fmt(v.submitted_at),
                "approvedBy":      v.approver.username  if v.approver  else None,
                "finalApprovedAt": _fmt(v.final_approved_at),
                "approvalHistory": _history_rows(_VOUCHER_MODULE, v.id),
                "details": [
                    {
                        "slNo":             d.sl_no,
                        "budgetDetailId":   d.budget_detail_id,
                        "ccCode":           d.cc_code,
                        "ccName":           d.cc_name,
                        "shortDescription": d.short_description,
                        "amount":           float(d.amount or 0),
                    }
                    for d in v.details
                ],
            })

        # ── Overall summary ───────────────────────────────────────
        total_budget    = float(budget.total_budget_amount or 0)
        total_used      = sum(used_map.get(d.id, 0.0) for d in budget.details)
        overall_summary = {
            "totalBudgetAmount": total_budget,
            "totalUsed":         round(total_used, 2),
            "totalRemaining":    round(total_budget - total_used, 2),
            "voucherCount":      len(vouchers_q),
            **status_counts,
        }

        return res("Petty cash ledger fetched", {
            "budget":    budget_block,
            "ccSummary": cc_summary,
            "vouchers":  vouchers,
            "summary":   overall_summary,
        }, 200)

    except Exception as e:
        return res(str(e), [], 500)
