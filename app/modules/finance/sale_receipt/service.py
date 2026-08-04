from sqlalchemy import func
from sqlalchemy.exc import SQLAlchemyError
from app.extensions import db
from datetime import datetime, date
import uuid as _uuid

from app.models.saleReceipt import SaleReceiptMaster, SaleReceiptItem, SaleReceiptGst
from app.models.saleBill import SaleBillMaster, SaleBillGst
from app.models.billingMaster import BillingMaster
from app.models.item import Item
from app.models.cc_code import CCCode
from app.response import res
from app.modules.work_flow import (
    is_creator,
    is_current_approver,
    get_first_approver,
    get_next_approver,
    create_history,
    get_history,
    get_approval_steps,
    get_my_approval_status,
)

_MODULE = "receipt"


# ══════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════

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


def _group_by_cc(billing_items):
    """Group BillingItem rows by CC Code, summing basic amounts."""
    item_codes = [i.item_code for i in billing_items if i.item_code]
    item_map   = {}
    cc_map     = {}

    if item_codes:
        item_objs = Item.query.filter(Item.item_code.in_(item_codes)).all()
        item_map  = {i.item_code: i for i in item_objs}
        cc_ids    = list({i.cc_code_id for i in item_objs if i.cc_code_id})
        if cc_ids:
            cc_objs = CCCode.query.filter(CCCode.id.in_(cc_ids)).all()
            cc_map  = {c.id: c for c in cc_objs}

    groups = {}
    order  = []

    for bi in billing_items:
        item  = item_map.get(bi.item_code)
        cc_id = item.cc_code_id if item else None
        cc    = cc_map.get(cc_id) if cc_id else None
        key   = cc_id or "none"

        if key not in groups:
            groups[key] = {
                "ccCode":      cc.cc_code if cc else None,
                "ccName":      cc.cc_name if cc else "Uncategorized",
                "basicAmount": 0.0,
            }
            order.append(key)

        groups[key]["basicAmount"] += float(bi.amount or 0)

    return [
        {
            "slNo":        idx + 1,
            "ccCode":      groups[k]["ccCode"],
            "ccName":      groups[k]["ccName"],
            "basicAmount": round(groups[k]["basicAmount"], 2),
        }
        for idx, k in enumerate(order)
    ]


def _build_detail_payload(receipt):
    return {
        "id":                  receipt.id,
        "receiptNo":           receipt.receipt_no,
        "receiptUuid":         receipt.receipt_uuid,
        "entryDate":           _fmt_date(receipt.entry_date),
        "ogSaleOrderNo":       receipt.og_sale_order_no,
        "ogSaleOrderId":       receipt.og_sale_order_id,
        "saleOrderDate":       _fmt_date(receipt.sale_order_date),
        "certifiedBillId":     receipt.certified_bill_id,
        "certifiedBillNo":     receipt.certified_bill_no,
        "projectCode":         receipt.project_code,
        "invoiceNo":           receipt.invoice_no,
        "invoiceDate":         _fmt_date(receipt.invoice_date),
        "billToAddress":       receipt.bill_to_address,
        "shipToAddress":       receipt.ship_to_address,
        "billAbstractNo":      receipt.bill_abstract_no,
        "billAbstractDate":    _fmt_date(receipt.bill_abstract_date),
        "paymentMode":         receipt.payment_mode,
        "cashAcId":            receipt.cash_ac_id,
        "cashAcName":          receipt.cash_account.bank_holder_name if receipt.cash_account else None,
        "bankAcId":            receipt.bank_ac_id,
        "bankAcName":          receipt.bank_account.bank_holder_name if receipt.bank_account else None,
        "bankCode":            receipt.bank_account.bank_code         if receipt.bank_account else None,
        "utrVoucherNo":        receipt.utr_voucher_no,
        "paymentRemarks":      receipt.payment_remarks,
        "basicAmount":         float(receipt.basic_amount         or 0),
        "gstAmount":           float(receipt.gst_amount           or 0),
        "discount":            float(receipt.discount             or 0),
        "roundOff":            float(receipt.round_off            or 0),
        "totalInvoiceAmount":  float(receipt.total_invoice_amount or 0),
        "workflowStatus":      receipt.workflow_status,
        "currentLevel":        receipt.current_level,
        "locked":              receipt.locked,
        "createdBy":           receipt.creator.username   if receipt.creator   else None,
        "createdAt":           _fmt_date(receipt.created_at),
        "submittedBy":         receipt.submitter.username if receipt.submitter else None,
        "submittedAt":         _fmt_date(receipt.submitted_at),
        "approvedBy":          receipt.approver.username  if receipt.approver  else None,
        "finalApprovedAt":     _fmt_date(receipt.final_approved_at),
        "rejectedBy":          receipt.rejector.username  if receipt.rejector  else None,
        "rejectedAt":          _fmt_date(receipt.rejected_at),
        "items": [
            {
                "id":             i.id,
                "slNo":           i.sl_no,
                "ccCode":         i.cc_code,
                "ccName":         i.cc_name,
                "bookedAmount":   float(i.booked_amount   or 0),
                "receivedAmount": float(i.received_amount or 0),
                "balanceAmount":  float(i.balance_amount  or 0),
                "currentAmount":  float(i.current_amount  or 0),
            }
            for i in receipt.items
        ],
        "gstLines": [
            {
                "id":             g.id,
                "gstType":        g.gst_type,
                "ccCode":         g.cc_code,
                "ccName":         g.cc_name,
                "percent":        float(g.percent         or 0),
                "bookedAmount":   float(g.booked_amount   or 0),
                "receivedAmount": float(g.received_amount or 0),
                "balanceAmount":  float(g.balance_amount  or 0),
                "currentAmount":  float(g.current_amount  or 0),
                "isSelected":     g.is_selected,
            }
            for g in receipt.gst_lines
        ],
    }


