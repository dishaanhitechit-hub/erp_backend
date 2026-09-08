import json
import math
from app.extensions import db
from datetime import datetime, date
from decimal import Decimal
import uuid as _uuid

from app.models.journalAccounting import PettyCashJournalAccounting, PettyCashJournalAccountingLine
from app.models.journalVoucher import PettyCashJournalVoucher, PettyCashJournalLine
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

_MODULE = "petty_cash"


# ══════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════

def _fmt(d):
    if d is None:
        return None
    if isinstance(d, datetime):
        return d.strftime("%Y-%m-%d %H:%M")
    return d.strftime("%Y-%m-%d")


def _parse_lines(data):
    lines = data.get("lines", [])
    if isinstance(lines, str):
        try:
            lines = json.loads(lines)
        except Exception:
            lines = []
    return lines


def _parse_int(val):
    try:
        return int(val) if val else None
    except Exception:
        return None


def _generate_voucher_no():
    last = (
        db.session.query(PettyCashJournalAccounting.voucher_no)
        .order_by(PettyCashJournalAccounting.id.desc())
        .with_for_update()
        .first()
    )
    num = 0
    if last and last[0] and last[0].startswith("JA"):
        try:
            num = int(last[0][2:])
        except Exception:
            num = 0
    return "JA" + str(num + 1).zfill(5)


def _build_line(line):
    return {
        "id":               line.id,
        "slNo":             line.sl_no,
        "journalLineId":    line.journal_line_id,
        "ccCode":           line.cc_code,
        "ccName":           line.cc_name,
        "shortDescription": line.short_description,
        "originalAmount":   float(line.original_amount or 0),
        "amount":           float(line.amount or 0),
    }


def _build_payload(ja):
    jv = ja.journal_voucher
    return {
        "id":                ja.id,
        "voucherNo":         ja.voucher_no,
        "voucherUuid":       ja.voucher_uuid,
        "voucherDate":       _fmt(ja.voucher_date),
        "projectCode":       ja.project_code,
        "totalAmount":       float(ja.total_amount or 0),
        "workflowStatus":    ja.workflow_status,
        "currentLevel":      ja.current_level,
        "locked":            ja.locked,
        "journalVoucherId":  ja.journal_voucher_id,
        "journalVoucherNo":  jv.voucher_no if jv else None,
        "fundSource":        jv.fund_source if jv else None,
        "createdBy":         ja.creator.username   if ja.creator   else None,
        "createdAt":         _fmt(ja.created_at),
        "submittedBy":       ja.submitter.username if ja.submitter else None,
        "submittedAt":       _fmt(ja.submitted_at),
        "approvedBy":        ja.approver.username  if ja.approver  else None,
        "finalApprovedAt":   _fmt(ja.final_approved_at),
        "rejectedBy":        ja.rejector.username  if ja.rejector  else None,
        "rejectedAt":        _fmt(ja.rejected_at),
        "lines":             [_build_line(l) for l in ja.lines],
    }


# ══════════════════════════════════════════════════════════════════
# 0. APPROVED JOURNAL VOUCHERS (source for selection)
# ══════════════════════════════════════════════════════════════════

def get_approved_vouchers(params):
    try:
        project_code = params.get("projectCode")
        if not project_code:
            return res("projectCode required", [], 400)

        # Already accounted voucher IDs (one-to-one)
        accounted_ids = {
            r[0]
            for r in db.session.query(PettyCashJournalAccounting.journal_voucher_id).all()
        }

        q = PettyCashJournalVoucher.query.filter(
            PettyCashJournalVoucher.project_code == project_code,
            PettyCashJournalVoucher.workflow_status == "Approved",
            PettyCashJournalVoucher.id.notin_(accounted_ids),
        ).order_by(PettyCashJournalVoucher.id.desc())

        vouchers = []
        for jv in q.all():
            vouchers.append({
                "journalVoucherId": jv.id,
                "voucherNo":        jv.voucher_no,
                "voucherDate":      _fmt(jv.voucher_date),
                "fundSource":       jv.fund_source,
                "totalAmount":      float(jv.total_amount or 0),
                "lines": [
                    {
                        "journalLineId":    ln.id,
                        "slNo":             ln.sl_no,
                        "ccCode":           ln.cc_code,
                        "ccName":           ln.cc_name,
                        "shortDescription": ln.short_description,
                        "amount":           float(ln.amount or 0),
                    }
                    for ln in jv.lines
                ],
            })

        return res("Approved journal vouchers fetched", {"vouchers": vouchers}, 200)
    except Exception as e:
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 1. CREATE
# ══════════════════════════════════════════════════════════════════

