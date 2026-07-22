from sqlalchemy import func
from sqlalchemy.exc import SQLAlchemyError
from app.extensions import db
from datetime import datetime
from collections import defaultdict
import uuid as _uuid

from app.models.orderMaster import OrderMaster, OrderItem
from app.models.grnMaster import GrnMaster, GrnItem
from app.models.ginMaster import GinMaster, GinItem
from app.response import res
from app.cloudinary_uploader import upload_file_to_bunny
from app.modules.work_flow import (
    is_creator,
    is_current_approver,
    get_first_approver,
    get_next_approver,
    create_history,
    get_history,
)
import json


# ══════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════

def _fmt_date(d):
    if d is None:
        return None
    if isinstance(d, datetime):
        return d.strftime("%Y-%m-%d %H:%M")
    return d.strftime("%Y-%m-%d")


def _total_received_qty(order_item_id):
    """Total approved GRN received qty for an order item."""
    result = (
        db.session.query(
            func.coalesce(func.sum(GrnItem.current_received_qty), 0)
        )
        .join(GrnMaster, GrnMaster.id == GrnItem.grn_id)
        .filter(
            GrnItem.order_item_id == order_item_id,
            GrnMaster.workflow_status == "Approved"
        )
        .scalar()
    )
    return float(result)


def _pre_issued_qty(order_item_id):
    """Sum of issue_qty already posted in non-rejected GINs for this order item."""
    result = (
        db.session.query(
            func.coalesce(func.sum(GinItem.issue_qty), 0)
        )
        .join(GinMaster, GinMaster.id == GinItem.gin_id)
        .filter(
            GinItem.order_item_id == order_item_id,
            GinMaster.workflow_status != "Rejected"
        )
        .scalar()
    )
    return float(result)


def _stock_qty(order_item_id):
    """Current stock = total received from GRN - total issued in GIN."""
    return _total_received_qty(order_item_id) - _pre_issued_qty(order_item_id)


def generate_ginl_no(line_no):
    return f"GINL{line_no:03d}"


def generate_gin_no():
    last = (
        db.session.query(GinMaster.gin_no)
        .order_by(GinMaster.id.desc())
        .first()
    )
    if last:
        try:
            last_serial = int(last[0])
        except Exception:
            last_serial = 810000
    else:
        last_serial = 810000
    return str(last_serial + 1)


# ══════════════════════════════════════════════════════════════════
# 1. GET ORDERS BY VENDOR  (filter panel)
# ══════════════════════════════════════════════════════════════════

def get_orders_by_vendor(data):
    try:

        vendor_id = data.get("vendorId")
        project_code = data.get("projectCode")

        if not vendor_id:
            return res("vendorId required", [], 400)

        if not project_code:
            return res("projectCode required", [], 400)

        query = OrderMaster.query.filter(
            OrderMaster.vendor_id == vendor_id,
            OrderMaster.project_code == project_code,
            OrderMaster.workflow_status == "Approved"
        )

        issue_category = data.get("issueCategory")
        item_category = data.get("itemCategory")
        cost_head = data.get("costHead")

        filtered_query = query
        if issue_category:
            filtered_query = filtered_query.filter(
                OrderMaster.category_code == issue_category
            )
        if cost_head:
            filtered_query = filtered_query.filter(
                OrderMaster.cost_head == cost_head
            )
        if item_category:
            filtered_query = filtered_query.filter(
                OrderMaster.sub_code == item_category
            )

        rows = filtered_query.order_by(OrderMaster.id.desc()).all()

        # if issueCategory was provided but matched nothing, fall back to
        # itemCategory + costHead only
        if not rows and issue_category:
            fallback_query = query
            if cost_head:
                fallback_query = fallback_query.filter(
                    OrderMaster.cost_head == cost_head
                )
            if item_category:
                fallback_query = fallback_query.filter(
                    OrderMaster.sub_code == item_category
                )
            rows = fallback_query.order_by(OrderMaster.id.desc()).all()

        result = []
        for row in rows:
            result.append({
                "id": row.id,
                "orderNo": row.order_no,
                "orderDate": _fmt_date(row.order_date),
                "categoryCode": row.category_code,
                "subCode": row.sub_code,
                "costHead": row.cost_head,
                "basicAmount": float(row.basic_amount or 0),
                "totalAmount": float(row.total_amount or 0),
                "workflowStatus": row.workflow_status,
            })

        return res("Orders fetched", result, 200)

    except Exception as e:
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 2. GET ORDER ITEMS FOR GIN  (populate GIN item grid)
# ══════════════════════════════════════════════════════════════════

