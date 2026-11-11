from decimal import Decimal
from sqlalchemy import func
from sqlalchemy.exc import SQLAlchemyError
from app.extensions import db
from datetime import datetime, date
import uuid as _uuid

from app.models.saleReceiptBilling import SaleReceiptBillingMaster, SaleReceiptItem, SaleReceiptGst
from app.models.saleReceipt import SaleReceiptMaster
from app.models.saleBill import SaleBillMaster, SaleBillGst, SaleBillItem
from app.models.billingMaster import BillingMaster
from app.models.ogSaleOrder import OgSaleOrderMaster
from app.models.item import Item
from app.models.cc_code import CCCode
from app.response import res
from app.utils.date_utils import parse_date
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


def _generate_srb_no():
    last = (
        db.session.query(SaleReceiptBillingMaster.srb_no)
        .order_by(SaleReceiptBillingMaster.id.desc())
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
                "basicAmount": Decimal('0'),
            }
            order.append(key)

        groups[key]["basicAmount"] += Decimal(str(bi.amount or 0))

    return [
        {
            "slNo":        idx + 1,
            "ccCode":      groups[k]["ccCode"],
            "ccName":      groups[k]["ccName"],
            "basicAmount": float(groups[k]["basicAmount"]),
        }
        for idx, k in enumerate(order)
    ]


def _srb_items_with_desc(srb):
    # Build cc_code → description map from the original sale bill
    cc_desc = {}
    if srb.invoice_no and srb.project_code:
        bill = SaleBillMaster.query.filter_by(
            sale_bill_no=srb.invoice_no, project_code=srb.project_code
        ).first()
        if bill:
            for bi in bill.items:
                cc = bi.cc_code or "GENERAL"
                if cc not in cc_desc:
                    cc_desc[cc] = bi.description
    return [
        {
            "id":             i.id,
            "slNo":           i.sl_no,
            "ccCode":         i.cc_code,
            "ccName":         i.cc_name,
            "description":    cc_desc.get(i.cc_code or "GENERAL"),
            "bookedAmount":   float(i.booked_amount   or 0),
            "receivedAmount": float(i.received_amount or 0),
            "balanceAmount":  float(i.balance_amount  or 0),
            "currentAmount":  float(i.current_amount  or 0),
        }
        for i in srb.items
    ]


def _build_srb_payload(srb):
    # Payment account from parent receipt (single FK access — no N+1)
    receipt = srb.receipt
    if receipt and receipt.payment_mode == "BANK" and receipt.bank_account:
        ac = receipt.bank_account
        ac_no = ac.bank_account_number
        payment_ac_name = f"{ac.bank_holder_name} (Acc: {ac_no})" if ac_no else ac.bank_holder_name
        payment_ac_code = "BANK"
    elif receipt and receipt.payment_mode == "CASH" and receipt.cash_account:
        ac = receipt.cash_account
        ac_no = ac.bank_account_number
        payment_ac_name = f"{ac.bank_holder_name} (Acc: {ac_no})" if ac_no else ac.bank_holder_name
        payment_ac_code = "CASH"
    else:
        payment_ac_name = receipt.payment_mode if receipt else None
        payment_ac_code = receipt.payment_mode if receipt else None

    debtor_name = srb.og_so.debtor.ledger_name if srb.og_so and srb.og_so.debtor else None

    return {
        "id":                   srb.id,
        "srbNo":                srb.srb_no,
        "srbDate":              _fmt_date(srb.srb_date),
        "srbUuid":              srb.srb_uuid,
        "receiptId":            srb.receipt_id,
        "debtorName":           debtor_name,
        "erpDocNumber":        srb.erp_no,
        "ogSaleOrderId":        srb.og_sale_order_id,
        "saleOrderDate":        _fmt_date(srb.sale_order_date),
        "certifiedBillId":      srb.certified_bill_id,
        "certifiedBillNo":      srb.bill_abstract_no,
        "certifiedBillDate":    _fmt_date(srb.bill_abstract_date),
        "projectCode":          srb.project_code,
        "invoiceNo":            srb.invoice_no,
        "paymentAccountName":   payment_ac_name,
        "paymentAccountCode":   payment_ac_code,
        "invoiceDate":        _fmt_date(srb.invoice_date),
        "billToAddress":      srb.bill_to_address,
        "shipToAddress":      srb.ship_to_address,
        "basicAmount":        float(srb.basic_amount         or 0),
        "gstAmount":          float(srb.gst_amount           or 0),
        "discount":           float(srb.discount             or 0),
        "roundOff":           float(srb.round_off            or 0),
        "totalInvoiceAmount": float(srb.total_invoice_amount or 0),
        "workflowStatus":     srb.workflow_status,
        "currentLevel":       srb.current_level,
        "locked":             srb.locked,
        "createdBy":          srb.creator.username   if srb.creator   else None,
        "createdAt":          _fmt_date(srb.created_at),
        "submittedBy":        srb.submitter.username if srb.submitter else None,
        "submittedAt":        _fmt_date(srb.submitted_at),
        "approvedBy":         srb.approver.username  if srb.approver  else None,
        "finalApprovedAt":    _fmt_date(srb.final_approved_at),
        "rejectedBy":         srb.rejector.username  if srb.rejector  else None,
        "rejectedAt":         _fmt_date(srb.rejected_at),
        "items": _srb_items_with_desc(srb),
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
            for g in srb.gst_lines
        ],
    }


