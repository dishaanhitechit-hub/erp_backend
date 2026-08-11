from decimal import Decimal
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy import func
from app.extensions import db
from datetime import datetime, date
import uuid as _uuid

from app.models.paymentVoucher  import PaymentVoucherMaster, PaymentVoucherItem, PaymentVoucherGst
from app.models.purchaseVoucher import PurchaseVoucherMaster
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

_MODULE = "payment"


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


def _generate_payment_vouch_no():
    last = (
        db.session.query(PaymentVoucherMaster.payment_vouch_no)
        .order_by(PaymentVoucherMaster.id.desc())
        .with_for_update()
        .first()
    )
    num = 0
    if last and last[0]:
        raw = last[0]
        try:
            num = int(raw[3:]) if raw.startswith("PVE") else int(raw)
        except Exception:
            num = 0
    return f"PVE{str(num + 1).zfill(3)}"


def _paid_basic_map(purchase_voucher_id, exclude_id=None):
    """Sum current_amount per pv_item_id from all Approved payment vouchers for a purchase voucher."""
    q = (
        db.session.query(
            PaymentVoucherItem.pv_item_id,
            func.coalesce(func.sum(PaymentVoucherItem.current_amount), 0).label("paid"),
        )
        .join(PaymentVoucherMaster, PaymentVoucherMaster.id == PaymentVoucherItem.payment_voucher_id)
        .filter(
            PaymentVoucherMaster.purchase_voucher_id == purchase_voucher_id,
            PaymentVoucherMaster.workflow_status     == "Approved",
        )
    )
    if exclude_id:
        q = q.filter(PaymentVoucherMaster.id != exclude_id)
    return {r.pv_item_id: float(r.paid) for r in q.group_by(PaymentVoucherItem.pv_item_id).all()}


def _paid_gst_map(purchase_voucher_id, exclude_id=None):
    """Sum current_amount per gst_type from all Approved payment vouchers for a purchase voucher."""
    q = (
        db.session.query(
            PaymentVoucherGst.gst_type,
            func.coalesce(func.sum(PaymentVoucherGst.current_amount), 0).label("paid"),
        )
        .join(PaymentVoucherMaster, PaymentVoucherMaster.id == PaymentVoucherGst.payment_voucher_id)
        .filter(
            PaymentVoucherMaster.purchase_voucher_id == purchase_voucher_id,
            PaymentVoucherMaster.workflow_status     == "Approved",
        )
    )
    if exclude_id:
        q = q.filter(PaymentVoucherMaster.id != exclude_id)
    return {r.gst_type: float(r.paid) for r in q.group_by(PaymentVoucherGst.gst_type).all()}


