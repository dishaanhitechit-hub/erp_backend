from sqlalchemy import func
from sqlalchemy.exc import SQLAlchemyError
from app.extensions import db
from datetime import datetime
import json

from app.models.brrMaster import BrrMaster
from app.models.ORDER_projectwork import ProjectWorkOrderMaster, ProjectWorkOrderItem
from app.models.srnMaster import SrnMaster, SrnItem
from app.models.brsMaster import BrsMaster, BrsItem
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

_MODULE = "billing_by_brr_srn"


# ══════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════

def _fmt_date(d):
    if d is None:
        return None
    if isinstance(d, datetime):
        return d.strftime("%Y-%m-%d %H:%M")
    return d.strftime("%Y-%m-%d")


def _already_billed_qty(srn_item_id):
    """
    Sum of billing_qty for this srn_item across all non-rejected BRS.
    Draft BRS counts — reduces available qty.
    Rejected BRS does not count — qty is freed back.
    """
    result = (
        db.session.query(
            func.coalesce(func.sum(BrsItem.billing_qty), 0)
        )
        .join(BrsMaster, BrsMaster.id == BrsItem.brs_id)
        .filter(
            BrsItem.srn_item_id == srn_item_id,
            BrsMaster.workflow_status != "Rejected"
        )
        .scalar()
    )
    return float(result)


