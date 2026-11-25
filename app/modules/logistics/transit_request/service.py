from app.utils.date_utils import created_ts
from sqlalchemy import func
from sqlalchemy.exc import SQLAlchemyError
from app.extensions import db
from datetime import datetime
from decimal import Decimal
import uuid as _uuid
import json

from app.models.transitRequest import TransitRequest, TransitRequestItem
from app.models.orderMaster import OrderMaster, OrderItem
from app.models.item import Item
from app.models.asset import Asset
from app.models.dcMaster import DcMaster, DcItem
from app.response import res
from app.cloudinary_uploader import upload_file_to_bunny
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
from app.models.user import User
from app.modules.communication import whatsapp_events as wa
from app.utils.date_utils import parse_date

MODULE_CODE = "transit_request"
PURCHASE_ORDER_TYPE = "Purchase_Order"
SITE_TRANSFER_TYPE = "Site_Transfer_Order"


def _fmt_date(d):
    if d is None:
        return None
    return d.strftime("%Y-%m-%d")


def _fmt_datetime(d):
    if d is None:
        return None
    if isinstance(d, datetime):
        return d.strftime("%Y-%m-%d %H:%M")
    return d.strftime("%Y-%m-%d")


def _ensure_tr_uuid(tr):
    """Backfill tr_uuid for legacy rows so Print works."""
    if not tr.tr_uuid:
        tr.tr_uuid = str(_uuid.uuid4())
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
    return tr.tr_uuid


def generate_tr_no():
    last = (
        db.session.query(TransitRequest.tr_no)
        .order_by(TransitRequest.id.desc())
        .first()
    )
    if last:
        try:
            last_serial = int(last[0].replace("TR", ""))
        except Exception:
            last_serial = 440000
    else:
        last_serial = 440000
    return f"TR{last_serial + 1}"


def _dispatched_qty_for_tr_item(tr_id, order_item_id):
    """Sum DC issue_qty for DCs linked to this TR for the given order_item."""
    result = (
        db.session.query(
            func.coalesce(func.sum(DcItem.issue_qty), 0)
        )
        .join(DcMaster, DcMaster.id == DcItem.dc_id)
        .filter(
            DcMaster.transit_request_id == tr_id,
            DcItem.order_item_id == order_item_id,
            DcMaster.workflow_status.notin_(("Rejected", "Cancelled")),
        )
        .scalar()
    )
    return Decimal(str(result or 0))


# ══════════════════════════════════════════════════════════════════
# GET APPROVED ORDERS FOR TR SELECTION
# ══════════════════════════════════════════════════════════════════

def get_approved_orders_for_tr(project_code, order_type):
    try:
        if not project_code:
            return res("projectCode required", [], 400)

        query = OrderMaster.query.filter(
            OrderMaster.project_code == project_code,
            OrderMaster.workflow_status == "Approved",
            OrderMaster.status == "Active",
        )

        if order_type == SITE_TRANSFER_TYPE:
            query = query.filter(
                OrderMaster.category_code == SITE_TRANSFER_TYPE
            )
        elif order_type == PURCHASE_ORDER_TYPE:
            query = query.filter(
                OrderMaster.category_code != SITE_TRANSFER_TYPE
            )

        rows = query.order_by(OrderMaster.id.desc()).all()

        result = []
        for row in rows:
            vendor_name = row.vendor.ledger_name if row.vendor else None
            result.append({
                "id":           row.id,
                "orderNo":      row.order_no,
                "orderDate":    _fmt_date(row.order_date),
                "categoryCode": row.category_code,
                "vendorId":     row.vendor_id,
                "vendorName":   vendor_name,
            })

        return res("Orders fetched", result, 200)

    except Exception as e:
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# GET ORDER ITEMS FOR TR
# ══════════════════════════════════════════════════════════════════

def get_order_items_for_tr(order_id):
    try:
        order = OrderMaster.query.get(order_id)
        if not order:
            return res("Order not found", [], 404)
        if order.workflow_status != "Approved":
            return res("Order is not approved", [], 400)

        items = []
        for oi in order.items:
            if oi.is_asset:
                name = oi.asset.asset_name if oi.asset else None
                unit = oi.asset.unit.unit_name if oi.asset and oi.asset.unit else None
            else:
                name = oi.item.item_name if oi.item else None
                unit = oi.item.unit.unit_name if oi.item and oi.item.unit else None

            items.append({
                "orderItemId": oi.id,
                "itemCode":    oi.asset_code if oi.is_asset else oi.item_code,
                "itemName":    name,
                "itemUnit":    unit,
                "isAsset":     oi.is_asset,
                "orderQty":    float(oi.qty or 0),
                "requestedQty": float(oi.qty or 0),
                "remarks":     "",
            })

        return res("Items fetched", {"items": items, "orderId": order.id, "orderNo": order.order_no}, 200)

    except Exception as e:
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# CREATE TRANSIT REQUEST
# ══════════════════════════════════════════════════════════════════