def _build_detail_payload(pvm):
    paid_basic = _paid_basic_map(pvm.purchase_voucher_id, exclude_id=pvm.id)
    paid_gst   = _paid_gst_map(pvm.purchase_voucher_id,   exclude_id=pvm.id)

    items = []
    for i in pvm.items:
        booked  = float(i.booked_amount  or 0)
        current = float(i.current_amount or 0)
        paid    = paid_basic.get(i.pv_item_id, 0)
        items.append({
            "id":            i.id,
            "pvItemId":      i.pv_item_id,
            "slNo":          i.sl_no,
            "ccCodeId":      i.cc_code_id,
            "ccCode":        i.cc_code,
            "ccName":        i.cc_name,
            "bookedAmount":  booked,
            "paidAmount":    paid,
            "balanceAmount": max(booked - paid, 0),
            "currentAmount": current,
        })

    gst_lines = []
    for g in pvm.gst_lines:
        booked  = float(g.booked_amount  or 0)
        current = float(g.current_amount or 0)
        paid    = paid_gst.get(g.gst_type, 0)
        gst_lines.append({
            "id":            g.id,
            "gstType":       g.gst_type,
            "ccCode":        g.cc_code,
            "ccName":        g.cc_name,
            "bookedAmount":  booked,
            "paidAmount":    paid,
            "balanceAmount": max(booked - paid, 0),
            "currentAmount": current,
            "isSelected":    g.is_selected,
        })

    pv = pvm.purchase_voucher
    return {
        "id":                  pvm.id,
        "paymentVouchNo":      pvm.payment_vouch_no,
        "paymentVouchUuid":    pvm.payment_vouch_uuid,
        "paymentDate":         _fmt_date(pvm.payment_date),
        "purchaseVoucherId":   pvm.purchase_voucher_id,
        "purchaseVoucherNo":   pv.voucher_no   if pv else None,
        "purchaseVoucherDate": _fmt_date(pv.voucher_date) if pv else None,
        "projectCode":         pvm.project_code,
        "vendorId":            pvm.vendor_id,
        "vendorName":          pvm.vendor.ledger_name if pvm.vendor else None,
        "paymentMode":         pvm.payment_mode,
        "cashAcId":            pvm.cash_ac_id,
        "cashAcName":          pvm.cash_account.bank_holder_name if pvm.cash_account else None,
        "bankAcId":            pvm.bank_ac_id,
        "bankAcName":          pvm.bank_account.bank_holder_name if pvm.bank_account else None,
        "utrVoucherNo":        pvm.utr_voucher_no,
        "paymentRemarks":      pvm.payment_remarks,
        "basicAmount":         float(pvm.basic_amount         or 0),
        "gstAmount":           float(pvm.gst_amount           or 0),
        "discount":            float(pvm.discount             or 0),
        "roundOff":            float(pvm.round_off            or 0),
        "totalInvoiceAmount":  float(pvm.total_invoice_amount or 0),
        "workflowStatus":      pvm.workflow_status,
        "currentLevel":        pvm.current_level,
        "locked":              pvm.locked,
        "createdBy":           pvm.creator.username   if pvm.creator   else None,
        "createdAt":           _fmt_date(pvm.created_at),
        "submittedBy":         pvm.submitter.username if pvm.submitter else None,
        "submittedAt":         _fmt_date(pvm.submitted_at),
        "approvedBy":          pvm.approver.username  if pvm.approver  else None,
        "finalApprovedAt":     _fmt_date(pvm.final_approved_at),
        "rejectedBy":          pvm.rejector.username  if pvm.rejector  else None,
        "rejectedAt":          _fmt_date(pvm.rejected_at),
        "items":               items,
        "gstLines":            gst_lines,
    }


# ══════════════════════════════════════════════════════════════════
# LOOKUP — Approved Purchase Vouchers for dropdown
# ══════════════════════════════════════════════════════════════════

def get_approved_purchase_vouchers(data):
    try:
        project_code = (data.get("projectCode") or "").strip()
        if not project_code:
            return res("projectCode required", [], 400)

        rows = PurchaseVoucherMaster.query.filter(
            PurchaseVoucherMaster.project_code    == project_code,
            PurchaseVoucherMaster.workflow_status == "Approved",
        ).order_by(PurchaseVoucherMaster.id.desc()).all()

        result = [
            {
                "id":              r.id,
                "voucherNo":       r.voucher_no,
                "voucherDate":     _fmt_date(r.voucher_date),
                "vendorId":        r.vendor_id,
                "vendorName":      r.vendor.ledger_name if r.vendor else None,
                "totalInvoiceAmount": float(r.total_invoice_amount or 0),
            }
            for r in rows
        ]

        return res("Approved purchase vouchers fetched", result, 200)

    except Exception as e:
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# LOOKUP — Items + GST of a purchase voucher with paid/balance
# ══════════════════════════════════════════════════════════════════

