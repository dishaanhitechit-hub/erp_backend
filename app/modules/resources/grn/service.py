from sqlalchemy import func
from sqlalchemy.exc import SQLAlchemyError
from app.extensions import db
from datetime import datetime

from app.models.orderMaster import OrderMaster, OrderItem
from app.models.grnMaster import GrnMaster, GrnItem
from app.models.item import Item
from app.models.unit import Unit
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


def _pre_received_qty(order_item_id):
    """
    Sum of all current_received_qty already posted in approved/submitted GRNs
    for this order item. Dynamically calculated — never stored.
    """
    result = (
        db.session.query(
            func.coalesce(
                func.sum(GrnItem.current_received_qty),
                0
            )
        )
        .join(
            GrnMaster,
            GrnMaster.id == GrnItem.grn_id
        )
        .filter(
            GrnItem.order_item_id == order_item_id,
            GrnMaster.workflow_status != "Rejected"
        )
        .scalar()
    )
    return float(result)


def generate_grnl_no(line_no):
    return f"GRNL{line_no:03d}"


def generate_grn_no():
    last = (
        db.session.query(GrnMaster.grn_no)
        .order_by(GrnMaster.id.desc())
        .first()
    )
    if last:
        try:
            last_serial = int(last[0])
        except Exception:
            last_serial = 720000
    else:
        last_serial = 720000
    return str(last_serial + 1)


# ══════════════════════════════════════════════════════════════════
# 1. GET ORDERS BY VENDOR  (filter panel helper)
# ══════════════════════════════════════════════════════════════════

def get_orders_by_vendor(data):
    """
    Input (all from request.args / request.json):
        vendorId          – required
        projectCode       – required
        receivedCategory  – optional  (maps to OrderMaster.category_code)
        itemCategory      – optional  (maps to OrderMaster.sub_code)
        costHead          – optional  (maps to OrderMaster.cost_head)

    Filter logic:
        if receivedCategory is provided → filter by category_code directly
        else → filter by costHead + itemCategory (sub_code) if provided
    """
    try:

        vendor_id = data.get("vendorId")
        project_code = data.get("projectCode")

        if not vendor_id:
            return res("vendorId required", [], 400)

        if not project_code:
            return res("projectCode required", [], 400)

        # ── base query ─────────────────────────────────────────
        query = OrderMaster.query.filter(
            OrderMaster.vendor_id == vendor_id,
            OrderMaster.project_code == project_code,
            OrderMaster.workflow_status == "Approved"
        )

        received_category = data.get("receivedCategory")
        item_category = data.get("itemCategory")
        cost_head = data.get("costHead")

        # ── smart filter ───────────────────────────────────────
        if received_category:
            # UI showed same receivedCategory → filter directly
            query = query.filter(
                OrderMaster.category_code == received_category
            )
        else:
            # fallback: use costHead + subCategory
            if cost_head:
                query = query.filter(
                    OrderMaster.cost_head == cost_head
                )
            if item_category:
                query = query.filter(
                    OrderMaster.sub_code == item_category
                )

        rows = query.order_by(OrderMaster.id.desc()).all()

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
# 2. GET ORDER ITEMS FOR GRN  (populate GRN item grid)
# ══════════════════════════════════════════════════════════════════

