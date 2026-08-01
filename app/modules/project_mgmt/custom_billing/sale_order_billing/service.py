from sqlalchemy import func
from sqlalchemy.exc import SQLAlchemyError
from app.extensions import db
from datetime import datetime
import uuid as _uuid

from app.models.saleOrderMaster import SaleOrderMaster, SaleOrderItem
from app.models.ogSaleOrder import OgSaleOrderMaster, OgSaleOrderItem
from app.models.item import Item
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

_MODULE = "sale_order_billing"


# ══════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════

def _fmt_date(d):
    if d is None:
        return None
    if isinstance(d, datetime):
        return d.strftime("%Y-%m-%d %H:%M")
    return d.strftime("%Y-%m-%d")


def _item_display_code(item_obj):
    if not item_obj:
        return None
    cc = item_obj.cc_code.cc_code if item_obj.cc_code else ""
    return f"{cc}{item_obj.item_code}"


def _get_pre_certified(og_sale_order_no, project_code, exclude_so_id=None):
    q = (
        db.session.query(
            func.coalesce(func.sum(SaleOrderMaster.this_bill_claim), 0)
        )
        .filter(
            SaleOrderMaster.og_sale_order_no == og_sale_order_no,
            SaleOrderMaster.project_code     == project_code,
            SaleOrderMaster.workflow_status  == "Approved",
        )
    )
    if exclude_so_id:
        q = q.filter(SaleOrderMaster.id != exclude_so_id)
    return float(q.scalar())


def _get_billed_amount(og_sale_order_no, project_code):
    return float(
        db.session.query(
            func.coalesce(func.sum(SaleOrderMaster.this_bill_claim), 0)
        )
        .filter(
            SaleOrderMaster.og_sale_order_no == og_sale_order_no,
            SaleOrderMaster.project_code     == project_code,
            SaleOrderMaster.workflow_status  == "Approved",
        )
        .scalar()
    )


def _get_order_financials(og_sale_order_no, project_code):
    og_so = OgSaleOrderMaster.query.filter_by(
        og_sale_order_no=og_sale_order_no,
        project_code=project_code,
    ).first()
    if not og_so:
        return None
    return {
        "ogSaleOrderId":   og_so.id,
        "ogSaleOrderNo":   og_so.og_sale_order_no,
        "ogSaleOrderDate": _fmt_date(og_so.og_sale_order_date),
        "orderTitle":      og_so.order_title,
        "basicAmount":     float(og_so.basic_amount or 0),
        "gstAmount":       float(og_so.gst_amount   or 0),
        "totalAmount":     float(og_so.total_amount  or 0),
    }


def generate_sale_order_billing_no():
    last = (
        db.session.query(SaleOrderMaster.sale_order_no)
        .order_by(SaleOrderMaster.id.desc())
        .with_for_update()
        .first()
    )
    if last:
        try:
            num = int(last[0][3:])  # strip "SOB" prefix
        except Exception:
            num = 0
    else:
        num = 0
    return f"SOB{str(num + 1).zfill(3)}"


def _sob_list_under_og_so(og_sale_order_no, project_code):
    rows = (
        SaleOrderMaster.query
        .filter(
            SaleOrderMaster.og_sale_order_no == og_sale_order_no,
            SaleOrderMaster.project_code     == project_code,
        )
        .order_by(SaleOrderMaster.id.asc())
        .all()
    )
    return [
        {
            "id":             r.id,
            "saleOrderBillNo": r.sale_order_no,
            "saleOrderDate":   _fmt_date(r.sale_order_date),
            "thisBillClaim":   float(r.this_bill_claim or 0),
            "workflowStatus":  r.workflow_status,
        }
        for r in rows
    ]


# ══════════════════════════════════════════════════════════════════
# 1. OG SALE ORDER LOOKUP  (replaces order-lookup)
# ══════════════════════════════════════════════════════════════════