def get_purchase_voucher_payment_items(pv_id):
    try:
        pv = PurchaseVoucherMaster.query.get(pv_id)
        if not pv:
            return res("Purchase voucher not found", [], 404)

        paid_basic = _paid_basic_map(pv.id)
        paid_gst   = _paid_gst_map(pv.id)

        items = []
        for i in pv.items:
            booked  = float(i.basic_amount or 0)
            paid    = paid_basic.get(i.id, 0)
            balance = max(booked - paid, 0)
            items.append({
                "pvItemId":      i.id,
                "slNo":          i.sl_no,
                "ccCodeId":      i.cc_code_id,
                "ccCode":        i.cc_code_rel.cc_code if i.cc_code_rel else None,
                "ccName":        i.cc_code_rel.cc_name if i.cc_code_rel else None,
                "bookedAmount":  booked,
                "paidAmount":    paid,
                "balanceAmount": balance,
                "currentAmount": 0,
            })

        gst_lines = []
        for g in pv.gst_lines:
            booked  = float(g.gst_amount or 0)
            paid    = paid_gst.get(g.gst_type, 0)
            balance = max(booked - paid, 0)
            gst_lines.append({
                "gstType":       g.gst_type,
                "ccCode":        g.cc_code,
                "ccName":        g.cc_name,
                "bookedAmount":  booked,
                "paidAmount":    paid,
                "balanceAmount": balance,
                "currentAmount": 0,
                "isSelected":    g.is_selected,
            })

        return res("Purchase voucher items fetched", {
            "purchaseVoucherId":      pv.id,
            "purchaseVoucherNo":      pv.voucher_no,
            "purchaseVoucherDate":    _fmt_date(pv.voucher_date),
            "vendorId":               pv.vendor_id,
            "vendorName":             pv.vendor.ledger_name if pv.vendor else None,
            "totalBookedBasic":       float(pv.basic_amount         or 0),
            "totalBookedGst":         float(pv.gst_amount           or 0),
            "totalBookedInvoice":     float(pv.total_invoice_amount or 0),
            "items":                  items,
            "gstLines":               gst_lines,
        }, 200)

    except Exception as e:
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 1. CREATE
# ══════════════════════════════════════════════════════════════════

def create_payment_voucher(data, user_id):
    try:
        project_code = (data.get("projectCode") or "").strip()
        if not project_code:
            return res("projectCode required", [], 400)

        purchase_voucher_id = data.get("purchaseVoucherId")
        if not purchase_voucher_id:
            return res("purchaseVoucherId required", [], 400)

        pv = PurchaseVoucherMaster.query.get(int(purchase_voucher_id))
        if not pv:
            return res("Purchase voucher not found", [], 404)
        if pv.workflow_status != "Approved":
            return res("Only Approved purchase vouchers can be paid", [], 400)

        allowed = is_creator(project_code, _MODULE, user_id)
        if not allowed:
            return res("You are not authorized to create payment vouchers", [], 403)

        items = data.get("items", [])
        if not items:
            return res("At least one BASIC item required", [], 400)

        gst_lines = data.get("gstLines", [])

        basic_total = sum(Decimal(str(i.get("currentAmount") or 0)) for i in items)
        gst_total   = sum(
            Decimal(str(g.get("currentAmount") or 0))
            for g in gst_lines if g.get("isSelected")
        )
        discount  = Decimal(str(data.get("discount")  or 0))
        round_off = Decimal(str(data.get("roundOff")  or 0))
        total     = basic_total + gst_total - discount + round_off

        payment_vouch_no   = _generate_payment_vouch_no()
        payment_vouch_uuid = str(_uuid.uuid4())

        pvm = PaymentVoucherMaster(
            payment_vouch_no   = payment_vouch_no,
            payment_vouch_uuid = payment_vouch_uuid,
            payment_date       = _parse_date(data.get("paymentDate")) or date.today(),
            purchase_voucher_id = int(purchase_voucher_id),
            project_code       = project_code,
            vendor_id          = data.get("vendorId") or pv.vendor_id,
            payment_mode       = data.get("paymentMode"),
            cash_ac_id         = data.get("cashAcId")  or None,
            bank_ac_id         = data.get("bankAcId")  or None,
            utr_voucher_no     = data.get("utrVoucherNo"),
            payment_remarks    = data.get("paymentRemarks"),
            basic_amount         = basic_total,
            gst_amount           = gst_total,
            discount             = discount,
            round_off            = round_off,
            total_invoice_amount = total,
            workflow_status = "Draft",
            current_level   = 0,
            locked          = False,
            created_by      = user_id,
        )
        db.session.add(pvm)
        db.session.flush()

        for idx, row in enumerate(items, start=1):
            db.session.add(PaymentVoucherItem(
                payment_voucher_id = pvm.id,
                pv_item_id         = row.get("pvItemId") or None,
                sl_no              = row.get("slNo") or idx,
                cc_code_id         = row.get("ccCodeId") or None,
                cc_code            = row.get("ccCode"),
                cc_name            = row.get("ccName"),
                booked_amount      = Decimal(str(row.get("bookedAmount") or 0)),
                current_amount     = Decimal(str(row.get("currentAmount") or 0)),
            ))

        for g in gst_lines:
            db.session.add(PaymentVoucherGst(
                payment_voucher_id = pvm.id,
                gst_type           = g.get("gstType"),
                cc_code            = g.get("ccCode"),
                cc_name            = g.get("ccName"),
                booked_amount      = Decimal(str(g.get("bookedAmount") or 0)),
                current_amount     = Decimal(str(g.get("currentAmount") or 0)) if g.get("isSelected") else Decimal("0"),
                is_selected        = bool(g.get("isSelected")),
            ))

        db.session.commit()

        return res("Payment voucher created", {
            "id":               pvm.id,
            "paymentVouchNo":   pvm.payment_vouch_no,
            "paymentVouchUuid": pvm.payment_vouch_uuid,
        }, 201)

    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 2. LIST
