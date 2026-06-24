# app/modules/resources/order_projectwork/service.py
#
# Project-Work Order Service
# ──────────────────────────────────────────────────────────────────
# Differences from the main Order service:
#   1. NO indent linkage — items are picked directly from the item list.
#   2. Item list supports MULTIPLE sub-category codes in one request
#      (e.g.  ?subCodes=SVC,COMP fetches items from both categories).
#   3. Max-quantity guard: before saving an item this service calls
#      get_item_max_qty(project_code, item_code).  Return None → no
#      limit enforced.  When you create the project-item allocation
#      table later, plug it into that helper function only — every
#      create / edit check picks up the limit automatically.
#   4. Workflow module code is "pw_order" (kept separate from "order").
#   5. Order-number series starts at 550000.
# ──────────────────────────────────────────────────────────────────

from sqlalchemy import func
from sqlalchemy.exc import SQLAlchemyError
from app.extensions import db
import json
from datetime import datetime

from app.models.ORDER_projectwork import (
    ProjectWorkOrderMaster,
    ProjectWorkOrderItem,
    ProjectWorkOrderTermsCondition,
)
from app.models.item import Item
from app.models.cc_code import CCCode
from app.models.category_group import GroupMaster, CategoryMaster
from app.models.unit import Unit
from app.models.term_conditions import TermConditions
from app.models.vendor import Vendor
from app.alias_helper import *
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


# ═══════════════════════════════════════════════════════════════════
# MAX-QTY HELPER
# ═══════════════════════════════════════════════════════════════════

def get_item_max_qty(project_code: str, item_code: str):
    """
    Return the maximum quantity allowed for *item_code* under
    *project_code*, or None if no limit is defined.

    ──────────────────────────────────────────────────────────────
    PLACEHOLDER – wire this to your project-item allocation model
    once you create it.  Example:

        from app.models.pw_item_allocation import PwItemAllocation
        row = PwItemAllocation.query.filter_by(
            project_code=project_code, item_code=item_code
        ).first()
        return float(row.max_qty) if row else None
    ──────────────────────────────────────────────────────────────
    """
    return None          # No limit until allocation table is added


# ═══════════════════════════════════════════════════════════════════
# CC-CODE SUMMARY (reused by create / edit response)
# ═══════════════════════════════════════════════════════════════════

def get_pw_cc_code_summary(order_id: int) -> list:

    rows = (
        db.session.query(
            CCCode.cc_code,
            CCCode.cc_name,
            func.sum(ProjectWorkOrderItem.amount).label("basic_amount"),
            func.sum(ProjectWorkOrderItem.gst_amount).label("gst_amount"),
        )
        .join(Item, Item.item_code == ProjectWorkOrderItem.item_code)
        .join(CCCode, CCCode.id == Item.cc_code_id)
        .filter(ProjectWorkOrderItem.order_id == order_id)
        .group_by(CCCode.cc_code, CCCode.cc_name)
        .all()
    )

    return [
        {
            "ccCode":      row.cc_code,
            "ccName":      row.cc_name,
            "basicAmount": float(row.basic_amount or 0),
            "gstAmount":   float(row.gst_amount or 0),
            "totalAmount": float((row.basic_amount or 0) + (row.gst_amount or 0)),
        }
        for row in rows
    ]


# ═══════════════════════════════════════════════════════════════════
# ORDER-NUMBER GENERATOR
# ═══════════════════════════════════════════════════════════════════

def generate_pw_order_no() -> str:

    last = (
        db.session.query(ProjectWorkOrderMaster.order_no)
        .order_by(ProjectWorkOrderMaster.id.desc())
        .first()
    )

    if last:
        try:
            last_serial = int(last[0])
        except Exception:
            last_serial = 550000
    else:
        last_serial = 550000

    return str(last_serial + 1)


# ═══════════════════════════════════════════════════════════════════
# ITEM LIST  (multi-subcategory, direct from item master)
# ═══════════════════════════════════════════════════════════════════

