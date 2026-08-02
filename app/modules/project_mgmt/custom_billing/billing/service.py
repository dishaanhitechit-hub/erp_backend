from sqlalchemy import func
from sqlalchemy.exc import SQLAlchemyError
from app.extensions import db
from datetime import datetime
import uuid as _uuid
import json

from app.models.billingMaster import BillingMaster, BillingItem
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

VALID_MODES = ("sale_claim_bill", "sale_certified_bill")


# ══════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════

def _module_for(mode):
    return "sale_order_billing" if mode == "sale_order_bill" else "sale_certified_bill"


def _billing_no_prefix(mode):
    return "SOB" if mode == "sale_order_bill" else "CB"


def _upload_billing_attachment(file, billing_no):
    if not file or not file.filename:
        return None
    return upload_file_to_bunny(
        file=file,
        mainFolder="billing",
        subFolder=billing_no,
        fileName="attachment",
    )


def _fmt_date(d):
    if d is None:
        return None
    if isinstance(d, datetime):
        return d.strftime("%Y-%m-%d %H:%M")
    return d.strftime("%Y-%m-%d")


def _item_display_code(item_obj):
    if not item_obj:
        return None
    cc = item_obj.cc_code.cc_code if item_obj.cc_code else ""
    return f"{cc}{item_obj.item_code}"


def _get_pre_certified(og_sale_order_no, project_code, mode, exclude_id=None):
    q = (
        db.session.query(
            func.coalesce(func.sum(BillingMaster.this_bill_claim), 0)
        )
        .filter(
            BillingMaster.og_sale_order_no == og_sale_order_no,
            BillingMaster.project_code     == project_code,
            BillingMaster.mode             == mode,
            BillingMaster.workflow_status  == "Approved",
        )
    )
    if exclude_id:
        q = q.filter(BillingMaster.id != exclude_id)
    return float(q.scalar())


def _get_billed_amount(og_sale_order_no, project_code, mode):
    return float(
        db.session.query(
            func.coalesce(func.sum(BillingMaster.this_bill_claim), 0)
        )
        .filter(
            BillingMaster.og_sale_order_no == og_sale_order_no,
            BillingMaster.project_code     == project_code,
            BillingMaster.mode             == mode,
            BillingMaster.workflow_status  == "Approved",
        )
        .scalar()
    )


def _get_order_financials(og_sale_order_no, project_code):
    og_so = OgSaleOrderMaster.query.filter_by(
        og_sale_order_no=og_sale_order_no,
        project_code=project_code,
    ).first()
    if not og_so:
        return None
    return {
        "ogSaleOrderId":   og_so.id,
        "ogSaleOrderNo":   og_so.og_sale_order_no,
        "ogSaleOrderDate": _fmt_date(og_so.og_sale_order_date),
        "orderTitle":      og_so.order_title,
        "basicAmount":     float(og_so.basic_amount or 0),
        "gstAmount":       float(og_so.gst_amount   or 0),
        "totalAmount":     float(og_so.total_amount  or 0),
    }


def generate_billing_no(mode):
    prefix = _billing_no_prefix(mode)
    last = (
        db.session.query(BillingMaster.billing_no)
        .filter(BillingMaster.mode == mode)
        .order_by(BillingMaster.id.desc())
        .with_for_update()
        .first()
    )
    if last:
        try:
            num = int(last[0][len(prefix):])
        except Exception:
            num = 0
    else:
        num = 0
    return f"{prefix}{str(num + 1).zfill(3)}"


def _bills_under_og_so(og_sale_order_no, project_code, mode):
    rows = (
        BillingMaster.query
        .filter(
            BillingMaster.og_sale_order_no == og_sale_order_no,
            BillingMaster.project_code     == project_code,
            BillingMaster.mode             == mode,
        )
        .order_by(BillingMaster.id.asc())
        .all()
    )
    return [
        {
            "id":             r.id,
            "billingNo":      r.billing_no,
            "billingDate":    _fmt_date(r.billing_date),
            "thisBillClaim":  float(r.this_bill_claim or 0),
            "workflowStatus": r.workflow_status,
        }
        for r in rows
    ]


