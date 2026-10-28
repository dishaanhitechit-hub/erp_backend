from sqlalchemy import func
from app.extensions import db
from datetime import datetime
from decimal import Decimal
import uuid as _uuid_lib

from app.models.uncertainAllocation import UncertainAllocationMaster, UncertainAllocationLine
from app.models.billingMaster import BillingMaster
from app.models.ogSaleOrder import OgSaleOrderMaster
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
from app.alias_helper import get_approval_module

MODULE = "uncertain_allocation"


# ══════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════

def _fmt_date(d):
    if d is None:
        return None
    if isinstance(d, datetime):
        return d.strftime("%Y-%m-%d %H:%M")
    return d.strftime("%Y-%m-%d")


def _generate_ua_no():
    last = (
        db.session.query(UncertainAllocationMaster.ua_no)
        .order_by(UncertainAllocationMaster.id.desc())
        .with_for_update()
        .first()
    )
    if last:
        try:
            last_serial = int(last[0])
        except Exception:
            last_serial = 700000
    else:
        last_serial = 700000
    return str(last_serial + 1)


def _fetch_claim_amount(og_sale_order_no, project_code):
    result = (
        db.session.query(func.coalesce(func.sum(BillingMaster.this_bill_claim), 0))
        .filter(
            BillingMaster.og_sale_order_no == og_sale_order_no,
            BillingMaster.project_code     == project_code,
            BillingMaster.mode             == "sale_claim_bill",
            BillingMaster.workflow_status  == "Approved",
        )
        .scalar()
    )
    return Decimal(str(result or 0))


def _fetch_certified_amount(og_sale_order_no, project_code):
    result = (
        db.session.query(func.coalesce(func.sum(BillingMaster.this_bill_claim), 0))
        .filter(
            BillingMaster.og_sale_order_no == og_sale_order_no,
            BillingMaster.project_code     == project_code,
            BillingMaster.mode             == "sale_certified_bill",
            BillingMaster.workflow_status  == "Approved",
        )
        .scalar()
    )
    return Decimal(str(result or 0))


def _line_payload(line):
    og = line.og_sale_order
    return {
        "id":                             line.id,
        "slNo":                           line.sl_no,
        "ogSaleOrderId":                  line.og_sale_order_id,
        "ogSaleOrderNo":                  line.og_sale_order_no,
        "orderTitle":                     line.order_title,
        "orderNo":                        line.order_no,
        "orderDate":                      _fmt_date(line.order_date),
        "ogSaleOrderDate":                _fmt_date(og.og_sale_order_date) if og else None,
        "claimAmount":                    float(line.claim_amount     or 0),
        "certifiedAmount":                float(line.certified_amount or 0),
        "difference":                     float(line.difference       or 0),
        "overBillingCalculationMistake":  float(line.over_billing_calculation_mistake or 0),
        "certifiedHoldAmendmentPending":  float(line.certified_hold_amendment_pending or 0),
        "nonBoqItemsRate":                float(line.non_boq_items_rate               or 0),
        "holdWork":                       float(line.hold_work                        or 0),
        "remarks":                        line.remarks,
    }


# ══════════════════════════════════════════════════════════════════
# 1. SALE ORDER LOOKUP
# ══════════════════════════════════════════════════════════════════

def get_sale_orders_for_lookup(data):
    try:
        project_code = data.get("projectCode")
        if not project_code:
            return res("projectCode required", [], 400)

        query = OgSaleOrderMaster.query.filter(
            OgSaleOrderMaster.project_code    == project_code,
            OgSaleOrderMaster.workflow_status == "Approved",
        )

        if data.get("search"):
            s = f"%{data.get('search')}%"
            query = query.filter(
                db.or_(
                    OgSaleOrderMaster.og_sale_order_no.ilike(s),
                    OgSaleOrderMaster.order_title.ilike(s),
                    OgSaleOrderMaster.order_no.ilike(s),
                )
            )

        rows = query.order_by(OgSaleOrderMaster.id.desc()).all()

        result = []
        for r in rows:
            claim_amt = _fetch_claim_amount(r.og_sale_order_no, project_code)
            cert_amt  = _fetch_certified_amount(r.og_sale_order_no, project_code)
            diff      = claim_amt - cert_amt
            result.append({
                "ogSaleOrderId":   r.id,
                "ogSaleOrderNo":   r.og_sale_order_no,
                "ogSaleOrderDate": _fmt_date(r.og_sale_order_date),
                "orderTitle":      r.order_title,
                "orderNo":         r.order_no,
                "orderDate":       _fmt_date(r.order_validity),
                "claimAmount":     float(claim_amt),
                "certifiedAmount": float(cert_amt),
                "difference":      float(diff),
            })

        return res("Sale orders fetched", result, 200)

    except Exception as e:
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 2. CREATE
# ══════════════════════════════════════════════════════════════════

