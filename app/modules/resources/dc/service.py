# app/modules/resources/dc/service.py
# Delivery Challan

from sqlalchemy import func, or_
from sqlalchemy.exc import SQLAlchemyError
from app.extensions import db
from datetime import datetime

from app.models.orderMaster import OrderMaster, OrderItem
from app.models.dcMaster import DcMaster, DcItem
from app.models.project import Project
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

MODULE_CODE = "delivery_challan"

PURCHASE_ORDER_TYPE   = "Purchase_Order"
SITE_TRANSFER_TYPE    = "Site_Transfer_Order"


# ══════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════

def _fmt_date(d):
    if d is None:
        return None
    return d.strftime("%Y-%m-%d")


def generate_dc_no():
    last = (
        db.session.query(DcMaster.dc_no)
        .order_by(DcMaster.id.desc())
        .first()
    )
    if last:
        try:
            last_serial = int(last[0].replace("DC", ""))
        except Exception:
            last_serial = 440000
    else:
        last_serial = 440000
    return f"DC{last_serial + 1}"


def _pre_issued_dc_qty(order_item_id):
    """Total qty already dispatched in non-rejected DCs for this order item."""
    result = (
        db.session.query(
            func.coalesce(func.sum(DcItem.issue_qty), 0)
        )
        .join(DcMaster, DcMaster.id == DcItem.dc_id)
        .filter(
            DcItem.order_item_id == order_item_id,
            DcMaster.workflow_status != "Rejected"
        )
        .scalar()
    )
    return float(result)


# ══════════════════════════════════════════════════════════════════
# 1. GET APPROVED ORDERS  (filter panel)
#    Returns approved orders for a project filtered by order_type
# ══════════════════════════════════════════════════════════════════

def get_approved_orders_for_dc(project_code, order_type):
    try:
        if not project_code or not order_type:
            return res("projectCode and orderType required", [], 400)

        query = (
            OrderMaster.query
            .filter(
                OrderMaster.project_code == project_code,
                OrderMaster.workflow_status == "Approved",
                OrderMaster.status == "Active"
            )
        )

        if order_type == SITE_TRANSFER_TYPE:
            query = query.filter(
                OrderMaster.category_code == SITE_TRANSFER_TYPE
            )
        else:
            # Purchase_Order — any category that is NOT site transfer
            query = query.filter(
                OrderMaster.category_code != SITE_TRANSFER_TYPE
            )

        orders = query.order_by(OrderMaster.id.desc()).all()

        data = [
            {
                "orderId":   o.id,
                "orderNo":   o.order_no,
                "orderDate": _fmt_date(o.order_date),
                "categoryCode": o.category_code,
                "vendorId":  o.vendor_id,
                "vendorName": o.vendor.ledger_name if o.vendor else None,
                "transferProjectSite": o.transfer_project_site,
            }
            for o in orders
        ]

        return res("Orders fetched", data, 200)

    except Exception as e:
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 2. GET ORDER ITEMS  (item selection for DC)
#    Shows order items with available qty to dispatch
# ══════════════════════════════════════════════════════════════════

def get_order_items_for_dc(order_id):
    try:
        order = OrderMaster.query.get(order_id)
        if not order:
            return res("Order not found", [], 404)

        result = []

        for oi in order.items:
            already_dispatched = _pre_issued_dc_qty(oi.id)
            order_qty = float(oi.qty or 0)
            balance_qty = order_qty - already_dispatched

            if balance_qty <= 0:
                continue

            result.append({
                "orderItemId":  oi.id,
                "itemCode":     oi.item_code,
                "itemName":     oi.item.item_name if oi.item else None,
                "itemUnit":     oi.item.unit.unit_name if oi.item and oi.item.unit else None,
                "orderQty":     order_qty,
                "dispatchedQty": already_dispatched,
                "balanceQty":   balance_qty,
                "issueQty":     balance_qty,  # default to full balance
                "stockLocation": oi.location,
            })

        return res("Order items fetched", result, 200)

    except Exception as e:
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 3. GET FROM-SIDE DETAILS  (auto-fill)
#    Based on order_type → vendor or transfer project details
# ══════════════════════════════════════════════════════════════════

