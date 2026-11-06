from decimal import Decimal
from sqlalchemy import func
from sqlalchemy.exc import SQLAlchemyError
from app.extensions import db
from datetime import datetime
import uuid as _uuid

from app.models.saleBill import SaleBillMaster, SaleBillItem, SaleBillGst, SaleBillSource
from app.models.billingMaster import BillingMaster, BillingBoqItem
from app.models.ogSaleOrder import OgSaleOrderMaster
from app.models.cc_code import CCCode
from app.models.bankCash import BankCash
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
from app.models.user import User
from app.modules.communication import whatsapp_events as wa
from app.utils.date_utils import parse_date

_MODULE      = "sale"
VALID_MODES  = ("Sale Invoice", "Proforma Invoice")


# ══════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════

def _fmt_date(d):
    if d is None:
        return None
    if isinstance(d, datetime):
        return d.strftime("%Y-%m-%d %H:%M")
    return d.strftime("%Y-%m-%d")


def _fy_prefix(invoice_date):
    """Return e.g. '2627DH' for a date in FY 2026-27 (Apr 2026 – Mar 2027)."""
    y, m = invoice_date.year, invoice_date.month
    fy_start = y if m >= 4 else y - 1
    fy_end   = fy_start + 1
    return f"{str(fy_start)[-2:]}{str(fy_end)[-2:]}DH"


def generate_sale_bill_no(project_code, invoice_date):
    prefix = _fy_prefix(invoice_date)
    count = (
        db.session.query(func.count(SaleBillMaster.id))
        .filter(SaleBillMaster.project_code == project_code)
        .scalar()
    ) or 0
    return f"{prefix}{str(count + 1).zfill(3)}{project_code}"


def _expand_items(billing_items, already_billed_map=None):
    """
    Return individual billing items with their GST rates.
    already_billed_map: {billing_item_id: Decimal} of amounts already invoiced.
    """
    result = []
    if already_billed_map is None:
        already_billed_map = {}

    for idx, bi in enumerate(billing_items):
        original    = Decimal(str(bi.amount or 0))
        gst_pct     = Decimal(str(bi.gst_percent or 0))
        already     = already_billed_map.get(bi.id, Decimal("0"))
        remaining   = max(original - already, Decimal("0"))

        status = "UNBILLED"
        if already >= original and original > 0:
            status = "FULLY_BILLED"
        elif already > 0:
            status = "PARTIALLY_BILLED"

        result.append({
            "billingItemId": bi.id,
            "slNo":          idx + 1,
            "itemCode":      getattr(bi, "item_code", None) or "",
            "itemName":      getattr(bi, "item_name", None) or "",
            "description":   getattr(bi, "item_name_desc", None) or "",
            "unit":          getattr(bi, "unit", None) or "",
            "claimQty":      float(getattr(bi, "claim_qty", 0) or 0),
            "rate":          float(getattr(bi, "rate", 0) or 0),
            "hsnSac":        "",
            "originalAmount": float(original),
            "alreadyBilled":  float(already),
            "remaining":      float(remaining),
            "gstPercent":     float(gst_pct),
            "billingStatus":  status,
        })
    return result


def _group_by_cc(billing_items):
    """Consolidate all certified bill items under the CRIN CC code (legacy helper)."""
    crin = CCCode.query.filter_by(cc_code="CRIN").first()
    cc_code = crin.cc_code if crin else "CRIN"
    cc_name = crin.cc_name if crin else "CRIN"

    total_basic = Decimal('0')
    total_gst   = Decimal('0')
    for bi in billing_items:
        total_basic += Decimal(str(bi.amount     or 0))
        total_gst   += Decimal(str(bi.gst_amount or 0))

    items = [
        {
            "slNo":        1,
            "ccCode":      cc_code,
            "ccName":      cc_name,
            "description": "",
            "hsnSac":      "",
            "basicAmount": float(total_basic),
        }
    ]

    gst_lines = []
    if total_gst > 0 and total_basic > 0:
        eff_pct  = (total_gst / total_basic * 100).quantize(Decimal("0.01"))
        half_pct = (eff_pct / 2).quantize(Decimal("0.01"))
        half_amt = (total_gst / 2).quantize(Decimal("0.01"))
        gst_lines = [
            {"gstType": "SGST", "ccCode": cc_code, "ccName": cc_name, "percent": float(half_pct), "gstAmount": float(half_amt), "isSelected": False},
            {"gstType": "CGST", "ccCode": cc_code, "ccName": cc_name, "percent": float(half_pct), "gstAmount": float(half_amt), "isSelected": False},
            {"gstType": "IGST", "ccCode": cc_code, "ccName": cc_name, "percent": float(eff_pct),  "gstAmount": float(total_gst),  "isSelected": True},
        ]

    return items, gst_lines


def _get_cert_bill_billed_amounts(cert_bill_id):
    """
    Return dict {billing_item_id: Decimal(billed_amount)} from active (non-Rejected) sale bills.
    """
    rows = (
        db.session.query(SaleBillItem.billing_item_id, func.coalesce(func.sum(SaleBillItem.basic_amount), 0))
        .join(SaleBillSource, SaleBillSource.id == SaleBillItem.source_id)
        .join(SaleBillMaster, SaleBillMaster.id == SaleBillItem.sale_bill_id)
        .filter(
            SaleBillSource.certified_bill_id == cert_bill_id,
            SaleBillMaster.workflow_status   != "Rejected",
        )
        .group_by(SaleBillItem.billing_item_id)
        .all()
    )
    return {r[0]: Decimal(str(r[1])) for r in rows if r[0] is not None}