def get_item_list_by_subcategories(
    project_code,               # optional – only used for orderedQty calc
    sub_codes,                  # str (comma-sep) or list
) -> object:
    """
    Return items whose category_code is in *sub_codes*.
    Items are global (not project-linked) so sub_codes is the only
    required filter.

    project_code is OPTIONAL:
      • Passed  → orderedQty shows how much of each item has already
                  been ordered under that project in PW orders.
      • Not passed / None → orderedQty is 0 for every item (no
                  project context); no error is raised.

    Multiple sub_codes accepted:
        ?subCodes=SVC           → single category
        ?subCodes=SVC,COMP      → items from Service AND Composite
    """

    try:

        # ── normalise sub_codes ───────────────────────────────────
        if isinstance(sub_codes, str):
            codes = [c.strip() for c in sub_codes.split(",") if c.strip()]
        else:
            codes = list(sub_codes or [])

        if not codes:
            return res("subCodes required", [], 400)

        # ── ordered-qty subquery (skipped when no project_code) ───
        # When project_code is None the subquery is not built at all;
        # the outer join just produces 0 for every item via coalesce.
        if project_code:
            ordered_subq = (
                db.session.query(
                    ProjectWorkOrderItem.item_code,
                    func.coalesce(
                        func.sum(ProjectWorkOrderItem.qty), 0
                    ).label("ordered_qty"),
                )
                .join(
                    ProjectWorkOrderMaster,
                    ProjectWorkOrderMaster.id == ProjectWorkOrderItem.order_id,
                )
                .filter(
                    ProjectWorkOrderMaster.project_code == project_code,
                    ProjectWorkOrderMaster.workflow_status != "Rejected",
                )
                .group_by(ProjectWorkOrderItem.item_code)
                .subquery()
            )
            ordered_col  = func.coalesce(ordered_subq.c.ordered_qty, 0)
            ordered_join = (ordered_subq, ordered_subq.c.item_code == Item.item_code)
        else:
            # No project → treat ordered qty as 0 for all items
            ordered_subq = None
            ordered_col  = func.coalesce(None, 0)   # always 0
            ordered_join = None

        # ── main item query ───────────────────────────────────────
        q = (
            db.session.query(
                Item.item_code,
                Item.item_name,
                Unit.unit_name.label("item_unit"),
                CategoryMaster.fixed_code.label("sub_code"),
                CategoryMaster.category_name.label("sub_code_name"),
                ordered_col.label("ordered_qty"),
            )
            .join(
                CategoryMaster,
                CategoryMaster.fixed_code == Item.category_code,
            )
            .outerjoin(Unit, Unit.id == Item.unit_id)
        )

        if ordered_join:
            q = q.outerjoin(*ordered_join)

        rows = (
            q.filter(
                Item.category_code.in_(codes),
                Item.status == "Active",
            )
            .order_by(CategoryMaster.fixed_code, Item.item_name)
            .all()
        )

        result = []
        for row in rows:
            ordered = float(row.ordered_qty)
            max_qty = get_item_max_qty(project_code, row.item_code)
            balance = (
                round(max_qty - ordered, 4) if max_qty is not None else None
            )

            result.append({
                "itemCode":    row.item_code,
                "itemName":    row.item_name,
                "itemUnit":    row.item_unit,
                "subCode":     row.sub_code,
                "subCodeName": row.sub_code_name,
                "orderedQty":  ordered,
                "maxQty":      max_qty,
                "balanceQty":  balance,
                "orderQty":    0,
            })

        return res("Item list fetched", result, 200)

    except Exception as e:
        return res(str(e), [], 500)


# ═══════════════════════════════════════════════════════════════════
# CREATE ORDER
# ═══════════════════════════════════════════════════════════════════

