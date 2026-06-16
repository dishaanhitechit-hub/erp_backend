from sqlalchemy import func
from sqlalchemy.exc import SQLAlchemyError
from app.extensions import db
from datetime import datetime
import json

from app.models.ORDER_projectwork import ProjectWorkOrderMaster, ProjectWorkOrderItem
from app.models.srnMaster import SrnMaster, SrnItem
from app.models.bssMaster import BssMaster, BssItem
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

_MODULE = "billing_by_srn"


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
    Sum of billing_qty for this srn_item across all non-rejected BSS.
    Draft BSS counts — reduces available qty.
    Rejected BSS does not count — qty is freed back.
    """
    result = (
        db.session.query(
            func.coalesce(func.sum(BssItem.billing_qty), 0)
        )
        .join(BssMaster, BssMaster.id == BssItem.bss_id)
        .filter(
            BssItem.srn_item_id == srn_item_id,
            BssMaster.workflow_status != "Rejected"
        )
        .scalar()
    )
    return float(result)


def _get_bss_cc_summary(bss_id):
    """
    CC code summary for a BSS.
    BssItem → SrnItem → PwOrderItem → Item → CCCode
    """
    rows = (
        db.session.query(
            CCCode.cc_code,
            CCCode.cc_name,
            func.sum(BssItem.amount).label("basic_amount"),
            func.sum(BssItem.gst_amount).label("gst_amount"),
        )
        .join(SrnItem,              SrnItem.id              == BssItem.srn_item_id)
        .join(ProjectWorkOrderItem, ProjectWorkOrderItem.id == SrnItem.pw_order_item_id)
        .join(Item,                 Item.item_code          == ProjectWorkOrderItem.item_code)
        .join(CCCode,               CCCode.id               == Item.cc_code_id)
        .filter(BssItem.bss_id == bss_id)
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


def generate_bss_no():
    last = (
        db.session.query(BssMaster.bss_no)
        .order_by(BssMaster.id.desc())
        .first()
    )
    if last:
        try:
            last_serial = int(last[0])
        except Exception:
            last_serial = 850000
    else:
        last_serial = 850000
    return str(last_serial + 1)


# ══════════════════════════════════════════════════════════════════
# 1. GET PW ORDERS BY VENDOR  (filter panel)
# ══════════════════════════════════════════════════════════════════

def get_pw_orders_by_vendor(data):
    try:

        vendor_id    = data.get("vendorId")
        project_code = data.get("projectCode")

        if not vendor_id:
            return res("vendorId required", [], 400)
        if not project_code:
            return res("projectCode required", [], 400)

        base_query = ProjectWorkOrderMaster.query.filter(
            ProjectWorkOrderMaster.vendor_id       == vendor_id,
            ProjectWorkOrderMaster.project_code    == project_code,
            ProjectWorkOrderMaster.workflow_status == "Approved"
        )

        received_category  = data.get("receivedCategory")
        item_category      = data.get("itemCategory")
        cost_head          = data.get("costHead")

        filtered_query = base_query
        if received_category:
            filtered_query = filtered_query.filter(
                ProjectWorkOrderMaster.category_code == received_category
            )
        if item_category:
            filtered_query = filtered_query.filter(
                ProjectWorkOrderMaster.sub_codes.ilike(f'%"{item_category}"%')
            )
        if cost_head:
            filtered_query = filtered_query.filter(
                ProjectWorkOrderMaster.cost_head == cost_head
            )

        rows = filtered_query.order_by(ProjectWorkOrderMaster.id.desc()).all()

        if not rows and received_category:
            fallback_query = base_query
            if item_category:
                fallback_query = fallback_query.filter(
                    ProjectWorkOrderMaster.sub_codes.ilike(f'%"{item_category}"%')
                )
            if cost_head:
                fallback_query = fallback_query.filter(
                    ProjectWorkOrderMaster.cost_head == cost_head
                )
            rows = fallback_query.order_by(ProjectWorkOrderMaster.id.desc()).all()

        result = []
        for row in rows:
            try:
                sub_codes_list = json.loads(row.sub_codes) if row.sub_codes else []
            except Exception:
                sub_codes_list = []

            result.append({
                "id":               row.id,
                "orderNo":          row.order_no,
                "orderDate":        _fmt_date(row.order_date),
                "categoryCode":     row.category_code,
                "subCategoryCodes": sub_codes_list,
                "costHead":         row.cost_head,
                "basicAmount":      float(row.basic_amount or 0),
                "totalAmount":      float(row.total_amount or 0),
                "workflowStatus":   row.workflow_status,
            })

        return res("PW Orders fetched", result, 200)

    except Exception as e:
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 2. GET SRNs BY ORDER  (BSS selection grid)
# ══════════════════════════════════════════════════════════════════

def get_srns_by_order(order_id):
    """
    Returns all Approved SRNs for the given pw_order_id.
    Each SRN contains its items with:
      - receivedQty  (current_received_qty from SRN item)
      - alreadyBilled (sum from non-rejected BSS)
      - availableQty  (receivedQty - alreadyBilled)
    Items with availableQty <= 0 are still returned (for visibility).
    """
    try:

        order = ProjectWorkOrderMaster.query.get(order_id)
        if not order:
            return res("PW Order not found", [], 404)

        srns = SrnMaster.query.filter(
            SrnMaster.order_id       == order_id,
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

        return res("SRNs fetched for order", data, 200)

    except Exception as e:
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 3. CREATE BSS
# ══════════════════════════════════════════════════════════════════

def create_bss(data, user_id):
    try:

        allowed = is_creator(
            data.get("projectCode"),
            _MODULE,
            user_id
        )
        if not allowed:
            return res("You are not BSS creator", [], 403)

        items = data.get("items", [])
        if isinstance(items, str):
            items = json.loads(items)

        if not items:
            return res("No items provided", [], 400)

        bss_no = generate_bss_no()

        raw_sub = data.get("itemCategory") or data.get("subCategoryCode") or []
        if isinstance(raw_sub, str):
            try:
                sub_codes_list = json.loads(raw_sub)  # JSON array string
            except Exception:
                # comma-separated fallback: "SVC,COMP"
                sub_codes_list = [c.strip() for c in raw_sub.split(",") if c.strip()]
        elif isinstance(raw_sub, list):
            sub_codes_list = raw_sub
        else:
            sub_codes_list = [raw_sub] if raw_sub else []

        if not sub_codes_list:
            return res("At least one subCategoryCode required", [], 400)



        bss = BssMaster(
            bss_no            = bss_no,
            bss_date          = data.get("bssDate"),
            project_code      = data.get("projectCode"),
            vendor_id         = data.get("vendorId"),
            party_bill_no     = data.get("partyBillNo"),
            party_date        = data.get("partyDate") or None,
            received_category = data.get("receivedCategory"),
            item_category     = json.dumps(sub_codes_list),
            cost_head         = data.get("costHead"),
            order_id          = data.get("orderId"),
            site              = data.get("site"),
            billing_address   = data.get("billingAddress"),
            shipping_address  = data.get("shippingAddress"),
            workflow_status   = "Draft",
            current_level     = 0,
            locked            = False,
            created_by        = user_id,
        )

        db.session.add(bss)
        db.session.flush()

        total_basic = 0
        total_gst   = 0

        for row in items:

            srn_item_id = row.get("srnItemId")
            billing_qty = float(row.get("billingQty", 0))

            if billing_qty <= 0:
                db.session.rollback()
                return res(
                    f"Invalid billingQty for srnItemId {srn_item_id}",
                    [], 400
                )

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

            # get rate & gst from pw_order_item
            oi          = srn_item.pw_order_item
            rate        = float(oi.rate        or 0) if oi else 0
            gst_percent = float(oi.gst_percent or 0) if oi else 0
            amount      = billing_qty * rate
            gst_amount  = (amount * gst_percent) / 100

            db.session.add(BssItem(
                bss_id      = bss.id,
                srn_item_id = srn_item_id,
                billing_qty = billing_qty,
                rate        = rate,
                amount      = amount,
                gst_percent = gst_percent,
                gst_amount  = gst_amount,
            ))

            total_basic += amount
            total_gst   += gst_amount

        bss.basic_amount = total_basic
        bss.gst_amount   = total_gst
        bss.total_amount = total_basic + total_gst

        db.session.commit()

        cc_summary = _get_bss_cc_summary(bss.id)

        return res(
            "BSS created",
            {
                "bssId":     bss.id,
                "bssNo":     bss.bss_no,
                "ccSummary": cc_summary,
            },
            201
        )

    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 4. BSS LIST
# ══════════════════════════════════════════════════════════════════

def get_bss_list(data):
    try:

        if not data.get("projectCode"):
            return res("projectCode required", [], 400)

        query = BssMaster.query.filter(
            BssMaster.project_code == data.get("projectCode")
        )

        if data.get("vendorId"):
            query = query.filter(BssMaster.vendor_id == data.get("vendorId"))

        if data.get("orderId"):
            query = query.filter(BssMaster.order_id == data.get("orderId"))

        if data.get("workflowStatus"):
            query = query.filter(
                BssMaster.workflow_status == data.get("workflowStatus")
            )

        if data.get("search"):
            query = query.filter(
                BssMaster.bss_no.ilike(f"%{data.get('search')}%")
            )

        rows = query.order_by(BssMaster.id.desc()).all()

        result = []
        for row in rows:
            result.append({
                "id":               row.id,
                "bssNo":            row.bss_no,
                "bssDate":          _fmt_date(row.bss_date),
                "projectCode":      row.project_code,
                "receivedCategory": row.received_category,
                "itemCategory":     row.item_category,
                "costHead":         row.cost_head,
                "orderNo":          row.order.order_no    if row.order  else None,
                "partyName":        row.vendor.ledger_name if row.vendor else None,
                "partyBillNo":      row.party_bill_no,
                "basicAmount":      float(row.basic_amount or 0),
                "totalAmount":      float(row.total_amount or 0),
                "workflowStatus":   row.workflow_status,
            })

        return res("BSS list fetched", result, 200)

    except Exception as e:
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 5. BSS DETAILS
# ══════════════════════════════════════════════════════════════════

def get_bss_details(bss_id):
    try:

        bss = BssMaster.query.get(bss_id)
        if not bss:
            return res("BSS not found", [], 404)

        items = []
        for bi in bss.items:

            si  = bi.srn_item
            oi  = si.pw_order_item if si else None
            srn = si.srn           if si else None

            already_billed = _already_billed_qty(bi.srn_item_id)
            received_qty   = float(si.current_received_qty or 0) if si else 0
            available_qty  = max(received_qty - already_billed, 0)

            items.append({
                "id":            bi.id,
                "srnItemId":     bi.srn_item_id,
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

        cc_summary = _get_bss_cc_summary(bss.id)

        data = {
            "id":               bss.id,
            "bssNo":            bss.bss_no,
            "bssDate":          _fmt_date(bss.bss_date),
            "projectCode":      bss.project_code,
            "vendorId":         bss.vendor_id,
            "receivedCategory": bss.received_category,
            "itemCategory":     bss.item_category,
            "costHead":         bss.cost_head,
            "partyName":        bss.vendor.ledger_name        if bss.vendor else None,
            "partyAddress":     bss.vendor.registered_address if bss.vendor else None,
            "partyGstn":        bss.vendor.gstin              if bss.vendor else None,
            "partyBillNo":      bss.party_bill_no,
            "partyDate":        _fmt_date(bss.party_date),
            "orderId":          bss.order_id,
            "orderNo":          bss.order.order_no              if bss.order else None,
            "orderDate":        _fmt_date(bss.order.order_date) if bss.order else None,
            "site":             bss.site,
            "billingAddress":   bss.billing_address,
            "shippingAddress":  bss.shipping_address,
            "basicAmount":      float(bss.basic_amount or 0),
            "gstAmount":        float(bss.gst_amount   or 0),
            "totalAmount":      float(bss.total_amount  or 0),
            "workflowStatus":   bss.workflow_status,
            "currentLevel":     bss.current_level,
            "locked":           bss.locked,
            "items":            items,
            "ccSummary":        cc_summary,
        }

        return res("BSS details fetched", data, 200)

    except Exception as e:
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 6. EDIT BSS
# ══════════════════════════════════════════════════════════════════

def edit_bss(bss_id, data, user_id):
    try:

        bss = BssMaster.query.get(bss_id)
        if not bss:
            return res("BSS not found", [], 404)

        if bss.locked:
            return res("BSS cannot be edited", [], 400)

        if bss.workflow_status not in ["Draft", "Reback"]:
            return res("Only Draft or Reback BSS can be edited", [], 400)

        allowed = is_creator(bss.project_code, _MODULE, user_id)
        if not allowed:
            return res("You are not BSS creator", [], 403)

        items = data.get("items", [])
        if isinstance(items, str):
            items = json.loads(items)

        if not items:
            return res("Items required", [], 400)

        # update header
        if data.get("bssDate"):
            bss.bss_date = data.get("bssDate")
        if data.get("vendorId"):
            bss.vendor_id = data.get("vendorId")
        if data.get("partyBillNo"):
            bss.party_bill_no = data.get("partyBillNo")
        if data.get("partyDate"):
            bss.party_date = data.get("partyDate") or None
        if data.get("orderId"):
            bss.order_id = data.get("orderId")
        if data.get("site"):
            bss.site = data.get("site")
        if data.get("billingAddress"):
            bss.billing_address = data.get("billingAddress")
        if data.get("shippingAddress"):
            bss.shipping_address = data.get("shippingAddress")

        # wipe old items & rebuild
        BssItem.query.filter_by(bss_id=bss.id).delete()
        db.session.flush()

        total_basic = 0
        total_gst   = 0

        for row in items:

            srn_item_id = row.get("srnItemId")
            billing_qty = float(row.get("billingQty", 0))

            if billing_qty <= 0:
                db.session.rollback()
                return res(
                    f"Invalid billingQty for srnItemId {srn_item_id}",
                    [], 400
                )

            srn_item = SrnItem.query.get(srn_item_id)
            if not srn_item:
                db.session.rollback()
                return res(f"SRN item {srn_item_id} not found", [], 404)

            # items wiped above so _already_billed excludes this BSS
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

            db.session.add(BssItem(
                bss_id      = bss.id,
                srn_item_id = srn_item_id,
                billing_qty = billing_qty,
                rate        = rate,
                amount      = amount,
                gst_percent = gst_percent,
                gst_amount  = gst_amount,
            ))

            total_basic += amount
            total_gst   += gst_amount

        bss.basic_amount = total_basic
        bss.gst_amount   = total_gst
        bss.total_amount = total_basic + total_gst

        if bss.workflow_status == "Reback":
            bss.correction_sent_at = None

        bss.updated_by = user_id
        bss.updated_at = datetime.utcnow()

        db.session.commit()

        cc_summary = _get_bss_cc_summary(bss.id)

        return res(
            "BSS updated successfully",
            {
                "bssId":     bss.id,
                "bssNo":     bss.bss_no,
                "ccSummary": cc_summary,
            },
            200
        )

    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 7. SUBMIT BSS
# ══════════════════════════════════════════════════════════════════

def submit_bss(bss_id, submitted_by=None):
    try:

        bss = BssMaster.query.get(bss_id)
        if not bss:
            return res("BSS not found", [], 404)

        if bss.workflow_status not in ["Draft", "Reback"]:
            return res("BSS already submitted", [], 400)

        if not bss.items:
            return res("BSS has no items", [], 400)

        if bss.workflow_status == "Reback":
            bss.current_level = 0

        first_level = get_first_approver(bss.project_code, _MODULE)

        if not first_level:
            bss.workflow_status   = "Approved"
            bss.locked            = True
            bss.approved_by       = submitted_by
            bss.submitted_at      = datetime.utcnow()
            bss.final_approved_at = datetime.utcnow()
        else:
            bss.workflow_status = f"Pending_L{first_level.level_no}"
            bss.current_level   = first_level.level_no
            bss.locked          = True
            bss.submitted_at    = datetime.utcnow()

        create_history(
            project_code = bss.project_code,
            module_code  = _MODULE,
            record_id    = bss.id,
            level_no     = bss.current_level,
            action       = "SUBMIT",
            action_by    = submitted_by
        )

        bss.submitted_by = submitted_by
        bss.updated_by   = submitted_by
        bss.updated_at   = datetime.utcnow()

        db.session.commit()

        return res(
            "BSS submitted successfully",
            {
                "bssId":          bss.id,
                "bssNo":          bss.bss_no,
                "workflowStatus": bss.workflow_status,
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
# 8. APPROVE BSS
# ══════════════════════════════════════════════════════════════════

def approve_bss(bss_id, approved_by=None, comments=None):
    try:

        bss = BssMaster.query.get(bss_id)
        if not bss:
            return res("BSS not found", [], 404)

        if not bss.workflow_status.startswith("Pending"):
            return res("BSS not pending", [], 400)

        allowed = is_current_approver(
            bss.project_code, _MODULE, bss.current_level, approved_by
        )
        if not allowed:
            return res("You are not current approver", [], 403)

        next_level = get_next_approver(bss.project_code, _MODULE, bss.current_level)

        if next_level:
            create_history(
                project_code = bss.project_code,
                module_code  = _MODULE,
                record_id    = bss.id,
                level_no     = bss.current_level,
                action       = "APPROVE",
                action_by    = approved_by,
                comments     = comments
            )
            bss.current_level   = next_level.level_no
            bss.workflow_status = f"Pending_L{next_level.level_no}"
        else:
            create_history(
                project_code = bss.project_code,
                module_code  = _MODULE,
                record_id    = bss.id,
                level_no     = bss.current_level,
                action       = "FINAL_APPROVE",
                action_by    = approved_by,
                comments     = comments
            )
            bss.workflow_status   = "Approved"
            bss.locked            = True
            bss.approved_by       = approved_by
            bss.final_approved_at = datetime.utcnow()

        bss.updated_by = approved_by
        bss.updated_at = datetime.utcnow()

        db.session.commit()

        return res(
            "BSS approved successfully",
            {
                "bssId":          bss.id,
                "workflowStatus": bss.workflow_status,
                "currentLevel":   bss.current_level,
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
# 9. REBACK BSS
# ══════════════════════════════════════════════════════════════════

def reback_bss(bss_id, reback_by=None, comments=None):
    try:

        bss = BssMaster.query.get(bss_id)
        if not bss:
            return res("BSS not found", [], 404)

        if not bss.workflow_status.startswith("Pending"):
            return res("BSS not pending", [], 400)

        if not comments:
            return res("Comments required", [], 400)

        allowed = is_current_approver(
            bss.project_code, _MODULE, bss.current_level, reback_by
        )
        if not allowed:
            return res("You are not current approver", [], 403)

        bss.workflow_status    = "Reback"
        bss.locked             = False
        bss.correction_sent_at = datetime.utcnow()
        bss.updated_by         = reback_by
        bss.updated_at         = datetime.utcnow()

        create_history(
            project_code = bss.project_code,
            module_code  = _MODULE,
            record_id    = bss.id,
            level_no     = bss.current_level,
            action       = "REBACK",
            action_by    = reback_by,
            comments     = comments
        )

        db.session.commit()

        return res(
            "BSS sent for correction",
            {"bssId": bss.id, "workflowStatus": bss.workflow_status},
            200
        )

    except SQLAlchemyError as e:
        db.session.rollback()
        return res(str(e), [], 500)
    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 10. REJECT BSS
# ══════════════════════════════════════════════════════════════════

def reject_bss(bss_id, rejected_by=None, comments=None):
    try:

        bss = BssMaster.query.get(bss_id)
        if not bss:
            return res("BSS not found", [], 404)

        if not bss.workflow_status.startswith("Pending"):
            return res("BSS not pending", [], 400)

        if not comments:
            return res("Comments required", [], 400)

        allowed = is_current_approver(
            bss.project_code, _MODULE, bss.current_level, rejected_by
        )
        if not allowed:
            return res("You are not current approver", [], 403)

        bss.workflow_status = "Rejected"
        bss.locked          = True
        bss.rejected_at     = datetime.utcnow()
        bss.rejected_by     = rejected_by
        bss.status          = "Inactive"
        bss.updated_by      = rejected_by
        bss.updated_at      = datetime.utcnow()

        create_history(
            project_code = bss.project_code,
            module_code  = _MODULE,
            record_id    = bss.id,
            level_no     = bss.current_level,
            action       = "REJECT",
            action_by    = rejected_by,
            comments     = comments
        )

        db.session.commit()

        return res(
            "BSS rejected",
            {"bssId": bss.id, "workflowStatus": bss.workflow_status},
            200
        )

    except SQLAlchemyError as e:
        db.session.rollback()
        return res(str(e), [], 500)
    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 11. BSS HISTORY
# ══════════════════════════════════════════════════════════════════

def get_bss_history(bss_id):
    try:

        bss = BssMaster.query.get(bss_id)
        if not bss:
            return res("BSS not found", [], 404)

        rows = get_history(_MODULE, bss.id)

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

        return res("BSS history fetched", data, 200)

    except Exception as e:
        return res(str(e), [], 500)
