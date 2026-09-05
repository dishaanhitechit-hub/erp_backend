import json
from sqlalchemy import func
from sqlalchemy.exc import SQLAlchemyError
from app.extensions import db
from datetime import datetime, date
from decimal import Decimal
import uuid as _uuid

from app.models.pettyCashDocketVoucher import (
    PettyCashDocketVoucher,
    PettyCashDocketVoucherDetail,
)
from app.models.pettyCashBudget import PettyCashBudget, PettyCashBudgetDetail
from app.cloudinary_uploader import upload_file_to_bunny
from app.response import res
from app.modules.work_flow import (
    is_creator,
    is_current_approver,
    get_first_approver,
    get_next_approver,
    get_gap_level,
    create_history,
    get_history,
    get_approval_steps,
    get_my_approval_status,
)

_MODULE = "petty_cash"


# ══════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════

def _fmt_date(d):
    if d is None:
        return None
    if isinstance(d, datetime):
        return d.strftime("%Y-%m-%d %H:%M")
    return d.strftime("%Y-%m-%d")


def _parse_date(s):
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except Exception:
        return None


def _parse_details(data):
    details = data.get("details", [])
    if isinstance(details, str):
        try:
            details = json.loads(details)
        except Exception:
            details = []
    return details


def _parse_int(val):
    try:
        return int(val) if val else None
    except Exception:
        return None


def _generate_voucher_no():
    last = (
        db.session.query(PettyCashDocketVoucher.voucher_no)
        .order_by(PettyCashDocketVoucher.id.desc())
        .with_for_update()
        .first()
    )
    num = 0
    if last and last[0] and last[0].startswith("DV"):
        try:
            num = int(last[0][2:])
        except Exception:
            num = 0
    return "DV" + str(num + 1).zfill(5)


def _build_detail_row(row):
    return {
        "id":               row.id,
        "slNo":             row.sl_no,
        "ccCode":           row.cc_code,
        "ccName":           row.cc_name,
        "shortDescription": row.short_description,
        "amount":           float(row.amount or 0),
    }


def _build_payload(voucher):
    return {
        "id":              voucher.id,
        "voucherNo":       voucher.voucher_no,
        "voucherUuid":     voucher.voucher_uuid,
        "voucherDate":     _fmt_date(voucher.voucher_date),
        "budgetId":        voucher.budget_id,
        "budgetNo":        voucher.budget.budget_no if voucher.budget else None,
        "expensesBy":      voucher.expenses_by,
        "modeOfPayment":   voucher.mode_of_payment,
        "fundSource":      voucher.fund_source,
        "paymentRefId":    voucher.payment_ref_id,
        "attachment":      voucher.attachment,
        "projectCode":     voucher.project_code,
        "totalAmount":     float(voucher.total_amount or 0),
        "workflowStatus":  voucher.workflow_status,
        "currentLevel":    voucher.current_level,
        "locked":          voucher.locked,
        "createdBy":       voucher.creator.username   if voucher.creator   else None,
        "createdAt":       _fmt_date(voucher.created_at),
        "submittedBy":     voucher.submitter.username if voucher.submitter else None,
        "submittedAt":     _fmt_date(voucher.submitted_at),
        "approvedBy":      voucher.approver.username  if voucher.approver  else None,
        "finalApprovedAt": _fmt_date(voucher.final_approved_at),
        "rejectedBy":      voucher.rejector.username  if voucher.rejector  else None,
        "rejectedAt":      _fmt_date(voucher.rejected_at),
        "details":         [_build_detail_row(r) for r in voucher.details],
    }


# ══════════════════════════════════════════════════════════════════
# 12. FETCH BUDGET ROWS (pre-fill helper)
# ══════════════════════════════════════════════════════════════════