def create_pw_order(data, user_id, files=None):

    allowed = is_creator(data.get("projectCode"), get_approval_module("pw_order"), user_id)
    if not allowed:
        return res("You are not service order creator", [], 403)

    try:

        items = data.get("items", [])
        terms = data.get("terms", [])

        if isinstance(items, str):
            items = json.loads(items)
        if isinstance(terms, str):
            terms = json.loads(terms)

        if not items:
            return res("No items selected", [], 400)

        # ── supporting file ───────────────────────────────────────
        order_file = files.get("orderFile") if files else None
        if not order_file:
            return res("Order file required", [], 400)

        xtemp = generate_pw_order_no()

        supporting_file = upload_file_to_bunny(
            file=order_file,
            mainFolder="pw_order",
            subFolder= xtemp,
            fileName="support",
        )
        # if not supporting_file:
        #     return res("ladle miaooo", [], 400)

        # ── parse sub-category codes (one or many) ───────────────
        raw_sub = data.get("subCategoryCodes") or data.get("subCategoryCode") or []
        if isinstance(raw_sub, str):
            try:
                sub_codes_list = json.loads(raw_sub)   # JSON array string
            except Exception:
                # comma-separated fallback: "SVC,COMP"
                sub_codes_list = [c.strip() for c in raw_sub.split(",") if c.strip()]
        elif isinstance(raw_sub, list):
            sub_codes_list = raw_sub
        else:
            sub_codes_list = [raw_sub] if raw_sub else []

        if not sub_codes_list:
            return res("At least one subCategoryCode required", [], 400)

        # ── master record ─────────────────────────────────────────
        order = ProjectWorkOrderMaster(
            order_no         = xtemp,
            project_code     = data.get("projectCode"),
            category_code    = data.get("categoryCode"),
            sub_codes        = json.dumps(sub_codes_list),   # stored as JSON array
            cost_head          =data.get("costHead"),
            vendor_id        = data.get("vendorId"),
            order_date       = data.get("orderDate"),
            validity_date    = data.get("validityDate"),
            quotation_no     = data.get("quotationNo"),
            quotation_date   = data.get("quotationDate"),
            billing_address  = data.get("billingAddress"),
            shipping_address = data.get("shippingAddress"),
            contact_person=data.get("contactPerson"),
            contact_number=data.get("contactNumber"),
            order_message    = data.get("orderMessage"),
            supporting_file  = supporting_file,
            workflow_status  = "Draft",
            current_level    = 0,
            locked           = False,
            created_by       = user_id,
        )

        db.session.add(order)
        db.session.flush()

        total_basic = 0
        total_gst   = 0

        # ── items ─────────────────────────────────────────────────
        for row in items:

            item_code    = row.get("itemCode")
            requested_qty = float(row.get("qty", 0))

            # validate item exists
            item_obj = Item.query.filter_by(item_code=item_code).first()
            if not item_obj:
                db.session.rollback()
                return res(f"Item '{item_code}' not found", [], 404)

            if requested_qty <= 0:
                db.session.rollback()
                return res(
                    f"Invalid qty for item {item_code}", [], 400
                )

            # ── MAX-QTY CHECK ─────────────────────────────────────
            # Checks how much of this item has already been ordered
            # for this project across all PW orders (excl. Rejected).
            # When get_item_max_qty returns a value, the new qty must
            # not push the running total past that limit.
            max_qty = get_item_max_qty(order.project_code, item_code)

            already_ordered = float(
                db.session.query(
                    func.coalesce(
                        func.sum(ProjectWorkOrderItem.qty), 0
                    )
                )
                .join(
                    ProjectWorkOrderMaster,
                    ProjectWorkOrderMaster.id == ProjectWorkOrderItem.order_id,
                )
                .filter(
                    ProjectWorkOrderMaster.project_code == order.project_code,
                    ProjectWorkOrderItem.item_code      == item_code,
                    ProjectWorkOrderMaster.workflow_status != "Rejected",
                )
                .scalar()
            )

            if max_qty is not None:
                if already_ordered + requested_qty > max_qty:
                    remaining = max_qty - already_ordered
                    db.session.rollback()
                    return res(
                        f"Item '{item_code}': max allowed {max_qty}, "
                        f"already ordered {already_ordered}, "
                        f"available {remaining}",
                        [],
                        400,
                    )

            # ── financials ────────────────────────────────────────
            rate        = float(row.get("rate", 0))
            gst_percent = float(row.get("gstPercent", 0))
            amount      = requested_qty * rate
            gst_amount  = (amount * gst_percent) / 100

            balance_qty = (
                round(max_qty - already_ordered - requested_qty, 4)
                if max_qty is not None
                else 0
            )

            db.session.add(
                ProjectWorkOrderItem(
                    order_id    = order.id,
                    item_code   = item_code,
                    custom_note = row.get("note"),
                    qty         = requested_qty,
                    balance_qty = balance_qty,
                    location    = row.get("location"),
                    rate        = rate,
                    amount      = amount,
                    gst_percent = gst_percent,
                    gst_amount  = gst_amount,
                )
            )

            total_basic += amount
            total_gst   += gst_amount

        # ── terms ─────────────────────────────────────────────────
        for idx, row in enumerate(terms, start=1):

            term = TermConditions.query.get(row.get("termId"))
            if not term:
                db.session.rollback()
                return res(
                    f"Term {row.get('termId')} not found", [], 404
                )

            db.session.add(
                ProjectWorkOrderTermsCondition(
                    order_id           = order.id,
                    term_id            = term.id,
                    custom_description = row.get("description") or None,
                    sequence_no        = row.get("sequenceNo", idx),
                    created_by         = user_id,
                )
            )

        # ── totals ────────────────────────────────────────────────
        order.basic_amount = total_basic
        order.gst_amount   = total_gst
        order.total_amount = total_basic + total_gst

        db.session.commit()

        cc_summary = get_pw_cc_code_summary(order.id)

        return res(
            "Service order created",
            {
                "orderId":   order.id,
                "orderNo":   order.order_no,
                "ccSummary": cc_summary,
            },
            201,
        )

    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ═══════════════════════════════════════════════════════════════════
