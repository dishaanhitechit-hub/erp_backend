from sqlalchemy import func
from sqlalchemy.exc import SQLAlchemyError
from app.extensions import db
from datetime import datetime, date
import uuid as _uuid
import json

from app.models.purchaseBill import PurchaseBillMaster, PurchaseBillItem, PurchaseBillGst
from app.models.brrMaster import BrrMaster
from app.models.brbMaster import BrbMaster, BrbItem
from app.models.orderMaster import OrderMaster, OrderItem
from app.models.ORDER_projectwork import ProjectWorkOrderMaster, ProjectWorkOrderItem
from app.models.grnMaster import GrnItem
from app.models.srnMaster import SrnMaster, SrnItem
from app.models.item import Item
from app.models.cc_code import CCCode
from app.models.category_group import CategoryMaster
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

_MODULE     = "purchases"
VALID_MODES = ("purchase_invoice", "proforma_invoice")


# ══════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════

def _fmt_date(d):
    if d is None:
        return None
    if isinstance(d, datetime):
        return d.strftime("%Y-%m-%d %H:%M")
    return d.strftime("%Y-%m-%d")


def _generate_purchase_bill_no():
    last = (
        db.session.query(PurchaseBillMaster.purchase_bill_no)
        .order_by(PurchaseBillMaster.id.desc())
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


def _cc_summary_from_brb(brb_id, billing_type):
    """CC-grouped basic amounts from a single BRB record."""
    if billing_type == "GRN":
        rows = (
            db.session.query(
                CCCode.cc_code,
                CCCode.cc_name,
                func.sum(BrbItem.amount).label("basic_amount"),
            )
            .join(GrnItem,   GrnItem.id   == BrbItem.grn_item_id)
            .join(OrderItem, OrderItem.id == GrnItem.order_item_id)
            .join(Item,      Item.item_code == OrderItem.item_code)
            .join(CCCode,    CCCode.id == Item.cc_code_id)
            .filter(BrbItem.brb_id == brb_id)
            .group_by(CCCode.cc_code, CCCode.cc_name)
            .all()
        )
    else:  # SRN
        rows = (
            db.session.query(
                CCCode.cc_code,
                CCCode.cc_name,
                func.sum(BrbItem.amount).label("basic_amount"),
            )
            .join(SrnItem,              SrnItem.id              == BrbItem.srn_item_id)
            .join(ProjectWorkOrderItem, ProjectWorkOrderItem.id == SrnItem.pw_order_item_id)
            .join(Item,                 Item.item_code          == ProjectWorkOrderItem.item_code)
            .join(CCCode,               CCCode.id               == Item.cc_code_id)
            .filter(BrbItem.brb_id == brb_id)
            .group_by(CCCode.cc_code, CCCode.cc_name)
            .all()
        )
    return [
        {
            "ccCode":      r.cc_code,
            "ccName":      r.cc_name,
            "basicAmount": float(r.basic_amount or 0),
        }
        for r in rows
    ]


def _build_detail_payload(bill):
    order_no = None
    if bill.order:
        order_no = bill.order.order_no
    elif bill.pw_order:
        order_no = bill.pw_order.order_no

    return {
        "id":                  bill.id,
        "purchaseBillNo":      bill.purchase_bill_no,
        "purchaseBillUuid":    bill.purchase_bill_uuid,
        "mode":                bill.mode,
        "processingDate":      _fmt_date(bill.processing_date),
        "projectCode":         bill.project_code,
        "vendorId":            bill.vendor_id,
        "vendorName":          bill.vendor.ledger_name if bill.vendor else None,
        "orderType":           bill.order_type,
        "orderId":             bill.order_id,
        "pwOrderId":           bill.pw_order_id,
        "orderNo":             order_no,
        "brrId":               bill.brr_id,
        "brrNo":               bill.brr_no,
        "brrDate":             _fmt_date(bill.brr_date),
        "vendorBillNo":        bill.vendor_bill_no,
        "vendorBillDate":      _fmt_date(bill.vendor_bill_date),
        "remarks":             bill.remarks,
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
                "id":         g.id,
                "gstType":    g.gst_type,
                "ccCode":     g.cc_code,
                "ccName":     g.cc_name,
                "description":g.description,
                "percent":    float(g.percent    or 0),
                "gstAmount":  float(g.gst_amount or 0),
                "isSelected": g.is_selected,
            }
            for g in bill.gst_lines
        ],
    }


