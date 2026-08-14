from decimal import Decimal
from sqlalchemy.exc import SQLAlchemyError
from app.extensions import db
from datetime import datetime, date
import uuid as _uuid

from app.models.purchaseVoucher import PurchaseVoucherMaster, PurchaseVoucherItem, PurchaseVoucherGst
from app.models.cc_code import CCCode
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

_MODULE = "purchases"


# ══════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════

def _fmt_date(d):
    if d is None:
        return None
    if isinstance(d, datetime):
        return d.strftime("%Y-%m-%d %H:%M")
    return d.strftime("%Y-%m-%d")


def _generate_voucher_no():
    last = (
        db.session.query(PurchaseVoucherMaster.voucher_no)
        .order_by(PurchaseVoucherMaster.id.desc())
        .with_for_update()
        .first()
    )
    num = 0
    if last:
        try:
            num = int(last[0])
        except Exception:
            num = 0
    return str(num + 1).zfill(3)


def _build_detail_payload(v):
    return {
        "id":                  v.id,
        "voucherNo":           v.voucher_no,
        "voucherUuid":         v.voucher_uuid,
        "processingDate":      _fmt_date(v.processing_date),
        "voucherDate":         _fmt_date(v.voucher_date),
        "vendorVoucherNo":     v.vendor_voucher_no,
        "projectCode":         v.project_code,
        "vendorId":            v.vendor_id,
        "vendorName":          v.vendor.ledger_name if v.vendor else None,
        "remarks":             v.remarks,
        "basicAmount":         float(v.basic_amount         or 0),
        "gstAmount":           float(v.gst_amount           or 0),
        "discount":            float(v.discount             or 0),
        "roundOff":            float(v.round_off            or 0),
        "totalInvoiceAmount":  float(v.total_invoice_amount or 0),
        "workflowStatus":      v.workflow_status,
        "currentLevel":        v.current_level,
        "locked":              v.locked,
        "createdBy":           v.creator.username   if v.creator   else None,
        "createdAt":           _fmt_date(v.created_at),
        "submittedBy":         v.submitter.username if v.submitter else None,
        "submittedAt":         _fmt_date(v.submitted_at),
        "approvedBy":          v.approver.username  if v.approver  else None,
        "finalApprovedAt":     _fmt_date(v.final_approved_at),
        "rejectedBy":          v.rejector.username  if v.rejector  else None,
        "rejectedAt":          _fmt_date(v.rejected_at),
        "items": [
            {
                "id":          i.id,
                "slNo":        i.sl_no,
                "ccCodeId":    i.cc_code_id,
                "ccCode":      i.cc_code_rel.cc_code if i.cc_code_rel else None,
                "ccName":      i.cc_code_rel.cc_name if i.cc_code_rel else None,
                "description": i.description,
                "basicAmount": float(i.basic_amount or 0),
            }
            for i in v.items
        ],
        "gstLines": [
            {
                "id":          g.id,
                "gstType":     g.gst_type,
                "ccCode":      g.cc_code,
                "ccName":      g.cc_name,
                "description": g.description,
                "percent":     float(g.percent    or 0),
                "gstAmount":   float(g.gst_amount or 0),
                "isSelected":  g.is_selected,
            }
            for g in v.gst_lines
        ],
    }


# ══════════════════════════════════════════════════════════════════
# 1. CREATE
# ══════════════════════════════════════════════════════════════════