def create_ua(data, user_id):
    try:
        project_code = data.get("projectCode")
        if not project_code:
            return res("projectCode required", [], 400)

        if not is_creator(project_code, get_approval_module(MODULE), user_id):
            return res("You are not authorised to create uncertain allocation", [], 403)

        lines_data = data.get("lines", [])
        if not lines_data:
            return res("At least one line is required", [], 400)

        ua = UncertainAllocationMaster(
            ua_no        = _generate_ua_no(),
            ua_date      = data.get("uaDate"),
            ua_uuid      = str(_uuid_lib.uuid4()),
            project_code = project_code,
            remarks      = data.get("remarks"),
            workflow_status = "Draft",
            current_level   = 0,
            locked          = False,
            created_by      = user_id,
        )
        db.session.add(ua)
        db.session.flush()

        total_claim = Decimal('0')
        total_cert  = Decimal('0')

        for idx, row in enumerate(lines_data, start=1):
            og_so_id = row.get("ogSaleOrderId")
            og_so    = OgSaleOrderMaster.query.get(og_so_id) if og_so_id else None

            og_so_no = (og_so.og_sale_order_no if og_so else row.get("ogSaleOrderNo"))

            claim_amt = _fetch_claim_amount(og_so_no, project_code)
            cert_amt  = _fetch_certified_amount(og_so_no, project_code)
            diff      = claim_amt - cert_amt

            line = UncertainAllocationLine(
                ua_id            = ua.id,
                sl_no            = idx,
                og_sale_order_id = og_so_id,
                og_sale_order_no = og_so_no,
                order_title      = og_so.order_title      if og_so else row.get("orderTitle"),
                order_no         = og_so.order_no         if og_so else row.get("orderNo"),
                order_date       = og_so.og_sale_order_date if og_so else None,
                claim_amount     = claim_amt,
                certified_amount = cert_amt,
                difference       = diff,
                over_billing_calculation_mistake = Decimal(str(row.get("overBillingCalculationMistake") or 0)),
                certified_hold_amendment_pending = Decimal(str(row.get("certifiedHoldAmendmentPending") or 0)),
                non_boq_items_rate               = Decimal(str(row.get("nonBoqItemsRate")               or 0)),
                hold_work                        = Decimal(str(row.get("holdWork")                       or 0)),
                remarks                          = row.get("remarks"),
            )
            db.session.add(line)
            total_claim += claim_amt
            total_cert  += cert_amt

        ua.total_claim      = total_claim
        ua.total_certified  = total_cert
        ua.total_difference = total_claim - total_cert

        db.session.commit()

        return res("Uncertain allocation created", {
            "uaId":  ua.id,
            "uaNo":  ua.ua_no,
            "uaUuid": ua.ua_uuid,
        }, 201)

    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 3. LIST
# ══════════════════════════════════════════════════════════════════

def get_ua_list(data):
    try:
        if not data.get("projectCode"):
            return res("projectCode required", [], 400)

        query = UncertainAllocationMaster.query.filter(
            UncertainAllocationMaster.project_code == data.get("projectCode")
        )

        if data.get("workflowStatus"):
            query = query.filter(UncertainAllocationMaster.workflow_status == data.get("workflowStatus"))
        if data.get("search"):
            query = query.filter(UncertainAllocationMaster.ua_no.ilike(f"%{data.get('search')}%"))

        rows = query.order_by(UncertainAllocationMaster.id.desc()).all()

        result = [
            {
                "id":              r.id,
                "uaNo":            r.ua_no,
                "uaDate":          _fmt_date(r.ua_date),
                "projectCode":     r.project_code,
                "totalClaim":      float(r.total_claim      or 0),
                "totalCertified":  float(r.total_certified  or 0),
                "totalDifference": float(r.total_difference or 0),
                "workflowStatus":  r.workflow_status,
                "remarks":         r.remarks,
                "createdBy":       r.creator.username if r.creator else None,
                "createdAt":       _fmt_date(r.created_at),
            }
            for r in rows
        ]

        return res("Uncertain allocation list fetched", result, 200)

    except Exception as e:
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 4. DETAILS
# ══════════════════════════════════════════════════════════════════