def _get_cert_bill_total_billed(cert_bill_id):
    """Sum of basic_amount billed from a cert bill across all active sale bills."""
    total = db.session.query(
        func.coalesce(func.sum(SaleBillSource.basic_amount), 0)
    ).join(
        SaleBillMaster, SaleBillMaster.id == SaleBillSource.sale_bill_id
    ).filter(
        SaleBillSource.certified_bill_id == cert_bill_id,
        SaleBillMaster.workflow_status   != "Rejected",
    ).scalar()
    return Decimal(str(total))


def _build_detail_payload(bill):
    # Build source index map for items
    source_id_to_index = {s.id: idx for idx, s in enumerate(bill.sources)}

    return {
        "id":                  bill.id,
        "saleBillNo":          bill.sale_bill_no,
        "saleBillUuid":        bill.sale_bill_uuid,
        "mode":                bill.mode,
        "invoiceDate":         _fmt_date(bill.invoice_date),
        "referenceNo":         bill.reference_no,
        "referenceDate":       _fmt_date(bill.reference_date),
        # Legacy single-source fields (kept for backward compat)
        "saleOrderNo":         bill.sale_order_no,
        "saleOrderId":         bill.sale_order_id,
        "certifiedBillId":     bill.certified_bill_id,
        "certifiedBillNo":     bill.certified_bill_no,
        "projectCode":         bill.project_code,
        "billToAddress":       bill.bill_to_address,
        "shipToAddress":       bill.ship_to_address,
        "billAbstractNo":      bill.bill_abstract_no,
        "billAbstractDate":    _fmt_date(bill.bill_abstract_date),
        "bankAc":              bill.bank_ac,
        "bankAcId":            bill.bank_ac_id,
        "bankAcName":          bill.bank_account.bank_holder_name if bill.bank_account else None,
        "bankCode":            bill.bank_account.bank_code        if bill.bank_account else None,
        "paymentTerms":        bill.payment_terms,
        "declaration":         bill.declaration,
        "basicAmount":         float(bill.basic_amount         or 0),
        "gstAmount":           float(bill.gst_amount           or 0),
        "discount":            float(bill.discount             or 0),
        "roundOff":            float(bill.round_off            or 0),
        "totalInvoiceAmount":  float(bill.total_invoice_amount or 0),
        "workflowStatus":      bill.workflow_status,
        "currentLevel":        bill.current_level,
        "locked":              bill.locked,
        "createdBy":           bill.creator.username   if bill.creator   else None,
        "createdAt":           _fmt_date(bill.created_at),
        "submittedBy":         bill.submitter.username if bill.submitter else None,
        "submittedAt":         _fmt_date(bill.submitted_at),
        "approvedBy":          bill.approver.username  if bill.approver  else None,
        "finalApprovedAt":     _fmt_date(bill.final_approved_at),
        "rejectedBy":          bill.rejector.username  if bill.rejector  else None,
        "rejectedAt":          _fmt_date(bill.rejected_at),
        # Multi-source list (new)
        "sources": [
            {
                "id":               s.id,
                "saleOrderId":      s.sale_order_id,
                "saleOrderNo":      s.sale_order_no,
                "certifiedBillId":  s.certified_bill_id,
                "certifiedBillNo":  s.certified_bill_no,
                "billingDate":      _fmt_date(s.billing_date),
                "basicAmount":      float(s.basic_amount or 0),
            }
            for s in bill.sources
        ],
        "items": [
            {
                "id":             i.id,
                "slNo":           i.sl_no,
                "ccCode":         i.cc_code,
                "ccName":         i.cc_name,
                "description":    i.description,
                "hsnSac":         i.hsn_sac,
                "basicAmount":    float(i.basic_amount or 0),
                "gstPercent":     float(i.gst_percent  or 0),
                "billingItemId":  i.billing_item_id,
                "sourceId":       i.source_id,
                "sourceIndex":    source_id_to_index.get(i.source_id),
            }
            for i in bill.items
        ],
        "gstLines": [
            {
                "id":          g.id,
                "gstType":     g.gst_type,
                "ccCode":      g.cc_code,
                "ccName":      g.cc_name,
                "description": g.description,
                "percent":     float(g.percent    or 0),
                "gstAmount":   float(g.gst_amount or 0),
                "isSelected":  g.is_selected,
            }
            for g in bill.gst_lines
        ],
    }


# ══════════════════════════════════════════════════════════════════
# 1. CERTIFIED BILLS LOOKUP
# ══════════════════════════════════════════════════════════════════