def create_purchase_voucher(data, user_id):
    try:
        project_code = data.get("projectCode")
        if not project_code:
            return res("projectCode required", [], 400)

        vendor_id = data.get("vendorId")
        if not vendor_id:
            return res("vendorId required", [], 400)

        allowed = is_creator(project_code, _MODULE, user_id)
        if not allowed:
            return res("You are not authorized to create purchase vouchers", [], 403)

        items = data.get("items", [])
        if not items:
            return res("At least one BASIC item required", [], 400)

        gst_lines = data.get("gstLines", [])

        basic_total = sum(Decimal(str(i.get("basicAmount") or 0)) for i in items)
        gst_total   = sum(
            (basic_total * Decimal(str(g.get("percent") or 0)) / 100).quantize(Decimal("0.01"))
            for g in gst_lines if g.get("isSelected")
        )
        discount  = Decimal(str(data.get("discount")  or 0))
        round_off = Decimal(str(data.get("roundOff")  or 0))
        total     = basic_total + gst_total - discount + round_off

        voucher_no   = _generate_voucher_no()
        voucher_uuid = str(_uuid.uuid4())

        v = PurchaseVoucherMaster(
            voucher_no        = voucher_no,
            voucher_uuid      = voucher_uuid,
            processing_date   = data.get("processingDate") or date.today(),
            voucher_date      = data.get("voucherDate"),
            vendor_voucher_no = data.get("vendorVoucherNo"),
            project_code      = project_code,
            vendor_id         = int(vendor_id),
            remarks           = data.get("remarks"),
            basic_amount         = basic_total,
            gst_amount           = gst_total,
            discount             = discount,
            round_off            = round_off,
            total_invoice_amount = total,
            workflow_status = "Draft",
            current_level   = 0,
            locked          = False,
            created_by      = user_id,
        )
        db.session.add(v)
        db.session.flush()

        for idx, row in enumerate(items, start=1):
            db.session.add(PurchaseVoucherItem(
                voucher_id   = v.id,
                sl_no        = row.get("slNo") or idx,
                cc_code_id   = row.get("ccCodeId"),
                description  = row.get("description"),
                basic_amount = Decimal(str(row.get("basicAmount") or 0)),
            ))

        for g in gst_lines:
            db.session.add(PurchaseVoucherGst(
                voucher_id  = v.id,
                gst_type    = g.get("gstType"),
                cc_code     = g.get("ccCode"),
                cc_name     = g.get("ccName"),
                description = g.get("description"),
                percent     = Decimal(str(g.get("percent")   or 0)),
                gst_amount  = (basic_total * Decimal(str(g.get("percent") or 0)) / 100).quantize(Decimal("0.01")) if g.get("isSelected") else Decimal("0"),
                is_selected = bool(g.get("isSelected")),
            ))

        db.session.commit()

        return res("Purchase voucher created", {
            "id":          v.id,
            "voucherNo":   v.voucher_no,
            "voucherUuid": v.voucher_uuid,
        }, 201)

    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 2. LIST
# ══════════════════════════════════════════════════════════════════

def get_purchase_voucher_list(data):
    try:
        project_code = data.get("projectCode")
        if not project_code:
            return res("projectCode required", [], 400)

        query = PurchaseVoucherMaster.query.filter(
            PurchaseVoucherMaster.project_code == project_code
        )

        if data.get("vendorId"):
            query = query.filter(PurchaseVoucherMaster.vendor_id == int(data.get("vendorId")))
        if data.get("workflowStatus"):
            query = query.filter(PurchaseVoucherMaster.workflow_status == data.get("workflowStatus"))
        if data.get("search"):
            term = f"%{data.get('search')}%"
            query = query.filter(
                db.or_(
                    PurchaseVoucherMaster.voucher_no.ilike(term),
                    PurchaseVoucherMaster.vendor_voucher_no.ilike(term),
                )
            )

        rows = query.order_by(PurchaseVoucherMaster.id.desc()).all()

        result = [
            {
                "id":                 r.id,
                "voucherNo":          r.voucher_no,
                "processingDate":     _fmt_date(r.processing_date),
                "voucherDate":        _fmt_date(r.voucher_date),
                "vendorVoucherNo":    r.vendor_voucher_no,
                "vendorId":           r.vendor_id,
                "vendorName":         r.vendor.ledger_name if r.vendor else None,
                "basicAmount":        float(r.basic_amount         or 0),
                "gstAmount":          float(r.gst_amount           or 0),
                "totalInvoiceAmount": float(r.total_invoice_amount or 0),
                "workflowStatus":     r.workflow_status,
                "createdBy":          r.creator.username if r.creator else None,
                "createdAt":          _fmt_date(r.created_at),
            }
            for r in rows
        ]

        return res("Purchase voucher list fetched", result, 200)

    except Exception as e:
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 3. DETAILS
# ══════════════════════════════════════════════════════════════════