# EDIT ORDER
# ═══════════════════════════════════════════════════════════════════

def edit_pw_order(order_id, data, user_id, files=None):

    try:

        order = ProjectWorkOrderMaster.query.get(order_id)
        if not order:
            return res("Service order not found", [], 404)

        if order.locked:
            return res("Service order cannot be edited", [], 400)

        allowed = is_creator(order.project_code, get_approval_module("pw_order"), user_id)
        if not allowed:
            return res("You are not Service order creator", [], 403)

        items = data.get("items")
        if not items:
            return res("Items required", [], 400)

        if isinstance(items, str):
            items = json.loads(items)

        # ── header ────────────────────────────────────────────────
        order.vendor_id        = data.get("vendorId",        order.vendor_id)
        order.order_date       = data.get("orderDate",       order.order_date)
        order.validity_date    = data.get("validityDate",    order.validity_date)
        order.billing_address  = data.get("billingAddress",  order.billing_address)
        order.shipping_address = data.get("shippingAddress", order.shipping_address)
        order.order_message    = data.get("orderMessage",    order.order_message)
        order.contact_person = data.get("contactPerson", order.contact_person)
        order.contact_number = data.get("contactNumber", order.contact_number)
        order.quotation_no     = data.get("quotationNo",     order.quotation_no)
        order.quotation_date   = data.get("quotationDate",   order.quotation_date)

        # ── update sub-category codes if provided ─────────────────
        raw_sub = data.get("subCategoryCodes") or data.get("subCategoryCode")
        if raw_sub:
            if isinstance(raw_sub, str):
                try:
                    new_sub_codes = json.loads(raw_sub)
                except Exception:
                    new_sub_codes = [c.strip() for c in raw_sub.split(",") if c.strip()]
            elif isinstance(raw_sub, list):
                new_sub_codes = raw_sub
            else:
                new_sub_codes = [raw_sub]
            if new_sub_codes:
                order.sub_codes = json.dumps(new_sub_codes)

        # ── file update ───────────────────────────────────────────
        if files:
            order_file = files.get("orderFile")
            if order_file:
                order.supporting_file = upload_file_to_bunny(
                    file=order_file,
                    mainFolder="pw_order",
                    subFolder=order.id,
                    fileName="support",
                )

        # ── wipe old items & terms (flush so subquery excludes them)
        ProjectWorkOrderItem.query.filter_by(order_id=order.id).delete()
        ProjectWorkOrderTermsCondition.query.filter_by(order_id=order.id).delete()
        db.session.flush()

        # ── rebuild items ─────────────────────────────────────────
        total_basic = 0
        total_gst   = 0

        for row in items:

            item_code     = row.get("itemCode")
            requested_qty = float(row.get("qty", 0))

            item_obj = Item.query.filter_by(item_code=item_code).first()
            if not item_obj:
                db.session.rollback()
                return res(f"Item '{item_code}' not found", [], 404)

            if requested_qty <= 0:
                db.session.rollback()
                return res(f"Invalid qty for item {item_code}", [], 400)

            # ── MAX-QTY CHECK ─────────────────────────────────────
            # Re-compute already_ordered excluding THIS order
            # (items were wiped above, so the subquery is clean).
            max_qty = get_item_max_qty(order.project_code, item_code)

            already_ordered = float(
                db.session.query(
                    func.coalesce(
                        func.sum(ProjectWorkOrderItem.qty), 0
                    )
                )
                .join(
                    ProjectWorkOrderMaster,
                    ProjectWorkOrderMaster.id == ProjectWorkOrderItem.order_id,
                )
                .filter(
                    ProjectWorkOrderMaster.project_code == order.project_code,
                    ProjectWorkOrderItem.item_code      == item_code,
                    ProjectWorkOrderMaster.workflow_status != "Rejected",
                )
                .scalar()
            )

            if max_qty is not None:
                if already_ordered + requested_qty > max_qty:
                    remaining = max_qty - already_ordered
                    db.session.rollback()
                    return res(
                        f"Item '{item_code}': max allowed {max_qty}, "
                        f"already ordered {already_ordered}, "
                        f"available {remaining}",
                        [],
                        400,
                    )

            rate        = float(row.get("rate", 0))
            gst_percent = float(row.get("gstPercent", 0))
            amount      = requested_qty * rate
            gst_amount  = (amount * gst_percent) / 100

            balance_qty = (
                round(max_qty - already_ordered - requested_qty, 4)
                if max_qty is not None
                else 0
            )

            db.session.add(
                ProjectWorkOrderItem(
                    order_id    = order.id,
                    item_code   = item_code,
                    custom_note = row.get("note"),
                    qty         = requested_qty,
                    balance_qty = balance_qty,
                    location    = row.get("location"),
                    rate        = rate,
                    amount      = amount,
                    gst_percent = gst_percent,
                    gst_amount  = gst_amount,
                )
            )

            total_basic += amount
            total_gst   += gst_amount

        # ── rebuild terms ─────────────────────────────────────────
        terms = data.get("terms", [])
        if isinstance(terms, str):
            terms = json.loads(terms)

        for idx, row in enumerate(terms, start=1):
            term = TermConditions.query.get(row.get("termId"))
            if not term:
                db.session.rollback()
                return res(f"Term {row.get('termId')} not found", [], 404)

            db.session.add(
                ProjectWorkOrderTermsCondition(
                    order_id           = order.id,
                    term_id            = term.id,
                    custom_description = row.get("description") or None,
                    sequence_no        = row.get("sequenceNo", idx),
                    created_by         = user_id,
                )
            )

        # ── totals ────────────────────────────────────────────────
        order.basic_amount = total_basic
        order.gst_amount   = total_gst
        order.total_amount = total_basic + total_gst

        if order.workflow_status == "Reback":
            order.correction_sent_at = None

        order.updated_by = user_id
        order.updated_at = datetime.utcnow()

        db.session.commit()

        return res(
            "Service order updated successfully",
            [{"orderId": order.id, "orderNo": order.order_no}],
            200,
        )

    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ═══════════════════════════════════════════════════════════════════