def get_certified_bills_for_order(data):
    """
    Return Approved certified bills for a sale order with their partial billing balances.
    Supports partial billing: a cert bill is shown even if previously partially invoiced.
    Only fully-billed cert bills are excluded (remaining == 0).
    """
    try:
        erp_no       = (data.get("erpDocNumber") or "").strip()
        project_code = (data.get("projectCode")  or "").strip()

        if not erp_no:
            return res("erpDocNumber required", [], 400)
        if not project_code:
            return res("projectCode required", [], 400)

        bills = BillingMaster.query.filter(
            BillingMaster.og_sale_order_erp_no == erp_no,
            BillingMaster.project_code         == project_code,
            BillingMaster.mode                 == "sale_certified_bill",
            BillingMaster.workflow_status       == "Approved",
        ).order_by(BillingMaster.id.asc()).all()

        # Deduplicate by billing_no: keep latest per billing_no
        latest_by_billing_no = {}
        for b in bills:
            key = b.billing_no or b.erp_no or str(b.id)
            if key not in latest_by_billing_no or b.id > latest_by_billing_no[key].id:
                latest_by_billing_no[key] = b

        result = []
        for b in latest_by_billing_no.values():
            original      = Decimal(str(b.this_bill_claim or 0))
            already_billed = _get_cert_bill_total_billed(b.id)
            remaining      = max(original - already_billed, Decimal("0"))

            status = "UNBILLED"
            if already_billed >= original and original > 0:
                status = "FULLY_BILLED"
            elif already_billed > 0:
                status = "PARTIALLY_BILLED"

            result.append({
                "id":              b.id,
                "billingNo":       b.billing_no or b.erp_no,
                "erpNo":           b.erp_no,
                "billingDate":     _fmt_date(b.billing_date),
                "thisBillClaim":   float(original),
                "alreadyBilled":   float(already_billed),
                "remaining":       float(remaining),
                "billingStatus":   status,
            })

        return res("Certified bills fetched", result, 200)

    except ValueError as e:
        db.session.rollback()
        return res(str(e), [], 400)
    except Exception as e:
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 2. ITEMS GROUPED BY CC CODE
# ══════════════════════════════════════════════════════════════════

def get_certified_bill_items_grouped(data):
    """
    Fetch items from an approved certified bill with individual item detail and
    partial billing balances. Each item shows originalAmount, alreadyBilled, remaining.
    """
    try:
        certified_bill_id = data.get("certifiedBillId")
        project_code      = (data.get("projectCode") or "").strip()

        if not certified_bill_id:
            return res("certifiedBillId required", [], 400)
        if not project_code:
            return res("projectCode required", [], 400)

        bill = BillingMaster.query.filter_by(
            id              = int(certified_bill_id),
            mode            = "sale_certified_bill",
            workflow_status = "Approved",
        ).first()

        if not bill:
            return res("Approved certified bill not found", [], 404)
        if bill.project_code != project_code:
            return res("Certified bill does not belong to this project", [], 403)

        already_billed_map = _get_cert_bill_billed_amounts(bill.id)
        total_billed       = _get_cert_bill_total_billed(bill.id)

        all_items = list(bill.items) + list(BillingBoqItem.query.filter_by(billing_id=bill.id).all())
        items = _expand_items(all_items, already_billed_map)

        # Build aggregate GST lines for the right panel (grouped by rate)
        total_basic = Decimal(str(bill.this_bill_claim or 0))
        total_gst   = sum(Decimal(str(bi.gst_amount or 0)) for bi in all_items)
        _, gst_lines = _group_by_cc(all_items)

        original  = Decimal(str(bill.this_bill_claim or 0))
        remaining = max(original - total_billed, Decimal("0"))

        return res("Certified bill items fetched", {
            "certifiedBillId":  bill.id,
            "certifiedErpDocNo": bill.erp_no,
            "billingNo":        bill.billing_no or bill.erp_no,
            "ogSaleOrderNo":    bill.og_sale_order_erp_no,
            "thisBillClaim":    float(original),
            "alreadyBilled":    float(total_billed),
            "remaining":        float(remaining),
            "items":            items,
            "gstLines":         gst_lines,
        }, 200)

    except ValueError as e:
        db.session.rollback()
        return res(str(e), [], 400)
    except Exception as e:
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 3. CREATE
# ══════════════════════════════════════════════════════════════════

def _resolve_sources(data, project_code, exclude_sale_bill_id=None):
    """
    Normalise the incoming payload to a list of source dicts.
    Supports both old single-source (certifiedBillId) and new multi-source (sources[]).
    Validates partial billing: basicAmount for each cert bill must not exceed remaining balance.
    Returns (sources_data, first_cert_bill_or_None, error_response_or_None).
    """
    raw_sources = data.get("sources")
    if raw_sources:
        if not isinstance(raw_sources, list) or len(raw_sources) == 0:
            return None, None, res("sources must be a non-empty list", [], 400)
    else:
        # backward-compat: wrap legacy single fields
        cert_id = data.get("certifiedBillId")
        if not cert_id:
            return None, None, res("sources (or certifiedBillId) required", [], 400)
        raw_sources = [{
            "certifiedBillId": cert_id,
            "certifiedBillNo": data.get("certifiedBillNo"),
            "saleOrderId":     data.get("saleOrderId"),
            "saleOrderNo":     data.get("saleOrderNo"),
        }]

    validated = []
    first_cert_bill = None
    seen_cert_ids = set()

    for idx, src in enumerate(raw_sources):
        cert_id = src.get("certifiedBillId")
        if not cert_id:
            return None, None, res(f"sources[{idx}].certifiedBillId required", [], 400)
        if int(cert_id) in seen_cert_ids:
            return None, None, res(f"Duplicate certifiedBillId {cert_id} in sources", [], 400)
        seen_cert_ids.add(int(cert_id))

        cert_bill = BillingMaster.query.filter_by(
            id=int(cert_id),
            mode="sale_certified_bill",
            workflow_status="Approved",
        ).first()
        if not cert_bill:
            return None, None, res(f"Approved certified bill {cert_id} not found", [], 404)
        if cert_bill.project_code != project_code:
            return None, None, res(f"Certified bill {cert_id} does not belong to this project", [], 403)

        basic_amount = Decimal(str(src.get("basicAmount") or 0))

        # Validate partial billing balance
        # When editing, exclude the current sale bill's own sources from the already-billed sum
        already_billed = _get_cert_bill_total_billed_excluding(cert_bill.id, exclude_sale_bill_id)
        original       = Decimal(str(cert_bill.this_bill_claim or 0))
        remaining      = max(original - already_billed, Decimal("0"))

        if basic_amount <= 0:
            return None, None, res(
                f"sources[{idx}] basicAmount must be greater than zero", [], 400
            )
        if basic_amount > remaining + Decimal("0.01"):  # 0.01 tolerance for rounding
            return None, None, res(
                f"sources[{idx}] basicAmount ({basic_amount}) exceeds remaining balance "
                f"({remaining}) for certified bill {cert_bill.billing_no or cert_bill.erp_no}",
                [], 400,
            )

        if first_cert_bill is None:
            first_cert_bill = cert_bill

        validated.append({
            "cert_bill":     cert_bill,
            "sale_order_id": src.get("saleOrderId") or cert_bill.og_sale_order_id,
            "sale_order_no": src.get("saleOrderNo") or cert_bill.og_sale_order_erp_no,
            "basic_amount":  basic_amount,
        })

    return validated, first_cert_bill, None


