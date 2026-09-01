from sqlalchemy.exc import SQLAlchemyError
from app.extensions import db
from datetime import datetime, date
from decimal import Decimal
import uuid as _uuid

from app.models.journalEntry import JournalEntryMaster, JournalEntryLine
from app.models.cc_code import CCCode
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

_MODULE = "journal"


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
        db.session.query(JournalEntryMaster.voucher_no)
        .order_by(JournalEntryMaster.id.desc())
        .with_for_update()
        .first()
    )
    num = 0
    if last and last[0] and last[0].startswith("JV"):
        try:
            num = int(last[0][2:])
        except Exception:
            num = 0
    return "JV" + str(num + 1).zfill(5)


def _build_line_payload(line):
    if line.account_type == "CC" and line.cc:
        account_id   = line.cc_id
        account_code = line.cc.cc_code
        account_name = line.cc.cc_name
    elif line.account_type == "Vendor" and line.vendor:
        account_id   = line.vendor_id
        account_code = line.vendor.ledger_code
        account_name = line.vendor.ledger_name
    else:
        account_id = account_code = account_name = None

    return {
        "id":             line.id,
        "slNo":           line.sl_no,
        "accountType":    line.account_type,
        "drCr":           line.dr_cr,
        "accountId":      account_id,
        "accountCode":    account_code,
        "accountName":    account_name,
        "openingBalance": float(line.opening_balance or 0),
        "debitAmount":    float(line.debit_amount    or 0),
        "creditAmount":   float(line.credit_amount   or 0),
        "closingBalance": float(line.closing_balance or 0),
    }


def _build_detail_payload(entry):
    return {
        "id":              entry.id,
        "voucherNo":       entry.voucher_no,
        "journalUuid":     entry.journal_uuid,
        "entryDate":       _fmt_date(entry.entry_date),
        "projectCode":     entry.project_code,
        "remarks":         entry.remarks,
        "totalDebit":      float(entry.total_debit  or 0),
        "totalCredit":     float(entry.total_credit or 0),
        "workflowStatus":  entry.workflow_status,
        "currentLevel":    entry.current_level,
        "locked":          entry.locked,
        "createdBy":       entry.creator.username   if entry.creator   else None,
        "createdAt":       _fmt_date(entry.created_at),
        "submittedBy":     entry.submitter.username if entry.submitter else None,
        "submittedAt":     _fmt_date(entry.submitted_at),
        "approvedBy":      entry.approver.username  if entry.approver  else None,
        "finalApprovedAt": _fmt_date(entry.final_approved_at),
        "rejectedBy":      entry.rejector.username  if entry.rejector  else None,
        "rejectedAt":      _fmt_date(entry.rejected_at),
        "lines":           [_build_line_payload(l) for l in entry.lines],
    }


# ══════════════════════════════════════════════════════════════════
# 1. CREATE
# ══════════════════════════════════════════════════════════════════

def create_journal_entry(data, user_id):
    try:
        project_code = data.get("projectCode")
        if not project_code:
            return res("projectCode required", [], 400)

        allowed = is_creator(project_code, _MODULE, user_id)
        if not allowed:
            return res("You are not authorized to create journal entries", [], 403)

        lines_data = data.get("lines", [])
        if len(lines_data) < 2:
            return res("At least one Dr and one Cr line required", [], 400)

        total_debit  = sum(Decimal(str(l.get("debitAmount")  or 0)) for l in lines_data)
        total_credit = sum(Decimal(str(l.get("creditAmount") or 0)) for l in lines_data)
        if total_debit != total_credit:
            return res("Total debit must equal total credit", [], 400)

        entry = JournalEntryMaster(
            voucher_no      = _generate_voucher_no(),
            journal_uuid    = str(_uuid.uuid4()),
            entry_date      = date.today(),
            project_code    = project_code,
            remarks         = data.get("remarks"),
            total_debit     = total_debit,
            total_credit    = total_credit,
            workflow_status = "Draft",
            current_level   = 0,
            locked          = False,
            created_by      = user_id,
        )
        db.session.add(entry)
        db.session.flush()

        for idx, row in enumerate(lines_data, start=1):
            opening = Decimal(str(row.get("openingBalance") or 0))
            debit   = Decimal(str(row.get("debitAmount")    or 0))
            credit  = Decimal(str(row.get("creditAmount")   or 0))
            closing = opening + credit - debit
            cc_id     = row.get("ccId")
            vendor_id = row.get("vendorId")
            acc_type  = "CC" if cc_id else "Vendor" if vendor_id else None
            db.session.add(JournalEntryLine(
                journal_id      = entry.id,
                sl_no           = row.get("slNo") or idx,
                account_type    = acc_type,
                dr_cr           = row.get("drCr"),
                cc_id           = cc_id,
                vendor_id       = vendor_id,
                opening_balance = opening,
                debit_amount    = debit,
                credit_amount   = credit,
                closing_balance = closing,
            ))

        db.session.commit()

        return res("Journal entry created", {
            "id":          entry.id,
            "voucherNo":   entry.voucher_no,
            "journalUuid": entry.journal_uuid,
        }, 201)

    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 2. LIST