# ══════════════════════════════════════════════════════════════════
# 1. CERTIFIED BILLS LOOKUP
# ══════════════════════════════════════════════════════════════════

def get_certified_bills_for_order(data):
    """Return all Approved certified bills for a given OG Sale Order."""
    try:
        og_sale_order_no = (data.get("ogSaleOrderNo") or "").strip()
        project_code     = (data.get("projectCode")   or "").strip()

        if not og_sale_order_no:
            return res("ogSaleOrderNo required", [], 400)
        if not project_code:
            return res("projectCode required", [], 400)

        bills = BillingMaster.query.filter(
            BillingMaster.og_sale_order_no == og_sale_order_no,
            BillingMaster.project_code     == project_code,
            BillingMaster.mode             == "sale_certified_bill",
            BillingMaster.workflow_status  == "Approved",
        ).order_by(BillingMaster.id.asc()).all()

        result = [
            {
                "id":            b.id,
                "billingNo":     b.billing_no,
                "billingDate":   _fmt_date(b.billing_date),
                "thisBillClaim": float(b.this_bill_claim or 0),
            }
            for b in bills
        ]

        return res("Certified bills fetched", result, 200)

    except Exception as e:
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 2. RECEIPT ITEMS  (accounting columns — Booked/Received/Balance)
# ══════════════════════════════════════════════════════════════════

