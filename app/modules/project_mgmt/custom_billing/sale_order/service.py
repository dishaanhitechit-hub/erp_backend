from sqlalchemy import func
from sqlalchemy.exc import SQLAlchemyError
from app.extensions import db
from datetime import datetime
import uuid as _uuid

from app.models.saleOrderMaster import SaleOrderMaster, SaleOrderItem
from app.models.orderMaster import OrderMaster
from app.models.ORDER_projectwork import ProjectWorkOrderMaster
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

_MODULE = "sale_order"


# ══════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════

def _fmt_date(d):
    if d is None:
        return None
    if isinstance(d, datetime):
        return d.strftime("%Y-%m-%d %H:%M")
    return d.strftime("%Y-%m-%d")


def _get_pre_certified(order_no, order_type, project_code, exclude_so_id=None):
    q = (
        db.session.query(
            func.coalesce(func.sum(SaleOrderMaster.this_bill_claim), 0)
        )
        .filter(
            SaleOrderMaster.order_no == order_no,
            SaleOrderMaster.order_type == order_type,
            SaleOrderMaster.project_code == project_code,
            SaleOrderMaster.workflow_status == "Approved",
        )
    )
    if exclude_so_id:
        q = q.filter(SaleOrderMaster.id != exclude_so_id)
    return float(q.scalar())


def _get_billed_amount(order_no, order_type, project_code):
    result = (
        db.session.query(
            func.coalesce(func.sum(SaleOrderMaster.this_bill_claim), 0)
        )
        .filter(
            SaleOrderMaster.order_no == order_no,
            SaleOrderMaster.order_type == order_type,
            SaleOrderMaster.project_code == project_code,
            SaleOrderMaster.workflow_status == "Approved",
        )
        .scalar()
    )
    return float(result)


def _get_order_financials(order_no, order_type, project_code):
    if order_type == "pw":
        order = ProjectWorkOrderMaster.query.filter_by(
            order_no=order_no,
            project_code=project_code
        ).first()
    else:
        order = OrderMaster.query.filter_by(
            order_no=order_no,
            project_code=project_code
        ).first()

    if not order:
        return None

    return {
        "orderId":     order.id,
        "orderNo":     order.order_no,
        "orderDate":   _fmt_date(order.order_date),
        "basicAmount": float(order.basic_amount or 0),
        "gstAmount":   float(order.gst_amount   or 0),
        "totalAmount": float(order.total_amount  or 0),
    }


def generate_sale_order_no():
    last = (
        db.session.query(SaleOrderMaster.sale_order_no)
        .order_by(SaleOrderMaster.id.desc())
        .with_for_update()
        .first()
    )
    if last:
        try:
            num = int(last[0][2:])  # strip "SO" prefix
        except Exception:
            num = 0
    else:
        num = 0
    return f"SO{str(num + 1).zfill(3)}"


def _so_list_under_order(order_no, order_type, project_code):
    rows = (
        SaleOrderMaster.query
        .filter(
            SaleOrderMaster.order_no     == order_no,
            SaleOrderMaster.order_type   == order_type,
            SaleOrderMaster.project_code == project_code,
        )
        .order_by(SaleOrderMaster.id.asc())
        .all()
    )
    return [
        {
            "id":             r.id,
            "saleOrderNo":    r.sale_order_no,
            "saleOrderDate":  _fmt_date(r.sale_order_date),
            "thisBillClaim":  float(r.this_bill_claim or 0),
            "workflowStatus": r.workflow_status,
        }
        for r in rows
    ]


# ══════════════════════════════════════════════════════════════════
# 1. ORDER LOOKUP
# ══════════════════════════════════════════════════════════════════