def create_tr(data, user_id, files=None):
    try:
        allowed = is_creator(data.get("projectCode"), MODULE_CODE, user_id)
        if not allowed:
            return res("You are not authorized to create Transit Request", [], 403)

        items = data.get("items", [])
        if isinstance(items, str):
            items = json.loads(items)
        if not items:
            return res("At least one item is required", [], 400)

        tr_no = generate_tr_no()
        new_uuid = str(_uuid.uuid4())

        attached_doc = None
        if files:
            doc_file = files.get("attachedDoc")
            if doc_file:
                attached_doc = upload_file_to_bunny(
                    file=doc_file,
                    mainFolder="transit_request",
                    subFolder=tr_no,
                    fileName="attached_doc"
                )

        est_freight = data.get("estimatedFreight")
        tr = TransitRequest(
            tr_no=tr_no,
            tr_uuid=new_uuid,
            request_date=data.get("requestDate"),
            project_code=data.get("projectCode"),
            order_type=data.get("orderType"),
            order_id=data.get("orderId") or None,
            transfer_type=data.get("transferType"),
            mode_of_transport=data.get("modeOfTransport"),
            preferred_carrier_id=(int(data["preferredCarrierId"]) if data.get("preferredCarrierId") else None),
            estimated_freight=(Decimal(str(est_freight)) if est_freight not in (None, "", "null") else None),
            source_location=data.get("sourceLocation"),
            destination_location=data.get("destinationLocation"),
            priority=data.get("priority", "Medium"),
            required_delivery_date=data.get("requiredDeliveryDate") or None,
            purpose=data.get("purpose"),
            remarks=data.get("remarks"),
            attached_doc=attached_doc,
            workflow_status="Draft",
            fulfillment_status="Open",
            current_level=0,
            locked=False,
            created_by=user_id,
        )

        db.session.add(tr)
        db.session.flush()

        for row in items:
            order_item_id = row.get("orderItemId")
            requested_qty = Decimal(str(row.get("requestedQty") or 0))
            if requested_qty <= 0:
                db.session.rollback()
                return res(f"requestedQty must be > 0 for item {row.get('itemCode')}", [], 400)

            # Determine item/asset codes from order_item if linked
            item_code = None
            asset_code = None
            is_asset = False

            if order_item_id:
                oi = OrderItem.query.get(order_item_id)
                if oi:
                    is_asset = oi.is_asset
                    item_code = oi.item_code
                    asset_code = oi.asset_code
            else:
                item_code = row.get("itemCode")
                is_asset = bool(row.get("isAsset"))
                asset_code = row.get("assetCode")

            tr_item = TransitRequestItem(
                tr_id=tr.id,
                order_item_id=order_item_id,
                item_code=item_code,
                is_asset=is_asset,
                asset_code=asset_code,
                requested_qty=requested_qty,
                remarks=row.get("remarks"),
            )
            db.session.add(tr_item)

        db.session.commit()
        return res("Transit Request created", {"trId": tr.id, "trNo": tr.tr_no, "uuid": tr.tr_uuid}, 201)

    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# UPDATE TRANSIT REQUEST
# ══════════════════════════════════════════════════════════════════

