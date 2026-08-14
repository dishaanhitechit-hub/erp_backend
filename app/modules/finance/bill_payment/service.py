from decimal import Decimal
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy import func
from app.extensions import db
from datetime import datetime, date
import uuid as _uuid

from app.models.billPaymentReceipt import (
    BillPaymentReceiptMaster,
    BillPaymentReceiptItem,
    BillPaymentReceiptGst,
)
from app.models.purchaseBill import PurchaseBillMaster
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


def _generate_receipt_no():
    last = (
        db.session.query(BillPaymentReceiptMaster.receipt_no)
        .order_by(BillPaymentReceiptMaster.id.desc())
        .with_for_update()
        .first()
    )
    num = 0
    if last and last[0]:
        raw = last[0]
        try:
            num = int(raw[3:]) if raw.startswith("BPR") else int(raw)
        except Exception:
            num = 0
    return f"BPR{str(num + 1).zfill(3)}"


def _paid_item_map(purchase_bill_id, exclude_id=None):
    """Sum current_amount per pb_item_id from all Approved receipts for a purchase bill."""
    q = (
        db.session.query(
            BillPaymentReceiptItem.pb_item_id,
            func.coalesce(func.sum(BillPaymentReceiptItem.current_amount), 0).label("paid"),
        )
        .join(BillPaymentReceiptMaster, BillPaymentReceiptMaster.id == BillPaymentReceiptItem.receipt_id)
        .filter(
            BillPaymentReceiptMaster.purchase_bill_id  == purchase_bill_id,
            BillPaymentReceiptMaster.workflow_status   == "Approved",
        )
    )
    if exclude_id:
        q = q.filter(BillPaymentReceiptMaster.id != exclude_id)
    return {r.pb_item_id: float(r.paid) for r in q.group_by(BillPaymentReceiptItem.pb_item_id).all()}


def _paid_gst_map(purchase_bill_id, exclude_id=None):
    """Sum current_amount per gst_type from all Approved receipts for a purchase bill."""
    q = (
        db.session.query(
            BillPaymentReceiptGst.gst_type,
            func.coalesce(func.sum(BillPaymentReceiptGst.current_amount), 0).label("paid"),
        )
        .join(BillPaymentReceiptMaster, BillPaymentReceiptMaster.id == BillPaymentReceiptGst.receipt_id)
        .filter(
            BillPaymentReceiptMaster.purchase_bill_id == purchase_bill_id,
            BillPaymentReceiptMaster.workflow_status  == "Approved",
        )
    )
    if exclude_id:
        q = q.filter(BillPaymentReceiptMaster.id != exclude_id)
    return {r.gst_type: float(r.paid) for r in q.group_by(BillPaymentReceiptGst.gst_type).all()}


def _build_detail_payload(r):
    paid_basic = _paid_item_map(r.purchase_bill_id, exclude_id=r.id)
    paid_gst   = _paid_gst_map(r.purchase_bill_id,  exclude_id=r.id)

    items = []
    for i in r.items:
        booked  = float(i.booked_amount  or 0)
        current = float(i.current_amount or 0)
        paid    = paid_basic.get(i.pb_item_id, 0)
        items.append({
            "id":            i.id,
            "pbItemId":      i.pb_item_id,
            "slNo":          i.sl_no,
            "ccCode":        i.cc_code,
            "ccName":        i.cc_name,
            "bookedAmount":  booked,
            "paidAmount":    paid,
            "balanceAmount": max(booked - paid, 0),
            "currentAmount": current,
        })

    gst_lines = []
    for g in r.gst_lines:
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

    bill = r.purchase_bill
    return {
        "id":                  r.id,
        "receiptNo":           r.receipt_no,
        "receiptUuid":         r.receipt_uuid,
        "paymentDate":         _fmt_date(r.payment_date),
        "purchaseBillId":      r.purchase_bill_id,
        "purchaseBillNo":      bill.purchase_bill_no if bill else None,
        "bvsDate":             _fmt_date(r.bvs_date),
        "vendorBillNo":        r.vendor_bill_no,
        "vendorBillDate":      _fmt_date(r.vendor_bill_date),
        "orderNo":             r.order_no,
        "projectCode":         r.project_code,
        "vendorId":            r.vendor_id,
        "vendorName":          r.vendor.ledger_name if r.vendor else None,
        "paymentMode":         r.payment_mode,
        "cashAcId":            r.cash_ac_id,
        "cashAcName":          r.cash_account.bank_holder_name if r.cash_account else None,
        "bankAcId":            r.bank_ac_id,
        "bankAcName":          r.bank_account.bank_holder_name if r.bank_account else None,
        "utrVoucherNo":        r.utr_voucher_no,
        "paymentRemarks":      r.payment_remarks,
        "basicAmount":         float(r.basic_amount         or 0),
        "gstAmount":           float(r.gst_amount           or 0),
        "discount":            float(r.discount             or 0),
        "roundOff":            float(r.round_off            or 0),
        "totalInvoiceAmount":  float(r.total_invoice_amount or 0),
        "workflowStatus":      r.workflow_status,
        "currentLevel":        r.current_level,
        "locked":              r.locked,
        "createdBy":           r.creator.username   if r.creator   else None,
        "createdAt":           _fmt_date(r.created_at),
        "submittedBy":         r.submitter.username if r.submitter else None,
        "submittedAt":         _fmt_date(r.submitted_at),
        "approvedBy":          r.approver.username  if r.approver  else None,
        "finalApprovedAt":     _fmt_date(r.final_approved_at),
        "rejectedBy":          r.rejector.username  if r.rejector  else None,
        "rejectedAt":          _fmt_date(r.rejected_at),
        "items":               items,
        "gstLines":            gst_lines,
    }