def get_receipt_items(data):
    """
    Return CC-grouped items from the certified bill with accounting columns.
    Received = sum of all non-Rejected previous sale receipts' current_amount
               for the same certified_bill_id and cc_code.
    """
    try:
        certified_bill_id = data.get("certifiedBillId")
        project_code      = (data.get("projectCode") or "").strip()

        if not certified_bill_id:
            return res("certifiedBillId required", [], 400)
        if not project_code:
            return res("projectCode required", [], 400)

        bill = BillingMaster.query.filter_by(
            id              = int(certified_bill_id),
            mode            = "sale_certified_bill",
            workflow_status = "Approved",
        ).first()

        if not bill:
            return res("Approved certified bill not found", [], 404)
        if bill.project_code != project_code:
            return res("Certified bill does not belong to this project", [], 403)

        # ── BASIC items ───────────────────────────────────────────
        grouped = _group_by_cc(bill.items)

        result_items = []
        for g in grouped:
            cc_code = g["ccCode"]
            booked  = g["basicAmount"]

            received = (
                db.session.query(func.sum(SaleReceiptItem.current_amount))
                .join(SaleReceiptMaster, SaleReceiptMaster.id == SaleReceiptItem.receipt_id)
                .filter(
                    SaleReceiptMaster.certified_bill_id == bill.id,
                    SaleReceiptMaster.workflow_status   != "Rejected",
                    SaleReceiptItem.cc_code             == cc_code,
                )
                .scalar() or 0
            )

            received = round(float(received), 2)
            balance  = round(booked - received, 2)

            result_items.append({
                "slNo":           g["slNo"],
                "ccCode":         cc_code,
                "ccName":         g["ccName"],
                "bookedAmount":   booked,
                "receivedAmount": received,
                "balanceAmount":  balance,
                "currentAmount":  0,
            })

        # ── GST lines — booked from approved sale bill for this cert bill ──
        gst_rows = (
            db.session.query(
                SaleBillGst.gst_type,
                SaleBillGst.cc_code,
                SaleBillGst.cc_name,
                SaleBillGst.percent,
                func.sum(SaleBillGst.gst_amount).label("total"),
            )
            .join(SaleBillMaster, SaleBillMaster.id == SaleBillGst.sale_bill_id)
            .filter(
                SaleBillMaster.certified_bill_id == bill.id,
                SaleBillMaster.workflow_status   == "Approved",
                SaleBillGst.is_selected          == True,
            )
            .group_by(
                SaleBillGst.gst_type,
                SaleBillGst.cc_code,
                SaleBillGst.cc_name,
                SaleBillGst.percent,
            )
            .all()
        )

        result_gst = []
        if gst_rows:
            for row in gst_rows:
                booked_gst = round(float(row.total or 0), 2)

                received_gst = (
                    db.session.query(func.sum(SaleReceiptGst.current_amount))
                    .join(SaleReceiptMaster, SaleReceiptMaster.id == SaleReceiptGst.receipt_id)
                    .filter(
                        SaleReceiptMaster.certified_bill_id == bill.id,
                        SaleReceiptMaster.workflow_status   != "Rejected",
                        SaleReceiptGst.gst_type             == row.gst_type,
                    )
                    .scalar() or 0
                )

                received_gst = round(float(received_gst), 2)
                balance_gst  = round(booked_gst - received_gst, 2)

                result_gst.append({
                    "gstType":        row.gst_type,
                    "ccCode":         row.cc_code,
                    "ccName":         row.cc_name,
                    "percent":        float(row.percent or 0),
                    "bookedAmount":   booked_gst,
                    "receivedAmount": received_gst,
                    "balanceAmount":  balance_gst,
                    "currentAmount":  0,
                    "isSelected":     True,
                })
        else:
            # No approved sale bill yet — return empty default GST lines
            for gst_type, cc_code, cc_name, pct in [
                ("IGST", "IGST", "Input-IGST", 18),
                ("CGST", "CGST", "Input-CGST", 9),
                ("SGST", "SGST", "Input-SGST", 9),
            ]:
                result_gst.append({
                    "gstType":        gst_type,
                    "ccCode":         cc_code,
                    "ccName":         cc_name,
                    "percent":        pct,
                    "bookedAmount":   0,
                    "receivedAmount": 0,
                    "balanceAmount":  0,
                    "currentAmount":  0,
                    "isSelected":     False,
                })

        return res("Receipt items fetched", {
            "certifiedBillId": bill.id,
            "certifiedBillNo": bill.billing_no,
            "ogSaleOrderNo":   bill.og_sale_order_no,
            "saleOrderDate":   _fmt_date(bill.og_so.og_sale_order_date) if bill.og_so else None,
            "items":           result_items,
            "gstLines":        result_gst,
        }, 200)

    except Exception as e:
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 3. CREATE
# ══════════════════════════════════════════════════════════════════