def update_tr(tr_id, data, user_id, files=None):
    try:
        tr = TransitRequest.query.get(tr_id)
        if not tr:
            return res("Transit Request not found", [], 404)
        if tr.workflow_status not in ("Draft", "Correction"):
            return res("Cannot edit a submitted/approved Transit Request", [], 400)
        if tr.locked:
            return res("Transit Request is locked", [], 400)

        if files:
            doc_file = files.get("attachedDoc")
            if doc_file:
                tr.attached_doc = upload_file_to_bunny(
                    file=doc_file, mainFolder="transit_request",
                    subFolder=tr.tr_no, fileName="attached_doc"
                )
        # Allow the form to explicitly clear an existing attachment
        if str(data.get("clearAttachedDoc", "")).lower() == "true":
            tr.attached_doc = None

        tr.request_date = data.get("requestDate") or tr.request_date
        tr.order_type = data.get("orderType") or tr.order_type
        tr.order_id = data.get("orderId") or tr.order_id
        if "transferType" in data:     tr.transfer_type = data.get("transferType") or tr.transfer_type
        if "modeOfTransport" in data:  tr.mode_of_transport = data.get("modeOfTransport") or tr.mode_of_transport
        if "preferredCarrierId" in data:
            pc = data.get("preferredCarrierId")
            tr.preferred_carrier_id = int(pc) if pc else None
        if "estimatedFreight" in data:
            ef = data.get("estimatedFreight")
            tr.estimated_freight = Decimal(str(ef)) if ef not in (None, "", "null") else None
        tr.source_location = data.get("sourceLocation", tr.source_location)
        tr.destination_location = data.get("destinationLocation", tr.destination_location)
        tr.priority = data.get("priority", tr.priority)
        tr.required_delivery_date = data.get("requiredDeliveryDate") or tr.required_delivery_date
        tr.purpose = data.get("purpose", tr.purpose)
        tr.remarks = data.get("remarks", tr.remarks)
        tr.updated_by = user_id
        tr.updated_at = datetime.utcnow()

        items = data.get("items", [])
        if isinstance(items, str):
            items = json.loads(items)

        if items:
            for old_item in tr.items:
                db.session.delete(old_item)
            db.session.flush()

            for row in items:
                requested_qty = Decimal(str(row.get("requestedQty") or 0))
                if requested_qty <= 0:
                    db.session.rollback()
                    return res(f"requestedQty must be > 0", [], 400)

                order_item_id = row.get("orderItemId")
                item_code = None
                asset_code = None
                is_asset = False

                if order_item_id:
                    oi = OrderItem.query.get(order_item_id)
                    if oi:
                        is_asset = oi.is_asset
                        item_code = oi.item_code
                        asset_code = oi.asset_code
                else:
                    item_code = row.get("itemCode")
                    is_asset = bool(row.get("isAsset"))

                tr_item = TransitRequestItem(
                    tr_id=tr.id,
                    order_item_id=order_item_id,
                    item_code=item_code,
                    is_asset=is_asset,
                    asset_code=asset_code,
                    requested_qty=requested_qty,
                    remarks=row.get("remarks"),
                )
                db.session.add(tr_item)

        db.session.commit()
        return res("Transit Request updated", {"trId": tr.id}, 200)

    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# LIST
# ══════════════════════════════════════════════════════════════════

def get_tr_list(data):
    try:
        project_code = data.get("projectCode")
        query = TransitRequest.query
        if project_code:
            query = query.filter(TransitRequest.project_code == project_code)
        if data.get("workflowStatus"):
            query = query.filter(TransitRequest.workflow_status == data["workflowStatus"])
        if data.get("priority"):
            query = query.filter(TransitRequest.priority == data["priority"])
        if data.get("orderType"):
            query = query.filter(TransitRequest.order_type == data["orderType"])
        if data.get("search"):
            s = f"%{data['search']}%"
            query = query.filter(
                (TransitRequest.tr_no.ilike(s)) | (TransitRequest.purpose.ilike(s))
            )

        rows = query.order_by(TransitRequest.id.desc()).all()

        result = []
        for row in rows:
            order_no = row.order.order_no if row.order else None
            creator_name = None
            if row.creator:
                creator_name = row.creator.username

            total_requested = sum(
                float(i.requested_qty or 0) for i in row.items
            )
            total_dispatched = sum(
                _dispatched_qty_for_tr_item(row.id, i.order_item_id)
                for i in row.items if i.order_item_id
            )

            result.append({
                "id":                  row.id,
                "trNo":                row.tr_no,
                "requestDate":         _fmt_date(row.request_date),
                "projectCode":         row.project_code,
                "orderType":           row.order_type,
                "orderNo":             order_no,
                "sourceLocation":      row.source_location,
                "destinationLocation": row.destination_location,
                "priority":            row.priority,
                "requiredDeliveryDate":_fmt_date(row.required_delivery_date),
                "purpose":             row.purpose,
                "noOfItems":           len(row.items),
                "totalRequestedQty":   float(total_requested),
                "totalDispatchedQty":  float(total_dispatched),
                "remainingQty":        float(total_requested - total_dispatched),
                "workflowStatus":      row.workflow_status,
                "transitStatus":       row.transit_status or "Pending_Dispatch",
                "createdBy":           creator_name,
                "createdAt":           _fmt_datetime(row.created_at),
                "createdTs":           created_ts(row.created_at),
            })

        return res("Transit Requests fetched", result, 200)

    except Exception as e:
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# DETAIL
# ══════════════════════════════════════════════════════════════════