# ══════════════════════════════════════════════════════════════════

def get_journal_entry_list(data):
    try:
        project_code = data.get("projectCode")
        if not project_code:
            return res("projectCode required", [], 400)

        query = JournalEntryMaster.query.filter(
            JournalEntryMaster.project_code == project_code
        )

        if data.get("workflowStatus"):
            query = query.filter(JournalEntryMaster.workflow_status == data["workflowStatus"])

        if data.get("search"):
            term = f"%{data['search']}%"
            query = query.filter(JournalEntryMaster.voucher_no.ilike(term))

        if data.get("fromDate"):
            query = query.filter(JournalEntryMaster.entry_date >= data["fromDate"])

        if data.get("toDate"):
            query = query.filter(JournalEntryMaster.entry_date <= data["toDate"])

        rows = query.order_by(JournalEntryMaster.id.desc()).all()

        result = [
            {
                "id":             r.id,
                "voucherNo":      r.voucher_no,
                "entryDate":      _fmt_date(r.entry_date),
                "totalDebit":     float(r.total_debit  or 0),
                "totalCredit":    float(r.total_credit or 0),
                "workflowStatus": r.workflow_status,
                "createdBy":      r.creator.username if r.creator else None,
                "createdAt":      _fmt_date(r.created_at),
            }
            for r in rows
        ]

        return res("Journal entry list fetched", {"list": result}, 200)

    except Exception as e:
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 3. GET BY ID
# ══════════════════════════════════════════════════════════════════

def get_journal_entry_details(entry_id):
    try:
        entry = JournalEntryMaster.query.get(entry_id)
        if not entry:
            return res("Journal entry not found", [], 404)
        return res("Journal entry fetched", _build_detail_payload(entry), 200)
    except Exception as e:
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 4. GET BY UUID (public)
# ══════════════════════════════════════════════════════════════════

def get_journal_entry_by_uuid(entry_uuid):
    try:
        entry = JournalEntryMaster.query.filter_by(journal_uuid=entry_uuid).first()
        if not entry:
            return res("Journal entry not found", [], 404)
        return res("Journal entry fetched", _build_detail_payload(entry), 200)
    except Exception as e:
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 5. EDIT
# ══════════════════════════════════════════════════════════════════