def get_order_items_for_gin(order_id):
    """
    Fetches order items for a given order_id.
    Computes stockQty (GRN received - GIN issued) and balance per item.
    Does NOT include indent info per business requirement.
    """
    try:

        order = OrderMaster.query.get(order_id)

        if not order:
            return res("Order not found", [], 404)

        if order.workflow_status != "Approved":
            return res("Order is not approved", [], 400)

        items = []

        for oi in order.items:

            stock = _stock_qty(oi.id)
            pre_issued = _pre_issued_qty(oi.id)

            items.append({
                "orderItemId": oi.id,
                "itemCode": oi.item_code,
                "itemName": (
                    oi.item.item_name if oi.item else None
                ),
                "itemUnit": (
                    oi.item.unit.unit_name
                    if oi.item and oi.item.unit else None
                ),
                "note": oi.custom_note,
                "stockQty": stock,
                "preIssuedQty": pre_issued,
                "issueQty": 0,
                "stockLocation": None,
                "itemUsedLocation": None,
            })

        data = {
            "orderId": order.id,
            "orderNo": order.order_no,
            "orderDate": _fmt_date(order.order_date),
            "vendorId": order.vendor_id,
            "partyName": (
                order.vendor.ledger_name if order.vendor else None
            ),
            "partyAddress": (
                order.vendor.registered_address if order.vendor else None
            ),
            "partyGstn": (
                order.vendor.gstin if order.vendor else None
            ),
            "projectCode": order.project_code,
            "site": order.project_code,
            "categoryCode": order.category_code,
            "subCode": order.sub_code,
            "costHead": order.cost_head,
            "items": items,
        }

        return res("Order items fetched", data, 200)

    except Exception as e:
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 3. CREATE GIN
# ══════════════════════════════════════════════════════════════════

def create_gin(data, user_id, files=None):
    try:

        allowed = is_creator(
            data.get("projectCode"),
            "goods_issue_note",
            user_id
        )

        if not allowed:
            return res("You are not GIN creator", [], 403)

        items = data.get("items", [])
        if isinstance(items, str):
            items = json.loads(items)

        if not items:
            return res("No items provided", [], 400)

        gin_no   = generate_gin_no()
        new_uuid = str(_uuid.uuid4())

        attached_doc = None
        if files:
            doc_file = files.get("attachedDoc")
            if doc_file:
                attached_doc = upload_file_to_bunny(
                    file=doc_file,
                    mainFolder="gin",
                    subFolder=gin_no,
                    fileName="attached_doc"
                )

        gin = GinMaster(
            gin_no=gin_no,
            gin_uuid=new_uuid,
            gin_date=data.get("ginDate"),
            project_code=data.get("projectCode"),
            issue_category=data.get("issueCategory"),
            item_category=data.get("itemCategory"),
            cost_head=data.get("costHead"),
            cost_factor=data.get("costFactor"),
            order_id=data.get("orderId"),
            vendor_id=data.get("vendorId"),
            site=data.get("site"),
            despatch_from=data.get("despatchFrom"),
            shipping_to=data.get("shippingTo"),
            recommendation_by=data.get("recommendationBy"),
            issue_slip_no=data.get("issueSlipNo"),
            handed_over_to=data.get("handedOverTo"),
            attached_doc=attached_doc,
            workflow_status="Draft",
            current_level=0,
            locked=False,
            created_by=user_id,
        )

        db.session.add(gin)
        db.session.flush()

        for line_no, row in enumerate(items, start=1):

            order_item_id = row.get("orderItemId")
            issue_qty = float(row.get("issueQty", 0))

            if issue_qty <= 0:
                db.session.rollback()
                return res(
                    f"Invalid issueQty for orderItemId {order_item_id}",
                    [], 400
                )

            order_item = OrderItem.query.get(order_item_id)
            if not order_item:
                db.session.rollback()
                return res(
                    f"Order item {order_item_id} not found",
                    [], 404
                )

            stock = _stock_qty(order_item_id)

            if issue_qty > stock:
                db.session.rollback()
                return res(
                    f"Only {stock} qty in stock for item {order_item.item_code}",
                    [], 400
                )

            gin_item = GinItem(
                gin_id=gin.id,
                order_item_id=order_item_id,
                ginl=generate_ginl_no(line_no),
                issue_qty=issue_qty,
                stock_location=row.get("stockLocation"),
                item_used_location=row.get("itemUsedLocation"),
            )

            db.session.add(gin_item)

        db.session.commit()

        return res(
            "GIN created",
            {"ginId": gin.id, "ginNo": gin.gin_no, "uuid": gin.gin_uuid},
            201
        )

    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 4. GIN LIST