def get_budget_rows_for_voucher(budget_id):
    try:
        budget = PettyCashBudget.query.get(budget_id)
        if not budget:
            return res("Budget not found", [], 404)
        if budget.workflow_status != "Approved":
            return res("Only Approved budgets can be referenced in a Docket Voucher", [], 400)

        # Sum used amounts per budget_detail_id from active vouchers (exclude only Rejected)
        _EXCLUDED = ("Rejected",)
        used_map = dict(
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

        rows = []
        for r in budget.details:
            budget_amt = float(r.budget_amount or 0)
            used_amt   = float(used_map.get(r.id, 0))
            rows.append({
                "budgetDetailId":   r.id,
                "slNo":             r.sl_no,
                "ccCode":           r.cc_code,
                "ccName":           r.cc_name,
                "shortDescription": r.short_description,
                "budgetAmount":     budget_amt,
                "usedAmount":       used_amt,
                "remaining":        round(budget_amt - used_amt, 2),
            })

        return res("Budget rows fetched", {
            "budgetId": budget.id,
            "budgetNo": budget.budget_no,
            "fromDate": _fmt_date(budget.from_date),
            "toDate":   _fmt_date(budget.to_date),
            "rows":     rows,
        }, 200)

    except Exception as e:
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 1. CREATE
# ══════════════════════════════════════════════════════════════════

def create_petty_cash_docket_voucher(data, user_id, files=None):
    try:
        project_code = data.get("projectCode")
        if not project_code:
            return res("projectCode required", [], 400)

        if not is_creator(project_code, _MODULE, user_id):
            return res("You are not authorized to create docket vouchers", [], 403)

        expenses_by     = data.get("expensesBy")
        mode_of_payment = data.get("modeOfPayment")
        fund_source     = data.get("fundSource")

        if not expenses_by:
            return res("expensesBy required", [], 400)
        if not mode_of_payment:
            return res("modeOfPayment required", [], 400)
        if not fund_source:
            return res("fundSource required", [], 400)

        details_data = _parse_details(data)
        if not details_data:
            return res("At least one detail row required", [], 400)

        budget_id = _parse_int(data.get("budgetId"))
        if budget_id:
            budget = PettyCashBudget.query.get(budget_id)
            if not budget:
                return res("Referenced budget not found", [], 404)
            if budget.workflow_status != "Approved":
                return res("Referenced budget must be Approved", [], 400)

        attachment_url = None
        if files:
            f = files.get("attachment")
            if f:
                attachment_url = upload_file_to_bunny(
                    file=f,
                    mainFolder="petty_cash",
                    subFolder="docket_voucher",
                    fileName=str(_uuid.uuid4()),
                )

        total = sum(Decimal(str(r.get("amount") or 0)) for r in details_data)

        voucher = PettyCashDocketVoucher(
            voucher_uuid    = str(_uuid.uuid4()),
            voucher_no      = _generate_voucher_no(),
            voucher_date    = date.today(),
            budget_id       = budget_id,
            expenses_by     = expenses_by,
            mode_of_payment = mode_of_payment,
            fund_source     = fund_source,
            payment_ref_id  = data.get("paymentRefId"),
            attachment      = attachment_url,
            project_code    = project_code,
            total_amount    = total,
            workflow_status = "Draft",
            current_level   = 0,
            locked          = False,
            created_by      = user_id,
        )
        db.session.add(voucher)
        db.session.flush()

        for idx, row in enumerate(details_data, start=1):
            db.session.add(PettyCashDocketVoucherDetail(
                voucher_id        = voucher.id,
                sl_no             = row.get("slNo") or idx,
                budget_detail_id  = _parse_int(row.get("budgetDetailId")),
                cc_code           = row.get("ccCode"),
                cc_name           = row.get("ccName"),
                short_description = row.get("shortDescription"),
                amount            = Decimal(str(row.get("amount") or 0)),
            ))

        db.session.commit()

        return res("Docket voucher created", {
            "id":          voucher.id,
            "voucherNo":   voucher.voucher_no,
            "voucherUuid": voucher.voucher_uuid,
        }, 201)

    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 2. LIST
# ══════════════════════════════════════════════════════════════════

def get_petty_cash_docket_voucher_list(data):
    try:
        project_code = data.get("projectCode")
        if not project_code:
            return res("projectCode required", [], 400)

        query = PettyCashDocketVoucher.query.filter(
            PettyCashDocketVoucher.project_code == project_code
        )

        if data.get("workflowStatus"):
            query = query.filter(PettyCashDocketVoucher.workflow_status == data["workflowStatus"])

        if data.get("search"):
            term = f"%{data['search']}%"
            query = query.filter(PettyCashDocketVoucher.voucher_no.ilike(term))

        if data.get("fromDate"):
            query = query.filter(PettyCashDocketVoucher.voucher_date >= data["fromDate"])

        if data.get("toDate"):
            query = query.filter(PettyCashDocketVoucher.voucher_date <= data["toDate"])

        rows = query.order_by(PettyCashDocketVoucher.id.desc()).all()

        result = [
            {
                "id":             r.id,
                "voucherNo":      r.voucher_no,
                "voucherDate":    _fmt_date(r.voucher_date),
                "budgetNo":       r.budget.budget_no if r.budget else None,
                "expensesBy":     r.expenses_by,
                "modeOfPayment":  r.mode_of_payment,
                "fundSource":     r.fund_source,
                "totalAmount":    float(r.total_amount or 0),
                "workflowStatus": r.workflow_status,
                "createdBy":      r.creator.username if r.creator else None,
                "createdAt":      _fmt_date(r.created_at),
            }
            for r in rows
        ]

        return res("Docket voucher list fetched", {"list": result}, 200)

    except Exception as e:
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 3. GET BY ID
# ══════════════════════════════════════════════════════════════════

def get_petty_cash_docket_voucher_details(voucher_id):
    try:
        voucher = PettyCashDocketVoucher.query.get(voucher_id)
        if not voucher:
            return res("Docket voucher not found", [], 404)
        return res("Docket voucher fetched", _build_payload(voucher), 200)
    except Exception as e:
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 4. GET BY UUID (public, no auth)
# ══════════════════════════════════════════════════════════════════

def get_petty_cash_docket_voucher_by_uuid(voucher_uuid):
    try:
        voucher = PettyCashDocketVoucher.query.filter_by(voucher_uuid=voucher_uuid).first()
        if not voucher:
            return res("Docket voucher not found", [], 404)
        return res("Docket voucher fetched", _build_payload(voucher), 200)
    except Exception as e:
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 5. EDIT (Draft / Reback only)
# ══════════════════════════════════════════════════════════════════

def edit_petty_cash_docket_voucher(voucher_id, data, user_id, files=None):
    try:
        voucher = PettyCashDocketVoucher.query.get(voucher_id)
        if not voucher:
            return res("Docket voucher not found", [], 404)
        if voucher.locked:
            return res("Docket voucher is locked and cannot be edited", [], 400)
        if voucher.workflow_status not in ("Draft", "Reback"):
            return res("Only Draft or Reback records can be edited", [], 400)

        if not is_creator(voucher.project_code, _MODULE, user_id):
            return res("You are not authorized to edit this docket voucher", [], 403)

        details_data = _parse_details(data)
        if not details_data:
            return res("At least one detail row required", [], 400)

        if data.get("expensesBy"):
            voucher.expenses_by = data["expensesBy"]
        if data.get("modeOfPayment"):
            voucher.mode_of_payment = data["modeOfPayment"]
        if data.get("fundSource"):
            voucher.fund_source = data["fundSource"]
        if data.get("paymentRefId") is not None:
            voucher.payment_ref_id = data["paymentRefId"]

        raw_budget_id = data.get("budgetId")
        if raw_budget_id is not None:
            budget_id = _parse_int(raw_budget_id)
            if budget_id:
                budget = PettyCashBudget.query.get(budget_id)
                if not budget:
                    return res("Referenced budget not found", [], 404)
                if budget.workflow_status != "Approved":
                    return res("Referenced budget must be Approved", [], 400)
            voucher.budget_id = budget_id

        if files:
            f = files.get("attachment")
            if f:
                voucher.attachment = upload_file_to_bunny(
                    file=f,
                    mainFolder="petty_cash",
                    subFolder="docket_voucher",
                    fileName=str(_uuid.uuid4()),
                )

        PettyCashDocketVoucherDetail.query.filter_by(voucher_id=voucher.id).delete()
        db.session.flush()

        total = Decimal("0")
        for idx, row in enumerate(details_data, start=1):
            amt = Decimal(str(row.get("amount") or 0))
            total += amt
            db.session.add(PettyCashDocketVoucherDetail(
                voucher_id        = voucher.id,
                sl_no             = row.get("slNo") or idx,
                budget_detail_id  = _parse_int(row.get("budgetDetailId")),
                cc_code           = row.get("ccCode"),
                cc_name           = row.get("ccName"),
                short_description = row.get("shortDescription"),
                amount            = amt,
            ))

        voucher.total_amount = total

        if voucher.workflow_status == "Reback":
            voucher.correction_sent_at = None

        voucher.updated_by = user_id
        voucher.updated_at = datetime.utcnow()

        db.session.commit()

        return res("Docket voucher updated", {"id": voucher.id, "voucherNo": voucher.voucher_no}, 200)

    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 6. SUBMIT
# ══════════════════════════════════════════════════════════════════

def submit_petty_cash_docket_voucher(voucher_id, user_id):
    try:
        voucher = PettyCashDocketVoucher.query.get(voucher_id)
        if not voucher:
            return res("Docket voucher not found", [], 404)
        if voucher.workflow_status not in ("Draft", "Reback"):
            return res("Docket voucher already submitted", [], 400)
        if not voucher.details:
            return res("Docket voucher has no detail rows", [], 400)

        if voucher.workflow_status == "Reback":
            voucher.current_level = 0

        first_level = get_first_approver(voucher.project_code, _MODULE)

        if not first_level:
            voucher.workflow_status   = "Approved"
            voucher.locked            = True
            voucher.approved_by       = user_id
            voucher.submitted_at      = datetime.utcnow()
            voucher.final_approved_at = datetime.utcnow()
        else:
            voucher.workflow_status = f"Pending_L{first_level.level_no}"
            voucher.current_level   = first_level.level_no
            voucher.locked          = True
            voucher.submitted_at    = datetime.utcnow()

        create_history(
            project_code=voucher.project_code,
            module_code=_MODULE,
            record_id=voucher.id,
            level_no=voucher.current_level,
            action="SUBMIT",
            action_by=user_id,
        )

        voucher.submitted_by = user_id
        voucher.updated_by   = user_id
        voucher.updated_at   = datetime.utcnow()

        db.session.commit()

        return res("Docket voucher submitted", {"id": voucher.id, "workflowStatus": voucher.workflow_status}, 200)

    except SQLAlchemyError as e:
        db.session.rollback()
        return res(str(e), [], 500)
    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 7. APPROVE
# ══════════════════════════════════════════════════════════════════

def approve_petty_cash_docket_voucher(voucher_id, approved_by, comments=None):
    try:
        voucher = PettyCashDocketVoucher.query.get(voucher_id)
        if not voucher:
            return res("Docket voucher not found", [], 404)
        if not voucher.workflow_status.startswith("Pending"):
            return res("Docket voucher is not pending approval", [], 400)

        if not is_current_approver(voucher.project_code, _MODULE, voucher.current_level, approved_by):
            return res("You are not the current approver", [], 403)

        gap = get_gap_level(voucher.project_code, _MODULE, voucher.current_level)
        if gap:
            return res(f"L{gap} is not assigned. Please assign it before approving.", [], 400)

        next_level = get_next_approver(voucher.project_code, _MODULE, voucher.current_level)

        if next_level:
            create_history(
                project_code=voucher.project_code, module_code=_MODULE,
                record_id=voucher.id, level_no=voucher.current_level,
                action="APPROVE", action_by=approved_by, comments=comments,
            )
            voucher.current_level   = next_level.level_no
            voucher.workflow_status = f"Pending_L{next_level.level_no}"
        else:
            create_history(
                project_code=voucher.project_code, module_code=_MODULE,
                record_id=voucher.id, level_no=voucher.current_level,
                action="FINAL_APPROVE", action_by=approved_by, comments=comments,
            )
            voucher.workflow_status   = "Approved"
            voucher.locked            = True
            voucher.approved_by       = approved_by
            voucher.final_approved_at = datetime.utcnow()

        voucher.updated_by = approved_by
        voucher.updated_at = datetime.utcnow()

        db.session.commit()

        return res("Docket voucher approved", {"id": voucher.id, "workflowStatus": voucher.workflow_status}, 200)

    except SQLAlchemyError as e:
        db.session.rollback()
        return res(str(e), [], 500)
    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 8. REBACK
# ══════════════════════════════════════════════════════════════════

def reback_petty_cash_docket_voucher(voucher_id, reback_by, comments=None):
    try:
        voucher = PettyCashDocketVoucher.query.get(voucher_id)
        if not voucher:
            return res("Docket voucher not found", [], 404)
        if not voucher.workflow_status.startswith("Pending"):
            return res("Docket voucher is not pending", [], 400)
        if not comments:
            return res("Comments required for reback", [], 400)

        if not is_current_approver(voucher.project_code, _MODULE, voucher.current_level, reback_by):
            return res("You are not the current approver", [], 403)

        voucher.workflow_status    = "Reback"
        voucher.locked             = False
        voucher.correction_sent_at = datetime.utcnow()
        voucher.updated_by         = reback_by
        voucher.updated_at         = datetime.utcnow()

        create_history(
            project_code=voucher.project_code, module_code=_MODULE,
            record_id=voucher.id, level_no=voucher.current_level,
            action="REBACK", action_by=reback_by, comments=comments,
        )

        db.session.commit()

        return res("Docket voucher sent for correction", {"id": voucher.id, "workflowStatus": voucher.workflow_status}, 200)

    except SQLAlchemyError as e:
        db.session.rollback()
        return res(str(e), [], 500)
    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 9. REJECT
# ══════════════════════════════════════════════════════════════════

def reject_petty_cash_docket_voucher(voucher_id, rejected_by, comments=None):
    try:
        voucher = PettyCashDocketVoucher.query.get(voucher_id)
        if not voucher:
            return res("Docket voucher not found", [], 404)
        if not voucher.workflow_status.startswith("Pending"):
            return res("Docket voucher is not pending", [], 400)
        if not comments:
            return res("Comments required for rejection", [], 400)

        if not is_current_approver(voucher.project_code, _MODULE, voucher.current_level, rejected_by):
            return res("You are not the current approver", [], 403)

        voucher.workflow_status = "Rejected"
        voucher.locked          = True
        voucher.rejected_at     = datetime.utcnow()
        voucher.rejected_by     = rejected_by
        voucher.status          = "Inactive"
        voucher.updated_by      = rejected_by
        voucher.updated_at      = datetime.utcnow()

        create_history(
            project_code=voucher.project_code, module_code=_MODULE,
            record_id=voucher.id, level_no=voucher.current_level,
            action="REJECT", action_by=rejected_by, comments=comments,
        )

        db.session.commit()

        return res("Docket voucher rejected", {"id": voucher.id, "workflowStatus": voucher.workflow_status}, 200)

    except SQLAlchemyError as e:
        db.session.rollback()
        return res(str(e), [], 500)
    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 10. HISTORY
# ══════════════════════════════════════════════════════════════════

def get_petty_cash_docket_voucher_history(voucher_id):
    try:
        voucher = PettyCashDocketVoucher.query.get(voucher_id)
        if not voucher:
            return res("Docket voucher not found", [], 404)

        rows = get_history(_MODULE, voucher.id)

        history = [
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

        steps = get_approval_steps(voucher.project_code, _MODULE, voucher, rows)

        return res("History fetched", {
            "workflowStatus": voucher.workflow_status,
            "currentLevel":   voucher.current_level,
            "approvalSteps":  steps,
            "history":        history,
        }, 200)

    except Exception as e:
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 11. MY APPROVAL STATUS
# ══════════════════════════════════════════════════════════════════

def get_petty_cash_docket_voucher_my_approval_status(voucher_id, user_id):
    try:
        voucher = PettyCashDocketVoucher.query.get(voucher_id)
        if not voucher:
            return res("Docket voucher not found", [], 404)
        data = get_my_approval_status(voucher.project_code, _MODULE, voucher, user_id)
        return res("Approval status", data, 200)
    except Exception as e:
        return res(str(e), [], 500)
