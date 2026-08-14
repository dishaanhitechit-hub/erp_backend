from decimal import Decimal
from sqlalchemy.exc import SQLAlchemyError
from app.extensions import db
from datetime import datetime, date
import uuid as _uuid

from app.models.debitNote import DebitNoteMaster, DebitNoteItem, DebitNoteGst
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

_MODULE = "debit_note"


def _fmt_date(d):
    if d is None:
        return None
    if isinstance(d, datetime):
        return d.strftime("%Y-%m-%d %H:%M")
    return d.strftime("%Y-%m-%d")


def _parse_date(s):
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except Exception:
        return None


def _generate_dn_no():
    last = (
        db.session.query(DebitNoteMaster.debit_note_no)
        .order_by(DebitNoteMaster.id.desc())
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


def _build_dn_payload(dn):
    return {
        "id":              dn.id,
        "debitNoteNo":     dn.debit_note_no,
        "debitNoteUuid":   dn.debit_note_uuid,
        "entryDate":       _fmt_date(dn.entry_date),
        "projectCode":     dn.project_code,
        "billNumber":      dn.bill_number,
        "billDate":        _fmt_date(dn.bill_date),
        "orderNumber":     dn.order_number,
        "orderDate":       _fmt_date(dn.order_date),
        "vendorName":      dn.vendor_name,
        "vendorGstn":      dn.vendor_gstn,
        "creditNoteNo":    dn.credit_note_no,
        "creditNoteDate":  _fmt_date(dn.credit_note_date),
        "basicAmount":     float(dn.basic_amount or 0),
        "gstAmount":       float(dn.gst_amount   or 0),
        "totalAmount":     float(dn.total_amount  or 0),
        "remarks":         dn.remarks,
        "workflowStatus":  dn.workflow_status,
        "currentLevel":    dn.current_level,
        "locked":          dn.locked,
        "createdBy":       dn.creator.username   if dn.creator   else None,
        "createdAt":       _fmt_date(dn.created_at),
        "submittedBy":     dn.submitter.username if dn.submitter else None,
        "submittedAt":     _fmt_date(dn.submitted_at),
        "approvedBy":      dn.approver.username  if dn.approver  else None,
        "finalApprovedAt": _fmt_date(dn.final_approved_at),
        "rejectedBy":      dn.rejector.username  if dn.rejector  else None,
        "rejectedAt":      _fmt_date(dn.rejected_at),
        "items": [
            {
                "id":          i.id,
                "slNo":        i.sl_no,
                "ccCode":      i.cc_code,
                "ccName":      i.cc_name,
                "description": i.description,
                "basicAmount": float(i.basic_amount or 0),
                "gstPercent":  float(i.gst_percent  or 0),
                "totalAmount": float(i.total_amount  or 0),
            }
            for i in dn.items
        ],
        "gstLines": [
            {
                "id":         g.id,
                "gstType":    g.gst_type,
                "ccCode":     g.cc_code,
                "ccName":     g.cc_name,
                "percent":    float(g.percent    or 0),
                "gstAmount":  float(g.gst_amount or 0),
                "isSelected": g.is_selected,
            }
            for g in dn.gst_lines
        ],
    }


# ══════════════════════════════════════════════════════════════════
# 1. CREATE
# ══════════════════════════════════════════════════════════════════

def create_debit_note(data, user_id):
    try:
        project_code = (data.get("projectCode") or "").strip()
        if not project_code:
            return res("projectCode required", [], 400)

        allowed = is_creator(project_code, _MODULE, user_id)
        if not allowed:
            return res("You are not authorized to create debit notes", [], 403)

        items     = data.get("items", [])
        gst_lines = data.get("gstLines", [])
        if not items:
            return res("At least one item required", [], 400)

        basic_total = sum(Decimal(str(i.get("basicAmount") or 0)) for i in items)
        gst_total   = sum(
            (basic_total * Decimal(str(g.get("percent") or 0)) / 100).quantize(Decimal("0.01"))
            for g in gst_lines if g.get("isSelected")
        )

        dn = DebitNoteMaster(
            debit_note_no    = _generate_dn_no(),
            debit_note_uuid  = str(_uuid.uuid4()),
            entry_date       = _parse_date(data.get("entryDate")) or date.today(),
            project_code     = project_code,
            bill_number      = data.get("billNumber"),
            bill_date        = _parse_date(data.get("billDate")),
            order_number     = data.get("orderNumber"),
            order_date       = _parse_date(data.get("orderDate")),
            vendor_id        = data.get("vendorId") or None,
            vendor_name      = data.get("vendorName"),
            vendor_gstn      = data.get("vendorGstn"),
            credit_note_no   = data.get("creditNoteNo"),
            credit_note_date = _parse_date(data.get("creditNoteDate")),
            basic_amount     = basic_total,
            gst_amount       = gst_total,
            total_amount     = basic_total + gst_total,
            remarks          = data.get("remarks"),
            workflow_status  = "Draft",
            current_level    = 0,
            locked           = False,
            created_by       = user_id,
        )
        db.session.add(dn)
        db.session.flush()

        for idx, row in enumerate(items, start=1):
            basic = Decimal(str(row.get("basicAmount") or 0))
            pct   = Decimal(str(row.get("gstPercent")  or 0))
            gst   = (basic * pct / 100).quantize(Decimal("0.01"))
            db.session.add(DebitNoteItem(
                debit_note_id = dn.id,
                sl_no         = row.get("slNo") or idx,
                cc_code       = row.get("ccCode"),
                cc_name       = row.get("ccName"),
                description   = row.get("description"),
                basic_amount  = basic,
                gst_percent   = pct,
                total_amount  = basic + gst,
            ))

        for g in gst_lines:
            db.session.add(DebitNoteGst(
                debit_note_id = dn.id,
                gst_type      = g.get("gstType"),
                cc_code       = g.get("ccCode"),
                cc_name       = g.get("ccName"),
                percent       = Decimal(str(g.get("percent")   or 0)),
                gst_amount    = (basic_total * Decimal(str(g.get("percent") or 0)) / 100).quantize(Decimal("0.01")) if g.get("isSelected") else Decimal("0"),
                is_selected   = bool(g.get("isSelected")),
            ))

        db.session.commit()

        return res("Debit note created", {
            "id":            dn.id,
            "debitNoteNo":   dn.debit_note_no,
            "debitNoteUuid": dn.debit_note_uuid,
        }, 201)

    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 2. LIST
# ══════════════════════════════════════════════════════════════════

def get_debit_note_list(data):
    try:
        project_code = data.get("projectCode")
        if not project_code:
            return res("projectCode required", [], 400)

        query = DebitNoteMaster.query.filter(
            DebitNoteMaster.project_code == project_code
        )

        if data.get("workflowStatus"):
            query = query.filter(DebitNoteMaster.workflow_status == data.get("workflowStatus"))
        if data.get("search"):
            term  = f"%{data.get('search')}%"
            query = query.filter(
                db.or_(
                    DebitNoteMaster.debit_note_no.ilike(term),
                    DebitNoteMaster.bill_number.ilike(term),
                    DebitNoteMaster.vendor_name.ilike(term),
                )
            )

        rows = query.order_by(DebitNoteMaster.id.desc()).all()

        result = [
            {
                "id":             r.id,
                "debitNoteNo":    r.debit_note_no,
                "entryDate":      _fmt_date(r.entry_date),
                "billNumber":     r.bill_number,
                "vendorName":     r.vendor_name,
                "basicAmount":    float(r.basic_amount or 0),
                "gstAmount":      float(r.gst_amount   or 0),
                "totalAmount":    float(r.total_amount  or 0),
                "workflowStatus": r.workflow_status,
                "createdBy":      r.creator.username if r.creator else None,
                "createdAt":      _fmt_date(r.created_at),
            }
            for r in rows
        ]

        return res("Debit note list fetched", result, 200)

    except Exception as e:
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 3. DETAILS
# ══════════════════════════════════════════════════════════════════

def get_debit_note_details(dn_id):
    try:
        dn = DebitNoteMaster.query.get(dn_id)
        if not dn:
            return res("Debit note not found", [], 404)
        return res("Debit note details fetched", _build_dn_payload(dn), 200)
    except Exception as e:
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 4. EDIT
# ══════════════════════════════════════════════════════════════════

def edit_debit_note(dn_id, data, user_id):
    try:
        dn = DebitNoteMaster.query.get(dn_id)
        if not dn:
            return res("Debit note not found", [], 404)
        if dn.locked:
            return res("Debit note is locked and cannot be edited", [], 400)
        if dn.workflow_status not in ("Draft", "Reback"):
            return res("Only Draft or Reback records can be edited", [], 400)

        allowed = is_creator(dn.project_code, _MODULE, user_id)
        if not allowed:
            return res("You are not authorized to edit this debit note", [], 403)

        items     = data.get("items", [])
        gst_lines = data.get("gstLines", [])
        if not items:
            return res("At least one item required", [], 400)

        date_fields = {"bill_date", "order_date", "credit_note_date", "entry_date"}
        for key, attr in [
            ("entryDate",      "entry_date"),
            ("billNumber",     "bill_number"),
            ("billDate",       "bill_date"),
            ("orderNumber",    "order_number"),
            ("orderDate",      "order_date"),
            ("vendorId",       "vendor_id"),
            ("vendorName",     "vendor_name"),
            ("vendorGstn",     "vendor_gstn"),
            ("creditNoteNo",   "credit_note_no"),
            ("creditNoteDate", "credit_note_date"),
            ("remarks",        "remarks"),
        ]:
            if data.get(key) is not None:
                val = _parse_date(data.get(key)) if attr in date_fields else (data.get(key) or None)
                setattr(dn, attr, val)

        DebitNoteItem.query.filter_by(debit_note_id=dn.id).delete()
        DebitNoteGst.query.filter_by(debit_note_id=dn.id).delete()
        db.session.flush()

        basic_total = Decimal("0")
        for idx, row in enumerate(items, start=1):
            basic = Decimal(str(row.get("basicAmount") or 0))
            pct   = Decimal(str(row.get("gstPercent")  or 0))
            gst   = (basic * pct / 100).quantize(Decimal("0.01"))
            basic_total += basic
            db.session.add(DebitNoteItem(
                debit_note_id = dn.id,
                sl_no         = row.get("slNo") or idx,
                cc_code       = row.get("ccCode"),
                cc_name       = row.get("ccName"),
                description   = row.get("description"),
                basic_amount  = basic,
                gst_percent   = pct,
                total_amount  = basic + gst,
            ))

        gst_total = Decimal("0")
        for g in gst_lines:
            pct = Decimal(str(g.get("percent") or 0))
            amt = (basic_total * pct / 100).quantize(Decimal("0.01")) if g.get("isSelected") else Decimal("0")
            gst_total += amt
            db.session.add(DebitNoteGst(
                debit_note_id = dn.id,
                gst_type      = g.get("gstType"),
                cc_code       = g.get("ccCode"),
                cc_name       = g.get("ccName"),
                percent       = Decimal(str(g.get("percent") or 0)),
                gst_amount    = amt,
                is_selected   = bool(g.get("isSelected")),
            ))

        dn.basic_amount = basic_total
        dn.gst_amount   = gst_total
        dn.total_amount = basic_total + gst_total

        if dn.workflow_status == "Reback":
            dn.correction_sent_at = None

        dn.updated_by = user_id
        dn.updated_at = datetime.utcnow()

        db.session.commit()
        return res("Debit note updated", {"id": dn.id, "debitNoteNo": dn.debit_note_no}, 200)

    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 5. SUBMIT
# ══════════════════════════════════════════════════════════════════

def submit_debit_note(dn_id, user_id):
    try:
        dn = DebitNoteMaster.query.get(dn_id)
        if not dn:
            return res("Debit note not found", [], 404)
        if dn.workflow_status not in ("Draft", "Reback"):
            return res("Debit note already submitted", [], 400)
        if not dn.items:
            return res("Debit note has no items", [], 400)

        if dn.workflow_status == "Reback":
            dn.current_level = 0

        first_level = get_first_approver(dn.project_code, _MODULE)

        if not first_level:
            dn.workflow_status   = "Approved"
            dn.locked            = True
            dn.approved_by       = user_id
            dn.submitted_at      = datetime.utcnow()
            dn.final_approved_at = datetime.utcnow()
        else:
            dn.workflow_status = f"Pending_L{first_level.level_no}"
            dn.current_level   = first_level.level_no
            dn.locked          = True
            dn.submitted_at    = datetime.utcnow()

        create_history(
            project_code = dn.project_code,
            module_code  = _MODULE,
            record_id    = dn.id,
            level_no     = dn.current_level,
            action       = "SUBMIT",
            action_by    = user_id,
        )

        dn.submitted_by = user_id
        dn.updated_by   = user_id
        dn.updated_at   = datetime.utcnow()

        db.session.commit()
        return res("Debit note submitted", {"id": dn.id, "workflowStatus": dn.workflow_status}, 200)

    except SQLAlchemyError as e:
        db.session.rollback()
        return res(str(e), [], 500)
    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 6. APPROVE
# ══════════════════════════════════════════════════════════════════

def approve_debit_note(dn_id, approved_by, comments=None):
    try:
        dn = DebitNoteMaster.query.get(dn_id)
        if not dn:
            return res("Debit note not found", [], 404)
        if not dn.workflow_status.startswith("Pending"):
            return res("Debit note is not pending approval", [], 400)

        allowed = is_current_approver(dn.project_code, _MODULE, dn.current_level, approved_by)
        if not allowed:
            return res("You are not the current approver", [], 403)

        gap = get_gap_level(dn.project_code, _MODULE, dn.current_level)
        if gap:
            return res(f"L{gap} is not assigned. Please assign it before approving.", [], 400)

        next_level = get_next_approver(dn.project_code, _MODULE, dn.current_level)

        if next_level:
            create_history(
                project_code=dn.project_code, module_code=_MODULE,
                record_id=dn.id, level_no=dn.current_level,
                action="APPROVE", action_by=approved_by, comments=comments,
            )
            dn.current_level   = next_level.level_no
            dn.workflow_status = f"Pending_L{next_level.level_no}"
        else:
            create_history(
                project_code=dn.project_code, module_code=_MODULE,
                record_id=dn.id, level_no=dn.current_level,
                action="FINAL_APPROVE", action_by=approved_by, comments=comments,
            )
            dn.workflow_status   = "Approved"
            dn.locked            = True
            dn.approved_by       = approved_by
            dn.final_approved_at = datetime.utcnow()

        dn.updated_by = approved_by
        dn.updated_at = datetime.utcnow()
        db.session.commit()

        return res("Debit note approved", {"id": dn.id, "workflowStatus": dn.workflow_status}, 200)

    except SQLAlchemyError as e:
        db.session.rollback()
        return res(str(e), [], 500)
    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 7. REBACK
# ══════════════════════════════════════════════════════════════════

def reback_debit_note(dn_id, reback_by, comments=None):
    try:
        dn = DebitNoteMaster.query.get(dn_id)
        if not dn:
            return res("Debit note not found", [], 404)
        if not dn.workflow_status.startswith("Pending"):
            return res("Debit note is not pending", [], 400)
        if not comments:
            return res("Comments required for reback", [], 400)

        allowed = is_current_approver(dn.project_code, _MODULE, dn.current_level, reback_by)
        if not allowed:
            return res("You are not the current approver", [], 403)

        dn.workflow_status    = "Reback"
        dn.locked             = False
        dn.correction_sent_at = datetime.utcnow()
        dn.updated_by         = reback_by
        dn.updated_at         = datetime.utcnow()

        create_history(
            project_code=dn.project_code, module_code=_MODULE,
            record_id=dn.id, level_no=dn.current_level,
            action="REBACK", action_by=reback_by, comments=comments,
        )

        db.session.commit()
        return res("Debit note sent for correction", {"id": dn.id, "workflowStatus": dn.workflow_status}, 200)

    except SQLAlchemyError as e:
        db.session.rollback()
        return res(str(e), [], 500)
    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 8. REJECT
# ══════════════════════════════════════════════════════════════════

def reject_debit_note(dn_id, rejected_by, comments=None):
    try:
        dn = DebitNoteMaster.query.get(dn_id)
        if not dn:
            return res("Debit note not found", [], 404)
        if not dn.workflow_status.startswith("Pending"):
            return res("Debit note is not pending", [], 400)
        if not comments:
            return res("Comments required for rejection", [], 400)

        allowed = is_current_approver(dn.project_code, _MODULE, dn.current_level, rejected_by)
        if not allowed:
            return res("You are not the current approver", [], 403)

        dn.workflow_status = "Rejected"
        dn.locked          = True
        dn.rejected_at     = datetime.utcnow()
        dn.rejected_by     = rejected_by
        dn.status          = "Inactive"
        dn.updated_by      = rejected_by
        dn.updated_at      = datetime.utcnow()

        create_history(
            project_code=dn.project_code, module_code=_MODULE,
            record_id=dn.id, level_no=dn.current_level,
            action="REJECT", action_by=rejected_by, comments=comments,
        )

        db.session.commit()
        return res("Debit note rejected", {"id": dn.id, "workflowStatus": dn.workflow_status}, 200)

    except SQLAlchemyError as e:
        db.session.rollback()
        return res(str(e), [], 500)
    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 9. HISTORY
# ══════════════════════════════════════════════════════════════════

def get_debit_note_history(dn_id):
    try:
        dn = DebitNoteMaster.query.get(dn_id)
        if not dn:
            return res("Debit note not found", [], 404)

        rows = get_history(_MODULE, dn.id)

        history = [
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

        steps = get_approval_steps(dn.project_code, _MODULE, dn, rows)

        return res("History fetched", {
            "workflowStatus": dn.workflow_status,
            "currentLevel":   dn.current_level,
            "approvalSteps":  steps,
            "history":        history,
        }, 200)

    except Exception as e:
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 10. MY APPROVAL STATUS
# ══════════════════════════════════════════════════════════════════

def get_dn_my_approval_status(dn_id, user_id):
    try:
        dn = DebitNoteMaster.query.get(dn_id)
        if not dn:
            return res("Debit note not found", [], 404)
        data = get_my_approval_status(dn.project_code, _MODULE, dn, user_id)
        return res("Approval status", data, 200)
    except Exception as e:
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 11. UUID LOOKUP
# ══════════════════════════════════════════════════════════════════

def get_debit_note_by_uuid(dn_uuid):
    try:
        dn = DebitNoteMaster.query.filter_by(debit_note_uuid=dn_uuid).first()
        if not dn:
            return res("Debit note not found", [], 404)
        return res("Debit note details fetched", _build_dn_payload(dn), 200)
    except Exception as e:
        return res(str(e), [], 500)
