"""
Payment Request — raised against an Approved BRR (Bill Receive Register).

Rules
─────
* Only an Approved BRR can have payment requests.
* Partial requests are allowed: many requests per BRR, as long as the sum of
  requested amounts of all non-Rejected requests never exceeds the bill amount.
* Bill amount = total of the BRR's Approved BRB when one exists, else BRR total.
* The balance is re-validated (with the BRR row locked) on create, edit,
  submit and final approval, so parallel requests can never overrun the bill.
* Creator / approver checks follow the shared approval path
  (module code `payment_request`), same as BRR.
"""

from decimal import Decimal, InvalidOperation
from datetime import datetime
import time as _time
import uuid as _uuid_lib

from sqlalchemy import func
from sqlalchemy.exc import SQLAlchemyError

from app.extensions import db
from app.models.brrMaster import BrrMaster
from app.models.brbMaster import BrbMaster
from app.models.paymentRequest import PaymentRequestMaster
from app.models.user import User
from app.response import res
from app.utils.date_utils import parse_date
from app.cloudinary_uploader import upload_file_to_bunny, delete_file_from_storage
from app.modules.communication import whatsapp_events as wa
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

_MODULE   = "payment_request"   # approval path / page code
_WA_CODE  = "payment_request"   # whatsapp module code
_NO_BASE  = 930000              # PR serial range (BRR 900000, BRB 910000, BRS 920000)
_TWO_DP   = Decimal("0.01")
_PAYMENT_MODES = {"Bank", "Cash"}


# ══════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════

def _fmt_date(d):
    if d is None:
        return None
    try:
        if isinstance(d, datetime):
            return d.strftime("%Y-%m-%d %H:%M")
        return d.strftime("%Y-%m-%d")
    except (ValueError, OverflowError):
        return None


def _dec(value, field):
    """Parse a money value into a 2-dp Decimal; blank → 0."""
    if value is None or value == "":
        return Decimal("0.00")
    try:
        return Decimal(str(value)).quantize(_TWO_DP)
    except (InvalidOperation, ValueError):
        raise ValueError(f"{field} must be a valid number")


def _f(v):
    return float(v or 0)


def generate_pr_no():
    last = (
        db.session.query(PaymentRequestMaster.pr_no)
        .order_by(PaymentRequestMaster.id.desc())
        .with_for_update()
        .first()
    )
    try:
        last_serial = int(last[0]) if last else _NO_BASE
    except Exception:
        last_serial = _NO_BASE
    return str(last_serial + 1)


def _lock_brr(brr_id):
    """Fetch the BRR with a row lock so balance checks are serialized."""
    return (
        BrrMaster.query
        .filter(BrrMaster.id == brr_id)
        .with_for_update()
        .first()
    )


def _approved_brb(brr_id):
    return (
        BrbMaster.query
        .filter(BrbMaster.brr_id == brr_id, BrbMaster.workflow_status == "Approved")
        .order_by(BrbMaster.id.desc())
        .first()
    )


def _linked_brb(brr_id):
    """The BRR's billing record (BRB) shown to the user: latest non-Rejected one."""
    return (
        BrbMaster.query
        .filter(BrbMaster.brr_id == brr_id, BrbMaster.workflow_status != "Rejected")
        .order_by(BrbMaster.id.desc())
        .first()
    )


def _bill_amount(brr):
    """Approved BRB total when present (actual reconciled bill), else BRR total."""
    brb = _approved_brb(brr.id)
    if brb:
        return Decimal(str(brb.total_amount or 0)).quantize(_TWO_DP)
    return Decimal(str(brr.total_amount or 0)).quantize(_TWO_DP)


