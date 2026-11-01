# app/modules/traceability/service.py
"""
Read-only item traceability.

Builds the downstream lifecycle of ONE indent item, using only the
foreign keys that already exist in the schema:

    indent_items
      ├─ enquiry_item.indent_item_id          (side branch)
      └─ order_items.indent_item_id           (one indent item → many order lines)
           ├─ grn_items.order_item_id         (receipt)
           │    └─ brb_items.grn_item_id      (exact item-level billing)
           │         └─ brb_master.brr_id → brr_master
           │              └─ purchase_bill_master.brr_id   (header level)
           │                   └─ bill_payment_receipt_master.purchase_bill_id
           ├─ gin_items.order_item_id         (issue)
           └─ dc_items.order_item_id          (dispatch / transfer)

Quantity rules mirror the existing services so the numbers match what
users already see elsewhere:
  * ordered    – non-rejected orders        (order/service.get_indent_pending_qty_list)
  * received   – non-rejected GRNs          (grn/service._pre_received_qty_bulk)
  * stock      – approved GRN − non-rejected GIN   (gin/service._stock_qty)
  * billable   – approved GRN − non-rejected BRB   (brr_billing/service.get_items_by_brr)
  * paid       – approved receipts only     (bill_payment/service._paid_item_map)

Purchase Bill lines and payments are stored per cost-centre (CC) code,
not per item, so any item-level ₹ figure past BRB is an ALLOCATION and
is always returned with isAllocated=True and its basis.

Nothing in this module writes to the database.
"""

from collections import defaultdict
from decimal import Decimal

from sqlalchemy import func
from sqlalchemy.orm import joinedload

from app.extensions import db
from app.response import res

from app.models.indent_master import IndentMaster
from app.models.indent_item import IndentItem
from app.models.enquiry_master import EnquiryMaster
from app.models.enquiry_item import EnquiryItem
from app.models.orderMaster import OrderMaster, OrderItem
from app.models.grnMaster import GrnMaster, GrnItem
from app.models.ginMaster import GinMaster, GinItem
from app.models.dcMaster import DcMaster, DcItem
from app.models.brbMaster import BrbMaster, BrbItem
from app.models.brrMaster import BrrMaster
from app.models.bvsMaster import BvsMaster, BvsItem
from app.models.purchaseBill import (
    PurchaseBillMaster, PurchaseBillItem, PurchaseBillGst,
)
from app.models.billPaymentReceipt import (
    BillPaymentReceiptMaster, BillPaymentReceiptItem, BillPaymentReceiptGst,
)
from app.models.item import Item
from app.models.asset import Asset
from app.models.cc_code import CCCode
from app.models.user import User


ZERO = Decimal("0")
REJECTED = "Rejected"
APPROVED = "Approved"

CUSTOMER_SUPPLY_CATEGORY = "Customer_Supply_Order"
SITE_TRANSFER_CATEGORY = "Site_Transfer_Order"

ALLOCATION_BASIS = (
    "Purchase Bill lines and payments are recorded per cost-centre (CC) code, "
    "not per item. Allocated value = Purchase Bill / payment amount for the item's "
    "CC code × (this item's approved BRB basic amount under the BRR ÷ total approved "
    "BRB basic amount for that CC code under the same BRR). Header-level discount and "
    "round-off are not allocated. Shares use the BRB lines approved today, which may "
    "differ from those approved when the Purchase Bill was prepared."
)


# ─────────────────────────────────────────────────────────────────
# small helpers
# ─────────────────────────────────────────────────────────────────

def _d(v):
    return Decimal(str(v)) if v is not None else ZERO


def _qty(v):
    return float(round(_d(v), 4))


def _amt(v):
    return float(round(_d(v), 2))


def _fq(v):
    """Quantity for messages, same 3-decimal style the UI uses."""
    return f"{_d(v):,.3f}"


def _status_label(s):
    return (s or "").replace("Pending_L", "Pending L").replace("_", " ")


def _date(d):
    return d.strftime("%Y-%m-%d") if d else None


def _live(status):
    """Existing services count everything that is not Rejected."""
    return status != REJECTED


def _user_is_super_admin(user_id):
    user = User.query.options(joinedload(User.global_role)).get(user_id)
    return bool(user and user.global_role and user.global_role.name == "super_admin")


def user_can_view_indent(user_id, project_id):
    """
    Same permission keys the frontend uses for the Indent page
    (indent.VIEW / indent.EDIT / indent.APPROVER), resolved from the
    database for the indent's own project — so a token issued for a
    different project cannot read this project's data.
    """
    if _user_is_super_admin(user_id):
        return True

    from app.modules.setting.permission_service import get_user_permissions

    perms = get_user_permissions(project_id, user_id) or {}
    return any(perms.get(f"indent.{a}") for a in ("VIEW", "EDIT", "APPROVER"))


def _party_name(order):
    """Same rule as order/service._resolve_party_name, on eager-loaded data."""
    if order.category_code == CUSTOMER_SUPPLY_CATEGORY:
        return order.project.client_name if order.project else None
    if order.category_code == SITE_TRANSFER_CATEGORY:
        p = order.transfer_site_project
        return p.client_name if p else None
    return order.vendor.ledger_name if order.vendor else None


# ─────────────────────────────────────────────────────────────────
# loaders  (each one is a single batched query)
# ─────────────────────────────────────────────────────────────────