def _get_cert_bill_total_billed_excluding(cert_bill_id, exclude_sale_bill_id=None):
    """
    Sum of basicAmount billed from a cert bill across active sale bills,
    optionally excluding a specific sale bill (for edits).
    """
    q = db.session.query(
        func.coalesce(func.sum(SaleBillSource.basic_amount), 0)
    ).join(
        SaleBillMaster, SaleBillMaster.id == SaleBillSource.sale_bill_id
    ).filter(
        SaleBillSource.certified_bill_id == cert_bill_id,
        SaleBillMaster.workflow_status   != "Rejected",
    )
    if exclude_sale_bill_id:
        q = q.filter(SaleBillMaster.id != int(exclude_sale_bill_id))
    return Decimal(str(q.scalar()))


def create_sale_bill(data, user_id):
    try:
        project_code = data.get("projectCode")
        if not project_code:
            return res("projectCode required", [], 400)

        mode = (data.get("mode") or "").strip()
        if mode not in VALID_MODES:
            return res(f"mode must be one of {VALID_MODES}", [], 400)

        allowed = is_creator(project_code, _MODULE, user_id)
        if not allowed:
            return res("You are not authorized to create sale bills", [], 403)

        sources_data, first_cert_bill, err = _resolve_sources(data, project_code)
        if err:
            return err

        items = data.get("items", [])
        if not items:
            return res("At least one BASIC item required", [], 400)

        gst_lines = data.get("gstLines", [])

        basic_total = sum(Decimal(str(i.get("basicAmount") or 0)) for i in items)
        # GST total: sum of per-item GST amounts (item.basicAmount × item.gstPercent / 100)
        gst_total = sum(
            (Decimal(str(i.get("basicAmount") or 0)) * Decimal(str(i.get("gstPercent") or 0)) / 100).quantize(Decimal("0.01"))
            for i in items
        )
        # Fall back to old gst_lines-based computation if no per-item rates
        if gst_total == 0 and gst_lines:
            gst_total = sum(
                Decimal(str(g.get("gstAmount") or 0))
                for g in gst_lines if g.get("isSelected")
            )
        discount  = Decimal(str(data.get("discount")  or 0))
        round_off = Decimal(str(data.get("roundOff")  or 0))
        total     = basic_total + gst_total - discount + round_off

        invoice_date_val = parse_date(data.get("invoiceDate"), "invoiceDate")
        sale_bill_no     = generate_sale_bill_no(project_code, invoice_date_val)
        sale_bill_uuid   = str(_uuid.uuid4())

        # Legacy single-source snapshot from first source (backward compat)
        bill = SaleBillMaster(
            sale_bill_no       = sale_bill_no,
            sale_bill_uuid     = sale_bill_uuid,
            mode               = mode,
            invoice_date       = invoice_date_val,
            reference_no       = data.get("referenceNo"),
            reference_date     = parse_date(data.get("referenceDate"), "referenceDate"),
            sale_order_no      = sources_data[0]["sale_order_no"],
            sale_order_id      = sources_data[0]["sale_order_id"],
            certified_bill_id  = sources_data[0]["cert_bill"].id,
            certified_bill_no  = sources_data[0]["cert_bill"].billing_no or sources_data[0]["cert_bill"].erp_no,
            project_code       = project_code,
            bill_to_address    = data.get("billToAddress"),
            ship_to_address    = data.get("shipToAddress"),
            bill_abstract_no   = data.get("billAbstractNo"),
            bill_abstract_date = parse_date(data.get("billAbstractDate"), "billAbstractDate"),
            bank_ac            = data.get("bankAc"),
            bank_ac_id         = data.get("bankAcId"),
            payment_terms      = data.get("paymentTerms"),
            declaration        = data.get("declaration"),
            basic_amount         = basic_total,
            gst_amount           = gst_total,
            discount             = discount,
            round_off            = round_off,
            total_invoice_amount = total,
            workflow_status = "Draft",
            current_level   = 0,
            locked          = False,
            created_by      = user_id,
        )
        db.session.add(bill)
        db.session.flush()

        # Create source rows and build index→id map
        source_index_to_id = {}
        for idx, src in enumerate(sources_data):
            cert_bill = src["cert_bill"]
            source_row = SaleBillSource(
                sale_bill_id      = bill.id,
                sale_order_id     = src["sale_order_id"],
                sale_order_no     = src["sale_order_no"],
                certified_bill_id = cert_bill.id,
                certified_bill_no = cert_bill.billing_no or cert_bill.erp_no,
                billing_date      = cert_bill.billing_date,
                basic_amount      = src["basic_amount"],
            )
            db.session.add(source_row)
            db.session.flush()
            source_index_to_id[idx] = source_row.id

        for idx, row in enumerate(items, start=1):
            source_index = row.get("sourceIndex")
            source_id = source_index_to_id.get(source_index) if source_index is not None else None
            db.session.add(SaleBillItem(
                sale_bill_id    = bill.id,
                source_id       = source_id,
                sl_no           = row.get("slNo") or idx,
                cc_code         = row.get("ccCode"),
                cc_name         = row.get("ccName"),
                description     = row.get("description"),
                hsn_sac         = row.get("hsnSac"),
                basic_amount    = Decimal(str(row.get("basicAmount") or 0)),
                gst_percent     = Decimal(str(row.get("gstPercent") or 0)),
                billing_item_id = row.get("billingItemId"),
            ))

        for g in gst_lines:
            db.session.add(SaleBillGst(
                sale_bill_id = bill.id,
                gst_type     = g.get("gstType"),
                cc_code      = g.get("ccCode"),
                cc_name      = g.get("ccName"),
                description  = g.get("description"),
                percent      = Decimal(str(g.get("percent")   or 0)),
                gst_amount   = Decimal(str(g.get("gstAmount") or 0)) if g.get("isSelected") else Decimal("0"),
                is_selected  = bool(g.get("isSelected")),
            ))

        db.session.commit()

        return res("Sale bill created", {
            "id":           bill.id,
            "saleBillNo":   bill.sale_bill_no,
            "saleBillUuid": bill.sale_bill_uuid,
            "mode":         bill.mode,
        }, 201)

    except ValueError as e:
        db.session.rollback()
        return res(str(e), [], 400)
    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 4. LIST