# ORDER DETAILS
# ═══════════════════════════════════════════════════════════════════

def get_pw_order_details(order_id: int):

    try:

        order = ProjectWorkOrderMaster.query.filter_by(id=order_id).first()
        if not order:
            return res("PW Order not found", [], 404)

        items = []
        for item in order.items:
            max_qty = get_item_max_qty(order.project_code, item.item_code)
            items.append({
                "id":          item.id,
                "itemCode":    item.item_code,
                "itemName":    item.item.item_name if item.item else None,
                "itemUnit":    (
                    item.item.unit.unit_name
                    if item.item and item.item.unit
                    else None
                ),
                "note":        item.custom_note,
                "qty":         float(item.qty or 0),
                "amendQty":    float(item.amend_qty or 0),
                "usedQty":     float(item.used_qty or 0),
                "balanceQty":  float(item.balance_qty or 0),
                "rate":        float(item.rate or 0),
                "amount":      float(item.amount or 0),
                "gstPercent":  float(item.gst_percent or 0),
                "gstAmount":   float(item.gst_amount or 0),
                "location":    item.location,
                "itemStatus":  item.item_status,
                "maxQty":      max_qty,
            })

        terms = []
        for t in order.terms_conditions:
            terms.append({
                "id":          t.id,
                "termId":      t.term_id,
                "header":      t.term.header,
                "subHeader":   t.term.sub_header,
                "description": (
                    t.custom_description or t.term.term_description
                ),
                "sequenceNo":  t.sequence_no,
            })

        cc_summary = get_pw_cc_code_summary(order.id)

        # parse stored JSON list back to Python list
        try:
            sub_codes_list = json.loads(order.sub_codes) if order.sub_codes else []
        except Exception:
            sub_codes_list = []

        data = {
            "id":               order.id,
            "orderNo":          order.order_no,
            "projectCode":      order.project_code,
            "projectName":      (
                order.project.project_name if order.project else None
            ),
            "subCategoryCodes": sub_codes_list,   # list e.g. ["SVC","COMP"]
            "categoryCode":     order.category_code,
            "costHead":order.cost_head,
            "vendorId":        order.vendor_id,
            "vendorName":      (
                order.vendor.ledger_name if order.vendor else None
            ),
            "orderDate":       str(order.order_date),
            "validityDate":    (
                str(order.validity_date) if order.validity_date else None
            ),
            "quotationNo":     order.quotation_no,
            "quotationDate":   (
                order.quotation_date.strftime(
                    "%Y-%m-%d") if order.quotation_date else None
            ),
            "billingAddress":  order.billing_address,
            "shippingAddress": order.shipping_address,
            "orderMessage":    order.order_message,
            "orderFile":       order.supporting_file,
            "contactPerson": order.contact_person,
            "contactNumber": order.contact_number,

            "bookedAmount":    float(order.booked_amount or 0),
            "basicAmount":     float(order.basic_amount or 0),
            "gstAmount":       float(order.gst_amount or 0),
            "totalAmount":     float(order.total_amount or 0),
            "workflowStatus":  order.workflow_status,
            # "status":          order.status,
            "locked":          order.locked,
            "currentLevel":    order.current_level,
            "items":           items,
            "terms":           terms,
            "ccSummary":       cc_summary,
        }

        return res("Service order details fetched", data, 200)

    except Exception as e:
        return res(str(e), [], 500)


