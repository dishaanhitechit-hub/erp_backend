import json
import math
from sqlalchemy.exc import SQLAlchemyError
from app.extensions import db
from datetime import datetime, date
from decimal import Decimal
import uuid as _uuid

from app.models.journalVoucher import PettyCashJournalVoucher, PettyCashJournalLine
from app.models.pettyCashDocketVoucher import PettyCashDocketVoucher, PettyCashDocketVoucherDetail
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
        db.session.query(PettyCashJournalVoucher.voucher_no)
        .order_by(PettyCashJournalVoucher.id.desc())
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


def _journalized_detail_ids():
    """All docket_detail_ids already assigned to any journal line (any status)."""
    rows = db.session.query(PettyCashJournalLine.docket_detail_id).all()
    return {r[0] for r in rows}


def _build_line(line):
    return {
        "id":               line.id,
        "slNo":             line.sl_no,
        "docketVoucherId":  line.docket_voucher_id,
        "docketDetailId":   line.docket_detail_id,
        "ccCode":           line.cc_code,
        "ccName":           line.cc_name,
        "shortDescription": line.short_description,
        "amount":           float(line.amount or 0),
    }


def _build_payload(jv):
    return {
        "id":               jv.id,
        "voucherNo":        jv.voucher_no,
        "voucherUuid":      jv.voucher_uuid,
        "voucherDate":      _fmt(jv.voucher_date),
        "fundSource":       jv.fund_source,
        "projectCode":      jv.project_code,
        "totalAmount":      float(jv.total_amount or 0),
        "workflowStatus":   jv.workflow_status,
        "currentLevel":     jv.current_level,
        "locked":           jv.locked,
        "createdBy":        jv.creator.username   if jv.creator   else None,
        "createdAt":        _fmt(jv.created_at),
        "submittedBy":      jv.submitter.username if jv.submitter else None,
        "submittedAt":      _fmt(jv.submitted_at),
        "approvedBy":       jv.approver.username  if jv.approver  else None,
        "finalApprovedAt":  _fmt(jv.final_approved_at),
        "rejectedBy":       jv.rejector.username  if jv.rejector  else None,
        "rejectedAt":       _fmt(jv.rejected_at),
        "lines":            [_build_line(l) for l in jv.lines],
    }


def _validate_lines(fund_source, lines_data):
    """Returns error string or None."""
    if not lines_data:
        return "At least one line required"

    docket_ids = {_parse_int(l.get("docketVoucherId")) for l in lines_data}
    detail_ids = [_parse_int(l.get("docketDetailId")) for l in lines_data]

    if None in docket_ids or None in detail_ids:
        return "Each line must have docketVoucherId and docketDetailId"

    if fund_source == "Bank":
        if len(docket_ids) > 1:
            return "Bank journal: only one docket voucher allowed"
        docket_id = list(docket_ids)[0]
        docket    = PettyCashDocketVoucher.query.get(docket_id)
        if not docket:
            return f"Docket voucher {docket_id} not found"
        all_ids   = {d.id for d in docket.details}
        submitted = set(detail_ids)
        if all_ids != submitted:
            return "Bank journal: all rows from the selected docket voucher must be included"

    if fund_source == "Cash":
        cc_codes = {l.get("ccCode") for l in lines_data}
        if len(cc_codes) > 1:
            return "Cash journal: all lines must belong to the same CC code"

    return None


# ══════════════════════════════════════════════════════════════════
# 0. AVAILABLE DOCKETS
# ══════════════════════════════════════════════════════════════════

def get_available_dockets(params):
    try:
        project_code = params.get("projectCode")
        fund_source  = params.get("fundSource")
        if not project_code:
            return res("projectCode required", [], 400)
        if not fund_source:
            return res("fundSource required", [], 400)

        used_ids = _journalized_detail_ids()

        dockets = (
            PettyCashDocketVoucher.query
            .filter_by(project_code=project_code, fund_source=fund_source, workflow_status="Approved")
            .order_by(PettyCashDocketVoucher.id.asc())
            .all()
        )

        result = []
        for docket in dockets:
            if fund_source == "Bank":
                # All rows must be un-journalized — no partial for bank
                if any(d.id in used_ids for d in docket.details):
                    continue
                available_rows = docket.details
            else:
                # Cash — show only un-journalized rows (partial OK)
                available_rows = [d for d in docket.details if d.id not in used_ids]

            if not available_rows:
                continue

            result.append({
                "docketVoucherId": docket.id,
                "voucherNo":       docket.voucher_no,
                "voucherDate":     _fmt(docket.voucher_date),
                "fundSource":      docket.fund_source,
                "totalAmount":     float(docket.total_amount or 0),
                "rows": [
                    {
                        "docketDetailId":   d.id,
                        "ccCode":           d.cc_code,
                        "ccName":           d.cc_name,
                        "shortDescription": d.short_description,
                        "amount":           float(d.amount or 0),
                    }
                    for d in available_rows
                ],
            })

        return res("Available dockets fetched", {"dockets": result}, 200)

    except Exception as e:
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 1. CREATE
# ══════════════════════════════════════════════════════════════════

