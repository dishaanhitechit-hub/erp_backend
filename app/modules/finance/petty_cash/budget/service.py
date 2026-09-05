import json
from sqlalchemy.exc import SQLAlchemyError
from app.extensions import db
from datetime import datetime, date
from decimal import Decimal
import uuid as _uuid

from app.models.pettyCashBudget import (
    PettyCashBudget,
    PettyCashBudgetDetail,
    PettyCashBudgetRevision,
)
from app.cloudinary_uploader import upload_file_to_bunny
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


def _parse_details(data):
    details = data.get("details", [])
    if isinstance(details, str):
        try:
            details = json.loads(details)
        except Exception:
            details = []
    return details


def _generate_budget_no():
    last = (
        db.session.query(PettyCashBudget.budget_no)
        .order_by(PettyCashBudget.id.desc())
        .with_for_update()
        .first()
    )
    num = 0
    if last and last[0] and last[0].startswith("PCB"):
        try:
            num = int(last[0][3:])
        except Exception:
            num = 0
    return "PCB" + str(num + 1).zfill(5)


def _build_detail_row(row):
    return {
        "id":               row.id,
        "slNo":             row.sl_no,
        "ccCode":           row.cc_code,
        "ccName":           row.cc_name,
        "shortDescription": row.short_description,
        "budgetAmount":     float(row.budget_amount or 0),
    }


def _build_payload(budget):
    return {
        "id":                 budget.id,
        "budgetNo":           budget.budget_no,
        "budgetUuid":         budget.budget_uuid,
        "budgetDate":         _fmt_date(budget.budget_date),
        "budgetFrequency":    budget.budget_frequency,
        "fromDate":           _fmt_date(budget.from_date),
        "toDate":             _fmt_date(budget.to_date),
        "attachment":         budget.attachment,
        "projectCode":        budget.project_code,
        "totalBudgetAmount":  float(budget.total_budget_amount or 0),
        "workflowStatus":     budget.workflow_status,
        "currentLevel":       budget.current_level,
        "locked":             budget.locked,
        "createdBy":          budget.creator.username   if budget.creator   else None,
        "createdAt":          _fmt_date(budget.created_at),
        "submittedBy":        budget.submitter.username if budget.submitter else None,
        "submittedAt":        _fmt_date(budget.submitted_at),
        "approvedBy":         budget.approver.username  if budget.approver  else None,
        "finalApprovedAt":    _fmt_date(budget.final_approved_at),
        "rejectedBy":         budget.rejector.username  if budget.rejector  else None,
        "rejectedAt":         _fmt_date(budget.rejected_at),
        "details":            [_build_detail_row(r) for r in budget.details],
    }


# ══════════════════════════════════════════════════════════════════
# 1. CREATE
# ══════════════════════════════════════════════════════════════════

def create_petty_cash_budget(data, user_id, files=None):
    try:
        project_code = data.get("projectCode")
        if not project_code:
            return res("projectCode required", [], 400)

        if not is_creator(project_code, _MODULE, user_id):
            return res("You are not authorized to create petty cash budgets", [], 403)

        details_data = _parse_details(data)
        if not details_data:
            return res("At least one budget detail row required", [], 400)

        total = sum(Decimal(str(r.get("budgetAmount") or 0)) for r in details_data)

        attachment_url = None
        if files:
            f = files.get("attachment")
            if f:
                attachment_url = upload_file_to_bunny(
                    file=f,
                    mainFolder="petty_cash",
                    subFolder="budget",
                    fileName=str(_uuid.uuid4()),
                )

        budget = PettyCashBudget(
            budget_uuid         = str(_uuid.uuid4()),
            budget_no           = _generate_budget_no(),
            budget_date         = date.today(),
            budget_frequency    = data.get("budgetFrequency"),
            from_date           = _parse_date(data.get("fromDate")),
            to_date             = _parse_date(data.get("toDate")),
            attachment          = attachment_url,
            project_code        = project_code,
            total_budget_amount = total,
            workflow_status     = "Draft",
            current_level       = 0,
            locked              = False,
            created_by          = user_id,
        )
        db.session.add(budget)
        db.session.flush()

        for idx, row in enumerate(details_data, start=1):
            db.session.add(PettyCashBudgetDetail(
                budget_id         = budget.id,
                sl_no             = row.get("slNo") or idx,
                cc_code           = row.get("ccCode"),
                cc_name           = row.get("ccName"),
                short_description = row.get("shortDescription"),
                budget_amount     = Decimal(str(row.get("budgetAmount") or 0)),
            ))

        db.session.commit()

        return res("Petty cash budget created", {
            "id":         budget.id,
            "budgetNo":   budget.budget_no,
            "budgetUuid": budget.budget_uuid,
        }, 201)

    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 2. LIST
