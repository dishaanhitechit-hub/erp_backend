import uuid as _uuid
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.extensions import db
from app.models.batchingPlant import BatchingPlantMaster
from app.models.ORDER_projectwork import ProjectWorkOrderMaster
from app.models.vendor import Vendor
from app.response import res
from app.modules.work_flow import (
    is_creator,
    is_current_approver,
    get_first_approver,
    get_next_approver,
    get_gap_level,
    create_history,
    get_history,
    get_approval_steps,
    get_my_approval_status,
)

MODULE_CODE = "batching"


# ═══════════════════════════════════════════════════════════════════
# DESPATCH NUMBER GENERATOR
# ═══════════════════════════════════════════════════════════════════

def _generate_despatch_no():
    db.session.execute(text("SELECT pg_advisory_xact_lock(460000)"))
    last = (
        db.session.query(BatchingPlantMaster.despatch_no)
        .order_by(BatchingPlantMaster.id.desc())
        .first()
    )
    if not last:
        return "BP001"
    suffix = last[0][2:]   # strip "BP"
    next_num = int(suffix) + 1
    return "BP" + str(next_num).zfill(len(suffix))


# ═══════════════════════════════════════════════════════════════════
# HELPER – vendor info dict
# ═══════════════════════════════════════════════════════════════════

def _vendor_info(vendor):
    if not vendor:
        return None
    return {
        "vendorId":   vendor.id,
        "ledgerName": vendor.ledger_name,
        "ledgerCode": vendor.ledger_code,
        "gstin":      vendor.gstin,
        "pan":        vendor.pan,
    }


# ═══════════════════════════════════════════════════════════════════
# HELPER – pw order info dict
# ═══════════════════════════════════════════════════════════════════

def _pw_order_info(order):
    if not order:
        return None
    return {
        "pwOrderId":  order.id,
        "orderNo":    order.order_no,
        "vendorId":   order.vendor_id,
        "vendorName": order.vendor.ledger_name if order.vendor else None,
    }


# ═══════════════════════════════════════════════════════════════════
# HELPER – serialise a BatchingPlantMaster row
# ═══════════════════════════════════════════════════════════════════

def _serialise(bp):
    return {
        "id":                  bp.id,
        "despatchNo":          bp.despatch_no,
        "uuid":                bp.bp_uuid,
        "projectCode":         bp.project_code,
        "projectName":         bp.project.project_name if bp.project else None,
        "productionDate":      str(bp.production_date) if bp.production_date else None,

        "pwOrderId":           bp.pw_order_id,
        "orderNo":             bp.pw_order.order_no if bp.pw_order else None,
        "vendorId":            bp.vendor_id,
        "vendorName":          bp.vendor.ledger_name if bp.vendor else None,

        "materialType":        bp.material_type,
        "grade":               bp.grade,
        "unitOfConcrete":      bp.unit_of_concrete,
        "volumeOfConcrete":    float(bp.volume_of_concrete) if bp.volume_of_concrete is not None else None,
        "weightOfConcrete":    float(bp.weight_of_concrete) if bp.weight_of_concrete is not None else None,

        "productionUnitName":  bp.production_unit_name,
        "operatorName":        bp.operator_name,
        "productionCompleted": bp.production_completed,
        "batchSlipNo":         bp.batch_slip_no,

        "vehicleNumber":       bp.vehicle_number,
        "driverName":          bp.driver_name,
        "loadingFinishTime":   bp.loading_finish_time,
        "pouringStartTime":    bp.pouring_start_time,
        "completionTime":      bp.completion_time,

        "requisitionBy":       bp.requisition_by,
        "requisitionDate":     str(bp.requisition_date) if bp.requisition_date else None,
        "requisitionTime":     bp.requisition_time,

        "workflowStatus":      bp.workflow_status,
        "status":              bp.status,
        "currentLevel":        bp.current_level,
        "locked":              bp.locked,

        "createdBy":           bp.creator.username if bp.creator else None,
        "createdAt":           bp.created_at.strftime("%Y-%m-%d %H:%M:%S") if bp.created_at else None,
        "approvedBy":          bp.approver.username if bp.approver else None,
        "finalApprovedAt":     bp.final_approved_at.strftime("%Y-%m-%d %H:%M:%S") if bp.final_approved_at else None,
    }


