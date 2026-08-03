from sqlalchemy.exc import SQLAlchemyError
from app.extensions import db
from datetime import datetime
import uuid as _uuid

from app.models.saleBill import SaleBillMaster, SaleBillItem, SaleBillGst
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

_MODULE      = "sale_bill"
VALID_MODES  = ("sale_invoice", "proforma_invoice")


# ══════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════

def _fmt_date(d):
    if d is None:
        return None
    if isinstance(d, datetime):
        return d.strftime("%Y-%m-%d %H:%M")
    return d.strftime("%Y-%m-%d")


def generate_sale_bill_no():
    last = (
        db.session.query(SaleBillMaster.sale_bill_no)
        .order_by(SaleBillMaster.id.desc())
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

    groups = {}  # cc_code_id (or "none") → aggregated data
    order  = []  # preserve insertion order

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
            "description": "",
            "hsnSac":      "",
            "basicAmount": round(groups[k]["basicAmount"], 2),
        }
        for idx, k in enumerate(order)
    ]


def _build_detail_payload(bill):
    return {
        "id":                  bill.id,
        "saleBillNo":          bill.sale_bill_no,
        "saleBillUuid":        bill.sale_bill_uuid,
        "mode":                bill.mode,
        "invoiceDate":         _fmt_date(bill.invoice_date),
        "referenceNo":         bill.reference_no,
        "referenceDate":       _fmt_date(bill.reference_date),
        "saleOrderNo":         bill.sale_order_no,
        "saleOrderId":         bill.sale_order_id,
        "certifiedBillId":     bill.certified_bill_id,
        "certifiedBillNo":     bill.certified_bill_no,
        "projectCode":         bill.project_code,
        "billToAddress":       bill.bill_to_address,
        "shipToAddress":       bill.ship_to_address,
        "billAbstractNo":      bill.bill_abstract_no,
        "billAbstractDate":    _fmt_date(bill.bill_abstract_date),
        "bankAc":              bill.bank_ac,
        "paymentTerms":        bill.payment_terms,
        "declaration":         bill.declaration,
        "basicAmount":         float(bill.basic_amount         or 0),
        "gstAmount":           float(bill.gst_amount           or 0),
        "discount":            float(bill.discount             or 0),
        "roundOff":            float(bill.round_off            or 0),
        "totalInvoiceAmount":  float(bill.total_invoice_amount or 0),
        "workflowStatus":      bill.workflow_status,
        "currentLevel":        bill.current_level,
        "locked":              bill.locked,
        "createdBy":           bill.creator.username   if bill.creator   else None,
        "createdAt":           _fmt_date(bill.created_at),
        "submittedBy":         bill.submitter.username if bill.submitter else None,
        "submittedAt":         _fmt_date(bill.submitted_at),
        "approvedBy":          bill.approver.username  if bill.approver  else None,
        "finalApprovedAt":     _fmt_date(bill.final_approved_at),
        "rejectedBy":          bill.rejector.username  if bill.rejector  else None,
        "rejectedAt":          _fmt_date(bill.rejected_at),
        "items": [
            {
                "id":          i.id,
                "slNo":        i.sl_no,
                "ccCode":      i.cc_code,
                "ccName":      i.cc_name,
                "description": i.description,
                "hsnSac":      i.hsn_sac,
                "basicAmount": float(i.basic_amount or 0),
            }
            for i in bill.items
        ],
        "gstLines": [
            {
                "id":          g.id,
                "gstType":     g.gst_type,
                "ccCode":      g.cc_code,
                "ccName":      g.cc_name,
                "description": g.description,
                "percent":     float(g.percent    or 0),
                "gstAmount":   float(g.gst_amount or 0),
                "isSelected":  g.is_selected,
            }
            for g in bill.gst_lines
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
# 2. ITEMS GROUPED BY CC CODE
# ══════════════════════════════════════════════════════════════════

def get_certified_bill_items_grouped(data):
    """Fetch items from an approved certified bill, grouped by CC Code."""
    try:
        certified_bill_id = data.get("certifiedBillId")
        project_code      = (data.get("projectCode") or "").strip()

        if not certified_bill_id:
            return res("certifiedBillId required", [], 400)
        if not project_code:
            return res("projectCode required", [], 400)

        bill = BillingMaster.query.filter_by(
            id             = int(certified_bill_id),
            mode           = "sale_certified_bill",
            workflow_status= "Approved",
        ).first()

        if not bill:
            return res("Approved certified bill not found", [], 404)
        if bill.project_code != project_code:
            return res("Certified bill does not belong to this project", [], 403)

        grouped = _group_by_cc(bill.items)

        return res("Items grouped by CC Code", {
            "certifiedBillId": bill.id,
            "certifiedBillNo": bill.billing_no,
            "ogSaleOrderNo":   bill.og_sale_order_no,
            "items":           grouped,
        }, 200)

    except Exception as e:
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 3. CREATE
# ══════════════════════════════════════════════════════════════════

def create_sale_bill(data, user_id):
    try:
        project_code = data.get("projectCode")
        if not project_code:
            return res("projectCode required", [], 400)

        mode = (data.get("mode") or "").strip()
        if mode not in VALID_MODES:
            return res(f"mode must be one of {VALID_MODES}", [], 400)

        allowed = is_creator(project_code, _MODULE, user_id)
        if not allowed:
            return res("You are not authorized to create sale bills", [], 403)

        certified_bill_id = data.get("certifiedBillId")
        if not certified_bill_id:
            return res("certifiedBillId required", [], 400)

        cert_bill = BillingMaster.query.filter_by(
            id             = int(certified_bill_id),
            mode           = "sale_certified_bill",
            workflow_status= "Approved",
        ).first()
        if not cert_bill:
            return res("Approved certified bill not found", [], 404)
        if cert_bill.project_code != project_code:
            return res("Certified bill does not belong to this project", [], 403)

        items = data.get("items", [])
        if not items:
            return res("At least one BASIC item required", [], 400)

        gst_lines = data.get("gstLines", [])

        basic_total = sum(float(i.get("basicAmount") or 0) for i in items)
        gst_total   = sum(
            float(g.get("gstAmount") or 0)
            for g in gst_lines if g.get("isSelected")
        )
        discount  = float(data.get("discount")  or 0)
        round_off = float(data.get("roundOff")  or 0)
        total     = round(basic_total + gst_total - discount + round_off, 2)

        sale_bill_no   = generate_sale_bill_no()
        sale_bill_uuid = str(_uuid.uuid4())

        bill = SaleBillMaster(
            sale_bill_no       = sale_bill_no,
            sale_bill_uuid     = sale_bill_uuid,
            mode               = mode,
            invoice_date       = data.get("invoiceDate"),
            reference_no       = data.get("referenceNo"),
            reference_date     = data.get("referenceDate"),
            sale_order_no      = cert_bill.og_sale_order_no,
            sale_order_id      = cert_bill.og_sale_order_id,
            certified_bill_id  = cert_bill.id,
            certified_bill_no  = cert_bill.billing_no,
            project_code       = project_code,
            bill_to_address    = data.get("billToAddress"),
            ship_to_address    = data.get("shipToAddress"),
            bill_abstract_no   = data.get("billAbstractNo"),
            bill_abstract_date = data.get("billAbstractDate"),
            bank_ac            = data.get("bankAc"),
            payment_terms      = data.get("paymentTerms"),
            declaration        = data.get("declaration"),
            basic_amount         = round(basic_total, 2),
            gst_amount           = round(gst_total,   2),
            discount             = discount,
            round_off            = round_off,
            total_invoice_amount = total,
            workflow_status = "Draft",
            current_level   = 0,
            locked          = False,
            created_by      = user_id,
        )
        db.session.add(bill)
        db.session.flush()

        for idx, row in enumerate(items, start=1):
            db.session.add(SaleBillItem(
                sale_bill_id = bill.id,
                sl_no        = row.get("slNo") or idx,
                cc_code      = row.get("ccCode"),
                cc_name      = row.get("ccName"),
                description  = row.get("description"),
                hsn_sac      = row.get("hsnSac"),
                basic_amount = float(row.get("basicAmount") or 0),
            ))

        for g in gst_lines:
            db.session.add(SaleBillGst(
                sale_bill_id = bill.id,
                gst_type     = g.get("gstType"),
                cc_code      = g.get("ccCode"),
                cc_name      = g.get("ccName"),
                description  = g.get("description"),
                percent      = float(g.get("percent")   or 0),
                gst_amount   = float(g.get("gstAmount") or 0) if g.get("isSelected") else 0,
                is_selected  = bool(g.get("isSelected")),
            ))

        db.session.commit()

        return res("Sale bill created", {
            "id":           bill.id,
            "saleBillNo":   bill.sale_bill_no,
            "saleBillUuid": bill.sale_bill_uuid,
            "mode":         bill.mode,
        }, 201)

    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 4. LIST
# ══════════════════════════════════════════════════════════════════

def get_sale_bill_list(data):
    try:
        project_code = data.get("projectCode")
        if not project_code:
            return res("projectCode required", [], 400)

        query = SaleBillMaster.query.filter(
            SaleBillMaster.project_code == project_code
        )

        if data.get("mode"):
            query = query.filter(SaleBillMaster.mode == data.get("mode"))
        if data.get("workflowStatus"):
            query = query.filter(SaleBillMaster.workflow_status == data.get("workflowStatus"))
        if data.get("saleOrderNo"):
            query = query.filter(
                SaleBillMaster.sale_order_no.ilike(f"%{data.get('saleOrderNo')}%")
            )
        if data.get("search"):
            term = f"%{data.get('search')}%"
            query = query.filter(
                db.or_(
                    SaleBillMaster.sale_bill_no.ilike(term),
                    SaleBillMaster.sale_order_no.ilike(term),
                    SaleBillMaster.certified_bill_no.ilike(term),
                )
            )

        rows = query.order_by(SaleBillMaster.id.desc()).all()

        result = [
            {
                "id":                 r.id,
                "saleBillNo":         r.sale_bill_no,
                "mode":               r.mode,
                "invoiceDate":        _fmt_date(r.invoice_date),
                "saleOrderNo":        r.sale_order_no,
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

        return res("Sale bill list fetched", result, 200)

    except Exception as e:
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 5. DETAILS
# ══════════════════════════════════════════════════════════════════

def get_sale_bill_details(bill_id):
    try:
        bill = SaleBillMaster.query.get(bill_id)
        if not bill:
            return res("Sale bill not found", [], 404)
        return res("Sale bill details fetched", _build_detail_payload(bill), 200)
    except Exception as e:
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 6. EDIT
# ══════════════════════════════════════════════════════════════════

def edit_sale_bill(bill_id, data, user_id):
    try:
        bill = SaleBillMaster.query.get(bill_id)
        if not bill:
            return res("Sale bill not found", [], 404)
        if bill.locked:
            return res("Sale bill is locked and cannot be edited", [], 400)
        if bill.workflow_status not in ("Draft", "Reback"):
            return res("Only Draft or Reback records can be edited", [], 400)

        allowed = is_creator(bill.project_code, _MODULE, user_id)
        if not allowed:
            return res("You are not authorized to edit sale bills", [], 403)

        items = data.get("items", [])
        if not items:
            return res("At least one BASIC item required", [], 400)

        gst_lines = data.get("gstLines", [])

        # Update header fields
        if data.get("mode") and data.get("mode") in VALID_MODES:
            bill.mode = data.get("mode")
        if data.get("invoiceDate"):
            bill.invoice_date = data.get("invoiceDate")
        if data.get("referenceNo") is not None:
            bill.reference_no = data.get("referenceNo")
        if data.get("referenceDate") is not None:
            bill.reference_date = data.get("referenceDate")
        if data.get("billToAddress") is not None:
            bill.bill_to_address = data.get("billToAddress")
        if data.get("shipToAddress") is not None:
            bill.ship_to_address = data.get("shipToAddress")
        if data.get("billAbstractNo") is not None:
            bill.bill_abstract_no = data.get("billAbstractNo")
        if data.get("billAbstractDate") is not None:
            bill.bill_abstract_date = data.get("billAbstractDate")
        if data.get("bankAc") is not None:
            bill.bank_ac = data.get("bankAc")
        if data.get("paymentTerms") is not None:
            bill.payment_terms = data.get("paymentTerms")
        if data.get("declaration") is not None:
            bill.declaration = data.get("declaration")

        # Rebuild items and GST
        SaleBillItem.query.filter_by(sale_bill_id=bill.id).delete()
        SaleBillGst.query.filter_by(sale_bill_id=bill.id).delete()
        db.session.flush()

        basic_total = sum(float(i.get("basicAmount") or 0) for i in items)
        gst_total   = sum(
            float(g.get("gstAmount") or 0)
            for g in gst_lines if g.get("isSelected")
        )
        discount  = float(data.get("discount")  or 0)
        round_off = float(data.get("roundOff")  or 0)

        for idx, row in enumerate(items, start=1):
            db.session.add(SaleBillItem(
                sale_bill_id = bill.id,
                sl_no        = row.get("slNo") or idx,
                cc_code      = row.get("ccCode"),
                cc_name      = row.get("ccName"),
                description  = row.get("description"),
                hsn_sac      = row.get("hsnSac"),
                basic_amount = float(row.get("basicAmount") or 0),
            ))

        for g in gst_lines:
            db.session.add(SaleBillGst(
                sale_bill_id = bill.id,
                gst_type     = g.get("gstType"),
                cc_code      = g.get("ccCode"),
                cc_name      = g.get("ccName"),
                description  = g.get("description"),
                percent      = float(g.get("percent")   or 0),
                gst_amount   = float(g.get("gstAmount") or 0) if g.get("isSelected") else 0,
                is_selected  = bool(g.get("isSelected")),
            ))

        bill.basic_amount         = round(basic_total, 2)
        bill.gst_amount           = round(gst_total,   2)
        bill.discount             = discount
        bill.round_off            = round_off
        bill.total_invoice_amount = round(basic_total + gst_total - discount + round_off, 2)

        if bill.workflow_status == "Reback":
            bill.correction_sent_at = None

        bill.updated_by = user_id
        bill.updated_at = datetime.utcnow()

        db.session.commit()

        return res("Sale bill updated", {"id": bill.id, "saleBillNo": bill.sale_bill_no}, 200)

    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 7. SUBMIT
# ══════════════════════════════════════════════════════════════════

def submit_sale_bill(bill_id, user_id):
    try:
        bill = SaleBillMaster.query.get(bill_id)
        if not bill:
            return res("Sale bill not found", [], 404)
        if bill.workflow_status not in ("Draft", "Reback"):
            return res("Sale bill already submitted", [], 400)
        if not bill.items:
            return res("Sale bill has no items", [], 400)

        if bill.workflow_status == "Reback":
            bill.current_level = 0

        first_level = get_first_approver(bill.project_code, _MODULE)

        if not first_level:
            bill.workflow_status   = "Approved"
            bill.locked            = True
            bill.approved_by       = user_id
            bill.submitted_at      = datetime.utcnow()
            bill.final_approved_at = datetime.utcnow()
        else:
            bill.workflow_status = f"Pending_L{first_level.level_no}"
            bill.current_level   = first_level.level_no
            bill.locked          = True
            bill.submitted_at    = datetime.utcnow()

        create_history(
            project_code=bill.project_code,
            module_code=_MODULE,
            record_id=bill.id,
            level_no=bill.current_level,
            action="SUBMIT",
            action_by=user_id,
        )

        bill.submitted_by = user_id
        bill.updated_by   = user_id
        bill.updated_at   = datetime.utcnow()

        db.session.commit()

        return res("Sale bill submitted", {
            "id":             bill.id,
            "workflowStatus": bill.workflow_status,
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

def approve_sale_bill(bill_id, approved_by, comments=None):
    try:
        bill = SaleBillMaster.query.get(bill_id)
        if not bill:
            return res("Sale bill not found", [], 404)
        if not bill.workflow_status.startswith("Pending"):
            return res("Sale bill is not pending approval", [], 400)

        allowed = is_current_approver(bill.project_code, _MODULE, bill.current_level, approved_by)
        if not allowed:
            return res("You are not the current approver", [], 403)

        next_level = get_next_approver(bill.project_code, _MODULE, bill.current_level)

        if next_level:
            create_history(
                project_code=bill.project_code, module_code=_MODULE,
                record_id=bill.id, level_no=bill.current_level,
                action="APPROVE", action_by=approved_by, comments=comments,
            )
            bill.current_level   = next_level.level_no
            bill.workflow_status = f"Pending_L{next_level.level_no}"
        else:
            create_history(
                project_code=bill.project_code, module_code=_MODULE,
                record_id=bill.id, level_no=bill.current_level,
                action="FINAL_APPROVE", action_by=approved_by, comments=comments,
            )
            bill.workflow_status   = "Approved"
            bill.locked            = True
            bill.approved_by       = approved_by
            bill.final_approved_at = datetime.utcnow()

        bill.updated_by = approved_by
        bill.updated_at = datetime.utcnow()

        db.session.commit()

        return res("Sale bill approved", {
            "id":             bill.id,
            "workflowStatus": bill.workflow_status,
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

def reback_sale_bill(bill_id, reback_by, comments=None):
    try:
        bill = SaleBillMaster.query.get(bill_id)
        if not bill:
            return res("Sale bill not found", [], 404)
        if not bill.workflow_status.startswith("Pending"):
            return res("Sale bill is not pending", [], 400)
        if not comments:
            return res("Comments required for reback", [], 400)

        allowed = is_current_approver(bill.project_code, _MODULE, bill.current_level, reback_by)
        if not allowed:
            return res("You are not the current approver", [], 403)

        bill.workflow_status    = "Reback"
        bill.locked             = False
        bill.correction_sent_at = datetime.utcnow()
        bill.updated_by         = reback_by
        bill.updated_at         = datetime.utcnow()

        create_history(
            project_code=bill.project_code, module_code=_MODULE,
            record_id=bill.id, level_no=bill.current_level,
            action="REBACK", action_by=reback_by, comments=comments,
        )

        db.session.commit()

        return res("Sale bill sent for correction", {
            "id":             bill.id,
            "workflowStatus": bill.workflow_status,
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

def reject_sale_bill(bill_id, rejected_by, comments=None):
    try:
        bill = SaleBillMaster.query.get(bill_id)
        if not bill:
            return res("Sale bill not found", [], 404)
        if not bill.workflow_status.startswith("Pending"):
            return res("Sale bill is not pending", [], 400)
        if not comments:
            return res("Comments required for rejection", [], 400)

        allowed = is_current_approver(bill.project_code, _MODULE, bill.current_level, rejected_by)
        if not allowed:
            return res("You are not the current approver", [], 403)

        bill.workflow_status = "Rejected"
        bill.locked          = True
        bill.rejected_at     = datetime.utcnow()
        bill.rejected_by     = rejected_by
        bill.status          = "Inactive"
        bill.updated_by      = rejected_by
        bill.updated_at      = datetime.utcnow()

        create_history(
            project_code=bill.project_code, module_code=_MODULE,
            record_id=bill.id, level_no=bill.current_level,
            action="REJECT", action_by=rejected_by, comments=comments,
        )

        db.session.commit()

        return res("Sale bill rejected", {
            "id":             bill.id,
            "workflowStatus": bill.workflow_status,
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

def get_sale_bill_history(bill_id):
    try:
        bill = SaleBillMaster.query.get(bill_id)
        if not bill:
            return res("Sale bill not found", [], 404)

        rows = get_history(_MODULE, bill.id)

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

        steps = get_approval_steps(bill.project_code, _MODULE, bill, rows)

        return res("History fetched", {
            "workflowStatus": bill.workflow_status,
            "currentLevel":   bill.current_level,
            "approvalSteps":  steps,
            "history":        history,
        }, 200)

    except Exception as e:
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 12. MY APPROVAL STATUS
# ══════════════════════════════════════════════════════════════════

def get_sale_bill_my_approval_status(bill_id, user_id):
    try:
        bill = SaleBillMaster.query.get(bill_id)
        if not bill:
            return res("Sale bill not found", [], 404)
        data = get_my_approval_status(bill.project_code, _MODULE, bill, user_id)
        return res("Approval status", data, 200)
    except Exception as e:
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 13. UUID LOOKUP (public)
# ══════════════════════════════════════════════════════════════════

def get_sale_bill_by_uuid(sale_bill_uuid):
    try:
        bill = SaleBillMaster.query.filter_by(sale_bill_uuid=sale_bill_uuid).first()
        if not bill:
            return res("Sale bill not found", [], 404)
        return res("Sale bill details fetched", _build_detail_payload(bill), 200)
    except Exception as e:
        return res(str(e), [], 500)