# ══════════════════════════════════════════════════════════════════

def get_petty_cash_budget_list(data):
    try:
        project_code = data.get("projectCode")
        if not project_code:
            return res("projectCode required", [], 400)

        query = PettyCashBudget.query.filter(PettyCashBudget.project_code == project_code)

        if data.get("workflowStatus"):
            query = query.filter(PettyCashBudget.workflow_status == data["workflowStatus"])

        if data.get("search"):
            term = f"%{data['search']}%"
            query = query.filter(PettyCashBudget.budget_no.ilike(term))

        if data.get("fromDate"):
            query = query.filter(PettyCashBudget.budget_date >= data["fromDate"])

        if data.get("toDate"):
            query = query.filter(PettyCashBudget.budget_date <= data["toDate"])

        rows = query.order_by(PettyCashBudget.id.desc()).all()

        result = [
            {
                "id":               r.id,
                "budgetNo":         r.budget_no,
                "budgetDate":       _fmt_date(r.budget_date),
                "budgetFrequency":  r.budget_frequency,
                "fromDate":         _fmt_date(r.from_date),
                "toDate":           _fmt_date(r.to_date),
                "totalBudgetAmount":float(r.total_budget_amount or 0),
                "workflowStatus":   r.workflow_status,
                "createdBy":        r.creator.username if r.creator else None,
                "createdAt":        _fmt_date(r.created_at),
            }
            for r in rows
        ]

        return res("Petty cash budget list fetched", {"list": result}, 200)

    except Exception as e:
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 3. GET BY ID
# ══════════════════════════════════════════════════════════════════

def get_petty_cash_budget_details(budget_id):
    try:
        budget = PettyCashBudget.query.get(budget_id)
        if not budget:
            return res("Petty cash budget not found", [], 404)
        return res("Petty cash budget fetched", _build_payload(budget), 200)
    except Exception as e:
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 4. GET BY UUID (public, no auth)
# ══════════════════════════════════════════════════════════════════

def get_petty_cash_budget_by_uuid(budget_uuid):
    try:
        budget = PettyCashBudget.query.filter_by(budget_uuid=budget_uuid).first()
        if not budget:
            return res("Petty cash budget not found", [], 404)
        return res("Petty cash budget fetched", _build_payload(budget), 200)
    except Exception as e:
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 5. EDIT (Draft / Reback only)
# ══════════════════════════════════════════════════════════════════