# ═══════════════════════════════════════════════════════════════════
# ORDER LIST
# ═══════════════════════════════════════════════════════════════════

def get_pw_order_list(data: dict):

    try:

        if not data.get("projectCode"):
            return res("projectCode required", [], 400)

        query = ProjectWorkOrderMaster.query.filter(
            ProjectWorkOrderMaster.project_code == data.get("projectCode")
        )

        # sub-category filter: match if the stored JSON contains the code
        if data.get("subCategoryCode"):
            query = query.filter(
                ProjectWorkOrderMaster.sub_codes.ilike(
                    f'%"{data.get("subCategoryCode")}"%'
                )
            )

        if data.get("categoryCode"):
            query = query.filter(
                ProjectWorkOrderMaster.category_code == data.get("categoryCode")
            )

        if data.get("workflowStatus"):
            query = query.filter(
                ProjectWorkOrderMaster.workflow_status == data.get("workflowStatus")
            )

        if data.get("search"):
            query = query.filter(
                ProjectWorkOrderMaster.order_no.ilike(
                    f"%{data.get('search')}%"
                )
            )

        rows = query.order_by(ProjectWorkOrderMaster.id.desc()).all()

        result = []
        for row in rows:
            result.append({
                "id":             row.id,
                "orderNo":        row.order_no,
                "projectCode":    row.project_code,
                "projectName":    (
                    row.project.project_name if row.project else None
                ),
                "partyName":      (
                    row.vendor.ledger_name if row.vendor else None
                ),
                "orderDate":      str(row.order_date),
                "categoryCode":    row.category_code,
                "subCategoryCodes": (
                    json.loads(row.sub_codes) if row.sub_codes else []
                ),
                "basicAmount":    float(row.basic_amount or 0),
                "gstAmount":      float(row.gst_amount or 0),
                "totalAmount":    float(row.total_amount or 0),
                "bookedAmount":   float(row.booked_amount or 0),
                # "workflowStatus": row.workflow_status,
                "status":         row.workflow_status
            })

        return res("Service orders fetched", result, 200)

    except Exception as e:
        return res(str(e), [], 500)