# ══════════════════════════════════════════════════════════════════

def get_payment_voucher_list(data):
    try:
        project_code = data.get("projectCode")
        if not project_code:
            return res("projectCode required", [], 400)

        query = PaymentVoucherMaster.query.filter(
            PaymentVoucherMaster.project_code == project_code
        )

        if data.get("workflowStatus"):
            query = query.filter(PaymentVoucherMaster.workflow_status == data.get("workflowStatus"))
        if data.get("vendorId"):
            query = query.filter(PaymentVoucherMaster.vendor_id == int(data.get("vendorId")))
        if data.get("search"):
            term = f"%{data.get('search')}%"
            query = query.filter(
                db.or_(
                    PaymentVoucherMaster.payment_vouch_no.ilike(term),
                    PaymentVoucherMaster.utr_voucher_no.ilike(term),
                )
            )

        rows = query.order_by(PaymentVoucherMaster.id.desc()).all()

        result = [
            {
                "id":                 r.id,
                "paymentVouchNo":     r.payment_vouch_no,
                "paymentDate":        _fmt_date(r.payment_date),
                "purchaseVoucherId":  r.purchase_voucher_id,
                "purchaseVoucherNo":  r.purchase_voucher.voucher_no if r.purchase_voucher else None,
                "vendorId":           r.vendor_id,
                "vendorName":         r.vendor.ledger_name if r.vendor else None,
                "paymentMode":        r.payment_mode,
                "utrVoucherNo":       r.utr_voucher_no,
                "basicAmount":        float(r.basic_amount         or 0),
                "gstAmount":          float(r.gst_amount           or 0),
                "totalInvoiceAmount": float(r.total_invoice_amount or 0),
                "workflowStatus":     r.workflow_status,
                "createdBy":          r.creator.username if r.creator else None,
                "createdAt":          _fmt_date(r.created_at),
            }
            for r in rows
        ]

        return res("Payment voucher list fetched", result, 200)

    except Exception as e:
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 3. DETAILS
# ══════════════════════════════════════════════════════════════════