def get_from_details(order_id, current_project_code):
    try:
        order = OrderMaster.query.get(order_id)
        if not order:
            return res("Order not found", [], 404)

        current_project = Project.query.filter_by(project_code=current_project_code).first()

        if order.category_code == SITE_TRANSFER_TYPE:
            # From = current project, To = transfer destination
            to_proj = order.transfer_site_project
            from_data = {
                "fromType": "project",
                "fromProjectCode": current_project.project_code if current_project else None,
                "fromProjectName": current_project.project_name if current_project else None,
                "fromAddress": current_project.shipping_address if current_project else None,
                "fromGstn": current_project.gstn if current_project else None,
            }
            to_data = {
                "toProjectCode": to_proj.project_code if to_proj else None,
                "toProjectName": to_proj.project_name if to_proj else None,
                "toAddress": to_proj.shipping_address if to_proj else None,
                "toGstn": to_proj.gstn if to_proj else None,
            }
        else:
            vendor = order.vendor
            from_data = {
                "fromType": "vendor",
                "fromVendorId": vendor.id if vendor else None,
                "fromVendorName": vendor.ledger_name if vendor else None,
                "fromAddress": vendor.registered_address if vendor else None,
                "fromGstn": vendor.gstin if vendor else None,
            }
            to_data = {
                "toProjectCode": current_project.project_code if current_project else None,
                "toProjectName": current_project.project_name if current_project else None,
                "toAddress": current_project.shipping_address if current_project else None,
                "toGstn": current_project.gstn if current_project else None,
            }

        return res("From details fetched", [{**from_data, **to_data}], 200)

    except Exception as e:
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 4. CREATE DC
# ══════════════════════════════════════════════════════════════════

def create_dc(data, user_id, files=None):
    try:
        items = data.get("items", [])
        if isinstance(items, str):
            items = json.loads(items)

        if not items:
            return res("No items selected", [], 400)

        order_id            = data.get("orderId")
        order_type          = data.get("orderType")
        current_project_code = data.get("currentProjectCode")

        if not order_id or not order_type or not current_project_code:
            return res("orderId, orderType and currentProjectCode required", [], 400)

        order = OrderMaster.query.get(order_id)
        if not order:
            return res("Order not found", [], 404)

        current_project = Project.query.filter_by(project_code=current_project_code).first()
        if not current_project:
            return res("Current project not found", [], 404)

        # resolve from/to side
        from_vendor_id    = None
        from_project_code = None
        to_project_code   = None
        shipping_from     = data.get("shippingFromAddress")

        if order.category_code == SITE_TRANSFER_TYPE:
            # Site Transfer: FROM = current project, TO = transfer destination
            from_project_code = current_project_code
            to_project_code   = order.transfer_project_site
            if not shipping_from:
                shipping_from = current_project.shipping_address
        else:
            # Purchase Order: FROM = vendor, TO = current project
            from_vendor_id = order.vendor_id
            to_project_code = current_project_code
            if not shipping_from and order.vendor:
                shipping_from = order.vendor.registered_address
        # attached doc upload
        attached_doc = None
        if files:
            doc_file = files.get("attachedDoc")
            if doc_file:
                dc_no_temp = generate_dc_no()
                attached_doc = upload_file_to_bunny(
                    file=doc_file,
                    mainFolder="dc",
                    subFolder=dc_no_temp,
                    fileName="doc"
                )

        dc = DcMaster(
            dc_no=generate_dc_no(),
            challan_date=data.get("challanDate"),
            order_type=order_type,
            order_id=order_id,
            from_vendor_id=from_vendor_id,
            from_project_code=from_project_code,
            shipping_from_address=shipping_from,
            to_project_code=to_project_code,
            shipping_to_address=data.get("shippingToAddress"),
            contact_person=data.get("contactPerson"),
            purpose_for_delivery=data.get("purposeForDelivery"),
            delivery_mode=data.get("deliveryMode"),
            vehicle_number=data.get("vehicleNumber"),
            driver_name=data.get("driverName"),
            driver_contact_number=data.get("driverContactNumber"),
            eway_bill_number=data.get("ewayBillNumber"),
            eway_bill_date=data.get("ewayBillDate"),
            eway_bill_expiry_date=data.get("ewayBillExpiryDate"),
            attached_doc=attached_doc,
            workflow_status="Draft",
            current_level=0,
            locked=False,
            created_by=user_id
        )

        db.session.add(dc)
        db.session.flush()

        for row in items:
            order_item_id = row.get("orderItemId")
            issue_qty     = float(row.get("issueQty", 0))

            if issue_qty <= 0:
                continue

            order_item = OrderItem.query.get(order_item_id)
            if not order_item:
                db.session.rollback()
                return res(f"Order item {order_item_id} not found", [], 404)

            # check balance
            already_dispatched = _pre_issued_dc_qty(order_item_id)
            balance = float(order_item.qty or 0) - already_dispatched

            if issue_qty > balance:
                db.session.rollback()
                return res(
                    f"Only {balance} available for item {order_item.item_code}",
                    [], 400
                )

            db.session.add(DcItem(
                dc_id=dc.id,
                order_item_id=order_item_id,
                item_code=order_item.item_code,
                issue_qty=issue_qty,
                stock_location=row.get("stockLocation") or order_item.location
            ))

        db.session.commit()

        return res("Delivery Challan created", [{"dcId": dc.id, "dcNo": dc.dc_no}], 201)

    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 5. DC LIST
