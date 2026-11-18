from sqlalchemy import func
from app.extensions import db
from datetime import datetime
from decimal import Decimal
import uuid as _uuid
import json

from app.models.logisticsBill import LogisticsBill, LogisticsBillChallan
from app.models.dcMaster import DcMaster
from app.models.vendor import Vendor
from app.response import res
from app.cloudinary_uploader import upload_file_to_bunny
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
from app.models.user import User
from app.modules.communication import whatsapp_events as wa

MODULE_CODE = "logistics_bill"


def _fmt_date(d):
    if d is None:
        return None
    return d.strftime("%Y-%m-%d")


def _fmt_datetime(d):
    if d is None:
        return None
    if isinstance(d, datetime):
        return d.strftime("%Y-%m-%d %H:%M")
    return d.strftime("%Y-%m-%d")


def _ensure_lb_uuid(lb):
    """Backfill lb_uuid for legacy rows so Print works."""
    if not lb.lb_uuid:
        lb.lb_uuid = str(_uuid.uuid4())
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
    return lb.lb_uuid


def generate_lb_no():
    last = (
        db.session.query(LogisticsBill.lb_no)
        .order_by(LogisticsBill.id.desc())
        .first()
    )
    if last:
        try:
            last_serial = int(last[0].replace("LB", ""))
        except Exception:
            last_serial = 440000
    else:
        last_serial = 440000
    return f"LB{last_serial + 1}"


def _compute_amounts(data):
    """Compute taxable_amount, tax amounts, total, net_payable from raw data."""
    basic_freight        = Decimal(str(data.get("basicFreight") or 0))
    loading_charges      = Decimal(str(data.get("loadingCharges") or 0))
    unloading_charges    = Decimal(str(data.get("unloadingCharges") or 0))
    waiting_charges      = Decimal(str(data.get("waitingCharges") or 0))
    toll_charges         = Decimal(str(data.get("tollCharges") or 0))
    other_charges        = Decimal(str(data.get("otherCharges") or 0))

    taxable_amount = (basic_freight + loading_charges + unloading_charges
                      + waiting_charges + toll_charges + other_charges)

    gst_type = data.get("gstType", "IGST")

    igst_percent = Decimal(str(data.get("igstPercent") or 0))
    cgst_percent = Decimal(str(data.get("cgstPercent") or 0))
    sgst_percent = Decimal(str(data.get("sgstPercent") or 0))

    if gst_type == "IGST":
        igst_amount = (taxable_amount * igst_percent / 100).quantize(Decimal("0.01"))
        cgst_amount = Decimal("0")
        sgst_amount = Decimal("0")
    else:
        igst_amount = Decimal("0")
        cgst_amount = (taxable_amount * cgst_percent / 100).quantize(Decimal("0.01"))
        sgst_amount = (taxable_amount * sgst_percent / 100).quantize(Decimal("0.01"))

    total_tax = igst_amount + cgst_amount + sgst_amount
    total_amount = taxable_amount + total_tax

    tds_percent = Decimal(str(data.get("tdsPercent") or 0))
    tds_amount = (taxable_amount * tds_percent / 100).quantize(Decimal("0.01"))

    net_payable = total_amount - tds_amount

    return {
        "taxable_amount":  taxable_amount,
        "igst_percent":    igst_percent,
        "igst_amount":     igst_amount,
        "cgst_percent":    cgst_percent,
        "cgst_amount":     cgst_amount,
        "sgst_percent":    sgst_percent,
        "sgst_amount":     sgst_amount,
        "tds_percent":     tds_percent,
        "tds_amount":      tds_amount,
        "total_amount":    total_amount,
        "net_payable":     net_payable,
    }


# ══════════════════════════════════════════════════════════════════
# GET ELIGIBLE DELIVERY CHALLANS (for bill linking)
# ══════════════════════════════════════════════════════════════════