def _load_indent_item(indent_item_id):
    return (
        IndentItem.query
        .options(
            joinedload(IndentItem.indent).joinedload(IndentMaster.project),
            joinedload(IndentItem.indent).joinedload(IndentMaster.category),
            joinedload(IndentItem.item).joinedload(Item.unit),
            joinedload(IndentItem.item).joinedload(Item.cc_code),
            joinedload(IndentItem.item).joinedload(Item.category),
            joinedload(IndentItem.asset).joinedload(Asset.unit),
            joinedload(IndentItem.asset).joinedload(Asset.cc_code),
            joinedload(IndentItem.asset).joinedload(Asset.category),
        )
        .filter(IndentItem.id == indent_item_id)
        .first()
    )


def _load_enquiry_lines(indent_item_id):
    return (
        db.session.query(EnquiryItem, EnquiryMaster)
        .join(EnquiryMaster, EnquiryMaster.id == EnquiryItem.enquiry_id)
        .filter(EnquiryItem.indent_item_id == indent_item_id)
        .order_by(EnquiryMaster.enquiry_date, EnquiryMaster.id)
        .all()
    )


def _load_order_lines(indent_item_id):
    return (
        db.session.query(OrderItem, OrderMaster)
        .join(OrderMaster, OrderMaster.id == OrderItem.order_id)
        .options(
            joinedload(OrderMaster.vendor),
            joinedload(OrderMaster.project),
            joinedload(OrderMaster.transfer_site_project),
        )
        .filter(OrderItem.indent_item_id == indent_item_id)
        .order_by(OrderMaster.order_date, OrderMaster.id, OrderItem.id)
        .all()
    )


def _load_by_order_items(item_model, master_model, fk_master, order_item_ids, order_by):
    if not order_item_ids:
        return []
    return (
        db.session.query(item_model, master_model)
        .join(master_model, master_model.id == fk_master)
        .filter(item_model.order_item_id.in_(order_item_ids))
        .order_by(*order_by)
        .all()
    )


def _load_brb_lines(grn_item_ids):
    if not grn_item_ids:
        return []
    return (
        db.session.query(BrbItem, BrbMaster)
        .join(BrbMaster, BrbMaster.id == BrbItem.brb_id)
        .filter(BrbItem.grn_item_id.in_(grn_item_ids))
        .order_by(BrbMaster.brb_date, BrbMaster.id, BrbItem.id)
        .all()
    )


def _load_legacy_bvs_lines(grn_item_ids):
    """
    BVS (old vendor billing on GRN) is no longer used by the frontend but
    its routes are still registered, so historical rows may exist. Shown
    for transparency only; never counted in billed quantities.
    """
    if not grn_item_ids:
        return []
    try:
        with db.session.begin_nested():
            return (
                db.session.query(BvsItem, BvsMaster)
                .join(BvsMaster, BvsMaster.id == BvsItem.bvs_id)
                .filter(BvsItem.grn_item_id.in_(grn_item_ids))
                .all()
            )
    except Exception:
        return []


def _brr_cc_totals(brr_ids):
    """
    Total APPROVED BRB basic amount per (BRR, CC code), using the exact join
    purchase_bill/service._cc_summary_from_brb uses to build Purchase Bill lines.
    """
    if not brr_ids:
        return {}
    rows = (
        db.session.query(
            BrbMaster.brr_id,
            CCCode.cc_code,
            func.coalesce(func.sum(BrbItem.amount), 0).label("basic"),
        )
        .join(BrbItem, BrbItem.brb_id == BrbMaster.id)
        .join(GrnItem, GrnItem.id == BrbItem.grn_item_id)
        .join(OrderItem, OrderItem.id == GrnItem.order_item_id)
        .join(Item, Item.item_code == OrderItem.item_code)
        .join(CCCode, CCCode.id == Item.cc_code_id)
        .filter(
            BrbMaster.brr_id.in_(brr_ids),
            BrbMaster.workflow_status == APPROVED,
        )
        .group_by(BrbMaster.brr_id, CCCode.cc_code)
        .all()
    )
    return {(r.brr_id, r.cc_code): _d(r.basic) for r in rows}


def _load_accounts(brr_ids):
    """Purchase Bills on these BRRs, their lines, GST, receipts and receipt lines."""
    out = {
        "bills": [], "bill_items": defaultdict(list), "bill_gst": defaultdict(list),
        "receipts": defaultdict(list), "receipt_items": defaultdict(list),
        "receipt_gst": defaultdict(list),
    }
    if not brr_ids:
        return out

    bills = (
        PurchaseBillMaster.query
        .filter(PurchaseBillMaster.brr_id.in_(brr_ids))
        .order_by(PurchaseBillMaster.processing_date, PurchaseBillMaster.id)
        .all()
    )
    out["bills"] = bills
    bill_ids = [b.id for b in bills]
    if not bill_ids:
        return out

    for row in PurchaseBillItem.query.filter(PurchaseBillItem.purchase_bill_id.in_(bill_ids)).all():
        out["bill_items"][row.purchase_bill_id].append(row)
    for row in PurchaseBillGst.query.filter(PurchaseBillGst.purchase_bill_id.in_(bill_ids)).all():
        out["bill_gst"][row.purchase_bill_id].append(row)

    receipts = (
        BillPaymentReceiptMaster.query
        .filter(BillPaymentReceiptMaster.purchase_bill_id.in_(bill_ids))
        .order_by(BillPaymentReceiptMaster.payment_date, BillPaymentReceiptMaster.id)
        .all()
    )
    receipt_ids = [r.id for r in receipts]
    for r in receipts:
        out["receipts"][r.purchase_bill_id].append(r)
    if receipt_ids:
        for row in BillPaymentReceiptItem.query.filter(BillPaymentReceiptItem.receipt_id.in_(receipt_ids)).all():
            out["receipt_items"][row.receipt_id].append(row)
        for row in BillPaymentReceiptGst.query.filter(BillPaymentReceiptGst.receipt_id.in_(receipt_ids)).all():
            out["receipt_gst"][row.receipt_id].append(row)
    return out