def _serialize_items(items):
    item_codes = [i.item_code for i in items if i.item_code]
    item_map   = {}
    if item_codes:
        objs = Item.query.filter(Item.item_code.in_(item_codes)).all()
        item_map = {obj.item_code: obj for obj in objs}

    result = []
    for item in items:
        item_obj = item_map.get(item.item_code)
        result.append({
            "id":                  item.id,
            "slNo":                item.sl_no,
            "ogSaleOrderItemId":   item.og_sale_order_item_id,
            "itemCode":            item.item_code,
            "itemName":        item.item_name,
            "itemDisplayCode": _item_display_code(item_obj),
            "itemDescription": item.item_name_desc,
            "unit":                item.unit,
            "claimQty":            float(item.claim_qty   or 0),
            "orderQty": float(item.og_so_item.order_qty or 0) if item.og_so_item else None,
            "rate":                float(item.rate         or 0),
            "amount":              float(item.amount       or 0),
            "gstPercent":          float(item.gst_percent  or 0),
            "gstAmount":           float(item.gst_amount   or 0),
        })
    return result


def _build_detail_payload(bill):
    mode      = bill.mode
    order_fin = _get_order_financials(bill.og_sale_order_no, bill.project_code)
    billed    = _get_billed_amount(bill.og_sale_order_no, bill.project_code, mode)
    bills     = _bills_under_og_so(bill.og_sale_order_no, bill.project_code, mode)
    order_basic = order_fin["basicAmount"] if order_fin else 0
    job_balance = round(order_basic - billed, 2)

    return {
        "id":                   bill.id,
        "billingNo":            bill.billing_no,
        "billingUuid":          bill.billing_uuid,
        "billingDate":          _fmt_date(bill.billing_date),
        "mode":                 bill.mode,
        "ogSaleOrderNo":        bill.og_sale_order_no,
        "ogSaleOrderId":        bill.og_sale_order_id,
        "projectCode":          bill.project_code,
        "title":                bill.title,
        "jobLocation":          bill.job_location,
        "attachment":           bill.attachment,
        "preCertifiedAmount":   float(bill.pre_certified_amount or 0),
        "thisBillClaim":        float(bill.this_bill_claim      or 0),
        "gstAmount":            float(bill.gst_amount           or 0),
        "totalClaim":           float(bill.total_claim          or 0),
        "workflowStatus":       bill.workflow_status,
        "currentLevel":         bill.current_level,
        "locked":               bill.locked,
        "orderTotalAmount":     order_fin["totalAmount"] if order_fin else 0,
        "orderBasicAmount":     order_fin["basicAmount"] if order_fin else 0,
        "orderGstAmount":       order_fin["gstAmount"]   if order_fin else 0,
        "orderTitle":           order_fin["orderTitle"]  if order_fin else None,
        "billedAmount":         billed,
        "jobBalance":           job_balance,
        "createdBy":            bill.creator.username   if bill.creator   else None,
        "createdAt":            _fmt_date(bill.created_at),
        "submittedBy":          bill.submitter.username if bill.submitter else None,
        "submittedAt":          _fmt_date(bill.submitted_at),
        "approvedBy":           bill.approver.username  if bill.approver  else None,
        "finalApprovedAt":      _fmt_date(bill.final_approved_at),
        "rejectedBy":           bill.rejector.username  if bill.rejector  else None,
        "rejectedAt":           _fmt_date(bill.rejected_at),
        "items":                _serialize_items(bill.items),
        "billsUnderOgSo":       bills,
    }


# ══════════════════════════════════════════════════════════════════
# 1. ORDER LOOKUP
# ══════════════════════════════════════════════════════════════════