def create_journal_accounting(data, user_id):
    try:
        project_code       = data.get("projectCode")
        journal_voucher_id = _parse_int(data.get("journalVoucherId"))
        voucher_date       = data.get("voucherDate") or date.today().isoformat()
        lines_data         = _parse_lines(data)

        if not project_code:
            return res("projectCode required", [], 400)
        if not journal_voucher_id:
            return res("journalVoucherId required", [], 400)
        if not lines_data:
            return res("At least one line required", [], 400)

        jv = PettyCashJournalVoucher.query.get(journal_voucher_id)
        if not jv:
            return res("Journal voucher not found", [], 404)
        if jv.workflow_status != "Approved":
            return res("Only approved journal vouchers can be accounted", [], 400)

        # One-to-one guard
        existing = PettyCashJournalAccounting.query.filter_by(
            journal_voucher_id=journal_voucher_id
        ).first()
        if existing:
            return res("This journal voucher is already accounted", [], 400)

        voucher_no   = _generate_voucher_no()
        voucher_uuid = str(_uuid.uuid4())

        ja = PettyCashJournalAccounting(
            voucher_no         = voucher_no,
            voucher_uuid       = voucher_uuid,
            voucher_date       = voucher_date,
            journal_voucher_id = journal_voucher_id,
            project_code       = project_code,
            workflow_status    = "Draft",
            current_level      = 0,
            locked             = False,
            created_by         = user_id,
        )
        db.session.add(ja)
        db.session.flush()

        total = Decimal(0)
        for idx, ld in enumerate(lines_data, start=1):
            journal_line_id = _parse_int(ld.get("journalLineId"))
            amount          = Decimal(str(ld.get("amount", 0) or 0))
            orig_amount     = Decimal(str(ld.get("originalAmount", amount) or amount))

            jl = PettyCashJournalLine.query.get(journal_line_id) if journal_line_id else None

            line = PettyCashJournalAccountingLine(
                journal_accounting_id = ja.id,
                journal_line_id       = journal_line_id,
                sl_no                 = ld.get("slNo", idx),
                cc_code               = ld.get("ccCode") or (jl.cc_code if jl else None),
                cc_name               = ld.get("ccName") or (jl.cc_name if jl else None),
                short_description     = ld.get("shortDescription") or (jl.short_description if jl else None),
                original_amount       = orig_amount,
                amount                = amount,
            )
            db.session.add(line)
            total += amount

        ja.total_amount = total
        db.session.commit()

        return res("Journal accounting created", {"id": ja.id, "voucherNo": ja.voucher_no, "voucherUuid": ja.voucher_uuid}, 201)
    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 2. LIST
# ══════════════════════════════════════════════════════════════════

def get_journal_accounting_list(params):
    try:
        project_code    = params.get("projectCode")
        page            = int(params.get("page", 1))
        page_size       = int(params.get("pageSize", 10))
        status_filter   = params.get("workflowStatus")
        fund_filter     = params.get("fundSource")

        q = PettyCashJournalAccounting.query
        if project_code:
            q = q.filter(PettyCashJournalAccounting.project_code == project_code)
        if status_filter:
            q = q.filter(PettyCashJournalAccounting.workflow_status == status_filter)
        if fund_filter:
            q = q.join(PettyCashJournalVoucher, PettyCashJournalAccounting.journal_voucher_id == PettyCashJournalVoucher.id)\
                 .filter(PettyCashJournalVoucher.fund_source == fund_filter)

        total = q.count()
        items = q.order_by(PettyCashJournalAccounting.id.desc())\
                 .offset((page - 1) * page_size).limit(page_size).all()

        lst = []
        for ja in items:
            jv = ja.journal_voucher
            lst.append({
                "id":               ja.id,
                "voucherNo":        ja.voucher_no,
                "voucherDate":      _fmt(ja.voucher_date),
                "journalVoucherNo": jv.voucher_no if jv else None,
                "fundSource":       jv.fund_source if jv else None,
                "totalAmount":      float(ja.total_amount or 0),
                "workflowStatus":   ja.workflow_status,
                "createdBy":        ja.creator.username if ja.creator else None,
                "createdAt":        _fmt(ja.created_at),
            })

        return res("Journal accounting list fetched", {
            "list": lst,
            "pagination": {
                "page": page,
                "pageSize": page_size,
                "total": total,
                "totalPages": math.ceil(total / page_size) if page_size else 1,
            },
        }, 200)
    except Exception as e:
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 3. DETAIL
# ══════════════════════════════════════════════════════════════════