# ═══════════════════════════════════════════════════════════════════
# CREATE
# ═══════════════════════════════════════════════════════════════════

def create_batching_plant(data, user_id):
    project_code = data.get("projectCode")

    if not project_code:
        return res("projectCode required", [], 400)

    allowed = is_creator(project_code, MODULE_CODE, user_id)
    if not allowed:
        return res("You are not a batching plant creator", [], 403)

    try:
        new_uuid = str(_uuid.uuid4())
        despatch_no = _generate_despatch_no()

        bp = BatchingPlantMaster(
            despatch_no=despatch_no,
            bp_uuid=new_uuid,
            project_code=project_code,
            production_date=data.get("productionDate") or None,
            pw_order_id=data.get("pwOrderId") or None,
            vendor_id=data.get("vendorId") or None,
            material_type=data.get("materialType"),
            grade=data.get("grade"),
            unit_of_concrete=data.get("unitOfConcrete"),
            volume_of_concrete=data.get("volumeOfConcrete") or None,
            weight_of_concrete=data.get("weightOfConcrete") or None,
            production_unit_name=data.get("productionUnitName"),
            operator_name=data.get("operatorName"),
            production_completed=data.get("productionCompleted"),
            batch_slip_no=data.get("batchSlipNo"),
            vehicle_number=data.get("vehicleNumber"),
            driver_name=data.get("driverName"),
            loading_finish_time=data.get("loadingFinishTime"),
            pouring_start_time=data.get("pouringStartTime"),
            completion_time=data.get("completionTime"),
            requisition_by=data.get("requisitionBy"),
            requisition_date=data.get("requisitionDate") or None,
            requisition_time=data.get("requisitionTime"),
            workflow_status="Draft",
            current_level=0,
            locked=False,
            created_by=user_id,
        )

        db.session.add(bp)
        db.session.commit()

        return res(
            "Batching plant docket created",
            {
                "id":         bp.id,
                "despatchNo": bp.despatch_no,
                "uuid":       bp.bp_uuid,
            },
            201,
        )

    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ═══════════════════════════════════════════════════════════════════
# LIST
# ═══════════════════════════════════════════════════════════════════

def get_batching_plant_list(data):
    project_code = data.get("projectCode")
    if not project_code:
        return res("projectCode required", [], 400)

    try:
        query = BatchingPlantMaster.query.filter(
            BatchingPlantMaster.project_code == project_code,
            BatchingPlantMaster.status == "Active",
        )

        if data.get("workflowStatus"):
            query = query.filter(
                BatchingPlantMaster.workflow_status == data["workflowStatus"]
            )

        if data.get("search"):
            query = query.filter(
                BatchingPlantMaster.despatch_no.ilike(f"%{data['search']}%")
            )

        rows = query.order_by(BatchingPlantMaster.id.desc()).all()

        result = []
        for row in rows:
            result.append({
                "id":             row.id,
                "despatchNo":     row.despatch_no,
                "uuid":           row.bp_uuid,
                "projectCode":    row.project_code,
                "productionDate": str(row.production_date) if row.production_date else None,
                "orderNo":        row.pw_order.order_no if row.pw_order else None,
                "vendorName":     row.vendor.ledger_name if row.vendor else None,
                "grade":          row.grade,
                "volumeOfConcrete": float(row.volume_of_concrete) if row.volume_of_concrete is not None else None,
                "workflowStatus": row.workflow_status,
                "createdBy":      row.creator.username if row.creator else None,
                "createdAt":      row.created_at.strftime("%Y-%m-%d %H:%M:%S") if row.created_at else None,
            })

        return res("Batching plant list fetched", result, 200)

    except Exception as e:
        return res(str(e), [], 500)


# ═══════════════════════════════════════════════════════════════════
# DETAILS BY ID
# ═══════════════════════════════════════════════════════════════════