def get_tr_detail(tr_id):
    try:
        tr = TransitRequest.query.get(tr_id)
        if not tr:
            return res("Transit Request not found", [], 404)

        items = []
        for i in tr.items:
            if i.is_asset:
                name = i.asset.asset_name if i.asset else None
                unit = i.asset.unit.unit_name if i.asset and i.asset.unit else None
            else:
                name = i.item.item_name if i.item else None
                unit = i.item.unit.unit_name if i.item and i.item.unit else None

            dispatched = (
                _dispatched_qty_for_tr_item(tr.id, i.order_item_id)
                if i.order_item_id else Decimal("0")
            )
            order_qty = float(i.order_item.qty or 0) if i.order_item else None

            items.append({
                "id":           i.id,
                "orderItemId":  i.order_item_id,
                "itemCode":     i.asset_code if i.is_asset else i.item_code,
                "itemName":     name,
                "itemUnit":     unit,
                "isAsset":      i.is_asset,
                "orderQty":     order_qty,
                "requestedQty": float(i.requested_qty or 0),
                "dispatchedQty":float(dispatched),
                "remainingQty": float(Decimal(str(i.requested_qty or 0)) - dispatched),
                "remarks":      i.remarks,
            })

        linked_dcs = []
        for dc in tr.delivery_challans:
            linked_dcs.append({
                "dcId":          dc.id,
                "dcNo":          dc.dc_no,
                "challanDate":   _fmt_date(dc.challan_date),
                "workflowStatus": dc.workflow_status,
                "noOfItems":     len(dc.items),
            })

        def _user_name(user):
            if not user:
                return None
            return user.username

        # Fulfillment status — computed from linked DCs:
        #   no items with order_item_id → Open
        #   all items fully dispatched → Fulfilled
        #   any dispatched but not all → Partial
        #   else → Open
        total_req = Decimal("0")
        total_disp = Decimal("0")
        for i in items:
            total_req += Decimal(str(i.get("requestedQty") or 0))
            total_disp += Decimal(str(i.get("dispatchedQty") or 0))
        if total_req == 0:
            fulfillment = tr.fulfillment_status or "Open"
        elif total_disp >= total_req:
            fulfillment = "Fulfilled"
        elif total_disp > 0:
            fulfillment = "Partial"
        else:
            fulfillment = "Open"

        tr_uuid_val = _ensure_tr_uuid(tr)
        data = {
            "id":                  tr.id,
            "trNo":                tr.tr_no,
            "trUuid":              tr_uuid_val,
            "uuid":                tr_uuid_val,
            "requestDate":         _fmt_date(tr.request_date),
            "projectCode":         tr.project_code,
            "orderType":           tr.order_type,
            "orderId":             tr.order_id,
            "orderNo":             tr.order.order_no if tr.order else None,
            "transferType":        tr.transfer_type,
            "modeOfTransport":     tr.mode_of_transport,
            "preferredCarrierId":  tr.preferred_carrier_id,
            "preferredCarrierName":(tr.preferred_carrier.ledger_name if tr.preferred_carrier else None),
            "estimatedFreight":    float(tr.estimated_freight) if tr.estimated_freight is not None else None,
            "sourceLocation":      tr.source_location,
            "destinationLocation": tr.destination_location,
            "priority":            tr.priority,
            "requiredDeliveryDate":_fmt_date(tr.required_delivery_date),
            "purpose":             tr.purpose,
            "remarks":             tr.remarks,
            "attachedDoc":         tr.attached_doc,
            "workflowStatus":      tr.workflow_status,
            "transitStatus":       tr.transit_status or "Pending_Dispatch",
            "fulfillmentStatus":   fulfillment,
            "currentLevel":        tr.current_level,
            "locked":              tr.locked,
            "items":               items,
            "linkedDcs":           linked_dcs,
            "createdBy":           _user_name(tr.creator),
            "createdAt":           _fmt_datetime(tr.created_at),
            "submittedBy":         _user_name(tr.submitter),
            "submittedAt":         _fmt_datetime(tr.submitted_at),
            "approvedBy":          _user_name(tr.approver),
            "finalApprovedAt":     _fmt_datetime(tr.final_approved_at),
            "rejectedBy":          _user_name(tr.rejector),
            "rejectedAt":          _fmt_datetime(tr.rejected_at),
        }

        return res("Transit Request fetched", data, 200)

    except Exception as e:
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# WORKFLOW: SUBMIT
# ══════════════════════════════════════════════════════════════════