def get_journal_accounting_detail(accounting_id):
    try:
        ja = PettyCashJournalAccounting.query.get(accounting_id)
        if not ja:
            return res("Journal accounting not found", [], 404)
        return res("Journal accounting fetched", _build_payload(ja), 200)
    except Exception as e:
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 3b. GET BY UUID (no auth)
# ══════════════════════════════════════════════════════════════════

def get_journal_accounting_by_uuid(voucher_uuid):
    try:
        ja = PettyCashJournalAccounting.query.filter_by(voucher_uuid=voucher_uuid).first()
        if not ja:
            return res("Journal accounting not found", [], 404)
        return res("Journal accounting fetched", _build_payload(ja), 200)
    except Exception as e:
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 4. EDIT
# ══════════════════════════════════════════════════════════════════

def edit_journal_accounting(accounting_id, data, user_id):
    try:
        ja = PettyCashJournalAccounting.query.get(accounting_id)
        if not ja:
            return res("Journal accounting not found", [], 404)
        if ja.workflow_status not in ("Draft", "Reback"):
            return res("Can only edit Draft or Reback vouchers", [], 400)
        if not is_creator(ja.project_code, _MODULE, user_id):
            return res("Not authorized", [], 403)

        lines_data   = _parse_lines(data)
        voucher_date = data.get("voucherDate") or ja.voucher_date

        if not lines_data:
            return res("At least one line required", [], 400)

        # Replace lines
        PettyCashJournalAccountingLine.query.filter_by(journal_accounting_id=ja.id).delete()

        total = Decimal(0)
        for idx, ld in enumerate(lines_data, start=1):
            journal_line_id = _parse_int(ld.get("journalLineId"))
            amount          = Decimal(str(ld.get("amount", 0) or 0))
            orig_amount     = Decimal(str(ld.get("originalAmount", amount) or amount))
            jl              = PettyCashJournalLine.query.get(journal_line_id) if journal_line_id else None

            line = PettyCashJournalAccountingLine(
                journal_accounting_id = ja.id,
                journal_line_id       = journal_line_id,
                sl_no                 = ld.get("slNo", idx),
                cc_code               = ld.get("ccCode") or (jl.cc_code if jl else None),
                cc_name               = ld.get("ccName") or (jl.cc_name if jl else None),
                short_description     = ld.get("shortDescription") or (jl.short_description if jl else None),
                original_amount       = orig_amount,
                amount                = amount,
            )
            db.session.add(line)
            total += amount

        ja.voucher_date  = voucher_date
        ja.total_amount  = total
        ja.updated_by    = user_id
        db.session.commit()

        return res("Journal accounting updated", {"id": ja.id}, 200)
    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 5. SUBMIT
# ══════════════════════════════════════════════════════════════════

def submit_journal_accounting(accounting_id, user_id):
    try:
        ja = PettyCashJournalAccounting.query.get(accounting_id)
        if not ja:
            return res("Journal accounting not found", [], 404)
        if ja.workflow_status not in ("Draft", "Reback"):
            return res("Only Draft or Reback vouchers can be submitted", [], 400)
        if not is_creator(ja.project_code, _MODULE, user_id):
            return res("Not authorized", [], 403)

        first = get_first_approver(ja.project_code, _MODULE)
        if not first:
            return res("No approver configured", [], 400)

        ja.workflow_status = "Pending_L1"
        ja.current_level   = 1
        ja.submitted_by    = user_id
        ja.submitted_at    = datetime.utcnow()
        create_history(project_code=ja.project_code, module_code=_MODULE, record_id=ja.id, level_no=0, action="SUBMIT", action_by=user_id)
        db.session.commit()

        return res("Submitted", {}, 200)
    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 6. APPROVE
# ══════════════════════════════════════════════════════════════════