def get_order_items_for_grn(order_id):
    """
    Fetches order items for a given order_id.
    Dynamically computes pre_received_qty and balance_qty per item.
    """
    try:

        order = OrderMaster.query.get(order_id)

        if not order:
            return res("Order not found", [], 404)

        if order.workflow_status != "Approved":
            return res("Order is not approved", [], 400)

        items = []

        for oi in order.items:

            pre_qty = _pre_received_qty(oi.id)
            order_qty = float(oi.qty or 0)
            balance_qty = order_qty - pre_qty

            items.append({

                "orderItemId": oi.id,
                "indentNo": (
                    oi.indent_item.indent.indent_no
                    if oi.indent_item and oi.indent_item.indent else None
                ),

                "itemCode": oi.item_code,
                "itemName": (
                    oi.item.item_name
                    if oi.item else None
                ),
                "itemUnit": (
                    oi.item.unit.unit_name
                    if oi.item and oi.item.unit else None
                ),
                "note": oi.custom_note,

                # qty columns
                "orderQty": order_qty,
                "preReceivedQty": pre_qty,
                "balanceQty": balance_qty,

                # user fills these
                "currentReceivedQty": 0,
                "useLocation": None,
                "storeLocation": None,
            })

        data = {
            "orderId": order.id,
            "orderNo": order.order_no,
            "orderDate": _fmt_date(order.order_date),
            "vendorId": order.vendor_id,
            "partyName": (
                order.vendor.ledger_name
                if order.vendor else None
            ),
            "partyAddress": (
                order.vendor.registered_address
                if order.vendor else None
            ),
            "partyGstn": (
                order.vendor.gstin
                if order.vendor else None
            ),
            "projectCode": order.project_code,
            "billingAddress": order.billing_address,
            "shippingAddress": order.shipping_address,
            "categoryCode": order.category_code,
            "subCode": order.sub_code,
            "costHead": order.cost_head,
            "items": items,
        }

        return res("Order items fetched", data, 200)

    except Exception as e:
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 3. CREATE GRN
# ══════════════════════════════════════════════════════════════════

def create_grn(data, user_id, files=None):
    try:

        allowed = is_creator(
            data.get("projectCode"),
            "goods_received_note",
            user_id
        )

        if not allowed:
            return res("You are not GRN creator", [], 403)

        items = data.get("items", [])
        if isinstance(items, str):
            items = json.loads(items)

        if not items:
            return res("No items provided", [], 400)

        grn_no = generate_grn_no()

        # ── file upload ────────────────────────────────────────
        attached_doc = None
        if files:
            doc_file = files.get("attachedDoc")
            if doc_file:
                attached_doc = upload_file_to_bunny(
                    file=doc_file,
                    mainFolder="grn",
                    subFolder=grn_no,
                    fileName="attached_doc"
                )

        grn = GrnMaster(

            grn_no=grn_no,
            grn_date=data.get("grnDate"),
            project_code=data.get("projectCode"),
            received_category=data.get("receivedCategory"),
            item_category=data.get("itemCategory"),
            cost_head=data.get("costHead"),
            order_id=data.get("orderId"),
            vendor_id=data.get("vendorId"),
            billing_address=data.get("billingAddress"),
            shipping_address=data.get("shippingAddress"),
            challan_no=data.get("challanNo"),
            party_bill_no=data.get("partyBillNo"),
            party_bill_date=data.get("partyBillDate"),
            deliver_vehicle_no=data.get("deliverVehicleNo"),
            delivered_concern=data.get("deliveredConcern"),
            unloading_datetime=data.get("unloadingDatetime"),
            physically_verified_by=data.get("physicallyVerifiedBy"),
            attached_doc=attached_doc,
            workflow_status="Draft",
            current_level=0,
            locked=False,
            created_by=user_id,

        )

        db.session.add(grn)
        db.session.flush()

        for line_no, row in enumerate(items, start=1):

            order_item_id = row.get("orderItemId")
            current_received_qty = float(row.get("currentReceivedQty", 0))

            if current_received_qty <= 0:
                db.session.rollback()
                return res(
                    f"Invalid currentReceivedQty for orderItemId {order_item_id}",
                    [], 400
                )

            # ── validate against remaining balance ─────────────
            order_item = OrderItem.query.get(order_item_id)
            if not order_item:
                db.session.rollback()
                return res(
                    f"Order item {order_item_id} not found",
                    [], 404
                )

            pre_qty = _pre_received_qty(order_item_id)
            balance = float(order_item.qty or 0) - pre_qty

            if current_received_qty > balance:
                db.session.rollback()
                return res(
                    f"Only {balance} qty remaining for item {order_item.item_code}",
                    [], 400
                )

            grn_item = GrnItem(

                grn_id=grn.id,
                order_item_id=order_item_id,
                grnl=generate_grnl_no(line_no),
                current_received_qty=current_received_qty,
                use_location=row.get("useLocation"),
                store_location=row.get("storeLocation"),

            )

            db.session.add(grn_item)

        db.session.commit()

        return res(
            "GRN created",
            {"grnId": grn.id, "grnNo": grn.grn_no},
            201
        )

    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 4. GRN LIST