def get_payment_voucher_details(pvm_id):
    try:
        pvm = PaymentVoucherMaster.query.get(pvm_id)
        if not pvm:
            return res("Payment voucher not found", [], 404)
        return res("Payment voucher details fetched", _build_detail_payload(pvm), 200)
    except Exception as e:
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 4. UUID LOOKUP
# ══════════════════════════════════════════════════════════════════

def get_payment_voucher_by_uuid(voucher_uuid):
    try:
        pvm = PaymentVoucherMaster.query.filter_by(payment_vouch_uuid=voucher_uuid).first()
        if not pvm:
            return res("Payment voucher not found", [], 404)
        return res("Payment voucher details fetched", _build_detail_payload(pvm), 200)
    except Exception as e:
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 5. EDIT
# ══════════════════════════════════════════════════════════════════

def edit_payment_voucher(pvm_id, data, user_id):
    try:
        pvm = PaymentVoucherMaster.query.get(pvm_id)
        if not pvm:
            return res("Payment voucher not found", [], 404)
        if pvm.locked:
            return res("Payment voucher is locked and cannot be edited", [], 400)
        if pvm.workflow_status not in ("Draft", "Reback"):
            return res("Only Draft or Reback records can be edited", [], 400)

        allowed = is_creator(pvm.project_code, _MODULE, user_id)
        if not allowed:
            return res("You are not authorized to edit payment vouchers", [], 403)

        items = data.get("items", [])
        if not items:
            return res("At least one BASIC item required", [], 400)

        gst_lines = data.get("gstLines", [])

        for key, attr in [
            ("paymentDate",    "payment_date"),
            ("paymentMode",    "payment_mode"),
            ("cashAcId",       "cash_ac_id"),
            ("bankAcId",       "bank_ac_id"),
            ("utrVoucherNo",   "utr_voucher_no"),
            ("paymentRemarks", "payment_remarks"),
        ]:
            if data.get(key) is not None:
                val = _parse_date(data[key]) if attr == "payment_date" else (data[key] or None)
                setattr(pvm, attr, val)

        PaymentVoucherItem.query.filter_by(payment_voucher_id=pvm.id).delete()
        PaymentVoucherGst.query.filter_by(payment_voucher_id=pvm.id).delete()
        db.session.flush()

        basic_total = sum(Decimal(str(i.get("currentAmount") or 0)) for i in items)
        gst_total   = sum(
            Decimal(str(g.get("currentAmount") or 0))
            for g in gst_lines if g.get("isSelected")
        )
        discount  = Decimal(str(data.get("discount")  or 0))
        round_off = Decimal(str(data.get("roundOff")  or 0))

        for idx, row in enumerate(items, start=1):
            db.session.add(PaymentVoucherItem(
                payment_voucher_id = pvm.id,
                pv_item_id         = row.get("pvItemId") or None,
                sl_no              = row.get("slNo") or idx,
                cc_code_id         = row.get("ccCodeId") or None,
                cc_code            = row.get("ccCode"),
                cc_name            = row.get("ccName"),
                booked_amount      = Decimal(str(row.get("bookedAmount") or 0)),
                current_amount     = Decimal(str(row.get("currentAmount") or 0)),
            ))

        for g in gst_lines:
            db.session.add(PaymentVoucherGst(
                payment_voucher_id = pvm.id,
                gst_type           = g.get("gstType"),
                cc_code            = g.get("ccCode"),
                cc_name            = g.get("ccName"),
                booked_amount      = Decimal(str(g.get("bookedAmount") or 0)),
                current_amount     = Decimal(str(g.get("currentAmount") or 0)) if g.get("isSelected") else Decimal("0"),
                is_selected        = bool(g.get("isSelected")),
            ))

        pvm.basic_amount         = basic_total
        pvm.gst_amount           = gst_total
        pvm.discount             = discount
        pvm.round_off            = round_off
        pvm.total_invoice_amount = basic_total + gst_total - discount + round_off

        if pvm.workflow_status == "Reback":
            pvm.correction_sent_at = None

        pvm.updated_by = user_id
        pvm.updated_at = datetime.utcnow()

        db.session.commit()

        return res("Payment voucher updated", {
            "id":             pvm.id,
            "paymentVouchNo": pvm.payment_vouch_no,
        }, 200)

    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 6. SUBMIT