def _requested_total(brr_id, exclude_id=None):
    """Sum of requested amounts of all non-Rejected requests on a BRR."""
    q = db.session.query(func.coalesce(func.sum(PaymentRequestMaster.requested_amount), 0)).filter(
        PaymentRequestMaster.brr_id == brr_id,
        PaymentRequestMaster.workflow_status != "Rejected",
    )
    if exclude_id:
        q = q.filter(PaymentRequestMaster.id != exclude_id)
    return Decimal(str(q.scalar() or 0)).quantize(_TWO_DP)


def _approved_total(brr_id, exclude_id=None):
    q = db.session.query(func.coalesce(func.sum(PaymentRequestMaster.requested_amount), 0)).filter(
        PaymentRequestMaster.brr_id == brr_id,
        PaymentRequestMaster.workflow_status == "Approved",
    )
    if exclude_id:
        q = q.filter(PaymentRequestMaster.id != exclude_id)
    return Decimal(str(q.scalar() or 0)).quantize(_TWO_DP)


def _brr_summary(brr, exclude_id=None):
    bill      = _bill_amount(brr)
    requested = _requested_total(brr.id, exclude_id)
    brb       = _linked_brb(brr.id)
    return {
        "brrId":              brr.id,
        "brrNo":              brr.brr_no,
        "brrDate":            _fmt_date(brr.brr_date),
        "brrStatus":          brr.workflow_status,
        "vendorId":           brr.vendor_id,
        "partyName":          brr.vendor.ledger_name if brr.vendor else None,
        "orderCategory":      brr.order_category,
        "orderNo":            (brr.order.order_no if brr.order_type == "GRN" and brr.order
                               else brr.pw_order.order_no if brr.pw_order else None),
        "partyBillNo":        brr.party_bill_no,
        "partyDate":          _fmt_date(brr.party_date),
        "brbId":              brb.id if brb else None,
        "brbNo":              brb.brb_no if brb else None,
        "brbStatus":          brb.workflow_status if brb else None,
        "brrTotalAmount":     _f(brr.total_amount),
        "billAmount":         float(bill),
        "billSource":         "BRB" if _approved_brb(brr.id) else "BRR",
        "requestedAmount":    float(requested),                       # other active requests
        "approvedAmount":     float(_approved_total(brr.id, exclude_id)),
        "balanceAmount":      float(bill - requested),
    }


def _validate_amounts(brr, requested, deduction, exclude_id=None):
    """Raise ValueError if amounts are invalid or exceed the BRR balance.
    Returns (bill_amount, previously_requested)."""
    if brr.workflow_status != "Approved":
        raise ValueError(f"BRR {brr.brr_no} is not Approved")
    if requested <= 0:
        raise ValueError("Requested amount must be greater than 0")
    if deduction < 0:
        raise ValueError("Deduction amount cannot be negative")
    if deduction > requested:
        raise ValueError("Deduction amount cannot exceed requested amount")

    bill     = _bill_amount(brr)
    previous = _requested_total(brr.id, exclude_id)
    balance  = bill - previous
    if requested > balance:
        raise ValueError(
            f"Requested amount {requested} exceeds BRR {brr.brr_no} balance {balance} "
            f"(bill {bill}, already requested {previous})"
        )
    return bill, previous