# ══════════════════════════════════════════════════════════════════

def get_grn_list(data):
    try:

        if not data.get("projectCode"):
            return res("projectCode required", [], 400)

        query = GrnMaster.query.filter(
            GrnMaster.project_code == data.get("projectCode")
        )

        if data.get("vendorId"):
            query = query.filter(
                GrnMaster.vendor_id == data.get("vendorId")
            )

        if data.get("orderId"):
            query = query.filter(
                GrnMaster.order_id == data.get("orderId")
            )

        if data.get("workflowStatus"):
            query = query.filter(
                GrnMaster.workflow_status == data.get("workflowStatus")
            )

        if data.get("search"):
            query = query.filter(
                GrnMaster.grn_no.ilike(f"%{data.get('search')}%")
            )

        rows = query.order_by(GrnMaster.id.desc()).all()

        result = []
        for row in rows:
            result.append({
                "id": row.id,
                "grnNo": row.grn_no,
                "grnDate": _fmt_date(row.grn_date),
                "projectCode": row.project_code,
                "orderNo": (
                    row.order.order_no
                    if row.order else None
                ),
                "partyName": (
                    row.vendor.ledger_name
                    if row.vendor else None
                ),
                "receivedCategory": row.received_category,
                "itemCategory": row.item_category,
                "costHead": row.cost_head,
                "workflowStatus": row.workflow_status,
            })

        return res("GRN list fetched", result, 200)

    except Exception as e:
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 5. GRN DETAILS
# ══════════════════════════════════════════════════════════════════

def get_grn_details(grn_id):
    try:

        grn = GrnMaster.query.get(grn_id)

        if not grn:
            return res("GRN not found", [], 404)

        items = []
        for gi in grn.items:

            oi = gi.order_item
            pre_qty = _pre_received_qty(gi.order_item_id)

            items.append({

                "id": gi.id,
                "orderItemId": gi.order_item_id,
                "grnl": gi.grnl,
                "indentNo": (
                    oi.indent_item.indent.indent_no
                    if oi and oi.indent_item and oi.indent_item.indent else None
                ),

                "itemCode": oi.item_code if oi else None,
                "itemName": (
                    oi.item.item_name
                    if oi and oi.item else None
                ),
                "itemUnit": (
                    oi.item.unit.unit_name
                    if oi and oi.item and oi.item.unit else None
                ),
                "note": oi.custom_note if oi else None,

                "orderQty": float(oi.qty or 0) if oi else 0,
                "preReceivedQty": pre_qty,
                "balanceQty": float(oi.qty or 0) - pre_qty if oi else 0,
                "currentReceivedQty": float(gi.current_received_qty or 0),

                "useLocation": gi.use_location,
                "storeLocation": gi.store_location,
            })

        data = {
            "id": grn.id,
            "grnNo": grn.grn_no,
            "grnDate": _fmt_date(grn.grn_date),
            "projectCode": grn.project_code,
            "receivedCategory": grn.received_category,
            "itemCategory": grn.item_category,
            "costHead": grn.cost_head,
            "orderId": grn.order_id,
            "orderNo": grn.order.order_no if grn.order else None,
            "orderDate":_fmt_date(grn.order.order_date),
            "vendorId": grn.vendor_id,
            "partyName": (
                grn.vendor.ledger_name if grn.vendor else None
            ),
            "partyAddress": (
                grn.vendor.registered_address if grn.vendor else None
            ),
            "partyGstn": (
                grn.vendor.gstin if grn.vendor else None
            ),
            "billingAddress": grn.billing_address,
            "shippingAddress": grn.shipping_address,
            "challanNo": grn.challan_no,
            "partyBillNo": grn.party_bill_no,
            "partyBillDate": _fmt_date(grn.party_bill_date),
            "deliverVehicleNo": grn.deliver_vehicle_no,
            "deliveredConcern": grn.delivered_concern,
            "unloadingDatetime": _fmt_date(grn.unloading_datetime),
            "physicallyVerifiedBy": grn.physically_verified_by,
            "attachedDoc": grn.attached_doc,
            "workflowStatus": grn.workflow_status,
            "currentLevel": grn.current_level,
            "locked": grn.locked,
            "items": items,
        }

        return res("GRN details fetched", data, 200)

    except Exception as e:
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 6. SUBMIT GRN
# ══════════════════════════════════════════════════════════════════