def create_journal_voucher(data, user_id):
    try:
        project_code = data.get("projectCode")
        fund_source  = data.get("fundSource")
        if not project_code:
            return res("projectCode required", [], 400)
        if not fund_source:
            return res("fundSource required", [], 400)

        if not is_creator(project_code, _MODULE, user_id):
            return res("You are not authorized to create journal vouchers", [], 403)

        lines_data = _parse_lines(data)
        err = _validate_lines(fund_source, lines_data)
        if err:
            return res(err, [], 400)

        used_ids = _journalized_detail_ids()
        for l in lines_data:
            if _parse_int(l.get("docketDetailId")) in used_ids:
                return res(
                    f"Detail row {l.get('docketDetailId')} is already added in another journal",
                    [], 400,
                )

        total = sum(Decimal(str(l.get("amount") or 0)) for l in lines_data)

        jv = PettyCashJournalVoucher(
            voucher_uuid    = str(_uuid.uuid4()),
            voucher_no      = _generate_voucher_no(),
            voucher_date    = date.today(),
            fund_source     = fund_source,
            project_code    = project_code,
            total_amount    = total,
            workflow_status = "Draft",
            current_level   = 0,
            locked          = False,
            created_by      = user_id,
        )
        db.session.add(jv)
        db.session.flush()

        for idx, l in enumerate(lines_data, start=1):
            db.session.add(PettyCashJournalLine(
                journal_voucher_id = jv.id,
                docket_voucher_id  = _parse_int(l.get("docketVoucherId")),
                docket_detail_id   = _parse_int(l.get("docketDetailId")),
                sl_no              = l.get("slNo") or idx,
                cc_code            = l.get("ccCode"),
                cc_name            = l.get("ccName"),
                short_description  = l.get("shortDescription"),
                amount             = Decimal(str(l.get("amount") or 0)),
            ))

        db.session.commit()
        return res("Journal voucher created", {
            "id":          jv.id,
            "voucherNo":   jv.voucher_no,
            "voucherUuid": jv.voucher_uuid,
        }, 201)

    except SQLAlchemyError as e:
        db.session.rollback()
        return res(str(e), [], 500)
    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 2. LIST
# ══════════════════════════════════════════════════════════════════