# ══════════════════════════════════════════════════════════════════

def get_gin_list(data):
    try:

        if not data.get("projectCode"):
            return res("projectCode required", [], 400)

        query = GinMaster.query.filter(
            GinMaster.project_code == data.get("projectCode")
        )

        if data.get("vendorId"):
            query = query.filter(GinMaster.vendor_id == data.get("vendorId"))

        if data.get("orderId"):
            query = query.filter(GinMaster.order_id == data.get("orderId"))

        if data.get("workflowStatus"):
            query = query.filter(
                GinMaster.workflow_status == data.get("workflowStatus")
            )

        if data.get("search"):
            query = query.filter(
                GinMaster.gin_no.ilike(f"%{data.get('search')}%")
            )

        rows = query.order_by(GinMaster.id.desc()).all()

        result = []
        for row in rows:
            result.append({
                "id": row.id,
                "ginNo": row.gin_no,
                "ginDate": _fmt_date(row.gin_date),
                "projectCode": row.project_code,
                "orderNo": row.order.order_no if row.order else None,
                "partyName": row.vendor.ledger_name if row.vendor else None,
                "issueCategory": row.issue_category,
                "itemCategory": row.item_category,
                "costHead": row.cost_head,
                "workflowStatus": row.workflow_status,
            })

        return res("GIN list fetched", result, 200)

    except Exception as e:
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 5. GIN DETAILS
# ══════════════════════════════════════════════════════════════════

def get_gin_details(gin_id):
    try:

        gin = GinMaster.query.get(gin_id)

        if not gin:
            return res("GIN not found", [], 404)

        items = []
        for gi in gin.items:

            oi = gi.order_item
            stock = _stock_qty(gi.order_item_id)
            pre_issued = _pre_issued_qty(gi.order_item_id)

            items.append({
                "id": gi.id,
                "orderItemId": gi.order_item_id,
                "ginl": gi.ginl,
                "itemCode": oi.item_code if oi else None,
                "itemName": (
                    oi.item.item_name if oi and oi.item else None
                ),
                "itemUnit": (
                    oi.item.unit.unit_name
                    if oi and oi.item and oi.item.unit else None
                ),
                "note": oi.custom_note if oi else None,
                "stockQty": stock,
                "preIssuedQty": pre_issued,
                "issueQty": float(gi.issue_qty or 0),
                "stockLocation": gi.stock_location,
                "itemUsedLocation": gi.item_used_location,
            })

        data = {
            "id": gin.id,
            "ginNo": gin.gin_no,
            "ginDate": _fmt_date(gin.gin_date),
            "projectCode": gin.project_code,
            "issueCategory": gin.issue_category,
            "itemCategory": gin.item_category,
            "costHead": gin.cost_head,
            "costFactor": gin.cost_factor,
            "orderId": gin.order_id,
            "orderNo": gin.order.order_no if gin.order else None,
            "orderDate": _fmt_date(gin.order.order_date) if gin.order else None,
            "vendorId": gin.vendor_id,
            "partyName": gin.vendor.ledger_name if gin.vendor else None,
            "partyAddress": (
                gin.vendor.registered_address if gin.vendor else None
            ),
            "partyGstn": gin.vendor.gstin if gin.vendor else None,
            "site": gin.site,
            "despatchFrom": gin.despatch_from,
            "shippingTo": gin.shipping_to,
            "recommendationBy": gin.recommendation_by,
            "issueSlipNo": gin.issue_slip_no,
            "handedOverTo": gin.handed_over_to,
            "attachedDoc": gin.attached_doc,
            "workflowStatus": gin.workflow_status,
            "currentLevel": gin.current_level,
            "locked": gin.locked,
            "items": items,
        }

        return res("GIN details fetched", data, 200)

    except Exception as e:
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 6. SUBMIT GIN
# ══════════════════════════════════════════════════════════════════