def _payload(pr, with_summary=True):
    data = {
        "id":                  pr.id,
        "uuid":                pr.pr_uuid,
        "prNo":                pr.pr_no,
        "prDate":              _fmt_date(pr.pr_date),
        "projectCode":         pr.project_code,
        "brrId":               pr.brr_id,
        "brrNo":               pr.brr_no,
        "vendorId":            pr.vendor_id,
        "partyName":           pr.vendor.ledger_name if pr.vendor else None,
        "orderCategory":       pr.order_category,
        "partyBillNo":         pr.party_bill_no,
        "partyDate":           _fmt_date(pr.party_date),
        "billAmount":          _f(pr.bill_amount),
        "previouslyRequested": _f(pr.previously_requested),
        "requestedAmount":     _f(pr.requested_amount),
        "deductionAmount":     _f(pr.deduction_amount),
        "deductionRemarks":    pr.deduction_remarks,
        "netPayable":          _f(pr.net_payable),
        "paymentMode":         pr.payment_mode,
        "requiredByDate":      _fmt_date(pr.required_by_date),
        "remarks":             pr.remarks,
        "attachedDoc":         pr.attached_doc,
        "workflowStatus":      pr.workflow_status,
        "currentLevel":        pr.current_level,
        "locked":              pr.locked,
        "createdBy":           pr.creator.username  if pr.creator  else None,
        "createdAt":           _fmt_date(pr.created_at),
        "approvedBy":          pr.approver.username if pr.approver else None,
        "finalApprovedAt":     _fmt_date(pr.final_approved_at),
    }
    if with_summary and pr.brr:
        data["brrSummary"] = _brr_summary(pr.brr, exclude_id=pr.id)
        data["siblingRequests"] = [
            {
                "id":              s.id,
                "prNo":            s.pr_no,
                "prDate":          _fmt_date(s.pr_date),
                "requestedAmount": _f(s.requested_amount),
                "netPayable":      _f(s.net_payable),
                "workflowStatus":  s.workflow_status,
            }
            for s in (
                PaymentRequestMaster.query
                .filter(PaymentRequestMaster.brr_id == pr.brr_id, PaymentRequestMaster.id != pr.id)
                .order_by(PaymentRequestMaster.id.asc())
                .all()
            )
        ]
    return data


def _apply_common_fields(pr, data):
    """Fields shared by create and edit (only keys present in data are applied)."""
    if "paymentMode" in data:
        mode = (data.get("paymentMode") or "").strip() or None
        if mode and mode not in _PAYMENT_MODES:
            raise ValueError("paymentMode must be Bank or Cash")
        pr.payment_mode = mode
    if "requiredByDate" in data:
        pr.required_by_date = parse_date(data.get("requiredByDate"), "requiredByDate")
    if "remarks" in data:
        pr.remarks = data.get("remarks") or None
    if "deductionRemarks" in data:
        pr.deduction_remarks = data.get("deductionRemarks") or None


def _rollback_res(e, code):
    db.session.rollback()
    return res(str(e), [], code)


# ══════════════════════════════════════════════════════════════════
# 1. ELIGIBLE BRRs (approved, balance > 0)
# ══════════════════════════════════════════════════════════════════

def get_eligible_brrs(data):
    try:
        project_code = data.get("projectCode")
        if not project_code:
            return res("projectCode required", [], 400)

        query = BrrMaster.query.filter(
            BrrMaster.project_code    == project_code,
            BrrMaster.workflow_status == "Approved",
        )
        if data.get("vendorId"):
            query = query.filter(BrrMaster.vendor_id == data.get("vendorId"))

        result = []
        for brr in query.order_by(BrrMaster.id.desc()).all():
            summary = _brr_summary(brr)
            if summary["balanceAmount"] > 0:
                result.append(summary)

        return res("Eligible BRRs fetched", result, 200)

    except ValueError as e:
        return _rollback_res(e, 400)
    except Exception as e:
        return _rollback_res(e, 500)


def get_brr_payment_summary(brr_id, exclude_id=None):
    try:
        brr = BrrMaster.query.get(brr_id)
        if not brr:
            return res("BRR not found", [], 404)
        return res("BRR payment summary", _brr_summary(brr, exclude_id), 200)
    except Exception as e:
        return _rollback_res(e, 500)


# ══════════════════════════════════════════════════════════════════
# 2. CREATE
# ══════════════════════════════════════════════════════════════════