def submit_grn(grn_id, submitted_by=None):
    try:

        grn = GrnMaster.query.get(grn_id)

        if not grn:
            return res("GRN not found", [], 404)

        if grn.workflow_status not in ["Draft", "Reback"]:
            return res("GRN already submitted", [], 400)

        if not grn.items:
            return res("GRN has no items", [], 400)

        if grn.workflow_status == "Reback":
            grn.current_level = 0

        first_level = get_first_approver(
            grn.project_code,
            "goods_received_note"
        )

        if not first_level:

            # ── auto approve ───────────────────────────────────
            grn.workflow_status = "Approved"
            grn.locked = True
            grn.approved_by = submitted_by
            grn.submitted_at = datetime.utcnow()
            grn.final_approved_at = datetime.utcnow()

        else:

            grn.workflow_status = f"Pending_L{first_level.level_no}"
            grn.current_level = first_level.level_no
            grn.locked = True
            grn.submitted_at = datetime.utcnow()

        create_history(
            project_code=grn.project_code,
            module_code="goods_received_note",
            record_id=grn.id,
            level_no=grn.current_level,
            action="SUBMIT",
            action_by=submitted_by
        )

        grn.submitted_by = submitted_by
        grn.updated_by = submitted_by
        grn.updated_at = datetime.utcnow()

        db.session.commit()

        return res(
            "GRN submitted successfully",
            {
                "grnId": grn.id,
                "grnNo": grn.grn_no,
                "workflowStatus": grn.workflow_status
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
# 7. APPROVE GRN
# ══════════════════════════════════════════════════════════════════

def approve_grn(grn_id, approved_by=None, comments=None):
    try:

        grn = GrnMaster.query.get(grn_id)

        if not grn:
            return res("GRN not found", [], 404)

        if not grn.workflow_status.startswith("Pending"):
            return res("GRN not pending", [], 400)

        allowed = is_current_approver(
            grn.project_code,
            "goods_received_note",
            grn.current_level,
            approved_by
        )

        if not allowed:
            return res("You are not current approver", [], 403)

        next_level = get_next_approver(
            grn.project_code,
            "goods_received_note",
            grn.current_level
        )

        if next_level:

            create_history(
                project_code=grn.project_code,
                module_code="goods_received_note",
                record_id=grn.id,
                level_no=grn.current_level,
                action="APPROVE",
                action_by=approved_by,
                comments=comments
            )

            grn.current_level = next_level.level_no
            grn.workflow_status = f"Pending_L{next_level.level_no}"

        else:

            create_history(
                project_code=grn.project_code,
                module_code="goods_received_note",
                record_id=grn.id,
                level_no=grn.current_level,
                action="FINAL_APPROVE",
                action_by=approved_by,
                comments=comments
            )

            grn.workflow_status = "Approved"
            grn.locked = True
            grn.approved_by = approved_by
            grn.final_approved_at = datetime.utcnow()

        grn.updated_by = approved_by
        grn.updated_at = datetime.utcnow()

        db.session.commit()

        return res(
            "GRN approved successfully",
            {
                "grnId": grn.id,
                "workflowStatus": grn.workflow_status,
                "currentLevel": grn.current_level
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
# 8. REBACK GRN
# ══════════════════════════════════════════════════════════════════

def reback_grn(grn_id, reback_by=None, comments=None):
    try:

        grn = GrnMaster.query.get(grn_id)

        if not grn:
            return res("GRN not found", [], 404)

        if not grn.workflow_status.startswith("Pending"):
            return res("GRN not pending", [], 400)

        if not comments:
            return res("Comments required", [], 400)

        allowed = is_current_approver(
            grn.project_code,
            "goods_received_note",
            grn.current_level,
            reback_by
        )

        if not allowed:
            return res("You are not current approver", [], 403)

        grn.workflow_status = "Reback"
        grn.locked = False
        grn.correction_sent_at = datetime.utcnow()
        grn.updated_by = reback_by
        grn.updated_at = datetime.utcnow()

        create_history(
            project_code=grn.project_code,
            module_code="goods_received_note",
            record_id=grn.id,
            level_no=grn.current_level,
            action="REBACK",
            action_by=reback_by,
            comments=comments
        )

        db.session.commit()

        return res(
            "GRN sent for correction",
            {
                "grnId": grn.id,
                "workflowStatus": grn.workflow_status
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
# 9. REJECT GRN
# ══════════════════════════════════════════════════════════════════

def reject_grn(grn_id, rejected_by=None, comments=None):
    try:

        grn = GrnMaster.query.get(grn_id)

        if not grn:
            return res("GRN not found", [], 404)

        if not grn.workflow_status.startswith("Pending"):
            return res("GRN not pending", [], 400)

        if not comments:
            return res("Comments required", [], 400)

        allowed = is_current_approver(
            grn.project_code,
            "goods_received_note",
            grn.current_level,
            rejected_by
        )

        if not allowed:
            return res("You are not current approver", [], 403)

        grn.workflow_status = "Rejected"
        grn.locked = True
        grn.rejected_at = datetime.utcnow()
        grn.rejected_by = rejected_by
        grn.status = "Inactive"
        grn.updated_by = rejected_by
        grn.updated_at = datetime.utcnow()

        create_history(
            project_code=grn.project_code,
            module_code="goods_received_note",
            record_id=grn.id,
            level_no=grn.current_level,
            action="REJECT",
            action_by=rejected_by,
            comments=comments
        )

        db.session.commit()

        return res(
            "GRN rejected",
            {
                "grnId": grn.id,
                "workflowStatus": grn.workflow_status
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
# 10. EDIT GRN
# ══════════════════════════════════════════════════════════════════

def edit_grn(grn_id, data, user_id, files=None):
    try:

        grn = GrnMaster.query.get(grn_id)

        if not grn:
            return res("GRN not found", [], 404)

        # ── lock check ─────────────────────────────────────────
        if grn.locked:
            return res("GRN cannot be edited", [], 400)

        # ── only Draft / Reback can edit ───────────────────────
        if grn.workflow_status not in ["Draft", "Reback"]:
            return res("Only Draft or Reback GRN can be edited", [], 400)

        # ── creator check ──────────────────────────────────────
        allowed = is_creator(grn.project_code, "goods_received_note", user_id)
        if not allowed:
            return res("You are not GRN creator", [], 403)

        # ── items required ─────────────────────────────────────
        items = data.get("items", [])
        if isinstance(items, str):
            items = json.loads(items)

        if not items:
            return res("Items required", [], 400)

        # ── update header fields ───────────────────────────────
        if data.get("grnDate"):
            grn.grn_date = data.get("grnDate")
        if data.get("receivedCategory"):
            grn.received_category = data.get("receivedCategory")
        if data.get("itemCategory"):
            grn.item_category = data.get("itemCategory")
        if data.get("costHead"):
            grn.cost_head = data.get("costHead")
        if data.get("orderId"):
            grn.order_id = data.get("orderId")
        if data.get("vendorId"):
            grn.vendor_id = data.get("vendorId")
        if data.get("billingAddress"):
            grn.billing_address = data.get("billingAddress")
        if data.get("shippingAddress"):
            grn.shipping_address = data.get("shippingAddress")
        if data.get("challanNo"):
            grn.challan_no = data.get("challanNo")
        if data.get("partyBillNo"):
            grn.party_bill_no = data.get("partyBillNo")
        if data.get("partyBillDate"):
            grn.party_bill_date = data.get("partyBillDate")
        if data.get("deliverVehicleNo"):
            grn.deliver_vehicle_no = data.get("deliverVehicleNo")
        if data.get("deliveredConcern"):
            grn.delivered_concern = data.get("deliveredConcern")
        if data.get("unloadingDatetime"):
            grn.unloading_datetime = data.get("unloadingDatetime")
        if data.get("physicallyVerifiedBy"):
            grn.physically_verified_by = data.get("physicallyVerifiedBy")

        # ── file update ────────────────────────────────────────
        if files:
            doc_file = files.get("attachedDoc")
            if doc_file:
                grn.attached_doc = upload_file_to_bunny(
                    file=doc_file,
                    mainFolder="grn",
                    subFolder=grn.grn_no,
                    fileName="attached_doc"
                )

        # ── wipe old items & rebuild ───────────────────────────
        GrnItem.query.filter_by(grn_id=grn.id).delete()
        db.session.flush()

        for line_no, row in enumerate(items, start=1):

            order_item_id = row.get("orderItemId")
            current_received_qty = float(row.get("currentReceivedQty", 0))

            if current_received_qty <= 0:
                db.session.rollback()
                return res(
                    f"Invalid currentReceivedQty for orderItemId {order_item_id}",
                    [], 400
                )

            order_item = OrderItem.query.get(order_item_id)
            if not order_item:
                db.session.rollback()
                return res(
                    f"Order item {order_item_id} not found",
                    [], 404
                )

            # pre_received excludes current GRN (already wiped above)
            pre_qty = _pre_received_qty(order_item_id)
            balance = float(order_item.qty or 0) - pre_qty

            if current_received_qty > balance:
                db.session.rollback()
                return res(
                    f"Only {balance} qty remaining for item {order_item.item_code}",
                    [], 400
                )

            db.session.add(GrnItem(
                grn_id=grn.id,
                order_item_id=order_item_id,
                grnl=generate_grnl_no(line_no),
                current_received_qty=current_received_qty,
                use_location=row.get("useLocation"),
                store_location=row.get("storeLocation"),
            ))

        # ── clear reback timestamp if editing after reback ─────
        if grn.workflow_status == "Reback":
            grn.correction_sent_at = None

        grn.updated_by = user_id
        grn.updated_at = datetime.utcnow()

        db.session.commit()

        return res(
            "GRN updated successfully",
            {"grnId": grn.id, "grnNo": grn.grn_no},
            200
        )

    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 11. GRN HISTORY
# ══════════════════════════════════════════════════════════════════

def get_grn_history(grn_id):
    try:

        grn = GrnMaster.query.get(grn_id)

        if not grn:
            return res("GRN not found", [], 404)

        rows = get_history("goods_received_note", grn.id)

        data = []
        for row in rows:
            data.append({
                "id": row.id,
                "action": row.action,
                "level": row.level_no,
                "comments": row.comments,
                "actionBy": (
                    row.user.username if row.user else None
                ),
                "createdAt": (
                    row.created_at.strftime("%Y%m%d %H:%M:%S")
                    if row.created_at else None
                ),
            })

        return res("GRN history fetched", data, 200)

    except Exception as e:
        return res(str(e), [], 500)