# ══════════════════════════════════════════════════════════════════
# 0. AVAILABLE INVOICES  (single picker API — returns all approved
#    sale invoices with their receipt-usage status)
# ══════════════════════════════════════════════════════════════════

def get_available_invoices(params):
    """
    Return Approved sale invoices with balance remaining to receive.
    Status:
      Free    — no receipt exists yet
      Partial — partially received (balance > 0)
      Draft   — a Draft SRB is in progress (disable selection)
      Full    — fully received (balance ≤ 0, skipped entirely)
    """
    try:
        project_code = (params.get("projectCode") or "").strip()
        if not project_code:
            return res("projectCode required", [], 400)

        bills = (
            SaleBillMaster.query
            .filter_by(project_code=project_code, workflow_status="Approved")
            .order_by(SaleBillMaster.id.desc())
            .all()
        )

        result = []
        for bill in bills:
            booked = Decimal(str(bill.basic_amount or 0))

            # Total received across all non-Rejected SRBs for this invoice
            received = Decimal(str(
                db.session.query(func.sum(SaleReceiptItem.current_amount))
                .join(SaleReceiptBillingMaster, SaleReceiptBillingMaster.id == SaleReceiptItem.receipt_id)
                .filter(
                    SaleReceiptBillingMaster.invoice_no    == bill.sale_bill_no,
                    SaleReceiptBillingMaster.project_code  == project_code,
                    SaleReceiptBillingMaster.workflow_status != "Rejected",
                )
                .scalar() or 0
            ))
            balance = booked - received

            # Fully received — skip
            if booked > 0 and balance <= 0:
                continue

            # Draft SRB in progress — show but disable
            draft_srb = (
                SaleReceiptBillingMaster.query
                .filter(
                    SaleReceiptBillingMaster.project_code    == project_code,
                    SaleReceiptBillingMaster.invoice_no      == bill.sale_bill_no,
                    SaleReceiptBillingMaster.workflow_status == "Draft",
                )
                .first()
            )

            if draft_srb:
                receipt_status = "Draft"
            elif received > 0:
                receipt_status = "Partial"
            else:
                receipt_status = "Free"

            customer_order_no = None
            sale_order_date   = None
            debtor_name       = None
            if bill.sale_order_id:
                so = OgSaleOrderMaster.query.get(bill.sale_order_id)
                if so:
                    customer_order_no = so.order_no
                    sale_order_date   = _fmt_date(so.og_sale_order_date)
                    if so.debtor:
                        debtor_name = so.debtor.ledger_name

            result.append({
                "id":               bill.id,
                "saleBillNo":       bill.sale_bill_no,
                "invoiceDate":      _fmt_date(bill.invoice_date),
                "saleOrderNo":      bill.sale_order_no,
                "customerOrderNo":  customer_order_no,
                "saleOrderDate":    sale_order_date,
                "debtorName":       debtor_name,
                "bookedAmount":     float(booked),
                "receivedAmount":   float(received),
                "balanceAmount":    float(balance),
                "totalInvoiceAmount": float(bill.total_invoice_amount or 0),
                "receiptStatus":    receipt_status,
            })

        return res("Available invoices fetched", result, 200)

    except Exception as e:
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 1. INVOICE LOOKUP  (by sale_bill_no → auto-fill child billing form)
# ══════════════════════════════════════════════════════════════════