# ══════════════════════════════════════════════════════════════════

def get_sale_bill_list(data):
    try:
        project_code = data.get("projectCode")
        if not project_code:
            return res("projectCode required", [], 400)

        query = SaleBillMaster.query.filter(
            SaleBillMaster.project_code == project_code
        )

        if data.get("mode"):
            query = query.filter(SaleBillMaster.mode == data.get("mode"))
        if data.get("workflowStatus"):
            query = query.filter(SaleBillMaster.workflow_status == data.get("workflowStatus"))
        if data.get("saleOrderNo"):
            query = query.filter(
                SaleBillMaster.sale_order_no.ilike(f"%{data.get('saleOrderNo')}%")
            )
        if data.get("search"):
            term = f"%{data.get('search')}%"
            query = query.filter(
                db.or_(
                    SaleBillMaster.sale_bill_no.ilike(term),
                    SaleBillMaster.sale_order_no.ilike(term),
                    SaleBillMaster.certified_bill_no.ilike(term),
                )
            )

        rows = query.order_by(SaleBillMaster.id.desc()).all()

        result = [
            {
                "id":                 r.id,
                "saleBillNo":         r.sale_bill_no,
                "mode":               r.mode,
                "invoiceDate":        _fmt_date(r.invoice_date),
                "saleOrderNo":        r.sale_order_no,
                "certifiedBillNo":    r.certified_bill_no,
                "basicAmount":        float(r.basic_amount         or 0),
                "gstAmount":          float(r.gst_amount           or 0),
                "totalInvoiceAmount": float(r.total_invoice_amount or 0),
                "workflowStatus":     r.workflow_status,
                "createdBy":          r.creator.username if r.creator else None,
                "createdAt":          _fmt_date(r.created_at),
            }
            for r in rows
        ]

        return res("Sale bill list fetched", result, 200)

    except ValueError as e:
        db.session.rollback()
        return res(str(e), [], 400)
    except Exception as e:
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 5. DETAILS
# ══════════════════════════════════════════════════════════════════

def get_sale_bill_details(bill_id):
    try:
        bill = SaleBillMaster.query.get(bill_id)
        if not bill:
            return res("Sale bill not found", [], 404)
        return res("Sale bill details fetched", _build_detail_payload(bill), 200)
    except ValueError as e:
        db.session.rollback()
        return res(str(e), [], 400)
    except Exception as e:
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 6. EDIT
# ══════════════════════════════════════════════════════════════════