def get_eligible_dcs(project_code):
    """Return Approved DCs for the project that are not already fully billed."""
    try:
        if not project_code:
            return res("projectCode required", [], 400)

        rows = (
            DcMaster.query
            .filter(
                DcMaster.to_project_code == project_code,
                DcMaster.workflow_status == "Approved",
            )
            .order_by(DcMaster.id.desc())
            .all()
        )

        # DCs already on a non-rejected bill
        billed_dc_ids = set(
            row.dc_id
            for row in db.session.query(LogisticsBillChallan.dc_id)
            .join(LogisticsBill, LogisticsBill.id == LogisticsBillChallan.lb_id)
            .filter(LogisticsBill.workflow_status != "Rejected")
            .all()
        )

        result = []
        for dc in rows:
            already_billed = dc.id in billed_dc_ids
            vendor_name = dc.from_vendor.ledger_name if dc.from_vendor else None
            order_no = dc.order.order_no if dc.order else None

            result.append({
                "dcId":          dc.id,
                "dcNo":          dc.dc_no,
                "challanDate":   _fmt_date(dc.challan_date),
                "orderType":     dc.order_type,
                "orderNo":       order_no,
                "fromName":      vendor_name or dc.from_project_code,
                "toProjectCode": dc.to_project_code,
                "noOfItems":     len(dc.items),
                "alreadyBilled": already_billed,
            })

        return res("Eligible DCs fetched", result, 200)

    except Exception as e:
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# CREATE LOGISTICS BILL
# ══════════════════════════════════════════════════════════════════

def create_lb(data, user_id, files=None):
    try:
        allowed = is_creator(data.get("projectCode"), MODULE_CODE, user_id)
        if not allowed:
            return res("You are not authorized to create Logistics Bill", [], 403)

        vendor_id = data.get("vendorId")
        if not vendor_id:
            return res("Transporter (vendorId) is required", [], 400)
        if not data.get("projectCode"):
            return res("projectCode is required", [], 400)
        if not data.get("billDate"):
            return res("billDate is required", [], 400)

        # Duplicate invoice check
        vendor_invoice_no = data.get("vendorInvoiceNo")
        if vendor_invoice_no:
            existing = LogisticsBill.query.filter_by(
                vendor_id=int(vendor_id),
                vendor_invoice_no=vendor_invoice_no,
            ).first()
            if existing:
                return res(
                    f"Invoice {vendor_invoice_no} already exists for this vendor (Bill: {existing.lb_no})",
                    [], 400
                )

        dc_ids_raw = data.get("dcIds", "[]")
        if isinstance(dc_ids_raw, str):
            dc_ids = json.loads(dc_ids_raw)
        else:
            dc_ids = dc_ids_raw or []

        lb_no = generate_lb_no()
        new_uuid = str(_uuid.uuid4())

        attached_doc = None
        if files:
            doc_file = files.get("attachedDoc")
            if doc_file:
                attached_doc = upload_file_to_bunny(
                    file=doc_file,
                    mainFolder="logistics_bill",
                    subFolder=lb_no,
                    fileName="attached_doc"
                )

        amounts = _compute_amounts(data)

        lb = LogisticsBill(
            lb_no=lb_no,
            lb_uuid=new_uuid,
            bill_date=data.get("billDate"),
            project_code=data.get("projectCode"),
            vendor_id=int(vendor_id),
            vendor_invoice_no=vendor_invoice_no,
            vendor_invoice_date=data.get("vendorInvoiceDate") or None,
            freight_basis=data.get("freightBasis"),
            basic_freight=Decimal(str(data.get("basicFreight") or 0)),
            loading_charges=Decimal(str(data.get("loadingCharges") or 0)),
            unloading_charges=Decimal(str(data.get("unloadingCharges") or 0)),
            waiting_charges=Decimal(str(data.get("waitingCharges") or 0)),
            toll_charges=Decimal(str(data.get("tollCharges") or 0)),
            other_charges_description=data.get("otherChargesDescription"),
            other_charges=Decimal(str(data.get("otherCharges") or 0)),
            gst_type=data.get("gstType", "IGST"),
            taxable_amount=amounts["taxable_amount"],
            igst_percent=amounts["igst_percent"],
            igst_amount=amounts["igst_amount"],
            cgst_percent=amounts["cgst_percent"],
            cgst_amount=amounts["cgst_amount"],
            sgst_percent=amounts["sgst_percent"],
            sgst_amount=amounts["sgst_amount"],
            tds_percent=amounts["tds_percent"],
            tds_amount=amounts["tds_amount"],
            total_amount=amounts["total_amount"],
            net_payable=amounts["net_payable"],
            payment_status="Unpaid",
            remarks=data.get("remarks"),
            attached_doc=attached_doc,
            workflow_status="Draft",
            current_level=0,
            locked=False,
            created_by=user_id,
        )

        db.session.add(lb)
        db.session.flush()

        dc_remarks_raw = data.get("dcRemarks", "{}")
        if isinstance(dc_remarks_raw, str):
            dc_remarks = json.loads(dc_remarks_raw)
        else:
            dc_remarks = dc_remarks_raw or {}

        for dc_id in dc_ids:
            lbc = LogisticsBillChallan(
                lb_id=lb.id,
                dc_id=int(dc_id),
                billing_remarks=dc_remarks.get(str(dc_id)),
            )
            db.session.add(lbc)

        db.session.commit()
        return res("Logistics Bill created", {"lbId": lb.id, "lbNo": lb.lb_no, "uuid": lb.lb_uuid}, 201)

    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# UPDATE LOGISTICS BILL
