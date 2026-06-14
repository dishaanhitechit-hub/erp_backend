from sqlalchemy import func
from sqlalchemy.exc import SQLAlchemyError
from app.extensions import db
from datetime import datetime
import json

from app.models.orderMaster import OrderMaster, OrderItem
from app.models.grnMaster import GrnMaster, GrnItem
from app.models.bvsMaster import BvsMaster, BvsItem
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
)

_MODULE = "billing_by_grn"


# ══════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════

def _fmt_date(d):
    if d is None:
        return None
    if isinstance(d, datetime):
        return d.strftime("%Y-%m-%d %H:%M")
    return d.strftime("%Y-%m-%d")


def _already_billed_qty(grn_item_id):
    """
    Sum of billing_qty for this grn_item across all non-rejected BVS.
    Draft BVS counts — reduces available qty.
    Rejected BVS does not count — qty is added back.
    """
    result = (
        db.session.query(
            func.coalesce(func.sum(BvsItem.billing_qty), 0)
        )
        .join(BvsMaster, BvsMaster.id == BvsItem.bvs_id)
        .filter(
            BvsItem.grn_item_id == grn_item_id,
            BvsMaster.workflow_status != "Rejected"
        )
        .scalar()
    )
    return float(result)


def _get_bvs_cc_summary(bvs_id):
    """
    CC code summary for a BVS.
    BvsItem → GrnItem → OrderItem → Item → CCCode
    """
    rows = (
        db.session.query(
            CCCode.cc_code,
            CCCode.cc_name,
            func.sum(BvsItem.amount).label("basic_amount"),
            func.sum(BvsItem.gst_amount).label("gst_amount"),
        )
        .join(GrnItem,   GrnItem.id   == BvsItem.grn_item_id)
        .join(OrderItem, OrderItem.id == GrnItem.order_item_id)
        .join(Item,      Item.item_code == OrderItem.item_code)
        .join(CCCode,    CCCode.id == Item.cc_code_id)
        .filter(BvsItem.bvs_id == bvs_id)
        .group_by(CCCode.cc_code, CCCode.cc_name)
        .all()
    )

    return [
        {
            "ccCode":      row.cc_code,
            "ccName":      row.cc_name,
            "basicAmount": float(row.basic_amount or 0),
            "gstAmount":   float(row.gst_amount   or 0),
            "totalAmount": float((row.basic_amount or 0) + (row.gst_amount or 0)),
        }
        for row in rows
    ]


def generate_bvs_no():
    last = (
        db.session.query(BvsMaster.bvs_no)
        .order_by(BvsMaster.id.desc())
        .first()
    )
    if last:
        try:
            last_serial = int(last[0])
        except Exception:
            last_serial = 840000
    else:
        last_serial = 840000
    return str(last_serial + 1)


# ══════════════════════════════════════════════════════════════════
# 1. GET ORDERS BY VENDOR  (filter panel — same logic as GRN)
# ══════════════════════════════════════════════════════════════════

def get_orders_by_vendor(data):
    """
    Filter approved orders for a vendor + project.
    Filters: receivedCategory (category_code), itemCategory (sub_code), costHead.
    Fallback: if receivedCategory provided but yields nothing → retry with
    itemCategory + costHead only.
    """
    try:

        vendor_id    = data.get("vendorId")
        project_code = data.get("projectCode")

        if not vendor_id:
            return res("vendorId required", [], 400)
        if not project_code:
            return res("projectCode required", [], 400)

        base_query = OrderMaster.query.filter(
            OrderMaster.vendor_id    == vendor_id,
            OrderMaster.project_code == project_code,
            OrderMaster.workflow_status == "Approved"
        )

        received_category = data.get("receivedCategory")
        item_category     = data.get("itemCategory")
        cost_head         = data.get("costHead")

        filtered_query = base_query
        if received_category:
            filtered_query = filtered_query.filter(
                OrderMaster.category_code == received_category
            )
        if item_category:
            filtered_query = filtered_query.filter(
                OrderMaster.sub_code == item_category
            )
        if cost_head:
            filtered_query = filtered_query.filter(
                OrderMaster.cost_head == cost_head
            )

        rows = filtered_query.order_by(OrderMaster.id.desc()).all()

        # if not rows and received_category:
        #     fallback_query = base_query
        #     if item_category:
        #         fallback_query = fallback_query.filter(
        #             OrderMaster.sub_code == item_category
        #         )
        #     if cost_head:
        #         fallback_query = fallback_query.filter(
        #             OrderMaster.cost_head == cost_head
        #         )
        #     rows = fallback_query.order_by(OrderMaster.id.desc()).all()

        result = []
        for row in rows:
            result.append({
                "id":             row.id,
                "orderNo":        row.order_no,
                "orderDate":      _fmt_date(row.order_date),
                "categoryCode":   row.category_code,
                "subCode":        row.sub_code,
                "costHead":       row.cost_head,
                "basicAmount":    float(row.basic_amount  or 0),
                "totalAmount":    float(row.total_amount  or 0),
                "workflowStatus": row.workflow_status,
            })

        return res("Orders fetched", result, 200)

    except Exception as e:
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 2. GET GRNS BY ORDER  (BVS selection grid)
# ══════════════════════════════════════════════════════════════════