def create_payment_request(data, user_id, files=None):
    try:
        project_code = data.get("projectCode")
        if not project_code:
            return res("projectCode required", [], 400)

        if not is_creator(project_code, _MODULE, user_id):
            return res("You are not Payment Request creator", [], 403)

        brr_id = data.get("brrId")
        if not brr_id:
            return res("brrId required", [], 400)

        brr = _lock_brr(brr_id)
        if not brr:
            return res("BRR not found", [], 404)
        if brr.project_code != project_code:
            return res("BRR does not belong to this project", [], 400)

        requested = _dec(data.get("requestedAmount"), "requestedAmount")
        deduction = _dec(data.get("deductionAmount"), "deductionAmount")
        bill, previous = _validate_amounts(brr, requested, deduction)

        pr_no = generate_pr_no()

        pr = PaymentRequestMaster(
            pr_no                = pr_no,
            pr_date              = datetime.utcnow().date(),
            pr_uuid              = str(_uuid_lib.uuid4()),
            project_code         = project_code,
            brr_id               = brr.id,
            brr_no               = brr.brr_no,
            vendor_id            = brr.vendor_id,
            order_category       = brr.order_category,
            party_bill_no        = brr.party_bill_no,
            party_date           = brr.party_date,
            bill_amount          = bill,
            previously_requested = previous,
            requested_amount     = requested,
            deduction_amount     = deduction,
            net_payable          = requested - deduction,
            workflow_status      = "Draft",
            status               = "Active",
            current_level        = 0,
            locked               = False,
            created_by           = user_id,
        )
        _apply_common_fields(pr, data)

        doc_file = files.get("attachedDoc") if files else None
        if doc_file:
            pr.attached_doc = upload_file_to_bunny(
                file       = doc_file,
                mainFolder = "payment_request",
                subFolder  = pr_no,
                fileName   = "attached_doc",
            )

        db.session.add(pr)
        db.session.commit()

        return res(
            "Payment Request created",
            {"id": pr.id, "prNo": pr.pr_no, "attachedDoc": pr.attached_doc},
            201,
        )

    except ValueError as e:
        return _rollback_res(e, 400)
    except SQLAlchemyError as e:
        return _rollback_res(e, 500)
    except Exception as e:
        return _rollback_res(e, 500)


# ══════════════════════════════════════════════════════════════════
# 3. LIST
# ══════════════════════════════════════════════════════════════════

def get_payment_request_list(data):
    try:
        if not data.get("projectCode"):
            return res("projectCode required", [], 400)

        query = PaymentRequestMaster.query.filter(
            PaymentRequestMaster.project_code == data.get("projectCode")
        )
        if data.get("brrId"):
            query = query.filter(PaymentRequestMaster.brr_id == data.get("brrId"))
        if data.get("vendorId"):
            query = query.filter(PaymentRequestMaster.vendor_id == data.get("vendorId"))
        if data.get("workflowStatus"):
            query = query.filter(PaymentRequestMaster.workflow_status == data.get("workflowStatus"))
        if data.get("search"):
            term = f"%{data.get('search')}%"
            query = query.filter(
                db.or_(PaymentRequestMaster.pr_no.ilike(term), PaymentRequestMaster.brr_no.ilike(term))
            )

        rows = query.order_by(PaymentRequestMaster.id.desc()).all()
        return res("Payment Request list fetched", [_payload(r, with_summary=False) for r in rows], 200)

    except ValueError as e:
        return _rollback_res(e, 400)
    except Exception as e:
        return _rollback_res(e, 500)


# ══════════════════════════════════════════════════════════════════
# 4. DETAILS / BY UUID
# ══════════════════════════════════════════════════════════════════

def get_payment_request_details(pr_id):
    try:
        pr = PaymentRequestMaster.query.get(pr_id)
        if not pr:
            return res("Payment Request not found", [], 404)
        if not pr.pr_uuid:
            pr.pr_uuid = str(_uuid_lib.uuid4())
            db.session.commit()
        return res("Payment Request details fetched", _payload(pr), 200)
    except Exception as e:
        return _rollback_res(e, 500)