def get_order_lookup(data):
    try:
        og_sale_order_no = (data.get("ogSaleOrderNo") or "").strip()
        project_code     = (data.get("projectCode")   or "").strip()

        if not og_sale_order_no:
            return res("ogSaleOrderNo required", [], 400)
        if not project_code:
            return res("projectCode required", [], 400)

        og_so = OgSaleOrderMaster.query.filter_by(
            og_sale_order_no=og_sale_order_no,
            project_code=project_code,
        ).first()

        if not og_so:
            return res("OG Sale Order not found in this project", [], 404)

        # Build items with display code for pre-population
        og_items = []
        item_codes = [i.item_code for i in og_so.items if i.item_code]
        item_map   = {}
        if item_codes:
            objs = Item.query.filter(Item.item_code.in_(item_codes)).all()
            item_map = {obj.item_code: obj for obj in objs}

        for og_item in og_so.items:
            item_obj = item_map.get(og_item.item_code)
            og_items.append({
                "ogSaleOrderItemId": og_item.id,
                "slNo":              og_item.sl_no,
                "itemCode":          og_item.item_code,
                "itemDisplayCode":   _item_display_code(item_obj),
                "itemNameDesc":      og_item.item_name_desc,
                "unit":              og_item.unit,
                "orderQty":          float(og_item.order_qty  or 0),
                "rate":              float(og_item.rate        or 0),
                "gstPercent":        float(og_item.gst_percent or 0),
            })

        pre_certified = _get_pre_certified(og_sale_order_no, project_code)

        return res("OG Sale Order found", {
            "ogSaleOrderId":      og_so.id,
            "ogSaleOrderNo":      og_so.og_sale_order_no,
            "ogSaleOrderDate":    _fmt_date(og_so.og_sale_order_date),
            "orderTitle":         og_so.order_title,
            "orderValidity":      _fmt_date(og_so.order_validity),
            "basicAmount":        float(og_so.basic_amount or 0),
            "gstAmount":          float(og_so.gst_amount   or 0),
            "totalAmount":        float(og_so.total_amount  or 0),
            "preCertifiedAmount": pre_certified,
            "items":              og_items,
        }, 200)

    except Exception as e:
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 2. CREATE
# ══════════════════════════════════════════════════════════════════

def create_sale_order(data, user_id):
    try:
        project_code = data.get("projectCode")
        if not project_code:
            return res("projectCode required", [], 400)

        allowed = is_creator(project_code, _MODULE, user_id)
        if not allowed:
            return res("You are not a Sale Order Billing creator", [], 403)

        og_sale_order_no = (data.get("ogSaleOrderNo") or "").strip()
        if not og_sale_order_no:
            return res("ogSaleOrderNo required", [], 400)

        og_so = OgSaleOrderMaster.query.filter_by(
            og_sale_order_no=og_sale_order_no,
            project_code=project_code,
        ).first()
        if not og_so:
            return res("OG Sale Order not found in this project", [], 404)

        items = data.get("items", [])
        if not items:
            return res("At least one BOQ item required", [], 400)

        # Validate og_sale_order_item_ids
        og_item_ids = [row.get("ogSaleOrderItemId") for row in items if row.get("ogSaleOrderItemId")]
        og_item_map = {}
        if og_item_ids:
            og_item_objs = OgSaleOrderItem.query.filter(
                OgSaleOrderItem.id.in_(og_item_ids),
                OgSaleOrderItem.og_sale_order_id == og_so.id,
            ).all()
            og_item_map = {obj.id: obj for obj in og_item_objs}

        so_no         = generate_sale_order_billing_no()
        so_uuid       = str(_uuid.uuid4())
        pre_certified = _get_pre_certified(og_sale_order_no, project_code)

        so = SaleOrderMaster(
            sale_order_no        = so_no,
            sale_order_uuid      = so_uuid,
            sale_order_date      = data.get("saleOrderDate"),
            og_sale_order_no     = og_sale_order_no,
            og_sale_order_id     = og_so.id,
            project_code         = project_code,
            title                = data.get("title"),
            job_location         = data.get("jobLocation"),
            pre_certified_amount = pre_certified,
            attachment           = data.get("attachment"),
            workflow_status      = "Draft",
            current_level        = 0,
            locked               = False,
            created_by           = user_id,
        )

        db.session.add(so)
        db.session.flush()

        total_basic = 0
        total_gst   = 0

        for idx, row in enumerate(items, start=1):
            og_item_id = row.get("ogSaleOrderItemId")
            og_item    = og_item_map.get(og_item_id) if og_item_id else None

            # Snapshot from OG SO item
            item_code      = og_item.item_code      if og_item else row.get("itemCode")
            item_name_desc = og_item.item_name_desc  if og_item else row.get("itemNameDesc")
            unit           = og_item.unit            if og_item else row.get("unit")

            claim_qty   = float(row.get("claimQty")   or 0)
            rate        = float(row.get("rate")        or 0)
            amount      = round(claim_qty * rate, 2)
            gst_percent = float(
                row.get("gstPercent")
                if row.get("gstPercent") not in (None, "")
                else (og_item.gst_percent if og_item else 0)
            )
            gst_amount = round((amount * gst_percent) / 100, 2)

            db.session.add(SaleOrderItem(
                sale_order_id         = so.id,
                sl_no                 = row.get("slNo") or idx,
                og_sale_order_item_id = og_item_id,
                item_code             = item_code,
                item_name_desc        = item_name_desc,
                unit                  = unit,
                claim_qty             = claim_qty,
                rate                  = rate,
                amount                = amount,
                gst_percent           = gst_percent,
                gst_amount            = gst_amount,
            ))

            total_basic += amount
            total_gst   += gst_amount

        so.this_bill_claim = round(total_basic, 2)
        so.gst_amount      = round(total_gst, 2)
        so.total_claim     = round(pre_certified + total_basic, 2)

        db.session.commit()

        return res("Sale Order Bill created", {
            "id":            so.id,
            "saleOrderNo":   so.sale_order_no,
            "saleOrderUuid": so.sale_order_uuid,
        }, 201)

    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 3. LIST