def create_sale_receipt(data, user_id):
    try:
        project_code = data.get("projectCode")
        if not project_code:
            return res("projectCode required", [], 400)

        allowed = is_creator(project_code, _MODULE, user_id)
        if not allowed:
            return res("You are not authorized to create sale receipts", [], 403)

        certified_bill_id = data.get("certifiedBillId")
        if not certified_bill_id:
            return res("certifiedBillId required", [], 400)

        cert_bill = BillingMaster.query.filter_by(
            id              = int(certified_bill_id),
            mode            = "sale_certified_bill",
            workflow_status = "Approved",
        ).first()
        if not cert_bill:
            return res("Approved certified bill not found", [], 404)
        if cert_bill.project_code != project_code:
            return res("Certified bill does not belong to this project", [], 403)

        items = data.get("items", [])
        if not items:
            return res("At least one BASIC item required", [], 400)

        gst_lines = data.get("gstLines", [])

        basic_total = sum(float(i.get("currentAmount") or 0) for i in items)
        gst_total   = sum(
            float(g.get("currentAmount") or 0)
            for g in gst_lines if g.get("isSelected")
        )
        discount  = float(data.get("discount")  or 0)
        round_off = float(data.get("roundOff")  or 0)
        total     = round(basic_total + gst_total - discount + round_off, 2)

        sale_order_date = None
        if cert_bill.og_so:
            sale_order_date = cert_bill.og_so.og_sale_order_date

        receipt = SaleReceiptMaster(
            receipt_no         = _generate_receipt_no(),
            receipt_uuid       = str(_uuid.uuid4()),
            entry_date         = date.today(),
            og_sale_order_no   = cert_bill.og_sale_order_no,
            og_sale_order_id   = cert_bill.og_sale_order_id,
            sale_order_date    = sale_order_date,
            certified_bill_id  = cert_bill.id,
            certified_bill_no  = cert_bill.billing_no,
            project_code       = project_code,
            invoice_no         = data.get("invoiceNo"),
            invoice_date       = data.get("invoiceDate"),
            bill_to_address    = data.get("billToAddress"),
            ship_to_address    = data.get("shipToAddress"),
            bill_abstract_no   = data.get("billAbstractNo"),
            bill_abstract_date = data.get("billAbstractDate"),
            payment_mode       = data.get("paymentMode"),
            cash_ac_id         = data.get("cashAcId"),
            bank_ac_id         = data.get("bankAcId"),
            utr_voucher_no     = data.get("utrVoucherNo"),
            payment_remarks    = data.get("paymentRemarks"),
            basic_amount         = round(basic_total, 2),
            gst_amount           = round(gst_total,   2),
            discount             = discount,
            round_off            = round_off,
            total_invoice_amount = total,
            workflow_status      = "Draft",
            current_level        = 0,
            locked               = False,
            created_by           = user_id,
        )
        db.session.add(receipt)
        db.session.flush()

        for idx, row in enumerate(items, start=1):
            booked   = float(row.get("bookedAmount")   or 0)
            received = float(row.get("receivedAmount") or 0)
            balance  = float(row.get("balanceAmount")  or 0)
            current  = float(row.get("currentAmount")  or 0)
            db.session.add(SaleReceiptItem(
                receipt_id      = receipt.id,
                sl_no           = row.get("slNo") or idx,
                cc_code         = row.get("ccCode"),
                cc_name         = row.get("ccName"),
                booked_amount   = booked,
                received_amount = received,
                balance_amount  = balance,
                current_amount  = current,
            ))

        for g in gst_lines:
            db.session.add(SaleReceiptGst(
                receipt_id      = receipt.id,
                gst_type        = g.get("gstType"),
                cc_code         = g.get("ccCode"),
                cc_name         = g.get("ccName"),
                percent         = float(g.get("percent")        or 0),
                booked_amount   = float(g.get("bookedAmount")   or 0),
                received_amount = float(g.get("receivedAmount") or 0),
                balance_amount  = float(g.get("balanceAmount")  or 0),
                current_amount  = float(g.get("currentAmount")  or 0) if g.get("isSelected") else 0,
                is_selected     = bool(g.get("isSelected")),
            ))

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
# 4. LIST
# ══════════════════════════════════════════════════════════════════

def get_sale_receipt_list(data):
    try:
        project_code = data.get("projectCode")
        if not project_code:
            return res("projectCode required", [], 400)

        query = SaleReceiptMaster.query.filter(
            SaleReceiptMaster.project_code == project_code
        )

        if data.get("workflowStatus"):
            query = query.filter(SaleReceiptMaster.workflow_status == data.get("workflowStatus"))
        if data.get("ogSaleOrderNo"):
            query = query.filter(
                SaleReceiptMaster.og_sale_order_no.ilike(f"%{data.get('ogSaleOrderNo')}%")
            )
        if data.get("search"):
            term = f"%{data.get('search')}%"
            query = query.filter(
                db.or_(
                    SaleReceiptMaster.receipt_no.ilike(term),
                    SaleReceiptMaster.certified_bill_no.ilike(term),
                    SaleReceiptMaster.og_sale_order_no.ilike(term),
                )
            )

        rows = query.order_by(SaleReceiptMaster.id.desc()).all()

        result = [
            {
                "id":                 r.id,
                "receiptNo":          r.receipt_no,
                "entryDate":          _fmt_date(r.entry_date),
                "ogSaleOrderNo":      r.og_sale_order_no,
                "certifiedBillNo":    r.certified_bill_no,
                "basicAmount":        float(r.basic_amount         or 0),
                "gstAmount":          float(r.gst_amount           or 0),
                "totalInvoiceAmount": float(r.total_invoice_amount or 0),
                "workflowStatus":     r.workflow_status,
                "createdBy":          r.creator.username if r.creator else None,
                "createdAt":          _fmt_date(r.created_at),
            }
            for r in rows
        ]

        return res("Sale receipt list fetched", result, 200)

    except Exception as e:
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 5. DETAILS
# ══════════════════════════════════════════════════════════════════