def get_order_lookup(data):
    try:
        og_sale_order_no = (data.get("ogSaleOrderNo") or "").strip()
        project_code     = (data.get("projectCode")   or "").strip()
        mode             = (data.get("mode")          or "").strip()

        if not og_sale_order_no:
            return res("ogSaleOrderNo required", [], 400)
        if not project_code:
            return res("projectCode required", [], 400)
        if mode not in VALID_MODES:
            return res(f"mode must be one of {VALID_MODES}", [], 400)

        og_so = OgSaleOrderMaster.query.filter_by(
            og_sale_order_no=og_sale_order_no,
            project_code=project_code,
        ).first()

        if not og_so:
            return res("OG Sale Order not found in this project", [], 404)

        # Build items with display codes for pre-population
        og_items   = []
        item_codes = [i.item_code for i in og_so.items if i.item_code]
        item_map   = {}
        if item_codes:
            objs     = Item.query.filter(Item.item_code.in_(item_codes)).all()
            item_map = {obj.item_code: obj for obj in objs}

        for og_item in og_so.items:
            item_obj = item_map.get(og_item.item_code)
            og_items.append({
                "ogSaleOrderItemId": og_item.id,
                "slNo":              og_item.sl_no,
                "itemCode":          og_item.item_code,
                "itemDisplayCode":   _item_display_code(item_obj),
                "itemName":          og_item.item_name,
                "itemDescription":   og_item.item_description,
                "unit":              og_item.unit,
                "orderQty":          float(og_item.order_qty  or 0),
                "rate":              float(og_item.rate        or 0),
                "gstPercent":        float(og_item.gst_percent or 0),
            })

        pre_certified = _get_pre_certified(og_sale_order_no, project_code, mode)

        return res("OG Sale Order found", {
            "ogSaleOrderId":      og_so.id,
            "ogSaleOrderNo":      og_so.og_sale_order_no,
            "ogSaleOrderDate":    _fmt_date(og_so.og_sale_order_date),
            "orderTitle":         og_so.order_title,
            "orderValidity":      _fmt_date(og_so.order_validity),
            "basicAmount":        float(og_so.basic_amount or 0),
            "gstAmount":          float(og_so.gst_amount   or 0),
            "totalAmount":        float(og_so.total_amount  or 0),
            "preCertifiedAmount": pre_certified,
            "items":              og_items,
        }, 200)

    except Exception as e:
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 2. CREATE
# ══════════════════════════════════════════════════════════════════

