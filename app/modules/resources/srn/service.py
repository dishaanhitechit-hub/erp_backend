from sqlalchemy import func
from sqlalchemy.exc import SQLAlchemyError
from app.extensions import db
from datetime import datetime
import json

from app.models.ORDER_projectwork import ProjectWorkOrderMaster, ProjectWorkOrderItem
from app.models.srnMaster import SrnMaster, SrnItem
from app.response import res
from app.cloudinary_uploader import upload_file_to_bunny
from app.alias_helper import get_approval_module
from app.modules.work_flow import (
    is_creator,
    is_current_approver,
    get_first_approver,
    get_next_approver,
    create_history,
    get_history,
)

# workflow alias — set in workflow_module_alias table with module_code="srn"
_MODULE = "srn"


# ══════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════

def _fmt_date(d):
    if d is None:
        return None
    if isinstance(d, datetime):
        return d.strftime("%Y-%m-%d %H:%M")
    return d.strftime("%Y-%m-%d")


def _pre_received_qty(pw_order_item_id):
    """Sum of current_received_qty in non-rejected SRNs for this pw_order_item."""
    result = (
        db.session.query(
            func.coalesce(func.sum(SrnItem.current_received_qty), 0)
        )
        .join(SrnMaster, SrnMaster.id == SrnItem.srn_id)
        .filter(
            SrnItem.pw_order_item_id == pw_order_item_id,
            SrnMaster.workflow_status != "Rejected"
        )
        .scalar()
    )
    return float(result)


def generate_srnl_no(line_no):
    return f"SRNL{line_no:03d}"


def generate_srn_no():
    last = (
        db.session.query(SrnMaster.srn_no)
        .order_by(SrnMaster.id.desc())
        .first()
    )
    if last:
        try:
            last_serial = int(last[0])
        except Exception:
            last_serial = 730000
    else:
        last_serial = 730000
    return str(last_serial + 1)


# ══════════════════════════════════════════════════════════════════
# 1. GET PW ORDERS BY VENDOR  (filter panel)
# ══════════════════════════════════════════════════════════════════