# ══════════════════════════════════════════════════════════════════

def get_sale_order_list(data):
    try:
        project_code = data.get("projectCode")
        if not project_code:
            return res("projectCode required", [], 400)

        query = SaleOrderMaster.query.filter(
            SaleOrderMaster.project_code == project_code
        )

        if data.get("ogSaleOrderNo"):
            query = query.filter(
                SaleOrderMaster.og_sale_order_no.ilike(f"%{data.get('ogSaleOrderNo')}%")
            )
        if data.get("workflowStatus"):
            query = query.filter(SaleOrderMaster.workflow_status == data.get("workflowStatus"))
        if data.get("search"):
            term = f"%{data.get('search')}%"
            query = query.filter(
                db.or_(
                    SaleOrderMaster.sale_order_no.ilike(term),
                    SaleOrderMaster.og_sale_order_no.ilike(term),
                    SaleOrderMaster.title.ilike(term),
                )
            )

        rows = query.order_by(SaleOrderMaster.id.desc()).all()

        result = []
        for row in rows:
            billed   = _get_billed_amount(row.og_sale_order_no, row.project_code)
            order_fin = _get_order_financials(row.og_sale_order_no, row.project_code)
            sob_list  = _sob_list_under_og_so(row.og_sale_order_no, row.project_code)

            order_basic = order_fin["basicAmount"] if order_fin else 0
            job_balance = round(order_basic - billed, 2)

            result.append({
                "id":                        row.id,
                "saleOrderBillNo":           row.sale_order_no,
                "saleOrderDate":             _fmt_date(row.sale_order_date),
                "ogSaleOrderNo":             row.og_sale_order_no,
                "title":                     row.title,
                "jobLocation":               row.job_location,
                "preCertifiedAmount":        float(row.pre_certified_amount or 0),
                "thisBillClaim":             float(row.this_bill_claim      or 0),
                "gstAmount":                 float(row.gst_amount           or 0),
                "totalClaim":                float(row.total_claim          or 0),
                "orderTotalAmount":          order_fin["totalAmount"] if order_fin else 0,
                "orderBasicAmount":          order_fin["basicAmount"] if order_fin else 0,
                "billedAmount":              billed,
                "jobBalance":                job_balance,
                "workflowStatus":            row.workflow_status,
                "createdBy":                 row.creator.username if row.creator else None,
                "createdAt":                 _fmt_date(row.created_at),
                "saleOrderBillsUnderOgSo":   sob_list,
            })

        return res("Sale Order Bill list fetched", result, 200)

    except Exception as e:
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 4. DETAILS
# ══════════════════════════════════════════════════════════════════

def _serialize_items(items):
    item_codes = [i.item_code for i in items if i.item_code]
    item_map   = {}
    if item_codes:
        objs = Item.query.filter(Item.item_code.in_(item_codes)).all()
        item_map = {obj.item_code: obj for obj in objs}

    result = []
    for item in items:
        item_obj = item_map.get(item.item_code)
        result.append({
            "id":                  item.id,
            "slNo":                item.sl_no,
            "ogSaleOrderItemId":   item.og_sale_order_item_id,
            "itemCode":            item.item_code,
            "itemDisplayCode":     _item_display_code(item_obj),
            "itemNameDesc":        item.item_name_desc,
            "unit":                item.unit,
            "claimQty":            float(item.claim_qty   or 0),
            "rate":                float(item.rate         or 0),
            "amount":              float(item.amount       or 0),
            "gstPercent":          float(item.gst_percent  or 0),
            "gstAmount":           float(item.gst_amount   or 0),
        })
    return result