def get_payment_request_by_uuid(pr_uuid):
    try:
        pr = PaymentRequestMaster.query.filter_by(pr_uuid=pr_uuid).first()
        if not pr:
            return res("Payment Request not found", [], 404)
        data = _payload(pr)
        if pr.vendor:
            data["partyAddress"] = getattr(pr.vendor, "registered_address", None)
            data["partyGstn"]    = getattr(pr.vendor, "gstin", None)
        return res("Payment Request fetched", data, 200)
    except Exception as e:
        return _rollback_res(e, 500)


# ══════════════════════════════════════════════════════════════════
# 5. EDIT  (BRR is fixed once raised — raise a new request for another BRR)
# ══════════════════════════════════════════════════════════════════

def edit_payment_request(pr_id, data, user_id, files=None):
    try:
        pr = PaymentRequestMaster.query.get(pr_id)
        if not pr:
            return res("Payment Request not found", [], 404)
        if pr.locked:
            return res("Payment Request cannot be edited", [], 400)
        if pr.workflow_status not in ["Draft", "Reback"]:
            return res("Only Draft or Reback Payment Request can be edited", [], 400)
        if not is_creator(pr.project_code, _MODULE, user_id):
            return res("You are not Payment Request creator", [], 403)
        if data.get("brrId") and str(data.get("brrId")) != str(pr.brr_id):
            return res("BRR cannot be changed. Raise a new Payment Request for another BRR.", [], 400)

        brr = _lock_brr(pr.brr_id)
        if not brr:
            return res("BRR not found", [], 404)

        requested = (_dec(data.get("requestedAmount"), "requestedAmount")
                     if data.get("requestedAmount") not in (None, "") else Decimal(str(pr.requested_amount or 0)))
        deduction = (_dec(data.get("deductionAmount"), "deductionAmount")
                     if "deductionAmount" in data else Decimal(str(pr.deduction_amount or 0)))
        bill, previous = _validate_amounts(brr, requested, deduction, exclude_id=pr.id)

        pr.bill_amount          = bill
        pr.previously_requested = previous
        pr.requested_amount     = requested
        pr.deduction_amount     = deduction
        pr.net_payable          = requested - deduction
        _apply_common_fields(pr, data)

        doc_file = files.get("attachedDoc") if files else None
        if doc_file:
            if pr.attached_doc:
                delete_file_from_storage(pr.attached_doc)
            pr.attached_doc = upload_file_to_bunny(
                file       = doc_file,
                mainFolder = "payment_request",
                subFolder  = pr.pr_no,
                fileName   = f"attached_doc_{int(_time.time())}",
            )
        elif data.get("clearAttachedDoc") == "true" and pr.attached_doc:
            delete_file_from_storage(pr.attached_doc)
            pr.attached_doc = None

        if pr.workflow_status == "Reback":
            pr.correction_sent_at = None

        pr.updated_by = user_id
        pr.updated_at = datetime.utcnow()
        db.session.commit()

        return res("Payment Request updated", {"id": pr.id, "prNo": pr.pr_no, "attachedDoc": pr.attached_doc}, 200)

    except ValueError as e:
        return _rollback_res(e, 400)
    except SQLAlchemyError as e:
        return _rollback_res(e, 500)
    except Exception as e:
        return _rollback_res(e, 500)


# ══════════════════════════════════════════════════════════════════
# 6. SUBMIT
# ══════════════════════════════════════════════════════════════════