# ─────────────────────────────────────────────────────────────────
# serialisers
# ─────────────────────────────────────────────────────────────────

def _source_payload(ii):
    indent = ii.indent
    if ii.is_asset:
        master = ii.asset
        code = ii.asset_code
        name = master.asset_name if master else None
        display_code = code
    else:
        master = ii.item
        code = ii.item_code
        name = master.item_name if master else None
        display_code = master.item_display_code if master else code

    unit = master.unit if master else None
    cc = master.cc_code if master else None
    cat = master.category if master else None

    return {
        "indentItemId": ii.id,
        "indentId": indent.id,
        "indentNo": indent.indent_no,
        "indentDate": _date(indent.indent_date),
        "indentStatus": indent.workflow_status,
        "priority": indent.priority,
        "requiredWithin": _date(indent.required_within),
        "projectCode": indent.project_code,
        "projectName": indent.project.project_name if indent.project else None,
        "indentCategoryCode": indent.category_code,
        "indentCategoryName": indent.category.category_name if indent.category else None,
        "itemCode": code,
        "itemDisplayCode": display_code,
        "itemName": name,
        "itemType": "Asset" if ii.is_asset else "Item",
        "isAsset": bool(ii.is_asset),
        "itemCategoryName": cat.category_name if cat else None,
        "unit": unit.short_name if unit else None,
        "unitName": unit.unit_name if unit else None,
        "gstPercent": _amt(master.gst_percentage) if master and master.gst_percentage is not None else None,
        "hsnSac": master.hsn_sac if master else None,
        "ccCode": cc.cc_code if cc else None,
        "ccName": cc.cc_name if cc else None,
        "qty": _qty(ii.qty),
        "location": ii.location,
        "note": ii.note,
    }


def _line_amounts(qty, rate, gst_percent, amount=None, gst_amount=None):
    """Use stored amounts when present; otherwise derive from qty × rate."""
    basic = _d(amount) if amount is not None else _d(qty) * _d(rate)
    gst = _d(gst_amount) if gst_amount is not None else basic * _d(gst_percent) / Decimal("100")
    return basic, gst


# ─────────────────────────────────────────────────────────────────
# main builder (reusable — no HTTP / auth concerns)
# ─────────────────────────────────────────────────────────────────