def submit_gin(gin_id, submitted_by=None):
    try:

        gin = GinMaster.query.get(gin_id)

        if not gin:
            return res("GIN not found", [], 404)

        if gin.workflow_status not in ["Draft", "Reback"]:
            return res("GIN already submitted", [], 400)

        if not gin.items:
            return res("GIN has no items", [], 400)

        if gin.workflow_status == "Reback":
            gin.current_level = 0

        first_level = get_first_approver(gin.project_code, "goods_issue_note")

        if not first_level:
            gin.workflow_status = "Approved"
            gin.locked = True
            gin.approved_by = submitted_by
            gin.submitted_at = datetime.utcnow()
            gin.final_approved_at = datetime.utcnow()
        else:
            gin.workflow_status = f"Pending_L{first_level.level_no}"
            gin.current_level = first_level.level_no
            gin.locked = True
            gin.submitted_at = datetime.utcnow()

        create_history(
            project_code=gin.project_code,
            module_code="goods_issue_note",
            record_id=gin.id,
            level_no=gin.current_level,
            action="SUBMIT",
            action_by=submitted_by
        )

        gin.submitted_by = submitted_by
        gin.updated_by = submitted_by
        gin.updated_at = datetime.utcnow()

        db.session.commit()

        return res(
            "GIN submitted successfully",
            {
                "ginId": gin.id,
                "ginNo": gin.gin_no,
                "workflowStatus": gin.workflow_status
            },
            200
        )

    except SQLAlchemyError as e:
        db.session.rollback()
        return res(str(e), [], 500)

    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 7. APPROVE GIN
# ══════════════════════════════════════════════════════════════════

def approve_gin(gin_id, approved_by=None, comments=None):
    try:

        gin = GinMaster.query.get(gin_id)

        if not gin:
            return res("GIN not found", [], 404)

        if not gin.workflow_status.startswith("Pending"):
            return res("GIN not pending", [], 400)

        allowed = is_current_approver(
            gin.project_code,
            "goods_issue_note",
            gin.current_level,
            approved_by
        )

        if not allowed:
            return res("You are not current approver", [], 403)

        next_level = get_next_approver(
            gin.project_code,
            "goods_issue_note",
            gin.current_level
        )

        if next_level:
            create_history(
                project_code=gin.project_code,
                module_code="goods_issue_note",
                record_id=gin.id,
                level_no=gin.current_level,
                action="APPROVE",
                action_by=approved_by,
                comments=comments
            )
            gin.current_level = next_level.level_no
            gin.workflow_status = f"Pending_L{next_level.level_no}"
        else:
            create_history(
                project_code=gin.project_code,
                module_code="goods_issue_note",
                record_id=gin.id,
                level_no=gin.current_level,
                action="FINAL_APPROVE",
                action_by=approved_by,
                comments=comments
            )
            gin.workflow_status = "Approved"
            gin.locked = True
            gin.approved_by = approved_by
            gin.final_approved_at = datetime.utcnow()

        gin.updated_by = approved_by
        gin.updated_at = datetime.utcnow()

        db.session.commit()

        return res(
            "GIN approved successfully",
            {
                "ginId": gin.id,
                "workflowStatus": gin.workflow_status,
                "currentLevel": gin.current_level
            },
            200
        )

    except SQLAlchemyError as e:
        db.session.rollback()
        return res(str(e), [], 500)

    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 8. REBACK GIN