def get_grns_by_order(order_id):
    """
    Returns all approved GRNs for the given order_id.
    Each GRN contains its items with:
      - receivedQty  (original from GRN)
      - alreadyBilled (sum from non-rejected BVS)
      - availableQty  (receivedQty - alreadyBilled)
    Items with availableQty <= 0 are still returned (for visibility)
    but availableQty will be 0.
    """
    try:

        order = OrderMaster.query.get(order_id)
        if not order:
            return res("Order not found", [], 404)

        grns = GrnMaster.query.filter(
            GrnMaster.order_id       == order_id,
            GrnMaster.workflow_status == "Approved"
        ).order_by(GrnMaster.id.asc()).all()

        grn_list = []
        for grn in grns:

            items = []
            for gi in grn.items:

                oi             = gi.order_item
                already_billed = _already_billed_qty(gi.id)
                received_qty   = float(gi.current_received_qty or 0)
                available_qty  = max(received_qty - already_billed, 0)

                rate        = float(oi.rate        or 0) if oi else 0
                gst_percent = float(oi.gst_percent or 0) if oi else 0

                items.append({
                    "grnItemId":     gi.id,
                    "grnl":          gi.grnl,
                    "itemCode":      oi.item_code if oi else None,
                    "itemName":      oi.item.item_name if oi and oi.item else None,
                    "itemUnit":      (
                        oi.item.unit.unit_name
                        if oi and oi.item and oi.item.unit else None
                    ),
                    "note":          oi.custom_note if oi else None,
                    "receivedQty":   received_qty,
                    "alreadyBilled": already_billed,
                    "availableQty":  available_qty,
                    "billingQty":    0,           # user fills
                    "rate":          rate,
                    "gstPercent":    gst_percent,
                    "useLocation":   gi.use_location,
                    "storeLocation": gi.store_location,
                })

            grn_list.append({
                "grnId":   grn.id,
                "grnNo":   grn.grn_no,
                "grnDate": _fmt_date(grn.grn_date),
                "items":   items,
            })

        data = {
            "orderId":         order.id,
            "orderNo":         order.order_no,
            "orderDate":       _fmt_date(order.order_date),
            "vendorId":        order.vendor_id,
            "partyName":       order.vendor.ledger_name        if order.vendor else None,
            "partyAddress":    order.vendor.registered_address if order.vendor else None,
            "partyGstn":       order.vendor.gstin              if order.vendor else None,
            "projectCode":     order.project_code,
            "site":            order.project_code,
            "billingAddress":  order.billing_address,
            "shippingAddress": order.shipping_address,
            "grns":            grn_list,
        }

        return res("GRNs fetched for order", data, 200)

    except Exception as e:
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 3. CREATE BVS
# ══════════════════════════════════════════════════════════════════