# ══════════════════════════════════════════════════════════════════
# 1. VENDOR ORDERS LOOKUP
# ══════════════════════════════════════════════════════════════════

def get_vendor_orders(data):
    """
    Returns Approved orders for a vendor.
    Optional filter: orderType=GRN | SRN (omit for both).
    Each row includes categoryCode, subCategory info, and costHead.
    """
    try:
        vendor_id         = data.get("vendorId")
        project_code      = data.get("projectCode")
        order_type_filter = (data.get("orderType") or "").strip().upper()

        if not vendor_id:
            return res("vendorId required", [], 400)
        if not project_code:
            return res("projectCode required", [], 400)

        result = []

        # ── GRN orders (order_master) ─────────────────────────────
        if order_type_filter in ("GRN", ""):
            grn_orders = (
                OrderMaster.query
                .filter(
                    OrderMaster.vendor_id       == int(vendor_id),
                    OrderMaster.project_code    == project_code,
                    OrderMaster.workflow_status == "Approved",
                )
                .order_by(OrderMaster.id.desc())
                .all()
            )
            for o in grn_orders:
                sub_name = (
                    o.sub_category.category_name
                    if o.sub_category else o.sub_code
                )
                result.append({
                    "id":              o.id,
                    "orderNo":         o.order_no,
                    "orderDate":       _fmt_date(o.order_date),
                    "orderType":       "GRN",
                    "categoryCode":    o.category_code,
                    "subCategoryCode": o.sub_code,
                    "subCategoryName": sub_name,
                    "costHead":        o.cost_head,
                })

        # ── SRN orders (pw_order_master) ──────────────────────────
        if order_type_filter in ("SRN", ""):
            srn_orders = (
                ProjectWorkOrderMaster.query
                .filter(
                    ProjectWorkOrderMaster.vendor_id       == int(vendor_id),
                    ProjectWorkOrderMaster.project_code    == project_code,
                    ProjectWorkOrderMaster.workflow_status == "Approved",
                )
                .order_by(ProjectWorkOrderMaster.id.desc())
                .all()
            )

            # Batch-resolve sub_codes → category names in one query
            all_codes = set()
            for o in srn_orders:
                if o.sub_codes:
                    try:
                        all_codes.update(json.loads(o.sub_codes))
                    except Exception:
                        pass

            code_name_map = {}
            if all_codes:
                cats = CategoryMaster.query.filter(
                    CategoryMaster.fixed_code.in_(list(all_codes))
                ).all()
                code_name_map = {c.fixed_code: c.category_name for c in cats}

            for o in srn_orders:
                sub_codes, sub_names = [], []
                if o.sub_codes:
                    try:
                        sub_codes = json.loads(o.sub_codes)
                        sub_names = [code_name_map.get(c, c) for c in sub_codes]
                    except Exception:
                        pass

                result.append({
                    "id":               o.id,
                    "orderNo":          o.order_no,
                    "orderDate":        _fmt_date(o.order_date),
                    "orderType":        "SRN",
                    "categoryCode":     o.category_code,
                    "subCategoryCodes": sub_codes,
                    "subCategoryNames": sub_names,
                    "costHead":         o.cost_head,
                })

        return res("Orders fetched", result, 200)

    except Exception as e:
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 2. BRR LIST FOR ORDER
# ══════════════════════════════════════════════════════════════════

def get_brr_list_for_order(data):
    try:
        order_id     = data.get("orderId")
        order_type   = (data.get("orderType") or "GRN").upper()
        project_code = data.get("projectCode")

        if not order_id:
            return res("orderId required", [], 400)
        if not project_code:
            return res("projectCode required", [], 400)

        if order_type == "GRN":
            rows = (
                BrrMaster.query
                .filter(
                    BrrMaster.order_id        == int(order_id),
                    BrrMaster.project_code    == project_code,
                    BrrMaster.workflow_status == "Approved",
                )
                .order_by(BrrMaster.id.desc())
                .all()
            )
        else:
            rows = (
                BrrMaster.query
                .filter(
                    BrrMaster.pw_order_id     == int(order_id),
                    BrrMaster.project_code    == project_code,
                    BrrMaster.workflow_status == "Approved",
                )
                .order_by(BrrMaster.id.desc())
                .all()
            )

        result = [
            {
                "id":          r.id,
                "brrNo":       r.brr_no,
                "brrDate":     _fmt_date(r.brr_date),
                "orderType":   r.order_type,
                "partyBillNo": r.party_bill_no,
                "partyDate":   _fmt_date(r.party_date),
                "basicAmount": float(r.basic_amount or 0),
                "totalAmount": float(r.total_amount or 0),
            }
            for r in rows
        ]

        return res("BRR list fetched", result, 200)

    except Exception as e:
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 3. BRR ITEMS GROUPED BY CC CODE
# ══════════════════════════════════════════════════════════════════