def approve_journal_accounting(accounting_id, user_id, comments=None):
    try:
        ja = PettyCashJournalAccounting.query.get(accounting_id)
        if not ja:
            return res("Journal accounting not found", [], 404)
        if not ja.workflow_status.startswith("Pending"):
            return res("Not pending approval", [], 400)
        if not is_current_approver(ja.project_code, _MODULE, ja.current_level, user_id):
            return res("Not authorized to approve at this level", [], 403)

        nxt = get_next_approver(ja.project_code, _MODULE, ja.current_level)
        if nxt:
            gap = get_gap_level(ja.project_code, _MODULE, ja.current_level)
            ja.workflow_status = f"Pending_L{ja.current_level + gap}"
            ja.current_level   = ja.current_level + gap
            create_history(project_code=ja.project_code, module_code=_MODULE, record_id=ja.id, level_no=ja.current_level - gap, action="APPROVE", action_by=user_id, comments=comments)
        else:
            ja.workflow_status   = "Approved"
            ja.approved_by       = user_id
            ja.final_approved_at = datetime.utcnow()
            ja.locked            = True
            create_history(project_code=ja.project_code, module_code=_MODULE, record_id=ja.id, level_no=ja.current_level, action="FINAL_APPROVE", action_by=user_id, comments=comments)

        db.session.commit()
        return res("Approved", {}, 200)
    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 7. REBACK
# ══════════════════════════════════════════════════════════════════

def reback_journal_accounting(accounting_id, user_id, comments=None):
    try:
        ja = PettyCashJournalAccounting.query.get(accounting_id)
        if not ja:
            return res("Journal accounting not found", [], 404)
        if not ja.workflow_status.startswith("Pending"):
            return res("Not pending approval", [], 400)
        if not is_current_approver(ja.project_code, _MODULE, ja.current_level, user_id):
            return res("Not authorized", [], 403)
        if not comments:
            return res("Comments required for reback", [], 400)

        level = ja.current_level
        ja.workflow_status = "Reback"
        ja.current_level   = 0
        create_history(project_code=ja.project_code, module_code=_MODULE, record_id=ja.id, level_no=level, action="REBACK", action_by=user_id, comments=comments)
        db.session.commit()
        return res("Sent back for correction", {}, 200)
    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 8. REJECT
# ══════════════════════════════════════════════════════════════════

def reject_journal_accounting(accounting_id, user_id, comments=None):
    try:
        ja = PettyCashJournalAccounting.query.get(accounting_id)
        if not ja:
            return res("Journal accounting not found", [], 404)
        if not ja.workflow_status.startswith("Pending"):
            return res("Not pending approval", [], 400)
        if not is_current_approver(ja.project_code, _MODULE, ja.current_level, user_id):
            return res("Not authorized", [], 403)
        if not comments:
            return res("Comments required for rejection", [], 400)

        level = ja.current_level
        ja.workflow_status = "Rejected"
        ja.rejected_by     = user_id
        ja.rejected_at     = datetime.utcnow()
        create_history(project_code=ja.project_code, module_code=_MODULE, record_id=ja.id, level_no=level, action="REJECT", action_by=user_id, comments=comments)
        db.session.commit()
        return res("Rejected", {}, 200)
    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 9. HISTORY
# ══════════════════════════════════════════════════════════════════

def get_journal_accounting_history(accounting_id):
    try:
        ja = PettyCashJournalAccounting.query.get(accounting_id)
        if not ja:
            return res("Journal accounting not found", [], 404)

        history = get_history("PettyCashJournalAccounting", accounting_id)
        steps   = get_approval_steps(ja.project_code, _MODULE, ja, history)

        return res("History fetched", {
            "workflowStatus": ja.workflow_status,
            "currentLevel":   ja.current_level,
            "approvalSteps":  steps,
            "history":        history,
        }, 200)
    except Exception as e:
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 10. MY STATUS
# ══════════════════════════════════════════════════════════════════

def get_journal_accounting_my_status(accounting_id, user_id):
    try:
        ja = PettyCashJournalAccounting.query.get(accounting_id)
        if not ja:
            return res("Journal accounting not found", [], 404)

        status = get_my_approval_status(ja.project_code, _MODULE, ja, user_id)
        return res("My status fetched", status, 200)
    except Exception as e:
        return res(str(e), [], 500)