def get_purchase_voucher_details(voucher_id):
    try:
        v = PurchaseVoucherMaster.query.get(voucher_id)
        if not v:
            return res("Purchase voucher not found", [], 404)
        return res("Purchase voucher details fetched", _build_detail_payload(v), 200)
    except Exception as e:
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 4. UUID LOOKUP
# ══════════════════════════════════════════════════════════════════

def get_purchase_voucher_by_uuid(voucher_uuid):
    try:
        v = PurchaseVoucherMaster.query.filter_by(voucher_uuid=voucher_uuid).first()
        if not v:
            return res("Purchase voucher not found", [], 404)
        return res("Purchase voucher details fetched", _build_detail_payload(v), 200)
    except Exception as e:
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 5. EDIT
# ══════════════════════════════════════════════════════════════════

def edit_purchase_voucher(voucher_id, data, user_id):
    try:
        v = PurchaseVoucherMaster.query.get(voucher_id)
        if not v:
            return res("Purchase voucher not found", [], 404)
        if v.locked:
            return res("Purchase voucher is locked and cannot be edited", [], 400)
        if v.workflow_status not in ("Draft", "Reback"):
            return res("Only Draft or Reback records can be edited", [], 400)

        allowed = is_creator(v.project_code, _MODULE, user_id)
        if not allowed:
            return res("You are not authorized to edit purchase vouchers", [], 403)

        items = data.get("items", [])
        if not items:
            return res("At least one BASIC item required", [], 400)

        gst_lines = data.get("gstLines", [])

        if data.get("voucherDate") is not None:
            v.voucher_date = data.get("voucherDate")
        if data.get("vendorVoucherNo") is not None:
            v.vendor_voucher_no = data.get("vendorVoucherNo")
        if data.get("remarks") is not None:
            v.remarks = data.get("remarks")

        PurchaseVoucherItem.query.filter_by(voucher_id=v.id).delete()
        PurchaseVoucherGst.query.filter_by(voucher_id=v.id).delete()
        db.session.flush()

        basic_total = sum(Decimal(str(i.get("basicAmount") or 0)) for i in items)
        gst_total   = sum(
            (basic_total * Decimal(str(g.get("percent") or 0)) / 100).quantize(Decimal("0.01"))
            for g in gst_lines if g.get("isSelected")
        )
        discount  = Decimal(str(data.get("discount")  or 0))
        round_off = Decimal(str(data.get("roundOff")  or 0))

        for idx, row in enumerate(items, start=1):
            db.session.add(PurchaseVoucherItem(
                voucher_id   = v.id,
                sl_no        = row.get("slNo") or idx,
                cc_code_id   = row.get("ccCodeId"),
                description  = row.get("description"),
                basic_amount = Decimal(str(row.get("basicAmount") or 0)),
            ))

        for g in gst_lines:
            db.session.add(PurchaseVoucherGst(
                voucher_id  = v.id,
                gst_type    = g.get("gstType"),
                cc_code     = g.get("ccCode"),
                cc_name     = g.get("ccName"),
                description = g.get("description"),
                percent     = Decimal(str(g.get("percent")   or 0)),
                gst_amount  = (basic_total * Decimal(str(g.get("percent") or 0)) / 100).quantize(Decimal("0.01")) if g.get("isSelected") else Decimal("0"),
                is_selected = bool(g.get("isSelected")),
            ))

        v.basic_amount         = basic_total
        v.gst_amount           = gst_total
        v.discount             = discount
        v.round_off            = round_off
        v.total_invoice_amount = basic_total + gst_total - discount + round_off

        if v.workflow_status == "Reback":
            v.correction_sent_at = None

        v.updated_by = user_id
        v.updated_at = datetime.utcnow()

        db.session.commit()

        return res("Purchase voucher updated", {"id": v.id, "voucherNo": v.voucher_no}, 200)

    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 6. SUBMIT