# ══════════════════════════════════════════════════════════════════

def update_lb(lb_id, data, user_id, files=None):
    try:
        lb = LogisticsBill.query.get(lb_id)
        if not lb:
            return res("Logistics Bill not found", [], 404)
        if lb.workflow_status not in ("Draft", "Correction"):
            return res("Cannot edit a submitted/approved bill", [], 400)
        if lb.locked:
            return res("Bill is locked", [], 400)

        # Duplicate invoice check (excluding self)
        vendor_invoice_no = data.get("vendorInvoiceNo")
        if vendor_invoice_no and vendor_invoice_no != lb.vendor_invoice_no:
            existing = LogisticsBill.query.filter(
                LogisticsBill.vendor_id == lb.vendor_id,
                LogisticsBill.vendor_invoice_no == vendor_invoice_no,
                LogisticsBill.id != lb_id,
            ).first()
            if existing:
                return res(f"Invoice {vendor_invoice_no} already exists (Bill: {existing.lb_no})", [], 400)

        if files:
            doc_file = files.get("attachedDoc")
            if doc_file:
                lb.attached_doc = upload_file_to_bunny(
                    file=doc_file, mainFolder="logistics_bill",
                    subFolder=lb.lb_no, fileName="attached_doc"
                )
        if str(data.get("clearAttachedDoc", "")).lower() == "true":
            lb.attached_doc = None

        lb.bill_date = data.get("billDate") or lb.bill_date
        lb.vendor_invoice_no = vendor_invoice_no or lb.vendor_invoice_no
        lb.vendor_invoice_date = data.get("vendorInvoiceDate") or lb.vendor_invoice_date
        if "freightBasis" in data: lb.freight_basis = data.get("freightBasis") or lb.freight_basis
        lb.basic_freight = Decimal(str(data.get("basicFreight") or lb.basic_freight))
        lb.loading_charges = Decimal(str(data.get("loadingCharges") or lb.loading_charges))
        lb.unloading_charges = Decimal(str(data.get("unloadingCharges") or lb.unloading_charges))
        lb.waiting_charges = Decimal(str(data.get("waitingCharges") or lb.waiting_charges))
        if "tollCharges" in data: lb.toll_charges = Decimal(str(data.get("tollCharges") or 0))
        lb.other_charges_description = data.get("otherChargesDescription", lb.other_charges_description)
        lb.other_charges = Decimal(str(data.get("otherCharges") or lb.other_charges))
        lb.gst_type = data.get("gstType", lb.gst_type)
        lb.remarks = data.get("remarks", lb.remarks)
        lb.updated_by = user_id
        lb.updated_at = datetime.utcnow()

        amounts = _compute_amounts({
            "basicFreight":    float(lb.basic_freight),
            "loadingCharges":  float(lb.loading_charges),
            "unloadingCharges":float(lb.unloading_charges),
            "waitingCharges":  float(lb.waiting_charges),
            "tollCharges":     float(lb.toll_charges or 0),
            "otherCharges":    float(lb.other_charges),
            "gstType":         lb.gst_type,
            "igstPercent":     float(data.get("igstPercent") or lb.igst_percent),
            "cgstPercent":     float(data.get("cgstPercent") or lb.cgst_percent),
            "sgstPercent":     float(data.get("sgstPercent") or lb.sgst_percent),
            "tdsPercent":      float(data.get("tdsPercent") or lb.tds_percent),
        })

        lb.taxable_amount  = amounts["taxable_amount"]
        lb.igst_percent    = amounts["igst_percent"]
        lb.igst_amount     = amounts["igst_amount"]
        lb.cgst_percent    = amounts["cgst_percent"]
        lb.cgst_amount     = amounts["cgst_amount"]
        lb.sgst_percent    = amounts["sgst_percent"]
        lb.sgst_amount     = amounts["sgst_amount"]
        lb.tds_percent     = amounts["tds_percent"]
        lb.tds_amount      = amounts["tds_amount"]
        lb.total_amount    = amounts["total_amount"]
        lb.net_payable     = amounts["net_payable"]

        # Update DC links
        dc_ids_raw = data.get("dcIds")
        if dc_ids_raw is not None:
            if isinstance(dc_ids_raw, str):
                dc_ids = json.loads(dc_ids_raw)
            else:
                dc_ids = dc_ids_raw

            for old_link in lb.challans:
                db.session.delete(old_link)
            db.session.flush()

            dc_remarks_raw = data.get("dcRemarks", "{}")
            dc_remarks = json.loads(dc_remarks_raw) if isinstance(dc_remarks_raw, str) else (dc_remarks_raw or {})

            for dc_id in dc_ids:
                db.session.add(LogisticsBillChallan(
                    lb_id=lb.id,
                    dc_id=int(dc_id),
                    billing_remarks=dc_remarks.get(str(dc_id)),
                ))

        db.session.commit()
        return res("Logistics Bill updated", {"lbId": lb.id}, 200)

    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# LIST