def submit_payment_request(pr_id, submitted_by=None):
    try:
        pr = PaymentRequestMaster.query.get(pr_id)
        if not pr:
            return res("Payment Request not found", [], 404)
        if pr.workflow_status not in ["Draft", "Reback"]:
            return res("Payment Request already submitted", [], 400)
        if not is_creator(pr.project_code, _MODULE, submitted_by):
            return res("You are not Payment Request creator", [], 403)

        brr = _lock_brr(pr.brr_id)
        if not brr:
            return res("BRR not found", [], 404)
        bill, previous = _validate_amounts(
            brr, Decimal(str(pr.requested_amount or 0)), Decimal(str(pr.deduction_amount or 0)), exclude_id=pr.id
        )
        pr.bill_amount          = bill
        pr.previously_requested = previous

        if pr.workflow_status == "Reback":
            pr.current_level = 0

        first_level = get_first_approver(pr.project_code, _MODULE)

        if not first_level:
            pr.workflow_status   = "Approved"
            pr.locked            = True
            pr.approved_by       = submitted_by
            pr.submitted_at      = datetime.utcnow()
            pr.final_approved_at = datetime.utcnow()
        else:
            pr.workflow_status = f"Pending_L{first_level.level_no}"
            pr.current_level   = first_level.level_no
            pr.locked          = True
            pr.submitted_at    = datetime.utcnow()

        create_history(
            project_code = pr.project_code,
            module_code  = _MODULE,
            record_id    = pr.id,
            level_no     = pr.current_level,
            action       = "SUBMIT",
            action_by    = submitted_by,
        )

        pr.submitted_by = submitted_by
        pr.updated_by   = submitted_by
        pr.updated_at   = datetime.utcnow()
        db.session.commit()

        try:
            if first_level:
                submitter = User.query.get(submitted_by)
                wa.on_submit(
                    module_code    = _WA_CODE,
                    doc_no         = pr.pr_no,
                    uuid           = str(pr.id),
                    project_code   = pr.project_code,
                    submitter_name = submitter.username if submitter else str(submitted_by),
                    approver_user  = first_level.user,
                    current_level  = first_level.level_no,
                    record_id      = pr.id,
                )
        except Exception:
            pass

        return res(
            "Payment Request submitted",
            {"id": pr.id, "prNo": pr.pr_no, "workflowStatus": pr.workflow_status},
            200,
        )

    except ValueError as e:
        return _rollback_res(e, 400)
    except SQLAlchemyError as e:
        return _rollback_res(e, 500)
    except Exception as e:
        return _rollback_res(e, 500)


# ══════════════════════════════════════════════════════════════════
# 7. APPROVE
# ══════════════════════════════════════════════════════════════════

def approve_payment_request(pr_id, approved_by=None, comments=None):
    try:
        pr = PaymentRequestMaster.query.get(pr_id)
        if not pr:
            return res("Payment Request not found", [], 404)
        if not (pr.workflow_status or "").startswith("Pending"):
            return res("Payment Request not pending", [], 400)
        if not is_current_approver(pr.project_code, _MODULE, pr.current_level, approved_by):
            return res("You are not current approver", [], 403)

        gap = get_gap_level(pr.project_code, _MODULE, pr.current_level)
        if gap:
            return res(f"L{gap} is not assigned. Please assign it before approving.", [], 400)

        next_level = get_next_approver(pr.project_code, _MODULE, pr.current_level)
        prev_level = pr.current_level

        if next_level:
            create_history(
                project_code = pr.project_code,
                module_code  = _MODULE,
                record_id    = pr.id,
                level_no     = pr.current_level,
                action       = "APPROVE",
                action_by    = approved_by,
                comments     = comments,
            )
            pr.current_level   = next_level.level_no
            pr.workflow_status = f"Pending_L{next_level.level_no}"
        else:
            # Final approval — balance must still hold
            brr = _lock_brr(pr.brr_id)
            if not brr:
                return res("BRR not found", [], 404)
            _validate_amounts(
                brr, Decimal(str(pr.requested_amount or 0)), Decimal(str(pr.deduction_amount or 0)), exclude_id=pr.id
            )
            create_history(
                project_code = pr.project_code,
                module_code  = _MODULE,
                record_id    = pr.id,
                level_no     = pr.current_level,
                action       = "FINAL_APPROVE",
                action_by    = approved_by,
                comments     = comments,
            )
            pr.workflow_status   = "Approved"
            pr.locked            = True
            pr.approved_by       = approved_by
            pr.final_approved_at = datetime.utcnow()

        pr.updated_by = approved_by
        pr.updated_at = datetime.utcnow()
        db.session.commit()

        try:
            approver_user = User.query.get(approved_by)
            approver_name = approver_user.username if approver_user else str(approved_by)
            if next_level:
                wa.on_approve(
                    module_code        = _WA_CODE,
                    doc_no             = pr.pr_no,
                    uuid               = str(pr.id),
                    project_code       = pr.project_code,
                    approver_name      = approver_name,
                    prev_level         = prev_level,
                    next_approver_user = next_level.user,
                    next_level         = next_level.level_no,
                    record_id          = pr.id,
                )
            else:
                wa.on_final_approve(
                    module_code   = _WA_CODE,
                    doc_no        = pr.pr_no,
                    uuid          = str(pr.id),
                    project_code  = pr.project_code,
                    approver_name = approver_name,
                    creator_user  = User.query.get(pr.created_by),
                    record_id     = pr.id,
                )
        except Exception:
            pass

        return res(
            "Payment Request approved",
            {"id": pr.id, "workflowStatus": pr.workflow_status, "currentLevel": pr.current_level},
            200,
        )

    except ValueError as e:
        return _rollback_res(e, 400)
    except SQLAlchemyError as e:
        return _rollback_res(e, 500)
    except Exception as e:
        return _rollback_res(e, 500)