def create_billing(req, user_id):
    try:
        project_code = req.form.get("projectCode")
        if not project_code:
            return res("projectCode required", [], 400)

        mode = (req.form.get("mode") or "").strip()
        if mode not in VALID_MODES:
            return res(f"mode must be one of {VALID_MODES}", [], 400)

        _mod = _module_for(mode)
        allowed = is_creator(project_code, _mod, user_id)
        if not allowed:
            return res("You are not a billing creator for this module", [], 403)

        og_sale_order_no = (req.form.get("ogSaleOrderNo") or "").strip()
        if not og_sale_order_no:
            return res("ogSaleOrderNo required", [], 400)

        og_so = OgSaleOrderMaster.query.filter_by(
            og_sale_order_no=og_sale_order_no,
            project_code=project_code,
        ).first()
        if not og_so:
            return res("OG Sale Order not found in this project", [], 404)

        items = json.loads(req.form.get("items") or "[]")
        if not items:
            return res("At least one BOQ item required", [], 400)

        # Validate og_sale_order_item_ids
        og_item_ids = [row.get("ogSaleOrderItemId") for row in items if row.get("ogSaleOrderItemId")]
        og_item_map = {}
        if og_item_ids:
            og_item_objs = OgSaleOrderItem.query.filter(
                OgSaleOrderItem.id.in_(og_item_ids),
                OgSaleOrderItem.og_sale_order_id == og_so.id,
            ).all()
            og_item_map = {obj.id: obj for obj in og_item_objs}

        billing_no    = generate_billing_no(mode)
        billing_uuid  = str(_uuid.uuid4())
        pre_certified = _get_pre_certified(og_sale_order_no, project_code, mode)

        attachment_url = _upload_billing_attachment(
            req.files.get("attachment"), billing_no
        )

        bill = BillingMaster(
            billing_no           = billing_no,
            billing_uuid         = billing_uuid,
            billing_date         = req.form.get("billingDate"),
            mode                 = mode,
            og_sale_order_no     = og_sale_order_no,
            og_sale_order_id     = og_so.id,
            project_code         = project_code,
            title                = req.form.get("title"),
            job_location         = req.form.get("jobLocation"),
            pre_certified_amount = pre_certified,
            attachment           = attachment_url,
            workflow_status      = "Draft",
            current_level        = 0,
            locked               = False,
            created_by           = user_id,
        )

        db.session.add(bill)
        db.session.flush()

        total_basic = 0
        total_gst   = 0

        for idx, row in enumerate(items, start=1):
            og_item_id = row.get("ogSaleOrderItemId")
            og_item    = og_item_map.get(og_item_id) if og_item_id else None

            item_code      = og_item.item_code        if og_item else row.get("itemCode")
            item_name      = og_item.item_name        if og_item else row.get("itemName")
            item_name_desc = og_item.item_description if og_item else row.get("itemDescription")
            unit           = og_item.unit              if og_item else row.get("unit")

            claim_qty   = float(row.get("claimQty")   or 0)
            rate        = float(row.get("rate")        or 0)
            amount      = round(claim_qty * rate, 2)
            gst_percent = float(
                row.get("gstPercent")
                if row.get("gstPercent") not in (None, "")
                else (og_item.gst_percent if og_item else 0)
            )
            gst_amount = round((amount * gst_percent) / 100, 2)

            db.session.add(BillingItem(
                billing_id            = bill.id,
                sl_no                 = row.get("slNo") or idx,
                og_sale_order_item_id = og_item_id,
                item_code             = item_code,
                item_name             = item_name,
                item_name_desc        = item_name_desc,
                unit                  = unit,
                claim_qty             = claim_qty,
                rate                  = rate,
                amount                = amount,
                gst_percent           = gst_percent,
                gst_amount            = gst_amount,
            ))

            total_basic += amount
            total_gst   += gst_amount

        bill.this_bill_claim = round(total_basic, 2)
        bill.gst_amount      = round(total_gst, 2)
        bill.total_claim     = round(pre_certified + total_basic, 2)

        db.session.commit()

        return res("Billing record created", {
            "id":          bill.id,
            "billingNo":   bill.billing_no,
            "billingUuid": bill.billing_uuid,
            "mode":        bill.mode,
        }, 201)

    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 3. LIST
# ══════════════════════════════════════════════════════════════════

def get_billing_list(data):
    try:
        project_code = data.get("projectCode")
        if not project_code:
            return res("projectCode required", [], 400)

        query = BillingMaster.query.filter(
            BillingMaster.project_code == project_code
        )

        if data.get("mode"):
            query = query.filter(BillingMaster.mode == data.get("mode"))
        if data.get("ogSaleOrderNo"):
            query = query.filter(
                BillingMaster.og_sale_order_no.ilike(f"%{data.get('ogSaleOrderNo')}%")
            )
        if data.get("workflowStatus"):
            query = query.filter(BillingMaster.workflow_status == data.get("workflowStatus"))
        if data.get("search"):
            term = f"%{data.get('search')}%"
            query = query.filter(
                db.or_(
                    BillingMaster.billing_no.ilike(term),
                    BillingMaster.og_sale_order_no.ilike(term),
                    BillingMaster.title.ilike(term),
                )
            )

        rows = query.order_by(BillingMaster.id.desc()).all()

        result = []
        for row in rows:
            mode      = row.mode
            billed    = _get_billed_amount(row.og_sale_order_no, row.project_code, mode)
            order_fin = _get_order_financials(row.og_sale_order_no, row.project_code)
            bills     = _bills_under_og_so(row.og_sale_order_no, row.project_code, mode)

            order_basic = order_fin["basicAmount"] if order_fin else 0
            job_balance = round(order_basic - billed, 2)

            result.append({
                "id":                  row.id,
                "billingNo":           row.billing_no,
                "billingDate":         _fmt_date(row.billing_date),
                "mode":                row.mode,
                "ogSaleOrderNo":       row.og_sale_order_no,
                "title":               row.title,
                "jobLocation":         row.job_location,
                "preCertifiedAmount":  float(row.pre_certified_amount or 0),
                "thisBillClaim":       float(row.this_bill_claim      or 0),
                "gstAmount":           float(row.gst_amount           or 0),
                "totalClaim":          float(row.total_claim          or 0),
                "orderTotalAmount":    order_fin["totalAmount"] if order_fin else 0,
                "orderBasicAmount":    order_fin["basicAmount"] if order_fin else 0,
                "billedAmount":        billed,
                "jobBalance":          job_balance,
                "workflowStatus":      row.workflow_status,
                "createdBy":           row.creator.username if row.creator else None,
                "createdAt":           _fmt_date(row.created_at),
                "billsUnderOgSo":      bills,
            })

        return res("Billing list fetched", result, 200)

    except Exception as e:
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 4. DETAILS
# ══════════════════════════════════════════════════════════════════