# ══════════════════════════════════════════════════════════════════

def submit_purchase_voucher(voucher_id, user_id):
    try:
        v = PurchaseVoucherMaster.query.get(voucher_id)
        if not v:
            return res("Purchase voucher not found", [], 404)
        if v.workflow_status not in ("Draft", "Reback"):
            return res("Purchase voucher already submitted", [], 400)
        if not v.items:
            return res("Purchase voucher has no items", [], 400)

        if v.workflow_status == "Reback":
            v.current_level = 0

        first_level = get_first_approver(v.project_code, _MODULE)

        if not first_level:
            v.workflow_status   = "Approved"
            v.locked            = True
            v.approved_by       = user_id
            v.submitted_at      = datetime.utcnow()
            v.final_approved_at = datetime.utcnow()
        else:
            v.workflow_status = f"Pending_L{first_level.level_no}"
            v.current_level   = first_level.level_no
            v.locked          = True
            v.submitted_at    = datetime.utcnow()

        create_history(
            project_code=v.project_code,
            module_code=_MODULE,
            record_id=v.id,
            level_no=v.current_level,
            action="SUBMIT",
            action_by=user_id,
        )

        v.submitted_by = user_id
        v.updated_by   = user_id
        v.updated_at   = datetime.utcnow()

        db.session.commit()

        return res("Purchase voucher submitted", {
            "id":             v.id,
            "workflowStatus": v.workflow_status,
        }, 200)

    except SQLAlchemyError as e:
        db.session.rollback()
        return res(str(e), [], 500)
    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 7. APPROVE
# ══════════════════════════════════════════════════════════════════

def approve_purchase_voucher(voucher_id, approved_by, comments=None):
    try:
        v = PurchaseVoucherMaster.query.get(voucher_id)
        if not v:
            return res("Purchase voucher not found", [], 404)
        if not v.workflow_status.startswith("Pending"):
            return res("Purchase voucher is not pending approval", [], 400)

        allowed = is_current_approver(v.project_code, _MODULE, v.current_level, approved_by)
        if not allowed:
            return res("You are not the current approver", [], 403)

        gap = get_gap_level(v.project_code, _MODULE, v.current_level)
        if gap:
            return res(f"L{gap} is not assigned. Please assign it before approving.", [], 400)

        next_level = get_next_approver(v.project_code, _MODULE, v.current_level)

        if next_level:
            create_history(
                project_code=v.project_code, module_code=_MODULE,
                record_id=v.id, level_no=v.current_level,
                action="APPROVE", action_by=approved_by, comments=comments,
            )
            v.current_level   = next_level.level_no
            v.workflow_status = f"Pending_L{next_level.level_no}"
        else:
            create_history(
                project_code=v.project_code, module_code=_MODULE,
                record_id=v.id, level_no=v.current_level,
                action="FINAL_APPROVE", action_by=approved_by, comments=comments,
            )
            v.workflow_status   = "Approved"
            v.locked            = True
            v.approved_by       = approved_by
            v.final_approved_at = datetime.utcnow()

        v.updated_by = approved_by
        v.updated_at = datetime.utcnow()

        db.session.commit()

        return res("Purchase voucher approved", {
            "id":             v.id,
            "workflowStatus": v.workflow_status,
        }, 200)

    except SQLAlchemyError as e:
        db.session.rollback()
        return res(str(e), [], 500)
    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 8. REBACK
# ══════════════════════════════════════════════════════════════════