def edit_sale_bill(bill_id, data, user_id):
    try:
        bill = SaleBillMaster.query.get(bill_id)
        if not bill:
            return res("Sale bill not found", [], 404)
        if bill.locked:
            return res("Sale bill is locked and cannot be edited", [], 400)
        if bill.workflow_status not in ("Draft", "Reback"):
            return res("Only Draft or Reback records can be edited", [], 400)

        allowed = is_creator(bill.project_code, _MODULE, user_id)
        if not allowed:
            return res("You are not authorized to edit sale bills", [], 403)

        items = data.get("items", [])
        if not items:
            return res("At least one BASIC item required", [], 400)

        gst_lines = data.get("gstLines", [])

        # Update header fields
        if data.get("mode") and data.get("mode") in VALID_MODES:
            bill.mode = data.get("mode")
        if data.get("invoiceDate"):
            bill.invoice_date = parse_date(data.get("invoiceDate"), "invoiceDate")
        if data.get("referenceNo") is not None:
            bill.reference_no = data.get("referenceNo")
        if data.get("referenceDate") is not None:
            bill.reference_date = parse_date(data.get("referenceDate"), "referenceDate")
        if data.get("billToAddress") is not None:
            bill.bill_to_address = data.get("billToAddress")
        if data.get("shipToAddress") is not None:
            bill.ship_to_address = data.get("shipToAddress")
        if data.get("billAbstractNo") is not None:
            bill.bill_abstract_no = data.get("billAbstractNo")
        if data.get("billAbstractDate") is not None:
            bill.bill_abstract_date = parse_date(data.get("billAbstractDate"), "billAbstractDate")
        if data.get("bankAc") is not None:
            bill.bank_ac = data.get("bankAc")
        if data.get("bankAcId") is not None:
            bill.bank_ac_id = data.get("bankAcId")
        if data.get("paymentTerms") is not None:
            bill.payment_terms = data.get("paymentTerms")
        if data.get("declaration") is not None:
            bill.declaration = data.get("declaration")

        # Rebuild sources, items and GST
        SaleBillItem.query.filter_by(sale_bill_id=bill.id).delete()
        SaleBillGst.query.filter_by(sale_bill_id=bill.id).delete()
        SaleBillSource.query.filter_by(sale_bill_id=bill.id).delete()
        db.session.flush()

        # Rebuild sources if provided
        source_index_to_id = {}
        if data.get("sources"):
            sources_data, first_cert_bill, err = _resolve_sources(data, bill.project_code, exclude_sale_bill_id=bill.id)
            if err:
                db.session.rollback()
                return err
            # Update legacy snapshot fields from first source
            bill.sale_order_no     = sources_data[0]["sale_order_no"]
            bill.sale_order_id     = sources_data[0]["sale_order_id"]
            bill.certified_bill_id = sources_data[0]["cert_bill"].id
            bill.certified_bill_no = sources_data[0]["cert_bill"].billing_no or sources_data[0]["cert_bill"].erp_no
            for idx, src in enumerate(sources_data):
                cert_bill = src["cert_bill"]
                source_row = SaleBillSource(
                    sale_bill_id      = bill.id,
                    sale_order_id     = src["sale_order_id"],
                    sale_order_no     = src["sale_order_no"],
                    certified_bill_id = cert_bill.id,
                    certified_bill_no = cert_bill.billing_no or cert_bill.erp_no,
                    billing_date      = cert_bill.billing_date,
                    basic_amount      = src["basic_amount"],
                )
                db.session.add(source_row)
                db.session.flush()
                source_index_to_id[idx] = source_row.id

        basic_total = sum(Decimal(str(i.get("basicAmount") or 0)) for i in items)
        gst_total = sum(
            (Decimal(str(i.get("basicAmount") or 0)) * Decimal(str(i.get("gstPercent") or 0)) / 100).quantize(Decimal("0.01"))
            for i in items
        )
        if gst_total == 0 and gst_lines:
            gst_total = sum(
                Decimal(str(g.get("gstAmount") or 0))
                for g in gst_lines if g.get("isSelected")
            )
        discount  = Decimal(str(data.get("discount")  or 0))
        round_off = Decimal(str(data.get("roundOff")  or 0))

        for idx, row in enumerate(items, start=1):
            source_index = row.get("sourceIndex")
            source_id = source_index_to_id.get(source_index) if source_index is not None else None
            db.session.add(SaleBillItem(
                sale_bill_id    = bill.id,
                source_id       = source_id,
                sl_no           = row.get("slNo") or idx,
                cc_code         = row.get("ccCode"),
                cc_name         = row.get("ccName"),
                description     = row.get("description"),
                hsn_sac         = row.get("hsnSac"),
                basic_amount    = Decimal(str(row.get("basicAmount") or 0)),
                gst_percent     = Decimal(str(row.get("gstPercent") or 0)),
                billing_item_id = row.get("billingItemId"),
            ))

        for g in gst_lines:
            db.session.add(SaleBillGst(
                sale_bill_id = bill.id,
                gst_type     = g.get("gstType"),
                cc_code      = g.get("ccCode"),
                cc_name      = g.get("ccName"),
                description  = g.get("description"),
                percent      = Decimal(str(g.get("percent")   or 0)),
                gst_amount   = Decimal(str(g.get("gstAmount") or 0)) if g.get("isSelected") else Decimal("0"),
                is_selected  = bool(g.get("isSelected")),
            ))

        bill.basic_amount         = basic_total
        bill.gst_amount           = gst_total
        bill.discount             = discount
        bill.round_off            = round_off
        bill.total_invoice_amount = basic_total + gst_total - discount + round_off

        if bill.workflow_status == "Reback":
            bill.correction_sent_at = None

        bill.updated_by = user_id
        bill.updated_at = datetime.utcnow()

        db.session.commit()

        return res("Sale bill updated", {"id": bill.id, "saleBillNo": bill.sale_bill_no}, 200)

    except ValueError as e:
        db.session.rollback()
        return res(str(e), [], 400)
    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 7. SUBMIT
