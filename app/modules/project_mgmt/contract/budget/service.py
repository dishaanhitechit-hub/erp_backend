from decimal import Decimal
from sqlalchemy.exc import SQLAlchemyError
from app.extensions import db
from datetime import datetime
import uuid as _uuid

from app.models.budget import BudgetMaster, BudgetItem, BudgetItemCCCode
from app.models.ogSaleOrder import OgSaleOrderMaster, OgSaleOrderItem
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

_MODULE = "budget_master"


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


def _generate_budget_no():
    db.session.execute(db.text("SELECT pg_advisory_xact_lock(780000)"))
    last = (
        db.session.query(BudgetMaster.budget_no)
        .order_by(BudgetMaster.id.desc())
        .first()
    )
    if last:
        try:
            num = int(last[0][3:])
        except Exception:
            num = 0
    else:
        num = 0
    return f"BDG{str(num + 1).zfill(4)}"


def _serialize_cc_codes(cc_lines):
    return [
        {
            "id":        line.id,
            "ccCodeId":  line.cc_code_id,
            "ccCode":    line.cc_code,
            "ccName":    line.cc_name,
            "ccValue":   float(line.cc_value or 0),
            "ccTotal":   float(line.cc_total  or 0),
        }
        for line in cc_lines
    ]


def _serialize_items(items):
    return [
        {
            "id":              item.id,
            "slNo":            item.sl_no,
            "itemCode":        item.item_code,
            "itemName":        item.item_name,
            "itemDescription": item.item_description,
            "unit":            item.unit,
            "orderQty":        float(item.order_qty      or 0),
            "rate":            float(item.rate           or 0),
            "initialAmount":   float(item.initial_amount or 0),
            "totalCcCost":     float(item.total_cc_cost  or 0),
            "totalCost":       float(item.total_cost     or 0),
            "ccCodes":         _serialize_cc_codes(item.cc_codes),
        }
        for item in items
    ]


def _build_detail_payload(budget):
    return {
        "id":               budget.id,
        "budgetNo":         budget.budget_no,
        "budgetUuid":       budget.budget_uuid,
        "budgetDate":       _fmt_date(budget.budget_date),
        "saleOrderId":      budget.sale_order_id,
        "saleOrderNo":      budget.sale_order_no,
        "saleOrderTitle":   budget.sale_order_title,
        "projectCode":      budget.project_code,
        "remarks":          budget.remarks,
        "totalInitialCost": float(budget.total_initial_cost or 0),
        "totalCcCost":      float(budget.total_cc_cost      or 0),
        "grandTotal":       float(budget.grand_total        or 0),
        "workflowStatus":   budget.workflow_status,
        "currentLevel":     budget.current_level,
        "locked":           budget.locked,
        "createdBy":        budget.creator.username   if budget.creator   else None,
        "createdAt":        _fmt_date(budget.created_at),
        "submittedBy":      budget.submitter.username if budget.submitter else None,
        "submittedAt":      _fmt_date(budget.submitted_at),
        "approvedBy":       budget.approver.username  if budget.approver  else None,
        "finalApprovedAt":  _fmt_date(budget.final_approved_at),
        "rejectedBy":       budget.rejector.username  if budget.rejector  else None,
        "rejectedAt":       _fmt_date(budget.rejected_at),
        "items":            _serialize_items(budget.items),
    }


# ══════════════════════════════════════════════════════════════════
# LOOKUP — Sale Orders for dropdown
# ══════════════════════════════════════════════════════════════════

def get_sale_orders_for_dropdown(args):
    try:
        project_code = args.get("projectCode")
        if not project_code:
            return res("projectCode required", [], 400)

        rows = (
            OgSaleOrderMaster.query
            .filter(
                OgSaleOrderMaster.project_code    == project_code,
                OgSaleOrderMaster.workflow_status == "Approved",
                OgSaleOrderMaster.status          == "Active",
            )
            .order_by(OgSaleOrderMaster.id.desc())
            .all()
        )

        result = [
            {
                "id":            row.id,
                "ogSaleOrderNo": row.og_sale_order_no,
                "orderTitle":    row.order_title,
                "totalAmount":   float(row.total_amount or 0),
            }
            for row in rows
        ]

        return res("Sale orders fetched", result, 200)

    except Exception as e:
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# LOOKUP — Items of a Sale Order
# ══════════════════════════════════════════════════════════════════

