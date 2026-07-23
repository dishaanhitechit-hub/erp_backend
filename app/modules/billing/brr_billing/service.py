from sqlalchemy import func
from sqlalchemy.exc import SQLAlchemyError
from app.extensions import db
from datetime import datetime
import json

from app.models.brrMaster import BrrMaster
from app.models.orderMaster import OrderMaster, OrderItem
from app.models.ORDER_projectwork import ProjectWorkOrderMaster, ProjectWorkOrderItem
from app.models.grnMaster import GrnMaster, GrnItem
from app.models.srnMaster import SrnMaster, SrnItem
from app.models.brbMaster import BrbMaster, BrbItem
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
from app.modules.billing.constants import (
    get_billing_type,
    get_module_code,
)


# ══════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════

def _fmt_date(d):
    if d is None:
        return None
    if isinstance(d, datetime):
        return d.strftime("%Y-%m-%d %H:%M")
    return d.strftime("%Y-%m-%d")


def _already_billed_grn(grn_item_id):
    result = (
        db.session.query(func.coalesce(func.sum(BrbItem.billing_qty), 0))
        .join(BrbMaster, BrbMaster.id == BrbItem.brb_id)
        .filter(
            BrbItem.grn_item_id == grn_item_id,
            BrbMaster.workflow_status != "Rejected"
        )
        .scalar()
    )
    return float(result)


def _already_billed_srn(srn_item_id):
    result = (
        db.session.query(func.coalesce(func.sum(BrbItem.billing_qty), 0))
        .join(BrbMaster, BrbMaster.id == BrbItem.brb_id)
        .filter(
            BrbItem.srn_item_id == srn_item_id,
            BrbMaster.workflow_status != "Rejected"
        )
        .scalar()
    )
    return float(result)


def _brr_billed_amount(brr_id, exclude_brb_id=None):
    """Total non-rejected BRB billing amount under a BRR."""
    q = (
        db.session.query(func.coalesce(func.sum(BrbMaster.total_amount), 0))
        .filter(BrbMaster.brr_id == brr_id, BrbMaster.workflow_status != "Rejected")
    )
    if exclude_brb_id:
        q = q.filter(BrbMaster.id != exclude_brb_id)
    return float(q.scalar())


def _cc_summary(brb_id, billing_type):
    if billing_type == "GRN":
        rows = (
            db.session.query(
                CCCode.cc_code,
                CCCode.cc_name,
                func.sum(BrbItem.amount).label("basic_amount"),
                func.sum(BrbItem.gst_amount).label("gst_amount"),
            )
            .join(GrnItem,   GrnItem.id   == BrbItem.grn_item_id)
            .join(OrderItem, OrderItem.id == GrnItem.order_item_id)
            .join(Item,      Item.item_code == OrderItem.item_code)
            .join(CCCode,    CCCode.id == Item.cc_code_id)
            .filter(BrbItem.brb_id == brb_id)
            .group_by(CCCode.cc_code, CCCode.cc_name)
            .all()
        )
    else:
        rows = (
            db.session.query(
                CCCode.cc_code,
                CCCode.cc_name,
                func.sum(BrbItem.amount).label("basic_amount"),
                func.sum(BrbItem.gst_amount).label("gst_amount"),
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
            "gstAmount":   float(r.gst_amount   or 0),
            "totalAmount": float((r.basic_amount or 0) + (r.gst_amount or 0)),
        }
        for r in rows
    ]