def get_sale_receipt_details(receipt_id):
    try:
        receipt = SaleReceiptMaster.query.get(receipt_id)
        if not receipt:
            return res("Sale receipt not found", [], 404)
        return res("Sale receipt details fetched", _build_detail_payload(receipt), 200)
    except Exception as e:
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 6. EDIT
# ══════════════════════════════════════════════════════════════════

def edit_sale_receipt(receipt_id, data, user_id):
    try:
        receipt = SaleReceiptMaster.query.get(receipt_id)
        if not receipt:
            return res("Sale receipt not found", [], 404)
        if receipt.locked:
            return res("Sale receipt is locked and cannot be edited", [], 400)
        if receipt.workflow_status not in ("Draft", "Reback"):
            return res("Only Draft or Reback records can be edited", [], 400)

        allowed = is_creator(receipt.project_code, _MODULE, user_id)
        if not allowed:
            return res("You are not authorized to edit this sale receipt", [], 403)

        items = data.get("items", [])
        if not items:
            return res("At least one BASIC item required", [], 400)

        gst_lines = data.get("gstLines", [])

        # Update header fields
        if data.get("invoiceNo") is not None:
            receipt.invoice_no = data.get("invoiceNo")
        if data.get("invoiceDate") is not None:
            receipt.invoice_date = data.get("invoiceDate")
        if data.get("billToAddress") is not None:
            receipt.bill_to_address = data.get("billToAddress")
        if data.get("shipToAddress") is not None:
            receipt.ship_to_address = data.get("shipToAddress")
        if data.get("billAbstractNo") is not None:
            receipt.bill_abstract_no = data.get("billAbstractNo")
        if data.get("billAbstractDate") is not None:
            receipt.bill_abstract_date = data.get("billAbstractDate")
        if data.get("paymentMode") is not None:
            receipt.payment_mode = data.get("paymentMode")
        if data.get("cashAcId") is not None:
            receipt.cash_ac_id = data.get("cashAcId")
        if data.get("bankAcId") is not None:
            receipt.bank_ac_id = data.get("bankAcId")
        if data.get("utrVoucherNo") is not None:
            receipt.utr_voucher_no = data.get("utrVoucherNo")
        if data.get("paymentRemarks") is not None:
            receipt.payment_remarks = data.get("paymentRemarks")

        # Rebuild items and GST
        SaleReceiptItem.query.filter_by(receipt_id=receipt.id).delete()
        SaleReceiptGst.query.filter_by(receipt_id=receipt.id).delete()
        db.session.flush()

        basic_total = sum(float(i.get("currentAmount") or 0) for i in items)
        gst_total   = sum(
            float(g.get("currentAmount") or 0)
            for g in gst_lines if g.get("isSelected")
        )
        discount  = float(data.get("discount")  or 0)
        round_off = float(data.get("roundOff")  or 0)

        for idx, row in enumerate(items, start=1):
            db.session.add(SaleReceiptItem(
                receipt_id      = receipt.id,
                sl_no           = row.get("slNo") or idx,
                cc_code         = row.get("ccCode"),
                cc_name         = row.get("ccName"),
                booked_amount   = float(row.get("bookedAmount")   or 0),
                received_amount = float(row.get("receivedAmount") or 0),
                balance_amount  = float(row.get("balanceAmount")  or 0),
                current_amount  = float(row.get("currentAmount")  or 0),
            ))

        for g in gst_lines:
            db.session.add(SaleReceiptGst(
                receipt_id      = receipt.id,
                gst_type        = g.get("gstType"),
                cc_code         = g.get("ccCode"),
                cc_name         = g.get("ccName"),
                percent         = float(g.get("percent")        or 0),
                booked_amount   = float(g.get("bookedAmount")   or 0),
                received_amount = float(g.get("receivedAmount") or 0),
                balance_amount  = float(g.get("balanceAmount")  or 0),
                current_amount  = float(g.get("currentAmount")  or 0) if g.get("isSelected") else 0,
                is_selected     = bool(g.get("isSelected")),
            ))

        receipt.basic_amount         = round(basic_total, 2)
        receipt.gst_amount           = round(gst_total,   2)
        receipt.discount             = discount
        receipt.round_off            = round_off
        receipt.total_invoice_amount = round(basic_total + gst_total - discount + round_off, 2)

        if receipt.workflow_status == "Reback":
            receipt.correction_sent_at = None

        receipt.updated_by = user_id
        receipt.updated_at = datetime.utcnow()

        db.session.commit()

        return res("Sale receipt updated", {"id": receipt.id, "receiptNo": receipt.receipt_no}, 200)

    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 7. SUBMIT