def create_bvs(data, user_id):
    try:

        allowed = is_creator(
            data.get("projectCode"),
            _MODULE,
            user_id
        )
        if not allowed:
            return res("You are not BVS creator", [], 403)

        items = data.get("items", [])
        if isinstance(items, str):
            items = json.loads(items)

        if not items:
            return res("No items provided", [], 400)

        bvs_no = generate_bvs_no()

        bvs = BvsMaster(
            bvs_no          = bvs_no,
            bvs_date        = data.get("bvsDate"),
            project_code    = data.get("projectCode"),
            vendor_id       = data.get("vendorId"),
            party_bill_no   = data.get("partyBillNo"),
            received_category=data.get("receivedCategory"),
            item_category = data.get("itemCategory"),
            cost_head = data.get("costHead"),

            party_date      = data.get("partyDate") or None,
            order_id        = data.get("orderId"),
            site            = data.get("site"),
            billing_address  = data.get("billingAddress"),
            shipping_address = data.get("shippingAddress"),
            workflow_status = "Draft",
            current_level   = 0,
            locked          = False,
            created_by      = user_id,
        )

        db.session.add(bvs)
        db.session.flush()

        total_basic = 0
        total_gst   = 0

        for row in items:

            grn_item_id = row.get("grnItemId")
            billing_qty = float(row.get("billingQty", 0))

            if billing_qty <= 0:
                db.session.rollback()
                return res(
                    f"Invalid billingQty for grnItemId {grn_item_id}",
                    [], 400
                )

            grn_item = GrnItem.query.get(grn_item_id)
            if not grn_item:
                db.session.rollback()
                return res(f"GRN item {grn_item_id} not found", [], 404)

            already_billed = _already_billed_qty(grn_item_id)
            available      = float(grn_item.current_received_qty or 0) - already_billed

            if billing_qty > available:
                db.session.rollback()
                return res(
                    f"Only {available} qty available for GRN item {grn_item_id}",
                    [], 400
                )

            # get rate & gst from order_item
            oi          = grn_item.order_item
            rate        = float(oi.rate        or 0) if oi else 0
            gst_percent = float(oi.gst_percent or 0) if oi else 0
            amount      = billing_qty * rate
            gst_amount  = (amount * gst_percent) / 100

            db.session.add(BvsItem(
                bvs_id      = bvs.id,
                grn_item_id = grn_item_id,
                billing_qty = billing_qty,
                rate        = rate,
                amount      = amount,
                gst_percent = gst_percent,
                gst_amount  = gst_amount,
            ))

            total_basic += amount
            total_gst   += gst_amount

        bvs.basic_amount = total_basic
        bvs.gst_amount   = total_gst
        bvs.total_amount = total_basic + total_gst

        db.session.commit()

        cc_summary = _get_bvs_cc_summary(bvs.id)

        return res(
            "BVS created",
            {
                "bvsId":     bvs.id,
                "bvsNo":     bvs.bvs_no,
                "ccSummary": cc_summary,
            },
            201
        )

    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 4. BVS LIST
# ══════════════════════════════════════════════════════════════════

def get_bvs_list(data):
    try:

        if not data.get("projectCode"):
            return res("projectCode required", [], 400)

        query = BvsMaster.query.filter(
            BvsMaster.project_code == data.get("projectCode")
        )

        if data.get("vendorId"):
            query = query.filter(BvsMaster.vendor_id == data.get("vendorId"))

        if data.get("orderId"):
            query = query.filter(BvsMaster.order_id == data.get("orderId"))

        if data.get("workflowStatus"):
            query = query.filter(
                BvsMaster.workflow_status == data.get("workflowStatus")
            )

        if data.get("search"):
            query = query.filter(
                BvsMaster.bvs_no.ilike(f"%{data.get('search')}%")
            )

        rows = query.order_by(BvsMaster.id.desc()).all()

        result = []
        for row in rows:
            result.append({
                "id":             row.id,
                "bvsNo":          row.bvs_no,
                "bvsDate":        _fmt_date(row.bvs_date),
                "projectCode":    row.project_code,
                "recievedCategory": row.received_category,
                "itemCategory": row.item_category,
                "costHead": row.cost_head,
                "orderNo":        row.order.order_no    if row.order  else None,
                "partyName":      row.vendor.ledger_name if row.vendor else None,
                "partyBillNo":    row.party_bill_no,
                "basicAmount":    float(row.basic_amount or 0),
                "totalAmount":    float(row.total_amount or 0),
                "workflowStatus": row.workflow_status,
            })

        return res("BVS list fetched", result, 200)

    except Exception as e:
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 5. BVS DETAILS
# ══════════════════════════════════════════════════════════════════