def get_ua_details(ua_id):
    try:
        ua = UncertainAllocationMaster.query.get(ua_id)
        if not ua:
            return res("Uncertain allocation not found", [], 404)

        data = {
            "id":              ua.id,
            "uaNo":            ua.ua_no,
            "uaDate":          _fmt_date(ua.ua_date),
            "uaUuid":          ua.ua_uuid,
            "projectCode":     ua.project_code,
            "remarks":         ua.remarks,
            "totalClaim":      float(ua.total_claim      or 0),
            "totalCertified":  float(ua.total_certified  or 0),
            "totalDifference": float(ua.total_difference or 0),
            "workflowStatus":  ua.workflow_status,
            "currentLevel":    ua.current_level,
            "locked":          ua.locked,
            "createdBy":       ua.creator.username  if ua.creator  else None,
            "createdAt":       _fmt_date(ua.created_at),
            "submittedBy":     ua.submitter.username if ua.submitter else None,
            "submittedAt":     _fmt_date(ua.submitted_at),
            "approvedBy":      ua.approver.username  if ua.approver  else None,
            "finalApprovedAt": _fmt_date(ua.final_approved_at),
            "lines":           [_line_payload(ln) for ln in ua.lines],
        }

        return res("Uncertain allocation details fetched", data, 200)

    except Exception as e:
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 5. EDIT
# ══════════════════════════════════════════════════════════════════

def edit_ua(ua_id, data, user_id):
    try:
        ua = UncertainAllocationMaster.query.get(ua_id)
        if not ua:
            return res("Uncertain allocation not found", [], 404)

        if ua.locked:
            return res("Uncertain allocation cannot be edited", [], 400)

        if ua.workflow_status not in ["Draft", "Reback"]:
            return res("Only Draft or Reback records can be edited", [], 400)

        if not is_creator(ua.project_code, get_approval_module(MODULE), user_id):
            return res("You are not authorised to edit uncertain allocation", [], 403)

        lines_data = data.get("lines", [])
        if not lines_data:
            return res("At least one line is required", [], 400)

        if data.get("uaDate") is not None:
            ua.ua_date = data.get("uaDate")
        if data.get("remarks") is not None:
            ua.remarks = data.get("remarks")

        # Replace all lines
        UncertainAllocationLine.query.filter_by(ua_id=ua.id).delete()
        db.session.flush()

        total_claim = Decimal('0')
        total_cert  = Decimal('0')

        for idx, row in enumerate(lines_data, start=1):
            og_so_id = row.get("ogSaleOrderId")
            og_so    = OgSaleOrderMaster.query.get(og_so_id) if og_so_id else None
            og_so_no = og_so.og_sale_order_no if og_so else row.get("ogSaleOrderNo")

            claim_amt = _fetch_claim_amount(og_so_no, ua.project_code)
            cert_amt  = _fetch_certified_amount(og_so_no, ua.project_code)
            diff      = claim_amt - cert_amt

            line = UncertainAllocationLine(
                ua_id            = ua.id,
                sl_no            = idx,
                og_sale_order_id = og_so_id,
                og_sale_order_no = og_so_no,
                order_title      = og_so.order_title        if og_so else row.get("orderTitle"),
                order_no         = og_so.order_no           if og_so else row.get("orderNo"),
                order_date       = og_so.og_sale_order_date if og_so else None,
                claim_amount     = claim_amt,
                certified_amount = cert_amt,
                difference       = diff,
                over_billing_calculation_mistake = Decimal(str(row.get("overBillingCalculationMistake") or 0)),
                certified_hold_amendment_pending = Decimal(str(row.get("certifiedHoldAmendmentPending") or 0)),
                non_boq_items_rate               = Decimal(str(row.get("nonBoqItemsRate")               or 0)),
                hold_work                        = Decimal(str(row.get("holdWork")                       or 0)),
                remarks                          = row.get("remarks"),
            )
            db.session.add(line)
            total_claim += claim_amt
            total_cert  += cert_amt

        ua.total_claim      = total_claim
        ua.total_certified  = total_cert
        ua.total_difference = total_claim - total_cert

        if ua.workflow_status == "Reback":
            ua.correction_sent_at = None

        ua.updated_by = user_id
        ua.updated_at = datetime.utcnow()

        db.session.commit()

        return res("Uncertain allocation updated", {"uaId": ua.id, "uaNo": ua.ua_no}, 200)

    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 6. SUBMIT
