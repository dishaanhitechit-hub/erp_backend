from decimal import Decimal
from sqlalchemy.exc import SQLAlchemyError
from app.extensions import db
from datetime import datetime, date
import uuid as _uuid

from app.models.creditNote import CreditNoteMaster, CreditNoteItem, CreditNoteGst
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

_MODULE = "credit_note"


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


def _generate_cn_no():
    last = (
        db.session.query(CreditNoteMaster.credit_note_no)
        .order_by(CreditNoteMaster.id.desc())
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


def _build_cn_payload(cn):
    return {
        "id":              cn.id,
        "creditNoteNo":    cn.credit_note_no,
        "creditNoteUuid":  cn.credit_note_uuid,
        "entryDate":       _fmt_date(cn.entry_date),
        "projectCode":     cn.project_code,
        "billNumber":      cn.bill_number,
        "billDate":        _fmt_date(cn.bill_date),
        "orderNumber":     cn.order_number,
        "orderDate":       _fmt_date(cn.order_date),
        "vendorName":      cn.vendor_name,
        "vendorGstn":      cn.vendor_gstn,
        "debitNoteNo":     cn.debit_note_no,
        "debitNoteDate":   _fmt_date(cn.debit_note_date),
        "basicAmount":     float(cn.basic_amount or 0),
        "gstAmount":       float(cn.gst_amount   or 0),
        "totalAmount":     float(cn.total_amount  or 0),
        "remarks":         cn.remarks,
        "workflowStatus":  cn.workflow_status,
        "currentLevel":    cn.current_level,
        "locked":          cn.locked,
        "createdBy":       cn.creator.username   if cn.creator   else None,
        "createdAt":       _fmt_date(cn.created_at),
        "submittedBy":     cn.submitter.username if cn.submitter else None,
        "submittedAt":     _fmt_date(cn.submitted_at),
        "approvedBy":      cn.approver.username  if cn.approver  else None,
        "finalApprovedAt": _fmt_date(cn.final_approved_at),
        "rejectedBy":      cn.rejector.username  if cn.rejector  else None,
        "rejectedAt":      _fmt_date(cn.rejected_at),
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
            for i in cn.items
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
            for g in cn.gst_lines
        ],
    }


# ══════════════════════════════════════════════════════════════════
# 1. CREATE
# ══════════════════════════════════════════════════════════════════

def create_credit_note(data, user_id):
    try:
        project_code = (data.get("projectCode") or "").strip()
        if not project_code:
            return res("projectCode required", [], 400)

        allowed = is_creator(project_code, _MODULE, user_id)
        if not allowed:
            return res("You are not authorized to create credit notes", [], 403)

        items     = data.get("items", [])
        gst_lines = data.get("gstLines", [])
        if not items:
            return res("At least one item required", [], 400)

        basic_total = sum(Decimal(str(i.get("basicAmount") or 0)) for i in items)
        gst_total   = sum(
            Decimal(str(g.get("gstAmount") or 0))
            for g in gst_lines if g.get("isSelected")
        )

        cn = CreditNoteMaster(
            credit_note_no   = _generate_cn_no(),
            credit_note_uuid = str(_uuid.uuid4()),
            entry_date       = _parse_date(data.get("entryDate")) or date.today(),
            project_code     = project_code,
            bill_number      = data.get("billNumber"),
            bill_date        = _parse_date(data.get("billDate")),
            order_number     = data.get("orderNumber"),
            order_date       = _parse_date(data.get("orderDate")),
            vendor_name      = data.get("vendorName"),
            vendor_gstn      = data.get("vendorGstn"),
            debit_note_no    = data.get("debitNoteNo"),
            debit_note_date  = _parse_date(data.get("debitNoteDate")),
            basic_amount     = basic_total,
            gst_amount       = gst_total,
            total_amount     = basic_total + gst_total,
            remarks          = data.get("remarks"),
            workflow_status  = "Draft",
            current_level    = 0,
            locked           = False,
            created_by       = user_id,
        )
        db.session.add(cn)
        db.session.flush()

        for idx, row in enumerate(items, start=1):
            basic = Decimal(str(row.get("basicAmount") or 0))
            pct   = Decimal(str(row.get("gstPercent")  or 0))
            gst   = (basic * pct / 100).quantize(Decimal("0.01"))
            db.session.add(CreditNoteItem(
                credit_note_id = cn.id,
                sl_no          = row.get("slNo") or idx,
                cc_code        = row.get("ccCode"),
                cc_name        = row.get("ccName"),
                description    = row.get("description"),
                basic_amount   = basic,
                gst_percent    = pct,
                total_amount   = basic + gst,
            ))

        for g in gst_lines:
            db.session.add(CreditNoteGst(
                credit_note_id = cn.id,
                gst_type       = g.get("gstType"),
                cc_code        = g.get("ccCode"),
                cc_name        = g.get("ccName"),
                percent        = Decimal(str(g.get("percent")   or 0)),
                gst_amount     = Decimal(str(g.get("gstAmount") or 0)) if g.get("isSelected") else Decimal("0"),
                is_selected    = bool(g.get("isSelected")),
            ))

        db.session.commit()

        return res("Credit note created", {
            "id":             cn.id,
            "creditNoteNo":   cn.credit_note_no,
            "creditNoteUuid": cn.credit_note_uuid,
        }, 201)

    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 2. LIST