def get_details_by_invoice_no(data):
    """
    Given an Approved sale bill's invoice number, return the sale bill's own
    items/GST lines with booked/received/balance figures — ready to pre-fill
    a new child billing form.  No dependency on BillingMaster.
    """
    try:
        invoice_no   = (data.get("invoiceNo")   or "").strip()
        project_code = (data.get("projectCode") or "").strip()

        if not invoice_no:
            return res("invoiceNo required", [], 400)
        if not project_code:
            return res("projectCode required", [], 400)

        sale_bill = SaleBillMaster.query.filter_by(
            sale_bill_no    = invoice_no,
            project_code    = project_code,
            workflow_status = "Approved",
        ).first()

        if not sale_bill:
            return res("Approved sale bill not found for this invoice number", [], 404)

        og_so = sale_bill.og_so

        # ── BASIC items (from SaleBillItem, grouped by CC code) ───
        cc_map = {}
        for item in sale_bill.items:
            cc = item.cc_code or "GENERAL"
            if cc not in cc_map:
                cc_map[cc] = {"ccName": item.cc_name or "General", "description": item.description, "basicAmount": Decimal("0")}
            cc_map[cc]["basicAmount"] += Decimal(str(item.basic_amount or 0))

        result_items = []
        for sl_no, (cc_code, g) in enumerate(cc_map.items(), 1):
            booked = g["basicAmount"]
            received = Decimal(str(
                db.session.query(func.sum(SaleReceiptItem.current_amount))
                .join(SaleReceiptBillingMaster, SaleReceiptBillingMaster.id == SaleReceiptItem.receipt_id)
                .filter(
                    SaleReceiptBillingMaster.invoice_no    == invoice_no,
                    SaleReceiptBillingMaster.project_code  == project_code,
                    SaleReceiptBillingMaster.workflow_status != "Rejected",
                    SaleReceiptItem.cc_code                == cc_code,
                )
                .scalar() or 0
            ))
            result_items.append({
                "slNo":           sl_no,
                "ccCode":         cc_code,
                "ccName":         g["ccName"],
                "description":    g.get("description"),
                "bookedAmount":   float(booked),
                "receivedAmount": float(received),
                "balanceAmount":  float(booked - received),
                "currentAmount":  0,
            })

        # ── GST lines (from SaleBillGst) ──────────────────────────
        result_gst = []
        for row in sale_bill.gst_lines:
            booked_gst = Decimal(str(row.gst_amount or 0))
            received_gst = Decimal(str(
                db.session.query(func.sum(SaleReceiptGst.current_amount))
                .join(SaleReceiptBillingMaster, SaleReceiptBillingMaster.id == SaleReceiptGst.receipt_id)
                .filter(
                    SaleReceiptBillingMaster.invoice_no    == invoice_no,
                    SaleReceiptBillingMaster.project_code  == project_code,
                    SaleReceiptBillingMaster.workflow_status != "Rejected",
                    SaleReceiptGst.gst_type               == row.gst_type,
                )
                .scalar() or 0
            ))
            result_gst.append({
                "gstType":        row.gst_type,
                "ccCode":         row.cc_code or "",
                "ccName":         row.cc_name or "",
                "percent":        float(row.percent or 0),
                "bookedAmount":   float(booked_gst),
                "receivedAmount": float(received_gst),
                "balanceAmount":  float(booked_gst - received_gst),
                "currentAmount":  0,
                "isSelected":     bool(row.is_selected),
            })

        if not result_gst:
            for gst_type, cc_code, cc_name in [
                ("IGST", "IGST", "Output-IGST"),
                ("CGST", "CGST", "Output-CGST"),
                ("SGST", "SGST", "Output-SGST"),
            ]:
                result_gst.append({
                    "gstType": gst_type, "ccCode": cc_code, "ccName": cc_name,
                    "percent": 0, "bookedAmount": 0, "receivedAmount": 0,
                    "balanceAmount": 0, "currentAmount": 0, "isSelected": False,
                })

        debtor_name = og_so.debtor.ledger_name if og_so and og_so.debtor else None

        return res("Invoice details fetched", {
            "invoiceNo":         sale_bill.sale_bill_no,
            "invoiceDate":       _fmt_date(sale_bill.invoice_date),
            "billToAddress":     sale_bill.bill_to_address,
            "shipToAddress":     sale_bill.ship_to_address,
            "certifiedBillNo":   sale_bill.certified_bill_no or sale_bill.bill_abstract_no or "",
            "certifiedBillDate": _fmt_date(sale_bill.reference_date),
            "certifiedBillId":   sale_bill.certified_bill_id,
            "ogSaleOrderNo":     sale_bill.sale_order_no or (og_so.og_sale_order_erp_no if og_so else None),
            "ogSaleOrderId":     sale_bill.sale_order_id,
            "saleOrderDate":     _fmt_date(og_so.og_sale_order_date) if og_so else None,
            "debtorName":        debtor_name,
            "items":             result_items,
            "gstLines":          result_gst,
        }, 200)

    except ValueError as e:
        db.session.rollback()
        return res(str(e), [], 400)
    except Exception as e:
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 4. CREATE CHILD BILLING
# ══════════════════════════════════════════════════════════════════