def get_order_lookup(data):
    try:
        order_no     = (data.get("orderNo")   or "").strip()
        project_code = (data.get("projectCode") or "").strip()
        order_type   = (data.get("orderType")  or "normal").lower()

        if not order_no:
            return res("orderNo required", [], 400)
        if not project_code:
            return res("projectCode required", [], 400)
        if order_type not in ("normal", "pw"):
            return res("orderType must be 'normal' or 'pw'", [], 400)

        if order_type == "pw":
            order = ProjectWorkOrderMaster.query.filter_by(
                order_no=order_no, project_code=project_code
            ).first()
        else:
            order = OrderMaster.query.filter_by(
                order_no=order_no, project_code=project_code
            ).first()

        if not order:
            return res("Order not found in this project", [], 404)

        pre_certified = _get_pre_certified(order_no, order_type, project_code)

        return res("Order found", {
            "orderId":            order.id,
            "orderNo":            order.order_no,
            "orderDate":          _fmt_date(order.order_date),
            "basicAmount":        float(order.basic_amount or 0),
            "gstAmount":          float(order.gst_amount   or 0),
            "totalAmount":        float(order.total_amount  or 0),
            "preCertifiedAmount": pre_certified,
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
            return res("You are not a Sale Order creator", [], 403)

        order_no   = (data.get("orderNo")   or "").strip()
        order_type = (data.get("orderType") or "normal").lower()

        if not order_no:
            return res("orderNo required", [], 400)
        if order_type not in ("normal", "pw"):
            return res("orderType must be 'normal' or 'pw'", [], 400)

        if order_type == "pw":
            order = ProjectWorkOrderMaster.query.filter_by(
                order_no=order_no, project_code=project_code
            ).first()
        else:
            order = OrderMaster.query.filter_by(
                order_no=order_no, project_code=project_code
            ).first()

        if not order:
            return res("Order not found in this project", [], 404)

        items = data.get("items", [])
        if not items:
            return res("At least one BOQ item required", [], 400)

        so_no         = generate_sale_order_no()
        so_uuid       = str(_uuid.uuid4())
        pre_certified = _get_pre_certified(order_no, order_type, project_code)

        so = SaleOrderMaster(
            sale_order_no    = so_no,
            sale_order_uuid  = so_uuid,
            sale_order_date  = data.get("saleOrderDate"),
            order_no         = order_no,
            order_id         = order.id,
            order_type       = order_type,
            project_code     = project_code,
            title            = data.get("title"),
            job_location     = data.get("jobLocation"),
            pre_certified_amount = pre_certified,
            attachment       = data.get("attachment"),
            workflow_status  = "Draft",
            current_level    = 0,
            locked           = False,
            created_by       = user_id,
        )

        db.session.add(so)
        db.session.flush()

        total_basic = 0
        total_gst   = 0

        for idx, row in enumerate(items, start=1):
            claim_qty   = float(row.get("claimQty")   or 0)
            rate        = float(row.get("rate")        or 0)
            amount      = round(claim_qty * rate, 2)
            gst_percent = float(row.get("gstPercent") or 0)
            gst_amount  = round((amount * gst_percent) / 100, 2)

            db.session.add(SaleOrderItem(
                sale_order_id  = so.id,
                sl_no          = row.get("slNo") or idx,
                item_code      = row.get("itemCode") or None,
                item_name_desc = row.get("itemNameDesc"),
                unit           = row.get("unit"),
                claim_qty      = claim_qty,
                rate           = rate,
                amount         = amount,
                gst_percent    = gst_percent,
                gst_amount     = gst_amount,
            ))

            total_basic += amount
            total_gst   += gst_amount

        so.this_bill_claim = round(total_basic, 2)
        so.gst_amount      = round(total_gst, 2)
        so.total_claim     = round(pre_certified + total_basic, 2)

        db.session.commit()

        return res("Sale Order created", {
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

        if data.get("orderNo"):
            query = query.filter(
                SaleOrderMaster.order_no.ilike(f"%{data.get('orderNo')}%")
            )
        if data.get("orderType"):
            query = query.filter(SaleOrderMaster.order_type == data.get("orderType"))
        if data.get("workflowStatus"):
            query = query.filter(SaleOrderMaster.workflow_status == data.get("workflowStatus"))
        if data.get("search"):
            term = f"%{data.get('search')}%"
            query = query.filter(
                db.or_(
                    SaleOrderMaster.sale_order_no.ilike(term),
                    SaleOrderMaster.order_no.ilike(term),
                    SaleOrderMaster.title.ilike(term),
                )
            )

        rows = query.order_by(SaleOrderMaster.id.desc()).all()

        result = []
        for row in rows:
            billed    = _get_billed_amount(row.order_no, row.order_type, row.project_code)
            order_fin = _get_order_financials(row.order_no, row.order_type, row.project_code)
            so_list   = _so_list_under_order(row.order_no, row.order_type, row.project_code)

            order_basic = order_fin["basicAmount"] if order_fin else 0
            job_balance = round(order_basic - billed, 2)

            result.append({
                "id":                  row.id,
                "saleOrderNo":         row.sale_order_no,
                "saleOrderDate":       _fmt_date(row.sale_order_date),
                "orderNo":             row.order_no,
                "orderType":           row.order_type,
                "title":               row.title,
                "jobLocation":         row.job_location,
                "preCertifiedAmount":  float(row.pre_certified_amount or 0),
                "thisBillClaim":       float(row.this_bill_claim      or 0),
                "gstAmount":           float(row.gst_amount           or 0),
                "totalClaim":          float(row.total_claim          or 0),
                "orderTotalAmount":    order_fin["totalAmount"] if order_fin else 0,
                "orderBasicAmount":    order_fin["basicAmount"] if order_fin else 0,
                "orderGstAmount":      order_fin["gstAmount"]   if order_fin else 0,
                "billedAmount":        billed,
                "jobBalance":          job_balance,
                "workflowStatus":      row.workflow_status,
                "createdBy":           row.creator.username if row.creator else None,
                "createdAt":           _fmt_date(row.created_at),
                "saleOrdersUnderOrder": so_list,
            })

        return res("Sale Order list fetched", result, 200)

    except Exception as e:
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 4. DETAILS
# ══════════════════════════════════════════════════════════════════

def get_sale_order_details(so_id):
    try:
        so = SaleOrderMaster.query.get(so_id)
        if not so:
            return res("Sale Order not found", [], 404)

        items = []
        for item in so.items:
            items.append({
                "id":           item.id,
                "slNo":         item.sl_no,
                "itemCode":     item.item_code,
                "itemNameDesc": item.item_name_desc,
                "unit":         item.unit,
                "claimQty":     float(item.claim_qty   or 0),
                "rate":         float(item.rate         or 0),
                "amount":       float(item.amount       or 0),
                "gstPercent":   float(item.gst_percent  or 0),
                "gstAmount":    float(item.gst_amount   or 0),
            })

        order_fin   = _get_order_financials(so.order_no, so.order_type, so.project_code)
        billed      = _get_billed_amount(so.order_no, so.order_type, so.project_code)
        so_list     = _so_list_under_order(so.order_no, so.order_type, so.project_code)
        order_basic = order_fin["basicAmount"] if order_fin else 0
        job_balance = round(order_basic - billed, 2)

        data = {
            "id":                  so.id,
            "saleOrderNo":         so.sale_order_no,
            "saleOrderDate":       _fmt_date(so.sale_order_date),
            "orderNo":             so.order_no,
            "orderId":             so.order_id,
            "orderType":           so.order_type,
            "projectCode":         so.project_code,
            "title":               so.title,
            "jobLocation":         so.job_location,
            "preCertifiedAmount":  float(so.pre_certified_amount or 0),
            "thisBillClaim":       float(so.this_bill_claim      or 0),
            "gstAmount":           float(so.gst_amount           or 0),
            "totalClaim":          float(so.total_claim          or 0),
            "attachment":          so.attachment,
            "workflowStatus":      so.workflow_status,
            "currentLevel":        so.current_level,
            "locked":              so.locked,
            "orderTotalAmount":    order_fin["totalAmount"] if order_fin else 0,
            "orderBasicAmount":    order_fin["basicAmount"] if order_fin else 0,
            "orderGstAmount":      order_fin["gstAmount"]   if order_fin else 0,
            "billedAmount":        billed,
            "jobBalance":          job_balance,
            "createdBy":           so.creator.username  if so.creator  else None,
            "createdAt":           _fmt_date(so.created_at),
            "submittedBy":         so.submitter.username if so.submitter else None,
            "submittedAt":         _fmt_date(so.submitted_at),
            "approvedBy":          so.approver.username  if so.approver  else None,
            "finalApprovedAt":     _fmt_date(so.final_approved_at),
            "rejectedBy":          so.rejector.username  if so.rejector  else None,
            "rejectedAt":          _fmt_date(so.rejected_at),
            "items":               items,
            "saleOrdersUnderOrder": so_list,
        }

        return res("Sale Order details fetched", data, 200)

    except Exception as e:
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 5. EDIT
# ══════════════════════════════════════════════════════════════════

def edit_sale_order(so_id, data, user_id):
    try:
        so = SaleOrderMaster.query.get(so_id)
        if not so:
            return res("Sale Order not found", [], 404)

        if so.locked:
            return res("Sale Order is locked and cannot be edited", [], 400)
        if so.workflow_status not in ("Draft", "Reback"):
            return res("Only Draft or Reback Sale Orders can be edited", [], 400)

        allowed = is_creator(so.project_code, _MODULE, user_id)
        if not allowed:
            return res("You are not a Sale Order creator", [], 403)

        items = data.get("items", [])
        if not items:
            return res("At least one BOQ item required", [], 400)

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
            claim_qty   = float(row.get("claimQty")   or 0)
            rate        = float(row.get("rate")        or 0)
            amount      = round(claim_qty * rate, 2)
            gst_percent = float(row.get("gstPercent") or 0)
            gst_amount  = round((amount * gst_percent) / 100, 2)

            db.session.add(SaleOrderItem(
                sale_order_id  = so.id,
                sl_no          = row.get("slNo") or idx,
                item_code      = row.get("itemCode") or None,
                item_name_desc = row.get("itemNameDesc"),
                unit           = row.get("unit"),
                claim_qty      = claim_qty,
                rate           = rate,
                amount         = amount,
                gst_percent    = gst_percent,
                gst_amount     = gst_amount,
            ))

            total_basic += amount
            total_gst   += gst_amount

        pre_certified = _get_pre_certified(
            so.order_no, so.order_type, so.project_code, exclude_so_id=so.id
        )

        so.this_bill_claim       = round(total_basic, 2)
        so.gst_amount            = round(total_gst, 2)
        so.pre_certified_amount  = pre_certified
        so.total_claim           = round(pre_certified + total_basic, 2)

        if so.workflow_status == "Reback":
            so.correction_sent_at = None

        so.updated_by = user_id
        so.updated_at = datetime.utcnow()

        db.session.commit()

        return res("Sale Order updated", {
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
            return res("Sale Order not found", [], 404)
        if so.workflow_status not in ("Draft", "Reback"):
            return res("Sale Order already submitted", [], 400)
        if not so.items:
            return res("Sale Order has no items", [], 400)

        if so.workflow_status == "Reback":
            so.current_level = 0

        first_level = get_first_approver(so.project_code, _MODULE)

        if not first_level:
            so.workflow_status    = "Approved"
            so.locked             = True
            so.approved_by        = submitted_by
            so.submitted_at       = datetime.utcnow()
            so.final_approved_at  = datetime.utcnow()
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

        return res("Sale Order submitted", {
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
            return res("Sale Order not found", [], 404)
        if not so.workflow_status.startswith("Pending"):
            return res("Sale Order is not pending approval", [], 400)

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
            so.workflow_status    = "Approved"
            so.locked             = True
            so.approved_by        = approved_by
            so.final_approved_at  = datetime.utcnow()

        so.updated_by = approved_by
        so.updated_at = datetime.utcnow()

        db.session.commit()

        return res("Sale Order approved", {
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
            return res("Sale Order not found", [], 404)
        if not so.workflow_status.startswith("Pending"):
            return res("Sale Order is not pending", [], 400)
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

        return res("Sale Order sent for correction", {
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
            return res("Sale Order not found", [], 404)
        if not so.workflow_status.startswith("Pending"):
            return res("Sale Order is not pending", [], 400)
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

        return res("Sale Order rejected", {
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
            return res("Sale Order not found", [], 404)

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
            return res("Sale Order not found", [], 404)
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
            return res("Sale Order not found", [], 404)

        items = []
        for item in so.items:
            items.append({
                "id":           item.id,
                "slNo":         item.sl_no,
                "itemCode":     item.item_code,
                "itemNameDesc": item.item_name_desc,
                "unit":         item.unit,
                "claimQty":     float(item.claim_qty   or 0),
                "rate":         float(item.rate         or 0),
                "amount":       float(item.amount       or 0),
                "gstPercent":   float(item.gst_percent  or 0),
                "gstAmount":    float(item.gst_amount   or 0),
            })

        order_fin   = _get_order_financials(so.order_no, so.order_type, so.project_code)
        billed      = _get_billed_amount(so.order_no, so.order_type, so.project_code)
        so_list     = _so_list_under_order(so.order_no, so.order_type, so.project_code)
        order_basic = order_fin["basicAmount"] if order_fin else 0
        job_balance = round(order_basic - billed, 2)

        data = {
            "id":                  so.id,
            "saleOrderNo":         so.sale_order_no,
            "saleOrderUuid":       so.sale_order_uuid,
            "saleOrderDate":       _fmt_date(so.sale_order_date),
            "orderNo":             so.order_no,
            "orderId":             so.order_id,
            "orderType":           so.order_type,
            "projectCode":         so.project_code,
            "title":               so.title,
            "jobLocation":         so.job_location,
            "preCertifiedAmount":  float(so.pre_certified_amount or 0),
            "thisBillClaim":       float(so.this_bill_claim      or 0),
            "gstAmount":           float(so.gst_amount           or 0),
            "totalClaim":          float(so.total_claim          or 0),
            "attachment":          so.attachment,
            "workflowStatus":      so.workflow_status,
            "currentLevel":        so.current_level,
            "locked":              so.locked,
            "orderTotalAmount":    order_fin["totalAmount"] if order_fin else 0,
            "orderBasicAmount":    order_fin["basicAmount"] if order_fin else 0,
            "orderGstAmount":      order_fin["gstAmount"]   if order_fin else 0,
            "billedAmount":        billed,
            "jobBalance":          job_balance,
            "createdBy":           so.creator.username  if so.creator  else None,
            "createdAt":           _fmt_date(so.created_at),
            "submittedBy":         so.submitter.username if so.submitter else None,
            "submittedAt":         _fmt_date(so.submitted_at),
            "approvedBy":          so.approver.username  if so.approver  else None,
            "finalApprovedAt":     _fmt_date(so.final_approved_at),
            "rejectedBy":          so.rejector.username  if so.rejector  else None,
            "rejectedAt":          _fmt_date(so.rejected_at),
            "items":               items,
            "saleOrdersUnderOrder": so_list,
        }

        return res("Sale Order details fetched", data, 200)

    except Exception as e:
        return res(str(e), [], 500)