# ══════════════════════════════════════════════════════════════════

def submit_sale_bill(bill_id, user_id):
    try:
        bill = SaleBillMaster.query.get(bill_id)
        if not bill:
            return res("Sale bill not found", [], 404)
        if bill.workflow_status not in ("Draft", "Reback"):
            return res("Sale bill already submitted", [], 400)
        if not bill.items:
            return res("Sale bill has no items", [], 400)

        if bill.workflow_status == "Reback":
            bill.current_level = 0

        first_level = get_first_approver(bill.project_code, _MODULE)

        if not first_level:
            bill.workflow_status   = "Approved"
            bill.locked            = True
            bill.approved_by       = user_id
            bill.submitted_at      = datetime.utcnow()
            bill.final_approved_at = datetime.utcnow()
        else:
            bill.workflow_status = f"Pending_L{first_level.level_no}"
            bill.current_level   = first_level.level_no
            bill.locked          = True
            bill.submitted_at    = datetime.utcnow()

        create_history(
            project_code=bill.project_code,
            module_code=_MODULE,
            record_id=bill.id,
            level_no=bill.current_level,
            action="SUBMIT",
            action_by=user_id,
        )

        bill.submitted_by = user_id
        bill.updated_by   = user_id
        bill.updated_at   = datetime.utcnow()

        db.session.commit()

        try:
            submitter = User.query.get(user_id)
            submitter_name = submitter.username if submitter else str(user_id)
            if first_level:
                wa.on_submit(
                    module_code="sale_bill",
                    doc_no=bill.sale_bill_no,
                    uuid=str(bill.sale_bill_uuid),
                    project_code=bill.project_code,
                    submitter_name=submitter_name,
                    approver_user=first_level.user,
                    current_level=first_level.level_no,
                    record_id=bill.id,
                )
        except Exception:
            pass

        return res("Sale bill submitted", {
            "id":             bill.id,
            "workflowStatus": bill.workflow_status,
        }, 200)

    except SQLAlchemyError as e:
        db.session.rollback()
        return res(str(e), [], 500)
    except ValueError as e:
        db.session.rollback()
        return res(str(e), [], 400)
    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 8. APPROVE
# ══════════════════════════════════════════════════════════════════

def approve_sale_bill(bill_id, approved_by, comments=None):
    try:
        bill = SaleBillMaster.query.get(bill_id)
        if not bill:
            return res("Sale bill not found", [], 404)
        if not bill.workflow_status.startswith("Pending"):
            return res("Sale bill is not pending approval", [], 400)

        allowed = is_current_approver(bill.project_code, _MODULE, bill.current_level, approved_by)
        if not allowed:
            return res("You are not the current approver", [], 403)

        gap = get_gap_level(bill.project_code, _MODULE, bill.current_level)
        if gap:
            return res(f"L{gap} is not assigned. Please assign it before approving.", [], 400)

        next_level = get_next_approver(bill.project_code, _MODULE, bill.current_level)

        if next_level:
            create_history(
                project_code=bill.project_code, module_code=_MODULE,
                record_id=bill.id, level_no=bill.current_level,
                action="APPROVE", action_by=approved_by, comments=comments,
            )
            bill.current_level   = next_level.level_no
            bill.workflow_status = f"Pending_L{next_level.level_no}"
        else:
            create_history(
                project_code=bill.project_code, module_code=_MODULE,
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

        try:
            approver_user = User.query.get(approved_by)
            approver_name = approver_user.username if approver_user else str(approved_by)
            if next_level:
                wa.on_approve(
                    module_code="sale_bill",
                    doc_no=bill.sale_bill_no,
                    uuid=str(bill.sale_bill_uuid),
                    project_code=bill.project_code,
                    approver_name=approver_name,
                    prev_level=bill.current_level,
                    next_approver_user=next_level.user,
                    next_level=next_level.level_no,
                    record_id=bill.id,
                )
            else:
                creator_user = User.query.get(bill.created_by)
                wa.on_final_approve(
                    module_code="sale_bill",
                    doc_no=bill.sale_bill_no,
                    uuid=str(bill.sale_bill_uuid),
                    project_code=bill.project_code,
                    approver_name=approver_name,
                    creator_user=creator_user,
                    record_id=bill.id,
                )
        except Exception:
            pass

        return res("Sale bill approved", {
            "id":             bill.id,
            "workflowStatus": bill.workflow_status,
        }, 200)

    except SQLAlchemyError as e:
        db.session.rollback()
        return res(str(e), [], 500)
    except ValueError as e:
        db.session.rollback()
        return res(str(e), [], 400)
    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 9. REBACK
# ══════════════════════════════════════════════════════════════════

def reback_sale_bill(bill_id, reback_by, comments=None):
    try:
        bill = SaleBillMaster.query.get(bill_id)
        if not bill:
            return res("Sale bill not found", [], 404)
        if not bill.workflow_status.startswith("Pending"):
            return res("Sale bill is not pending", [], 400)
        if not comments:
            return res("Comments required for reback", [], 400)

        allowed = is_current_approver(bill.project_code, _MODULE, bill.current_level, reback_by)
        if not allowed:
            return res("You are not the current approver", [], 403)

        bill.workflow_status    = "Reback"
        bill.locked             = False
        bill.correction_sent_at = datetime.utcnow()
        bill.updated_by         = reback_by
        bill.updated_at         = datetime.utcnow()

        create_history(
            project_code=bill.project_code, module_code=_MODULE,
            record_id=bill.id, level_no=bill.current_level,
            action="REBACK", action_by=reback_by, comments=comments,
        )

        db.session.commit()

        try:
            reback_user = User.query.get(reback_by)
            reback_name = reback_user.username if reback_user else str(reback_by)
            creator_user = User.query.get(bill.created_by)
            wa.on_reback(
                module_code="sale_bill",
                doc_no=bill.sale_bill_no,
                uuid=str(bill.sale_bill_uuid),
                project_code=bill.project_code,
                approver_name=reback_name,
                creator_user=creator_user,
                comments=comments,
                record_id=bill.id,
            )
        except Exception:
            pass

        return res("Sale bill sent for correction", {
            "id":             bill.id,
            "workflowStatus": bill.workflow_status,
        }, 200)

    except SQLAlchemyError as e:
        db.session.rollback()
        return res(str(e), [], 500)
    except ValueError as e:
        db.session.rollback()
        return res(str(e), [], 400)
    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 10. REJECT
# ══════════════════════════════════════════════════════════════════

def reject_sale_bill(bill_id, rejected_by, comments=None):
    try:
        bill = SaleBillMaster.query.get(bill_id)
        if not bill:
            return res("Sale bill not found", [], 404)
        if not bill.workflow_status.startswith("Pending"):
            return res("Sale bill is not pending", [], 400)
        if not comments:
            return res("Comments required for rejection", [], 400)

        allowed = is_current_approver(bill.project_code, _MODULE, bill.current_level, rejected_by)
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
            project_code=bill.project_code, module_code=_MODULE,
            record_id=bill.id, level_no=bill.current_level,
            action="REJECT", action_by=rejected_by, comments=comments,
        )

        db.session.commit()

        try:
            rejected_user = User.query.get(rejected_by)
            rejected_name = rejected_user.username if rejected_user else str(rejected_by)
            creator_user = User.query.get(bill.created_by)
            wa.on_reject(
                module_code="sale_bill",
                doc_no=bill.sale_bill_no,
                uuid=str(bill.sale_bill_uuid),
                project_code=bill.project_code,
                approver_name=rejected_name,
                creator_user=creator_user,
                comments=comments,
                record_id=bill.id,
            )
        except Exception:
            pass

        return res("Sale bill rejected", {
            "id":             bill.id,
            "workflowStatus": bill.workflow_status,
        }, 200)

    except SQLAlchemyError as e:
        db.session.rollback()
        return res(str(e), [], 500)
    except ValueError as e:
        db.session.rollback()
        return res(str(e), [], 400)
    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 11. HISTORY