# ══════════════════════════════════════════════════════════════════

def get_lb_list(data):
    try:
        project_code = data.get("projectCode")
        query = LogisticsBill.query
        if project_code:
            query = query.filter(LogisticsBill.project_code == project_code)
        if data.get("workflowStatus"):
            query = query.filter(LogisticsBill.workflow_status == data["workflowStatus"])
        if data.get("paymentStatus"):
            query = query.filter(LogisticsBill.payment_status == data["paymentStatus"])
        if data.get("vendorId"):
            query = query.filter(LogisticsBill.vendor_id == int(data["vendorId"]))
        if data.get("search"):
            s = f"%{data['search']}%"
            query = query.filter(
                (LogisticsBill.lb_no.ilike(s)) |
                (LogisticsBill.vendor_invoice_no.ilike(s))
            )

        rows = query.order_by(LogisticsBill.id.desc()).all()

        result = []
        for row in rows:
            vendor_name = row.vendor.ledger_name if row.vendor else None
            result.append({
                "id":               row.id,
                "lbNo":             row.lb_no,
                "billDate":         _fmt_date(row.bill_date),
                "projectCode":      row.project_code,
                "vendorId":         row.vendor_id,
                "vendorName":       vendor_name,
                "vendorInvoiceNo":  row.vendor_invoice_no,
                "vendorInvoiceDate":_fmt_date(row.vendor_invoice_date),
                "noOfChallans":     len(row.challans),
                "taxableAmount":    float(row.taxable_amount or 0),
                "totalAmount":      float(row.total_amount or 0),
                "netPayable":       float(row.net_payable or 0),
                "workflowStatus":   row.workflow_status,
                "paymentStatus":    row.payment_status,
            })

        return res("Logistics Bills fetched", result, 200)

    except Exception as e:
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# DETAIL
# ══════════════════════════════════════════════════════════════════