# ═══════════════════════════════════════════════════════════════════
# SUBMIT
# ═══════════════════════════════════════════════════════════════════

def submit_pw_order(order_id: int, submitted_by=None):

    try:

        order = ProjectWorkOrderMaster.query.get(order_id)
        if not order:
            return res("Service order not found", [], 404)

        if order.workflow_status not in ["Draft", "Reback"]:
            return res("Service Order already submitted", [], 400)

        if not order.items:
            return res("Service Order has no items", [], 400)

        if order.workflow_status == "Reback":
            order.current_level = 0

        first_level = get_first_approver(order.project_code,  get_approval_module("pw_order"))

        if not first_level:
            # Auto-approve when no approver is configured
            order.workflow_status   = "Approved"
            order.locked            = True
            order.approved_by       = submitted_by
            order.submitted_at      = datetime.utcnow()
            order.final_approved_at = datetime.utcnow()
        else:
            order.workflow_status = f"Pending_L{first_level.level_no}"
            order.current_level   = first_level.level_no
            order.locked          = True
            order.submitted_at    = datetime.utcnow()

        create_history(
            project_code = order.project_code,
            module_code  = "pw_order",
            record_id    = order.id,
            level_no     = order.current_level,
            action       = "SUBMIT",
            action_by    = submitted_by,
        )

        order.updated_by  = submitted_by
        order.submitted_by = submitted_by
        order.updated_at  = datetime.utcnow()

        db.session.commit()

        return res(
            "Service order submitted successfully",
            {
                "orderId":        order.id,
                "orderNo":        order.order_no,
                "workflowStatus": order.workflow_status,
            },
            200,
        )

    except SQLAlchemyError as e:
        db.session.rollback()
        return res(str(e), [], 500)
    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ═══════════════════════════════════════════════════════════════════
# APPROVE
# ═══════════════════════════════════════════════════════════════════

def approve_pw_order(order_id: int, approved_by=None, comments=None):

    try:

        order = ProjectWorkOrderMaster.query.get(order_id)
        if not order:
            return res("Service order not found", [], 404)

        if not order.workflow_status.startswith("Pending"):
            return res("Service order not pending", [], 400)

        allowed = is_current_approver(
            order.project_code, get_approval_module("pw_order"), order.current_level, approved_by
        )
        if not allowed:
            return res("You are not current approver", [], 403)

        next_level = get_next_approver(
            order.project_code, get_approval_module("pw_order"), order.current_level
        )

        if next_level:
            create_history(
                project_code = order.project_code,
                module_code  = "pw_order",
                record_id    = order.id,
                level_no     = order.current_level,
                action       = "APPROVE",
                action_by    = approved_by,
                comments     = comments,
            )
            order.current_level   = next_level.level_no
            order.workflow_status = f"Pending_L{next_level.level_no}"

        else:
            create_history(
                project_code = order.project_code,
                module_code  = "pw_order",
                record_id    = order.id,
                level_no     = order.current_level,
                action       = "FINAL_APPROVE",
                action_by    = approved_by,
                comments     = comments,
            )
            order.workflow_status   = "Approved"
            order.locked            = True
            order.approved_by       = approved_by
            order.final_approved_at = datetime.utcnow()

        order.updated_by = approved_by
        order.updated_at = datetime.utcnow()

        db.session.commit()

        return res(
            "Service order approved successfully",
            {
                "orderId":        order.id,
                "workflowStatus": order.workflow_status,
                "currentLevel":   order.current_level,
            },
            200,
        )

    except SQLAlchemyError as e:
        db.session.rollback()
        return res(str(e), [], 500)
    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ═══════════════════════════════════════════════════════════════════
# REBACK
# ═══════════════════════════════════════════════════════════════════