# ══════════════════════════════════════════════════════════════════

def get_dc_list(data):
    try:
        project_code = data.get("projectCode")
        if not project_code:
            return res("projectCode required", [], 400)

        # Site Transfer: current project is FROM, others are TO
        # Purchase Order: current project is TO, others are FROM
        query = DcMaster.query.filter(
            or_(
                (DcMaster.to_project_code == project_code) & (DcMaster.order_type != SITE_TRANSFER_TYPE),
                (DcMaster.from_project_code == project_code) & (DcMaster.order_type == SITE_TRANSFER_TYPE),
            )
        )

        if data.get("orderType"):
            query = query.filter(DcMaster.order_type == data.get("orderType"))

        if data.get("workflowStatus"):
            query = query.filter(DcMaster.workflow_status == data.get("workflowStatus"))

        if data.get("search"):
            query = query.filter(DcMaster.dc_no.ilike(f"%{data.get('search')}%"))

        rows = query.order_by(DcMaster.id.desc()).all()

        result = []
        for row in rows:
            # from-side name
            if row.order_type == SITE_TRANSFER_TYPE:
                from_name = row.from_project.project_name if row.from_project else None
            else:
                from_name = row.from_vendor.ledger_name if row.from_vendor else None

            result.append({
                "id":             row.id,
                "dcNo":           row.dc_no,
                "challanDate":    _fmt_date(row.challan_date),
                "orderType":      row.order_type,
                "orderNo":        row.order.order_no if row.order else None,
                "fromName":       from_name,
                "toProjectCode":  row.to_project_code,
                "toProjectName":  row.to_project.project_name if row.to_project else None,
                "purposeForDelivery": row.purpose_for_delivery,
                "noOfItems":      len(row.items),
                "workflowStatus": row.workflow_status,
                "ewayBillNumber": row.eway_bill_number,
            })

        return res("DC list fetched", result, 200)

    except Exception as e:
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 6. DC DETAIL
# ══════════════════════════════════════════════════════════════════