def edit_journal_entry(entry_id, data, user_id):
    try:
        entry = JournalEntryMaster.query.get(entry_id)
        if not entry:
            return res("Journal entry not found", [], 404)
        if entry.locked:
            return res("Journal entry is locked and cannot be edited", [], 400)
        if entry.workflow_status not in ("Draft", "Reback"):
            return res("Only Draft or Reback records can be edited", [], 400)

        allowed = is_creator(entry.project_code, _MODULE, user_id)
        if not allowed:
            return res("You are not authorized to edit this journal entry", [], 403)

        lines_data = data.get("lines", [])
        if len(lines_data) < 2:
            return res("At least one Dr and one Cr line required", [], 400)

        total_debit  = sum(Decimal(str(l.get("debitAmount")  or 0)) for l in lines_data)
        total_credit = sum(Decimal(str(l.get("creditAmount") or 0)) for l in lines_data)
        if total_debit != total_credit:
            return res("Total debit must equal total credit", [], 400)

        if data.get("remarks") is not None:
            entry.remarks = data["remarks"]

        JournalEntryLine.query.filter_by(journal_id=entry.id).delete()
        db.session.flush()

        for idx, row in enumerate(lines_data, start=1):
            opening = Decimal(str(row.get("openingBalance") or 0))
            debit   = Decimal(str(row.get("debitAmount")    or 0))
            credit  = Decimal(str(row.get("creditAmount")   or 0))
            closing = opening + credit - debit
            cc_id     = row.get("ccId")
            vendor_id = row.get("vendorId")
            acc_type  = "CC" if cc_id else "Vendor" if vendor_id else None
            db.session.add(JournalEntryLine(
                journal_id      = entry.id,
                sl_no           = row.get("slNo") or idx,
                account_type    = acc_type,
                dr_cr           = row.get("drCr"),
                cc_id           = cc_id,
                vendor_id       = vendor_id,
                opening_balance = opening,
                debit_amount    = debit,
                credit_amount   = credit,
                closing_balance = closing,
            ))

        entry.total_debit  = total_debit
        entry.total_credit = total_credit

        if entry.workflow_status == "Reback":
            entry.correction_sent_at = None

        entry.updated_by = user_id
        entry.updated_at = datetime.utcnow()

        db.session.commit()

        return res("Journal entry updated", {"id": entry.id, "voucherNo": entry.voucher_no}, 200)

    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 6. SUBMIT
# ══════════════════════════════════════════════════════════════════