def _build_detail_payload(so):
    order_fin   = _get_order_financials(so.og_sale_order_no, so.project_code)
    billed      = _get_billed_amount(so.og_sale_order_no, so.project_code)
    sob_list    = _sob_list_under_og_so(so.og_sale_order_no, so.project_code)
    order_basic = order_fin["basicAmount"] if order_fin else 0
    job_balance = round(order_basic - billed, 2)

    return {
        "id":                      so.id,
        "saleOrderBillNo":         so.sale_order_no,
        "saleOrderUuid":           so.sale_order_uuid,
        "saleOrderDate":           _fmt_date(so.sale_order_date),
        "ogSaleOrderNo":           so.og_sale_order_no,
        "ogSaleOrderId":           so.og_sale_order_id,
        "projectCode":             so.project_code,
        "title":                   so.title,
        "jobLocation":             so.job_location,
        "preCertifiedAmount":      float(so.pre_certified_amount or 0),
        "thisBillClaim":           float(so.this_bill_claim      or 0),
        "gstAmount":               float(so.gst_amount           or 0),
        "totalClaim":              float(so.total_claim          or 0),
        "attachment":              so.attachment,
        "workflowStatus":          so.workflow_status,
        "currentLevel":            so.current_level,
        "locked":                  so.locked,
        "orderTotalAmount":        order_fin["totalAmount"] if order_fin else 0,
        "orderBasicAmount":        order_fin["basicAmount"] if order_fin else 0,
        "orderGstAmount":          order_fin["gstAmount"]   if order_fin else 0,
        "orderTitle":              order_fin["orderTitle"]  if order_fin else None,
        "billedAmount":            billed,
        "jobBalance":              job_balance,
        "createdBy":               so.creator.username  if so.creator  else None,
        "createdAt":               _fmt_date(so.created_at),
        "submittedBy":             so.submitter.username if so.submitter else None,
        "submittedAt":             _fmt_date(so.submitted_at),
        "approvedBy":              so.approver.username  if so.approver  else None,
        "finalApprovedAt":         _fmt_date(so.final_approved_at),
        "rejectedBy":              so.rejector.username  if so.rejector  else None,
        "rejectedAt":              _fmt_date(so.rejected_at),
        "items":                   _serialize_items(so.items),
        "saleOrderBillsUnderOgSo": sob_list,
    }


def get_sale_order_details(so_id):
    try:
        so = SaleOrderMaster.query.get(so_id)
        if not so:
            return res("Sale Order Bill not found", [], 404)
        return res("Sale Order Bill details fetched", _build_detail_payload(so), 200)
    except Exception as e:
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 5. EDIT
# ══════════════════════════════════════════════════════════════════