# ══════════════════════════════════════════════════════════════════

def submit_payment_voucher(pvm_id, user_id):
    try:
        pvm = PaymentVoucherMaster.query.get(pvm_id)
        if not pvm:
            return res("Payment voucher not found", [], 404)
        if pvm.workflow_status not in ("Draft", "Reback"):
            return res("Payment voucher already submitted", [], 400)
        if not pvm.items:
            return res("Payment voucher has no items", [], 400)

        if pvm.workflow_status == "Reback":
            pvm.current_level = 0

        first_level = get_first_approver(pvm.project_code, _MODULE)

        if not first_level:
            pvm.workflow_status   = "Approved"
            pvm.locked            = True
            pvm.approved_by       = user_id
            pvm.submitted_at      = datetime.utcnow()
            pvm.final_approved_at = datetime.utcnow()
        else:
            pvm.workflow_status = f"Pending_L{first_level.level_no}"
            pvm.current_level   = first_level.level_no
            pvm.locked          = True
            pvm.submitted_at    = datetime.utcnow()

        create_history(
            project_code = pvm.project_code,
            module_code  = _MODULE,
            record_id    = pvm.id,
            level_no     = pvm.current_level,
            action       = "SUBMIT",
            action_by    = user_id,
        )

        pvm.submitted_by = user_id
        pvm.updated_by   = user_id
        pvm.updated_at   = datetime.utcnow()

        db.session.commit()

        return res("Payment voucher submitted", {
            "id":             pvm.id,
            "workflowStatus": pvm.workflow_status,
        }, 200)

    except SQLAlchemyError as e:
        db.session.rollback()
        return res(str(e), [], 500)
    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 7. APPROVE
# ══════════════════════════════════════════════════════════════════

def approve_payment_voucher(pvm_id, approved_by, comments=None):
    try:
        pvm = PaymentVoucherMaster.query.get(pvm_id)
        if not pvm:
            return res("Payment voucher not found", [], 404)
        if not pvm.workflow_status.startswith("Pending"):
            return res("Payment voucher is not pending approval", [], 400)

        allowed = is_current_approver(pvm.project_code, _MODULE, pvm.current_level, approved_by)
        if not allowed:
            return res("You are not the current approver", [], 403)

        gap = get_gap_level(pvm.project_code, _MODULE, pvm.current_level)
        if gap:
            return res(f"L{gap} is not assigned. Please assign it before approving.", [], 400)

        next_level = get_next_approver(pvm.project_code, _MODULE, pvm.current_level)

        if next_level:
            create_history(
                project_code=pvm.project_code, module_code=_MODULE,
                record_id=pvm.id, level_no=pvm.current_level,
                action="APPROVE", action_by=approved_by, comments=comments,
            )
            pvm.current_level   = next_level.level_no
            pvm.workflow_status = f"Pending_L{next_level.level_no}"
        else:
            create_history(
                project_code=pvm.project_code, module_code=_MODULE,
                record_id=pvm.id, level_no=pvm.current_level,
                action="FINAL_APPROVE", action_by=approved_by, comments=comments,
            )
            pvm.workflow_status   = "Approved"
            pvm.locked            = True
            pvm.approved_by       = approved_by
            pvm.final_approved_at = datetime.utcnow()

        pvm.updated_by = approved_by
        pvm.updated_at = datetime.utcnow()

        db.session.commit()

        return res("Payment voucher approved", {
            "id":             pvm.id,
            "workflowStatus": pvm.workflow_status,
        }, 200)

    except SQLAlchemyError as e:
        db.session.rollback()
        return res(str(e), [], 500)
    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 8. REBACK