def submit_journal_entry(entry_id, user_id):
    try:
        entry = JournalEntryMaster.query.get(entry_id)
        if not entry:
            return res("Journal entry not found", [], 404)
        if entry.workflow_status not in ("Draft", "Reback"):
            return res("Journal entry already submitted", [], 400)
        if not entry.lines:
            return res("Journal entry has no lines", [], 400)

        if entry.workflow_status == "Reback":
            entry.current_level = 0

        first_level = get_first_approver(entry.project_code, _MODULE)

        if not first_level:
            entry.workflow_status   = "Approved"
            entry.locked            = True
            entry.approved_by       = user_id
            entry.submitted_at      = datetime.utcnow()
            entry.final_approved_at = datetime.utcnow()
        else:
            entry.workflow_status = f"Pending_L{first_level.level_no}"
            entry.current_level   = first_level.level_no
            entry.locked          = True
            entry.submitted_at    = datetime.utcnow()

        create_history(
            project_code=entry.project_code,
            module_code=_MODULE,
            record_id=entry.id,
            level_no=entry.current_level,
            action="SUBMIT",
            action_by=user_id,
        )

        entry.submitted_by = user_id
        entry.updated_by   = user_id
        entry.updated_at   = datetime.utcnow()

        db.session.commit()

        return res("Journal entry submitted", {
            "id":             entry.id,
            "workflowStatus": entry.workflow_status,
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

def approve_journal_entry(entry_id, approved_by, comments=None):
    try:
        entry = JournalEntryMaster.query.get(entry_id)
        if not entry:
            return res("Journal entry not found", [], 404)
        if not entry.workflow_status.startswith("Pending"):
            return res("Journal entry is not pending approval", [], 400)

        allowed = is_current_approver(entry.project_code, _MODULE, entry.current_level, approved_by)
        if not allowed:
            return res("You are not the current approver", [], 403)

        gap = get_gap_level(entry.project_code, _MODULE, entry.current_level)
        if gap:
            return res(f"L{gap} is not assigned. Please assign it before approving.", [], 400)

        next_level = get_next_approver(entry.project_code, _MODULE, entry.current_level)

        if next_level:
            create_history(
                project_code=entry.project_code, module_code=_MODULE,
                record_id=entry.id, level_no=entry.current_level,
                action="APPROVE", action_by=approved_by, comments=comments,
            )
            entry.current_level   = next_level.level_no
            entry.workflow_status = f"Pending_L{next_level.level_no}"
        else:
            create_history(
                project_code=entry.project_code, module_code=_MODULE,
                record_id=entry.id, level_no=entry.current_level,
                action="FINAL_APPROVE", action_by=approved_by, comments=comments,
            )
            entry.workflow_status   = "Approved"
            entry.locked            = True
            entry.approved_by       = approved_by
            entry.final_approved_at = datetime.utcnow()

        entry.updated_by = approved_by
        entry.updated_at = datetime.utcnow()

        db.session.commit()

        return res("Journal entry approved", {
            "id":             entry.id,
            "workflowStatus": entry.workflow_status,
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

def reback_journal_entry(entry_id, reback_by, comments=None):
    try:
        entry = JournalEntryMaster.query.get(entry_id)
        if not entry:
            return res("Journal entry not found", [], 404)
        if not entry.workflow_status.startswith("Pending"):
            return res("Journal entry is not pending", [], 400)
        if not comments:
            return res("Comments required for reback", [], 400)

        allowed = is_current_approver(entry.project_code, _MODULE, entry.current_level, reback_by)
        if not allowed:
            return res("You are not the current approver", [], 403)

        entry.workflow_status    = "Reback"
        entry.locked             = False
        entry.correction_sent_at = datetime.utcnow()
        entry.updated_by         = reback_by
        entry.updated_at         = datetime.utcnow()

        create_history(
            project_code=entry.project_code, module_code=_MODULE,
            record_id=entry.id, level_no=entry.current_level,
            action="REBACK", action_by=reback_by, comments=comments,
        )

        db.session.commit()

        return res("Journal entry sent for correction", {
            "id":             entry.id,
            "workflowStatus": entry.workflow_status,
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

def reject_journal_entry(entry_id, rejected_by, comments=None):
    try:
        entry = JournalEntryMaster.query.get(entry_id)
        if not entry:
            return res("Journal entry not found", [], 404)
        if not entry.workflow_status.startswith("Pending"):
            return res("Journal entry is not pending", [], 400)
        if not comments:
            return res("Comments required for rejection", [], 400)

        allowed = is_current_approver(entry.project_code, _MODULE, entry.current_level, rejected_by)
        if not allowed:
            return res("You are not the current approver", [], 403)

        entry.workflow_status = "Rejected"
        entry.locked          = True
        entry.rejected_at     = datetime.utcnow()
        entry.rejected_by     = rejected_by
        entry.status          = "Inactive"
        entry.updated_by      = rejected_by
        entry.updated_at      = datetime.utcnow()

        create_history(
            project_code=entry.project_code, module_code=_MODULE,
            record_id=entry.id, level_no=entry.current_level,
            action="REJECT", action_by=rejected_by, comments=comments,
        )

        db.session.commit()

        return res("Journal entry rejected", {
            "id":             entry.id,
            "workflowStatus": entry.workflow_status,
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

def get_journal_entry_history(entry_id):
    try:
        entry = JournalEntryMaster.query.get(entry_id)
        if not entry:
            return res("Journal entry not found", [], 404)

        rows = get_history(_MODULE, entry.id)

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

        steps = get_approval_steps(entry.project_code, _MODULE, entry, rows)

        return res("History fetched", {
            "workflowStatus": entry.workflow_status,
            "currentLevel":   entry.current_level,
            "approvalSteps":  steps,
            "history":        history,
        }, 200)

    except Exception as e:
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 11. MY APPROVAL STATUS
# ══════════════════════════════════════════════════════════════════

def get_journal_entry_my_approval_status(entry_id, user_id):
    try:
        entry = JournalEntryMaster.query.get(entry_id)
        if not entry:
            return res("Journal entry not found", [], 404)
        data = get_my_approval_status(entry.project_code, _MODULE, entry, user_id)
        return res("Approval status", data, 200)
    except Exception as e:
        return res(str(e), [], 500)