def get_batching_plant_details(bp_id):
    try:
        bp = BatchingPlantMaster.query.get(bp_id)
        if not bp:
            return res("Batching plant docket not found", [], 404)
        return res("Batching plant details fetched", _serialise(bp), 200)
    except Exception as e:
        return res(str(e), [], 500)


# ═══════════════════════════════════════════════════════════════════
# DETAILS BY UUID (public)
# ═══════════════════════════════════════════════════════════════════

def get_batching_plant_by_uuid(bp_uuid):
    try:
        bp = BatchingPlantMaster.query.filter_by(bp_uuid=bp_uuid).first()
        if not bp:
            return res("Batching plant docket not found", [], 404)
        return res("Batching plant details fetched", _serialise(bp), 200)
    except Exception as e:
        return res(str(e), [], 500)


# ═══════════════════════════════════════════════════════════════════
# SUBMIT
# ═══════════════════════════════════════════════════════════════════

def submit_batching_plant(bp_id, submitted_by):
    try:
        bp = BatchingPlantMaster.query.get(bp_id)
        if not bp:
            return res("Batching plant docket not found", [], 404)

        if bp.workflow_status not in ("Draft", "Reback"):
            return res("Docket already submitted", [], 400)

        if bp.workflow_status == "Reback":
            bp.current_level = 0

        first_level = get_first_approver(bp.project_code, MODULE_CODE)

        if not first_level:
            bp.workflow_status = "Approved"
            bp.locked = True
            bp.approved_by = submitted_by
            bp.submitted_at = datetime.utcnow()
            bp.final_approved_at = datetime.utcnow()
        else:
            bp.workflow_status = f"Pending_L{first_level.level_no}"
            bp.current_level = first_level.level_no
            bp.locked = True
            bp.submitted_at = datetime.utcnow()

        create_history(
            project_code=bp.project_code,
            module_code=MODULE_CODE,
            record_id=bp.id,
            level_no=bp.current_level,
            action="SUBMIT",
            action_by=submitted_by,
        )

        bp.submitted_by = submitted_by
        bp.updated_by = submitted_by
        bp.updated_at = datetime.utcnow()

        db.session.commit()

        return res(
            "Docket submitted successfully",
            {"id": bp.id, "despatchNo": bp.despatch_no, "workflowStatus": bp.workflow_status},
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

def approve_batching_plant(bp_id, approved_by, comments=None):
    try:
        bp = BatchingPlantMaster.query.get(bp_id)
        if not bp:
            return res("Batching plant docket not found", [], 404)

        if not bp.workflow_status.startswith("Pending"):
            return res("Docket is not pending", [], 400)

        if not is_current_approver(bp.project_code, MODULE_CODE, bp.current_level, approved_by):
            return res("You are not the current approver", [], 403)

        gap = get_gap_level(bp.project_code, MODULE_CODE, bp.current_level)
        if gap:
            return res(f"L{gap} is not assigned. Please assign it before approving.", [], 400)

        next_level = get_next_approver(bp.project_code, MODULE_CODE, bp.current_level)

        if next_level:
            create_history(
                project_code=bp.project_code,
                module_code=MODULE_CODE,
                record_id=bp.id,
                level_no=bp.current_level,
                action="APPROVE",
                action_by=approved_by,
                comments=comments,
            )
            bp.current_level = next_level.level_no
            bp.workflow_status = f"Pending_L{next_level.level_no}"
        else:
            create_history(
                project_code=bp.project_code,
                module_code=MODULE_CODE,
                record_id=bp.id,
                level_no=bp.current_level,
                action="FINAL_APPROVE",
                action_by=approved_by,
                comments=comments,
            )
            bp.workflow_status = "Approved"
            bp.locked = True
            bp.approved_by = approved_by
            bp.final_approved_at = datetime.utcnow()

        bp.updated_by = approved_by
        bp.updated_at = datetime.utcnow()
        db.session.commit()

        return res(
            "Docket approved",
            {"id": bp.id, "workflowStatus": bp.workflow_status, "currentLevel": bp.current_level},
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

def reback_batching_plant(bp_id, reback_by, comments=None):
    try:
        bp = BatchingPlantMaster.query.get(bp_id)
        if not bp:
            return res("Batching plant docket not found", [], 404)

        if not bp.workflow_status.startswith("Pending"):
            return res("Docket is not pending", [], 400)

        if not comments:
            return res("Comments required", [], 400)

        if not is_current_approver(bp.project_code, MODULE_CODE, bp.current_level, reback_by):
            return res("You are not the current approver", [], 403)

        bp.workflow_status = "Reback"
        bp.locked = False
        bp.correction_sent_at = datetime.utcnow()
        bp.updated_by = reback_by
        bp.updated_at = datetime.utcnow()

        create_history(
            project_code=bp.project_code,
            module_code=MODULE_CODE,
            record_id=bp.id,
            level_no=bp.current_level,
            action="REBACK",
            action_by=reback_by,
            comments=comments,
        )

        db.session.commit()

        return res(
            "Docket sent back for correction",
            {"id": bp.id, "workflowStatus": bp.workflow_status},
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

def reject_batching_plant(bp_id, rejected_by, comments=None):
    try:
        bp = BatchingPlantMaster.query.get(bp_id)
        if not bp:
            return res("Batching plant docket not found", [], 404)

        if not bp.workflow_status.startswith("Pending"):
            return res("Docket is not pending", [], 400)

        if not comments:
            return res("Comments required", [], 400)

        if not is_current_approver(bp.project_code, MODULE_CODE, bp.current_level, rejected_by):
            return res("You are not the current approver", [], 403)

        bp.workflow_status = "Rejected"
        bp.locked = True
        bp.rejected_at = datetime.utcnow()
        bp.rejected_by = rejected_by
        bp.status = "Inactive"
        bp.updated_by = rejected_by
        bp.updated_at = datetime.utcnow()

        create_history(
            project_code=bp.project_code,
            module_code=MODULE_CODE,
            record_id=bp.id,
            level_no=bp.current_level,
            action="REJECT",
            action_by=rejected_by,
            comments=comments,
        )

        db.session.commit()

        return res(
            "Docket rejected",
            {"id": bp.id, "workflowStatus": bp.workflow_status},
            200,
        )

    except SQLAlchemyError as e:
        db.session.rollback()
        return res(str(e), [], 500)
    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ═══════════════════════════════════════════════════════════════════
# EDIT
# ═══════════════════════════════════════════════════════════════════

def edit_batching_plant(bp_id, data, user_id):
    try:
        bp = BatchingPlantMaster.query.get(bp_id)
        if not bp:
            return res("Batching plant docket not found", [], 404)

        if bp.locked:
            return res("Only Draft or Reback dockets can be edited", [], 400)

        updatable = [
            ("productionDate",     "production_date"),
            ("pwOrderId",          "pw_order_id"),
            ("vendorId",           "vendor_id"),
            ("materialType",       "material_type"),
            ("grade",              "grade"),
            ("unitOfConcrete",     "unit_of_concrete"),
            ("volumeOfConcrete",   "volume_of_concrete"),
            ("weightOfConcrete",   "weight_of_concrete"),
            ("productionUnitName", "production_unit_name"),
            ("operatorName",       "operator_name"),
            ("productionCompleted","production_completed"),
            ("batchSlipNo",        "batch_slip_no"),
            ("vehicleNumber",      "vehicle_number"),
            ("driverName",         "driver_name"),
            ("loadingFinishTime",  "loading_finish_time"),
            ("pouringStartTime",   "pouring_start_time"),
            ("completionTime",     "completion_time"),
            ("requisitionBy",      "requisition_by"),
            ("requisitionDate",    "requisition_date"),
            ("requisitionTime",    "requisition_time"),
        ]

        for key, col in updatable:
            if key in data:
                val = data[key]
                setattr(bp, col, val if val not in ("", None) else None)

        bp.updated_by = user_id
        bp.updated_at = datetime.utcnow()

        db.session.commit()

        return res("Docket updated", {"id": bp.id, "despatchNo": bp.despatch_no}, 200)

    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ═══════════════════════════════════════════════════════════════════
# DELETE
# ═══════════════════════════════════════════════════════════════════

def delete_batching_plant(bp_id):
    try:
        bp = BatchingPlantMaster.query.get(bp_id)
        if not bp:
            return res("Batching plant docket not found", [], 404)

        if bp.locked:
            return res("Only Draft or Reback dockets can be deleted", [], 400)

        db.session.delete(bp)
        db.session.commit()

        return res("Docket deleted", [], 200)

    except SQLAlchemyError as e:
        db.session.rollback()
        return res(str(e), [], 500)
    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ═══════════════════════════════════════════════════════════════════
# HISTORY
# ═══════════════════════════════════════════════════════════════════

def get_batching_plant_history(bp_id):
    try:
        bp = BatchingPlantMaster.query.get(bp_id)
        if not bp:
            return res("Batching plant docket not found", [], 404)

        rows = get_history(MODULE_CODE, bp.id)

        history = [
            {
                "id":        row.id,
                "action":    row.action,
                "level":     row.level_no,
                "comments":  row.comments,
                "actionBy":  row.user.username if row.user else None,
                "createdAt": row.created_at.strftime("%Y-%m-%d %H:%M:%S") if row.created_at else None,
            }
            for row in rows
        ]

        steps = get_approval_steps(bp.project_code, MODULE_CODE, bp, rows)

        return res(
            "History fetched",
            {
                "workflowStatus": bp.workflow_status,
                "currentLevel":   bp.current_level,
                "approvalSteps":  steps,
                "history":        history,
            },
            200,
        )

    except Exception as e:
        return res(str(e), [], 500)


# ═══════════════════════════════════════════════════════════════════
# MY APPROVAL STATUS
# ═══════════════════════════════════════════════════════════════════

def get_batching_plant_my_approval_status(bp_id, user_id):
    try:
        bp = BatchingPlantMaster.query.get(bp_id)
        if not bp:
            return res("Batching plant docket not found", [], 404)

        status = get_my_approval_status(bp.project_code, MODULE_CODE, bp, user_id)
        return res("Approval status fetched", status, 200)

    except Exception as e:
        return res(str(e), [], 500)


# ═══════════════════════════════════════════════════════════════════
# APPROVED PW ORDERS (helper for order-dropdown)
# ═══════════════════════════════════════════════════════════════════

def get_approved_pw_orders(project_code, vendor_id=None):
    if not project_code:
        return res("projectCode required", [], 400)

    try:
        query = ProjectWorkOrderMaster.query.filter(
            ProjectWorkOrderMaster.project_code == project_code,
            ProjectWorkOrderMaster.workflow_status == "Approved",
        )

        if vendor_id:
            query = query.filter(
                ProjectWorkOrderMaster.vendor_id == int(vendor_id)
            )

        orders = query.order_by(ProjectWorkOrderMaster.id.desc()).all()

        result = [
            {
                "pwOrderId":  o.id,
                "orderNo":    o.order_no,
                "vendorId":   o.vendor_id,
                "vendorName": o.vendor.ledger_name if o.vendor else None,
            }
            for o in orders
        ]

        return res("Approved PW orders fetched", result, 200)

    except Exception as e:
        return res(str(e), [], 500)


# ═══════════════════════════════════════════════════════════════════
# VENDOR FROM PW ORDER (auto-fill when order is selected first)
# ═══════════════════════════════════════════════════════════════════

def get_vendor_from_pw_order(pw_order_id):
    try:
        order = ProjectWorkOrderMaster.query.get(pw_order_id)
        if not order:
            return res("PW order not found", [], 404)

        return res(
            "Vendor fetched",
            {
                "pwOrderId":  order.id,
                "orderNo":    order.order_no,
                "vendor":     _vendor_info(order.vendor),
            },
            200,
        )

    except Exception as e:
        return res(str(e), [], 500)