def get_billing_details(bill_id):
    try:
        bill = BillingMaster.query.get(bill_id)
        if not bill:
            return res("Billing record not found", [], 404)
        return res("Billing details fetched", _build_detail_payload(bill), 200)
    except Exception as e:
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 5. EDIT
# ══════════════════════════════════════════════════════════════════

def edit_billing(bill_id, req, user_id):
    try:
        bill = BillingMaster.query.get(bill_id)
        if not bill:
            return res("Billing record not found", [], 404)

        if bill.locked:
            return res("Billing record is locked and cannot be edited", [], 400)
        if bill.workflow_status not in ("Draft", "Reback"):
            return res("Only Draft or Reback records can be edited", [], 400)

        _mod   = _module_for(bill.mode)
        allowed = is_creator(bill.project_code, _mod, user_id)
        if not allowed:
            return res("You are not a billing creator for this module", [], 403)

        items = json.loads(req.form.get("items") or "[]")
        if not items:
            return res("At least one BOQ item required", [], 400)

        og_so = OgSaleOrderMaster.query.get(bill.og_sale_order_id)
        og_item_map = {}
        if og_so:
            og_item_ids = [row.get("ogSaleOrderItemId") for row in items if row.get("ogSaleOrderItemId")]
            if og_item_ids:
                og_item_objs = OgSaleOrderItem.query.filter(
                    OgSaleOrderItem.id.in_(og_item_ids),
                    OgSaleOrderItem.og_sale_order_id == og_so.id,
                ).all()
                og_item_map = {obj.id: obj for obj in og_item_objs}

        if req.form.get("billingDate"):
            bill.billing_date = req.form.get("billingDate")
        if req.form.get("title") is not None:
            bill.title = req.form.get("title")
        if req.form.get("jobLocation") is not None:
            bill.job_location = req.form.get("jobLocation")

        new_file = req.files.get("attachment")
        if new_file and new_file.filename:
            bill.attachment = _upload_billing_attachment(new_file, bill.billing_no)

        BillingItem.query.filter_by(billing_id=bill.id).delete()
        db.session.flush()

        total_basic = 0
        total_gst   = 0

        for idx, row in enumerate(items, start=1):
            og_item_id = row.get("ogSaleOrderItemId")
            og_item    = og_item_map.get(og_item_id) if og_item_id else None

            item_code      = og_item.item_code        if og_item else row.get("itemCode")
            item_name      = og_item.item_name        if og_item else row.get("itemName")
            item_name_desc = og_item.item_description if og_item else row.get("itemDescription")
            unit           = og_item.unit              if og_item else row.get("unit")

            claim_qty   = float(row.get("claimQty")   or 0)
            rate        = float(row.get("rate")        or 0)
            amount      = round(claim_qty * rate, 2)
            gst_percent = float(
                row.get("gstPercent")
                if row.get("gstPercent") not in (None, "")
                else (og_item.gst_percent if og_item else 0)
            )
            gst_amount = round((amount * gst_percent) / 100, 2)

            db.session.add(BillingItem(
                billing_id            = bill.id,
                sl_no                 = row.get("slNo") or idx,
                og_sale_order_item_id = og_item_id,
                item_code             = item_code,
                item_name             = item_name,
                item_name_desc        = item_name_desc,
                unit                  = unit,
                claim_qty             = claim_qty,
                rate                  = rate,
                amount                = amount,
                gst_percent           = gst_percent,
                gst_amount            = gst_amount,
            ))

            total_basic += amount
            total_gst   += gst_amount

        pre_certified = _get_pre_certified(
            bill.og_sale_order_no, bill.project_code, bill.mode, exclude_id=bill.id
        )

        bill.this_bill_claim      = round(total_basic, 2)
        bill.gst_amount           = round(total_gst, 2)
        bill.pre_certified_amount = pre_certified
        bill.total_claim          = round(pre_certified + total_basic, 2)

        if bill.workflow_status == "Reback":
            bill.correction_sent_at = None

        bill.updated_by = user_id
        bill.updated_at = datetime.utcnow()

        db.session.commit()

        return res("Billing record updated", {
            "id":        bill.id,
            "billingNo": bill.billing_no,
        }, 200)

    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 6. SUBMIT