# ══════════════════════════════════════════════════════════════════

def get_credit_note_list(data):
    try:
        project_code = data.get("projectCode")
        if not project_code:
            return res("projectCode required", [], 400)

        query = CreditNoteMaster.query.filter(
            CreditNoteMaster.project_code == project_code
        )

        if data.get("workflowStatus"):
            query = query.filter(CreditNoteMaster.workflow_status == data.get("workflowStatus"))
        if data.get("search"):
            term  = f"%{data.get('search')}%"
            query = query.filter(
                db.or_(
                    CreditNoteMaster.credit_note_no.ilike(term),
                    CreditNoteMaster.bill_number.ilike(term),
                    CreditNoteMaster.vendor_name.ilike(term),
                )
            )

        rows = query.order_by(CreditNoteMaster.id.desc()).all()

        result = [
            {
                "id":             r.id,
                "creditNoteNo":   r.credit_note_no,
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

        return res("Credit note list fetched", result, 200)

    except Exception as e:
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 3. DETAILS
# ══════════════════════════════════════════════════════════════════

def get_credit_note_details(cn_id):
    try:
        cn = CreditNoteMaster.query.get(cn_id)
        if not cn:
            return res("Credit note not found", [], 404)
        return res("Credit note details fetched", _build_cn_payload(cn), 200)
    except Exception as e:
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 4. EDIT
# ══════════════════════════════════════════════════════════════════

def edit_credit_note(cn_id, data, user_id):
    try:
        cn = CreditNoteMaster.query.get(cn_id)
        if not cn:
            return res("Credit note not found", [], 404)
        if cn.locked:
            return res("Credit note is locked and cannot be edited", [], 400)
        if cn.workflow_status not in ("Draft", "Reback"):
            return res("Only Draft or Reback records can be edited", [], 400)

        allowed = is_creator(cn.project_code, _MODULE, user_id)
        if not allowed:
            return res("You are not authorized to edit this credit note", [], 403)

        items     = data.get("items", [])
        gst_lines = data.get("gstLines", [])
        if not items:
            return res("At least one item required", [], 400)

        date_fields = {"bill_date", "order_date", "debit_note_date", "entry_date"}
        for key, attr in [
            ("entryDate",     "entry_date"),
            ("billNumber",    "bill_number"),
            ("billDate",      "bill_date"),
            ("orderNumber",   "order_number"),
            ("orderDate",     "order_date"),
            ("vendorName",    "vendor_name"),
            ("vendorGstn",    "vendor_gstn"),
            ("debitNoteNo",   "debit_note_no"),
            ("debitNoteDate", "debit_note_date"),
            ("remarks",       "remarks"),
        ]:
            if data.get(key) is not None:
                val = _parse_date(data.get(key)) if attr in date_fields else (data.get(key) or None)
                setattr(cn, attr, val)

        CreditNoteItem.query.filter_by(credit_note_id=cn.id).delete()
        CreditNoteGst.query.filter_by(credit_note_id=cn.id).delete()
        db.session.flush()

        basic_total = Decimal("0")
        for idx, row in enumerate(items, start=1):
            basic = Decimal(str(row.get("basicAmount") or 0))
            pct   = Decimal(str(row.get("gstPercent")  or 0))
            gst   = (basic * pct / 100).quantize(Decimal("0.01"))
            basic_total += basic
            db.session.add(CreditNoteItem(
                credit_note_id = cn.id,
                sl_no          = row.get("slNo") or idx,
                cc_code        = row.get("ccCode"),
                cc_name        = row.get("ccName"),
                description    = row.get("description"),
                basic_amount   = basic,
                gst_percent    = pct,
                total_amount   = basic + gst,
            ))

        gst_total = Decimal("0")
        for g in gst_lines:
            amt = Decimal(str(g.get("gstAmount") or 0)) if g.get("isSelected") else Decimal("0")
            gst_total += amt
            db.session.add(CreditNoteGst(
                credit_note_id = cn.id,
                gst_type       = g.get("gstType"),
                cc_code        = g.get("ccCode"),
                cc_name        = g.get("ccName"),
                percent        = Decimal(str(g.get("percent") or 0)),
                gst_amount     = amt,
                is_selected    = bool(g.get("isSelected")),
            ))

        cn.basic_amount = basic_total
        cn.gst_amount   = gst_total
        cn.total_amount = basic_total + gst_total

        if cn.workflow_status == "Reback":
            cn.correction_sent_at = None

        cn.updated_by = user_id
        cn.updated_at = datetime.utcnow()

        db.session.commit()
        return res("Credit note updated", {"id": cn.id, "creditNoteNo": cn.credit_note_no}, 200)

    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 5. SUBMIT
# ══════════════════════════════════════════════════════════════════

def submit_credit_note(cn_id, user_id):
    try:
        cn = CreditNoteMaster.query.get(cn_id)
        if not cn:
            return res("Credit note not found", [], 404)
        if cn.workflow_status not in ("Draft", "Reback"):
            return res("Credit note already submitted", [], 400)
        if not cn.items:
            return res("Credit note has no items", [], 400)

        if cn.workflow_status == "Reback":
            cn.current_level = 0

        first_level = get_first_approver(cn.project_code, _MODULE)

        if not first_level:
            cn.workflow_status   = "Approved"
            cn.locked            = True
            cn.approved_by       = user_id
            cn.submitted_at      = datetime.utcnow()
            cn.final_approved_at = datetime.utcnow()
        else:
            cn.workflow_status = f"Pending_L{first_level.level_no}"
            cn.current_level   = first_level.level_no
            cn.locked          = True
            cn.submitted_at    = datetime.utcnow()

        create_history(
            project_code = cn.project_code,
            module_code  = _MODULE,
            record_id    = cn.id,
            level_no     = cn.current_level,
            action       = "SUBMIT",
            action_by    = user_id,
        )

        cn.submitted_by = user_id
        cn.updated_by   = user_id
        cn.updated_at   = datetime.utcnow()

        db.session.commit()
        return res("Credit note submitted", {"id": cn.id, "workflowStatus": cn.workflow_status}, 200)

    except SQLAlchemyError as e:
        db.session.rollback()
        return res(str(e), [], 500)
    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 6. APPROVE
# ══════════════════════════════════════════════════════════════════

def approve_credit_note(cn_id, approved_by, comments=None):
    try:
        cn = CreditNoteMaster.query.get(cn_id)
        if not cn:
            return res("Credit note not found", [], 404)
        if not cn.workflow_status.startswith("Pending"):
            return res("Credit note is not pending approval", [], 400)

        allowed = is_current_approver(cn.project_code, _MODULE, cn.current_level, approved_by)
        if not allowed:
            return res("You are not the current approver", [], 403)

        gap = get_gap_level(cn.project_code, _MODULE, cn.current_level)
        if gap:
            return res(f"L{gap} is not assigned. Please assign it before approving.", [], 400)

        next_level = get_next_approver(cn.project_code, _MODULE, cn.current_level)

        if next_level:
            create_history(
                project_code=cn.project_code, module_code=_MODULE,
                record_id=cn.id, level_no=cn.current_level,
                action="APPROVE", action_by=approved_by, comments=comments,
            )
            cn.current_level   = next_level.level_no
            cn.workflow_status = f"Pending_L{next_level.level_no}"
        else:
            create_history(
                project_code=cn.project_code, module_code=_MODULE,
                record_id=cn.id, level_no=cn.current_level,
                action="FINAL_APPROVE", action_by=approved_by, comments=comments,
            )
            cn.workflow_status   = "Approved"
            cn.locked            = True
            cn.approved_by       = approved_by
            cn.final_approved_at = datetime.utcnow()

        cn.updated_by = approved_by
        cn.updated_at = datetime.utcnow()
        db.session.commit()

        return res("Credit note approved", {"id": cn.id, "workflowStatus": cn.workflow_status}, 200)

    except SQLAlchemyError as e:
        db.session.rollback()
        return res(str(e), [], 500)
    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 7. REBACK
# ══════════════════════════════════════════════════════════════════

def reback_credit_note(cn_id, reback_by, comments=None):
    try:
        cn = CreditNoteMaster.query.get(cn_id)
        if not cn:
            return res("Credit note not found", [], 404)
        if not cn.workflow_status.startswith("Pending"):
            return res("Credit note is not pending", [], 400)
        if not comments:
            return res("Comments required for reback", [], 400)

        allowed = is_current_approver(cn.project_code, _MODULE, cn.current_level, reback_by)
        if not allowed:
            return res("You are not the current approver", [], 403)

        cn.workflow_status    = "Reback"
        cn.locked             = False
        cn.correction_sent_at = datetime.utcnow()
        cn.updated_by         = reback_by
        cn.updated_at         = datetime.utcnow()

        create_history(
            project_code=cn.project_code, module_code=_MODULE,
            record_id=cn.id, level_no=cn.current_level,
            action="REBACK", action_by=reback_by, comments=comments,
        )

        db.session.commit()
        return res("Credit note sent for correction", {"id": cn.id, "workflowStatus": cn.workflow_status}, 200)

    except SQLAlchemyError as e:
        db.session.rollback()
        return res(str(e), [], 500)
    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 8. REJECT
# ══════════════════════════════════════════════════════════════════

def reject_credit_note(cn_id, rejected_by, comments=None):
    try:
        cn = CreditNoteMaster.query.get(cn_id)
        if not cn:
            return res("Credit note not found", [], 404)
        if not cn.workflow_status.startswith("Pending"):
            return res("Credit note is not pending", [], 400)
        if not comments:
            return res("Comments required for rejection", [], 400)

        allowed = is_current_approver(cn.project_code, _MODULE, cn.current_level, rejected_by)
        if not allowed:
            return res("You are not the current approver", [], 403)

        cn.workflow_status = "Rejected"
        cn.locked          = True
        cn.rejected_at     = datetime.utcnow()
        cn.rejected_by     = rejected_by
        cn.status          = "Inactive"
        cn.updated_by      = rejected_by
        cn.updated_at      = datetime.utcnow()

        create_history(
            project_code=cn.project_code, module_code=_MODULE,
            record_id=cn.id, level_no=cn.current_level,
            action="REJECT", action_by=rejected_by, comments=comments,
        )

        db.session.commit()
        return res("Credit note rejected", {"id": cn.id, "workflowStatus": cn.workflow_status}, 200)

    except SQLAlchemyError as e:
        db.session.rollback()
        return res(str(e), [], 500)
    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 9. HISTORY
# ══════════════════════════════════════════════════════════════════

def get_credit_note_history(cn_id):
    try:
        cn = CreditNoteMaster.query.get(cn_id)
        if not cn:
            return res("Credit note not found", [], 404)

        rows = get_history(_MODULE, cn.id)

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

        steps = get_approval_steps(cn.project_code, _MODULE, cn, rows)

        return res("History fetched", {
            "workflowStatus": cn.workflow_status,
            "currentLevel":   cn.current_level,
            "approvalSteps":  steps,
            "history":        history,
        }, 200)

    except Exception as e:
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 10. MY APPROVAL STATUS
# ══════════════════════════════════════════════════════════════════

def get_cn_my_approval_status(cn_id, user_id):
    try:
        cn = CreditNoteMaster.query.get(cn_id)
        if not cn:
            return res("Credit note not found", [], 404)
        data = get_my_approval_status(cn.project_code, _MODULE, cn, user_id)
        return res("Approval status", data, 200)
    except Exception as e:
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 11. UUID LOOKUP
# ══════════════════════════════════════════════════════════════════

def get_credit_note_by_uuid(cn_uuid):
    try:
        cn = CreditNoteMaster.query.filter_by(credit_note_uuid=cn_uuid).first()
        if not cn:
            return res("Credit note not found", [], 404)
        return res("Credit note details fetched", _build_cn_payload(cn), 200)
    except Exception as e:
        return res(str(e), [], 500)