def _get_brs_cc_summary(brs_id):
    """
    CC code summary for a BRS.
    BrsItem → SrnItem → PwOrderItem → Item → CCCode
    """
    rows = (
        db.session.query(
            CCCode.cc_code,
            CCCode.cc_name,
            func.sum(BrsItem.amount).label("basic_amount"),
            func.sum(BrsItem.gst_amount).label("gst_amount"),
        )
        .join(SrnItem,              SrnItem.id              == BrsItem.srn_item_id)
        .join(ProjectWorkOrderItem, ProjectWorkOrderItem.id == SrnItem.pw_order_item_id)
        .join(Item,                 Item.item_code          == ProjectWorkOrderItem.item_code)
        .join(CCCode,               CCCode.id               == Item.cc_code_id)
        .filter(BrsItem.brs_id == brs_id)
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


def generate_brs_no():
    last = (
        db.session.query(BrsMaster.brs_no)
        .order_by(BrsMaster.id.desc())
        .with_for_update()
        .first()
    )
    if last:
        try:
            last_serial = int(last[0])
        except Exception:
            last_serial = 920000
    else:
        last_serial = 920000
    return str(last_serial + 1)


# ══════════════════════════════════════════════════════════════════
# 1. GET SRNs BY BRR  (selection grid)
# ══════════════════════════════════════════════════════════════════

def get_srns_by_brr(brr_id):
    """
    Returns the PW order and all its approved SRNs derived from the given BRR.
    Each SRN contains items with receivedQty, alreadyBilled (BRS), availableQty.
    """
    try:
        brr = BrrMaster.query.get(brr_id)
        if not brr:
            return res("BRR not found", [], 404)

        if not brr.pw_order_id:
            return res("BRR has no SRN order linked", [], 400)

        order = ProjectWorkOrderMaster.query.get(brr.pw_order_id)
        if not order:
            return res("PW Order not found", [], 404)

        srns = SrnMaster.query.filter(
            SrnMaster.order_id        == order.id,
            SrnMaster.workflow_status == "Approved"
        ).order_by(SrnMaster.id.asc()).all()

        srn_list = []
        for srn in srns:

            items = []
            for si in srn.items:

                oi             = si.pw_order_item
                already_billed = _already_billed_qty(si.id)
                received_qty   = float(si.current_received_qty or 0)
                available_qty  = max(received_qty - already_billed, 0)

                rate        = float(oi.rate        or 0) if oi else 0
                gst_percent = float(oi.gst_percent or 0) if oi else 0

                items.append({
                    "srnItemId":     si.id,
                    "srnl":          si.srnl,
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
                    "useLocation":   si.use_location,
                    "storeLocation": si.store_location,
                })

            srn_list.append({
                "srnId":   srn.id,
                "srnNo":   srn.srn_no,
                "srnDate": _fmt_date(srn.srn_date),
                "items":   items,
            })

        try:
            sub_codes_list = json.loads(order.sub_codes) if order.sub_codes else []
        except Exception:
            sub_codes_list = []

        data = {
            "brrId":            brr.id,
            "brrNo":            brr.brr_no,
            "orderId":          order.id,
            "orderNo":          order.order_no,
            "orderDate":        _fmt_date(order.order_date),
            "vendorId":         order.vendor_id,
            "partyName":        order.vendor.ledger_name        if order.vendor else None,
            "partyAddress":     order.vendor.registered_address if order.vendor else None,
            "partyGstn":        order.vendor.gstin              if order.vendor else None,
            "projectCode":      order.project_code,
            "site":             order.project_code,
            "subCategoryCodes": sub_codes_list,
            "billingAddress":   order.billing_address,
            "shippingAddress":  order.shipping_address,
            "srns":             srn_list,
        }

        return res("SRNs fetched for BRR", data, 200)

    except Exception as e:
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 2. CREATE BRS
# ══════════════════════════════════════════════════════════════════

def create_brs(data, user_id):
    try:

        allowed = is_creator(data.get("projectCode"), _MODULE, user_id)
        if not allowed:
            return res("You are not BRS creator", [], 403)

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

        raw_sub = data.get("itemCategory") or data.get("subCategoryCode") or []
        if isinstance(raw_sub, str):
            try:
                sub_codes_list = json.loads(raw_sub)
            except Exception:
                sub_codes_list = [c.strip() for c in raw_sub.split(",") if c.strip()]
        elif isinstance(raw_sub, list):
            sub_codes_list = raw_sub
        else:
            sub_codes_list = [raw_sub] if raw_sub else []

        brs_no = generate_brs_no()

        brs = BrsMaster(
            brs_no            = brs_no,
            brs_date          = data.get("brsDate"),
            project_code      = data.get("projectCode"),
            brr_id            = brr_id,
            order_id          = data.get("orderId") or brr.pw_order_id,
            vendor_id         = data.get("vendorId"),
            received_category = data.get("receivedCategory"),
            item_category     = json.dumps(sub_codes_list) if sub_codes_list else None,
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

        db.session.add(brs)
        db.session.flush()

        total_basic = 0
        total_gst   = 0

        for row in items:

            srn_item_id = row.get("srnItemId")
            billing_qty = float(row.get("billingQty", 0))

            if billing_qty <= 0:
                db.session.rollback()
                return res(f"Invalid billingQty for srnItemId {srn_item_id}", [], 400)

            srn_item = SrnItem.query.get(srn_item_id)
            if not srn_item:
                db.session.rollback()
                return res(f"SRN item {srn_item_id} not found", [], 404)

            already_billed = _already_billed_qty(srn_item_id)
            available      = float(srn_item.current_received_qty or 0) - already_billed

            if billing_qty > available:
                db.session.rollback()
                return res(
                    f"Only {available} qty available for SRN item {srn_item_id}",
                    [], 400
                )

            oi          = srn_item.pw_order_item
            rate        = float(oi.rate        or 0) if oi else 0
            gst_percent = float(oi.gst_percent or 0) if oi else 0
            amount      = billing_qty * rate
            gst_amount  = (amount * gst_percent) / 100

            db.session.add(BrsItem(
                brs_id      = brs.id,
                srn_id      = srn_item.srn_id,
                srn_item_id = srn_item_id,
                billing_qty = billing_qty,
                rate        = rate,
                amount      = amount,
                gst_percent = gst_percent,
                gst_amount  = gst_amount,
            ))

            total_basic += amount
            total_gst   += gst_amount

        brs.basic_amount = total_basic
        brs.gst_amount   = total_gst
        brs.total_amount = total_basic + total_gst

        db.session.commit()

        cc_summary = _get_brs_cc_summary(brs.id)

        return res(
            "BRS created",
            {"brsId": brs.id, "brsNo": brs.brs_no, "ccSummary": cc_summary},
            201
        )

    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 3. BRS LIST
# ══════════════════════════════════════════════════════════════════

def get_brs_list(data):
    try:

        if not data.get("projectCode"):
            return res("projectCode required", [], 400)

        query = BrsMaster.query.filter(
            BrsMaster.project_code == data.get("projectCode")
        )

        if data.get("vendorId"):
            query = query.filter(BrsMaster.vendor_id == data.get("vendorId"))

        if data.get("brrId"):
            query = query.filter(BrsMaster.brr_id == data.get("brrId"))

        if data.get("orderId"):
            query = query.filter(BrsMaster.order_id == data.get("orderId"))

        if data.get("workflowStatus"):
            query = query.filter(BrsMaster.workflow_status == data.get("workflowStatus"))

        if data.get("search"):
            query = query.filter(BrsMaster.brs_no.ilike(f"%{data.get('search')}%"))

        rows = query.order_by(BrsMaster.id.desc()).all()

        result = []
        for row in rows:
            try:
                sub_codes_list = json.loads(row.item_category) if row.item_category else []
            except Exception:
                sub_codes_list = []

            result.append({
                "id":               row.id,
                "brsNo":            row.brs_no,
                "brsDate":          _fmt_date(row.brs_date),
                "projectCode":      row.project_code,
                "brrNo":            row.brr.brr_no     if row.brr    else None,
                "orderNo":          row.order.order_no if row.order  else None,
                "partyName":        row.vendor.ledger_name if row.vendor else None,
                "receivedCategory": row.received_category,
                "itemCategory":     sub_codes_list,
                "costHead":         row.cost_head,
                "partyBillNo":      row.party_bill_no,
                "basicAmount":      float(row.basic_amount or 0),
                "totalAmount":      float(row.total_amount or 0),
                "workflowStatus":   row.workflow_status,
            })

        return res("BRS list fetched", result, 200)

    except Exception as e:
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 4. BRS DETAILS
# ══════════════════════════════════════════════════════════════════

def get_brs_details(brs_id):
    try:

        brs = BrsMaster.query.get(brs_id)
        if not brs:
            return res("BRS not found", [], 404)

        items = []
        for bi in brs.items:

            si  = bi.srn_item
            oi  = si.pw_order_item if si else None
            srn = bi.srn

            already_billed = _already_billed_qty(bi.srn_item_id)
            received_qty   = float(si.current_received_qty or 0) if si else 0
            available_qty  = max(received_qty - already_billed, 0)

            items.append({
                "id":            bi.id,
                "srnItemId":     bi.srn_item_id,
                "srnId":         bi.srn_id,
                "srnNo":         srn.srn_no              if srn else None,
                "srnDate":       _fmt_date(srn.srn_date) if srn else None,
                "srnl":          si.srnl                 if si  else None,
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

        cc_summary = _get_brs_cc_summary(brs.id)

        try:
            sub_codes_list = json.loads(brs.item_category) if brs.item_category else []
        except Exception:
            sub_codes_list = []

        data = {
            "id":               brs.id,
            "brsNo":            brs.brs_no,
            "brsDate":          _fmt_date(brs.brs_date),
            "projectCode":      brs.project_code,
            "brrId":            brs.brr_id,
            "brrNo":            brs.brr.brr_no if brs.brr else None,
            "vendorId":         brs.vendor_id,
            "partyName":        brs.vendor.ledger_name        if brs.vendor else None,
            "partyAddress":     brs.vendor.registered_address if brs.vendor else None,
            "partyGstn":        brs.vendor.gstin              if brs.vendor else None,
            "receivedCategory": brs.received_category,
            "itemCategory":     sub_codes_list,
            "costHead":         brs.cost_head,
            "partyBillNo":      brs.party_bill_no,
            "partyDate":        _fmt_date(brs.party_date),
            "orderId":          brs.order_id,
            "orderNo":          brs.order.order_no              if brs.order else None,
            "orderDate":        _fmt_date(brs.order.order_date) if brs.order else None,
            "site":             brs.site,
            "billingAddress":   brs.billing_address,
            "shippingAddress":  brs.shipping_address,
            "basicAmount":      float(brs.basic_amount or 0),
            "gstAmount":        float(brs.gst_amount   or 0),
            "totalAmount":      float(brs.total_amount  or 0),
            "workflowStatus":   brs.workflow_status,
            "currentLevel":     brs.current_level,
            "locked":           brs.locked,
            "items":            items,
            "ccSummary":        cc_summary,
        }

        return res("BRS details fetched", data, 200)

    except Exception as e:
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 5. EDIT BRS
# ══════════════════════════════════════════════════════════════════

def edit_brs(brs_id, data, user_id):
    try:

        brs = BrsMaster.query.get(brs_id)
        if not brs:
            return res("BRS not found", [], 404)

        if brs.locked:
            return res("BRS cannot be edited", [], 400)

        if brs.workflow_status not in ["Draft", "Reback"]:
            return res("Only Draft or Reback BRS can be edited", [], 400)

        allowed = is_creator(brs.project_code, _MODULE, user_id)
        if not allowed:
            return res("You are not BRS creator", [], 403)

        items = data.get("items", [])
        if isinstance(items, str):
            items = json.loads(items)

        if not items:
            return res("Items required", [], 400)

        # update header fields
        for key, attr in [
            ("brsDate",          "brs_date"),
            ("vendorId",         "vendor_id"),
            ("partyBillNo",      "party_bill_no"),
            ("partyDate",        "party_date"),
            ("orderId",          "order_id"),
            ("site",             "site"),
            ("billingAddress",   "billing_address"),
            ("shippingAddress",  "shipping_address"),
            ("receivedCategory", "received_category"),
            ("costHead",         "cost_head"),
        ]:
            if data.get(key) is not None:
                setattr(brs, attr, data.get(key) or None)

        raw_sub = data.get("itemCategory") or data.get("subCategoryCode")
        if raw_sub is not None:
            if isinstance(raw_sub, str):
                try:
                    sub_codes_list = json.loads(raw_sub)
                except Exception:
                    sub_codes_list = [c.strip() for c in raw_sub.split(",") if c.strip()]
            elif isinstance(raw_sub, list):
                sub_codes_list = raw_sub
            else:
                sub_codes_list = [raw_sub] if raw_sub else []
            brs.item_category = json.dumps(sub_codes_list)

        # wipe old items & rebuild
        BrsItem.query.filter_by(brs_id=brs.id).delete()
        db.session.flush()

        total_basic = 0
        total_gst   = 0

        for row in items:

            srn_item_id = row.get("srnItemId")
            billing_qty = float(row.get("billingQty", 0))

            if billing_qty <= 0:
                db.session.rollback()
                return res(f"Invalid billingQty for srnItemId {srn_item_id}", [], 400)

            srn_item = SrnItem.query.get(srn_item_id)
            if not srn_item:
                db.session.rollback()
                return res(f"SRN item {srn_item_id} not found", [], 404)

            already_billed = _already_billed_qty(srn_item_id)
            available      = float(srn_item.current_received_qty or 0) - already_billed

            if billing_qty > available:
                db.session.rollback()
                return res(
                    f"Only {available} qty available for SRN item {srn_item_id}",
                    [], 400
                )

            oi          = srn_item.pw_order_item
            rate        = float(oi.rate        or 0) if oi else 0
            gst_percent = float(oi.gst_percent or 0) if oi else 0
            amount      = billing_qty * rate
            gst_amount  = (amount * gst_percent) / 100

            db.session.add(BrsItem(
                brs_id      = brs.id,
                srn_id      = srn_item.srn_id,
                srn_item_id = srn_item_id,
                billing_qty = billing_qty,
                rate        = rate,
                amount      = amount,
                gst_percent = gst_percent,
                gst_amount  = gst_amount,
            ))

            total_basic += amount
            total_gst   += gst_amount

        brs.basic_amount = total_basic
        brs.gst_amount   = total_gst
        brs.total_amount = total_basic + total_gst

        if brs.workflow_status == "Reback":
            brs.correction_sent_at = None

        brs.updated_by = user_id
        brs.updated_at = datetime.utcnow()

        db.session.commit()

        cc_summary = _get_brs_cc_summary(brs.id)

        return res(
            "BRS updated successfully",
            {"brsId": brs.id, "brsNo": brs.brs_no, "ccSummary": cc_summary},
            200
        )

    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 6. SUBMIT BRS
# ══════════════════════════════════════════════════════════════════

def submit_brs(brs_id, submitted_by=None):
    try:

        brs = BrsMaster.query.get(brs_id)
        if not brs:
            return res("BRS not found", [], 404)

        if brs.workflow_status not in ["Draft", "Reback"]:
            return res("BRS already submitted", [], 400)

        if not brs.items:
            return res("BRS has no items", [], 400)

        if brs.workflow_status == "Reback":
            brs.current_level = 0

        first_level = get_first_approver(brs.project_code, _MODULE)

        if not first_level:
            brs.workflow_status   = "Approved"
            brs.locked            = True
            brs.approved_by       = submitted_by
            brs.submitted_at      = datetime.utcnow()
            brs.final_approved_at = datetime.utcnow()
        else:
            brs.workflow_status = f"Pending_L{first_level.level_no}"
            brs.current_level   = first_level.level_no
            brs.locked          = True
            brs.submitted_at    = datetime.utcnow()

        create_history(
            project_code = brs.project_code,
            module_code  = _MODULE,
            record_id    = brs.id,
            level_no     = brs.current_level,
            action       = "SUBMIT",
            action_by    = submitted_by
        )

        brs.submitted_by = submitted_by
        brs.updated_by   = submitted_by
        brs.updated_at   = datetime.utcnow()

        db.session.commit()

        return res(
            "BRS submitted successfully",
            {"brsId": brs.id, "brsNo": brs.brs_no, "workflowStatus": brs.workflow_status},
            200
        )

    except SQLAlchemyError as e:
        db.session.rollback()
        return res(str(e), [], 500)
    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 7. APPROVE BRS
# ══════════════════════════════════════════════════════════════════

def approve_brs(brs_id, approved_by=None, comments=None):
    try:

        brs = BrsMaster.query.get(brs_id)
        if not brs:
            return res("BRS not found", [], 404)

        if not brs.workflow_status.startswith("Pending"):
            return res("BRS not pending", [], 400)

        allowed = is_current_approver(
            brs.project_code, _MODULE, brs.current_level, approved_by
        )
        if not allowed:
            return res("You are not current approver", [], 403)

        next_level = get_next_approver(brs.project_code, _MODULE, brs.current_level)

        if next_level:
            create_history(
                project_code = brs.project_code,
                module_code  = _MODULE,
                record_id    = brs.id,
                level_no     = brs.current_level,
                action       = "APPROVE",
                action_by    = approved_by,
                comments     = comments
            )
            brs.current_level   = next_level.level_no
            brs.workflow_status = f"Pending_L{next_level.level_no}"
        else:
            create_history(
                project_code = brs.project_code,
                module_code  = _MODULE,
                record_id    = brs.id,
                level_no     = brs.current_level,
                action       = "FINAL_APPROVE",
                action_by    = approved_by,
                comments     = comments
            )
            brs.workflow_status   = "Approved"
            brs.locked            = True
            brs.approved_by       = approved_by
            brs.final_approved_at = datetime.utcnow()

        brs.updated_by = approved_by
        brs.updated_at = datetime.utcnow()

        db.session.commit()

        return res(
            "BRS approved successfully",
            {"brsId": brs.id, "workflowStatus": brs.workflow_status, "currentLevel": brs.current_level},
            200
        )

    except SQLAlchemyError as e:
        db.session.rollback()
        return res(str(e), [], 500)
    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 8. REBACK BRS
# ══════════════════════════════════════════════════════════════════

def reback_brs(brs_id, reback_by=None, comments=None):
    try:

        brs = BrsMaster.query.get(brs_id)
        if not brs:
            return res("BRS not found", [], 404)

        if not brs.workflow_status.startswith("Pending"):
            return res("BRS not pending", [], 400)

        if not comments:
            return res("Comments required", [], 400)

        allowed = is_current_approver(
            brs.project_code, _MODULE, brs.current_level, reback_by
        )
        if not allowed:
            return res("You are not current approver", [], 403)

        brs.workflow_status    = "Reback"
        brs.locked             = False
        brs.correction_sent_at = datetime.utcnow()
        brs.updated_by         = reback_by
        brs.updated_at         = datetime.utcnow()

        create_history(
            project_code = brs.project_code,
            module_code  = _MODULE,
            record_id    = brs.id,
            level_no     = brs.current_level,
            action       = "REBACK",
            action_by    = reback_by,
            comments     = comments
        )

        db.session.commit()

        return res(
            "BRS sent for correction",
            {"brsId": brs.id, "workflowStatus": brs.workflow_status},
            200
        )

    except SQLAlchemyError as e:
        db.session.rollback()
        return res(str(e), [], 500)
    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 9. REJECT BRS
# ══════════════════════════════════════════════════════════════════

def reject_brs(brs_id, rejected_by=None, comments=None):
    try:

        brs = BrsMaster.query.get(brs_id)
        if not brs:
            return res("BRS not found", [], 404)

        if not brs.workflow_status.startswith("Pending"):
            return res("BRS not pending", [], 400)

        if not comments:
            return res("Comments required", [], 400)

        allowed = is_current_approver(
            brs.project_code, _MODULE, brs.current_level, rejected_by
        )
        if not allowed:
            return res("You are not current approver", [], 403)

        brs.workflow_status = "Rejected"
        brs.locked          = True
        brs.rejected_at     = datetime.utcnow()
        brs.rejected_by     = rejected_by
        brs.status          = "Inactive"
        brs.updated_by      = rejected_by
        brs.updated_at      = datetime.utcnow()

        create_history(
            project_code = brs.project_code,
            module_code  = _MODULE,
            record_id    = brs.id,
            level_no     = brs.current_level,
            action       = "REJECT",
            action_by    = rejected_by,
            comments     = comments
        )

        db.session.commit()

        return res(
            "BRS rejected",
            {"brsId": brs.id, "workflowStatus": brs.workflow_status},
            200
        )

    except SQLAlchemyError as e:
        db.session.rollback()
        return res(str(e), [], 500)
    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 10. BRS HISTORY
# ══════════════════════════════════════════════════════════════════

def get_brs_history(brs_id):
    try:

        brs = BrsMaster.query.get(brs_id)
        if not brs:
            return res("BRS not found", [], 404)

        rows = get_history(_MODULE, brs.id)

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

        return res("BRS history fetched", data, 200)

    except Exception as e:
        return res(str(e), [], 500)
