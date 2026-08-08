from decimal import Decimal
from app.extensions import db
from datetime import datetime, date
import uuid as _uuid

from app.models.saleReceipt import SaleReceiptMaster
from app.models.ogSaleOrder import OgSaleOrderMaster
from app.response import res


def _fmt_date(d):
    if d is None:
        return None
    if isinstance(d, datetime):
        return d.strftime("%Y-%m-%d %H:%M")
    return d.strftime("%Y-%m-%d")


def _generate_receipt_no():
    last = (
        db.session.query(SaleReceiptMaster.receipt_no)
        .order_by(SaleReceiptMaster.id.desc())
        .with_for_update()
        .first()
    )
    num = 0
    if last:
        try:
            num = int(last[0])
        except Exception:
            num = 0
    return str(num + 1).zfill(3)


# ══════════════════════════════════════════════════════════════════
# 1. APPROVED OG SALE ORDERS  (lookup for child billing reference)
# ══════════════════════════════════════════════════════════════════

def get_og_sale_orders(data):
    """Return all Approved OG Sale Orders for a project."""
    try:
        project_code = (data.get("projectCode") or "").strip()
        if not project_code:
            return res("projectCode required", [], 400)

        orders = OgSaleOrderMaster.query.filter(
            OgSaleOrderMaster.project_code    == project_code,
            OgSaleOrderMaster.workflow_status == "Approved",
        ).order_by(OgSaleOrderMaster.id.desc()).all()

        result = [
            {
                "id":              o.id,
                "ogSaleOrderNo":   o.og_sale_order_no,
                "ogSaleOrderDate": _fmt_date(o.og_sale_order_date),
                "orderTitle":      o.order_title,
                "totalAmount":     float(o.total_amount or 0),
            }
            for o in orders
        ]

        return res("OG sale orders fetched", result, 200)

    except Exception as e:
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 2. CREATE PARENT RECEIPT
# ══════════════════════════════════════════════════════════════════

def create_sale_receipt(data, user_id):
    try:
        project_code = (data.get("projectCode") or "").strip()
        if not project_code:
            return res("projectCode required", [], 400)

        receipt = SaleReceiptMaster(
            receipt_no      = _generate_receipt_no(),
            receipt_uuid    = str(_uuid.uuid4()),
            entry_date      = date.today(),
            project_code    = project_code,
            payment_mode    = data.get("paymentMode"),
            cash_ac_id      = data.get("cashAcId") or None,
            bank_ac_id      = data.get("bankAcId") or None,
            utr_voucher_no  = data.get("utrVoucherNo"),
            payment_remarks = data.get("paymentRemarks"),
            total_amount    = Decimal(str(data.get("totalAmount") or 0)),
            created_by      = user_id,
        )
        db.session.add(receipt)
        db.session.commit()

        return res("Sale receipt created", {
            "id":          receipt.id,
            "receiptNo":   receipt.receipt_no,
            "receiptUuid": receipt.receipt_uuid,
        }, 201)

    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 3. LIST
# ══════════════════════════════════════════════════════════════════

def get_sale_receipt_list(data):
    try:
        project_code = data.get("projectCode")
        if not project_code:
            return res("projectCode required", [], 400)

        query = SaleReceiptMaster.query.filter(
            SaleReceiptMaster.project_code == project_code
        )

        if data.get("search"):
            term = f"%{data.get('search')}%"
            query = query.filter(
                db.or_(
                    SaleReceiptMaster.receipt_no.ilike(term),
                    SaleReceiptMaster.utr_voucher_no.ilike(term),
                )
            )

        rows = query.order_by(SaleReceiptMaster.id.desc()).all()

        result = [
            {
                "id":             r.id,
                "receiptNo":      r.receipt_no,
                "entryDate":      _fmt_date(r.entry_date),
                "utrVoucherNo":   r.utr_voucher_no,
                "paymentMode":    r.payment_mode,
                "totalAmount":    float(r.total_amount or 0),
                "billingCount":   len(r.billings),
                "createdBy":      r.creator.username if r.creator else None,
                "createdAt":      _fmt_date(r.created_at),
            }
            for r in rows
        ]

        return res("Sale receipt list fetched", result, 200)

    except Exception as e:
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 4. DETAILS
# ══════════════════════════════════════════════════════════════════

def get_sale_receipt_details(receipt_id):
    try:
        receipt = SaleReceiptMaster.query.get(receipt_id)
        if not receipt:
            return res("Sale receipt not found", [], 404)

        billings = [
            {
                "id":                 b.id,
                "srbNo":              b.srb_no,
                "ogSaleOrderNo":      b.og_sale_order_no,
                "certifiedBillNo":    b.certified_bill_no,
                "basicAmount":        float(b.basic_amount         or 0),
                "gstAmount":          float(b.gst_amount           or 0),
                "totalInvoiceAmount": float(b.total_invoice_amount or 0),
                "workflowStatus":     b.workflow_status,
            }
            for b in receipt.billings
        ]

        data = {
            "id":             receipt.id,
            "receiptNo":      receipt.receipt_no,
            "receiptUuid":    receipt.receipt_uuid,
            "entryDate":      _fmt_date(receipt.entry_date),
            "projectCode":    receipt.project_code,
            "paymentMode":    receipt.payment_mode,
            "cashAcId":       receipt.cash_ac_id,
            "cashAcName":     receipt.cash_account.bank_holder_name if receipt.cash_account else None,
            "bankAcId":       receipt.bank_ac_id,
            "bankAcName":     receipt.bank_account.bank_holder_name if receipt.bank_account else None,
            "bankCode":       receipt.bank_account.bank_code         if receipt.bank_account else None,
            "utrVoucherNo":   receipt.utr_voucher_no,
            "paymentRemarks": receipt.payment_remarks,
            "totalAmount":    float(receipt.total_amount or 0),
            "createdBy":      receipt.creator.username if receipt.creator else None,
            "createdAt":      _fmt_date(receipt.created_at),
            "billings":       billings,
        }

        return res("Sale receipt details fetched", data, 200)

    except Exception as e:
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 5. EDIT
# ══════════════════════════════════════════════════════════════════

def edit_sale_receipt(receipt_id, data, user_id):
    try:
        receipt = SaleReceiptMaster.query.get(receipt_id)
        if not receipt:
            return res("Sale receipt not found", [], 404)

        fields = [
            ("paymentMode",    "payment_mode"),
            ("cashAcId",       "cash_ac_id"),
            ("bankAcId",       "bank_ac_id"),
            ("utrVoucherNo",   "utr_voucher_no"),
            ("paymentRemarks", "payment_remarks"),
        ]
        for key, attr in fields:
            if data.get(key) is not None:
                setattr(receipt, attr, data.get(key) or None)

        if data.get("totalAmount") is not None:
            receipt.total_amount = Decimal(str(data.get("totalAmount") or 0))

        receipt.updated_by = user_id
        receipt.updated_at = datetime.utcnow()

        db.session.commit()
        return res("Sale receipt updated", {"id": receipt.id, "receiptNo": receipt.receipt_no}, 200)

    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 6. DELETE
# ══════════════════════════════════════════════════════════════════

def delete_sale_receipt(receipt_id, user_id):
    try:
        receipt = SaleReceiptMaster.query.get(receipt_id)
        if not receipt:
            return res("Sale receipt not found", [], 404)

        active = [b for b in receipt.billings if b.workflow_status not in ("Rejected",)]
        if active:
            return res("Cannot delete: receipt has active child billings", [], 400)

        db.session.delete(receipt)
        db.session.commit()
        return res("Sale receipt deleted", {}, 200)

    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)