# ══════════════════════════════════════════════════════════════════
# LOOKUP — Approved Purchase Bills for BVS dropdown
# ══════════════════════════════════════════════════════════════════

def get_approved_purchase_bills(data):
    try:
        project_code = (data.get("projectCode") or "").strip()
        if not project_code:
            return res("projectCode required", [], 400)

        query = PurchaseBillMaster.query.filter(
            PurchaseBillMaster.project_code    == project_code,
            PurchaseBillMaster.workflow_status == "Approved",
        )

        if data.get("vendorId"):
            query = query.filter(PurchaseBillMaster.vendor_id == int(data.get("vendorId")))

        rows = query.order_by(PurchaseBillMaster.id.desc()).all()

        result = [
            {
                "id":                 r.id,
                "purchaseBillNo":     r.purchase_bill_no,
                "processingDate":     _fmt_date(r.processing_date),
                "vendorId":           r.vendor_id,
                "vendorName":         r.vendor.ledger_name if r.vendor else None,
                "brrNo":              r.brr_no,
                "brrDate":            _fmt_date(r.brr_date),
                "vendorBillNo":       r.vendor_bill_no,
                "vendorBillDate":     _fmt_date(r.vendor_bill_date),
                "orderNo":            (r.order.order_no if r.order else None) or (r.pw_order.order_no if r.pw_order else None),
                "totalInvoiceAmount": float(r.total_invoice_amount or 0),
            }
            for r in rows
        ]

        return res("Approved purchase bills fetched", result, 200)

    except Exception as e:
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# LOOKUP — Items + GST of a purchase bill with paid/balance
# ══════════════════════════════════════════════════════════════════

def get_purchase_bill_payment_items(bill_id):
    try:
        bill = PurchaseBillMaster.query.get(bill_id)
        if not bill:
            return res("Purchase bill not found", [], 404)
        if bill.workflow_status != "Approved":
            return res("Only Approved purchase bills can be paid", [], 400)

        paid_basic = _paid_item_map(bill.id)
        paid_gst   = _paid_gst_map(bill.id)

        items = []
        for i in bill.items:
            booked  = float(i.basic_amount or 0)
            paid    = paid_basic.get(i.id, 0)
            balance = max(booked - paid, 0)
            items.append({
                "pbItemId":      i.id,
                "slNo":          i.sl_no,
                "ccCode":        i.cc_code,
                "ccName":        i.cc_name,
                "bookedAmount":  booked,
                "paidAmount":    paid,
                "balanceAmount": balance,
                "currentAmount": 0,
            })

        gst_lines = []
        for g in bill.gst_lines:
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

        order_no = (bill.order.order_no if bill.order else None) or (bill.pw_order.order_no if bill.pw_order else None)

        return res("Purchase bill payment items fetched", {
            "purchaseBillId":      bill.id,
            "purchaseBillNo":      bill.purchase_bill_no,
            "bvsDate":             _fmt_date(bill.processing_date),
            "vendorBillNo":        bill.vendor_bill_no,
            "vendorBillDate":      _fmt_date(bill.vendor_bill_date),
            "orderNo":             order_no,
            "vendorId":            bill.vendor_id,
            "vendorName":          bill.vendor.ledger_name if bill.vendor else None,
            "totalBookedBasic":    float(bill.basic_amount         or 0),
            "totalBookedGst":      float(bill.gst_amount           or 0),
            "totalBookedInvoice":  float(bill.total_invoice_amount or 0),
            "items":               items,
            "gstLines":            gst_lines,
        }, 200)

    except Exception as e:
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 1. CREATE
# ══════════════════════════════════════════════════════════════════