def submit_tr(tr_id, submitted_by):
    try:
        tr = TransitRequest.query.get(tr_id)
        if not tr:
            return res("Transit Request not found", [], 404)
        if tr.workflow_status not in ("Draft", "Correction"):
            return res("Only Draft or Correction TRs can be submitted", [], 400)
        if not tr.items:
            return res("No items to submit", [], 400)

        first = get_first_approver(tr.project_code, MODULE_CODE)
        tr.submitted_by = submitted_by
        tr.submitted_at = datetime.utcnow()

        if not first:
            # No approval path → auto-approve
            tr.workflow_status = "Approved"
            tr.approved_by = submitted_by
            tr.final_approved_at = datetime.utcnow()
            tr.current_level = 0
            tr.locked = True
        else:
            tr.workflow_status = f"Pending_L{first.level_no}"
            tr.current_level = first.level_no
            tr.locked = True

        create_history(
            module_code=MODULE_CODE,
            record_id=tr.id,
            action="Submitted",
            done_by=submitted_by,
        )

        db.session.commit()
        wa.on_submit(tr.id, MODULE_CODE)
        return res("Transit Request submitted", {}, 200)

    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# WORKFLOW: APPROVE
# ══════════════════════════════════════════════════════════════════

def approve_tr(tr_id, approved_by, comments=None):
    try:
        tr = TransitRequest.query.get(tr_id)
        if not tr:
            return res("Transit Request not found", [], 404)
        if not (tr.workflow_status or "").startswith("Pending"):
            return res("Only Pending TRs can be approved", [], 400)

        if not is_current_approver(tr.project_code, MODULE_CODE, tr.current_level, approved_by):
            return res("You are not the current approver", [], 403)

        next_approver = get_next_approver(tr.project_code, MODULE_CODE, tr.current_level)

        create_history(
            module_code=MODULE_CODE,
            record_id=tr.id,
            action="Approved",
            done_by=approved_by,
            comments=comments,
            level=tr.current_level,
        )

        if next_approver:
            tr.current_level = next_approver.level_no
            tr.workflow_status = f"Pending_L{next_approver.level_no}"
            db.session.commit()
            wa.on_approve(tr.id, MODULE_CODE)
        else:
            tr.workflow_status = "Approved"
            tr.approved_by = approved_by
            tr.final_approved_at = datetime.utcnow()
            tr.locked = True
            db.session.commit()
            wa.on_final_approve(tr.id, MODULE_CODE)

        return res("Transit Request approved", {}, 200)

    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# WORKFLOW: REBACK
# ══════════════════════════════════════════════════════════════════

def reback_tr(tr_id, reback_by, comments=None):
    try:
        tr = TransitRequest.query.get(tr_id)
        if not tr:
            return res("Transit Request not found", [], 404)
        if not (tr.workflow_status or "").startswith("Pending"):
            return res("Only Pending TRs can be sent for correction", [], 400)

        if not is_current_approver(tr.project_code, MODULE_CODE, tr.current_level, reback_by):
            return res("You are not the current approver", [], 403)

        tr.workflow_status = "Correction"
        tr.current_level = 0
        tr.locked = False
        tr.correction_sent_at = datetime.utcnow()

        create_history(
            module_code=MODULE_CODE,
            record_id=tr.id,
            action="Reback",
            done_by=reback_by,
            comments=comments,
        )

        db.session.commit()
        wa.on_reback(tr.id, MODULE_CODE)
        return res("Transit Request sent for correction", {}, 200)

    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# WORKFLOW: REJECT
# ══════════════════════════════════════════════════════════════════