def get_bvs_details(bvs_id):
    try:

        bvs = BvsMaster.query.get(bvs_id)
        if not bvs:
            return res("BVS not found", [], 404)

        items = []
        for bi in bvs.items:

            gi  = bi.grn_item
            oi  = gi.order_item if gi else None
            grn = gi.grn        if gi else None

            already_billed = _already_billed_qty(bi.grn_item_id)
            received_qty   = float(gi.current_received_qty or 0) if gi else 0
            available_qty  = max(received_qty - already_billed, 0)

            items.append({
                "id":            bi.id,
                "grnItemId":     bi.grn_item_id,

                "grnNo":         grn.grn_no   if grn else None,
                "grnl":          gi.grnl      if gi  else None,
                "itemCode":      oi.item_code if oi  else None,
                "itemName":      oi.item.item_name if oi and oi.item else None,
                "itemUnit":      (
                    oi.item.unit.unit_name
                    if oi and oi.item and oi.item.unit else None
                ),
                "note":          oi.custom_note if oi else None,
                "receivedQty":   received_qty,
                "alreadyBilled": already_billed,
                "availableQty":  available_qty,
                "billingQty":    float(bi.billing_qty or 0),
                "rate":          float(bi.rate        or 0),
                "amount":        float(bi.amount      or 0),
                "gstPercent":    float(bi.gst_percent or 0),
                "gstAmount":     float(bi.gst_amount  or 0),
            })

        cc_summary = _get_bvs_cc_summary(bvs.id)

        data = {
            "id":              bvs.id,
            "bvsNo":           bvs.bvs_no,
            "bvsDate":         _fmt_date(bvs.bvs_date),
            "projectCode":     bvs.project_code,
            "vendorId":        bvs.vendor_id,
            "recievedCategory": bvs.received_category,
            "itemCategory": bvs.item_category,
            "costHead": bvs.cost_head,
            "partyName":       bvs.vendor.ledger_name        if bvs.vendor else None,
            "partyAddress":    bvs.vendor.registered_address if bvs.vendor else None,
            "partyGstn":       bvs.vendor.gstin              if bvs.vendor else None,
            "partyBillNo":     bvs.party_bill_no,
            "partyDate":       _fmt_date(bvs.party_date),
            "orderId":         bvs.order_id,
            "orderNo":         bvs.order.order_no   if bvs.order else None,
            "orderDate":       _fmt_date(bvs.order.order_date) if bvs.order else None,
            "site":            bvs.site,
            "billingAddress":  bvs.billing_address,
            "shippingAddress": bvs.shipping_address,
            "basicAmount":     float(bvs.basic_amount or 0),
            "gstAmount":       float(bvs.gst_amount   or 0),
            "totalAmount":     float(bvs.total_amount  or 0),
            "workflowStatus":  bvs.workflow_status,
            "currentLevel":    bvs.current_level,
            "locked":          bvs.locked,
            "items":           items,
            "ccSummary":       cc_summary,
        }

        return res("BVS details fetched", data, 200)

    except Exception as e:
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 6. EDIT BVS
# ══════════════════════════════════════════════════════════════════