def _generate_brb_no():
    last = (
        db.session.query(BrbMaster.brb_no)
        .order_by(BrbMaster.id.desc())
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


def _get_order_and_vendor(brr, billing_type):
    """Returns (order, vendor) by traversing the BRR chain."""
    if billing_type == "GRN":
        order  = brr.order
        vendor = order.vendor if order else None
    else:
        order  = brr.pw_order
        vendor = order.vendor if order else None
    return order, vendor


# ══════════════════════════════════════════════════════════════════
# 1. GET ITEMS BY BRR  (selection grid)
# ══════════════════════════════════════════════════════════════════

def get_items_by_brr(brr_id):
    try:
        brr = BrrMaster.query.get(brr_id)
        if not brr:
            return res("BRR not found", [], 404)

        billing_type = get_billing_type(brr.order_category)
        if not billing_type:
            return res(f"Unknown order category: {brr.order_category}", [], 400)

        order, vendor = _get_order_and_vendor(brr, billing_type)
        if not order:
            return res("BRR has no order linked", [], 400)

        brr_total    = float(brr.total_amount or 0)
        billed_total = _brr_billed_amount(brr_id)
        remaining    = max(brr_total - billed_total, 0)

        base = {
            "brrId":           brr.id,
            "brrNo":           brr.brr_no,
            "billingType":     billing_type,
            "brrTotal":        brr_total,
            "billedSoFar":     billed_total,
            "remainingAmount": remaining,
            "orderId":         order.id,
            "orderNo":         order.order_no,
            "orderDate":       _fmt_date(order.order_date),
            "vendorId":        order.vendor_id,
            "partyName":       vendor.ledger_name        if vendor else None,
            "partyAddress":    vendor.registered_address if vendor else None,
            "partyGstn":       vendor.gstin              if vendor else None,
            "projectCode":     order.project_code,
            "site":            order.project_code,
            "billingAddress":  order.billing_address,
            "shippingAddress": order.shipping_address,
        }

        if billing_type == "GRN":
            grns = GrnMaster.query.filter(
                GrnMaster.order_id        == order.id,
                GrnMaster.workflow_status == "Approved"
            ).order_by(GrnMaster.id.asc()).all()

            grn_list = []
            for grn in grns:
                items = []
                for gi in grn.items:
                    oi             = gi.order_item
                    already_billed = _already_billed_grn(gi.id)
                    received_qty   = float(gi.current_received_qty or 0)
                    available_qty  = max(received_qty - already_billed, 0)
                    items.append({
                        "grnItemId":     gi.id,
                        "grnl":          gi.grnl,
                        "itemCode":      oi.item_code if oi else None,
                        "itemName":      oi.item.item_name if oi and oi.item else None,
                        "itemUnit":      (oi.item.unit.unit_name if oi and oi.item and oi.item.unit else None),
                        "note":          oi.custom_note if oi else None,
                        "receivedQty":   received_qty,
                        "alreadyBilled": already_billed,
                        "availableQty":  available_qty,
                        "billingQty":    0,
                        "rate":          float(oi.rate        or 0) if oi else 0,
                        "gstPercent":    float(oi.gst_percent or 0) if oi else 0,
                        "useLocation":   gi.use_location,
                        "storeLocation": gi.store_location,
                    })
                grn_list.append({
                    "grnId":   grn.id,
                    "grnNo":   grn.grn_no,
                    "grnDate": _fmt_date(grn.grn_date),
                    "items":   items,
                })
            base["grns"] = grn_list

        else:
            srns = SrnMaster.query.filter(
                SrnMaster.order_id        == order.id,
                SrnMaster.workflow_status == "Approved"
            ).order_by(SrnMaster.id.asc()).all()

            try:
                sub_codes_list = json.loads(order.sub_codes) if order.sub_codes else []
            except Exception:
                sub_codes_list = []

            base["subCategoryCodes"] = sub_codes_list

            srn_list = []
            for srn in srns:
                items = []
                for si in srn.items:
                    oi             = si.pw_order_item
                    already_billed = _already_billed_srn(si.id)
                    received_qty   = float(si.current_received_qty or 0)
                    available_qty  = max(received_qty - already_billed, 0)
                    items.append({
                        "srnItemId":     si.id,
                        "srnl":          si.srnl,
                        "itemCode":      oi.item_code if oi else None,
                        "itemName":      oi.item.item_name if oi and oi.item else None,
                        "itemUnit":      (oi.item.unit.unit_name if oi and oi.item and oi.item.unit else None),
                        "note":          oi.custom_note if oi else None,
                        "receivedQty":   received_qty,
                        "alreadyBilled": already_billed,
                        "availableQty":  available_qty,
                        "billingQty":    0,
                        "rate":          float(oi.rate        or 0) if oi else 0,
                        "gstPercent":    float(oi.gst_percent or 0) if oi else 0,
                        "useLocation":   si.use_location,
                        "storeLocation": si.store_location,
                    })
                srn_list.append({
                    "srnId":   srn.id,
                    "srnNo":   srn.srn_no,
                    "srnDate": _fmt_date(srn.srn_date),
                    "items":   items,
                })
            base["srns"] = srn_list

        return res("Items fetched for BRR", base, 200)

    except Exception as e:
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 2. CREATE BRB
# ══════════════════════════════════════════════════════════════════

def create_brb(data, user_id):
    try:
        allowed = is_creator(data.get("projectCode"), _module(data), user_id)
        if not allowed:
            return res("You are not authorised to create billing", [], 403)

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

        billing_type = get_billing_type(brr.order_category)
        if not billing_type:
            return res(f"Unknown order category: {brr.order_category}", [], 400)

        order, _ = _get_order_and_vendor(brr, billing_type)
        if not order:
            return res("BRR has no order linked", [], 400)

        # item_category handling
        raw_cat = data.get("itemCategory") or []
        if isinstance(raw_cat, str):
            try:
                cat_list = json.loads(raw_cat)
            except Exception:
                cat_list = [c.strip() for c in raw_cat.split(",") if c.strip()]
        elif isinstance(raw_cat, list):
            cat_list = raw_cat
        else:
            cat_list = []

        brb = BrbMaster(
            brb_no        = _generate_brb_no(),
            brb_date      = data.get("brbDate"),
            project_code  = data.get("projectCode"),
            brr_id        = brr_id,
            billing_type  = billing_type,
            vendor_id     = order.vendor_id,
            order_id      = order.id,
            item_category = json.dumps(cat_list) if cat_list else None,
            cost_head     = data.get("costHead"),
            party_bill_no = data.get("partyBillNo"),
            party_date    = data.get("partyDate") or None,
            workflow_status = "Draft",
            current_level   = 0,
            locked          = False,
            created_by      = user_id,
        )

        db.session.add(brb)
        db.session.flush()

        total_basic = 0
        total_gst   = 0

        if billing_type == "GRN":
            for row in items:
                grn_item_id = row.get("grnItemId")
                billing_qty = float(row.get("billingQty", 0))

                if billing_qty <= 0:
                    db.session.rollback()
                    return res(f"Invalid billingQty for grnItemId {grn_item_id}", [], 400)

                gi = GrnItem.query.get(grn_item_id)
                if not gi:
                    db.session.rollback()
                    return res(f"GRN item {grn_item_id} not found", [], 404)

                already = _already_billed_grn(grn_item_id)
                available = float(gi.current_received_qty or 0) - already
                if billing_qty > available:
                    db.session.rollback()
                    return res(f"Only {available} qty available for GRN item {grn_item_id}", [], 400)

                oi         = gi.order_item
                rate        = float(oi.rate        or 0) if oi else 0
                gst_percent = float(oi.gst_percent or 0) if oi else 0
                amount      = billing_qty * rate
                gst_amount  = (amount * gst_percent) / 100

                db.session.add(BrbItem(
                    brb_id      = brb.id,
                    grn_id      = gi.grn_id,
                    grn_item_id = grn_item_id,
                    billing_qty = billing_qty,
                    rate        = rate,
                    amount      = amount,
                    gst_percent = gst_percent,
                    gst_amount  = gst_amount,
                ))
                total_basic += amount
                total_gst   += gst_amount

        else:
            for row in items:
                srn_item_id = row.get("srnItemId")
                billing_qty = float(row.get("billingQty", 0))

                if billing_qty <= 0:
                    db.session.rollback()
                    return res(f"Invalid billingQty for srnItemId {srn_item_id}", [], 400)

                si = SrnItem.query.get(srn_item_id)
                if not si:
                    db.session.rollback()
                    return res(f"SRN item {srn_item_id} not found", [], 404)

                already   = _already_billed_srn(srn_item_id)
                available = float(si.current_received_qty or 0) - already
                if billing_qty > available:
                    db.session.rollback()
                    return res(f"Only {available} qty available for SRN item {srn_item_id}", [], 400)

                oi          = si.pw_order_item
                rate        = float(oi.rate        or 0) if oi else 0
                gst_percent = float(oi.gst_percent or 0) if oi else 0
                amount      = billing_qty * rate
                gst_amount  = (amount * gst_percent) / 100

                db.session.add(BrbItem(
                    brb_id      = brb.id,
                    srn_id      = si.srn_id,
                    srn_item_id = srn_item_id,
                    billing_qty = billing_qty,
                    rate        = rate,
                    amount      = amount,
                    gst_percent = gst_percent,
                    gst_amount  = gst_amount,
                ))
                total_basic += amount
                total_gst   += gst_amount

        new_total       = total_basic + total_gst
        brr_total       = float(brr.total_amount or 0)
        existing_billed = _brr_billed_amount(brr_id)

        if brr_total > 0 and existing_billed + new_total > brr_total:
            db.session.rollback()
            remaining = brr_total - existing_billed
            return res(
                f"Billing exceeds BRR amount. BRR total: {brr_total:.2f}, "
                f"already billed: {existing_billed:.2f}, remaining: {remaining:.2f}",
                [], 400
            )

        brb.basic_amount = total_basic
        brb.gst_amount   = total_gst
        brb.total_amount = new_total

        db.session.commit()

        return res(
            "Billing created",
            {
                "brbId":      brb.id,
                "brbNo":      brb.brb_no,
                "billingType": billing_type,
                "ccSummary":  _cc_summary(brb.id, billing_type),
            },
            201
        )

    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 3. LIST
# ══════════════════════════════════════════════════════════════════

def get_brb_list(data):
    try:
        if not data.get("projectCode"):
            return res("projectCode required", [], 400)

        query = BrbMaster.query.filter(
            BrbMaster.project_code == data.get("projectCode")
        )

        if data.get("billingType"):
            query = query.filter(BrbMaster.billing_type == data.get("billingType"))
        if data.get("vendorId"):
            query = query.filter(BrbMaster.vendor_id == data.get("vendorId"))
        if data.get("brrId"):
            query = query.filter(BrbMaster.brr_id == data.get("brrId"))
        if data.get("orderId"):
            query = query.filter(BrbMaster.order_id == data.get("orderId"))
        if data.get("workflowStatus"):
            query = query.filter(BrbMaster.workflow_status == data.get("workflowStatus"))
        if data.get("search"):
            query = query.filter(BrbMaster.brb_no.ilike(f"%{data.get('search')}%"))

        rows = query.order_by(BrbMaster.id.desc()).all()

        result = []
        for row in rows:
            order, vendor = _get_order_and_vendor(row.brr, row.billing_type) if row.brr else (None, None)

            try:
                cat_list = json.loads(row.item_category) if row.item_category else []
            except Exception:
                cat_list = []

            result.append({
                "id":             row.id,
                "brbNo":          row.brb_no,
                "brbDate":        _fmt_date(row.brb_date),
                "billingType":    row.billing_type,
                "projectCode":    row.project_code,
                "brrNo":          row.brr.brr_no      if row.brr else None,
                "orderNo":        order.order_no       if order   else None,
                "partyName":      vendor.ledger_name   if vendor  else None,
                "itemCategory":   cat_list,
                "costHead":       row.cost_head,
                "partyBillNo":    row.party_bill_no,
                "basicAmount":    float(row.basic_amount or 0),
                "totalAmount":    float(row.total_amount or 0),
                "workflowStatus": row.workflow_status,
            })

        return res("Billing list fetched", result, 200)

    except Exception as e:
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 4. DETAILS
# ══════════════════════════════════════════════════════════════════

def get_brb_details(brb_id):
    try:
        brb = BrbMaster.query.get(brb_id)
        if not brb:
            return res("Billing not found", [], 404)

        order, vendor = _get_order_and_vendor(brb.brr, brb.billing_type) if brb.brr else (None, None)

        items = []
        for bi in brb.items:
            if brb.billing_type == "GRN":
                gi  = bi.grn_item
                oi  = gi.order_item if gi else None
                grn = bi.grn

                already   = _already_billed_grn(bi.grn_item_id)
                recv_qty  = float(gi.current_received_qty or 0) if gi else 0
                avail_qty = max(recv_qty - already, 0)

                items.append({
                    "id":            bi.id,
                    "grnItemId":     bi.grn_item_id,
                    "grnId":         bi.grn_id,
                    "grnNo":         grn.grn_no              if grn else None,
                    "grnDate":       _fmt_date(grn.grn_date) if grn else None,
                    "grnl":          gi.grnl                 if gi  else None,
                    "itemCode":      oi.item_code            if oi  else None,
                    "itemName":      oi.item.item_name       if oi and oi.item else None,
                    "itemUnit":      (oi.item.unit.unit_name if oi and oi.item and oi.item.unit else None),
                    "note":          oi.custom_note if oi else None,
                    "receivedQty":   recv_qty,
                    "alreadyBilled": already,
                    "availableQty":  avail_qty,
                    "billingQty":    float(bi.billing_qty or 0),
                    "rate":          float(bi.rate        or 0),
                    "amount":        float(bi.amount      or 0),
                    "gstPercent":    float(bi.gst_percent or 0),
                    "gstAmount":     float(bi.gst_amount  or 0),
                })
            else:
                si  = bi.srn_item
                oi  = si.pw_order_item if si else None
                srn = bi.srn

                already   = _already_billed_srn(bi.srn_item_id)
                recv_qty  = float(si.current_received_qty or 0) if si else 0
                avail_qty = max(recv_qty - already, 0)

                items.append({
                    "id":            bi.id,
                    "srnItemId":     bi.srn_item_id,
                    "srnId":         bi.srn_id,
                    "srnNo":         srn.srn_no              if srn else None,
                    "srnDate":       _fmt_date(srn.srn_date) if srn else None,
                    "srnl":          si.srnl                 if si  else None,
                    "itemCode":      oi.item_code            if oi  else None,
                    "itemName":      oi.item.item_name       if oi and oi.item else None,
                    "itemUnit":      (oi.item.unit.unit_name if oi and oi.item and oi.item.unit else None),
                    "note":          oi.custom_note if oi else None,
                    "receivedQty":   recv_qty,
                    "alreadyBilled": already,
                    "availableQty":  avail_qty,
                    "billingQty":    float(bi.billing_qty or 0),
                    "rate":          float(bi.rate        or 0),
                    "amount":        float(bi.amount      or 0),
                    "gstPercent":    float(bi.gst_percent or 0),
                    "gstAmount":     float(bi.gst_amount  or 0),
                })

        try:
            cat_list = json.loads(brb.item_category) if brb.item_category else []
        except Exception:
            cat_list = []

        try:
            order_sub_codes = json.loads(order.sub_codes) if order and hasattr(order, "sub_codes") and order.sub_codes else []
        except Exception:
            order_sub_codes = []

        data = {
            "id":               brb.id,
            "brbNo":            brb.brb_no,
            "brbDate":          _fmt_date(brb.brb_date),
            "billingType":      brb.billing_type,
            "projectCode":      brb.project_code,
            "brrId":            brb.brr_id,
            "brrNo":            brb.brr.brr_no             if brb.brr else None,
            "vendorId":         order.vendor_id             if order   else None,
            "partyName":        vendor.ledger_name          if vendor  else None,
            "partyAddress":     vendor.registered_address   if vendor  else None,
            "partyGstn":        vendor.gstin                if vendor  else None,
            "orderId":          order.id                    if order   else None,
            "orderNo":          order.order_no              if order   else None,
            "orderDate":        _fmt_date(order.order_date) if order   else None,
            "orderCategory":    brb.brr.order_category      if brb.brr else None,
            "subCategoryCodes": order_sub_codes,
            "itemCategory":     cat_list,
            "costHead":         brb.cost_head,
            "partyBillNo":      brb.party_bill_no,
            "partyDate":        _fmt_date(brb.party_date),
            "site":             order.project_code          if order   else None,
            "billingAddress":   order.billing_address       if order   else None,
            "shippingAddress":  order.shipping_address      if order   else None,
            "basicAmount":      float(brb.basic_amount or 0),
            "gstAmount":        float(brb.gst_amount   or 0),
            "totalAmount":      float(brb.total_amount  or 0),
            "workflowStatus":   brb.workflow_status,
            "currentLevel":     brb.current_level,
            "locked":           brb.locked,
            "items":            items,
            "ccSummary":        _cc_summary(brb.id, brb.billing_type),
        }

        return res("Billing details fetched", data, 200)

    except Exception as e:
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 5. EDIT
# ══════════════════════════════════════════════════════════════════

def edit_brb(brb_id, data, user_id):
    try:
        brb = BrbMaster.query.get(brb_id)
        if not brb:
            return res("Billing not found", [], 404)

        if brb.locked:
            return res("Billing cannot be edited", [], 400)

        if brb.workflow_status not in ["Draft", "Reback"]:
            return res("Only Draft or Reback billing can be edited", [], 400)

        module = get_module_code(brb.billing_type)
        if not is_creator(brb.project_code, module, user_id):
            return res("You are not authorised to edit billing", [], 403)

        items = data.get("items", [])
        if isinstance(items, str):
            items = json.loads(items)
        if not items:
            return res("Items required", [], 400)

        for key, attr in [
            ("brbDate",     "brb_date"),
            ("partyBillNo", "party_bill_no"),
            ("partyDate",   "party_date"),
            ("costHead",    "cost_head"),
        ]:
            if data.get(key) is not None:
                setattr(brb, attr, data.get(key) or None)

        raw_cat = data.get("itemCategory")
        if raw_cat is not None:
            if isinstance(raw_cat, str):
                try:
                    cat_list = json.loads(raw_cat)
                except Exception:
                    cat_list = [c.strip() for c in raw_cat.split(",") if c.strip()]
            elif isinstance(raw_cat, list):
                cat_list = raw_cat
            else:
                cat_list = []
            brb.item_category = json.dumps(cat_list)

        BrbItem.query.filter_by(brb_id=brb.id).delete()
        db.session.flush()

        total_basic = 0
        total_gst   = 0

        if brb.billing_type == "GRN":
            for row in items:
                grn_item_id = row.get("grnItemId")
                billing_qty = float(row.get("billingQty", 0))
                if billing_qty <= 0:
                    db.session.rollback()
                    return res(f"Invalid billingQty for grnItemId {grn_item_id}", [], 400)

                gi = GrnItem.query.get(grn_item_id)
                if not gi:
                    db.session.rollback()
                    return res(f"GRN item {grn_item_id} not found", [], 404)

                already   = _already_billed_grn(grn_item_id)
                available = float(gi.current_received_qty or 0) - already
                if billing_qty > available:
                    db.session.rollback()
                    return res(f"Only {available} qty available for GRN item {grn_item_id}", [], 400)

                oi          = gi.order_item
                rate        = float(oi.rate        or 0) if oi else 0
                gst_percent = float(oi.gst_percent or 0) if oi else 0
                amount      = billing_qty * rate
                gst_amount  = (amount * gst_percent) / 100

                db.session.add(BrbItem(
                    brb_id=brb.id, grn_id=gi.grn_id, grn_item_id=grn_item_id,
                    billing_qty=billing_qty, rate=rate, amount=amount,
                    gst_percent=gst_percent, gst_amount=gst_amount,
                ))
                total_basic += amount
                total_gst   += gst_amount

        else:
            for row in items:
                srn_item_id = row.get("srnItemId")
                billing_qty = float(row.get("billingQty", 0))
                if billing_qty <= 0:
                    db.session.rollback()
                    return res(f"Invalid billingQty for srnItemId {srn_item_id}", [], 400)

                si = SrnItem.query.get(srn_item_id)
                if not si:
                    db.session.rollback()
                    return res(f"SRN item {srn_item_id} not found", [], 404)

                already   = _already_billed_srn(srn_item_id)
                available = float(si.current_received_qty or 0) - already
                if billing_qty > available:
                    db.session.rollback()
                    return res(f"Only {available} qty available for SRN item {srn_item_id}", [], 400)

                oi          = si.pw_order_item
                rate        = float(oi.rate        or 0) if oi else 0
                gst_percent = float(oi.gst_percent or 0) if oi else 0
                amount      = billing_qty * rate
                gst_amount  = (amount * gst_percent) / 100

                db.session.add(BrbItem(
                    brb_id=brb.id, srn_id=si.srn_id, srn_item_id=srn_item_id,
                    billing_qty=billing_qty, rate=rate, amount=amount,
                    gst_percent=gst_percent, gst_amount=gst_amount,
                ))
                total_basic += amount
                total_gst   += gst_amount

        new_total       = total_basic + total_gst
        brr_total       = float(brb.brr.total_amount or 0) if brb.brr else 0
        existing_billed = _brr_billed_amount(brb.brr_id, exclude_brb_id=brb.id)

        if brr_total > 0 and existing_billed + new_total > brr_total:
            db.session.rollback()
            remaining = brr_total - existing_billed
            return res(
                f"Billing exceeds BRR amount. BRR total: {brr_total:.2f}, "
                f"already billed: {existing_billed:.2f}, remaining: {remaining:.2f}",
                [], 400
            )

        brb.basic_amount = total_basic
        brb.gst_amount   = total_gst
        brb.total_amount = new_total

        if brb.workflow_status == "Reback":
            brb.correction_sent_at = None

        brb.updated_by = user_id
        brb.updated_at = datetime.utcnow()

        db.session.commit()

        return res(
            "Billing updated",
            {"brbId": brb.id, "brbNo": brb.brb_no, "ccSummary": _cc_summary(brb.id, brb.billing_type)},
            200
        )

    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# WORKFLOW HELPERS
# ══════════════════════════════════════════════════════════════════

def _module(data_or_brb):
    """Resolve module code from data dict (create) or BrbMaster object (workflow)."""
    if isinstance(data_or_brb, dict):
        brr = BrrMaster.query.get(data_or_brb.get("brrId"))
        bt  = get_billing_type(brr.order_category) if brr else None
    else:
        bt = data_or_brb.billing_type
    return get_module_code(bt)


# ══════════════════════════════════════════════════════════════════
# 6. SUBMIT
# ══════════════════════════════════════════════════════════════════

def submit_brb(brb_id, submitted_by=None):
    try:
        brb = BrbMaster.query.get(brb_id)
        if not brb:
            return res("Billing not found", [], 404)
        if brb.workflow_status not in ["Draft", "Reback"]:
            return res("Billing already submitted", [], 400)
        if not brb.items:
            return res("Billing has no items", [], 400)

        module = get_module_code(brb.billing_type)

        if brb.workflow_status == "Reback":
            brb.current_level = 0

        first_level = get_first_approver(brb.project_code, module)

        if not first_level:
            brb.workflow_status   = "Approved"
            brb.locked            = True
            brb.approved_by       = submitted_by
            brb.submitted_at      = datetime.utcnow()
            brb.final_approved_at = datetime.utcnow()
        else:
            brb.workflow_status = f"Pending_L{first_level.level_no}"
            brb.current_level   = first_level.level_no
            brb.locked          = True
            brb.submitted_at    = datetime.utcnow()

        create_history(
            project_code=brb.project_code, module_code=module,
            record_id=brb.id, level_no=brb.current_level,
            action="SUBMIT", action_by=submitted_by
        )

        brb.submitted_by = submitted_by
        brb.updated_by   = submitted_by
        brb.updated_at   = datetime.utcnow()

        db.session.commit()
        return res("Billing submitted", {"brbId": brb.id, "brbNo": brb.brb_no, "workflowStatus": brb.workflow_status}, 200)

    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 7. APPROVE
# ══════════════════════════════════════════════════════════════════

def approve_brb(brb_id, approved_by=None, comments=None):
    try:
        brb = BrbMaster.query.get(brb_id)
        if not brb:
            return res("Billing not found", [], 404)
        if not brb.workflow_status.startswith("Pending"):
            return res("Billing not pending", [], 400)

        module = get_module_code(brb.billing_type)

        if not is_current_approver(brb.project_code, module, brb.current_level, approved_by):
            return res("You are not current approver", [], 403)

        next_level = get_next_approver(brb.project_code, module, brb.current_level)

        if next_level:
            create_history(project_code=brb.project_code, module_code=module, record_id=brb.id,
                           level_no=brb.current_level, action="APPROVE", action_by=approved_by, comments=comments)
            brb.current_level   = next_level.level_no
            brb.workflow_status = f"Pending_L{next_level.level_no}"
        else:
            create_history(project_code=brb.project_code, module_code=module, record_id=brb.id,
                           level_no=brb.current_level, action="FINAL_APPROVE", action_by=approved_by, comments=comments)
            brb.workflow_status   = "Approved"
            brb.locked            = True
            brb.approved_by       = approved_by
            brb.final_approved_at = datetime.utcnow()

        brb.updated_by = approved_by
        brb.updated_at = datetime.utcnow()
        db.session.commit()
        return res("Billing approved", {"brbId": brb.id, "workflowStatus": brb.workflow_status, "currentLevel": brb.current_level}, 200)

    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 8. REBACK
# ══════════════════════════════════════════════════════════════════

def reback_brb(brb_id, reback_by=None, comments=None):
    try:
        brb = BrbMaster.query.get(brb_id)
        if not brb:
            return res("Billing not found", [], 404)
        if not brb.workflow_status.startswith("Pending"):
            return res("Billing not pending", [], 400)
        if not comments:
            return res("Comments required", [], 400)

        module = get_module_code(brb.billing_type)

        if not is_current_approver(brb.project_code, module, brb.current_level, reback_by):
            return res("You are not current approver", [], 403)

        brb.workflow_status    = "Reback"
        brb.locked             = False
        brb.correction_sent_at = datetime.utcnow()
        brb.updated_by         = reback_by
        brb.updated_at         = datetime.utcnow()

        create_history(project_code=brb.project_code, module_code=module, record_id=brb.id,
                       level_no=brb.current_level, action="REBACK", action_by=reback_by, comments=comments)

        db.session.commit()
        return res("Billing sent for correction", {"brbId": brb.id, "workflowStatus": brb.workflow_status}, 200)

    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 9. REJECT
# ══════════════════════════════════════════════════════════════════

def reject_brb(brb_id, rejected_by=None, comments=None):
    try:
        brb = BrbMaster.query.get(brb_id)
        if not brb:
            return res("Billing not found", [], 404)
        if not brb.workflow_status.startswith("Pending"):
            return res("Billing not pending", [], 400)
        if not comments:
            return res("Comments required", [], 400)

        module = get_module_code(brb.billing_type)

        if not is_current_approver(brb.project_code, module, brb.current_level, rejected_by):
            return res("You are not current approver", [], 403)

        brb.workflow_status = "Rejected"
        brb.locked          = True
        brb.rejected_at     = datetime.utcnow()
        brb.rejected_by     = rejected_by
        brb.status          = "Inactive"
        brb.updated_by      = rejected_by
        brb.updated_at      = datetime.utcnow()

        create_history(project_code=brb.project_code, module_code=module, record_id=brb.id,
                       level_no=brb.current_level, action="REJECT", action_by=rejected_by, comments=comments)

        db.session.commit()
        return res("Billing rejected", {"brbId": brb.id, "workflowStatus": brb.workflow_status}, 200)

    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 10. HISTORY
# ══════════════════════════════════════════════════════════════════

def get_brb_history(brb_id):
    try:
        brb = BrbMaster.query.get(brb_id)
        if not brb:
            return res("Billing not found", [], 404)

        module = get_module_code(brb.billing_type)
        rows   = get_history(module, brb.id)

        data = [
            {
                "id":        r.id,
                "action":    r.action,
                "level":     r.level_no,
                "comments":  r.comments,
                "actionBy":  r.user.username if r.user else None,
                "createdAt": r.created_at.strftime("%Y-%m-%d %H:%M:%S") if r.created_at else None,
            }
            for r in rows
        ]

        return res("History fetched", data, 200)

    except Exception as e:
        return res(str(e), [], 500)