def reback_pw_order(order_id: int, reback_by=None, comments=None):

    try:

        order = ProjectWorkOrderMaster.query.get(order_id)
        if not order:
            return res("Service order not found", [], 404)

        if not order.workflow_status.startswith("Pending"):
            return res("Service order not pending", [], 400)

        if not comments:
            return res("Comments required", [], 400)

        allowed = is_current_approver(
            order.project_code, get_approval_module("pw_order"), order.current_level, reback_by
        )
        if not allowed:
            return res("You are not current approver", [], 403)

        order.workflow_status    = "Reback"
        order.locked             = False
        order.correction_sent_at = datetime.utcnow()
        order.updated_by         = reback_by
        order.updated_at         = datetime.utcnow()

        create_history(
            project_code = order.project_code,
            module_code  = "pw_order",
            record_id    = order.id,
            level_no     = order.current_level,
            action       = "REBACK",
            action_by    = reback_by,
            comments     = comments,
        )

        db.session.commit()

        return res(
            "Service order sent for correction",
            {"orderId": order.id, "workflowStatus": order.workflow_status},
            200,
        )

    except SQLAlchemyError as e:
        db.session.rollback()
        return res(str(e), [], 500)
    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ═══════════════════════════════════════════════════════════════════
# REJECT
# ═══════════════════════════════════════════════════════════════════

def reject_pw_order(order_id: int, rejected_by=None, comments=None):

    try:

        order = ProjectWorkOrderMaster.query.get(order_id)
        if not order:
            return res("Service order not found", [], 404)

        if not order.workflow_status.startswith("Pending"):
            return res("Service order not pending", [], 400)

        if not comments:
            return res("Comments required", [], 400)

        allowed = is_current_approver(
            order.project_code, get_approval_module("pw_order"), order.current_level, rejected_by
        )
        if not allowed:
            return res("You are not current approver", [], 403)

        order.workflow_status = "Rejected"
        order.locked          = True
        order.rejected_at     = datetime.utcnow()
        order.rejected_by     = rejected_by
        order.status          = "Inactive"
        order.updated_by      = rejected_by
        order.updated_at      = datetime.utcnow()

        create_history(
            project_code = order.project_code,
            module_code  = "pw_order",
            record_id    = order.id,
            level_no     = order.current_level,
            action       = "REJECT",
            action_by    = rejected_by,
            comments     = comments,
        )

        db.session.commit()

        return res(
            "Service order rejected",
            {"orderId": order.id, "workflowStatus": order.workflow_status},
            200,
        )

    except SQLAlchemyError as e:
        db.session.rollback()
        return res(str(e), [], 500)
    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ═══════════════════════════════════════════════════════════════════
# DELETE
# ═══════════════════════════════════════════════════════════════════

def delete_pw_order(order_id: int):

    try:

        order = ProjectWorkOrderMaster.query.get(order_id)
        if not order:
            return res("Service order order not found", [], 404)

        if order.locked:
            return res("Only Draft/Reback Service orders can be deleted", [], 400)

        ProjectWorkOrderItem.query.filter_by(order_id=order.id).delete()

        for row in order.terms_conditions:
            db.session.delete(row)

        db.session.delete(order)
        db.session.commit()

        return res("Service order deleted successfully", [], 200)

    except SQLAlchemyError as e:
        db.session.rollback()
        return res(str(e), [], 500)
    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ═══════════════════════════════════════════════════════════════════
# HISTORY
# ═══════════════════════════════════════════════════════════════════

def get_pw_order_history(order_id: int):

    try:

        order = ProjectWorkOrderMaster.query.get(order_id)
        if not order:
            return res("PW Order not found", [], 404)

        rows = get_history("pw_order", order.id)

        data = [
            {
                "id":        row.id,
                "action":    row.action,
                "level":     row.level_no,
                "comments":  row.comments,
                "actionBy":  row.user.username if row.user else None,
                "createdAt": (
                    row.created_at.strftime("%Y-%m-%d %H:%M:%S")
                    if row.created_at
                    else None
                ),
            }
            for row in rows
        ]

        return res("PW Order history fetched", data, 200)

    except Exception as e:
        return res(str(e), [], 500)