def edit_petty_cash_budget(budget_id, data, user_id, files=None):
    try:
        budget = PettyCashBudget.query.get(budget_id)
        if not budget:
            return res("Petty cash budget not found", [], 404)
        if budget.locked:
            return res("Budget is locked and cannot be edited", [], 400)
        if budget.workflow_status not in ("Draft", "Reback"):
            return res("Only Draft or Reback records can be edited", [], 400)

        if not is_creator(budget.project_code, _MODULE, user_id):
            return res("You are not authorized to edit this budget", [], 403)

        details_data = _parse_details(data)
        if not details_data:
            return res("At least one budget detail row required", [], 400)

        if data.get("budgetFrequency") is not None:
            budget.budget_frequency = data["budgetFrequency"]
        if data.get("fromDate") is not None:
            budget.from_date = _parse_date(data["fromDate"])
        if data.get("toDate") is not None:
            budget.to_date = _parse_date(data["toDate"])

        if files:
            f = files.get("attachment")
            if f:
                budget.attachment = upload_file_to_bunny(
                    file=f,
                    mainFolder="petty_cash",
                    subFolder="budget",
                    fileName=str(_uuid.uuid4()),
                )

        PettyCashBudgetDetail.query.filter_by(budget_id=budget.id).delete()
        db.session.flush()

        total = Decimal("0")
        for idx, row in enumerate(details_data, start=1):
            amt = Decimal(str(row.get("budgetAmount") or 0))
            total += amt
            db.session.add(PettyCashBudgetDetail(
                budget_id         = budget.id,
                sl_no             = row.get("slNo") or idx,
                cc_code           = row.get("ccCode"),
                cc_name           = row.get("ccName"),
                short_description = row.get("shortDescription"),
                budget_amount     = amt,
            ))

        budget.total_budget_amount = total

        if budget.workflow_status == "Reback":
            budget.correction_sent_at = None

        budget.updated_by = user_id
        budget.updated_at = datetime.utcnow()

        db.session.commit()

        return res("Petty cash budget updated", {"id": budget.id, "budgetNo": budget.budget_no}, 200)

    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 6. SUBMIT
# ══════════════════════════════════════════════════════════════════

def submit_petty_cash_budget(budget_id, user_id):
    try:
        budget = PettyCashBudget.query.get(budget_id)
        if not budget:
            return res("Petty cash budget not found", [], 404)
        if budget.workflow_status not in ("Draft", "Reback"):
            return res("Budget already submitted", [], 400)
        if not budget.details:
            return res("Budget has no detail rows", [], 400)

        if budget.workflow_status == "Reback":
            budget.current_level = 0

        first_level = get_first_approver(budget.project_code, _MODULE)

        if not first_level:
            budget.workflow_status   = "Approved"
            budget.locked            = True
            budget.approved_by       = user_id
            budget.submitted_at      = datetime.utcnow()
            budget.final_approved_at = datetime.utcnow()
        else:
            budget.workflow_status = f"Pending_L{first_level.level_no}"
            budget.current_level   = first_level.level_no
            budget.locked          = True
            budget.submitted_at    = datetime.utcnow()

        create_history(
            project_code=budget.project_code,
            module_code=_MODULE,
            record_id=budget.id,
            level_no=budget.current_level,
            action="SUBMIT",
            action_by=user_id,
        )

        budget.submitted_by = user_id
        budget.updated_by   = user_id
        budget.updated_at   = datetime.utcnow()

        db.session.commit()

        return res("Budget submitted", {"id": budget.id, "workflowStatus": budget.workflow_status}, 200)

    except SQLAlchemyError as e:
        db.session.rollback()
        return res(str(e), [], 500)
    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 7. APPROVE
# ══════════════════════════════════════════════════════════════════