def get_pw_orders_by_vendor(data):
    """
    Filter approved PW orders for a vendor + project.
    Filters: categoryCode, subCategoryCode (JSON contains), costHead.
    Same fallback logic — if categoryCode provided but yields nothing,
    falls back to subCategoryCode + costHead.
    """
    try:

        vendor_id    = data.get("vendorId")
        project_code = data.get("projectCode")

        if not vendor_id:
            return res("vendorId required", [], 400)
        if not project_code:
            return res("projectCode required", [], 400)

        base_query = ProjectWorkOrderMaster.query.filter(
            ProjectWorkOrderMaster.vendor_id    == vendor_id,
            ProjectWorkOrderMaster.project_code == project_code,
            ProjectWorkOrderMaster.workflow_status == "Approved"
        )

        category_code    = data.get("receivedCategory")
        sub_category_code = data.get("itemCategory")
        cost_head        = data.get("costHead")

        filtered_query = base_query
        if category_code:
            filtered_query = filtered_query.filter(
                ProjectWorkOrderMaster.category_code == category_code
            )
        if sub_category_code:
            filtered_query = filtered_query.filter(
                ProjectWorkOrderMaster.sub_codes.ilike(f'%"{sub_category_code}"%')
            )
        if cost_head:
            filtered_query = filtered_query.filter(
                ProjectWorkOrderMaster.cost_head == cost_head
            )

        rows = filtered_query.order_by(ProjectWorkOrderMaster.id.desc()).all()

        # fallback: if categoryCode provided but nothing matched,
        # retry with subCategoryCode + costHead only
        if not rows and category_code:
            fallback_query = base_query
            if sub_category_code:
                fallback_query = fallback_query.filter(
                    ProjectWorkOrderMaster.sub_codes.ilike(f'%"{sub_category_code}"%')
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
# 2. GET PW ORDER ITEMS FOR SRN GRID
# ══════════════════════════════════════════════════════════════════

def get_pw_order_items_for_srn(order_id):
    """
    Fetches pw_order items for a given order_id.
    Dynamically computes preReceivedQty and balanceQty per item.
    No indent info — pw_order has no indent linkage.
    """
    try:

        order = ProjectWorkOrderMaster.query.get(order_id)

        if not order:
            return res("PW Order not found", [], 404)

        if order.workflow_status != "Approved":
            return res("PW Order is not approved", [], 400)

        items = []
        for oi in order.items:

            pre_qty   = _pre_received_qty(oi.id)
            order_qty = float(oi.qty or 0)
            balance   = order_qty - pre_qty

            items.append({
                "pwOrderItemId":      oi.id,
                "itemCode":           oi.item_code,
                "itemName":           oi.item.item_name if oi.item else None,
                "itemUnit":           (
                    oi.item.unit.unit_name
                    if oi.item and oi.item.unit else None
                ),
                "note":               oi.custom_note,
                "orderQty":           order_qty,
                "preReceivedQty":     pre_qty,
                "balanceQty":         balance,
                "currentReceivedQty": 0,
                "useLocation":        None,
                "storeLocation":      None,
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
            "partyName":        order.vendor.ledger_name         if order.vendor else None,
            "partyAddress":     order.vendor.registered_address  if order.vendor else None,
            "partyGstn":        order.vendor.gstin               if order.vendor else None,
            "projectCode":      order.project_code,
            "billingAddress":   order.billing_address,
            "shippingAddress":  order.shipping_address,
            "categoryCode":     order.category_code,
            "subCategoryCodes": sub_codes_list,
            "costHead":         order.cost_head,
            "items":            items,
        }

        return res("PW Order items fetched", data, 200)

    except Exception as e:
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 3. CREATE SRN
# ══════════════════════════════════════════════════════════════════

def create_srn(data, user_id, files=None):
    try:

        allowed = is_creator(
            data.get("projectCode"),
            get_approval_module(_MODULE),
            user_id
        )
        if not allowed:
            return res("You are not SRN creator", [], 403)

        items = data.get("items", [])
        if isinstance(items, str):
            items = json.loads(items)

        if not items:
            return res("No items provided", [], 400)

        srn_no = generate_srn_no()

        attached_doc = None
        if files:
            doc_file = files.get("attachedDoc")
            if doc_file:
                attached_doc = upload_file_to_bunny(
                    file=doc_file,
                    mainFolder="srn",
                    subFolder=srn_no,
                    fileName="attached_doc"
                )

        srn = SrnMaster(
            srn_no                = srn_no,
            srn_date              = data.get("srnDate"),
            project_code          = data.get("projectCode"),
            received_category     = data.get("receivedCategory"),
            item_category         = data.get("itemCategory"),
            cost_head             = data.get("costHead"),
            order_id              = data.get("orderId"),
            vendor_id             = data.get("vendorId"),
            billing_address       = data.get("billingAddress"),
            shipping_address      = data.get("shippingAddress"),
            challan_no            = data.get("challanNo"),
            party_bill_no         = data.get("partyBillNo"),
            party_bill_date       = data.get("partyBillDate"),
            deliver_vehicle_no    = data.get("deliverVehicleNo"),
            delivered_concern     = data.get("deliveredConcern"),
            unloading_datetime    = data.get("unloadingDatetime"),
            physically_verified_by = data.get("physicallyVerifiedBy"),
            attached_doc          = attached_doc,
            workflow_status       = "Draft",
            current_level         = 0,
            locked                = False,
            created_by            = user_id,
        )

        db.session.add(srn)
        db.session.flush()

        for line_no, row in enumerate(items, start=1):

            pw_order_item_id     = row.get("pwOrderItemId")
            current_received_qty = float(row.get("currentReceivedQty", 0))

            if current_received_qty <= 0:
                db.session.rollback()
                return res(
                    f"Invalid currentReceivedQty for pwOrderItemId {pw_order_item_id}",
                    [], 400
                )

            pw_order_item = ProjectWorkOrderItem.query.get(pw_order_item_id)
            if not pw_order_item:
                db.session.rollback()
                return res(
                    f"PW Order item {pw_order_item_id} not found",
                    [], 404
                )

            pre_qty = _pre_received_qty(pw_order_item_id)
            balance = float(pw_order_item.qty or 0) - pre_qty

            if current_received_qty > balance:
                db.session.rollback()
                return res(
                    f"Only {balance} qty remaining for item {pw_order_item.item_code}",
                    [], 400
                )

            db.session.add(SrnItem(
                srn_id               = srn.id,
                pw_order_item_id     = pw_order_item_id,
                srnl                 = generate_srnl_no(line_no),
                current_received_qty = current_received_qty,
                use_location         = row.get("useLocation"),
                store_location       = row.get("storeLocation"),
            ))

        db.session.commit()

        return res(
            "SRN created",
            {"srnId": srn.id, "srnNo": srn.srn_no},
            201
        )

    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 4. SRN LIST
# ══════════════════════════════════════════════════════════════════

def get_srn_list(data):
    try:

        if not data.get("projectCode"):
            return res("projectCode required", [], 400)

        query = SrnMaster.query.filter(
            SrnMaster.project_code == data.get("projectCode")
        )

        if data.get("vendorId"):
            query = query.filter(SrnMaster.vendor_id == data.get("vendorId"))

        if data.get("orderId"):
            query = query.filter(SrnMaster.order_id == data.get("orderId"))

        if data.get("workflowStatus"):
            query = query.filter(
                SrnMaster.workflow_status == data.get("workflowStatus")
            )

        if data.get("search"):
            query = query.filter(
                SrnMaster.srn_no.ilike(f"%{data.get('search')}%")
            )

        rows = query.order_by(SrnMaster.id.desc()).all()

        result = []
        for row in rows:
            result.append({
                "id":               row.id,
                "srnNo":            row.srn_no,
                "srnDate":          _fmt_date(row.srn_date),
                "projectCode":      row.project_code,
                "orderNo":          row.order.order_no if row.order else None,
                "partyName":        row.vendor.ledger_name if row.vendor else None,
                "receivedCategory": row.received_category,
                "itemCategory":     row.item_category,
                "costHead":         row.cost_head,
                "workflowStatus":   row.workflow_status,
            })

        return res("SRN list fetched", result, 200)

    except Exception as e:
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 5. SRN DETAILS
# ══════════════════════════════════════════════════════════════════

def get_srn_details(srn_id):
    try:

        srn = SrnMaster.query.get(srn_id)

        if not srn:
            return res("SRN not found", [], 404)

        items = []
        for si in srn.items:

            oi      = si.pw_order_item
            pre_qty = _pre_received_qty(si.pw_order_item_id)

            items.append({
                "id":                  si.id,
                "pwOrderItemId":       si.pw_order_item_id,
                "srnl":                si.srnl,
                "itemCode":            oi.item_code if oi else None,
                "itemName":            oi.item.item_name if oi and oi.item else None,
                "itemUnit":            (
                    oi.item.unit.unit_name
                    if oi and oi.item and oi.item.unit else None
                ),
                "note":                oi.custom_note if oi else None,
                "orderQty":            float(oi.qty or 0) if oi else 0,
                "preReceivedQty":      pre_qty,
                "balanceQty":          float(oi.qty or 0) - pre_qty if oi else 0,
                "currentReceivedQty":  float(si.current_received_qty or 0),
                "useLocation":         si.use_location,
                "storeLocation":       si.store_location,
            })

        data = {
            "id":                    srn.id,
            "srnNo":                 srn.srn_no,
            "srnDate":               _fmt_date(srn.srn_date),
            "projectCode":           srn.project_code,
            "receivedCategory":      srn.received_category,
            "itemCategory":          srn.item_category,
            "costHead":              srn.cost_head,
            "orderId":               srn.order_id,
            "orderNo":               srn.order.order_no   if srn.order else None,
            "orderDate":             _fmt_date(srn.order.order_date) if srn.order else None,
            "vendorId":              srn.vendor_id,
            "partyName":             srn.vendor.ledger_name        if srn.vendor else None,
            "partyAddress":          srn.vendor.registered_address if srn.vendor else None,
            "partyGstn":             srn.vendor.gstin               if srn.vendor else None,
            "billingAddress":        srn.billing_address,
            "shippingAddress":       srn.shipping_address,
            "challanNo":             srn.challan_no,
            "partyBillNo":           srn.party_bill_no,
            "partyBillDate":         _fmt_date(srn.party_bill_date),
            "deliverVehicleNo":      srn.deliver_vehicle_no,
            "deliveredConcern":      srn.delivered_concern,
            "unloadingDatetime":     _fmt_date(srn.unloading_datetime),
            "physicallyVerifiedBy":  srn.physically_verified_by,
            "attachedDoc":           srn.attached_doc,
            "workflowStatus":        srn.workflow_status,
            "currentLevel":          srn.current_level,
            "locked":                srn.locked,
            "items":                 items,
        }

        return res("SRN details fetched", data, 200)

    except Exception as e:
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 6. SUBMIT SRN
# ══════════════════════════════════════════════════════════════════

def submit_srn(srn_id, submitted_by=None):
    try:

        srn = SrnMaster.query.get(srn_id)

        if not srn:
            return res("SRN not found", [], 404)

        if srn.workflow_status not in ["Draft", "Reback"]:
            return res("SRN already submitted", [], 400)

        if not srn.items:
            return res("SRN has no items", [], 400)

        if srn.workflow_status == "Reback":
            srn.current_level = 0

        first_level = get_first_approver(
            srn.project_code,
            get_approval_module(_MODULE)
        )

        if not first_level:
            srn.workflow_status   = "Approved"
            srn.locked            = True
            srn.approved_by       = submitted_by
            srn.submitted_at      = datetime.utcnow()
            srn.final_approved_at = datetime.utcnow()
        else:
            srn.workflow_status = f"Pending_L{first_level.level_no}"
            srn.current_level   = first_level.level_no
            srn.locked          = True
            srn.submitted_at    = datetime.utcnow()

        create_history(
            project_code = srn.project_code,
            module_code  = get_approval_module(_MODULE),
            record_id    = srn.id,
            level_no     = srn.current_level,
            action       = "SUBMIT",
            action_by    = submitted_by
        )

        srn.submitted_by = submitted_by
        srn.updated_by   = submitted_by
        srn.updated_at   = datetime.utcnow()

        db.session.commit()

        return res(
            "SRN submitted successfully",
            {
                "srnId":          srn.id,
                "srnNo":          srn.srn_no,
                "workflowStatus": srn.workflow_status
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
# 7. APPROVE SRN
# ══════════════════════════════════════════════════════════════════

def approve_srn(srn_id, approved_by=None, comments=None):
    try:

        srn = SrnMaster.query.get(srn_id)

        if not srn:
            return res("SRN not found", [], 404)

        if not srn.workflow_status.startswith("Pending"):
            return res("SRN not pending", [], 400)

        allowed = is_current_approver(
            srn.project_code,
            get_approval_module(_MODULE),
            srn.current_level,
            approved_by
        )
        if not allowed:
            return res("You are not current approver", [], 403)

        next_level = get_next_approver(
            srn.project_code,
            get_approval_module(_MODULE),
            srn.current_level
        )

        if next_level:
            create_history(
                project_code = srn.project_code,
                module_code  = get_approval_module(_MODULE),
                record_id    = srn.id,
                level_no     = srn.current_level,
                action       = "APPROVE",
                action_by    = approved_by,
                comments     = comments
            )
            srn.current_level   = next_level.level_no
            srn.workflow_status = f"Pending_L{next_level.level_no}"
        else:
            create_history(
                project_code = srn.project_code,
                module_code  = get_approval_module(_MODULE),
                record_id    = srn.id,
                level_no     = srn.current_level,
                action       = "FINAL_APPROVE",
                action_by    = approved_by,
                comments     = comments
            )
            srn.workflow_status   = "Approved"
            srn.locked            = True
            srn.approved_by       = approved_by
            srn.final_approved_at = datetime.utcnow()

        srn.updated_by = approved_by
        srn.updated_at = datetime.utcnow()

        db.session.commit()

        return res(
            "SRN approved successfully",
            {
                "srnId":          srn.id,
                "workflowStatus": srn.workflow_status,
                "currentLevel":   srn.current_level
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
# 8. REBACK SRN
# ══════════════════════════════════════════════════════════════════

def reback_srn(srn_id, reback_by=None, comments=None):
    try:

        srn = SrnMaster.query.get(srn_id)

        if not srn:
            return res("SRN not found", [], 404)

        if not srn.workflow_status.startswith("Pending"):
            return res("SRN not pending", [], 400)

        if not comments:
            return res("Comments required", [], 400)

        allowed = is_current_approver(
            srn.project_code,
            get_approval_module(_MODULE),
            srn.current_level,
            reback_by
        )
        if not allowed:
            return res("You are not current approver", [], 403)

        srn.workflow_status    = "Reback"
        srn.locked             = False
        srn.correction_sent_at = datetime.utcnow()
        srn.updated_by         = reback_by
        srn.updated_at         = datetime.utcnow()

        create_history(
            project_code = srn.project_code,
            module_code  = get_approval_module(_MODULE),
            record_id    = srn.id,
            level_no     = srn.current_level,
            action       = "REBACK",
            action_by    = reback_by,
            comments     = comments
        )

        db.session.commit()

        return res(
            "SRN sent for correction",
            {"srnId": srn.id, "workflowStatus": srn.workflow_status},
            200
        )

    except SQLAlchemyError as e:
        db.session.rollback()
        return res(str(e), [], 500)
    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 9. REJECT SRN
# ══════════════════════════════════════════════════════════════════

def reject_srn(srn_id, rejected_by=None, comments=None):
    try:

        srn = SrnMaster.query.get(srn_id)

        if not srn:
            return res("SRN not found", [], 404)

        if not srn.workflow_status.startswith("Pending"):
            return res("SRN not pending", [], 400)

        if not comments:
            return res("Comments required", [], 400)

        allowed = is_current_approver(
            srn.project_code,
            get_approval_module(_MODULE),
            srn.current_level,
            rejected_by
        )
        if not allowed:
            return res("You are not current approver", [], 403)

        srn.workflow_status = "Rejected"
        srn.locked          = True
        srn.rejected_at     = datetime.utcnow()
        srn.rejected_by     = rejected_by
        srn.status          = "Inactive"
        srn.updated_by      = rejected_by
        srn.updated_at      = datetime.utcnow()

        create_history(
            project_code = srn.project_code,
            module_code  = get_approval_module(_MODULE),
            record_id    = srn.id,
            level_no     = srn.current_level,
            action       = "REJECT",
            action_by    = rejected_by,
            comments     = comments
        )

        db.session.commit()

        return res(
            "SRN rejected",
            {"srnId": srn.id, "workflowStatus": srn.workflow_status},
            200
        )

    except SQLAlchemyError as e:
        db.session.rollback()
        return res(str(e), [], 500)
    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 10. EDIT SRN
# ══════════════════════════════════════════════════════════════════

def edit_srn(srn_id, data, user_id, files=None):
    try:

        srn = SrnMaster.query.get(srn_id)

        if not srn:
            return res("SRN not found", [], 404)

        if srn.locked:
            return res("SRN cannot be edited", [], 400)

        if srn.workflow_status not in ["Draft", "Reback"]:
            return res("Only Draft or Reback SRN can be edited", [], 400)

        allowed = is_creator(
            srn.project_code,
            get_approval_module(_MODULE),
            user_id
        )
        if not allowed:
            return res("You are not SRN creator", [], 403)

        items = data.get("items", [])
        if isinstance(items, str):
            items = json.loads(items)

        if not items:
            return res("Items required", [], 400)

        # update header
        if data.get("srnDate"):
            srn.srn_date = data.get("srnDate")
        if data.get("receivedCategory"):
            srn.received_category = data.get("receivedCategory")
        if data.get("itemCategory"):
            srn.item_category = data.get("itemCategory")
        if data.get("costHead"):
            srn.cost_head = data.get("costHead")
        if data.get("orderId"):
            srn.order_id = data.get("orderId")
        if data.get("vendorId"):
            srn.vendor_id = data.get("vendorId")
        if data.get("billingAddress"):
            srn.billing_address = data.get("billingAddress")
        if data.get("shippingAddress"):
            srn.shipping_address = data.get("shippingAddress")
        if data.get("challanNo"):
            srn.challan_no = data.get("challanNo")
        if data.get("partyBillNo"):
            srn.party_bill_no = data.get("partyBillNo")
        if data.get("partyBillDate"):
            srn.party_bill_date = data.get("partyBillDate")
        if data.get("deliverVehicleNo"):
            srn.deliver_vehicle_no = data.get("deliverVehicleNo")
        if data.get("deliveredConcern"):
            srn.delivered_concern = data.get("deliveredConcern")
        if data.get("unloadingDatetime"):
            srn.unloading_datetime = data.get("unloadingDatetime")
        if data.get("physicallyVerifiedBy"):
            srn.physically_verified_by = data.get("physicallyVerifiedBy")

        if files:
            doc_file = files.get("attachedDoc")
            if doc_file:
                srn.attached_doc = upload_file_to_bunny(
                    file=doc_file,
                    mainFolder="srn",
                    subFolder=srn.srn_no,
                    fileName="attached_doc"
                )

        # wipe old items & rebuild
        SrnItem.query.filter_by(srn_id=srn.id).delete()
        db.session.flush()

        for line_no, row in enumerate(items, start=1):

            pw_order_item_id     = row.get("pwOrderItemId")
            current_received_qty = float(row.get("currentReceivedQty", 0))

            if current_received_qty <= 0:
                db.session.rollback()
                return res(
                    f"Invalid currentReceivedQty for pwOrderItemId {pw_order_item_id}",
                    [], 400
                )

            pw_order_item = ProjectWorkOrderItem.query.get(pw_order_item_id)
            if not pw_order_item:
                db.session.rollback()
                return res(
                    f"PW Order item {pw_order_item_id} not found",
                    [], 404
                )

            pre_qty = _pre_received_qty(pw_order_item_id)
            balance = float(pw_order_item.qty or 0) - pre_qty

            if current_received_qty > balance:
                db.session.rollback()
                return res(
                    f"Only {balance} qty remaining for item {pw_order_item.item_code}",
                    [], 400
                )

            db.session.add(SrnItem(
                srn_id               = srn.id,
                pw_order_item_id     = pw_order_item_id,
                srnl                 = generate_srnl_no(line_no),
                current_received_qty = current_received_qty,
                use_location         = row.get("useLocation"),
                store_location       = row.get("storeLocation"),
            ))

        if srn.workflow_status == "Reback":
            srn.correction_sent_at = None

        srn.updated_by = user_id
        srn.updated_at = datetime.utcnow()

        db.session.commit()

        return res(
            "SRN updated successfully",
            {"srnId": srn.id, "srnNo": srn.srn_no},
            200
        )

    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 11. SRN HISTORY
# ══════════════════════════════════════════════════════════════════

def get_srn_history(srn_id):
    try:

        srn = SrnMaster.query.get(srn_id)

        if not srn:
            return res("SRN not found", [], 404)

        rows = get_history(get_approval_module(_MODULE), srn.id)

        data = []
        for row in rows:
            data.append({
                "id":        row.id,
                "action":    row.action,
                "level":     row.level_no,
                "comments":  row.comments,
                "actionBy":  row.user.username if row.user else None,
                "createdAt": (
                    row.created_at.strftime("%Y%m%d %H:%M:%S")
                    if row.created_at else None
                ),
            })

        return res("SRN history fetched", data, 200)

    except Exception as e:
        return res(str(e), [], 500)