# ══════════════════════════════════════════════════════════════════

def get_sale_bill_history(bill_id):
    try:
        bill = SaleBillMaster.query.get(bill_id)
        if not bill:
            return res("Sale bill not found", [], 404)

        rows = get_history(_MODULE, bill.id)

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

        steps = get_approval_steps(bill.project_code, _MODULE, bill, rows)

        return res("History fetched", {
            "workflowStatus": bill.workflow_status,
            "currentLevel":   bill.current_level,
            "approvalSteps":  steps,
            "history":        history,
        }, 200)

    except ValueError as e:
        db.session.rollback()
        return res(str(e), [], 400)
    except Exception as e:
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 12. MY APPROVAL STATUS
# ══════════════════════════════════════════════════════════════════

def get_sale_bill_my_approval_status(bill_id, user_id):
    try:
        bill = SaleBillMaster.query.get(bill_id)
        if not bill:
            return res("Sale bill not found", [], 404)
        data = get_my_approval_status(bill.project_code, _MODULE, bill, user_id)
        return res("Approval status", data, 200)
    except ValueError as e:
        db.session.rollback()
        return res(str(e), [], 400)
    except Exception as e:
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# 13. UUID LOOKUP (public)
# ══════════════════════════════════════════════════════════════════

def get_sale_bill_by_uuid(sale_bill_uuid):
    try:
        bill = SaleBillMaster.query.filter_by(sale_bill_uuid=sale_bill_uuid).first()
        if not bill:
            return res("Sale bill not found", [], 404)
        return res("Sale bill details fetched", _build_detail_payload(bill), 200)
    except ValueError as e:
        db.session.rollback()
        return res(str(e), [], 400)
    except Exception as e:
        return res(str(e), [], 500)


def delete_sale_bill(bill_id):
    try:
        bill = SaleBillMaster.query.get(bill_id)
        if not bill:
            return res("Sale Bill not found", [], 404)
        if bill.locked:
            return res("Only draft Sale Bill can be deleted", [], 400)
        SaleBillGst.query.filter_by(sale_bill_id=bill.id).delete()
        SaleBillItem.query.filter_by(sale_bill_id=bill.id).delete()
        db.session.delete(bill)
        db.session.commit()
        from app.modules.delete_manager.service import auto_complete_check
        auto_complete_check("SALE_BILL", bill_id)
        return res("Sale Bill deleted successfully", [], 200)
    except SQLAlchemyError as e:
        db.session.rollback()
        return res(str(e), [], 500)
    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)