def get_journal_voucher_list(params):
    try:
        project_code = params.get("projectCode")
        if not project_code:
            return res("projectCode required", [], 400)

        page      = max(1, int(params.get("page", 1) or 1))
        page_size = max(1, int(params.get("pageSize", 10) or 10))

        query = PettyCashJournalVoucher.query.filter_by(project_code=project_code)

        if params.get("workflowStatus"):
            query = query.filter(PettyCashJournalVoucher.workflow_status == params["workflowStatus"])
        if params.get("fundSource"):
            query = query.filter(PettyCashJournalVoucher.fund_source == params["fundSource"])

        total = query.count()
        rows  = (
            query.order_by(PettyCashJournalVoucher.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )

        result = [
            {
                "id":             r.id,
                "voucherNo":      r.voucher_no,
                "voucherDate":    _fmt(r.voucher_date),
                "fundSource":     r.fund_source,
                "totalAmount":    float(r.total_amount or 0),
                "workflowStatus": r.workflow_status,
                "createdBy":      r.creator.username if r.creator else None,
                "createdAt":      _fmt(r.created_at),
            }
            for r in rows
        ]

        return res("Journal voucher list fetched", {
            "list": result,
            "pagination": {
                "page":       page,
                "pageSize":   page_size,
                "total":      total,
                "totalPages": math.ceil(total / page_size) if page_size else 1,
            },
        }, 200)

    except Exception as e:
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 3. DETAIL
# ══════════════════════════════════════════════════════════════════

def get_journal_voucher_detail(journal_id):
    try:
        jv = PettyCashJournalVoucher.query.get(journal_id)
        if not jv:
            return res("Journal voucher not found", [], 404)
        return res("Journal voucher fetched", _build_payload(jv), 200)
    except Exception as e:
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 4. EDIT (Draft / Reback only)
# ══════════════════════════════════════════════════════════════════

def edit_journal_voucher(journal_id, data, user_id):
    try:
        jv = PettyCashJournalVoucher.query.get(journal_id)
        if not jv:
            return res("Journal voucher not found", [], 404)
        if jv.locked:
            return res("Journal voucher is locked", [], 400)
        if jv.workflow_status not in ("Draft", "Reback"):
            return res("Only Draft or Reback records can be edited", [], 400)
        if not is_creator(jv.project_code, _MODULE, user_id):
            return res("You are not authorized to edit this journal voucher", [], 403)

        lines_data = _parse_lines(data)
        err = _validate_lines(jv.fund_source, lines_data)
        if err:
            return res(err, [], 400)

        old_detail_ids = {l.docket_detail_id for l in jv.lines}
        used_ids       = _journalized_detail_ids()
        for l in lines_data:
            did = _parse_int(l.get("docketDetailId"))
            if did in used_ids and did not in old_detail_ids:
                return res(f"Detail row {did} is already added in another journal", [], 400)

        PettyCashJournalLine.query.filter_by(journal_voucher_id=jv.id).delete()
        db.session.flush()

        total = Decimal("0")
        for idx, l in enumerate(lines_data, start=1):
            amt = Decimal(str(l.get("amount") or 0))
            total += amt
            db.session.add(PettyCashJournalLine(
                journal_voucher_id = jv.id,
                docket_voucher_id  = _parse_int(l.get("docketVoucherId")),
                docket_detail_id   = _parse_int(l.get("docketDetailId")),
                sl_no              = l.get("slNo") or idx,
                cc_code            = l.get("ccCode"),
                cc_name            = l.get("ccName"),
                short_description  = l.get("shortDescription"),
                amount             = amt,
            ))

        jv.total_amount = total
        jv.updated_by   = user_id
        jv.updated_at   = datetime.utcnow()

        db.session.commit()
        return res("Journal voucher updated", {"id": jv.id, "voucherNo": jv.voucher_no}, 200)

    except SQLAlchemyError as e:
        db.session.rollback()
        return res(str(e), [], 500)
    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 5. SUBMIT
# ══════════════════════════════════════════════════════════════════

def submit_journal_voucher(journal_id, user_id):
    try:
        jv = PettyCashJournalVoucher.query.get(journal_id)
        if not jv:
            return res("Journal voucher not found", [], 404)
        if jv.workflow_status not in ("Draft", "Reback"):
            return res("Journal voucher already submitted", [], 400)
        if not jv.lines:
            return res("Journal voucher has no lines", [], 400)

        if jv.workflow_status == "Reback":
            jv.current_level = 0

        first_level = get_first_approver(jv.project_code, _MODULE)

        if not first_level:
            jv.workflow_status   = "Approved"
            jv.locked            = True
            jv.approved_by       = user_id
            jv.submitted_at      = datetime.utcnow()
            jv.final_approved_at = datetime.utcnow()
        else:
            jv.workflow_status = f"Pending_L{first_level.level_no}"
            jv.current_level   = first_level.level_no
            jv.locked          = True
            jv.submitted_at    = datetime.utcnow()

        create_history(
            project_code=jv.project_code, module_code=_MODULE,
            record_id=jv.id, level_no=jv.current_level,
            action="SUBMIT", action_by=user_id,
        )

        jv.submitted_by = user_id
        jv.updated_by   = user_id
        jv.updated_at   = datetime.utcnow()

        db.session.commit()
        return res("Journal voucher submitted", {"id": jv.id, "workflowStatus": jv.workflow_status}, 200)

    except SQLAlchemyError as e:
        db.session.rollback()
        return res(str(e), [], 500)
    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 6. APPROVE
# ══════════════════════════════════════════════════════════════════

def approve_journal_voucher(journal_id, approved_by, comments=None):
    try:
        jv = PettyCashJournalVoucher.query.get(journal_id)
        if not jv:
            return res("Journal voucher not found", [], 404)
        if not jv.workflow_status.startswith("Pending"):
            return res("Journal voucher is not pending approval", [], 400)

        if not is_current_approver(jv.project_code, _MODULE, jv.current_level, approved_by):
            return res("You are not the current approver", [], 403)

        gap = get_gap_level(jv.project_code, _MODULE, jv.current_level)
        if gap:
            return res(f"L{gap} is not assigned. Please assign it before approving.", [], 400)

        next_level = get_next_approver(jv.project_code, _MODULE, jv.current_level)

        if next_level:
            create_history(
                project_code=jv.project_code, module_code=_MODULE,
                record_id=jv.id, level_no=jv.current_level,
                action="APPROVE", action_by=approved_by, comments=comments,
            )
            jv.current_level   = next_level.level_no
            jv.workflow_status = f"Pending_L{next_level.level_no}"
        else:
            create_history(
                project_code=jv.project_code, module_code=_MODULE,
                record_id=jv.id, level_no=jv.current_level,
                action="FINAL_APPROVE", action_by=approved_by, comments=comments,
            )
            jv.workflow_status   = "Approved"
            jv.locked            = True
            jv.approved_by       = approved_by
            jv.final_approved_at = datetime.utcnow()

        jv.updated_by = approved_by
        jv.updated_at = datetime.utcnow()

        db.session.commit()
        return res("Journal voucher approved", {"id": jv.id, "workflowStatus": jv.workflow_status}, 200)

    except SQLAlchemyError as e:
        db.session.rollback()
        return res(str(e), [], 500)
    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 7. REBACK
# ══════════════════════════════════════════════════════════════════

def reback_journal_voucher(journal_id, reback_by, comments=None):
    try:
        jv = PettyCashJournalVoucher.query.get(journal_id)
        if not jv:
            return res("Journal voucher not found", [], 404)
        if not jv.workflow_status.startswith("Pending"):
            return res("Journal voucher is not pending", [], 400)
        if not comments:
            return res("Comments required for reback", [], 400)

        if not is_current_approver(jv.project_code, _MODULE, jv.current_level, reback_by):
            return res("You are not the current approver", [], 403)

        jv.workflow_status = "Reback"
        jv.locked          = False
        jv.updated_by      = reback_by
        jv.updated_at      = datetime.utcnow()

        create_history(
            project_code=jv.project_code, module_code=_MODULE,
            record_id=jv.id, level_no=jv.current_level,
            action="REBACK", action_by=reback_by, comments=comments,
        )

        db.session.commit()
        return res("Journal voucher sent for correction", {"id": jv.id, "workflowStatus": jv.workflow_status}, 200)

    except SQLAlchemyError as e:
        db.session.rollback()
        return res(str(e), [], 500)
    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 8. REJECT
# ══════════════════════════════════════════════════════════════════

def reject_journal_voucher(journal_id, rejected_by, comments=None):
    try:
        jv = PettyCashJournalVoucher.query.get(journal_id)
        if not jv:
            return res("Journal voucher not found", [], 404)
        if not jv.workflow_status.startswith("Pending"):
            return res("Journal voucher is not pending", [], 400)
        if not comments:
            return res("Comments required for rejection", [], 400)

        if not is_current_approver(jv.project_code, _MODULE, jv.current_level, rejected_by):
            return res("You are not the current approver", [], 403)

        jv.workflow_status = "Rejected"
        jv.locked          = True
        jv.rejected_at     = datetime.utcnow()
        jv.rejected_by     = rejected_by
        jv.updated_by      = rejected_by
        jv.updated_at      = datetime.utcnow()

        create_history(
            project_code=jv.project_code, module_code=_MODULE,
            record_id=jv.id, level_no=jv.current_level,
            action="REJECT", action_by=rejected_by, comments=comments,
        )

        db.session.commit()
        return res("Journal voucher rejected", {"id": jv.id, "workflowStatus": jv.workflow_status}, 200)

    except SQLAlchemyError as e:
        db.session.rollback()
        return res(str(e), [], 500)
    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 9. HISTORY
# ══════════════════════════════════════════════════════════════════

def get_journal_voucher_history(journal_id):
    try:
        jv = PettyCashJournalVoucher.query.get(journal_id)
        if not jv:
            return res("Journal voucher not found", [], 404)

        rows = get_history(_MODULE, jv.id)
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
        steps = get_approval_steps(jv.project_code, _MODULE, jv, rows)

        return res("History fetched", {
            "workflowStatus": jv.workflow_status,
            "currentLevel":   jv.current_level,
            "approvalSteps":  steps,
            "history":        history,
        }, 200)

    except Exception as e:
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 10. MY APPROVAL STATUS
# ══════════════════════════════════════════════════════════════════

def get_journal_voucher_my_status(journal_id, user_id):
    try:
        jv = PettyCashJournalVoucher.query.get(journal_id)
        if not jv:
            return res("Journal voucher not found", [], 404)
        data = get_my_approval_status(jv.project_code, _MODULE, jv, user_id)
        return res("Approval status", data, 200)
    except Exception as e:
        return res(str(e), [], 500)