# ══════════════════════════════════════════════════════════════════

def submit_ua(ua_id, submitted_by=None):
    try:
        ua = UncertainAllocationMaster.query.get(ua_id)
        if not ua:
            return res("Uncertain allocation not found", [], 404)
        if ua.workflow_status not in ["Draft", "Reback"]:
            return res("Already submitted", [], 400)
        if not ua.lines:
            return res("No lines found", [], 400)

        if ua.workflow_status == "Reback":
            ua.current_level = 0

        first_level = get_first_approver(ua.project_code, get_approval_module(MODULE))

        if not first_level:
            ua.workflow_status   = "Approved"
            ua.locked            = True
            ua.approved_by       = submitted_by
            ua.submitted_at      = datetime.utcnow()
            ua.final_approved_at = datetime.utcnow()
        else:
            ua.workflow_status = f"Pending_L{first_level.level_no}"
            ua.current_level   = first_level.level_no
            ua.locked          = True
            ua.submitted_at    = datetime.utcnow()

        create_history(
            project_code=ua.project_code, module_code=MODULE,
            record_id=ua.id, level_no=ua.current_level,
            action="SUBMIT", action_by=submitted_by,
        )

        ua.submitted_by = submitted_by
        ua.updated_by   = submitted_by
        ua.updated_at   = datetime.utcnow()

        db.session.commit()

        return res("Uncertain allocation submitted", {
            "uaId": ua.id, "uaNo": ua.ua_no, "workflowStatus": ua.workflow_status,
        }, 200)

    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 7. APPROVE
# ══════════════════════════════════════════════════════════════════

def approve_ua(ua_id, approved_by=None, comments=None):
    try:
        ua = UncertainAllocationMaster.query.get(ua_id)
        if not ua:
            return res("Uncertain allocation not found", [], 404)
        if not ua.workflow_status.startswith("Pending"):
            return res("Not pending approval", [], 400)

        if not is_current_approver(ua.project_code, get_approval_module(MODULE), ua.current_level, approved_by):
            return res("You are not the current approver", [], 403)

        gap = get_gap_level(ua.project_code, get_approval_module(MODULE), ua.current_level)
        if gap:
            return res(f"L{gap} is not assigned. Please assign before approving.", [], 400)

        next_level = get_next_approver(ua.project_code, get_approval_module(MODULE), ua.current_level)

        if next_level:
            create_history(project_code=ua.project_code, module_code=MODULE, record_id=ua.id,
                           level_no=ua.current_level, action="APPROVE",
                           action_by=approved_by, comments=comments)
            ua.current_level   = next_level.level_no
            ua.workflow_status = f"Pending_L{next_level.level_no}"
        else:
            create_history(project_code=ua.project_code, module_code=MODULE, record_id=ua.id,
                           level_no=ua.current_level, action="FINAL_APPROVE",
                           action_by=approved_by, comments=comments)
            ua.workflow_status   = "Approved"
            ua.locked            = True
            ua.approved_by       = approved_by
            ua.final_approved_at = datetime.utcnow()

        ua.updated_by = approved_by
        ua.updated_at = datetime.utcnow()
        db.session.commit()

        return res("Approved", {
            "uaId": ua.id, "workflowStatus": ua.workflow_status, "currentLevel": ua.current_level,
        }, 200)

    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 8. REBACK
# ══════════════════════════════════════════════════════════════════