# ══════════════════════════════════════════════════════════════════
# 8. REBACK
# ══════════════════════════════════════════════════════════════════

def reback_payment_request(pr_id, reback_by=None, comments=None):
    try:
        pr = PaymentRequestMaster.query.get(pr_id)
        if not pr:
            return res("Payment Request not found", [], 404)
        if not (pr.workflow_status or "").startswith("Pending"):
            return res("Payment Request not pending", [], 400)
        if not comments:
            return res("Comments required", [], 400)
        if not is_current_approver(pr.project_code, _MODULE, pr.current_level, reback_by):
            return res("You are not current approver", [], 403)

        pr.workflow_status    = "Reback"
        pr.locked             = False
        pr.correction_sent_at = datetime.utcnow()
        pr.updated_by         = reback_by
        pr.updated_at         = datetime.utcnow()

        create_history(
            project_code = pr.project_code,
            module_code  = _MODULE,
            record_id    = pr.id,
            level_no     = pr.current_level,
            action       = "REBACK",
            action_by    = reback_by,
            comments     = comments,
        )
        db.session.commit()

        try:
            reback_user = User.query.get(reback_by)
            wa.on_reback(
                module_code   = _WA_CODE,
                doc_no        = pr.pr_no,
                uuid          = str(pr.id),
                project_code  = pr.project_code,
                approver_name = reback_user.username if reback_user else str(reback_by),
                creator_user  = User.query.get(pr.created_by),
                comments      = comments,
                record_id     = pr.id,
            )
        except Exception:
            pass

        return res("Payment Request sent for correction",
                   {"id": pr.id, "workflowStatus": pr.workflow_status}, 200)

    except ValueError as e:
        return _rollback_res(e, 400)
    except SQLAlchemyError as e:
        return _rollback_res(e, 500)
    except Exception as e:
        return _rollback_res(e, 500)


# ══════════════════════════════════════════════════════════════════
# 9. REJECT  (frees the BRR balance)
# ══════════════════════════════════════════════════════════════════