def build_indent_item_trace(ii):
    src = _source_payload(ii)
    unit = src["unit"]
    item_cc = src["ccCode"]
    is_asset = src["isAsset"]
    indent_qty = _d(ii.qty)

    ledger = []
    exceptions = []

    def add_ex(code, severity, message, ref=None):
        exceptions.append({"code": code, "severity": severity, "message": message, "ref": ref})

    def add_ledger(**row):
        row.setdefault("unit", unit)
        row.setdefault("isAllocated", False)
        ledger.append(row)

    add_ledger(
        date=src["indentDate"], stage=0, module="Procurement", transactionType="Indent",
        docType="INDENT", docId=src["indentId"], docNo=src["indentNo"], parentRef=None,
        qty=src["qty"], rate=None, amount=None, status=src["indentStatus"],
    )

    # ── enquiries ────────────────────────────────────────────────
    enquiries = []
    for ei, em in _load_enquiry_lines(ii.id):
        enquiries.append({
            "enquiryId": em.id,
            "enquiryNo": em.enquiry_no,
            "enquiryDate": _date(em.enquiry_date),
            "enquiryTo": em.enquiry_to,
            "workflowStatus": em.workflow_status,
            "enquiryItemId": ei.id,
            "indentQty": _qty(ei.indent_qty),
            "enquiryQty": _qty(ei.enquiry_qty),
        })
        add_ledger(
            date=_date(em.enquiry_date), stage=1, module="Procurement", transactionType="Enquiry",
            docType="ENQUIRY", docId=em.id, docNo=em.enquiry_no, parentRef=src["indentNo"],
            qty=_qty(ei.enquiry_qty), rate=None, amount=None, status=em.workflow_status,
        )

    # ── order lines ──────────────────────────────────────────────
    order_rows = _load_order_lines(ii.id)
    oi_ids = [oi.id for oi, _ in order_rows]

    grn_rows = _load_by_order_items(
        GrnItem, GrnMaster, GrnItem.grn_id, oi_ids,
        (GrnMaster.grn_date, GrnMaster.id, GrnItem.id),
    )
    gin_rows = _load_by_order_items(
        GinItem, GinMaster, GinItem.gin_id, oi_ids,
        (GinMaster.gin_date, GinMaster.id, GinItem.id),
    )
    dc_rows = _load_by_order_items(
        DcItem, DcMaster, DcItem.dc_id, oi_ids,
        (DcMaster.challan_date, DcMaster.id, DcItem.id),
    )

    grn_item_ids = [gi.id for gi, _ in grn_rows]
    brb_rows = _load_brb_lines(grn_item_ids)
    bvs_rows = _load_legacy_bvs_lines(grn_item_ids)

    brr_ids = sorted({bm.brr_id for _, bm in brb_rows if bm.brr_id})
    brrs = {b.id: b for b in BrrMaster.query.filter(BrrMaster.id.in_(brr_ids)).all()} if brr_ids else {}
    cc_totals = _brr_cc_totals(brr_ids)
    acc = _load_accounts(brr_ids)

    # index children by parent
    grn_by_oi = defaultdict(list)
    for gi, gm in grn_rows:
        grn_by_oi[gi.order_item_id].append((gi, gm))
    gin_by_oi = defaultdict(list)
    for gi, gm in gin_rows:
        gin_by_oi[gi.order_item_id].append((gi, gm))
    dc_by_oi = defaultdict(list)
    for di, dm in dc_rows:
        dc_by_oi[di.order_item_id].append((di, dm))
    brb_by_grn_item = defaultdict(list)
    for bi, bm in brb_rows:
        brb_by_grn_item[bi.grn_item_id].append((bi, bm))
    bills_by_brr = defaultdict(list)
    for b in acc["bills"]:
        bills_by_brr[b.brr_id].append(b)

    # totals across all order lines
    T = defaultdict(lambda: ZERO)
    orders = []
    rejected_docs = set()
    in_process_docs = set()

    def note_status(doc_type, doc_no, status):
        if status == REJECTED:
            rejected_docs.add((doc_type, doc_no))
        elif status != APPROVED:
            in_process_docs.add((doc_type, doc_no, status))

    for oi, om in order_rows:
        note_status("Order", om.order_no, om.workflow_status)
        o_live = _live(om.workflow_status)
        o_qty = _d(oi.qty)
        o_basic, o_gst = _line_amounts(oi.qty, oi.rate, oi.gst_percent, oi.amount, oi.gst_amount)

        if o_live:
            T["ordered"] += o_qty
        if om.workflow_status == APPROVED:
            T["orderedApproved"] += o_qty

        add_ledger(
            date=_date(om.order_date), stage=2, module="Procurement", transactionType="Material Order",
            docType="ORDER", docId=om.id, docNo=om.order_no, parentRef=src["indentNo"],
            qty=_qty(o_qty), rate=_amt(oi.rate), amount=_amt(o_basic + o_gst),
            status=om.workflow_status, orderItemId=oi.id,
        )

        # GRNs
        received = received_approved = ZERO
        grns = []
        billing_lines = []
        billed_live = billed_approved = billed_amt = billed_gst = ZERO
        billable = ZERO   # per approved GRN line: received − non-rejected BRB qty
        # item's approved BRB basic per BRR (for allocation), for this order line only
        item_brr_basic = defaultdict(lambda: ZERO)
        item_brr_all = set()

        for gi, gm in grn_by_oi.get(oi.id, []):
            note_status("GRN", gm.grn_no, gm.workflow_status)
            rq = _d(gi.current_received_qty)
            if _live(gm.workflow_status):
                received += rq
            if gm.workflow_status == APPROVED:
                received_approved += rq

            g_billed = ZERO
            g_lines = []
            for bi, bm in brb_by_grn_item.get(gi.id, []):
                note_status("BRB", bm.brb_no, bm.workflow_status)
                bq = _d(bi.billing_qty)
                b_basic, b_gst = _line_amounts(bi.billing_qty, bi.rate, bi.gst_percent, bi.amount, bi.gst_amount)
                brr = brrs.get(bm.brr_id)
                line = {
                    "brbId": bm.id,
                    "brbNo": bm.brb_no,
                    "brbDate": _date(bm.brb_date),
                    "workflowStatus": bm.workflow_status,
                    "brbItemId": bi.id,
                    "brrId": bm.brr_id,
                    "brrNo": brr.brr_no if brr else None,
                    "grnId": gm.id,
                    "grnNo": gm.grn_no,
                    "grnItemId": gi.id,
                    "partyBillNo": bm.party_bill_no,
                    "partyDate": _date(bm.party_date),
                    "billingQty": _qty(bq),
                    "rate": _amt(bi.rate),
                    "basicAmount": _amt(b_basic),
                    "gstPercent": _amt(bi.gst_percent),
                    "gstAmount": _amt(b_gst),
                    "totalAmount": _amt(b_basic + b_gst),
                }
                g_lines.append(line)
                billing_lines.append(line)
                if bm.brr_id:
                    item_brr_all.add(bm.brr_id)
                if _live(bm.workflow_status):
                    g_billed += bq
                    billed_live += bq
                    billed_amt += b_basic
                    billed_gst += b_gst
                if bm.workflow_status == APPROVED:
                    billed_approved += bq
                    if bm.brr_id:
                        item_brr_basic[bm.brr_id] += b_basic

                add_ledger(
                    date=_date(bm.brb_date), stage=6, module="Billing", transactionType="BRB Billing",
                    docType="BRB", docId=bm.id, docNo=bm.brb_no, parentRef=gm.grn_no,
                    qty=_qty(bq), rate=_amt(bi.rate), amount=_amt(b_basic + b_gst),
                    status=bm.workflow_status, orderItemId=oi.id,
                )

            if gm.workflow_status == APPROVED:
                billable += max(rq - g_billed, ZERO)

            r_basic = rq * _d(oi.rate)
            grns.append({
                "grnId": gm.id,
                "grnNo": gm.grn_no,
                "grnDate": _date(gm.grn_date),
                "workflowStatus": gm.workflow_status,
                "grnItemId": gi.id,
                "challanNo": gm.challan_no,
                "partyBillNo": gm.party_bill_no,
                "receivedQty": _qty(rq),
                "orderRate": _amt(oi.rate),
                "valueAtOrderRate": _amt(r_basic),
                "storeLocation": gi.store_location,
                "useLocation": gi.use_location,
                "billedQty": _qty(g_billed),
                "billings": g_lines,
            })
            add_ledger(
                date=_date(gm.grn_date), stage=3, module="Inventory", transactionType="GRN (Receipt)",
                docType="GRN", docId=gm.id, docNo=gm.grn_no, parentRef=om.order_no,
                qty=_qty(rq), rate=_amt(oi.rate), amount=_amt(r_basic),
                status=gm.workflow_status, orderItemId=oi.id,
            )

        # GINs
        issued = issued_approved = ZERO
        gins = []
        for gi, gm in gin_by_oi.get(oi.id, []):
            note_status("GIN", gm.gin_no, gm.workflow_status)
            iq = _d(gi.issue_qty)
            if _live(gm.workflow_status):
                issued += iq
            if gm.workflow_status == APPROVED:
                issued_approved += iq
            gins.append({
                "ginId": gm.id,
                "ginNo": gm.gin_no,
                "ginDate": _date(gm.gin_date),
                "workflowStatus": gm.workflow_status,
                "ginItemId": gi.id,
                "issueCategory": gm.issue_category,
                "issueSlipNo": gm.issue_slip_no,
                "handedOverTo": gm.handed_over_to,
                "issueQty": _qty(iq),
                "stockLocation": gi.stock_location,
                "usedLocation": gi.item_used_location,
            })
            add_ledger(
                date=_date(gm.gin_date), stage=4, module="Inventory", transactionType="GIN (Issue)",
                docType="GIN", docId=gm.id, docNo=gm.gin_no, parentRef=om.order_no,
                qty=_qty(iq), rate=_amt(oi.rate), amount=_amt(iq * _d(oi.rate)),
                status=gm.workflow_status, orderItemId=oi.id,
            )

        # DCs
        dispatched = ZERO
        dcs = []
        for di, dm in dc_by_oi.get(oi.id, []):
            note_status("DC", dm.dc_no, dm.workflow_status)
            dq = _d(di.issue_qty)
            if _live(dm.workflow_status):
                dispatched += dq
            dcs.append({
                "dcId": dm.id,
                "dcNo": dm.dc_no,
                "challanDate": _date(dm.challan_date),
                "workflowStatus": dm.workflow_status,
                "dcItemId": di.id,
                "orderType": dm.order_type,
                "fromProjectCode": dm.from_project_code,
                "toProjectCode": dm.to_project_code,
                "vehicleNumber": dm.vehicle_number,
                "qty": _qty(dq),
                "stockLocation": di.stock_location,
            })
            add_ledger(
                date=_date(dm.challan_date), stage=5, module="Logistics", transactionType="Delivery Challan",
                docType="DC", docId=dm.id, docNo=dm.dc_no, parentRef=om.order_no,
                qty=_qty(dq), rate=None, amount=None,
                status=dm.workflow_status, orderItemId=oi.id,
            )

        # BRR → Purchase Bill → Payment (header-linked; CC-level money)
        brr_nodes = []
        for brr_id in sorted(item_brr_all):
            brr = brrs.get(brr_id)
            if not brr:
                continue
            note_status("BRR", brr.brr_no, brr.workflow_status)
            item_basic = item_brr_basic.get(brr_id, ZERO)
            denom = cc_totals.get((brr_id, item_cc), ZERO) if (item_cc and not is_asset) else ZERO
            share = (item_basic / denom) if denom > 0 else None
            if share is not None and share > 1:
                share = Decimal("1")

            bills = []
            for bill in bills_by_brr.get(brr_id, []):
                note_status("Purchase Bill", bill.purchase_bill_no, bill.workflow_status)
                bill_node = _purchase_bill_node(bill, acc, item_cc, share, is_asset, note_status)
                bills.append(bill_node)

                alloc = bill_node["allocation"]
                if alloc["available"] and _live(bill.workflow_status):
                    T["pbAllocated"] += _d(alloc["billTotal"])
                    T["paidAllocated"] += _d(alloc["paidTotal"])
                    T["paidInProcessAllocated"] += _d(alloc["inProcessTotal"])
                    add_ledger(
                        date=_date(bill.processing_date), stage=7, module="Accounts",
                        transactionType="Purchase Bill", docType="PURCHASE_BILL", docId=bill.id,
                        docNo=bill.purchase_bill_no, parentRef=brr.brr_no, qty=None, rate=None,
                        amount=alloc["billTotal"], status=bill.workflow_status,
                        isAllocated=True, orderItemId=oi.id,
                    )
                else:
                    add_ledger(
                        date=_date(bill.processing_date), stage=7, module="Accounts",
                        transactionType="Purchase Bill", docType="PURCHASE_BILL", docId=bill.id,
                        docNo=bill.purchase_bill_no, parentRef=brr.brr_no, qty=None, rate=None,
                        amount=None, status=bill.workflow_status, orderItemId=oi.id,
                    )
                for p in bill_node["payments"]:
                    add_ledger(
                        date=p["paymentDate"], stage=8, module="Accounts",
                        transactionType="Bill Payment", docType="BILL_PAYMENT", docId=p["receiptId"],
                        docNo=p["receiptNo"], parentRef=bill.purchase_bill_no, qty=None, rate=None,
                        amount=p["allocatedAmount"], status=p["workflowStatus"],
                        isAllocated=p["allocatedAmount"] is not None, orderItemId=oi.id,
                    )

                if _live(bill.workflow_status) and alloc["available"]:
                    outstanding = _d(alloc["billTotal"]) - _d(alloc["paidTotal"])
                    if bill.workflow_status == APPROVED and outstanding > Decimal("0.01"):
                        add_ex(
                            "PAYMENT_OUTSTANDING", "warning",
                            f"{bill.purchase_bill_no}: approx. ₹ {_amt(outstanding):,.2f} of this item's "
                            f"allocated bill value is not yet paid (allocated estimate).",
                            {"docType": "PURCHASE_BILL", "docId": bill.id},
                        )

            live_bills = [b for b in bills if _live(b["workflowStatus"])]
            if len(live_bills) > 1:
                add_ex(
                    "MULTIPLE_PURCHASE_BILLS", "warning",
                    f"{brr.brr_no} has {len(live_bills)} active Purchase Bills. Please verify the BRR "
                    f"is not booked twice.",
                    {"docType": "BRR", "docId": brr.id},
                )
            if item_basic > 0 and not live_bills:
                add_ex(
                    "NOT_PURCHASE_BILLED", "warning",
                    f"Approved BRB billing under {brr.brr_no} has no Purchase Bill yet.",
                    {"docType": "BRR", "docId": brr.id},
                )

            brr_nodes.append({
                "brrId": brr.id,
                "brrNo": brr.brr_no,
                "brrDate": _date(brr.brr_date),
                "workflowStatus": brr.workflow_status,
                "partyBillNo": brr.party_bill_no,
                "partyDate": _date(brr.party_date),
                "basicAmount": _amt(brr.basic_amount),
                "gstAmount": _amt(brr.gst_amount),
                "totalAmount": _amt(brr.total_amount),
                "itemApprovedBrbBasic": _amt(item_basic),
                "ccApprovedBrbBasic": _amt(denom) if denom else None,
                "allocationShare": float(round(share, 6)) if share is not None else None,
                "purchaseBills": bills,
            })
            add_ledger(
                date=_date(brr.brr_date), stage=6.5, module="Billing", transactionType="Bill Receive Register",
                docType="BRR", docId=brr.id, docNo=brr.brr_no, parentRef=om.order_no,
                qty=None, rate=None, amount=_amt(brr.total_amount), status=brr.workflow_status,
                orderItemId=oi.id,
            )

        stock = received_approved - issued
        T["received"] += received
        T["receivedApproved"] += received_approved
        T["issued"] += issued
        T["issuedApproved"] += issued_approved
        T["dispatched"] += dispatched
        T["stock"] += stock
        T["billed"] += billed_live
        T["billedApproved"] += billed_approved
        T["billedBasic"] += billed_amt
        T["billedGst"] += billed_gst
        T["pendingBilling"] += billable

        # per-order exceptions
        if om.workflow_status == APPROVED:
            if received == 0:
                add_ex("NOT_RECEIVED", "warning",
                       f"{om.order_no}: nothing received yet against {_fq(o_qty)} {unit or ''} ordered.",
                       {"docType": "ORDER", "docId": om.id})
            elif received < o_qty:
                add_ex("PARTIAL_RECEIPT", "warning",
                       f"{om.order_no}: {_fq(o_qty - received)} {unit or ''} still to be received "
                       f"({_fq(received)} of {_fq(o_qty)}).",
                       {"docType": "ORDER", "docId": om.id})
        if o_live and received > o_qty:
            add_ex("OVER_RECEIVED", "error",
                   f"{om.order_no}: received {_fq(received)} exceeds ordered {_fq(o_qty)}.",
                   {"docType": "ORDER", "docId": om.id})
        if issued > received_approved:
            add_ex("OVER_ISSUED", "error",
                   f"{om.order_no}: issued {_fq(issued)} exceeds approved receipts {_fq(received_approved)}.",
                   {"docType": "ORDER", "docId": om.id})
        if billed_live > received:
            add_ex("OVER_BILLED", "error",
                   f"{om.order_no}: billed {_fq(billed_live)} exceeds received {_fq(received)}.",
                   {"docType": "ORDER", "docId": om.id})
        if stock > 0:
            add_ex("NOT_ISSUED", "info",
                   f"{om.order_no}: {_fq(stock)} {unit or ''} received but not yet issued (in stock).",
                   {"docType": "ORDER", "docId": om.id})
        if billable > 0:
            add_ex("PENDING_BILLING", "warning",
                   f"{om.order_no}: {_fq(billable)} {unit or ''} received (approved GRN) but not yet billed.",
                   {"docType": "ORDER", "docId": om.id})

        orders.append({
            "orderId": om.id,
            "orderNo": om.order_no,
            "orderDate": _date(om.order_date),
            "workflowStatus": om.workflow_status,
            "orderCategory": om.category_code,
            "partyName": _party_name(om),
            "vendorId": om.vendor_id,
            "orderItemId": oi.id,
            "qty": _qty(o_qty),
            "rate": _amt(oi.rate),
            "basicAmount": _amt(o_basic),
            "gstPercent": _amt(oi.gst_percent),
            "gstAmount": _amt(o_gst),
            "totalAmount": _amt(o_basic + o_gst),
            "location": oi.location,
            "receivedQty": _qty(received),
            "receivedApprovedQty": _qty(received_approved),
            "pendingReceiptQty": _qty(max(o_qty - received, ZERO)) if o_live else 0.0,
            "issuedQty": _qty(issued),
            "stockQty": _qty(stock),
            "dispatchedQty": _qty(dispatched),
            "billedQty": _qty(billed_live),
            "billedApprovedQty": _qty(billed_approved),
            "pendingBillingQty": _qty(max(billable, ZERO)),
            "billedBasicAmount": _amt(billed_amt),
            "billedGstAmount": _amt(billed_gst),
            "grns": grns,
            "gins": gins,
            "dcs": dcs,
            "billings": billing_lines,
            "brrs": brr_nodes,
        })

    # ── legacy billing (transparency only) ───────────────────────
    legacy = []
    for bi, bm in bvs_rows:
        legacy.append({
            "docType": "BVS",
            "docId": bm.id,
            "docNo": bm.bvs_no,
            "docDate": _date(bm.bvs_date),
            "workflowStatus": bm.workflow_status,
            "grnItemId": bi.grn_item_id,
            "billingQty": _qty(bi.billing_qty),
            "rate": _amt(bi.rate),
            "basicAmount": _amt(bi.amount),
            "gstAmount": _amt(bi.gst_amount),
        })
    if legacy:
        add_ex("LEGACY_BILLING", "info",
               f"{len(legacy)} legacy vendor-billing (BVS) line(s) reference this item's GRNs. "
               f"They are shown for reference and not counted in billed quantity.")

    # ── summary & item-level exceptions ──────────────────────────
    unallocated = indent_qty - T["ordered"]
    if src["indentStatus"] != APPROVED:
        add_ex("INDENT_NOT_APPROVED", "info",
               f"Indent is {_status_label(src['indentStatus'])}. Orders can only be raised on approved indents.")
    elif unallocated > 0:
        add_ex("NOT_ORDERED", "warning",
               f"{_fq(unallocated)} {unit or ''} of the indent quantity is not yet on any order.")
    if unallocated < 0:
        add_ex("OVER_ORDERED", "error",
               f"Ordered {_fq(T['ordered'])} exceeds indent quantity {_fq(indent_qty)}.")

    for doc_type, doc_no in sorted(rejected_docs):
        add_ex("REJECTED_DOCUMENT", "info",
               f"{doc_type} {doc_no} was rejected and is excluded from all quantities.")
    if in_process_docs:
        listed = ", ".join(f"{t} {n} ({_status_label(st)})" for t, n, st in sorted(in_process_docs))
        add_ex("IN_PROCESS_DOCUMENTS", "info",
               "Not yet approved (counted in ordered / received / issued / billed, as the existing "
               f"modules do): {listed}.")
    if is_asset and acc["bills"]:
        add_ex("ASSET_ACCOUNTS_UNALLOCATED", "info",
               "Purchase Bill CC lines are built from item-master CC codes only, so asset lines are "
               "not part of them. Item-level Purchase Bill and payment values cannot be allocated "
               "for this asset.")

    summary = {
        "indentQty": _qty(indent_qty),
        "orderedQty": _qty(T["ordered"]),
        "orderedApprovedQty": _qty(T["orderedApproved"]),
        "unallocatedQty": _qty(max(unallocated, ZERO)),
        "receivedQty": _qty(T["received"]),
        "receivedApprovedQty": _qty(T["receivedApproved"]),
        "netAcceptedQty": _qty(T["receivedApproved"]),
        "issuedQty": _qty(T["issued"]),
        "issuedApprovedQty": _qty(T["issuedApproved"]),
        "dispatchedQty": _qty(T["dispatched"]),
        "stockQty": _qty(T["stock"]),
        "billedQty": _qty(T["billed"]),
        "billedApprovedQty": _qty(T["billedApproved"]),
        "pendingBillingQty": _qty(T["pendingBilling"]),
        "billedBasicAmount": _amt(T["billedBasic"]),
        "billedGstAmount": _amt(T["billedGst"]),
        "billedTotalAmount": _amt(T["billedBasic"] + T["billedGst"]),
        "purchaseBilledAllocated": _amt(T["pbAllocated"]),
        "paidAllocated": _amt(T["paidAllocated"]),
        "paidInProcessAllocated": _amt(T["paidInProcessAllocated"]),
        "outstandingAllocated": _amt(max(T["pbAllocated"] - T["paidAllocated"], ZERO)),
        "accountsAllocationAvailable": (not is_asset) and bool(item_cc),
        "purchaseBillCount": len({b.id for b in acc["bills"] if _live(b.workflow_status)}),
        "unavailableMetrics": [
            {"metric": "approvedQty",
             "reason": "Indent items store a single quantity; there is no separately approved quantity."},
            {"metric": "rejectedReturnedQty",
             "reason": "GRN lines have no rejected/returned quantity field and there is no material "
                       "return document. Rejected GRN documents are excluded instead."},
        ],
    }

    stage_order = {k: i for i, k in enumerate(
        ["INDENT", "ENQUIRY", "ORDER", "GRN", "GIN", "DC", "BRR", "BRB", "PURCHASE_BILL", "BILL_PAYMENT"])}
    ledger.sort(key=lambda r: (r["date"] or "9999-99-99", r["stage"], stage_order.get(r["docType"], 99), r["docId"] or 0))
    for r in ledger:
        r.pop("stage", None)

    sev = {"error": 0, "warning": 1, "info": 2}
    exceptions.sort(key=lambda e: sev.get(e["severity"], 3))

    return {
        "source": src,
        "summary": summary,
        "enquiries": enquiries,
        "orders": orders,
        "legacyBilling": legacy,
        "ledger": ledger,
        "exceptions": exceptions,
        "allocationBasis": ALLOCATION_BASIS,
        "rules": {
            "ordered": "Sum of order lines on non-rejected orders (same as Order → indent pending list).",
            "received": "Sum of GRN lines on non-rejected GRNs (same as GRN balance logic).",
            "netAccepted": "Sum of GRN lines on approved GRNs (basis for stock and billing).",
            "issued": "Sum of GIN lines on non-rejected GINs (same as GIN stock check).",
            "stock": "Approved GRN quantity − non-rejected GIN quantity for this item's order lines "
                     "(same as GIN available-stock rule).",
            "billed": "Sum of BRB lines on non-rejected BRBs (same as BRB billing check).",
            "pendingBilling": "Per approved GRN line: received quantity − non-rejected BRB quantity "
                              "(same as BRB available-to-bill rule).",
            "paid": "Approved bill payment receipts only (same as Bill Payment logic).",
        },
    }