def get_lb_detail(lb_id):
    try:
        lb = LogisticsBill.query.get(lb_id)
        if not lb:
            return res("Logistics Bill not found", [], 404)

        challans = []
        for lbc in lb.challans:
            dc = lbc.dc
            challans.append({
                "lbcId":         lbc.id,
                "dcId":          dc.id,
                "dcNo":          dc.dc_no,
                "challanDate":   _fmt_date(dc.challan_date),
                "orderType":     dc.order_type,
                "orderNo":       dc.order.order_no if dc.order else None,
                "fromName":      dc.from_vendor.ledger_name if dc.from_vendor else dc.from_project_code,
                "toProjectCode": dc.to_project_code,
                "noOfItems":     len(dc.items),
                "workflowStatus":dc.workflow_status,
                "billingRemarks":lbc.billing_remarks,
            })

        def _user_name(user):
            if not user:
                return None
            return f"{user.first_name or ''} {user.last_name or ''}".strip() or user.username

        vendor = lb.vendor
        vendor_data = None
        if vendor:
            vendor_data = {
                "id":          vendor.id,
                "ledgerCode":  vendor.ledger_code,
                "ledgerName":  vendor.ledger_name,
                "gstin":       vendor.gstin,
                "address":     vendor.registered_address,
                "stateCode":   vendor.state_code,
                "stateName":   vendor.state_name,
            }

        lb_uuid_val = _ensure_lb_uuid(lb)
        data = {
            "id":               lb.id,
            "lbNo":             lb.lb_no,
            "lbUuid":           lb_uuid_val,
            "uuid":             lb_uuid_val,
            "billDate":         _fmt_date(lb.bill_date),
            "projectCode":      lb.project_code,
            "vendor":           vendor_data,
            "vendorId":         lb.vendor_id,
            "vendorInvoiceNo":  lb.vendor_invoice_no,
            "vendorInvoiceDate":_fmt_date(lb.vendor_invoice_date),
            "freightBasis":     lb.freight_basis,
            "basicFreight":     float(lb.basic_freight or 0),
            "loadingCharges":   float(lb.loading_charges or 0),
            "unloadingCharges": float(lb.unloading_charges or 0),
            "waitingCharges":   float(lb.waiting_charges or 0),
            "tollCharges":      float(lb.toll_charges or 0),
            "otherChargesDescription": lb.other_charges_description,
            "otherCharges":     float(lb.other_charges or 0),
            "taxableAmount":    float(lb.taxable_amount or 0),
            "gstType":          lb.gst_type,
            "igstPercent":      float(lb.igst_percent or 0),
            "igstAmount":       float(lb.igst_amount or 0),
            "cgstPercent":      float(lb.cgst_percent or 0),
            "cgstAmount":       float(lb.cgst_amount or 0),
            "sgstPercent":      float(lb.sgst_percent or 0),
            "sgstAmount":       float(lb.sgst_amount or 0),
            "tdsPercent":       float(lb.tds_percent or 0),
            "tdsAmount":        float(lb.tds_amount or 0),
            "totalAmount":      float(lb.total_amount or 0),
            "netPayable":       float(lb.net_payable or 0),
            "paymentStatus":    lb.payment_status,
            "voucherId":        lb.voucher_id,
            "remarks":          lb.remarks,
            "attachedDoc":      lb.attached_doc,
            "workflowStatus":   lb.workflow_status,
            "currentLevel":     lb.current_level,
            "locked":           lb.locked,
            "challans":         challans,
            "createdBy":        _user_name(lb.creator),
            "createdAt":        _fmt_datetime(lb.created_at),
            "submittedBy":      _user_name(lb.submitter),
            "submittedAt":      _fmt_datetime(lb.submitted_at),
            "approvedBy":       _user_name(lb.approver),
            "finalApprovedAt":  _fmt_datetime(lb.final_approved_at),
            "rejectedBy":       _user_name(lb.rejector),
            "rejectedAt":       _fmt_datetime(lb.rejected_at),
        }

        return res("Logistics Bill fetched", data, 200)

    except Exception as e:
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# WORKFLOW
# ══════════════════════════════════════════════════════════════════

def submit_lb(lb_id, submitted_by):
    try:
        lb = LogisticsBill.query.get(lb_id)
        if not lb:
            return res("Logistics Bill not found", [], 404)
        if lb.workflow_status not in ("Draft", "Correction"):
            return res("Only Draft or Correction bills can be submitted", [], 400)

        first = get_first_approver(lb.project_code, MODULE_CODE)
        lb.submitted_by = submitted_by
        lb.submitted_at = datetime.utcnow()

        if not first:
            # No approval path → auto-approve
            lb.workflow_status = "Approved"
            lb.approved_by = submitted_by
            lb.final_approved_at = datetime.utcnow()
            lb.current_level = 0
            lb.locked = True
            if not lb.voucher_id:
                lb.voucher_id = -lb.id
        else:
            lb.workflow_status = f"Pending_L{first.level_no}"
            lb.current_level = first.level_no
            lb.locked = True

        create_history(module_code=MODULE_CODE, record_id=lb.id, action="Submitted", done_by=submitted_by)
        db.session.commit()
        wa.on_submit(lb.id, MODULE_CODE)
        return res("Logistics Bill submitted", {}, 200)

    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