def get_dc_detail(dc_id):
    try:
        dc = DcMaster.query.get(dc_id)
        if not dc:
            return res("DC not found", [], 404)

        # from-side
        if dc.order_type == SITE_TRANSFER_TYPE:
            from_data = {
                "fromType":        "project",
                "fromProjectCode": dc.from_project_code,
                "fromProjectName": dc.from_project.project_name if dc.from_project else None,
                "fromClientName":  dc.from_project.client_name if dc.from_project else None,
                "fromGstn":        dc.from_project.gstn if dc.from_project else None,
            }
        else:
            from_data = {
                "fromType":       "vendor",
                "fromVendorId":   dc.from_vendor_id,
                "fromVendorName": dc.from_vendor.ledger_name if dc.from_vendor else None,
                "fromGstn":       dc.from_vendor.gstin if dc.from_vendor else None,
            }

        items = [
            {
                "id":            i.id,
                "orderItemId":   i.order_item_id,
                "itemCode":      i.item_code,
                "itemName":      i.item.item_name if i.item else None,
                "itemUnit":      i.item.unit.unit_name if i.item and i.item.unit else None,
                "issueQty":      float(i.issue_qty or 0),
                "stockLocation": i.stock_location,
                "orderQty":      float(i.order_item.qty or 0) if i.order_item else None,
            }
            for i in dc.items
        ]

        data = {
            "id":               dc.id,
            "dcNo":             dc.dc_no,
            "challanDate":      _fmt_date(dc.challan_date),
            "orderType":        dc.order_type,
            "orderId":          dc.order_id,
            "orderNo":          dc.order.order_no if dc.order else None,
            **from_data,
            "shippingFromAddress": dc.shipping_from_address,
            "toProjectCode":    dc.to_project_code,
            "toProjectName":    dc.to_project.project_name if dc.to_project else None,
            "shippingToAddress": dc.shipping_to_address,
            "contactPerson":    dc.contact_person,
            "purposeForDelivery": dc.purpose_for_delivery,
            "deliveryMode":     dc.delivery_mode,
            "vehicleNumber":    dc.vehicle_number,
            "driverName":       dc.driver_name,
            "driverContactNumber": dc.driver_contact_number,
            "ewayBillNumber":   dc.eway_bill_number,
            "ewayBillDate":     _fmt_date(dc.eway_bill_date),
            "ewayBillExpiryDate": _fmt_date(dc.eway_bill_expiry_date),
            "attachedDoc":      dc.attached_doc,
            "workflowStatus":   dc.workflow_status,
            "items":            items,
        }

        return res("DC detail fetched", [data], 200)

    except Exception as e:
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# WORKFLOW PROJECT CODE
#   The "owning" project for approval flow = the project where the DC
#   was created (current project).
#   • Purchase_Order      → to_project_code   (current = receiver)
#   • Site_Transfer_Order → from_project_code (current = sender)
# ══════════════════════════════════════════════════════════════════

def _dc_project_code(dc):
    if dc.order_type == SITE_TRANSFER_TYPE:
        return dc.from_project_code
    return dc.to_project_code


# ══════════════════════════════════════════════════════════════════
# 7. SUBMIT DC
# ══════════════════════════════════════════════════════════════════