def edit_bvs(bvs_id, data, user_id):
    try:

        bvs = BvsMaster.query.get(bvs_id)
        if not bvs:
            return res("BVS not found", [], 404)

        if bvs.locked:
            return res("BVS cannot be edited", [], 400)

        if bvs.workflow_status not in ["Draft", "Reback"]:
            return res("Only Draft or Reback BVS can be edited", [], 400)

        allowed = is_creator(bvs.project_code, _MODULE, user_id)
        if not allowed:
            return res("You are not BVS creator", [], 403)

        items = data.get("items", [])
        if isinstance(items, str):
            items = json.loads(items)

        if not items:
            return res("Items required", [], 400)

        # update header
        if data.get("bvsDate"):
            bvs.bvs_date = data.get("bvsDate")
        if data.get("vendorId"):
            bvs.vendor_id = data.get("vendorId")
        if data.get("partyBillNo"):
            bvs.party_bill_no = data.get("partyBillNo")
        if data.get("partyDate"):
            bvs.party_date = data.get("partyDate") or None
        if data.get("orderId"):
            bvs.order_id = data.get("orderId")
        if data.get("site"):
            bvs.site = data.get("site")
        if data.get("billingAddress"):
            bvs.billing_address = data.get("billingAddress")
        if data.get("shippingAddress"):
            bvs.shipping_address = data.get("shippingAddress")

        # wipe old items & rebuild
        BvsItem.query.filter_by(bvs_id=bvs.id).delete()
        db.session.flush()

        total_basic = 0
        total_gst   = 0

        for row in items:

            grn_item_id = row.get("grnItemId")
            billing_qty = float(row.get("billingQty", 0))

            if billing_qty <= 0:
                db.session.rollback()
                return res(
                    f"Invalid billingQty for grnItemId {grn_item_id}",
                    [], 400
                )

            grn_item = GrnItem.query.get(grn_item_id)
            if not grn_item:
                db.session.rollback()
                return res(f"GRN item {grn_item_id} not found", [], 404)

            # items wiped above so _already_billed excludes this BVS
            already_billed = _already_billed_qty(grn_item_id)
            available      = float(grn_item.current_received_qty or 0) - already_billed

            if billing_qty > available:
                db.session.rollback()
                return res(
                    f"Only {available} qty available for GRN item {grn_item_id}",
                    [], 400
                )

            oi          = grn_item.order_item
            rate        = float(oi.rate        or 0) if oi else 0
            gst_percent = float(oi.gst_percent or 0) if oi else 0
            amount      = billing_qty * rate
            gst_amount  = (amount * gst_percent) / 100

            db.session.add(BvsItem(
                bvs_id      = bvs.id,
                grn_item_id = grn_item_id,
                billing_qty = billing_qty,
                rate        = rate,
                amount      = amount,
                gst_percent = gst_percent,
                gst_amount  = gst_amount,
            ))

            total_basic += amount
            total_gst   += gst_amount

        bvs.basic_amount = total_basic
        bvs.gst_amount   = total_gst
        bvs.total_amount = total_basic + total_gst

        if bvs.workflow_status == "Reback":
            bvs.correction_sent_at = None

        bvs.updated_by = user_id
        bvs.updated_at = datetime.utcnow()

        db.session.commit()

        cc_summary = _get_bvs_cc_summary(bvs.id)

        return res(
            "BVS updated successfully",
            {
                "bvsId":     bvs.id,
                "bvsNo":     bvs.bvs_no,
                "ccSummary": cc_summary,
            },
            200
        )

    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 7. SUBMIT BVS
# ══════════════════════════════════════════════════════════════════

