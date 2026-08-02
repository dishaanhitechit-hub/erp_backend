from sqlalchemy.exc import SQLAlchemyError
from app.extensions import db
from datetime import datetime
import uuid as _uuid
import json

from app.models.ogSaleOrder import OgSaleOrderMaster, OgSaleOrderItem
from app.models.item import Item
from app.cloudinary_uploader import upload_file_to_bunny
from app.response import res
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

_MODULE = "sale_order"


# ══════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════

def _fmt_date(d):
    if d is None:
        return None
    if isinstance(d, datetime):
        return d.strftime("%Y-%m-%d %H:%M")
    return d.strftime("%Y-%m-%d")


def _parse_date(val):
    if not val:
        return None
    try:
        return datetime.strptime(str(val).strip(), "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def generate_og_sale_order_no():
    last = (
        db.session.query(OgSaleOrderMaster.og_sale_order_no)
        .order_by(OgSaleOrderMaster.id.desc())
        .with_for_update()
        .first()
    )
    if last:
        try:
            num = int(last[0][3:])  # strip "OSO" prefix
        except Exception:
            num = 0
    else:
        num = 0
    return f"OSO{str(num + 1).zfill(3)}"


def _upload_attachment(file, so_no, slot):
    if not file or not file.filename:
        return None
    return upload_file_to_bunny(
        file=file,
        mainFolder="og_sale_order",
        subFolder=so_no,
        fileName=slot,
    )


def _item_display_code(item_obj):
    """Returns cc_code + item_code, e.g. 'CC0010042'."""
    if not item_obj:
        return None
    cc = item_obj.cc_code.cc_code if item_obj.cc_code else ""
    return f"{cc}{item_obj.item_code}"


def _build_item_map(rows):
    """
    Batch-fetch Item objects for all itemCodes in rows.
    Returns (item_map, errors):
        item_map: {item_code: Item}
        errors:   list of error strings (empty when all ok)
    """
    codes = [str(r.get("itemCode", "")).strip() for r in rows]
    missing_idx = [i + 1 for i, c in enumerate(codes) if not c]
    if missing_idx:
        return {}, [f"Row {i}: itemCode is required" for i in missing_idx]

    objs = Item.query.filter(Item.item_code.in_(codes)).all()
    item_map = {obj.item_code: obj for obj in objs}

    errors = []
    for idx, code in enumerate(codes, start=1):
        if code not in item_map:
            errors.append(f"Row {idx}: itemCode '{code}' not found")

    return item_map, errors


def _serialize_items(items):
    codes = [row.item_code for row in items if row.item_code]
    item_map = {}
    if codes:
        objs = Item.query.filter(Item.item_code.in_(codes)).all()
        for obj in objs:
            item_map[obj.item_code] = obj

    result = []
    for row in items:
        item_obj = item_map.get(row.item_code)
        result.append({
            "id":              row.id,
            "slNo":            row.sl_no,
            "itemCode":        row.item_code,
            "itemDisplayCode": _item_display_code(item_obj),
            "itemName":        row.item_name,
            "itemDescription": row.item_description,
            "itemNameDesc":    row.item_name_desc,
            "unit":            row.unit,
            "orderQty":        float(row.order_qty   or 0),
            "rate":            float(row.rate         or 0),
            "amount":          float(row.amount       or 0),
            "gstPercent":      float(row.gst_percent  or 0),
            "gstAmount":       float(row.gst_amount   or 0),
        })
    return result


def _build_items(rows, og_sale_order_id, item_map):
    items = []
    total_basic = 0
    total_gst   = 0

    for idx, row in enumerate(rows, start=1):
        item_code = str(row.get("itemCode", "")).strip()
        item_obj  = item_map.get(item_code)

        # Snapshot from master; frontend can override description
        item_name        = item_obj.item_name        if item_obj else row.get("itemName")
        item_description = (
            row.get("itemDescription")
            if row.get("itemDescription") not in (None, "")
            else (item_obj.item_description if item_obj else None)
        )
        item_name_desc = item_name  # keep legacy field in sync
        unit           = row.get("unit") or (
            item_obj.unit.unit_name if item_obj and item_obj.unit else None
        )
        gst_percent = float(
            row.get("gstPercent")
            if row.get("gstPercent") not in (None, "")
            else (item_obj.gst_percentage or 0)
        )

        order_qty  = float(row.get("orderQty") or 0)
        rate       = float(row.get("rate")      or 0)
        amount     = round(order_qty * rate, 2)
        gst_amount = round((amount * gst_percent) / 100, 2)

        items.append(OgSaleOrderItem(
            og_sale_order_id = og_sale_order_id,
            sl_no            = row.get("slNo") or idx,
            item_code        = item_code,
            item_name        = item_name,
            item_description = item_description,
            item_name_desc   = item_name_desc,
            unit             = unit,
            order_qty        = order_qty,
            rate             = rate,
            amount           = amount,
            gst_percent      = gst_percent,
            gst_amount       = gst_amount,
        ))

        total_basic += amount
        total_gst   += gst_amount

    return items, round(total_basic, 2), round(total_gst, 2)


# ══════════════════════════════════════════════════════════════════
# 1. CREATE
# ══════════════════════════════════════════════════════════════════

def create_og_sale_order(request, user_id):
    try:
        data         = request.form
        project_code = data.get("projectCode")

        if not project_code:
            return res("projectCode required", [], 400)

        allowed = is_creator(project_code, _MODULE, user_id)
        if not allowed:
            return res("You are not an OG Sale Order creator", [], 403)

        order_title = data.get("orderTitle", "").strip()
        if not order_title:
            return res("orderTitle is required", [], 400)

        og_so_date = _parse_date(data.get("ogSaleOrderDate"))
        if not og_so_date:
            return res("ogSaleOrderDate is required (YYYY-MM-DD)", [], 400)

        try:
            items_raw = json.loads(data.get("items", "[]"))
        except Exception:
            items_raw = []

        if not items_raw:
            return res("At least one BOQ item required", [], 400)

        # Validate item codes against items master
        item_map, errors = _build_item_map(items_raw)
        if errors:
            return res("; ".join(errors), [], 400)

        so_no   = generate_og_sale_order_no()
        so_uuid = str(_uuid.uuid4())

        att_1 = _upload_attachment(request.files.get("attachment_1"), so_no, "attachment_1")
        att_2 = _upload_attachment(request.files.get("attachment_2"), so_no, "attachment_2")
        att_3 = _upload_attachment(request.files.get("attachment_3"), so_no, "attachment_3")

        og_so = OgSaleOrderMaster(
            og_sale_order_no   = so_no,
            og_sale_order_uuid = so_uuid,
            og_sale_order_date = og_so_date,
            order_no           = data.get("orderNo") or None,
            order_validity     = _parse_date(data.get("orderValidity")),
            order_title        = order_title,
            project_code       = project_code,
            prefix             = data.get("prefix")  or None,
            suffix             = data.get("suffix")  or None,
            attachment_1       = att_1,
            attachment_2       = att_2,
            attachment_3       = att_3,
            workflow_status    = "Draft",
            current_level      = 0,
            locked             = False,
            created_by         = user_id,
        )

        db.session.add(og_so)
        db.session.flush()

        built_items, total_basic, total_gst = _build_items(items_raw, og_so.id, item_map)
        for item in built_items:
            db.session.add(item)

        og_so.basic_amount = total_basic
        og_so.gst_amount   = total_gst
        og_so.total_amount = round(total_basic + total_gst, 2)

        db.session.commit()

        return res("OG Sale Order created", {
            "id":              og_so.id,
            "ogSaleOrderNo":   og_so.og_sale_order_no,
            "ogSaleOrderUuid": og_so.og_sale_order_uuid,
        }, 201)

    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 2. LIST
# ══════════════════════════════════════════════════════════════════

def get_og_sale_order_list(data):
    try:
        project_code = data.get("projectCode")
        if not project_code:
            return res("projectCode required", [], 400)

        query = OgSaleOrderMaster.query.filter(
            OgSaleOrderMaster.project_code == project_code
        )

        if data.get("workflowStatus"):
            query = query.filter(
                OgSaleOrderMaster.workflow_status == data.get("workflowStatus")
            )
        if data.get("search"):
            term = f"%{data.get('search')}%"
            query = query.filter(
                db.or_(
                    OgSaleOrderMaster.og_sale_order_no.ilike(term),
                    OgSaleOrderMaster.order_no.ilike(term),
                    OgSaleOrderMaster.order_title.ilike(term),
                )
            )

        rows = query.order_by(OgSaleOrderMaster.id.desc()).all()

        result = []
        for row in rows:
            result.append({
                "id":              row.id,
                "ogSaleOrderNo":   row.og_sale_order_no,
                "ogSaleOrderDate": _fmt_date(row.og_sale_order_date),
                "orderNo":         row.order_no,
                "orderValidity":   _fmt_date(row.order_validity),
                "orderTitle":      row.order_title,
                "basicAmount":     float(row.basic_amount or 0),
                "gstAmount":       float(row.gst_amount   or 0),
                "totalAmount":     float(row.total_amount  or 0),
                "workflowStatus":  row.workflow_status,
                "createdBy":       row.creator.username if row.creator else None,
                "createdAt":       _fmt_date(row.created_at),
            })

        return res("OG Sale Order list fetched", result, 200)

    except Exception as e:
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 3. DETAILS
# ══════════════════════════════════════════════════════════════════

def _build_detail_payload(og_so):
    return {
        "id":               og_so.id,
        "ogSaleOrderNo":    og_so.og_sale_order_no,
        "ogSaleOrderUuid":  og_so.og_sale_order_uuid,
        "ogSaleOrderDate":  _fmt_date(og_so.og_sale_order_date),
        "orderNo":          og_so.order_no,
        "orderValidity":    _fmt_date(og_so.order_validity),
        "orderTitle":       og_so.order_title,
        "projectCode":      og_so.project_code,
        "basicAmount":      float(og_so.basic_amount or 0),
        "gstAmount":        float(og_so.gst_amount   or 0),
        "totalAmount":      float(og_so.total_amount  or 0),
        "prefix":           og_so.prefix,
        "suffix":           og_so.suffix,
        "attachment1":      og_so.attachment_1,
        "attachment2":      og_so.attachment_2,
        "attachment3":      og_so.attachment_3,
        "workflowStatus":   og_so.workflow_status,
        "currentLevel":     og_so.current_level,
        "locked":           og_so.locked,
        "createdBy":        og_so.creator.username  if og_so.creator  else None,
        "createdAt":        _fmt_date(og_so.created_at),
        "submittedBy":      og_so.submitter.username if og_so.submitter else None,
        "submittedAt":      _fmt_date(og_so.submitted_at),
        "approvedBy":       og_so.approver.username  if og_so.approver  else None,
        "finalApprovedAt":  _fmt_date(og_so.final_approved_at),
        "rejectedBy":       og_so.rejector.username  if og_so.rejector  else None,
        "rejectedAt":       _fmt_date(og_so.rejected_at),
        "items":            _serialize_items(og_so.items),
    }


def get_og_sale_order_details(so_id):
    try:
        og_so = OgSaleOrderMaster.query.get(so_id)
        if not og_so:
            return res("OG Sale Order not found", [], 404)
        return res("OG Sale Order details fetched", _build_detail_payload(og_so), 200)
    except Exception as e:
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 4. EDIT
# ══════════════════════════════════════════════════════════════════

def edit_og_sale_order(so_id, request, user_id):
    try:
        og_so = OgSaleOrderMaster.query.get(so_id)
        if not og_so:
            return res("OG Sale Order not found", [], 404)

        if og_so.locked:
            return res("OG Sale Order is locked and cannot be edited", [], 400)
        if og_so.workflow_status not in ("Draft", "Reback"):
            return res("Only Draft or Reback records can be edited", [], 400)

        allowed = is_creator(og_so.project_code, _MODULE, user_id)
        if not allowed:
            return res("You are not an OG Sale Order creator", [], 403)

        data = request.form

        try:
            items_raw = json.loads(data.get("items", "[]"))
        except Exception:
            items_raw = []

        if not items_raw:
            return res("At least one BOQ item required", [], 400)

        # Validate item codes
        item_map, errors = _build_item_map(items_raw)
        if errors:
            return res("; ".join(errors), [], 400)

        # Update header fields
        if data.get("ogSaleOrderDate"):
            og_so.og_sale_order_date = _parse_date(data.get("ogSaleOrderDate"))
        if data.get("orderNo") is not None:
            og_so.order_no = data.get("orderNo") or None
        if data.get("orderValidity") is not None:
            og_so.order_validity = _parse_date(data.get("orderValidity"))
        if data.get("orderTitle"):
            og_so.order_title = data.get("orderTitle").strip()
        if data.get("prefix") is not None:
            og_so.prefix = data.get("prefix") or None
        if data.get("suffix") is not None:
            og_so.suffix = data.get("suffix") or None

        # Upload attachments only if new file provided
        f1 = request.files.get("attachment_1")
        f2 = request.files.get("attachment_2")
        f3 = request.files.get("attachment_3")
        if f1 and f1.filename:
            og_so.attachment_1 = _upload_attachment(f1, og_so.og_sale_order_no, "attachment_1")
        if f2 and f2.filename:
            og_so.attachment_2 = _upload_attachment(f2, og_so.og_sale_order_no, "attachment_2")
        if f3 and f3.filename:
            og_so.attachment_3 = _upload_attachment(f3, og_so.og_sale_order_no, "attachment_3")

        # Rebuild items
        OgSaleOrderItem.query.filter_by(og_sale_order_id=og_so.id).delete()
        db.session.flush()

        built_items, total_basic, total_gst = _build_items(items_raw, og_so.id, item_map)
        for item in built_items:
            db.session.add(item)

        og_so.basic_amount = total_basic
        og_so.gst_amount   = total_gst
        og_so.total_amount = round(total_basic + total_gst, 2)

        if og_so.workflow_status == "Reback":
            og_so.correction_sent_at = None

        og_so.updated_by = user_id
        og_so.updated_at = datetime.utcnow()

        db.session.commit()

        return res("OG Sale Order updated", {
            "id":            og_so.id,
            "ogSaleOrderNo": og_so.og_sale_order_no,
        }, 200)

    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 5. SUBMIT
# ══════════════════════════════════════════════════════════════════

def submit_og_sale_order(so_id, submitted_by):
    try:
        og_so = OgSaleOrderMaster.query.get(so_id)
        if not og_so:
            return res("OG Sale Order not found", [], 404)
        if og_so.workflow_status not in ("Draft", "Reback"):
            return res("OG Sale Order already submitted", [], 400)
        if not og_so.items:
            return res("OG Sale Order has no items", [], 400)

        if og_so.workflow_status == "Reback":
            og_so.current_level = 0

        first_level = get_first_approver(og_so.project_code, _MODULE)

        if not first_level:
            og_so.workflow_status   = "Approved"
            og_so.locked            = True
            og_so.approved_by       = submitted_by
            og_so.submitted_at      = datetime.utcnow()
            og_so.final_approved_at = datetime.utcnow()
        else:
            og_so.workflow_status = f"Pending_L{first_level.level_no}"
            og_so.current_level   = first_level.level_no
            og_so.locked          = True
            og_so.submitted_at    = datetime.utcnow()

        create_history(
            project_code=og_so.project_code,
            module_code=_MODULE,
            record_id=og_so.id,
            level_no=og_so.current_level,
            action="SUBMIT",
            action_by=submitted_by,
        )

        og_so.submitted_by = submitted_by
        og_so.updated_by   = submitted_by
        og_so.updated_at   = datetime.utcnow()

        db.session.commit()

        return res("OG Sale Order submitted", {
            "id":             og_so.id,
            "ogSaleOrderNo":  og_so.og_sale_order_no,
            "workflowStatus": og_so.workflow_status,
        }, 200)

    except SQLAlchemyError as e:
        db.session.rollback()
        return res(str(e), [], 500)
    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 6. APPROVE
# ══════════════════════════════════════════════════════════════════

def approve_og_sale_order(so_id, approved_by, comments=None):
    try:
        og_so = OgSaleOrderMaster.query.get(so_id)
        if not og_so:
            return res("OG Sale Order not found", [], 404)
        if not og_so.workflow_status.startswith("Pending"):
            return res("OG Sale Order is not pending approval", [], 400)

        allowed = is_current_approver(
            og_so.project_code, _MODULE, og_so.current_level, approved_by
        )
        if not allowed:
            return res("You are not the current approver", [], 403)

        next_level = get_next_approver(og_so.project_code, _MODULE, og_so.current_level)

        if next_level:
            create_history(
                project_code=og_so.project_code, module_code=_MODULE,
                record_id=og_so.id, level_no=og_so.current_level,
                action="APPROVE", action_by=approved_by, comments=comments,
            )
            og_so.current_level   = next_level.level_no
            og_so.workflow_status = f"Pending_L{next_level.level_no}"
        else:
            create_history(
                project_code=og_so.project_code, module_code=_MODULE,
                record_id=og_so.id, level_no=og_so.current_level,
                action="FINAL_APPROVE", action_by=approved_by, comments=comments,
            )
            og_so.workflow_status   = "Approved"
            og_so.locked            = True
            og_so.approved_by       = approved_by
            og_so.final_approved_at = datetime.utcnow()

        og_so.updated_by = approved_by
        og_so.updated_at = datetime.utcnow()

        db.session.commit()

        return res("OG Sale Order approved", {
            "id":             og_so.id,
            "workflowStatus": og_so.workflow_status,
            "currentLevel":   og_so.current_level,
        }, 200)

    except SQLAlchemyError as e:
        db.session.rollback()
        return res(str(e), [], 500)
    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 7. REBACK
# ══════════════════════════════════════════════════════════════════

def reback_og_sale_order(so_id, reback_by, comments=None):
    try:
        og_so = OgSaleOrderMaster.query.get(so_id)
        if not og_so:
            return res("OG Sale Order not found", [], 404)
        if not og_so.workflow_status.startswith("Pending"):
            return res("OG Sale Order is not pending", [], 400)
        if not comments:
            return res("Comments required for reback", [], 400)

        allowed = is_current_approver(
            og_so.project_code, _MODULE, og_so.current_level, reback_by
        )
        if not allowed:
            return res("You are not the current approver", [], 403)

        og_so.workflow_status    = "Reback"
        og_so.locked             = False
        og_so.correction_sent_at = datetime.utcnow()
        og_so.updated_by         = reback_by
        og_so.updated_at         = datetime.utcnow()

        create_history(
            project_code=og_so.project_code, module_code=_MODULE,
            record_id=og_so.id, level_no=og_so.current_level,
            action="REBACK", action_by=reback_by, comments=comments,
        )

        db.session.commit()

        return res("OG Sale Order sent for correction", {
            "id":             og_so.id,
            "workflowStatus": og_so.workflow_status,
        }, 200)

    except SQLAlchemyError as e:
        db.session.rollback()
        return res(str(e), [], 500)
    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 8. REJECT
# ══════════════════════════════════════════════════════════════════

def reject_og_sale_order(so_id, rejected_by, comments=None):
    try:
        og_so = OgSaleOrderMaster.query.get(so_id)
        if not og_so:
            return res("OG Sale Order not found", [], 404)
        if not og_so.workflow_status.startswith("Pending"):
            return res("OG Sale Order is not pending", [], 400)
        if not comments:
            return res("Comments required for rejection", [], 400)

        allowed = is_current_approver(
            og_so.project_code, _MODULE, og_so.current_level, rejected_by
        )
        if not allowed:
            return res("You are not the current approver", [], 403)

        og_so.workflow_status = "Rejected"
        og_so.locked          = True
        og_so.rejected_at     = datetime.utcnow()
        og_so.rejected_by     = rejected_by
        og_so.status          = "Inactive"
        og_so.updated_by      = rejected_by
        og_so.updated_at      = datetime.utcnow()

        create_history(
            project_code=og_so.project_code, module_code=_MODULE,
            record_id=og_so.id, level_no=og_so.current_level,
            action="REJECT", action_by=rejected_by, comments=comments,
        )

        db.session.commit()

        return res("OG Sale Order rejected", {
            "id":             og_so.id,
            "workflowStatus": og_so.workflow_status,
        }, 200)

    except SQLAlchemyError as e:
        db.session.rollback()
        return res(str(e), [], 500)
    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 9. HISTORY
# ══════════════════════════════════════════════════════════════════

def get_og_sale_order_history(so_id):
    try:
        og_so = OgSaleOrderMaster.query.get(so_id)
        if not og_so:
            return res("OG Sale Order not found", [], 404)

        rows = get_history(_MODULE, og_so.id)

        history = []
        for row in rows:
            history.append({
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

        steps = get_approval_steps(og_so.project_code, _MODULE, og_so, rows)

        return res("History fetched", {
            "workflowStatus": og_so.workflow_status,
            "currentLevel":   og_so.current_level,
            "approvalSteps":  steps,
            "history":        history,
        }, 200)

    except Exception as e:
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 10. MY APPROVAL STATUS
# ══════════════════════════════════════════════════════════════════

def get_og_sale_order_my_approval_status(so_id, user_id):
    try:
        og_so = OgSaleOrderMaster.query.get(so_id)
        if not og_so:
            return res("OG Sale Order not found", [], 404)
        data = get_my_approval_status(og_so.project_code, _MODULE, og_so, user_id)
        return res("Approval status", data, 200)
    except Exception as e:
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 11. GET BY UUID  (public — no JWT)
# ══════════════════════════════════════════════════════════════════

def get_og_sale_order_by_uuid(so_uuid):
    try:
        og_so = OgSaleOrderMaster.query.filter_by(og_sale_order_uuid=so_uuid).first()
        if not og_so:
            return res("OG Sale Order not found", [], 404)
        return res("OG Sale Order details fetched", _build_detail_payload(og_so), 200)
    except Exception as e:
        return res(str(e), [], 500)