def approve_lb(lb_id, approved_by, comments=None):
    try:
        lb = LogisticsBill.query.get(lb_id)
        if not lb:
            return res("Logistics Bill not found", [], 404)
        if not (lb.workflow_status or "").startswith("Pending"):
            return res("Only Pending bills can be approved", [], 400)

        if not is_current_approver(lb.project_code, MODULE_CODE, lb.current_level, approved_by):
            return res("You are not the current approver", [], 403)

        next_approver = get_next_approver(lb.project_code, MODULE_CODE, lb.current_level)
        create_history(module_code=MODULE_CODE, record_id=lb.id, action="Approved",
                       done_by=approved_by, comments=comments, level=lb.current_level)

        if next_approver:
            lb.current_level = next_approver.level_no
            lb.workflow_status = f"Pending_L{next_approver.level_no}"
            db.session.commit()
            wa.on_approve(lb.id, MODULE_CODE)
        else:
            lb.workflow_status = "Approved"
            lb.approved_by = approved_by
            lb.final_approved_at = datetime.utcnow()
            lb.locked = True

            # Mark the bill as posted to AP. voucher_id will be populated by the
            # finance module's AP posting hook when it wires the journal.
            # Until then, a non-null placeholder prevents accidental deletion.
            if not lb.voucher_id:
                lb.voucher_id = -lb.id  # negative marker: "posted, journal TBD"

            db.session.commit()
            wa.on_final_approve(lb.id, MODULE_CODE)

        return res("Logistics Bill approved", {}, 200)

    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


def reback_lb(lb_id, reback_by, comments=None):
    try:
        lb = LogisticsBill.query.get(lb_id)
        if not lb:
            return res("Logistics Bill not found", [], 404)
        if not (lb.workflow_status or "").startswith("Pending"):
            return res("Only Pending bills can be sent for correction", [], 400)

        if not is_current_approver(lb.project_code, MODULE_CODE, lb.current_level, reback_by):
            return res("You are not the current approver", [], 403)

        lb.workflow_status = "Correction"
        lb.current_level = 0
        lb.locked = False
        lb.correction_sent_at = datetime.utcnow()

        create_history(module_code=MODULE_CODE, record_id=lb.id, action="Reback",
                       done_by=reback_by, comments=comments)
        db.session.commit()
        wa.on_reback(lb.id, MODULE_CODE)
        return res("Logistics Bill sent for correction", {}, 200)

    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


def reject_lb(lb_id, rejected_by, comments=None):
    try:
        lb = LogisticsBill.query.get(lb_id)
        if not lb:
            return res("Logistics Bill not found", [], 404)
        if not (lb.workflow_status or "").startswith("Pending"):
            return res("Only Pending bills can be rejected", [], 400)

        if not is_current_approver(lb.project_code, MODULE_CODE, lb.current_level, rejected_by):
            return res("You are not the current approver", [], 403)

        lb.workflow_status = "Rejected"
        lb.rejected_by = rejected_by
        lb.rejected_at = datetime.utcnow()
        lb.locked = False

        create_history(module_code=MODULE_CODE, record_id=lb.id, action="Rejected",
                       done_by=rejected_by, comments=comments)
        db.session.commit()
        wa.on_reject(lb.id, MODULE_CODE)
        return res("Logistics Bill rejected", {}, 200)

    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


def get_lb_history(lb_id):
    try:
        lb = LogisticsBill.query.get(lb_id)
        if not lb:
            return res("Logistics Bill not found", [], 404)

        history = get_history(MODULE_CODE, lb_id)
        steps = get_approval_steps(lb.project_code, MODULE_CODE)
        return res("History fetched", {"history": history, "steps": steps}, 200)

    except Exception as e:
        return res(str(e), [], 500)


def get_lb_my_approval_status(lb_id, user_id):
    try:
        lb = LogisticsBill.query.get(lb_id)
        if not lb:
            return res("Logistics Bill not found", [], 404)

        status = get_my_approval_status(
            project_code=lb.project_code,
            module_code=MODULE_CODE,
            record=lb,
            user_id=user_id,
        )
        return res("Approval status fetched", status, 200)

    except Exception as e:
        return res(str(e), [], 500)


def delete_lb(lb_id):
    """Delete chain protection:
       - Draft (voucher not posted)  → delete allowed.
       - Approved with voucher_id    → BLOCK. Caller must reverse the voucher
                                       first (finance module), which nulls
                                       voucher_id, then delete can proceed.
    """
    try:
        lb = LogisticsBill.query.get(lb_id)
        if not lb:
            return res("Logistics Bill not found", [], 404)
        if lb.voucher_id:
            return res(
                "This Bill is posted to Finance. "
                "Reverse the linked voucher in Finance before deleting.",
                [], 400,
            )
        if lb.workflow_status not in ("Draft",):
            return res("Only Draft bills can be deleted", [], 400)
        if lb.locked:
            return res("Bill is locked", [], 400)

        db.session.delete(lb)
        db.session.commit()
        return res("Logistics Bill deleted", {}, 200)

    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)