def get_brr_items_grouped(data):
    try:
        brr_id       = data.get("brrId")
        project_code = data.get("projectCode")

        if not brr_id:
            return res("brrId required", [], 400)
        if not project_code:
            return res("projectCode required", [], 400)

        brr = BrrMaster.query.filter_by(
            id           = int(brr_id),
            project_code = project_code,
        ).first()

        if not brr:
            return res("BRR not found", [], 404)

        billing_type = brr.order_type or "GRN"

        brbs = (
            BrbMaster.query
            .filter_by(brr_id=brr.id, workflow_status="Approved")
            .all()
        )

        cc_totals = {}
        cc_order  = []

        for brb in brbs:
            for row in _cc_summary_from_brb(brb.id, billing_type):
                key = row["ccCode"] or "none"
                if key not in cc_totals:
                    cc_totals[key] = {
                        "ccCode":      row["ccCode"],
                        "ccName":      row["ccName"],
                        "basicAmount": 0.0,
                    }
                    cc_order.append(key)
                cc_totals[key]["basicAmount"] += row["basicAmount"]

        items = [
            {
                "slNo":        idx + 1,
                "ccCode":      cc_totals[k]["ccCode"],
                "ccName":      cc_totals[k]["ccName"],
                "description": "",
                "hsnSac":      "",
                "basicAmount": round(cc_totals[k]["basicAmount"], 2),
            }
            for idx, k in enumerate(cc_order)
        ]

        return res("BRR items grouped by CC Code", {
            "brrId":          brr.id,
            "brrNo":          brr.brr_no,
            "brrDate":        _fmt_date(brr.brr_date),
            "orderType":      billing_type,
            "vendorBillNo":   brr.party_bill_no,
            "vendorBillDate": _fmt_date(brr.party_date),
            "items":          items,
        }, 200)

    except Exception as e:
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 4. CREATE
# ══════════════════════════════════════════════════════════════════