def create_srb(data, user_id):
    try:
        project_code = (data.get("projectCode") or "").strip()
        if not project_code:
            return res("projectCode required", [], 400)

        allowed = is_creator(project_code, _MODULE, user_id)
        if not allowed:
            return res("You are not authorized to create sale receipt billings", [], 403)

        receipt_id = data.get("receiptId")
        if not receipt_id:
            return res("receiptId required", [], 400)

        parent = SaleReceiptMaster.query.get(int(receipt_id))
        if not parent:
            return res("Parent receipt not found", [], 404)
        if parent.project_code != project_code:
            return res("Receipt does not belong to this project", [], 403)

        invoice_no = (data.get("invoiceNo") or "").strip()
        if not invoice_no:
            return res("invoiceNo required", [], 400)

        sale_bill = SaleBillMaster.query.filter_by(
            sale_bill_no    = invoice_no,
            project_code    = project_code,
            workflow_status = "Approved",
        ).first()
        if not sale_bill:
            return res("Approved sale bill not found for this invoice number", [], 404)

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

        og_so           = sale_bill.og_so
        sale_order_date = og_so.og_sale_order_date if og_so else None

        srb = SaleReceiptBillingMaster(
            srb_no             = _generate_srb_no(),
            srb_uuid           = str(_uuid.uuid4()),
            srb_date           = parse_date(data.get("srbDate"), "srbDate") if data.get("srbDate") else None,
            receipt_id         = parent.id,
            erp_no             = sale_bill.sale_order_no,
            og_sale_order_id   = sale_bill.sale_order_id,
            sale_order_date    = sale_order_date,
            certified_bill_id  = sale_bill.certified_bill_id,
            project_code       = project_code,
            invoice_no         = invoice_no,
            invoice_date       = parse_date(data.get("invoiceDate"), "invoiceDate"),
            bill_to_address    = data.get("billToAddress"),
            ship_to_address    = data.get("shipToAddress"),
            bill_abstract_no   = data.get("certifiedBillNo"),
            bill_abstract_date = parse_date(data.get("certifiedBillDate"), "certifiedBillDate") if data.get("certifiedBillDate") else None,
            basic_amount         = basic_total,
            gst_amount           = gst_total,
            discount             = discount,
            round_off            = round_off,
            total_invoice_amount = total,
            workflow_status      = "Draft",
            current_level        = 0,
            locked               = False,
            created_by           = user_id,
        )
        db.session.add(srb)
        db.session.flush()

        for idx, row in enumerate(items, start=1):
            db.session.add(SaleReceiptItem(
                receipt_id      = srb.id,
                sl_no           = row.get("slNo") or idx,
                cc_code         = row.get("ccCode"),
                cc_name         = row.get("ccName"),
                booked_amount   = Decimal(str(row.get("bookedAmount")   or 0)),
                received_amount = Decimal(str(row.get("receivedAmount") or 0)),
                balance_amount  = Decimal(str(row.get("balanceAmount")  or 0)),
                current_amount  = Decimal(str(row.get("currentAmount")  or 0)),
            ))

        for g in gst_lines:
            db.session.add(SaleReceiptGst(
                receipt_id      = srb.id,
                gst_type        = g.get("gstType"),
                cc_code         = g.get("ccCode"),
                cc_name         = g.get("ccName"),
                percent         = Decimal(str(g.get("percent")        or 0)),
                booked_amount   = Decimal(str(g.get("bookedAmount")   or 0)),
                received_amount = Decimal(str(g.get("receivedAmount") or 0)),
                balance_amount  = Decimal(str(g.get("balanceAmount")  or 0)),
                current_amount  = Decimal(str(g.get("currentAmount")  or 0)) if g.get("isSelected") else Decimal('0'),
                is_selected     = bool(g.get("isSelected")),
            ))

        db.session.commit()

        return res("Sale receipt billing created", {
            "id":      srb.id,
            "srbNo":   srb.srb_no,
            "srbUuid": srb.srb_uuid,
        }, 201)

    except ValueError as e:
        db.session.rollback()
        return res(str(e), [], 400)
    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 4. LIST CHILD BILLINGS FOR A PARENT