def approve_petty_cash_budget(budget_id, approved_by, comments=None):
    try:
        budget = PettyCashBudget.query.get(budget_id)
        if not budget:
            return res("Petty cash budget not found", [], 404)
        if not budget.workflow_status.startswith("Pending"):
            return res("Budget is not pending approval", [], 400)

        if not is_current_approver(budget.project_code, _MODULE, budget.current_level, approved_by):
            return res("You are not the current approver", [], 403)

        gap = get_gap_level(budget.project_code, _MODULE, budget.current_level)
        if gap:
            return res(f"L{gap} is not assigned. Please assign it before approving.", [], 400)

        next_level = get_next_approver(budget.project_code, _MODULE, budget.current_level)

        if next_level:
            create_history(
                project_code=budget.project_code, module_code=_MODULE,
                record_id=budget.id, level_no=budget.current_level,
                action="APPROVE", action_by=approved_by, comments=comments,
            )
            budget.current_level   = next_level.level_no
            budget.workflow_status = f"Pending_L{next_level.level_no}"
        else:
            create_history(
                project_code=budget.project_code, module_code=_MODULE,
                record_id=budget.id, level_no=budget.current_level,
                action="FINAL_APPROVE", action_by=approved_by, comments=comments,
            )
            budget.workflow_status   = "Approved"
            budget.locked            = True
            budget.approved_by       = approved_by
            budget.final_approved_at = datetime.utcnow()

        budget.updated_by = approved_by
        budget.updated_at = datetime.utcnow()

        db.session.commit()

        return res("Budget approved", {"id": budget.id, "workflowStatus": budget.workflow_status}, 200)

    except SQLAlchemyError as e:
        db.session.rollback()
        return res(str(e), [], 500)
    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 8. REBACK
# ══════════════════════════════════════════════════════════════════

def reback_petty_cash_budget(budget_id, reback_by, comments=None):
    try:
        budget = PettyCashBudget.query.get(budget_id)
        if not budget:
            return res("Petty cash budget not found", [], 404)
        if not budget.workflow_status.startswith("Pending"):
            return res("Budget is not pending", [], 400)
        if not comments:
            return res("Comments required for reback", [], 400)

        if not is_current_approver(budget.project_code, _MODULE, budget.current_level, reback_by):
            return res("You are not the current approver", [], 403)

        budget.workflow_status    = "Reback"
        budget.locked             = False
        budget.correction_sent_at = datetime.utcnow()
        budget.updated_by         = reback_by
        budget.updated_at         = datetime.utcnow()

        create_history(
            project_code=budget.project_code, module_code=_MODULE,
            record_id=budget.id, level_no=budget.current_level,
            action="REBACK", action_by=reback_by, comments=comments,
        )

        db.session.commit()

        return res("Budget sent for correction", {"id": budget.id, "workflowStatus": budget.workflow_status}, 200)

    except SQLAlchemyError as e:
        db.session.rollback()
        return res(str(e), [], 500)
    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 9. REJECT
# ══════════════════════════════════════════════════════════════════

def reject_petty_cash_budget(budget_id, rejected_by, comments=None):
    try:
        budget = PettyCashBudget.query.get(budget_id)
        if not budget:
            return res("Petty cash budget not found", [], 404)
        if not budget.workflow_status.startswith("Pending"):
            return res("Budget is not pending", [], 400)
        if not comments:
            return res("Comments required for rejection", [], 400)

        if not is_current_approver(budget.project_code, _MODULE, budget.current_level, rejected_by):
            return res("You are not the current approver", [], 403)

        budget.workflow_status = "Rejected"
        budget.locked          = True
        budget.rejected_at     = datetime.utcnow()
        budget.rejected_by     = rejected_by
        budget.status          = "Inactive"
        budget.updated_by      = rejected_by
        budget.updated_at      = datetime.utcnow()

        create_history(
            project_code=budget.project_code, module_code=_MODULE,
            record_id=budget.id, level_no=budget.current_level,
            action="REJECT", action_by=rejected_by, comments=comments,
        )

        db.session.commit()

        return res("Budget rejected", {"id": budget.id, "workflowStatus": budget.workflow_status}, 200)

    except SQLAlchemyError as e:
        db.session.rollback()
        return res(str(e), [], 500)
    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 10. APPROVAL HISTORY
# ══════════════════════════════════════════════════════════════════