def submit_dc(dc_id, submitted_by=None):
    try:
        dc = DcMaster.query.get(dc_id)
        if not dc:
            return res("DC not found", [], 404)

        if dc.workflow_status not in ["Draft", "Reback"]:
            return res("DC already submitted", [], 400)

        if not dc.items:
            return res("DC has no items", [], 400)

        project_code = _dc_project_code(dc)

        allowed = is_creator(project_code, MODULE_CODE, submitted_by)
        if not allowed:
            return res("You are not DC creator", [], 403)

        if dc.workflow_status == "Reback":
            dc.current_level = 0

        first_level = get_first_approver(project_code, MODULE_CODE)

        if not first_level:
            dc.workflow_status = "Approved"
            dc.locked = True
            dc.approved_by = submitted_by
            dc.submitted_at = datetime.utcnow()
            dc.final_approved_at = datetime.utcnow()
        else:
            dc.workflow_status = f"Pending_L{first_level.level_no}"
            dc.current_level = first_level.level_no
            dc.locked = True
            dc.submitted_at = datetime.utcnow()

        create_history(
            project_code=project_code,
            module_code=MODULE_CODE,
            record_id=dc.id,
            level_no=dc.current_level,
            action="SUBMIT",
            action_by=submitted_by
        )

        dc.submitted_by = submitted_by
        dc.updated_by = submitted_by
        dc.updated_at = datetime.utcnow()

        if dc.workflow_status == "Reback":
            dc.correction_sent_at = None

        db.session.commit()

        return res(
            "DC submitted successfully",
            {
                "dcId": dc.id,
                "dcNo": dc.dc_no,
                "workflowStatus": dc.workflow_status
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
# 8. APPROVE DC
# ══════════════════════════════════════════════════════════════════

def approve_dc(dc_id, approved_by=None, comments=None):
    try:
        dc = DcMaster.query.get(dc_id)
        if not dc:
            return res("DC not found", [], 404)

        if not dc.workflow_status.startswith("Pending"):
            return res("DC not pending", [], 400)

        project_code = _dc_project_code(dc)

        allowed = is_current_approver(
            project_code,
            MODULE_CODE,
            dc.current_level,
            approved_by
        )

        if not allowed:
            return res("You are not current approver", [], 403)

        next_level = get_next_approver(
            project_code,
            MODULE_CODE,
            dc.current_level
        )

        if next_level:
            create_history(
                project_code=project_code,
                module_code=MODULE_CODE,
                record_id=dc.id,
                level_no=dc.current_level,
                action="APPROVE",
                action_by=approved_by,
                comments=comments
            )
            dc.current_level = next_level.level_no
            dc.workflow_status = f"Pending_L{next_level.level_no}"
        else:
            create_history(
                project_code=project_code,
                module_code=MODULE_CODE,
                record_id=dc.id,
                level_no=dc.current_level,
                action="FINAL_APPROVE",
                action_by=approved_by,
                comments=comments
            )
            dc.workflow_status = "Approved"
            dc.locked = True
            dc.approved_by = approved_by
            dc.final_approved_at = datetime.utcnow()

        dc.updated_by = approved_by
        dc.updated_at = datetime.utcnow()

        db.session.commit()

        return res(
            "DC approved successfully",
            {
                "dcId": dc.id,
                "workflowStatus": dc.workflow_status,
                "currentLevel": dc.current_level
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
# 9. REBACK DC (send for correction)
# ══════════════════════════════════════════════════════════════════

def reback_dc(dc_id, reback_by=None, comments=None):
    try:
        dc = DcMaster.query.get(dc_id)
        if not dc:
            return res("DC not found", [], 404)

        if not dc.workflow_status.startswith("Pending"):
            return res("DC not pending", [], 400)

        if not comments:
            return res("Comments required", [], 400)

        project_code = _dc_project_code(dc)

        allowed = is_current_approver(
            project_code,
            MODULE_CODE,
            dc.current_level,
            reback_by
        )

        if not allowed:
            return res("You are not current approver", [], 403)

        dc.workflow_status = "Reback"
        dc.locked = False
        dc.correction_sent_at = datetime.utcnow()
        dc.updated_by = reback_by
        dc.updated_at = datetime.utcnow()

        create_history(
            project_code=project_code,
            module_code=MODULE_CODE,
            record_id=dc.id,
            level_no=dc.current_level,
            action="REBACK",
            action_by=reback_by,
            comments=comments
        )

        db.session.commit()

        return res(
            "DC sent for correction",
            {"dcId": dc.id, "workflowStatus": dc.workflow_status},
            200
        )

    except SQLAlchemyError as e:
        db.session.rollback()
        return res(str(e), [], 500)

    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 10. REJECT DC
# ══════════════════════════════════════════════════════════════════

def reject_dc(dc_id, rejected_by=None, comments=None):
    try:
        dc = DcMaster.query.get(dc_id)
        if not dc:
            return res("DC not found", [], 404)

        if not dc.workflow_status.startswith("Pending"):
            return res("DC not pending", [], 400)

        if not comments:
            return res("Comments required", [], 400)

        project_code = _dc_project_code(dc)

        allowed = is_current_approver(
            project_code,
            MODULE_CODE,
            dc.current_level,
            rejected_by
        )

        if not allowed:
            return res("You are not current approver", [], 403)

        dc.workflow_status = "Rejected"
        dc.locked = True
        dc.rejected_at = datetime.utcnow()
        dc.rejected_by = rejected_by
        dc.status = "Inactive"
        dc.updated_by = rejected_by
        dc.updated_at = datetime.utcnow()

        create_history(
            project_code=project_code,
            module_code=MODULE_CODE,
            record_id=dc.id,
            level_no=dc.current_level,
            action="REJECT",
            action_by=rejected_by,
            comments=comments
        )

        db.session.commit()

        return res(
            "DC rejected",
            {"dcId": dc.id, "workflowStatus": dc.workflow_status},
            200
        )

    except SQLAlchemyError as e:
        db.session.rollback()
        return res(str(e), [], 500)

    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 11. DC HISTORY
# ══════════════════════════════════════════════════════════════════

def get_dc_history(dc_id):
    try:
        dc = DcMaster.query.get(dc_id)
        if not dc:
            return res("DC not found", [], 404)

        rows = get_history(MODULE_CODE, dc.id)

        data = []
        for row in rows:
            data.append({
                "id": row.id,
                "action": row.action,
                "level": row.level_no,
                "comments": row.comments,
                "actionBy": row.user.username if row.user else None,
                "createdAt": (
                    row.created_at.strftime("%Y-%m-%d %H:%M:%S")
                    if row.created_at else None
                ),
            })

        return res("DC history fetched", data, 200)

    except Exception as e:
        return res(str(e), [], 500)