def create_purchase_bill(data, user_id):
    try:
        project_code = data.get("projectCode")
        if not project_code:
            return res("projectCode required", [], 400)

        mode = (data.get("mode") or "").strip()
        if mode not in VALID_MODES:
            return res(f"mode must be one of {VALID_MODES}", [], 400)

        allowed = is_creator(project_code, _MODULE, user_id)
        if not allowed:
            return res("You are not authorized to create purchase bills", [], 403)

        brr_id = data.get("brrId")
        if not brr_id:
            return res("brrId required", [], 400)

        brr = BrrMaster.query.filter_by(
            id           = int(brr_id),
            project_code = project_code,
        ).first()
        if not brr:
            return res("BRR not found", [], 404)

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

        purchase_bill_no   = _generate_purchase_bill_no()
        purchase_bill_uuid = str(_uuid.uuid4())

        bill = PurchaseBillMaster(
            purchase_bill_no   = purchase_bill_no,
            purchase_bill_uuid = purchase_bill_uuid,
            mode               = mode,
            processing_date    = data.get("processingDate") or date.today(),
            project_code       = project_code,
            vendor_id          = brr.vendor_id,
            order_type         = brr.order_type,
            order_id           = brr.order_id,
            pw_order_id        = brr.pw_order_id,
            brr_id             = brr.id,
            brr_no             = brr.brr_no,
            brr_date           = brr.brr_date,
            vendor_bill_no     = brr.party_bill_no,
            vendor_bill_date   = brr.party_date,
            remarks            = data.get("remarks"),
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
            db.session.add(PurchaseBillItem(
                purchase_bill_id = bill.id,
                sl_no            = row.get("slNo") or idx,
                cc_code          = row.get("ccCode"),
                cc_name          = row.get("ccName"),
                description      = row.get("description"),
                hsn_sac          = row.get("hsnSac"),
                basic_amount     = float(row.get("basicAmount") or 0),
            ))

        for g in gst_lines:
            db.session.add(PurchaseBillGst(
                purchase_bill_id = bill.id,
                gst_type         = g.get("gstType"),
                cc_code          = g.get("ccCode"),
                cc_name          = g.get("ccName"),
                description      = g.get("description"),
                percent          = float(g.get("percent")   or 0),
                gst_amount       = float(g.get("gstAmount") or 0) if g.get("isSelected") else 0,
                is_selected      = bool(g.get("isSelected")),
            ))

        db.session.commit()

        return res("Purchase bill created", {
            "id":               bill.id,
            "purchaseBillNo":   bill.purchase_bill_no,
            "purchaseBillUuid": bill.purchase_bill_uuid,
            "mode":             bill.mode,
        }, 201)

    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 5. LIST
# ══════════════════════════════════════════════════════════════════

def get_purchase_bill_list(data):
    try:
        project_code = data.get("projectCode")
        if not project_code:
            return res("projectCode required", [], 400)

        query = PurchaseBillMaster.query.filter(
            PurchaseBillMaster.project_code == project_code
        )

        if data.get("mode"):
            query = query.filter(PurchaseBillMaster.mode == data.get("mode"))
        if data.get("workflowStatus"):
            query = query.filter(PurchaseBillMaster.workflow_status == data.get("workflowStatus"))
        if data.get("vendorId"):
            query = query.filter(PurchaseBillMaster.vendor_id == int(data.get("vendorId")))
        if data.get("search"):
            term = f"%{data.get('search')}%"
            query = query.filter(
                db.or_(
                    PurchaseBillMaster.purchase_bill_no.ilike(term),
                    PurchaseBillMaster.brr_no.ilike(term),
                    PurchaseBillMaster.vendor_bill_no.ilike(term),
                )
            )

        rows = query.order_by(PurchaseBillMaster.id.desc()).all()

        result = [
            {
                "id":                 r.id,
                "purchaseBillNo":     r.purchase_bill_no,
                "mode":               r.mode,
                "processingDate":     _fmt_date(r.processing_date),
                "vendorId":           r.vendor_id,
                "vendorName":         r.vendor.ledger_name if r.vendor else None,
                "brrNo":              r.brr_no,
                "vendorBillNo":       r.vendor_bill_no,
                "basicAmount":        float(r.basic_amount         or 0),
                "gstAmount":          float(r.gst_amount           or 0),
                "totalInvoiceAmount": float(r.total_invoice_amount or 0),
                "workflowStatus":     r.workflow_status,
                "createdBy":          r.creator.username if r.creator else None,
                "createdAt":          _fmt_date(r.created_at),
            }
            for r in rows
        ]

        return res("Purchase bill list fetched", result, 200)

    except Exception as e:
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 6. DETAILS
# ══════════════════════════════════════════════════════════════════

def get_purchase_bill_details(bill_id):
    try:
        bill = PurchaseBillMaster.query.get(bill_id)
        if not bill:
            return res("Purchase bill not found", [], 404)
        return res("Purchase bill details fetched", _build_detail_payload(bill), 200)
    except Exception as e:
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 7. EDIT
# ══════════════════════════════════════════════════════════════════

def edit_purchase_bill(bill_id, data, user_id):
    try:
        bill = PurchaseBillMaster.query.get(bill_id)
        if not bill:
            return res("Purchase bill not found", [], 404)
        if bill.locked:
            return res("Purchase bill is locked and cannot be edited", [], 400)
        if bill.workflow_status not in ("Draft", "Reback"):
            return res("Only Draft or Reback records can be edited", [], 400)

        allowed = is_creator(bill.project_code, _MODULE, user_id)
        if not allowed:
            return res("You are not authorized to edit purchase bills", [], 403)

        items = data.get("items", [])
        if not items:
            return res("At least one BASIC item required", [], 400)

        gst_lines = data.get("gstLines", [])

        if data.get("mode") in VALID_MODES:
            bill.mode = data.get("mode")
        if data.get("remarks") is not None:
            bill.remarks = data.get("remarks")

        PurchaseBillItem.query.filter_by(purchase_bill_id=bill.id).delete()
        PurchaseBillGst.query.filter_by(purchase_bill_id=bill.id).delete()
        db.session.flush()

        basic_total = sum(float(i.get("basicAmount") or 0) for i in items)
        gst_total   = sum(
            float(g.get("gstAmount") or 0)
            for g in gst_lines if g.get("isSelected")
        )
        discount  = float(data.get("discount")  or 0)
        round_off = float(data.get("roundOff")  or 0)

        for idx, row in enumerate(items, start=1):
            db.session.add(PurchaseBillItem(
                purchase_bill_id = bill.id,
                sl_no            = row.get("slNo") or idx,
                cc_code          = row.get("ccCode"),
                cc_name          = row.get("ccName"),
                description      = row.get("description"),
                hsn_sac          = row.get("hsnSac"),
                basic_amount     = float(row.get("basicAmount") or 0),
            ))

        for g in gst_lines:
            db.session.add(PurchaseBillGst(
                purchase_bill_id = bill.id,
                gst_type         = g.get("gstType"),
                cc_code          = g.get("ccCode"),
                cc_name          = g.get("ccName"),
                description      = g.get("description"),
                percent          = float(g.get("percent")   or 0),
                gst_amount       = float(g.get("gstAmount") or 0) if g.get("isSelected") else 0,
                is_selected      = bool(g.get("isSelected")),
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

        return res("Purchase bill updated", {
            "id":             bill.id,
            "purchaseBillNo": bill.purchase_bill_no,
        }, 200)

    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 8. SUBMIT
# ══════════════════════════════════════════════════════════════════

def submit_purchase_bill(bill_id, user_id):
    try:
        bill = PurchaseBillMaster.query.get(bill_id)
        if not bill:
            return res("Purchase bill not found", [], 404)
        if bill.workflow_status not in ("Draft", "Reback"):
            return res("Purchase bill already submitted", [], 400)
        if not bill.items:
            return res("Purchase bill has no items", [], 400)

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

        return res("Purchase bill submitted", {
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
# 9. APPROVE
# ══════════════════════════════════════════════════════════════════

def approve_purchase_bill(bill_id, approved_by, comments=None):
    try:
        bill = PurchaseBillMaster.query.get(bill_id)
        if not bill:
            return res("Purchase bill not found", [], 404)
        if not bill.workflow_status.startswith("Pending"):
            return res("Purchase bill is not pending approval", [], 400)

        allowed = is_current_approver(bill.project_code, _MODULE, bill.current_level, approved_by)
        if not allowed:
            return res("You are not the current approver", [], 403)

        gap = get_gap_level(bill.project_code, _MODULE, bill.current_level)
        if gap:
            return res(f"L{gap} is not assigned. Please assign it before approving.", [], 400)

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

        return res("Purchase bill approved", {
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
# 10. REBACK
# ══════════════════════════════════════════════════════════════════

def reback_purchase_bill(bill_id, reback_by, comments=None):
    try:
        bill = PurchaseBillMaster.query.get(bill_id)
        if not bill:
            return res("Purchase bill not found", [], 404)
        if not bill.workflow_status.startswith("Pending"):
            return res("Purchase bill is not pending", [], 400)
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

        return res("Purchase bill sent for correction", {
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
# 11. REJECT
# ══════════════════════════════════════════════════════════════════

def reject_purchase_bill(bill_id, rejected_by, comments=None):
    try:
        bill = PurchaseBillMaster.query.get(bill_id)
        if not bill:
            return res("Purchase bill not found", [], 404)
        if not bill.workflow_status.startswith("Pending"):
            return res("Purchase bill is not pending", [], 400)
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

        return res("Purchase bill rejected", {
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
# 12. HISTORY
# ══════════════════════════════════════════════════════════════════

def get_purchase_bill_history(bill_id):
    try:
        bill = PurchaseBillMaster.query.get(bill_id)
        if not bill:
            return res("Purchase bill not found", [], 404)

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
# 13. MY APPROVAL STATUS
# ══════════════════════════════════════════════════════════════════

def get_purchase_bill_my_approval_status(bill_id, user_id):
    try:
        bill = PurchaseBillMaster.query.get(bill_id)
        if not bill:
            return res("Purchase bill not found", [], 404)
        data = get_my_approval_status(bill.project_code, _MODULE, bill, user_id)
        return res("Approval status", data, 200)
    except Exception as e:
        return res(str(e), [], 500)