def get_sale_order_items(so_id):
    try:
        og_so = OgSaleOrderMaster.query.get(so_id)
        if not og_so:
            return res("Sale order not found", [], 404)

        items = [
            {
                "id":              item.id,
                "slNo":            item.sl_no,
                "itemCode":        item.item_code,
                "itemName":        item.item_name,
                "itemDescription": item.item_description,
                "unit":            item.unit,
                "orderQty":        float(item.order_qty  or 0),
                "rate":            float(item.rate        or 0),
                "amount":          float(item.amount      or 0),
            }
            for item in og_so.items
        ]

        return res("Sale order items fetched", {
            "saleOrderId":    og_so.id,
            "ogSaleOrderNo":  og_so.og_sale_order_no,
            "orderTitle":     og_so.order_title,
            "items":          items,
        }, 200)

    except Exception as e:
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# LOOKUP — CC Codes
# ══════════════════════════════════════════════════════════════════

def get_cc_codes_list(args):
    try:
        rows = CCCode.query.filter(CCCode.status == "Active").order_by(CCCode.cc_code).all()

        result = [
            {
                "id":     row.id,
                "ccCode": row.cc_code,
                "ccName": row.cc_name,
            }
            for row in rows
        ]

        return res("CC codes fetched", result, 200)

    except Exception as e:
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 1. CREATE
# ══════════════════════════════════════════════════════════════════