def reback_purchase_voucher(voucher_id, reback_by, comments=None):
    try:
        v = PurchaseVoucherMaster.query.get(voucher_id)
        if not v:
            return res("Purchase voucher not found", [], 404)
        if not v.workflow_status.startswith("Pending"):
            return res("Purchase voucher is not pending", [], 400)
        if not comments:
            return res("Comments required for reback", [], 400)

        allowed = is_current_approver(v.project_code, _MODULE, v.current_level, reback_by)
        if not allowed:
            return res("You are not the current approver", [], 403)

        v.workflow_status    = "Reback"
        v.locked             = False
        v.correction_sent_at = datetime.utcnow()
        v.updated_by         = reback_by
        v.updated_at         = datetime.utcnow()

        create_history(
            project_code=v.project_code, module_code=_MODULE,
            record_id=v.id, level_no=v.current_level,
            action="REBACK", action_by=reback_by, comments=comments,
        )

        db.session.commit()

        return res("Purchase voucher sent for correction", {
            "id":             v.id,
            "workflowStatus": v.workflow_status,
        }, 200)

    except SQLAlchemyError as e:
        db.session.rollback()
        return res(str(e), [], 500)
    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 9. REJECT
# ══════════════════════════════════════════════════════════════════

def reject_purchase_voucher(voucher_id, rejected_by, comments=None):
    try:
        v = PurchaseVoucherMaster.query.get(voucher_id)
        if not v:
            return res("Purchase voucher not found", [], 404)
        if not v.workflow_status.startswith("Pending"):
            return res("Purchase voucher is not pending", [], 400)
        if not comments:
            return res("Comments required for rejection", [], 400)

        allowed = is_current_approver(v.project_code, _MODULE, v.current_level, rejected_by)
        if not allowed:
            return res("You are not the current approver", [], 403)

        v.workflow_status = "Rejected"
        v.locked          = True
        v.rejected_at     = datetime.utcnow()
        v.rejected_by     = rejected_by
        v.status          = "Inactive"
        v.updated_by      = rejected_by
        v.updated_at      = datetime.utcnow()

        create_history(
            project_code=v.project_code, module_code=_MODULE,
            record_id=v.id, level_no=v.current_level,
            action="REJECT", action_by=rejected_by, comments=comments,
        )

        db.session.commit()

        return res("Purchase voucher rejected", {
            "id":             v.id,
            "workflowStatus": v.workflow_status,
        }, 200)

    except SQLAlchemyError as e:
        db.session.rollback()
        return res(str(e), [], 500)
    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 10. HISTORY
# ══════════════════════════════════════════════════════════════════

def get_purchase_voucher_history(voucher_id):
    try:
        v = PurchaseVoucherMaster.query.get(voucher_id)
        if not v:
            return res("Purchase voucher not found", [], 404)

        rows = get_history(_MODULE, v.id)

        history = [
            {
                "id":        r.id,
                "action":    r.action,
                "level":     r.level_no,
                "comments":  r.comments,
                "actionBy":  r.user.username if r.user else None,
                "createdAt": (
                    r.created_at.strftime("%Y-%m-%d %H:%M:%S")
                    if r.created_at else None
                ),
            }
            for r in rows
        ]

        steps = get_approval_steps(v.project_code, _MODULE, v, rows)

        return res("History fetched", {
            "workflowStatus": v.workflow_status,
            "currentLevel":   v.current_level,
            "approvalSteps":  steps,
            "history":        history,
        }, 200)

    except Exception as e:
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 11. MY APPROVAL STATUS
# ══════════════════════════════════════════════════════════════════

def get_purchase_voucher_my_approval_status(voucher_id, user_id):
    try:
        v = PurchaseVoucherMaster.query.get(voucher_id)
        if not v:
            return res("Purchase voucher not found", [], 404)
        data = get_my_approval_status(v.project_code, _MODULE, v, user_id)
        return res("Approval status", data, 200)
    except Exception as e:
        return res(str(e), [], 500)