def reback_ua(ua_id, reback_by=None, comments=None):
    try:
        ua = UncertainAllocationMaster.query.get(ua_id)
        if not ua:
            return res("Uncertain allocation not found", [], 404)
        if not ua.workflow_status.startswith("Pending"):
            return res("Not pending approval", [], 400)
        if not comments:
            return res("Comments required", [], 400)

        if not is_current_approver(ua.project_code, get_approval_module(MODULE), ua.current_level, reback_by):
            return res("You are not the current approver", [], 403)

        ua.workflow_status    = "Reback"
        ua.locked             = False
        ua.correction_sent_at = datetime.utcnow()
        ua.updated_by         = reback_by
        ua.updated_at         = datetime.utcnow()

        create_history(project_code=ua.project_code, module_code=MODULE, record_id=ua.id,
                       level_no=ua.current_level, action="REBACK",
                       action_by=reback_by, comments=comments)

        db.session.commit()

        return res("Sent for correction", {"uaId": ua.id, "workflowStatus": ua.workflow_status}, 200)

    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 9. REJECT
# ══════════════════════════════════════════════════════════════════

def reject_ua(ua_id, rejected_by=None, comments=None):
    try:
        ua = UncertainAllocationMaster.query.get(ua_id)
        if not ua:
            return res("Uncertain allocation not found", [], 404)
        if not ua.workflow_status.startswith("Pending"):
            return res("Not pending approval", [], 400)
        if not comments:
            return res("Comments required", [], 400)

        if not is_current_approver(ua.project_code, get_approval_module(MODULE), ua.current_level, rejected_by):
            return res("You are not the current approver", [], 403)

        ua.workflow_status = "Rejected"
        ua.locked          = True
        ua.rejected_at     = datetime.utcnow()
        ua.rejected_by     = rejected_by
        ua.status          = "Inactive"
        ua.updated_by      = rejected_by
        ua.updated_at      = datetime.utcnow()

        create_history(project_code=ua.project_code, module_code=MODULE, record_id=ua.id,
                       level_no=ua.current_level, action="REJECT",
                       action_by=rejected_by, comments=comments)

        db.session.commit()

        return res("Rejected", {"uaId": ua.id, "workflowStatus": ua.workflow_status}, 200)

    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 10. HISTORY
# ══════════════════════════════════════════════════════════════════

def get_ua_history(ua_id):
    try:
        ua = UncertainAllocationMaster.query.get(ua_id)
        if not ua:
            return res("Uncertain allocation not found", [], 404)

        rows = get_history(MODULE, ua.id)

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

        steps = get_approval_steps(ua.project_code, MODULE, ua, rows)

        return res("History fetched", {
            "workflowStatus": ua.workflow_status,
            "currentLevel":   ua.current_level,
            "approvalSteps":  steps,
            "history":        history,
        }, 200)

    except Exception as e:
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 11. MY APPROVAL STATUS
# ══════════════════════════════════════════════════════════════════

def get_ua_my_approval_status(ua_id, user_id):
    try:
        ua = UncertainAllocationMaster.query.get(ua_id)
        if not ua:
            return res("Uncertain allocation not found", [], 404)
        data = get_my_approval_status(ua.project_code, MODULE, ua, user_id)
        return res("Approval status", data, 200)
    except Exception as e:
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 12. GET BY UUID  (no-auth, for print page)
# ══════════════════════════════════════════════════════════════════

def get_ua_by_uuid(ua_uuid):
    try:
        ua = UncertainAllocationMaster.query.filter_by(ua_uuid=ua_uuid).first()
        if not ua:
            return res("Uncertain allocation not found", [], 404)

        data = {
            "id":              ua.id,
            "uaNo":            ua.ua_no,
            "uaDate":          _fmt_date(ua.ua_date),
            "uaUuid":          ua.ua_uuid,
            "projectCode":     ua.project_code,
            "remarks":         ua.remarks,
            "totalClaim":      float(ua.total_claim      or 0),
            "totalCertified":  float(ua.total_certified  or 0),
            "totalDifference": float(ua.total_difference or 0),
            "workflowStatus":  ua.workflow_status,
            "createdBy":       ua.creator.username  if ua.creator  else None,
            "createdAt":       _fmt_date(ua.created_at),
            "submittedBy":     ua.submitter.username if ua.submitter else None,
            "submittedAt":     _fmt_date(ua.submitted_at),
            "approvedBy":      ua.approver.username  if ua.approver  else None,
            "finalApprovedAt": _fmt_date(ua.final_approved_at),
            "lines":           [_line_payload(ln) for ln in ua.lines],
        }

        return res("Uncertain allocation details fetched", data, 200)

    except Exception as e:
        return res(str(e), [], 500)