# ══════════════════════════════════════════════════════════════════

def get_srb_list(data):
    try:
        receipt_id   = data.get("receiptId")
        project_code = data.get("projectCode")

        if not receipt_id:
            return res("receiptId required", [], 400)
        if not project_code:
            return res("projectCode required", [], 400)

        query = SaleReceiptBillingMaster.query.filter(
            SaleReceiptBillingMaster.receipt_id   == int(receipt_id),
            SaleReceiptBillingMaster.project_code == project_code,
        )

        if data.get("workflowStatus"):
            query = query.filter(
                SaleReceiptBillingMaster.workflow_status == data.get("workflowStatus")
            )

        rows = query.order_by(SaleReceiptBillingMaster.id.asc()).all()

        result = [
            {
                "id":                 r.id,
                "srbNo":              r.srb_no,
                "erpDocNumber":      r.erp_no,
                "certifiedBillNo":    r.bill_abstract_no,
                "basicAmount":        float(r.basic_amount         or 0),
                "gstAmount":          float(r.gst_amount           or 0),
                "totalInvoiceAmount": float(r.total_invoice_amount or 0),
                "workflowStatus":     r.workflow_status,
                "createdBy":          r.creator.username if r.creator else None,
                "createdAt":          _fmt_date(r.created_at),
            }
            for r in rows
        ]

        return res("Sale receipt billing list fetched", result, 200)

    except ValueError as e:
        db.session.rollback()
        return res(str(e), [], 400)
    except Exception as e:
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 5. DETAILS
# ══════════════════════════════════════════════════════════════════

def get_srb_details(srb_id):
    try:
        srb = SaleReceiptBillingMaster.query.get(srb_id)
        if not srb:
            return res("Sale receipt billing not found", [], 404)
        return res("Sale receipt billing details fetched", _build_srb_payload(srb), 200)
    except ValueError as e:
        db.session.rollback()
        return res(str(e), [], 400)
    except Exception as e:
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 6. EDIT
# ══════════════════════════════════════════════════════════════════