def reject_payment_request(pr_id, rejected_by=None, comments=None):
    try:
        pr = PaymentRequestMaster.query.get(pr_id)
        if not pr:
            return res("Payment Request not found", [], 404)
        if not (pr.workflow_status or "").startswith("Pending"):
            return res("Payment Request not pending", [], 400)
        if not comments:
            return res("Comments required", [], 400)
        if not is_current_approver(pr.project_code, _MODULE, pr.current_level, rejected_by):
            return res("You are not current approver", [], 403)

        pr.workflow_status = "Rejected"
        pr.locked          = True
        pr.rejected_at     = datetime.utcnow()
        pr.rejected_by     = rejected_by
        pr.status          = "Inactive"
        pr.updated_by      = rejected_by
        pr.updated_at      = datetime.utcnow()

        create_history(
            project_code = pr.project_code,
            module_code  = _MODULE,
            record_id    = pr.id,
            level_no     = pr.current_level,
            action       = "REJECT",
            action_by    = rejected_by,
            comments     = comments,
        )
        db.session.commit()

        try:
            rejected_user = User.query.get(rejected_by)
            wa.on_reject(
                module_code   = _WA_CODE,
                doc_no        = pr.pr_no,
                uuid          = str(pr.id),
                project_code  = pr.project_code,
                approver_name = rejected_user.username if rejected_user else str(rejected_by),
                creator_user  = User.query.get(pr.created_by),
                comments      = comments,
                record_id     = pr.id,
            )
        except Exception:
            pass

        return res("Payment Request rejected",
                   {"id": pr.id, "workflowStatus": pr.workflow_status}, 200)

    except ValueError as e:
        return _rollback_res(e, 400)
    except SQLAlchemyError as e:
        return _rollback_res(e, 500)
    except Exception as e:
        return _rollback_res(e, 500)


# ══════════════════════════════════════════════════════════════════
# 10. HISTORY / MY APPROVAL STATUS
# ══════════════════════════════════════════════════════════════════

def get_payment_request_history(pr_id):
    try:
        pr = PaymentRequestMaster.query.get(pr_id)
        if not pr:
            return res("Payment Request not found", [], 404)

        rows = get_history(_MODULE, pr.id)
        data = [
            {
                "id":        row.id,
                "action":    row.action,
                "level":     row.level_no,
                "comments":  row.comments,
                "actionBy":  row.user.username if row.user else None,
                "createdAt": row.created_at.strftime("%Y-%m-%d %H:%M:%S") if row.created_at else None,
            }
            for row in rows
        ]
        steps = get_approval_steps(pr.project_code, _MODULE, pr, rows)

        return res("Payment Request history fetched", {
            "workflowStatus": pr.workflow_status,
            "currentLevel":   pr.current_level,
            "approvalSteps":  steps,
            "history":        data,
        }, 200)

    except ValueError as e:
        return _rollback_res(e, 400)
    except Exception as e:
        return _rollback_res(e, 500)


def get_payment_request_my_approval_status(pr_id, user_id):
    try:
        pr = PaymentRequestMaster.query.get(pr_id)
        if not pr:
            return res("Payment Request not found", [], 404)
        return res("Approval status", get_my_approval_status(pr.project_code, _MODULE, pr, user_id), 200)
    except ValueError as e:
        return _rollback_res(e, 400)
    except Exception as e:
        return _rollback_res(e, 500)


# ══════════════════════════════════════════════════════════════════
# 11. DELETE (draft only)
# ══════════════════════════════════════════════════════════════════

def delete_payment_request(pr_id):
    try:
        pr = PaymentRequestMaster.query.get(pr_id)
        if not pr:
            return res("Payment Request not found", [], 404)
        if pr.locked or pr.workflow_status not in ["Draft", "Reback"]:
            return res("Only Draft / Reback Payment Request can be deleted", [], 400)
        if pr.attached_doc:
            try:
                delete_file_from_storage(pr.attached_doc)
            except Exception:
                pass
        db.session.delete(pr)
        db.session.commit()
        from app.modules.delete_manager.service import auto_complete_check
        auto_complete_check("PAYMENT_REQUEST", pr_id)
        return res("Payment Request deleted successfully", [], 200)
    except SQLAlchemyError as e:
        return _rollback_res(e, 500)
    except Exception as e:
        return _rollback_res(e, 500)