# ══════════════════════════════════════════════════════════════════

def submit_sale_receipt(receipt_id, user_id):
    try:
        receipt = SaleReceiptMaster.query.get(receipt_id)
        if not receipt:
            return res("Sale receipt not found", [], 404)
        if receipt.workflow_status not in ("Draft", "Reback"):
            return res("Sale receipt already submitted", [], 400)
        if not receipt.items:
            return res("Sale receipt has no items", [], 400)

        if receipt.workflow_status == "Reback":
            receipt.current_level = 0

        first_level = get_first_approver(receipt.project_code, _MODULE)

        if not first_level:
            receipt.workflow_status   = "Approved"
            receipt.locked            = True
            receipt.approved_by       = user_id
            receipt.submitted_at      = datetime.utcnow()
            receipt.final_approved_at = datetime.utcnow()
        else:
            receipt.workflow_status = f"Pending_L{first_level.level_no}"
            receipt.current_level   = first_level.level_no
            receipt.locked          = True
            receipt.submitted_at    = datetime.utcnow()

        create_history(
            project_code=receipt.project_code,
            module_code=_MODULE,
            record_id=receipt.id,
            level_no=receipt.current_level,
            action="SUBMIT",
            action_by=user_id,
        )

        receipt.submitted_by = user_id
        receipt.updated_by   = user_id
        receipt.updated_at   = datetime.utcnow()

        db.session.commit()

        return res("Sale receipt submitted", {
            "id":             receipt.id,
            "workflowStatus": receipt.workflow_status,
        }, 200)

    except SQLAlchemyError as e:
        db.session.rollback()
        return res(str(e), [], 500)
    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 8. APPROVE
# ══════════════════════════════════════════════════════════════════

def approve_sale_receipt(receipt_id, approved_by, comments=None):
    try:
        receipt = SaleReceiptMaster.query.get(receipt_id)
        if not receipt:
            return res("Sale receipt not found", [], 404)
        if not receipt.workflow_status.startswith("Pending"):
            return res("Sale receipt is not pending approval", [], 400)

        allowed = is_current_approver(receipt.project_code, _MODULE, receipt.current_level, approved_by)
        if not allowed:
            return res("You are not the current approver", [], 403)

        next_level = get_next_approver(receipt.project_code, _MODULE, receipt.current_level)

        if next_level:
            create_history(
                project_code=receipt.project_code, module_code=_MODULE,
                record_id=receipt.id, level_no=receipt.current_level,
                action="APPROVE", action_by=approved_by, comments=comments,
            )
            receipt.current_level   = next_level.level_no
            receipt.workflow_status = f"Pending_L{next_level.level_no}"
        else:
            create_history(
                project_code=receipt.project_code, module_code=_MODULE,
                record_id=receipt.id, level_no=receipt.current_level,
                action="FINAL_APPROVE", action_by=approved_by, comments=comments,
            )
            receipt.workflow_status   = "Approved"
            receipt.locked            = True
            receipt.approved_by       = approved_by
            receipt.final_approved_at = datetime.utcnow()

        receipt.updated_by = approved_by
        receipt.updated_at = datetime.utcnow()

        db.session.commit()

        return res("Sale receipt approved", {
            "id":             receipt.id,
            "workflowStatus": receipt.workflow_status,
        }, 200)

    except SQLAlchemyError as e:
        db.session.rollback()
        return res(str(e), [], 500)
    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 9. REBACK
# ══════════════════════════════════════════════════════════════════