def edit_srb(srb_id, data, user_id):
    try:
        srb = SaleReceiptBillingMaster.query.get(srb_id)
        if not srb:
            return res("Sale receipt billing not found", [], 404)
        if srb.locked:
            return res("Sale receipt billing is locked and cannot be edited", [], 400)
        if srb.workflow_status not in ("Draft", "Reback"):
            return res("Only Draft or Reback records can be edited", [], 400)

        allowed = is_creator(srb.project_code, _MODULE, user_id)
        if not allowed:
            return res("You are not authorized to edit this billing", [], 403)

        items = data.get("items", [])
        if not items:
            return res("At least one BASIC item required", [], 400)

        gst_lines = data.get("gstLines", [])

        if data.get("srbDate"):
            srb.srb_date = parse_date(data.get("srbDate"), "srbDate")

        fields = [
            ("invoiceNo",       "invoice_no"),
            ("invoiceDate",     "invoice_date"),
            ("billToAddress",   "bill_to_address"),
            ("shipToAddress",   "ship_to_address"),
            ("certifiedBillNo", "bill_abstract_no"),
        ]
        for key, attr in fields:
            if data.get(key) is not None:
                setattr(srb, attr, data.get(key) or None)

        if data.get("certifiedBillDate"):
            srb.bill_abstract_date = parse_date(data.get("certifiedBillDate"), "certifiedBillDate")

        SaleReceiptItem.query.filter_by(receipt_id=srb.id).delete()
        SaleReceiptGst.query.filter_by(receipt_id=srb.id).delete()
        db.session.flush()

        basic_total = sum(Decimal(str(i.get("currentAmount") or 0)) for i in items)
        gst_total   = sum(
            Decimal(str(g.get("currentAmount") or 0))
            for g in gst_lines if g.get("isSelected")
        )
        discount  = Decimal(str(data.get("discount")  or 0))
        round_off = Decimal(str(data.get("roundOff")  or 0))

        for idx, row in enumerate(items, start=1):
            db.session.add(SaleReceiptItem(
                receipt_id      = srb.id,
                sl_no           = row.get("slNo") or idx,
                cc_code         = row.get("ccCode"),
                cc_name         = row.get("ccName"),
                booked_amount   = Decimal(str(row.get("bookedAmount")   or 0)),
                received_amount = Decimal(str(row.get("receivedAmount") or 0)),
                balance_amount  = Decimal(str(row.get("balanceAmount")  or 0)),
                current_amount  = Decimal(str(row.get("currentAmount")  or 0)),
            ))

        for g in gst_lines:
            db.session.add(SaleReceiptGst(
                receipt_id      = srb.id,
                gst_type        = g.get("gstType"),
                cc_code         = g.get("ccCode"),
                cc_name         = g.get("ccName"),
                percent         = Decimal(str(g.get("percent")        or 0)),
                booked_amount   = Decimal(str(g.get("bookedAmount")   or 0)),
                received_amount = Decimal(str(g.get("receivedAmount") or 0)),
                balance_amount  = Decimal(str(g.get("balanceAmount")  or 0)),
                current_amount  = Decimal(str(g.get("currentAmount")  or 0)) if g.get("isSelected") else Decimal('0'),
                is_selected     = bool(g.get("isSelected")),
            ))

        srb.basic_amount         = basic_total
        srb.gst_amount           = gst_total
        srb.discount             = discount
        srb.round_off            = round_off
        srb.total_invoice_amount = basic_total + gst_total - discount + round_off

        if srb.workflow_status == "Reback":
            srb.correction_sent_at = None

        srb.updated_by = user_id
        srb.updated_at = datetime.utcnow()

        db.session.commit()
        return res("Sale receipt billing updated", {"id": srb.id, "srbNo": srb.srb_no}, 200)

    except ValueError as e:
        db.session.rollback()
        return res(str(e), [], 400)
    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 7. SUBMIT
# ══════════════════════════════════════════════════════════════════

def submit_srb(srb_id, user_id):
    try:
        srb = SaleReceiptBillingMaster.query.get(srb_id)
        if not srb:
            return res("Sale receipt billing not found", [], 404)
        if srb.workflow_status not in ("Draft", "Reback"):
            return res("Sale receipt billing already submitted", [], 400)
        if not srb.items:
            return res("Sale receipt billing has no items", [], 400)

        if srb.workflow_status == "Reback":
            srb.current_level = 0

        first_level = get_first_approver(srb.project_code, _MODULE)

        if not first_level:
            srb.workflow_status   = "Approved"
            srb.locked            = True
            srb.approved_by       = user_id
            srb.submitted_at      = datetime.utcnow()
            srb.final_approved_at = datetime.utcnow()
        else:
            srb.workflow_status = f"Pending_L{first_level.level_no}"
            srb.current_level   = first_level.level_no
            srb.locked          = True
            srb.submitted_at    = datetime.utcnow()

        create_history(
            project_code = srb.project_code,
            module_code  = _MODULE,
            record_id    = srb.id,
            level_no     = srb.current_level,
            action       = "SUBMIT",
            action_by    = user_id,
        )

        srb.submitted_by = user_id
        srb.updated_by   = user_id
        srb.updated_at   = datetime.utcnow()

        db.session.commit()

        return res("Sale receipt billing submitted", {
            "id":             srb.id,
            "workflowStatus": srb.workflow_status,
        }, 200)

    except SQLAlchemyError as e:
        db.session.rollback()
        return res(str(e), [], 500)
    except ValueError as e:
        db.session.rollback()
        return res(str(e), [], 400)
    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 8. APPROVE
# ══════════════════════════════════════════════════════════════════