# ══════════════════════════════════════════════════════════════════

def reback_gin(gin_id, reback_by=None, comments=None):
    try:

        gin = GinMaster.query.get(gin_id)

        if not gin:
            return res("GIN not found", [], 404)

        if not gin.workflow_status.startswith("Pending"):
            return res("GIN not pending", [], 400)

        if not comments:
            return res("Comments required", [], 400)

        allowed = is_current_approver(
            gin.project_code,
            "goods_issue_note",
            gin.current_level,
            reback_by
        )

        if not allowed:
            return res("You are not current approver", [], 403)

        gin.workflow_status = "Reback"
        gin.locked = False
        gin.correction_sent_at = datetime.utcnow()
        gin.updated_by = reback_by
        gin.updated_at = datetime.utcnow()

        create_history(
            project_code=gin.project_code,
            module_code="goods_issue_note",
            record_id=gin.id,
            level_no=gin.current_level,
            action="REBACK",
            action_by=reback_by,
            comments=comments
        )

        db.session.commit()

        return res(
            "GIN sent for correction",
            {"ginId": gin.id, "workflowStatus": gin.workflow_status},
            200
        )

    except SQLAlchemyError as e:
        db.session.rollback()
        return res(str(e), [], 500)

    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 9. REJECT GIN
# ══════════════════════════════════════════════════════════════════

def reject_gin(gin_id, rejected_by=None, comments=None):
    try:

        gin = GinMaster.query.get(gin_id)

        if not gin:
            return res("GIN not found", [], 404)

        if not gin.workflow_status.startswith("Pending"):
            return res("GIN not pending", [], 400)

        if not comments:
            return res("Comments required", [], 400)

        allowed = is_current_approver(
            gin.project_code,
            "goods_issue_note",
            gin.current_level,
            rejected_by
        )

        if not allowed:
            return res("You are not current approver", [], 403)

        gin.workflow_status = "Rejected"
        gin.locked = True
        gin.rejected_at = datetime.utcnow()
        gin.rejected_by = rejected_by
        gin.status = "Inactive"
        gin.updated_by = rejected_by
        gin.updated_at = datetime.utcnow()

        create_history(
            project_code=gin.project_code,
            module_code="goods_issue_note",
            record_id=gin.id,
            level_no=gin.current_level,
            action="REJECT",
            action_by=rejected_by,
            comments=comments
        )

        db.session.commit()

        return res(
            "GIN rejected",
            {"ginId": gin.id, "workflowStatus": gin.workflow_status},
            200
        )

    except SQLAlchemyError as e:
        db.session.rollback()
        return res(str(e), [], 500)

    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 10. EDIT GIN
# ══════════════════════════════════════════════════════════════════