def _purchase_bill_node(bill, acc, item_cc, share, is_asset, note_status):
    items = acc["bill_items"].get(bill.id, [])
    gsts = acc["bill_gst"].get(bill.id, [])
    cc_items = [i for i in items if item_cc and i.cc_code == item_cc]
    cc_item_ids = {i.id for i in cc_items}
    cc_basic = sum((_d(i.basic_amount) for i in cc_items), ZERO)
    cc_gst = sum((_d(g.gst_amount) for g in gsts if g.cc_code == item_cc and g.is_selected), ZERO)
    gst_breakdown = defaultdict(lambda: ZERO)
    for g in gsts:
        if g.is_selected:
            gst_breakdown[g.gst_type] += _d(g.gst_amount)

    can_alloc = (share is not None) and (not is_asset) and bool(cc_items)
    reason = None
    if is_asset:
        reason = "Asset lines are not included in Purchase Bill CC lines."
    elif share is None:
        reason = "No approved BRB amount for this item's CC code under this BRR."
    elif not cc_items:
        reason = "This Purchase Bill has no line for the item's CC code."

    payments = []
    paid_basic = paid_gst = ip_basic = ip_gst = ZERO
    for r in acc["receipts"].get(bill.id, []):
        note_status("Bill Payment", r.receipt_no, r.workflow_status)
        r_basic = sum(
            (_d(x.current_amount) for x in acc["receipt_items"].get(r.id, []) if x.pb_item_id in cc_item_ids),
            ZERO,
        )
        r_gst = sum(
            (_d(x.current_amount) for x in acc["receipt_gst"].get(r.id, [])
             if x.is_selected and item_cc and x.cc_code == item_cc),
            ZERO,
        )
        if r.workflow_status == APPROVED:
            paid_basic += r_basic
            paid_gst += r_gst
        elif _live(r.workflow_status):
            ip_basic += r_basic
            ip_gst += r_gst
        payments.append({
            "receiptId": r.id,
            "receiptNo": r.receipt_no,
            "paymentDate": _date(r.payment_date),
            "workflowStatus": r.workflow_status,
            "paymentMode": r.payment_mode,
            "utrVoucherNo": r.utr_voucher_no,
            "receiptTotal": _amt(r.total_invoice_amount),
            "ccPaidBasic": _amt(r_basic),
            "ccPaidGst": _amt(r_gst),
            "allocatedAmount": _amt((r_basic + r_gst) * share) if can_alloc else None,
        })

    alloc = {
        "available": can_alloc,
        "reason": reason,
        "share": float(round(share, 6)) if share is not None else None,
        "ccCode": item_cc,
        "ccBasic": _amt(cc_basic),
        "ccGst": _amt(cc_gst),
        "billBasic": _amt(cc_basic * share) if can_alloc else None,
        "billGst": _amt(cc_gst * share) if can_alloc else None,
        "billTotal": _amt((cc_basic + cc_gst) * share) if can_alloc else None,
        "paidTotal": _amt((paid_basic + paid_gst) * share) if can_alloc else None,
        "inProcessTotal": _amt((ip_basic + ip_gst) * share) if can_alloc else None,
    }

    return {
        "purchaseBillId": bill.id,
        "purchaseBillNo": bill.purchase_bill_no,
        "processingDate": _date(bill.processing_date),
        "workflowStatus": bill.workflow_status,
        "vendorBillNo": bill.vendor_bill_no,
        "vendorBillDate": _date(bill.vendor_bill_date),
        "basicAmount": _amt(bill.basic_amount),
        "gstAmount": _amt(bill.gst_amount),
        "discount": _amt(bill.discount),
        "roundOff": _amt(bill.round_off),
        "totalInvoiceAmount": _amt(bill.total_invoice_amount),
        "gstBreakdown": {k: _amt(v) for k, v in gst_breakdown.items()},
        "allocation": alloc,
        "payments": payments,
    }


# ─────────────────────────────────────────────────────────────────
# HTTP-facing entry point
# ─────────────────────────────────────────────────────────────────

def get_indent_item_trace(indent_item_id, user_id):
    try:
        ii = _load_indent_item(indent_item_id)
        if not ii or not ii.indent:
            return res("Indent item not found", [], 404)

        project = ii.indent.project
        if not project or not user_can_view_indent(user_id, project.id):
            return res("Access denied", [], 403)

        return res("Item trace fetched successfully", build_indent_item_trace(ii), 200)

    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)