def approve_srb(srb_id, approved_by, comments=None):
    try:
        srb = SaleReceiptBillingMaster.query.get(srb_id)
        if not srb:
            return res("Sale receipt billing not found", [], 404)
        if not srb.workflow_status.startswith("Pending"):
            return res("Sale receipt billing is not pending approval", [], 400)

        allowed = is_current_approver(srb.project_code, _MODULE, srb.current_level, approved_by)
        if not allowed:
            return res("You are not the current approver", [], 403)

        gap = get_gap_level(srb.project_code, _MODULE, srb.current_level)
        if gap:
            return res(f"L{gap} is not assigned. Please assign it before approving.", [], 400)

        next_level = get_next_approver(srb.project_code, _MODULE, srb.current_level)

        if next_level:
            create_history(
                project_code = srb.project_code, module_code = _MODULE,
                record_id    = srb.id, level_no = srb.current_level,
                action       = "APPROVE", action_by = approved_by, comments = comments,
            )
            srb.current_level   = next_level.level_no
            srb.workflow_status = f"Pending_L{next_level.level_no}"
        else:
            create_history(
                project_code = srb.project_code, module_code = _MODULE,
                record_id    = srb.id, level_no = srb.current_level,
                action       = "FINAL_APPROVE", action_by = approved_by, comments = comments,
            )
            srb.workflow_status   = "Approved"
            srb.locked            = True
            srb.approved_by       = approved_by
            srb.final_approved_at = datetime.utcnow()

        srb.updated_by = approved_by
        srb.updated_at = datetime.utcnow()

        if srb.workflow_status == "Approved":
            db.session.flush()
            try:
                from app.modules.finance.accounting import post_document
                post_document("sale_receipt_billing", srb.id, approved_by)
            except Exception as e:
                import logging
                logging.getLogger(__name__).warning(f"Accounting posting failed for SRB {srb.id}: {e}")

        db.session.commit()

        return res("Sale receipt billing approved", {
            "id":             srb.id,
            "workflowStatus": srb.workflow_status,
        }, 200)

    except SQLAlchemyError as e:
        db.session.rollback()
        return res(str(e), [], 500)
    except ValueError as e:
        db.session.rollback()
        return res(str(e), [], 400)
    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 9. REBACK
# ══════════════════════════════════════════════════════════════════

def reback_srb(srb_id, reback_by, comments=None):
    try:
        srb = SaleReceiptBillingMaster.query.get(srb_id)
        if not srb:
            return res("Sale receipt billing not found", [], 404)
        if not srb.workflow_status.startswith("Pending"):
            return res("Sale receipt billing is not pending", [], 400)
        if not comments:
            return res("Comments required for reback", [], 400)

        allowed = is_current_approver(srb.project_code, _MODULE, srb.current_level, reback_by)
        if not allowed:
            return res("You are not the current approver", [], 403)

        srb.workflow_status    = "Reback"
        srb.locked             = False
        srb.correction_sent_at = datetime.utcnow()
        srb.updated_by         = reback_by
        srb.updated_at         = datetime.utcnow()

        create_history(
            project_code = srb.project_code, module_code = _MODULE,
            record_id    = srb.id, level_no = srb.current_level,
            action       = "REBACK", action_by = reback_by, comments = comments,
        )

        db.session.commit()

        return res("Sale receipt billing sent for correction", {
            "id":             srb.id,
            "workflowStatus": srb.workflow_status,
        }, 200)

    except SQLAlchemyError as e:
        db.session.rollback()
        return res(str(e), [], 500)
    except ValueError as e:
        db.session.rollback()
        return res(str(e), [], 400)
    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 10. REJECT
# ══════════════════════════════════════════════════════════════════

def reject_srb(srb_id, rejected_by, comments=None):
    try:
        srb = SaleReceiptBillingMaster.query.get(srb_id)
        if not srb:
            return res("Sale receipt billing not found", [], 404)
        if not srb.workflow_status.startswith("Pending"):
            return res("Sale receipt billing is not pending", [], 400)
        if not comments:
            return res("Comments required for rejection", [], 400)

        allowed = is_current_approver(srb.project_code, _MODULE, srb.current_level, rejected_by)
        if not allowed:
            return res("You are not the current approver", [], 403)

        srb.workflow_status = "Rejected"
        srb.locked          = True
        srb.rejected_at     = datetime.utcnow()
        srb.rejected_by     = rejected_by
        srb.status          = "Inactive"
        srb.updated_by      = rejected_by
        srb.updated_at      = datetime.utcnow()

        create_history(
            project_code = srb.project_code, module_code = _MODULE,
            record_id    = srb.id, level_no = srb.current_level,
            action       = "REJECT", action_by = rejected_by, comments = comments,
        )

        db.session.commit()

        return res("Sale receipt billing rejected", {
            "id":             srb.id,
            "workflowStatus": srb.workflow_status,
        }, 200)

    except SQLAlchemyError as e:
        db.session.rollback()
        return res(str(e), [], 500)
    except ValueError as e:
        db.session.rollback()
        return res(str(e), [], 400)
    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 11. HISTORY