def create_budget(data, user_id):
    try:
        project_code = data.get("projectCode")
        if not project_code:
            return res("projectCode required", [], 400)

        allowed = is_creator(project_code, _MODULE, user_id)
        if not allowed:
            return res("You are not a Budget creator", [], 403)

        sale_order_id = data.get("saleOrderId")
        if not sale_order_id:
            return res("saleOrderId required", [], 400)

        og_so = OgSaleOrderMaster.query.get(int(sale_order_id))
        if not og_so:
            return res("Sale order not found", [], 404)

        budget_date = _parse_date(data.get("budgetDate"))
        if not budget_date:
            return res("budgetDate required (YYYY-MM-DD)", [], 400)

        items_raw = data.get("items", [])
        if not items_raw:
            return res("At least one item is required", [], 400)

        budget_no   = _generate_budget_no()
        budget_uuid = str(_uuid.uuid4())

        budget = BudgetMaster(
            budget_no        = budget_no,
            budget_uuid      = budget_uuid,
            budget_date      = budget_date,
            sale_order_id    = og_so.id,
            sale_order_no    = og_so.og_sale_order_no,
            sale_order_title = og_so.order_title,
            project_code     = project_code,
            remarks          = data.get("remarks") or None,
            workflow_status  = "Draft",
            current_level    = 0,
            locked           = False,
            created_by       = user_id,
        )

        db.session.add(budget)
        db.session.flush()

        total_initial = Decimal("0")
        total_cc      = Decimal("0")

        for idx, item_data in enumerate(items_raw, start=1):
            order_qty      = Decimal(str(item_data.get("orderQty") or 0))
            rate           = Decimal(str(item_data.get("rate")     or 0))
            initial_amount = order_qty * rate

            budget_item = BudgetItem(
                budget_id             = budget.id,
                og_sale_order_item_id = item_data.get("ogSaleOrderItemId") or None,
                sl_no                 = item_data.get("slNo") or idx,
                item_code             = item_data.get("itemCode") or None,
                item_name             = item_data.get("itemName"),
                item_description      = item_data.get("itemDescription"),
                unit                  = item_data.get("unitItem"),
                order_qty             = order_qty,
                rate                  = rate,
                initial_amount        = initial_amount,
            )

            db.session.add(budget_item)
            db.session.flush()

            item_cc_total = Decimal("0")

            for cc_data in item_data.get("ccCodes", []):
                cc_ref = CCCode.query.get(int(cc_data.get("ccCodeId")))
                if not cc_ref:
                    continue

                cc_value = Decimal(str(cc_data.get("ccValue") or 0))
                cc_total = order_qty * cc_value

                cc_line = BudgetItemCCCode(
                    budget_item_id = budget_item.id,
                    cc_code_id     = cc_ref.id,
                    cc_code        = cc_ref.cc_code,
                    cc_name        = cc_ref.cc_name,
                    cc_value       = cc_value,
                    cc_total       = cc_total,
                )
                db.session.add(cc_line)
                item_cc_total += cc_total

            budget_item.total_cc_cost = item_cc_total
            budget_item.total_cost    = initial_amount + item_cc_total

            total_initial += initial_amount
            total_cc      += item_cc_total

        budget.total_initial_cost = total_initial
        budget.total_cc_cost      = total_cc
        budget.grand_total        = total_initial + total_cc

        db.session.commit()

        return res("Budget created", {
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

def get_budget_list(args):
    try:
        project_code = args.get("projectCode")
        if not project_code:
            return res("projectCode required", [], 400)

        query = BudgetMaster.query.filter(BudgetMaster.project_code == project_code)

        if args.get("workflowStatus"):
            query = query.filter(BudgetMaster.workflow_status == args.get("workflowStatus"))

        if args.get("search"):
            term = f"%{args.get('search')}%"
            query = query.filter(
                db.or_(
                    BudgetMaster.budget_no.ilike(term),
                    BudgetMaster.sale_order_no.ilike(term),
                    BudgetMaster.sale_order_title.ilike(term),
                )
            )

        rows = query.order_by(BudgetMaster.id.desc()).all()

        result = [
            {
                "id":               row.id,
                "budgetNo":         row.budget_no,
                "budgetDate":       _fmt_date(row.budget_date),
                "saleOrderNo":      row.sale_order_no,
                "saleOrderTitle":   row.sale_order_title,
                "totalInitialCost": float(row.total_initial_cost or 0),
                "totalCcCost":      float(row.total_cc_cost      or 0),
                "grandTotal":       float(row.grand_total        or 0),
                "workflowStatus":   row.workflow_status,
                "createdBy":        row.creator.username if row.creator else None,
                "createdAt":        _fmt_date(row.created_at),
            }
            for row in rows
        ]

        return res("Budget list fetched", result, 200)

    except Exception as e:
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 3. DETAILS
# ══════════════════════════════════════════════════════════════════

def get_budget_details(budget_id):
    try:
        budget = BudgetMaster.query.get(budget_id)
        if not budget:
            return res("Budget not found", [], 404)
        return res("Budget details fetched", _build_detail_payload(budget), 200)
    except Exception as e:
        return res(str(e), [], 500)


def get_budget_by_uuid(budget_uuid):
    try:
        budget = BudgetMaster.query.filter_by(budget_uuid=budget_uuid).first()
        if not budget:
            return res("Budget not found", [], 404)
        return res("Budget details fetched", _build_detail_payload(budget), 200)
    except Exception as e:
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 4. EDIT
# ══════════════════════════════════════════════════════════════════

def edit_budget(budget_id, data, user_id):
    try:
        budget = BudgetMaster.query.get(budget_id)
        if not budget:
            return res("Budget not found", [], 404)
        if budget.locked:
            return res("Budget is locked and cannot be edited", [], 400)
        if budget.workflow_status not in ("Draft", "Reback"):
            return res("Only Draft or Reback budgets can be edited", [], 400)

        allowed = is_creator(budget.project_code, _MODULE, user_id)
        if not allowed:
            return res("You are not a Budget creator", [], 403)

        items_raw = data.get("items", [])
        if not items_raw:
            return res("At least one item is required", [], 400)

        if data.get("budgetDate"):
            budget.budget_date = _parse_date(data.get("budgetDate"))
        if data.get("remarks") is not None:
            budget.remarks = data.get("remarks") or None

        # Rebuild items and CC codes from scratch
        BudgetItem.query.filter_by(budget_id=budget.id).delete()
        db.session.flush()

        total_initial = Decimal("0")
        total_cc      = Decimal("0")

        for idx, item_data in enumerate(items_raw, start=1):
            order_qty      = Decimal(str(item_data.get("orderQty") or 0))
            rate           = Decimal(str(item_data.get("rate")     or 0))
            initial_amount = order_qty * rate

            budget_item = BudgetItem(
                budget_id             = budget.id,
                og_sale_order_item_id = item_data.get("ogSaleOrderItemId") or None,
                sl_no                 = item_data.get("slNo") or idx,
                item_code             = item_data.get("itemCode") or None,
                item_name             = item_data.get("itemName"),
                item_description      = item_data.get("itemDescription"),
                unit                  = item_data.get("unit"),
                order_qty             = order_qty,
                rate                  = rate,
                initial_amount        = initial_amount,
            )

            db.session.add(budget_item)
            db.session.flush()

            item_cc_total = Decimal("0")

            for cc_data in item_data.get("ccCodes", []):
                cc_ref = CCCode.query.get(int(cc_data.get("ccCodeId")))
                if not cc_ref:
                    continue

                cc_value = Decimal(str(cc_data.get("ccValue") or 0))
                cc_total = order_qty * cc_value

                cc_line = BudgetItemCCCode(
                    budget_item_id = budget_item.id,
                    cc_code_id     = cc_ref.id,
                    cc_code        = cc_ref.cc_code,
                    cc_name        = cc_ref.cc_name,
                    cc_value       = cc_value,
                    cc_total       = cc_total,
                )
                db.session.add(cc_line)
                item_cc_total += cc_total

            budget_item.total_cc_cost = item_cc_total
            budget_item.total_cost    = initial_amount + item_cc_total

            total_initial += initial_amount
            total_cc      += item_cc_total

        budget.total_initial_cost = total_initial
        budget.total_cc_cost      = total_cc
        budget.grand_total        = total_initial + total_cc

        if budget.workflow_status == "Reback":
            budget.correction_sent_at = None

        budget.updated_by = user_id
        budget.updated_at = datetime.utcnow()

        db.session.commit()

        return res("Budget updated", {"id": budget.id, "budgetNo": budget.budget_no}, 200)

    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 5. SUBMIT
# ══════════════════════════════════════════════════════════════════

def submit_budget(budget_id, submitted_by):
    try:
        budget = BudgetMaster.query.get(budget_id)
        if not budget:
            return res("Budget not found", [], 404)
        if budget.workflow_status not in ("Draft", "Reback"):
            return res("Budget already submitted", [], 400)
        if not budget.items:
            return res("Budget has no items", [], 400)

        if budget.workflow_status == "Reback":
            budget.current_level = 0

        first_level = get_first_approver(budget.project_code, _MODULE)

        if not first_level:
            budget.workflow_status   = "Approved"
            budget.locked            = True
            budget.approved_by       = submitted_by
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
            action_by=submitted_by,
        )

        budget.submitted_by = submitted_by
        budget.updated_by   = submitted_by
        budget.updated_at   = datetime.utcnow()

        db.session.commit()

        return res("Budget submitted", {
            "id":             budget.id,
            "budgetNo":       budget.budget_no,
            "workflowStatus": budget.workflow_status,
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

def approve_budget(budget_id, approved_by, comments=None):
    try:
        budget = BudgetMaster.query.get(budget_id)
        if not budget:
            return res("Budget not found", [], 404)
        if not budget.workflow_status.startswith("Pending"):
            return res("Budget is not pending approval", [], 400)

        allowed = is_current_approver(
            budget.project_code, _MODULE, budget.current_level, approved_by
        )
        if not allowed:
            return res("You are not the current approver", [], 403)

        gap = get_gap_level(budget.project_code, _MODULE, budget.current_level)
        if gap:
            return res(f"L{gap} is not assigned. Please assign before approving.", [], 400)

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

        return res("Budget approved", {
            "id":             budget.id,
            "workflowStatus": budget.workflow_status,
            "currentLevel":   budget.current_level,
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

def reback_budget(budget_id, reback_by, comments=None):
    try:
        budget = BudgetMaster.query.get(budget_id)
        if not budget:
            return res("Budget not found", [], 404)
        if not budget.workflow_status.startswith("Pending"):
            return res("Budget is not pending", [], 400)
        if not comments:
            return res("Comments required for reback", [], 400)

        allowed = is_current_approver(
            budget.project_code, _MODULE, budget.current_level, reback_by
        )
        if not allowed:
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

        return res("Budget sent for correction", {
            "id":             budget.id,
            "workflowStatus": budget.workflow_status,
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

def reject_budget(budget_id, rejected_by, comments=None):
    try:
        budget = BudgetMaster.query.get(budget_id)
        if not budget:
            return res("Budget not found", [], 404)
        if not budget.workflow_status.startswith("Pending"):
            return res("Budget is not pending", [], 400)
        if not comments:
            return res("Comments required for rejection", [], 400)

        allowed = is_current_approver(
            budget.project_code, _MODULE, budget.current_level, rejected_by
        )
        if not allowed:
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

        return res("Budget rejected", {
            "id":             budget.id,
            "workflowStatus": budget.workflow_status,
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

def get_budget_history(budget_id):
    try:
        budget = BudgetMaster.query.get(budget_id)
        if not budget:
            return res("Budget not found", [], 404)

        rows = get_history(_MODULE, budget.id)

        history = [
            {
                "id":        row.id,
                "action":    row.action,
                "level":     row.level_no,
                "comments":  row.comments,
                "actionBy":  row.user.username if row.user else None,
                "createdAt": (
                    row.created_at.strftime("%Y-%m-%d %H:%M:%S")
                    if row.created_at else None
                ),
            }
            for row in rows
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
# 10. MY APPROVAL STATUS
# ══════════════════════════════════════════════════════════════════

def get_budget_my_approval_status(budget_id, user_id):
    try:
        budget = BudgetMaster.query.get(budget_id)
        if not budget:
            return res("Budget not found", [], 404)
        data = get_my_approval_status(budget.project_code, _MODULE, budget, user_id)
        return res("Approval status", data, 200)
    except Exception as e:
        return res(str(e), [], 500)