def edit_gin(gin_id, data, user_id, files=None):
    try:

        gin = GinMaster.query.get(gin_id)

        if not gin:
            return res("GIN not found", [], 404)

        if gin.locked:
            return res("GIN cannot be edited", [], 400)

        if gin.workflow_status not in ["Draft", "Reback"]:
            return res("Only Draft or Reback GIN can be edited", [], 400)

        allowed = is_creator(gin.project_code, "goods_issue_note", user_id)
        if not allowed:
            return res("You are not GIN creator", [], 403)

        items = data.get("items", [])
        if isinstance(items, str):
            items = json.loads(items)

        if not items:
            return res("Items required", [], 400)

        # update header
        if data.get("ginDate"):
            gin.gin_date = data.get("ginDate")
        if data.get("issueCategory"):
            gin.issue_category = data.get("issueCategory")
        if data.get("itemCategory"):
            gin.item_category = data.get("itemCategory")
        if data.get("costHead"):
            gin.cost_head = data.get("costHead")
        if data.get("costFactor"):
            gin.cost_factor = data.get("costFactor")
        if data.get("orderId"):
            gin.order_id = data.get("orderId")
        if data.get("vendorId"):
            gin.vendor_id = data.get("vendorId")
        if data.get("site"):
            gin.site = data.get("site")
        if data.get("despatchFrom"):
            gin.despatch_from = data.get("despatchFrom")
        if data.get("shippingTo"):
            gin.shipping_to = data.get("shippingTo")
        if data.get("recommendationBy"):
            gin.recommendation_by = data.get("recommendationBy")
        if data.get("issueSlipNo"):
            gin.issue_slip_no = data.get("issueSlipNo")
        if data.get("handedOverTo"):
            gin.handed_over_to = data.get("handedOverTo")

        if files:
            doc_file = files.get("attachedDoc")
            if doc_file:
                gin.attached_doc = upload_file_to_bunny(
                    file=doc_file,
                    mainFolder="gin",
                    subFolder=gin.gin_no,
                    fileName="attached_doc"
                )

        # wipe old items & rebuild
        GinItem.query.filter_by(gin_id=gin.id).delete()
        db.session.flush()

        for line_no, row in enumerate(items, start=1):

            order_item_id = row.get("orderItemId")
            issue_qty = float(row.get("issueQty", 0))

            if issue_qty <= 0:
                db.session.rollback()
                return res(
                    f"Invalid issueQty for orderItemId {order_item_id}",
                    [], 400
                )

            order_item = OrderItem.query.get(order_item_id)
            if not order_item:
                db.session.rollback()
                return res(
                    f"Order item {order_item_id} not found",
                    [], 404
                )

            # stock excludes current GIN (already wiped above)
            stock = _stock_qty(order_item_id)

            if issue_qty > stock:
                db.session.rollback()
                return res(
                    f"Only {stock} qty in stock for item {order_item.item_code}",
                    [], 400
                )

            db.session.add(GinItem(
                gin_id=gin.id,
                order_item_id=order_item_id,
                ginl=generate_ginl_no(line_no),
                issue_qty=issue_qty,
                stock_location=row.get("stockLocation"),
                item_used_location=row.get("itemUsedLocation"),
            ))

        if gin.workflow_status == "Reback":
            gin.correction_sent_at = None

        gin.updated_by = user_id
        gin.updated_at = datetime.utcnow()

        db.session.commit()

        return res(
            "GIN updated successfully",
            {"ginId": gin.id, "ginNo": gin.gin_no},
            200
        )

    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 11. GIN HISTORY
# ══════════════════════════════════════════════════════════════════

def get_gin_history(gin_id):
    try:

        gin = GinMaster.query.get(gin_id)

        if not gin:
            return res("GIN not found", [], 404)

        rows = get_history("goods_issue_note", gin.id)

        data = []
        for row in rows:
            data.append({
                "id": row.id,
                "action": row.action,
                "level": row.level_no,
                "comments": row.comments,
                "actionBy": row.user.username if row.user else None,
                "createdAt": (
                    row.created_at.strftime("%Y%m%d %H:%M:%S")
                    if row.created_at else None
                ),
            })

        return res("GIN history fetched", data, 200)

    except Exception as e:
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# GET FULL GIN DETAILS BY UUID
# ══════════════════════════════════════════════════════════════════