# ══════════════════════════════════════════════════════════════════

def get_srb_history(srb_id):
    try:
        srb = SaleReceiptBillingMaster.query.get(srb_id)
        if not srb:
            return res("Sale receipt billing not found", [], 404)

        rows = get_history(_MODULE, srb.id)

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

        steps = get_approval_steps(srb.project_code, _MODULE, srb, rows)

        return res("History fetched", {
            "workflowStatus": srb.workflow_status,
            "currentLevel":   srb.current_level,
            "approvalSteps":  steps,
            "history":        history,
        }, 200)

    except ValueError as e:
        db.session.rollback()
        return res(str(e), [], 400)
    except Exception as e:
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 12. MY APPROVAL STATUS
# ══════════════════════════════════════════════════════════════════

def get_srb_my_approval_status(srb_id, user_id):
    try:
        srb = SaleReceiptBillingMaster.query.get(srb_id)
        if not srb:
            return res("Sale receipt billing not found", [], 404)
        data = get_my_approval_status(srb.project_code, _MODULE, srb, user_id)
        return res("Approval status", data, 200)
    except ValueError as e:
        db.session.rollback()
        return res(str(e), [], 400)
    except Exception as e:
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 13. UUID LOOKUP (public)
# ══════════════════════════════════════════════════════════════════

def get_srb_by_uuid(srb_uuid):
    try:
        srb = SaleReceiptBillingMaster.query.filter_by(srb_uuid=srb_uuid).first()
        if not srb:
            return res("Sale receipt billing not found", [], 404)
        return res("Sale receipt billing details fetched", _build_srb_payload(srb), 200)
    except ValueError as e:
        db.session.rollback()
        return res(str(e), [], 400)
    except Exception as e:
        return res(str(e), [], 500)


def delete_sale_receipt_billing(srb_id):
    try:
        srb = SaleReceiptBillingMaster.query.get(srb_id)
        if not srb:
            return res("Sale Receipt Billing not found", [], 404)
        if srb.locked:
            return res("Only draft Sale Receipt Billing can be deleted", [], 400)
        from app.modules.finance.accounting.deletion_guard import check_posted_before_delete
        can_delete, msg = check_posted_before_delete("SaleReceiptBillingMaster", srb_id)
        if not can_delete:
            return res(msg, [], 400)
        SaleReceiptGst.query.filter_by(receipt_id=srb.id).delete()
        SaleReceiptItem.query.filter_by(receipt_id=srb.id).delete()
        db.session.delete(srb)
        db.session.commit()
        from app.modules.delete_manager.service import auto_complete_check
        auto_complete_check("SALE_RECEIPT_BILLING", srb_id)
        return res("Sale Receipt Billing deleted successfully", [], 200)
    except SQLAlchemyError as e:
        db.session.rollback()
        return res(str(e), [], 500)
    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


def get_srb_list_by_project(params):
    """List all Sale Receipt Billings for a project (no receiptId required). Used for adjustment bill reference lookup."""
    try:
        project_code = (params.get("projectCode") or "").strip()
        if not project_code:
            return res("projectCode required", [], 400)

        query = SaleReceiptBillingMaster.query.filter(
            SaleReceiptBillingMaster.project_code == project_code,
        )

        if params.get("workflowStatus"):
            query = query.filter(
                SaleReceiptBillingMaster.workflow_status == params["workflowStatus"]
            )

        if params.get("search"):
            term = f"%{params['search']}%"
            query = query.filter(
                SaleReceiptBillingMaster.erp_no.ilike(term) |
                SaleReceiptBillingMaster.srb_no.ilike(term)
            )

        rows = query.order_by(SaleReceiptBillingMaster.id.desc()).all()

        result = [
            {
                "id":                 r.id,
                "srbNo":              r.srb_no,
                "erpDocNumber":       r.erp_no,
                "certifiedBillNo":    r.bill_abstract_no,
                "basicAmount":        float(r.basic_amount         or 0),
                "gstAmount":          float(r.gst_amount           or 0),
                "totalInvoiceAmount": float(r.total_invoice_amount or 0),
                "workflowStatus":     r.workflow_status,
                "createdAt":          _fmt_date(r.created_at),
            }
            for r in rows
        ]

        return res("Sale receipt billing list fetched", result, 200)

    except Exception as e:
        return res(str(e), [], 500)