def edit_sale_order(so_id, data, user_id):
    try:
        so = SaleOrderMaster.query.get(so_id)
        if not so:
            return res("Sale Order Bill not found", [], 404)

        if so.locked:
            return res("Sale Order Bill is locked and cannot be edited", [], 400)
        if so.workflow_status not in ("Draft", "Reback"):
            return res("Only Draft or Reback records can be edited", [], 400)

        allowed = is_creator(so.project_code, _MODULE, user_id)
        if not allowed:
            return res("You are not a Sale Order Billing creator", [], 403)

        items = data.get("items", [])
        if not items:
            return res("At least one BOQ item required", [], 400)

        # Validate og_sale_order_item_ids
        og_so = OgSaleOrderMaster.query.get(so.og_sale_order_id)
        og_item_map = {}
        if og_so:
            og_item_ids = [row.get("ogSaleOrderItemId") for row in items if row.get("ogSaleOrderItemId")]
            if og_item_ids:
                og_item_objs = OgSaleOrderItem.query.filter(
                    OgSaleOrderItem.id.in_(og_item_ids),
                    OgSaleOrderItem.og_sale_order_id == og_so.id,
                ).all()
                og_item_map = {obj.id: obj for obj in og_item_objs}

        if data.get("saleOrderDate"):
            so.sale_order_date = data.get("saleOrderDate")
        if data.get("title") is not None:
            so.title = data.get("title")
        if data.get("jobLocation") is not None:
            so.job_location = data.get("jobLocation")
        if data.get("attachment") is not None:
            so.attachment = data.get("attachment")

        SaleOrderItem.query.filter_by(sale_order_id=so.id).delete()
        db.session.flush()

        total_basic = 0
        total_gst   = 0

        for idx, row in enumerate(items, start=1):
            og_item_id = row.get("ogSaleOrderItemId")
            og_item    = og_item_map.get(og_item_id) if og_item_id else None

            item_code      = og_item.item_code      if og_item else row.get("itemCode")
            item_name_desc = og_item.item_name_desc  if og_item else row.get("itemNameDesc")
            unit           = og_item.unit            if og_item else row.get("unit")

            claim_qty   = float(row.get("claimQty")   or 0)
            rate        = float(row.get("rate")        or 0)
            amount      = round(claim_qty * rate, 2)
            gst_percent = float(
                row.get("gstPercent")
                if row.get("gstPercent") not in (None, "")
                else (og_item.gst_percent if og_item else 0)
            )
            gst_amount = round((amount * gst_percent) / 100, 2)

            db.session.add(SaleOrderItem(
                sale_order_id         = so.id,
                sl_no                 = row.get("slNo") or idx,
                og_sale_order_item_id = og_item_id,
                item_code             = item_code,
                item_name_desc        = item_name_desc,
                unit                  = unit,
                claim_qty             = claim_qty,
                rate                  = rate,
                amount                = amount,
                gst_percent           = gst_percent,
                gst_amount            = gst_amount,
            ))

            total_basic += amount
            total_gst   += gst_amount

        pre_certified = _get_pre_certified(
            so.og_sale_order_no, so.project_code, exclude_so_id=so.id
        )

        so.this_bill_claim      = round(total_basic, 2)
        so.gst_amount           = round(total_gst, 2)
        so.pre_certified_amount = pre_certified
        so.total_claim          = round(pre_certified + total_basic, 2)

        if so.workflow_status == "Reback":
            so.correction_sent_at = None

        so.updated_by = user_id
        so.updated_at = datetime.utcnow()

        db.session.commit()

        return res("Sale Order Bill updated", {
            "id":          so.id,
            "saleOrderNo": so.sale_order_no,
        }, 200)

    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 6. SUBMIT
# ══════════════════════════════════════════════════════════════════

