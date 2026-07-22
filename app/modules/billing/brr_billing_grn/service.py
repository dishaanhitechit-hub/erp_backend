from sqlalchemy import func
from sqlalchemy.exc import SQLAlchemyError
from app.extensions import db
from datetime import datetime
import json

from app.models.brrMaster import BrrMaster
from app.models.orderMaster import OrderMaster, OrderItem
from app.models.grnMaster import GrnMaster, GrnItem
from app.models.brgMaster import BrgMaster, BrgItem
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
    Sum of billing_qty for this grn_item across all non-rejected BRG.
    Draft BRG counts — reduces available qty.
    Rejected BRG does not count — qty is freed back.
    """
    result = (
        db.session.query(
            func.coalesce(func.sum(BrgItem.billing_qty), 0)
        )
        .join(BrgMaster, BrgMaster.id == BrgItem.brg_id)
        .filter(
            BrgItem.grn_item_id == grn_item_id,
            BrgMaster.workflow_status != "Rejected"
        )
        .scalar()
    )
    return float(result)


def _get_brg_cc_summary(brg_id):
    """
    CC code summary for a BRG.
    BrgItem → GrnItem → OrderItem → Item → CCCode
    """
    rows = (
        db.session.query(
            CCCode.cc_code,
            CCCode.cc_name,
            func.sum(BrgItem.amount).label("basic_amount"),
            func.sum(BrgItem.gst_amount).label("gst_amount"),
        )
        .join(GrnItem,   GrnItem.id   == BrgItem.grn_item_id)
        .join(OrderItem, OrderItem.id == GrnItem.order_item_id)
        .join(Item,      Item.item_code == OrderItem.item_code)
        .join(CCCode,    CCCode.id == Item.cc_code_id)
        .filter(BrgItem.brg_id == brg_id)
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


def generate_brg_no():
    last = (
        db.session.query(BrgMaster.brg_no)
        .order_by(BrgMaster.id.desc())
        .with_for_update()
        .first()
    )
    if last:
        try:
            last_serial = int(last[0])
        except Exception:
            last_serial = 910000
    else:
        last_serial = 910000
    return str(last_serial + 1)


# ══════════════════════════════════════════════════════════════════
# 1. GET GRNs BY BRR  (selection grid)
# ══════════════════════════════════════════════════════════════════

def get_grns_by_brr(brr_id):
    """
    Returns the order and all its approved GRNs derived from the given BRR.
    Each GRN contains items with receivedQty, alreadyBilled (BRG), availableQty.
    """
    try:
        brr = BrrMaster.query.get(brr_id)
        if not brr:
            return res("BRR not found", [], 404)

        if not brr.order_id:
            return res("BRR has no GRN order linked", [], 400)

        order = OrderMaster.query.get(brr.order_id)
        if not order:
            return res("Order not found", [], 404)

        grns = GrnMaster.query.filter(
            GrnMaster.order_id        == order.id,
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
                    "billingQty":    0,
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
            "brrId":           brr.id,
            "brrNo":           brr.brr_no,
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

        return res("GRNs fetched for BRR", data, 200)

    except Exception as e:
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 2. CREATE BRG
# ══════════════════════════════════════════════════════════════════

def create_brg(data, user_id):
    try:

        allowed = is_creator(data.get("projectCode"), _MODULE, user_id)
        if not allowed:
            return res("You are not BRG creator", [], 403)

        items = data.get("items", [])
        if isinstance(items, str):
            items = json.loads(items)

        if not items:
            return res("No items provided", [], 400)

        brr_id = data.get("brrId")
        if not brr_id:
            return res("brrId required", [], 400)

        brr = BrrMaster.query.get(brr_id)
        if not brr:
            return res("BRR not found", [], 404)

        brg_no = generate_brg_no()

        brg = BrgMaster(
            brg_no            = brg_no,
            brg_date          = data.get("brgDate"),
            project_code      = data.get("projectCode"),
            brr_id            = brr_id,
            order_id          = data.get("orderId") or brr.order_id,
            vendor_id         = data.get("vendorId"),
            received_category = data.get("receivedCategory"),
            item_category     = data.get("itemCategory"),
            cost_head         = data.get("costHead"),
            party_bill_no     = data.get("partyBillNo"),
            party_date        = data.get("partyDate") or None,
            site              = data.get("site"),
            billing_address   = data.get("billingAddress"),
            shipping_address  = data.get("shippingAddress"),
            workflow_status   = "Draft",
            current_level     = 0,
            locked            = False,
            created_by        = user_id,
        )

        db.session.add(brg)
        db.session.flush()

        total_basic = 0
        total_gst   = 0

        for row in items:

            grn_item_id = row.get("grnItemId")
            billing_qty = float(row.get("billingQty", 0))

            if billing_qty <= 0:
                db.session.rollback()
                return res(f"Invalid billingQty for grnItemId {grn_item_id}", [], 400)

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

            oi          = grn_item.order_item
            rate        = float(oi.rate        or 0) if oi else 0
            gst_percent = float(oi.gst_percent or 0) if oi else 0
            amount      = billing_qty * rate
            gst_amount  = (amount * gst_percent) / 100

            db.session.add(BrgItem(
                brg_id      = brg.id,
                grn_id      = grn_item.grn_id,
                grn_item_id = grn_item_id,
                billing_qty = billing_qty,
                rate        = rate,
                amount      = amount,
                gst_percent = gst_percent,
                gst_amount  = gst_amount,
            ))

            total_basic += amount
            total_gst   += gst_amount

        brg.basic_amount = total_basic
        brg.gst_amount   = total_gst
        brg.total_amount = total_basic + total_gst

        db.session.commit()

        cc_summary = _get_brg_cc_summary(brg.id)

        return res(
            "BRG created",
            {"brgId": brg.id, "brgNo": brg.brg_no, "ccSummary": cc_summary},
            201
        )

    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 3. BRG LIST
# ══════════════════════════════════════════════════════════════════

def get_brg_list(data):
    try:

        if not data.get("projectCode"):
            return res("projectCode required", [], 400)

        query = BrgMaster.query.filter(
            BrgMaster.project_code == data.get("projectCode")
        )

        if data.get("vendorId"):
            query = query.filter(BrgMaster.vendor_id == data.get("vendorId"))

        if data.get("brrId"):
            query = query.filter(BrgMaster.brr_id == data.get("brrId"))

        if data.get("orderId"):
            query = query.filter(BrgMaster.order_id == data.get("orderId"))

        if data.get("workflowStatus"):
            query = query.filter(BrgMaster.workflow_status == data.get("workflowStatus"))

        if data.get("search"):
            query = query.filter(BrgMaster.brg_no.ilike(f"%{data.get('search')}%"))

        rows = query.order_by(BrgMaster.id.desc()).all()

        result = []
        for row in rows:
            result.append({
                "id":               row.id,
                "brgNo":            row.brg_no,
                "brgDate":          _fmt_date(row.brg_date),
                "projectCode":      row.project_code,
                "brrNo":            row.brr.brr_no     if row.brr    else None,
                "orderNo":          row.order.order_no if row.order  else None,
                "partyName":        row.vendor.ledger_name if row.vendor else None,
                "receivedCategory": row.received_category,
                "itemCategory":     row.item_category,
                "costHead":         row.cost_head,
                "partyBillNo":      row.party_bill_no,
                "basicAmount":      float(row.basic_amount or 0),
                "totalAmount":      float(row.total_amount or 0),
                "workflowStatus":   row.workflow_status,
            })

        return res("BRG list fetched", result, 200)

    except Exception as e:
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 4. BRG DETAILS
# ══════════════════════════════════════════════════════════════════

def get_brg_details(brg_id):
    try:

        brg = BrgMaster.query.get(brg_id)
        if not brg:
            return res("BRG not found", [], 404)

        items = []
        for bi in brg.items:

            gi  = bi.grn_item
            oi  = gi.order_item if gi else None
            grn = bi.grn

            already_billed = _already_billed_qty(bi.grn_item_id)
            received_qty   = float(gi.current_received_qty or 0) if gi else 0
            available_qty  = max(received_qty - already_billed, 0)

            items.append({
                "id":            bi.id,
                "grnItemId":     bi.grn_item_id,
                "grnId":         bi.grn_id,
                "grnNo":         grn.grn_no              if grn else None,
                "grnDate":       _fmt_date(grn.grn_date) if grn else None,
                "grnl":          gi.grnl                 if gi  else None,
                "itemCode":      oi.item_code            if oi  else None,
                "itemName":      oi.item.item_name       if oi and oi.item else None,
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

        cc_summary = _get_brg_cc_summary(brg.id)

        data = {
            "id":               brg.id,
            "brgNo":            brg.brg_no,
            "brgDate":          _fmt_date(brg.brg_date),
            "projectCode":      brg.project_code,
            "brrId":            brg.brr_id,
            "brrNo":            brg.brr.brr_no if brg.brr else None,
            "vendorId":         brg.vendor_id,
            "partyName":        brg.vendor.ledger_name        if brg.vendor else None,
            "partyAddress":     brg.vendor.registered_address if brg.vendor else None,
            "partyGstn":        brg.vendor.gstin              if brg.vendor else None,
            "receivedCategory": brg.received_category,
            "itemCategory":     brg.item_category,
            "costHead":         brg.cost_head,
            "partyBillNo":      brg.party_bill_no,
            "partyDate":        _fmt_date(brg.party_date),
            "orderId":          brg.order_id,
            "orderNo":          brg.order.order_no              if brg.order else None,
            "orderDate":        _fmt_date(brg.order.order_date) if brg.order else None,
            "site":             brg.site,
            "billingAddress":   brg.billing_address,
            "shippingAddress":  brg.shipping_address,
            "basicAmount":      float(brg.basic_amount or 0),
            "gstAmount":        float(brg.gst_amount   or 0),
            "totalAmount":      float(brg.total_amount  or 0),
            "workflowStatus":   brg.workflow_status,
            "currentLevel":     brg.current_level,
            "locked":           brg.locked,
            "items":            items,
            "ccSummary":        cc_summary,
        }

        return res("BRG details fetched", data, 200)

    except Exception as e:
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 5. EDIT BRG
# ══════════════════════════════════════════════════════════════════

def edit_brg(brg_id, data, user_id):
    try:

        brg = BrgMaster.query.get(brg_id)
        if not brg:
            return res("BRG not found", [], 404)

        if brg.locked:
            return res("BRG cannot be edited", [], 400)

        if brg.workflow_status not in ["Draft", "Reback"]:
            return res("Only Draft or Reback BRG can be edited", [], 400)

        allowed = is_creator(brg.project_code, _MODULE, user_id)
        if not allowed:
            return res("You are not BRG creator", [], 403)

        items = data.get("items", [])
        if isinstance(items, str):
            items = json.loads(items)

        if not items:
            return res("Items required", [], 400)

        # update header fields
        for key, attr in [
            ("brgDate",          "brg_date"),
            ("vendorId",         "vendor_id"),
            ("partyBillNo",      "party_bill_no"),
            ("partyDate",        "party_date"),
            ("orderId",          "order_id"),
            ("site",             "site"),
            ("billingAddress",   "billing_address"),
            ("shippingAddress",  "shipping_address"),
            ("receivedCategory", "received_category"),
            ("itemCategory",     "item_category"),
            ("costHead",         "cost_head"),
        ]:
            if data.get(key) is not None:
                setattr(brg, attr, data.get(key) or None)

        # wipe old items & rebuild
        BrgItem.query.filter_by(brg_id=brg.id).delete()
        db.session.flush()

        total_basic = 0
        total_gst   = 0

        for row in items:

            grn_item_id = row.get("grnItemId")
            billing_qty = float(row.get("billingQty", 0))

            if billing_qty <= 0:
                db.session.rollback()
                return res(f"Invalid billingQty for grnItemId {grn_item_id}", [], 400)

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

            oi          = grn_item.order_item
            rate        = float(oi.rate        or 0) if oi else 0
            gst_percent = float(oi.gst_percent or 0) if oi else 0
            amount      = billing_qty * rate
            gst_amount  = (amount * gst_percent) / 100

            db.session.add(BrgItem(
                brg_id      = brg.id,
                grn_id      = grn_item.grn_id,
                grn_item_id = grn_item_id,
                billing_qty = billing_qty,
                rate        = rate,
                amount      = amount,
                gst_percent = gst_percent,
                gst_amount  = gst_amount,
            ))

            total_basic += amount
            total_gst   += gst_amount

        brg.basic_amount = total_basic
        brg.gst_amount   = total_gst
        brg.total_amount = total_basic + total_gst

        if brg.workflow_status == "Reback":
            brg.correction_sent_at = None

        brg.updated_by = user_id
        brg.updated_at = datetime.utcnow()

        db.session.commit()

        cc_summary = _get_brg_cc_summary(brg.id)

        return res(
            "BRG updated successfully",
            {"brgId": brg.id, "brgNo": brg.brg_no, "ccSummary": cc_summary},
            200
        )

    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 6. SUBMIT BRG
# ══════════════════════════════════════════════════════════════════

def submit_brg(brg_id, submitted_by=None):
    try:

        brg = BrgMaster.query.get(brg_id)
        if not brg:
            return res("BRG not found", [], 404)

        if brg.workflow_status not in ["Draft", "Reback"]:
            return res("BRG already submitted", [], 400)

        if not brg.items:
            return res("BRG has no items", [], 400)

        if brg.workflow_status == "Reback":
            brg.current_level = 0

        first_level = get_first_approver(brg.project_code, _MODULE)

        if not first_level:
            brg.workflow_status   = "Approved"
            brg.locked            = True
            brg.approved_by       = submitted_by
            brg.submitted_at      = datetime.utcnow()
            brg.final_approved_at = datetime.utcnow()
        else:
            brg.workflow_status = f"Pending_L{first_level.level_no}"
            brg.current_level   = first_level.level_no
            brg.locked          = True
            brg.submitted_at    = datetime.utcnow()

        create_history(
            project_code = brg.project_code,
            module_code  = _MODULE,
            record_id    = brg.id,
            level_no     = brg.current_level,
            action       = "SUBMIT",
            action_by    = submitted_by
        )

        brg.submitted_by = submitted_by
        brg.updated_by   = submitted_by
        brg.updated_at   = datetime.utcnow()

        db.session.commit()

        return res(
            "BRG submitted successfully",
            {"brgId": brg.id, "brgNo": brg.brg_no, "workflowStatus": brg.workflow_status},
            200
        )

    except SQLAlchemyError as e:
        db.session.rollback()
        return res(str(e), [], 500)
    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 7. APPROVE BRG
# ══════════════════════════════════════════════════════════════════

def approve_brg(brg_id, approved_by=None, comments=None):
    try:

        brg = BrgMaster.query.get(brg_id)
        if not brg:
            return res("BRG not found", [], 404)

        if not brg.workflow_status.startswith("Pending"):
            return res("BRG not pending", [], 400)

        allowed = is_current_approver(
            brg.project_code, _MODULE, brg.current_level, approved_by
        )
        if not allowed:
            return res("You are not current approver", [], 403)

        next_level = get_next_approver(brg.project_code, _MODULE, brg.current_level)

        if next_level:
            create_history(
                project_code = brg.project_code,
                module_code  = _MODULE,
                record_id    = brg.id,
                level_no     = brg.current_level,
                action       = "APPROVE",
                action_by    = approved_by,
                comments     = comments
            )
            brg.current_level   = next_level.level_no
            brg.workflow_status = f"Pending_L{next_level.level_no}"
        else:
            create_history(
                project_code = brg.project_code,
                module_code  = _MODULE,
                record_id    = brg.id,
                level_no     = brg.current_level,
                action       = "FINAL_APPROVE",
                action_by    = approved_by,
                comments     = comments
            )
            brg.workflow_status   = "Approved"
            brg.locked            = True
            brg.approved_by       = approved_by
            brg.final_approved_at = datetime.utcnow()

        brg.updated_by = approved_by
        brg.updated_at = datetime.utcnow()

        db.session.commit()

        return res(
            "BRG approved successfully",
            {"brgId": brg.id, "workflowStatus": brg.workflow_status, "currentLevel": brg.current_level},
            200
        )

    except SQLAlchemyError as e:
        db.session.rollback()
        return res(str(e), [], 500)
    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 8. REBACK BRG
# ══════════════════════════════════════════════════════════════════

def reback_brg(brg_id, reback_by=None, comments=None):
    try:

        brg = BrgMaster.query.get(brg_id)
        if not brg:
            return res("BRG not found", [], 404)

        if not brg.workflow_status.startswith("Pending"):
            return res("BRG not pending", [], 400)

        if not comments:
            return res("Comments required", [], 400)

        allowed = is_current_approver(
            brg.project_code, _MODULE, brg.current_level, reback_by
        )
        if not allowed:
            return res("You are not current approver", [], 403)

        brg.workflow_status    = "Reback"
        brg.locked             = False
        brg.correction_sent_at = datetime.utcnow()
        brg.updated_by         = reback_by
        brg.updated_at         = datetime.utcnow()

        create_history(
            project_code = brg.project_code,
            module_code  = _MODULE,
            record_id    = brg.id,
            level_no     = brg.current_level,
            action       = "REBACK",
            action_by    = reback_by,
            comments     = comments
        )

        db.session.commit()

        return res(
            "BRG sent for correction",
            {"brgId": brg.id, "workflowStatus": brg.workflow_status},
            200
        )

    except SQLAlchemyError as e:
        db.session.rollback()
        return res(str(e), [], 500)
    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 9. REJECT BRG
# ══════════════════════════════════════════════════════════════════

def reject_brg(brg_id, rejected_by=None, comments=None):
    try:

        brg = BrgMaster.query.get(brg_id)
        if not brg:
            return res("BRG not found", [], 404)

        if not brg.workflow_status.startswith("Pending"):
            return res("BRG not pending", [], 400)

        if not comments:
            return res("Comments required", [], 400)

        allowed = is_current_approver(
            brg.project_code, _MODULE, brg.current_level, rejected_by
        )
        if not allowed:
            return res("You are not current approver", [], 403)

        brg.workflow_status = "Rejected"
        brg.locked          = True
        brg.rejected_at     = datetime.utcnow()
        brg.rejected_by     = rejected_by
        brg.status          = "Inactive"
        brg.updated_by      = rejected_by
        brg.updated_at      = datetime.utcnow()

        create_history(
            project_code = brg.project_code,
            module_code  = _MODULE,
            record_id    = brg.id,
            level_no     = brg.current_level,
            action       = "REJECT",
            action_by    = rejected_by,
            comments     = comments
        )

        db.session.commit()

        return res(
            "BRG rejected",
            {"brgId": brg.id, "workflowStatus": brg.workflow_status},
            200
        )

    except SQLAlchemyError as e:
        db.session.rollback()
        return res(str(e), [], 500)
    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 10. BRG HISTORY
# ══════════════════════════════════════════════════════════════════

def get_brg_history(brg_id):
    try:

        brg = BrgMaster.query.get(brg_id)
        if not brg:
            return res("BRG not found", [], 404)

        rows = get_history(_MODULE, brg.id)

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

        return res("BRG history fetched", data, 200)

    except Exception as e:
        return res(str(e), [], 500)