def submit_bvs(bvs_id, submitted_by=None):
    try:

        bvs = BvsMaster.query.get(bvs_id)
        if not bvs:
            return res("BVS not found", [], 404)

        if bvs.workflow_status not in ["Draft", "Reback"]:
            return res("BVS already submitted", [], 400)

        if not bvs.items:
            return res("BVS has no items", [], 400)

        if bvs.workflow_status == "Reback":
            bvs.current_level = 0

        first_level = get_first_approver(bvs.project_code, _MODULE)

        if not first_level:
            bvs.workflow_status   = "Approved"
            bvs.locked            = True
            bvs.approved_by       = submitted_by
            bvs.submitted_at      = datetime.utcnow()
            bvs.final_approved_at = datetime.utcnow()
        else:
            bvs.workflow_status = f"Pending_L{first_level.level_no}"
            bvs.current_level   = first_level.level_no
            bvs.locked          = True
            bvs.submitted_at    = datetime.utcnow()

        create_history(
            project_code = bvs.project_code,
            module_code  = _MODULE,
            record_id    = bvs.id,
            level_no     = bvs.current_level,
            action       = "SUBMIT",
            action_by    = submitted_by
        )

        bvs.submitted_by = submitted_by
        bvs.updated_by   = submitted_by
        bvs.updated_at   = datetime.utcnow()

        db.session.commit()

        return res(
            "BVS submitted successfully",
            {
                "bvsId":          bvs.id,
                "bvsNo":          bvs.bvs_no,
                "workflowStatus": bvs.workflow_status,
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
# 8. APPROVE BVS
# ══════════════════════════════════════════════════════════════════

def approve_bvs(bvs_id, approved_by=None, comments=None):
    try:

        bvs = BvsMaster.query.get(bvs_id)
        if not bvs:
            return res("BVS not found", [], 404)

        if not bvs.workflow_status.startswith("Pending"):
            return res("BVS not pending", [], 400)

        allowed = is_current_approver(
            bvs.project_code, _MODULE, bvs.current_level, approved_by
        )
        if not allowed:
            return res("You are not current approver", [], 403)

        next_level = get_next_approver(
            bvs.project_code, _MODULE, bvs.current_level
        )

        if next_level:
            create_history(
                project_code = bvs.project_code,
                module_code  = _MODULE,
                record_id    = bvs.id,
                level_no     = bvs.current_level,
                action       = "APPROVE",
                action_by    = approved_by,
                comments     = comments
            )
            bvs.current_level   = next_level.level_no
            bvs.workflow_status = f"Pending_L{next_level.level_no}"
        else:
            create_history(
                project_code = bvs.project_code,
                module_code  = _MODULE,
                record_id    = bvs.id,
                level_no     = bvs.current_level,
                action       = "FINAL_APPROVE",
                action_by    = approved_by,
                comments     = comments
            )
            bvs.workflow_status   = "Approved"
            bvs.locked            = True
            bvs.approved_by       = approved_by
            bvs.final_approved_at = datetime.utcnow()

        bvs.updated_by = approved_by
        bvs.updated_at = datetime.utcnow()

        db.session.commit()

        return res(
            "BVS approved successfully",
            {
                "bvsId":          bvs.id,
                "workflowStatus": bvs.workflow_status,
                "currentLevel":   bvs.current_level,
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
# 9. REBACK BVS
# ══════════════════════════════════════════════════════════════════

def reback_bvs(bvs_id, reback_by=None, comments=None):
    try:

        bvs = BvsMaster.query.get(bvs_id)
        if not bvs:
            return res("BVS not found", [], 404)

        if not bvs.workflow_status.startswith("Pending"):
            return res("BVS not pending", [], 400)

        if not comments:
            return res("Comments required", [], 400)

        allowed = is_current_approver(
            bvs.project_code, _MODULE, bvs.current_level, reback_by
        )
        if not allowed:
            return res("You are not current approver", [], 403)

        bvs.workflow_status    = "Reback"
        bvs.locked             = False
        bvs.correction_sent_at = datetime.utcnow()
        bvs.updated_by         = reback_by
        bvs.updated_at         = datetime.utcnow()

        create_history(
            project_code = bvs.project_code,
            module_code  = _MODULE,
            record_id    = bvs.id,
            level_no     = bvs.current_level,
            action       = "REBACK",
            action_by    = reback_by,
            comments     = comments
        )

        db.session.commit()

        return res(
            "BVS sent for correction",
            {"bvsId": bvs.id, "workflowStatus": bvs.workflow_status},
            200
        )

    except SQLAlchemyError as e:
        db.session.rollback()
        return res(str(e), [], 500)
    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 10. REJECT BVS
# ══════════════════════════════════════════════════════════════════

def reject_bvs(bvs_id, rejected_by=None, comments=None):
    try:

        bvs = BvsMaster.query.get(bvs_id)
        if not bvs:
            return res("BVS not found", [], 404)

        if not bvs.workflow_status.startswith("Pending"):
            return res("BVS not pending", [], 400)

        if not comments:
            return res("Comments required", [], 400)

        allowed = is_current_approver(
            bvs.project_code, _MODULE, bvs.current_level, rejected_by
        )
        if not allowed:
            return res("You are not current approver", [], 403)

        bvs.workflow_status = "Rejected"
        bvs.locked          = True
        bvs.rejected_at     = datetime.utcnow()
        bvs.rejected_by     = rejected_by
        bvs.status          = "Inactive"
        bvs.updated_by      = rejected_by
        bvs.updated_at      = datetime.utcnow()

        create_history(
            project_code = bvs.project_code,
            module_code  = _MODULE,
            record_id    = bvs.id,
            level_no     = bvs.current_level,
            action       = "REJECT",
            action_by    = rejected_by,
            comments     = comments
        )

        db.session.commit()

        return res(
            "BVS rejected",
            {"bvsId": bvs.id, "workflowStatus": bvs.workflow_status},
            200
        )

    except SQLAlchemyError as e:
        db.session.rollback()
        return res(str(e), [], 500)
    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 11. BVS HISTORY
# ══════════════════════════════════════════════════════════════════

def get_bvs_history(bvs_id):
    try:

        bvs = BvsMaster.query.get(bvs_id)
        if not bvs:
            return res("BVS not found", [], 404)

        rows = get_history(_MODULE, bvs.id)

        data = []
        for row in rows:
            data.append({
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

        return res("BVS history fetched", data, 200)

    except Exception as e:
        return res(str(e), [], 500)