def reback_sale_receipt(receipt_id, reback_by, comments=None):
    try:
        receipt = SaleReceiptMaster.query.get(receipt_id)
        if not receipt:
            return res("Sale receipt not found", [], 404)
        if not receipt.workflow_status.startswith("Pending"):
            return res("Sale receipt is not pending", [], 400)
        if not comments:
            return res("Comments required for reback", [], 400)

        allowed = is_current_approver(receipt.project_code, _MODULE, receipt.current_level, reback_by)
        if not allowed:
            return res("You are not the current approver", [], 403)

        receipt.workflow_status    = "Reback"
        receipt.locked             = False
        receipt.correction_sent_at = datetime.utcnow()
        receipt.updated_by         = reback_by
        receipt.updated_at         = datetime.utcnow()

        create_history(
            project_code=receipt.project_code, module_code=_MODULE,
            record_id=receipt.id, level_no=receipt.current_level,
            action="REBACK", action_by=reback_by, comments=comments,
        )

        db.session.commit()

        return res("Sale receipt sent for correction", {
            "id":             receipt.id,
            "workflowStatus": receipt.workflow_status,
        }, 200)

    except SQLAlchemyError as e:
        db.session.rollback()
        return res(str(e), [], 500)
    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 10. REJECT
# ══════════════════════════════════════════════════════════════════

def reject_sale_receipt(receipt_id, rejected_by, comments=None):
    try:
        receipt = SaleReceiptMaster.query.get(receipt_id)
        if not receipt:
            return res("Sale receipt not found", [], 404)
        if not receipt.workflow_status.startswith("Pending"):
            return res("Sale receipt is not pending", [], 400)
        if not comments:
            return res("Comments required for rejection", [], 400)

        allowed = is_current_approver(receipt.project_code, _MODULE, receipt.current_level, rejected_by)
        if not allowed:
            return res("You are not the current approver", [], 403)

        receipt.workflow_status = "Rejected"
        receipt.locked          = True
        receipt.rejected_at     = datetime.utcnow()
        receipt.rejected_by     = rejected_by
        receipt.status          = "Inactive"
        receipt.updated_by      = rejected_by
        receipt.updated_at      = datetime.utcnow()

        create_history(
            project_code=receipt.project_code, module_code=_MODULE,
            record_id=receipt.id, level_no=receipt.current_level,
            action="REJECT", action_by=rejected_by, comments=comments,
        )

        db.session.commit()

        return res("Sale receipt rejected", {
            "id":             receipt.id,
            "workflowStatus": receipt.workflow_status,
        }, 200)

    except SQLAlchemyError as e:
        db.session.rollback()
        return res(str(e), [], 500)
    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 11. HISTORY
# ══════════════════════════════════════════════════════════════════

def get_sale_receipt_history(receipt_id):
    try:
        receipt = SaleReceiptMaster.query.get(receipt_id)
        if not receipt:
            return res("Sale receipt not found", [], 404)

        rows = get_history(_MODULE, receipt.id)

        history = [
            {
                "id":        r.id,
                "action":    r.action,
                "level":     r.level_no,
                "comments":  r.comments,
                "actionBy":  r.user.username if r.user else None,
                "createdAt": (
                    r.created_at.strftime("%Y-%m-%d %H:%M:%S")
                    if r.created_at else None
                ),
            }
            for r in rows
        ]

        steps = get_approval_steps(receipt.project_code, _MODULE, receipt, rows)

        return res("History fetched", {
            "workflowStatus": receipt.workflow_status,
            "currentLevel":   receipt.current_level,
            "approvalSteps":  steps,
            "history":        history,
        }, 200)

    except Exception as e:
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 12. MY APPROVAL STATUS
# ══════════════════════════════════════════════════════════════════

def get_sale_receipt_my_approval_status(receipt_id, user_id):
    try:
        receipt = SaleReceiptMaster.query.get(receipt_id)
        if not receipt:
            return res("Sale receipt not found", [], 404)
        data = get_my_approval_status(receipt.project_code, _MODULE, receipt, user_id)
        return res("Approval status", data, 200)
    except Exception as e:
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 13. UUID LOOKUP (public)
# ══════════════════════════════════════════════════════════════════

def get_sale_receipt_by_uuid(receipt_uuid):
    try:
        receipt = SaleReceiptMaster.query.filter_by(receipt_uuid=receipt_uuid).first()
        if not receipt:
            return res("Sale receipt not found", [], 404)
        return res("Sale receipt details fetched", _build_detail_payload(receipt), 200)
    except Exception as e:
        return res(str(e), [], 500)