def create_bill_payment_receipt(data, user_id):
    try:
        project_code = (data.get("projectCode") or "").strip()
        if not project_code:
            return res("projectCode required", [], 400)

        purchase_bill_id = data.get("purchaseBillId")
        if not purchase_bill_id:
            return res("purchaseBillId required", [], 400)

        bill = PurchaseBillMaster.query.get(int(purchase_bill_id))
        if not bill:
            return res("Purchase bill not found", [], 404)
        if bill.workflow_status != "Approved":
            return res("Only Approved purchase bills can be paid", [], 400)

        allowed = is_creator(project_code, _MODULE, user_id)
        if not allowed:
            return res("You are not authorized to create bill payment receipts", [], 403)

        items = data.get("items", [])
        if not items:
            return res("At least one BASIC item required", [], 400)

        gst_lines = data.get("gstLines", [])

        basic_total = sum(Decimal(str(i.get("currentAmount") or 0)) for i in items)
        pct_map   = {bg.gst_type: Decimal(str(bg.percent or 0)) for bg in bill.gst_lines}
        gst_total = sum(
            (basic_total * pct_map.get(g.get("gstType"), Decimal("0")) / 100).quantize(Decimal("0.01"))
            for g in gst_lines if g.get("isSelected")
        )
        discount  = Decimal(str(data.get("discount")  or 0))
        round_off = Decimal(str(data.get("roundOff")  or 0))
        total     = basic_total + gst_total - discount + round_off

        order_no = (bill.order.order_no if bill.order else None) or (bill.pw_order.order_no if bill.pw_order else None)

        r = BillPaymentReceiptMaster(
            receipt_no       = _generate_receipt_no(),
            receipt_uuid     = str(_uuid.uuid4()),
            payment_date     = _parse_date(data.get("paymentDate")) or date.today(),
            purchase_bill_id = int(purchase_bill_id),
            bvs_date         = bill.processing_date,
            vendor_bill_no   = bill.vendor_bill_no,
            vendor_bill_date = bill.vendor_bill_date,
            order_no         = order_no,
            project_code     = project_code,
            vendor_id        = data.get("vendorId") or bill.vendor_id,
            payment_mode     = data.get("paymentMode"),
            cash_ac_id       = data.get("cashAcId")  or None,
            bank_ac_id       = data.get("bankAcId")  or None,
            utr_voucher_no   = data.get("utrVoucherNo"),
            payment_remarks  = data.get("paymentRemarks"),
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
        db.session.add(r)
        db.session.flush()

        for idx, row in enumerate(items, start=1):
            db.session.add(BillPaymentReceiptItem(
                receipt_id     = r.id,
                pb_item_id     = row.get("pbItemId") or None,
                sl_no          = row.get("slNo") or idx,
                cc_code        = row.get("ccCode"),
                cc_name        = row.get("ccName"),
                booked_amount  = Decimal(str(row.get("bookedAmount")  or 0)),
                current_amount = Decimal(str(row.get("currentAmount") or 0)),
            ))

        for g in gst_lines:
            db.session.add(BillPaymentReceiptGst(
                receipt_id     = r.id,
                gst_type       = g.get("gstType"),
                cc_code        = g.get("ccCode"),
                cc_name        = g.get("ccName"),
                booked_amount  = Decimal(str(g.get("bookedAmount")  or 0)),
                current_amount = (basic_total * pct_map.get(g.get("gstType"), Decimal("0")) / 100).quantize(Decimal("0.01")) if g.get("isSelected") else Decimal("0"),
                is_selected    = bool(g.get("isSelected")),
            ))

        db.session.commit()

        return res("Bill payment receipt created", {
            "id":          r.id,
            "receiptNo":   r.receipt_no,
            "receiptUuid": r.receipt_uuid,
        }, 201)

    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 2. LIST
# ══════════════════════════════════════════════════════════════════

def get_bill_payment_list(data):
    try:
        project_code = data.get("projectCode")
        if not project_code:
            return res("projectCode required", [], 400)

        query = BillPaymentReceiptMaster.query.filter(
            BillPaymentReceiptMaster.project_code == project_code
        )

        if data.get("workflowStatus"):
            query = query.filter(BillPaymentReceiptMaster.workflow_status == data.get("workflowStatus"))
        if data.get("vendorId"):
            query = query.filter(BillPaymentReceiptMaster.vendor_id == int(data.get("vendorId")))
        if data.get("search"):
            term = f"%{data.get('search')}%"
            query = query.filter(
                db.or_(
                    BillPaymentReceiptMaster.receipt_no.ilike(term),
                    BillPaymentReceiptMaster.utr_voucher_no.ilike(term),
                    BillPaymentReceiptMaster.vendor_bill_no.ilike(term),
                )
            )

        rows = query.order_by(BillPaymentReceiptMaster.id.desc()).all()

        result = [
            {
                "id":                 r.id,
                "receiptNo":          r.receipt_no,
                "paymentDate":        _fmt_date(r.payment_date),
                "purchaseBillId":     r.purchase_bill_id,
                "purchaseBillNo":     r.purchase_bill.purchase_bill_no if r.purchase_bill else None,
                "bvsDate":            _fmt_date(r.bvs_date),
                "vendorBillNo":       r.vendor_bill_no,
                "orderNo":            r.order_no,
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

        return res("Bill payment list fetched", result, 200)

    except Exception as e:
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 3. DETAILS
# ══════════════════════════════════════════════════════════════════

def get_bill_payment_details(receipt_id):
    try:
        r = BillPaymentReceiptMaster.query.get(receipt_id)
        if not r:
            return res("Bill payment receipt not found", [], 404)
        return res("Bill payment details fetched", _build_detail_payload(r), 200)
    except Exception as e:
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 4. UUID LOOKUP
# ══════════════════════════════════════════════════════════════════

def get_bill_payment_by_uuid(receipt_uuid):
    try:
        r = BillPaymentReceiptMaster.query.filter_by(receipt_uuid=receipt_uuid).first()
        if not r:
            return res("Bill payment receipt not found", [], 404)
        return res("Bill payment details fetched", _build_detail_payload(r), 200)
    except Exception as e:
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 5. EDIT
# ══════════════════════════════════════════════════════════════════

def edit_bill_payment_receipt(receipt_id, data, user_id):
    try:
        r = BillPaymentReceiptMaster.query.get(receipt_id)
        if not r:
            return res("Bill payment receipt not found", [], 404)
        if r.locked:
            return res("Bill payment receipt is locked and cannot be edited", [], 400)
        if r.workflow_status not in ("Draft", "Reback"):
            return res("Only Draft or Reback records can be edited", [], 400)

        allowed = is_creator(r.project_code, _MODULE, user_id)
        if not allowed:
            return res("You are not authorized to edit bill payment receipts", [], 403)

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
                setattr(r, attr, val)

        BillPaymentReceiptItem.query.filter_by(receipt_id=r.id).delete()
        BillPaymentReceiptGst.query.filter_by(receipt_id=r.id).delete()
        db.session.flush()

        basic_total = sum(Decimal(str(i.get("currentAmount") or 0)) for i in items)
        bill_ref  = PurchaseBillMaster.query.get(r.purchase_bill_id)
        pct_map   = {bg.gst_type: Decimal(str(bg.percent or 0)) for bg in (bill_ref.gst_lines if bill_ref else [])}
        gst_total = sum(
            (basic_total * pct_map.get(g.get("gstType"), Decimal("0")) / 100).quantize(Decimal("0.01"))
            for g in gst_lines if g.get("isSelected")
        )
        discount  = Decimal(str(data.get("discount")  or 0))
        round_off = Decimal(str(data.get("roundOff")  or 0))

        for idx, row in enumerate(items, start=1):
            db.session.add(BillPaymentReceiptItem(
                receipt_id     = r.id,
                pb_item_id     = row.get("pbItemId") or None,
                sl_no          = row.get("slNo") or idx,
                cc_code        = row.get("ccCode"),
                cc_name        = row.get("ccName"),
                booked_amount  = Decimal(str(row.get("bookedAmount")  or 0)),
                current_amount = Decimal(str(row.get("currentAmount") or 0)),
            ))

        for g in gst_lines:
            db.session.add(BillPaymentReceiptGst(
                receipt_id     = r.id,
                gst_type       = g.get("gstType"),
                cc_code        = g.get("ccCode"),
                cc_name        = g.get("ccName"),
                booked_amount  = Decimal(str(g.get("bookedAmount")  or 0)),
                current_amount = (basic_total * pct_map.get(g.get("gstType"), Decimal("0")) / 100).quantize(Decimal("0.01")) if g.get("isSelected") else Decimal("0"),
                is_selected    = bool(g.get("isSelected")),
            ))

        r.basic_amount         = basic_total
        r.gst_amount           = gst_total
        r.discount             = discount
        r.round_off            = round_off
        r.total_invoice_amount = basic_total + gst_total - discount + round_off

        if r.workflow_status == "Reback":
            r.correction_sent_at = None

        r.updated_by = user_id
        r.updated_at = datetime.utcnow()

        db.session.commit()

        return res("Bill payment receipt updated", {"id": r.id, "receiptNo": r.receipt_no}, 200)

    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 6. SUBMIT
# ══════════════════════════════════════════════════════════════════

def submit_bill_payment(receipt_id, user_id):
    try:
        r = BillPaymentReceiptMaster.query.get(receipt_id)
        if not r:
            return res("Bill payment receipt not found", [], 404)
        if r.workflow_status not in ("Draft", "Reback"):
            return res("Bill payment receipt already submitted", [], 400)
        if not r.items:
            return res("Bill payment receipt has no items", [], 400)

        if r.workflow_status == "Reback":
            r.current_level = 0

        first_level = get_first_approver(r.project_code, _MODULE)

        if not first_level:
            r.workflow_status   = "Approved"
            r.locked            = True
            r.approved_by       = user_id
            r.submitted_at      = datetime.utcnow()
            r.final_approved_at = datetime.utcnow()
        else:
            r.workflow_status = f"Pending_L{first_level.level_no}"
            r.current_level   = first_level.level_no
            r.locked          = True
            r.submitted_at    = datetime.utcnow()

        create_history(
            project_code = r.project_code,
            module_code  = _MODULE,
            record_id    = r.id,
            level_no     = r.current_level,
            action       = "SUBMIT",
            action_by    = user_id,
        )

        r.submitted_by = user_id
        r.updated_by   = user_id
        r.updated_at   = datetime.utcnow()

        db.session.commit()

        return res("Bill payment receipt submitted", {"id": r.id, "workflowStatus": r.workflow_status}, 200)

    except SQLAlchemyError as e:
        db.session.rollback()
        return res(str(e), [], 500)
    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 7. APPROVE
# ══════════════════════════════════════════════════════════════════

def approve_bill_payment(receipt_id, approved_by, comments=None):
    try:
        r = BillPaymentReceiptMaster.query.get(receipt_id)
        if not r:
            return res("Bill payment receipt not found", [], 404)
        if not r.workflow_status.startswith("Pending"):
            return res("Bill payment receipt is not pending approval", [], 400)

        allowed = is_current_approver(r.project_code, _MODULE, r.current_level, approved_by)
        if not allowed:
            return res("You are not the current approver", [], 403)

        gap = get_gap_level(r.project_code, _MODULE, r.current_level)
        if gap:
            return res(f"L{gap} is not assigned. Please assign it before approving.", [], 400)

        next_level = get_next_approver(r.project_code, _MODULE, r.current_level)

        if next_level:
            create_history(
                project_code=r.project_code, module_code=_MODULE,
                record_id=r.id, level_no=r.current_level,
                action="APPROVE", action_by=approved_by, comments=comments,
            )
            r.current_level   = next_level.level_no
            r.workflow_status = f"Pending_L{next_level.level_no}"
        else:
            create_history(
                project_code=r.project_code, module_code=_MODULE,
                record_id=r.id, level_no=r.current_level,
                action="FINAL_APPROVE", action_by=approved_by, comments=comments,
            )
            r.workflow_status   = "Approved"
            r.locked            = True
            r.approved_by       = approved_by
            r.final_approved_at = datetime.utcnow()

        r.updated_by = approved_by
        r.updated_at = datetime.utcnow()

        db.session.commit()

        return res("Bill payment receipt approved", {"id": r.id, "workflowStatus": r.workflow_status}, 200)

    except SQLAlchemyError as e:
        db.session.rollback()
        return res(str(e), [], 500)
    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 8. REBACK
# ══════════════════════════════════════════════════════════════════

def reback_bill_payment(receipt_id, reback_by, comments=None):
    try:
        r = BillPaymentReceiptMaster.query.get(receipt_id)
        if not r:
            return res("Bill payment receipt not found", [], 404)
        if not r.workflow_status.startswith("Pending"):
            return res("Bill payment receipt is not pending", [], 400)
        if not comments:
            return res("Comments required for reback", [], 400)

        allowed = is_current_approver(r.project_code, _MODULE, r.current_level, reback_by)
        if not allowed:
            return res("You are not the current approver", [], 403)

        r.workflow_status    = "Reback"
        r.locked             = False
        r.correction_sent_at = datetime.utcnow()
        r.updated_by         = reback_by
        r.updated_at         = datetime.utcnow()

        create_history(
            project_code=r.project_code, module_code=_MODULE,
            record_id=r.id, level_no=r.current_level,
            action="REBACK", action_by=reback_by, comments=comments,
        )

        db.session.commit()

        return res("Bill payment receipt sent for correction", {"id": r.id, "workflowStatus": r.workflow_status}, 200)

    except SQLAlchemyError as e:
        db.session.rollback()
        return res(str(e), [], 500)
    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 9. REJECT
# ══════════════════════════════════════════════════════════════════

def reject_bill_payment(receipt_id, rejected_by, comments=None):
    try:
        r = BillPaymentReceiptMaster.query.get(receipt_id)
        if not r:
            return res("Bill payment receipt not found", [], 404)
        if not r.workflow_status.startswith("Pending"):
            return res("Bill payment receipt is not pending", [], 400)
        if not comments:
            return res("Comments required for rejection", [], 400)

        allowed = is_current_approver(r.project_code, _MODULE, r.current_level, rejected_by)
        if not allowed:
            return res("You are not the current approver", [], 403)

        r.workflow_status = "Rejected"
        r.locked          = True
        r.rejected_at     = datetime.utcnow()
        r.rejected_by     = rejected_by
        r.status          = "Inactive"
        r.updated_by      = rejected_by
        r.updated_at      = datetime.utcnow()

        create_history(
            project_code=r.project_code, module_code=_MODULE,
            record_id=r.id, level_no=r.current_level,
            action="REJECT", action_by=rejected_by, comments=comments,
        )

        db.session.commit()

        return res("Bill payment receipt rejected", {"id": r.id, "workflowStatus": r.workflow_status}, 200)

    except SQLAlchemyError as e:
        db.session.rollback()
        return res(str(e), [], 500)
    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 10. HISTORY
# ══════════════════════════════════════════════════════════════════

def get_bill_payment_history(receipt_id):
    try:
        r = BillPaymentReceiptMaster.query.get(receipt_id)
        if not r:
            return res("Bill payment receipt not found", [], 404)

        rows = get_history(_MODULE, r.id)

        history = [
            {
                "id":        h.id,
                "action":    h.action,
                "level":     h.level_no,
                "comments":  h.comments,
                "actionBy":  h.user.username if h.user else None,
                "createdAt": h.created_at.strftime("%Y-%m-%d %H:%M:%S") if h.created_at else None,
            }
            for h in rows
        ]

        steps = get_approval_steps(r.project_code, _MODULE, r, rows)

        return res("History fetched", {
            "workflowStatus": r.workflow_status,
            "currentLevel":   r.current_level,
            "approvalSteps":  steps,
            "history":        history,
        }, 200)

    except Exception as e:
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 11. MY APPROVAL STATUS
# ══════════════════════════════════════════════════════════════════

def get_bill_payment_my_approval_status(receipt_id, user_id):
    try:
        r = BillPaymentReceiptMaster.query.get(receipt_id)
        if not r:
            return res("Bill payment receipt not found", [], 404)
        data = get_my_approval_status(r.project_code, _MODULE, r, user_id)
        return res("Approval status", data, 200)
    except Exception as e:
        return res(str(e), [], 500)