def reject_tr(tr_id, rejected_by, comments=None):
    try:
        tr = TransitRequest.query.get(tr_id)
        if not tr:
            return res("Transit Request not found", [], 404)
        if not (tr.workflow_status or "").startswith("Pending"):
            return res("Only Pending TRs can be rejected", [], 400)

        if not is_current_approver(tr.project_code, MODULE_CODE, tr.current_level, rejected_by):
            return res("You are not the current approver", [], 403)

        tr.workflow_status = "Rejected"
        tr.rejected_by = rejected_by
        tr.rejected_at = datetime.utcnow()
        tr.locked = False

        create_history(
            module_code=MODULE_CODE,
            record_id=tr.id,
            action="Rejected",
            done_by=rejected_by,
            comments=comments,
        )

        db.session.commit()
        wa.on_reject(tr.id, MODULE_CODE)
        return res("Transit Request rejected", {}, 200)

    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# HISTORY / APPROVAL STATUS
# ══════════════════════════════════════════════════════════════════

def get_tr_history(tr_id):
    try:
        tr = TransitRequest.query.get(tr_id)
        if not tr:
            return res("Transit Request not found", [], 404)

        history = get_history(MODULE_CODE, tr_id)
        steps = get_approval_steps(tr.project_code, MODULE_CODE)

        return res("History fetched", {"history": history, "steps": steps}, 200)

    except Exception as e:
        return res(str(e), [], 500)


def get_tr_my_approval_status(tr_id, user_id):
    try:
        tr = TransitRequest.query.get(tr_id)
        if not tr:
            return res("Transit Request not found", [], 404)

        status = get_my_approval_status(
            project_code=tr.project_code,
            module_code=MODULE_CODE,
            record=tr,
            user_id=user_id,
        )
        return res("Approval status fetched", status, 200)

    except Exception as e:
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# DELETE (Draft only)
# ══════════════════════════════════════════════════════════════════

def delete_tr(tr_id):
    try:
        tr = TransitRequest.query.get(tr_id)
        if not tr:
            return res("Transit Request not found", [], 404)
        if tr.workflow_status not in ("Draft",):
            return res("Only Draft Transit Requests can be deleted", [], 400)
        if tr.locked:
            return res("Transit Request is locked", [], 400)

        db.session.delete(tr)
        db.session.commit()
        return res("Transit Request deleted", {}, 200)

    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# UPDATE TRANSIT STATUS (operational — post-approval)
# ══════════════════════════════════════════════════════════════════

VALID_TRANSIT_STATUSES = ("Pending_Dispatch", "In_Transit", "Partially_Delivered", "Delivered")

def update_transit_status(tr_id, new_status, user_id):
    try:
        if new_status not in VALID_TRANSIT_STATUSES:
            return res(f"Invalid transit status. Allowed: {', '.join(VALID_TRANSIT_STATUSES)}", [], 400)

        tr = TransitRequest.query.get(tr_id)
        if not tr:
            return res("Transit Request not found", [], 404)
        if tr.workflow_status != "Approved":
            return res("Transit status can only be updated for Approved Transit Requests", [], 400)

        tr.transit_status = new_status
        tr.updated_by = user_id
        tr.updated_at = datetime.utcnow()

        create_history(
            module_code=MODULE_CODE,
            record_id=tr.id,
            action=f"Transit Status: {new_status}",
            done_by=user_id,
        )

        db.session.commit()
        return res(f"Transit status updated to {new_status}", {"transitStatus": new_status}, 200)

    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# GET APPROVED TRs (for DC creation — link picker)
# ══════════════════════════════════════════════════════════════════

def get_approved_trs_for_dc(project_code, order_id=None):
    """Return Approved TRs that have remaining (undispatched) items."""
    try:
        query = TransitRequest.query.filter(
            TransitRequest.project_code == project_code,
            TransitRequest.workflow_status == "Approved",
        )
        if order_id:
            query = query.filter(TransitRequest.order_id == order_id)

        rows = query.order_by(TransitRequest.id.desc()).all()
        result = []
        for tr in rows:
            remaining = sum(
                float(
                    Decimal(str(i.requested_qty or 0))
                    - _dispatched_qty_for_tr_item(tr.id, i.order_item_id)
                )
                for i in tr.items if i.order_item_id
            )
            if remaining > 0:
                result.append({
                    "id":     tr.id,
                    "trNo":   tr.tr_no,
                    "purpose": tr.purpose,
                    "remainingQty": remaining,
                })

        return res("Approved TRs fetched", result, 200)

    except Exception as e:
        return res(str(e), [], 500)