# ══════════════════════════════════════════════════════════════════

def submit_billing(bill_id, submitted_by):
    try:
        bill = BillingMaster.query.get(bill_id)
        if not bill:
            return res("Billing record not found", [], 404)
        if bill.workflow_status not in ("Draft", "Reback"):
            return res("Billing record already submitted", [], 400)
        if not bill.items:
            return res("Billing record has no items", [], 400)

        if bill.workflow_status == "Reback":
            bill.current_level = 0

        _mod        = _module_for(bill.mode)
        first_level = get_first_approver(bill.project_code, _mod)

        if not first_level:
            bill.workflow_status   = "Approved"
            bill.locked            = True
            bill.approved_by       = submitted_by
            bill.submitted_at      = datetime.utcnow()
            bill.final_approved_at = datetime.utcnow()
        else:
            bill.workflow_status = f"Pending_L{first_level.level_no}"
            bill.current_level   = first_level.level_no
            bill.locked          = True
            bill.submitted_at    = datetime.utcnow()

        create_history(
            project_code=bill.project_code,
            module_code=_mod,
            record_id=bill.id,
            level_no=bill.current_level,
            action="SUBMIT",
            action_by=submitted_by,
        )

        bill.submitted_by = submitted_by
        bill.updated_by   = submitted_by
        bill.updated_at   = datetime.utcnow()

        db.session.commit()

        return res("Billing record submitted", {
            "id":             bill.id,
            "billingNo":      bill.billing_no,
            "workflowStatus": bill.workflow_status,
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

def approve_billing(bill_id, approved_by, comments=None):
    try:
        bill = BillingMaster.query.get(bill_id)
        if not bill:
            return res("Billing record not found", [], 404)
        if not bill.workflow_status.startswith("Pending"):
            return res("Billing record is not pending approval", [], 400)

        _mod    = _module_for(bill.mode)
        allowed = is_current_approver(bill.project_code, _mod, bill.current_level, approved_by)
        if not allowed:
            return res("You are not the current approver", [], 403)

        next_level = get_next_approver(bill.project_code, _mod, bill.current_level)

        if next_level:
            create_history(
                project_code=bill.project_code, module_code=_mod,
                record_id=bill.id, level_no=bill.current_level,
                action="APPROVE", action_by=approved_by, comments=comments,
            )
            bill.current_level   = next_level.level_no
            bill.workflow_status = f"Pending_L{next_level.level_no}"
        else:
            create_history(
                project_code=bill.project_code, module_code=_mod,
                record_id=bill.id, level_no=bill.current_level,
                action="FINAL_APPROVE", action_by=approved_by, comments=comments,
            )
            bill.workflow_status   = "Approved"
            bill.locked            = True
            bill.approved_by       = approved_by
            bill.final_approved_at = datetime.utcnow()

        bill.updated_by = approved_by
        bill.updated_at = datetime.utcnow()

        db.session.commit()

        return res("Billing record approved", {
            "id":             bill.id,
            "workflowStatus": bill.workflow_status,
            "currentLevel":   bill.current_level,
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

def reback_billing(bill_id, reback_by, comments=None):
    try:
        bill = BillingMaster.query.get(bill_id)
        if not bill:
            return res("Billing record not found", [], 404)
        if not bill.workflow_status.startswith("Pending"):
            return res("Billing record is not pending", [], 400)
        if not comments:
            return res("Comments required for reback", [], 400)

        _mod    = _module_for(bill.mode)
        allowed = is_current_approver(bill.project_code, _mod, bill.current_level, reback_by)
        if not allowed:
            return res("You are not the current approver", [], 403)

        bill.workflow_status    = "Reback"
        bill.locked             = False
        bill.correction_sent_at = datetime.utcnow()
        bill.updated_by         = reback_by
        bill.updated_at         = datetime.utcnow()

        create_history(
            project_code=bill.project_code, module_code=_mod,
            record_id=bill.id, level_no=bill.current_level,
            action="REBACK", action_by=reback_by, comments=comments,
        )

        db.session.commit()

        return res("Billing record sent for correction", {
            "id":             bill.id,
            "workflowStatus": bill.workflow_status,
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

def reject_billing(bill_id, rejected_by, comments=None):
    try:
        bill = BillingMaster.query.get(bill_id)
        if not bill:
            return res("Billing record not found", [], 404)
        if not bill.workflow_status.startswith("Pending"):
            return res("Billing record is not pending", [], 400)
        if not comments:
            return res("Comments required for rejection", [], 400)

        _mod    = _module_for(bill.mode)
        allowed = is_current_approver(bill.project_code, _mod, bill.current_level, rejected_by)
        if not allowed:
            return res("You are not the current approver", [], 403)

        bill.workflow_status = "Rejected"
        bill.locked          = True
        bill.rejected_at     = datetime.utcnow()
        bill.rejected_by     = rejected_by
        bill.status          = "Inactive"
        bill.updated_by      = rejected_by
        bill.updated_at      = datetime.utcnow()

        create_history(
            project_code=bill.project_code, module_code=_mod,
            record_id=bill.id, level_no=bill.current_level,
            action="REJECT", action_by=rejected_by, comments=comments,
        )

        db.session.commit()

        return res("Billing record rejected", {
            "id":             bill.id,
            "workflowStatus": bill.workflow_status,
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

def get_billing_history(bill_id):
    try:
        bill = BillingMaster.query.get(bill_id)
        if not bill:
            return res("Billing record not found", [], 404)

        _mod = _module_for(bill.mode)
        rows = get_history(_mod, bill.id)

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

        steps = get_approval_steps(bill.project_code, _mod, bill, rows)

        return res("History fetched", {
            "workflowStatus": bill.workflow_status,
            "currentLevel":   bill.current_level,
            "approvalSteps":  steps,
            "history":        history,
        }, 200)

    except Exception as e:
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 11. MY APPROVAL STATUS
# ══════════════════════════════════════════════════════════════════

def get_billing_my_approval_status(bill_id, user_id):
    try:
        bill = BillingMaster.query.get(bill_id)
        if not bill:
            return res("Billing record not found", [], 404)
        _mod = _module_for(bill.mode)
        data = get_my_approval_status(bill.project_code, _mod, bill, user_id)
        return res("Approval status", data, 200)
    except Exception as e:
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 12. GET BY UUID  (public — no JWT)
# ══════════════════════════════════════════════════════════════════

def get_billing_by_uuid(billing_uuid):
    try:
        bill = BillingMaster.query.filter_by(billing_uuid=billing_uuid).first()
        if not bill:
            return res("Billing record not found", [], 404)
        return res("Billing details fetched", _build_detail_payload(bill), 200)
    except Exception as e:
        return res(str(e), [], 500)