# ══════════════════════════════════════════════════════════════════

def reback_payment_voucher(pvm_id, reback_by, comments=None):
    try:
        pvm = PaymentVoucherMaster.query.get(pvm_id)
        if not pvm:
            return res("Payment voucher not found", [], 404)
        if not pvm.workflow_status.startswith("Pending"):
            return res("Payment voucher is not pending", [], 400)
        if not comments:
            return res("Comments required for reback", [], 400)

        allowed = is_current_approver(pvm.project_code, _MODULE, pvm.current_level, reback_by)
        if not allowed:
            return res("You are not the current approver", [], 403)

        pvm.workflow_status    = "Reback"
        pvm.locked             = False
        pvm.correction_sent_at = datetime.utcnow()
        pvm.updated_by         = reback_by
        pvm.updated_at         = datetime.utcnow()

        create_history(
            project_code=pvm.project_code, module_code=_MODULE,
            record_id=pvm.id, level_no=pvm.current_level,
            action="REBACK", action_by=reback_by, comments=comments,
        )

        db.session.commit()

        return res("Payment voucher sent for correction", {
            "id":             pvm.id,
            "workflowStatus": pvm.workflow_status,
        }, 200)

    except SQLAlchemyError as e:
        db.session.rollback()
        return res(str(e), [], 500)
    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 9. REJECT
# ══════════════════════════════════════════════════════════════════

def reject_payment_voucher(pvm_id, rejected_by, comments=None):
    try:
        pvm = PaymentVoucherMaster.query.get(pvm_id)
        if not pvm:
            return res("Payment voucher not found", [], 404)
        if not pvm.workflow_status.startswith("Pending"):
            return res("Payment voucher is not pending", [], 400)
        if not comments:
            return res("Comments required for rejection", [], 400)

        allowed = is_current_approver(pvm.project_code, _MODULE, pvm.current_level, rejected_by)
        if not allowed:
            return res("You are not the current approver", [], 403)

        pvm.workflow_status = "Rejected"
        pvm.locked          = True
        pvm.rejected_at     = datetime.utcnow()
        pvm.rejected_by     = rejected_by
        pvm.status          = "Inactive"
        pvm.updated_by      = rejected_by
        pvm.updated_at      = datetime.utcnow()

        create_history(
            project_code=pvm.project_code, module_code=_MODULE,
            record_id=pvm.id, level_no=pvm.current_level,
            action="REJECT", action_by=rejected_by, comments=comments,
        )

        db.session.commit()

        return res("Payment voucher rejected", {
            "id":             pvm.id,
            "workflowStatus": pvm.workflow_status,
        }, 200)

    except SQLAlchemyError as e:
        db.session.rollback()
        return res(str(e), [], 500)
    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 10. HISTORY
# ══════════════════════════════════════════════════════════════════

def get_payment_voucher_history(pvm_id):
    try:
        pvm = PaymentVoucherMaster.query.get(pvm_id)
        if not pvm:
            return res("Payment voucher not found", [], 404)

        rows = get_history(_MODULE, pvm.id)

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

        steps = get_approval_steps(pvm.project_code, _MODULE, pvm, rows)

        return res("History fetched", {
            "workflowStatus": pvm.workflow_status,
            "currentLevel":   pvm.current_level,
            "approvalSteps":  steps,
            "history":        history,
        }, 200)

    except Exception as e:
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 11. MY APPROVAL STATUS
# ══════════════════════════════════════════════════════════════════

def get_payment_voucher_my_approval_status(pvm_id, user_id):
    try:
        pvm = PaymentVoucherMaster.query.get(pvm_id)
        if not pvm:
            return res("Payment voucher not found", [], 404)
        data = get_my_approval_status(pvm.project_code, _MODULE, pvm, user_id)
        return res("Approval status", data, 200)
    except Exception as e:
        return res(str(e), [], 500)