def get_gin_by_uuid(gin_uuid):
    try:
        gin = GinMaster.query.filter_by(gin_uuid=gin_uuid).first()
        if not gin:
            return res("GIN not found", [], 404)

        # ── project ───────────────────────────────────────────────
        proj = gin.project
        project_info = None
        if proj:
            project_info = {
                "projectCode":   proj.project_code,
                "projectName":   proj.project_name if hasattr(proj, "project_name") else None,
                "clientName":    proj.client_name  if hasattr(proj, "client_name")  else None,
                "projectStatus": proj.status        if hasattr(proj, "status")       else None,
            }

        # ── order ─────────────────────────────────────────────────
        order_info = None
        if gin.order:
            order_info = {
                "orderId":  gin.order.id,
                "orderNo":  gin.order.order_no,
                "orderDate": _fmt_date(gin.order.order_date),
            }

        # ── vendor ────────────────────────────────────────────────
        vendor_info = None
        if gin.vendor:
            v = gin.vendor
            vendor_info = {
                "vendorId":          v.id,
                "ledgerCode":        v.ledger_code            if hasattr(v, "ledger_code")            else None,
                "ledgerName":        v.ledger_name            if hasattr(v, "ledger_name")            else None,
                "gstin":             v.gstin                  if hasattr(v, "gstin")                  else None,
                "pan":               v.pan                    if hasattr(v, "pan")                    else None,
                "stateName":         v.state_name             if hasattr(v, "state_name")             else None,
                "registeredAddress": v.registered_address     if hasattr(v, "registered_address")     else None,
                "primaryContact":    v.primary_contact        if hasattr(v, "primary_contact")        else None,
            }

        # ── users ─────────────────────────────────────────────────
        def _uname(rel): return rel.username if rel else None

        # ── items ─────────────────────────────────────────────────
        items = []
        total_issue_qty = 0.0
        for gi in gin.items:
            oi = gi.order_item
            item_name = hsn_sac = unit = None
            order_qty  = 0.0
            if oi:
                if oi.item:
                    item_name = oi.item.item_name
                    hsn_sac   = oi.item.hsn_sac   if hasattr(oi.item, "hsn_sac") else None
                    unit      = oi.item.unit.unit_name if oi.item.unit else None
                order_qty = float(oi.qty or 0)

            issue_qty  = float(gi.issue_qty or 0)
            stock_qty  = _stock_qty(gi.order_item_id) if gi.order_item_id else 0.0
            total_issue_qty += issue_qty

            items.append({
                "ginItemId":       gi.id,
                "ginl":            gi.ginl,
                "orderItemId":     gi.order_item_id,
                "itemName":        item_name,
                "hsnSac":          hsn_sac,
                "unit":            unit,
                "orderQty":        order_qty,
                "issueQty":        issue_qty,
                "stockQty":        stock_qty,
                "stockLocation":   gi.stock_location,
                "itemUsedLocation": gi.item_used_location,
            })

        # ── history ───────────────────────────────────────────────
        history_rows = get_history("goods_issue_note", gin.id)
        history = []
        for row in history_rows:
            history.append({
                "id":        row.id,
                "action":    row.action,
                "level":     row.level_no,
                "comments":  row.comments,
                "actionBy":  row.user.username if row.user else None,
                "createdAt": row.created_at.strftime("%Y-%m-%d %H:%M:%S") if row.created_at else None,
            })

        data = {
            "uuid":              gin.gin_uuid,
            "ginId":             gin.id,
            "ginNo":             gin.gin_no,
            "ginDate":           _fmt_date(gin.gin_date),
            "workflowStatus":    gin.workflow_status,
            "status":            gin.status,
            "currentLevel":      gin.current_level,
            "locked":            gin.locked,

            "issueCategory":     gin.issue_category,
            "itemCategory":      gin.item_category,
            "costHead":          gin.cost_head,
            "costFactor":        gin.cost_factor,
            "site":              gin.site,
            "despatchFrom":      gin.despatch_from,
            "shippingTo":        gin.shipping_to,
            "recommendationBy":  gin.recommendation_by,
            "issueSlipNo":       gin.issue_slip_no,
            "handedOverTo":      gin.handed_over_to,
            "attachedDoc":       gin.attached_doc,

            "project":           project_info,
            "order":             order_info,
            "vendor":            vendor_info,

            "createdBy":         _uname(gin.creator),
            "submittedBy":       _uname(gin.submitter),
            "approvedBy":        _uname(gin.approver),
            "rejectedBy":        _uname(gin.rejector),
            "updatedBy":         _uname(gin.updater),

            "createdAt":         _fmt_date(gin.created_at),
            "updatedAt":         _fmt_date(gin.updated_at),
            "submittedAt":       _fmt_date(gin.submitted_at),
            "finalApprovedAt":   _fmt_date(gin.final_approved_at),
            "rejectedAt":        _fmt_date(gin.rejected_at),
            "correctionSentAt":  _fmt_date(gin.correction_sent_at),

            "items":             items,
            "summary": {
                "totalItems":    len(items),
                "totalIssueQty": round(total_issue_qty, 2),
            },
            "history":           history,
        }

        return res("GIN details fetched", data, 200)

    except Exception as e:
        return res(str(e), [], 500)