def submit_sale_order(so_id, submitted_by):
    try:
        so = SaleOrderMaster.query.get(so_id)
        if not so:
            return res("Sale Order Bill not found", [], 404)
        if so.workflow_status not in ("Draft", "Reback"):
            return res("Sale Order Bill already submitted", [], 400)
        if not so.items:
            return res("Sale Order Bill has no items", [], 400)

        if so.workflow_status == "Reback":
            so.current_level = 0

        first_level = get_first_approver(so.project_code, _MODULE)

        if not first_level:
            so.workflow_status   = "Approved"
            so.locked            = True
            so.approved_by       = submitted_by
            so.submitted_at      = datetime.utcnow()
            so.final_approved_at = datetime.utcnow()
        else:
            so.workflow_status = f"Pending_L{first_level.level_no}"
            so.current_level   = first_level.level_no
            so.locked          = True
            so.submitted_at    = datetime.utcnow()

        create_history(
            project_code=so.project_code,
            module_code=_MODULE,
            record_id=so.id,
            level_no=so.current_level,
            action="SUBMIT",
            action_by=submitted_by,
        )

        so.submitted_by = submitted_by
        so.updated_by   = submitted_by
        so.updated_at   = datetime.utcnow()

        db.session.commit()

        return res("Sale Order Bill submitted", {
            "id":             so.id,
            "saleOrderNo":    so.sale_order_no,
            "workflowStatus": so.workflow_status,
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

def approve_sale_order(so_id, approved_by, comments=None):
    try:
        so = SaleOrderMaster.query.get(so_id)
        if not so:
            return res("Sale Order Bill not found", [], 404)
        if not so.workflow_status.startswith("Pending"):
            return res("Sale Order Bill is not pending approval", [], 400)

        allowed = is_current_approver(so.project_code, _MODULE, so.current_level, approved_by)
        if not allowed:
            return res("You are not the current approver", [], 403)

        next_level = get_next_approver(so.project_code, _MODULE, so.current_level)

        if next_level:
            create_history(
                project_code=so.project_code, module_code=_MODULE,
                record_id=so.id, level_no=so.current_level,
                action="APPROVE", action_by=approved_by, comments=comments,
            )
            so.current_level   = next_level.level_no
            so.workflow_status = f"Pending_L{next_level.level_no}"
        else:
            create_history(
                project_code=so.project_code, module_code=_MODULE,
                record_id=so.id, level_no=so.current_level,
                action="FINAL_APPROVE", action_by=approved_by, comments=comments,
            )
            so.workflow_status   = "Approved"
            so.locked            = True
            so.approved_by       = approved_by
            so.final_approved_at = datetime.utcnow()

        so.updated_by = approved_by
        so.updated_at = datetime.utcnow()

        db.session.commit()

        return res("Sale Order Bill approved", {
            "id":             so.id,
            "workflowStatus": so.workflow_status,
            "currentLevel":   so.current_level,
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

def reback_sale_order(so_id, reback_by, comments=None):
    try:
        so = SaleOrderMaster.query.get(so_id)
        if not so:
            return res("Sale Order Bill not found", [], 404)
        if not so.workflow_status.startswith("Pending"):
            return res("Sale Order Bill is not pending", [], 400)
        if not comments:
            return res("Comments required for reback", [], 400)

        allowed = is_current_approver(so.project_code, _MODULE, so.current_level, reback_by)
        if not allowed:
            return res("You are not the current approver", [], 403)

        so.workflow_status    = "Reback"
        so.locked             = False
        so.correction_sent_at = datetime.utcnow()
        so.updated_by         = reback_by
        so.updated_at         = datetime.utcnow()

        create_history(
            project_code=so.project_code, module_code=_MODULE,
            record_id=so.id, level_no=so.current_level,
            action="REBACK", action_by=reback_by, comments=comments,
        )

        db.session.commit()

        return res("Sale Order Bill sent for correction", {
            "id":             so.id,
            "workflowStatus": so.workflow_status,
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

def reject_sale_order(so_id, rejected_by, comments=None):
    try:
        so = SaleOrderMaster.query.get(so_id)
        if not so:
            return res("Sale Order Bill not found", [], 404)
        if not so.workflow_status.startswith("Pending"):
            return res("Sale Order Bill is not pending", [], 400)
        if not comments:
            return res("Comments required for rejection", [], 400)

        allowed = is_current_approver(so.project_code, _MODULE, so.current_level, rejected_by)
        if not allowed:
            return res("You are not the current approver", [], 403)

        so.workflow_status = "Rejected"
        so.locked          = True
        so.rejected_at     = datetime.utcnow()
        so.rejected_by     = rejected_by
        so.status          = "Inactive"
        so.updated_by      = rejected_by
        so.updated_at      = datetime.utcnow()

        create_history(
            project_code=so.project_code, module_code=_MODULE,
            record_id=so.id, level_no=so.current_level,
            action="REJECT", action_by=rejected_by, comments=comments,
        )

        db.session.commit()

        return res("Sale Order Bill rejected", {
            "id":             so.id,
            "workflowStatus": so.workflow_status,
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

def get_sale_order_history(so_id):
    try:
        so = SaleOrderMaster.query.get(so_id)
        if not so:
            return res("Sale Order Bill not found", [], 404)

        rows = get_history(_MODULE, so.id)

        history = []
        for row in rows:
            history.append({
                "id":        row.id,
                "action":    row.action,
                "level":     row.level_no,
                "comments":  row.comments,
                "actionBy":  row.user.username if row.user else None,
                "createdAt": (
                    row.created_at.strftime("%Y-%m-%d %H:%M:%S")
                    if row.created_at else None
                ),
            })

        steps = get_approval_steps(so.project_code, _MODULE, so, rows)

        return res("History fetched", {
            "workflowStatus": so.workflow_status,
            "currentLevel":   so.current_level,
            "approvalSteps":  steps,
            "history":        history,
        }, 200)

    except Exception as e:
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 11. MY APPROVAL STATUS
# ══════════════════════════════════════════════════════════════════

def get_sale_order_my_approval_status(so_id, user_id):
    try:
        so = SaleOrderMaster.query.get(so_id)
        if not so:
            return res("Sale Order Bill not found", [], 404)
        data = get_my_approval_status(so.project_code, _MODULE, so, user_id)
        return res("Approval status", data, 200)
    except Exception as e:
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 12. GET BY UUID  (public — no JWT)
# ══════════════════════════════════════════════════════════════════

def get_sale_order_by_uuid(so_uuid):
    try:
        so = SaleOrderMaster.query.filter_by(sale_order_uuid=so_uuid).first()
        if not so:
            return res("Sale Order Bill not found", [], 404)
        return res("Sale Order Bill details fetched", _build_detail_payload(so), 200)
    except Exception as e:
        return res(str(e), [], 500)