def get_petty_cash_budget_history(budget_id):
    try:
        budget = PettyCashBudget.query.get(budget_id)
        if not budget:
            return res("Petty cash budget not found", [], 404)

        rows = get_history(_MODULE, budget.id)

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

        steps = get_approval_steps(budget.project_code, _MODULE, budget, rows)

        return res("History fetched", {
            "workflowStatus": budget.workflow_status,
            "currentLevel":   budget.current_level,
            "approvalSteps":  steps,
            "history":        history,
        }, 200)

    except Exception as e:
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 11. MY APPROVAL STATUS
# ══════════════════════════════════════════════════════════════════

def get_petty_cash_budget_my_approval_status(budget_id, user_id):
    try:
        budget = PettyCashBudget.query.get(budget_id)
        if not budget:
            return res("Petty cash budget not found", [], 404)
        data = get_my_approval_status(budget.project_code, _MODULE, budget, user_id)
        return res("Approval status", data, 200)
    except Exception as e:
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 12. REVISE BUDGET AMOUNT (post-approval, approver only)
# ══════════════════════════════════════════════════════════════════

def revise_petty_cash_budget(budget_id, data, user_id):
    try:
        budget = PettyCashBudget.query.get(budget_id)
        if not budget:
            return res("Petty cash budget not found", [], 404)
        if not budget.workflow_status.startswith("Pending"):
            return res("Budget can only be revised while it is pending approval", [], 400)

        if not is_current_approver(budget.project_code, _MODULE, budget.current_level, user_id):
            return res("You are not authorized to revise this budget", [], 403)

        revisions_data = data.get("revisions", [])
        if not revisions_data:
            return res("No revision data provided", [], 400)

        for item in revisions_data:
            detail_id  = item.get("detailRowId")
            new_amount = Decimal(str(item.get("newAmount") or 0))
            remark     = item.get("remark")

            detail = PettyCashBudgetDetail.query.filter_by(id=detail_id, budget_id=budget.id).first()
            if not detail:
                return res(f"Detail row {detail_id} not found in this budget", [], 404)

            old_amount = detail.budget_amount

            db.session.add(PettyCashBudgetRevision(
                budget_id     = budget.id,
                detail_row_id = detail.id,
                revised_by    = user_id,
                revised_at    = datetime.utcnow(),
                old_amount    = old_amount,
                new_amount    = new_amount,
                remark        = remark,
            ))

            detail.budget_amount = new_amount

        budget.total_budget_amount = sum(
            d.budget_amount for d in PettyCashBudgetDetail.query.filter_by(budget_id=budget.id).all()
        )
        budget.updated_by = user_id
        budget.updated_at = datetime.utcnow()

        db.session.commit()

        return res("Budget revised successfully", {
            "id":                budget.id,
            "budgetNo":          budget.budget_no,
            "totalBudgetAmount": float(budget.total_budget_amount),
        }, 200)

    except SQLAlchemyError as e:
        db.session.rollback()
        return res(str(e), [], 500)
    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 13. REVISION HISTORY
# ══════════════════════════════════════════════════════════════════

def get_petty_cash_budget_revision_history(budget_id):
    try:
        budget = PettyCashBudget.query.get(budget_id)
        if not budget:
            return res("Petty cash budget not found", [], 404)

        revisions = (
            PettyCashBudgetRevision.query
            .filter_by(budget_id=budget.id)
            .order_by(PettyCashBudgetRevision.id.asc())
            .all()
        )

        result = [
            {
                "id":          r.id,
                "detailRowId": r.detail_row_id,
                "ccName":      r.detail_row.cc_name if r.detail_row else None,
                "oldAmount":   float(r.old_amount),
                "newAmount":   float(r.new_amount),
                "remark":      r.remark,
                "revisedBy":   r.revisor.username if r.revisor else None,
                "revisedAt":   r.revised_at.strftime("%Y-%m-%d %H:%M:%S") if r.revised_at else None,
            }
            for r in revisions
        ]

        return res("Revision history fetched", {"revisions": result}, 200)

    except Exception as e:
        return res(str(e), [], 500)
