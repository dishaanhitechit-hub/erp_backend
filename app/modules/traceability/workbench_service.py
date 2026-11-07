# app/modules/traceability/workbench_service.py
"""
Traceability Workbench: context, document search and document inspector.
Read-only. All access goes through TraceAccess.
"""

from collections import defaultdict
from decimal import Decimal

from sqlalchemy import or_, func, select, literal, cast, null, union_all, Date, DateTime, String
from sqlalchemy.orm import aliased

from app.extensions import db
from app.response import res
from app.models.item import Item
from app.models.asset import Asset
from app.models.unit import Unit
from app.models.vendor import Vendor
from app.models.indent_master import IndentMaster
from app.models.indent_item import IndentItem
from app.models.purchaseBill import PurchaseBillItem, PurchaseBillGst
from app.models.billPaymentReceipt import BillPaymentReceiptItem, BillPaymentReceiptGst
from app.models.saleBill import SaleBillItem, SaleBillGst
from app.models.saleReceiptBilling import SaleReceiptItem, SaleReceiptGst
from app.models.billingMaster import BillingItem, BillingBoqItem

from app.modules.traceability.access import TraceAccess
from app.modules.traceability.registry import (
    DOC_TYPES, LINE_TYPES, LINE_LINKS, STAGES, doc_projects,
)

ZERO = Decimal("0")
SEARCH_LIMIT_PER_TYPE = 8


def _d(v):
    return Decimal(str(v)) if v is not None else ZERO


def _date(v):
    return v.strftime("%Y-%m-%d") if v else None


def _num(v, places=2):
    return float(round(_d(v), places)) if v is not None else None


def _like(q):
    q = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{q}%"


def _project_filter(dt, allowed):
    """SQL filter limiting a document type to allowed project codes (None = no limit)."""
    if allowed is None:
        return None
    model = DOC_TYPES[dt]["model"]
    cols = [getattr(model, c) for c in DOC_TYPES[dt]["projects"]]
    return or_(*[c.in_(allowed or ["__none__"]) for c in cols])


# ─────────────────────────────────────────────────────────────────
# context
# ─────────────────────────────────────────────────────────────────

def get_workbench_context(user_id):
    try:
        access = TraceAccess(user_id)
        types = []
        for dt, m in DOC_TYPES.items():
            allowed = access.projects_for_pages(m["pages"])
            types.append({
                "docType": dt, "label": m["label"], "stage": m["stage"], "flow": m["flow"],
                "legacy": bool(m.get("legacy")), "searchable": allowed is None or bool(allowed),
            })
        return res("Workbench context", {
            "isGlobal": access.is_global,
            "role": access.role,
            "projects": [{"code": p["code"], "name": p["name"]} for p in access.projects()],
            "docTypes": types,
            "stages": [{"key": k, "label": l} for k, l in STAGES],
        }, 200)
    except Exception as e:
        return res(str(e), [], 500)


# ─────────────────────────────────────────────────────────────────
# search
# ─────────────────────────────────────────────────────────────────

def _as_date(col):
    """Date columns as-is; datetime columns truncated with date(), valid in Postgres and SQLite."""
    return func.date(col, type_=Date) if isinstance(col.type, DateTime) else col


def _doc_select(dt, pattern, allowed, limit):
    """
    One SELECT for a document type, normalised to the same columns so all types
    can be UNION ALL-ed into a single round trip. Each part keeps its own
    ORDER BY id DESC LIMIT (newest first, uses the primary-key index).
    """
    meta = DOC_TYPES[dt]
    model = meta["model"]
    no_col = getattr(model, meta["no"])
    vendor_fk = getattr(model, "vendor_id", None) or getattr(model, "from_vendor_id", None)
    proj_cols = [getattr(model, c) for c in meta["projects"]]
    project = proj_cols[0] if len(proj_cols) == 1 else func.coalesce(*reversed(proj_cols))

    # Some documents (e.g. Sale Receipt) have no workflow_status column.
    status_col = (getattr(model, "workflow_status") if hasattr(model, "workflow_status")
                  else cast(null(), String))
    vendor_join_fk = getattr(model, "vendor_id", None) or getattr(model, "from_vendor_id", None) \
        or getattr(model, "debtor_id", None)

    stmt = select(
        literal(dt).label("doc_type"),
        model.id.label("doc_id"),
        no_col.label("doc_no"),
        _as_date(getattr(model, meta["date"])).label("doc_date"),
        status_col.label("status"),
        cast(project, String).label("project_code"),
        (Vendor.ledger_name if vendor_join_fk is not None else cast(null(), String)).label("party"),
    )
    if vendor_join_fk is not None:
        stmt = stmt.select_from(model).outerjoin(Vendor, Vendor.id == vendor_join_fk)
    if pattern:
        stmt = stmt.where(no_col.ilike(pattern, escape="\\"))
    # Shared-table doc types (Claim vs Certified bill) restrict rows by their mode filter.
    row_filter = meta.get("row_filter")
    if row_filter is not None:
        stmt = stmt.where(row_filter(model))
    pf = _project_filter(dt, allowed)
    if pf is not None:
        stmt = stmt.where(pf)
    return stmt.order_by(model.id.desc()).limit(limit).subquery()


def _item_lines(pattern, allowed, limit):
    """Indent lines whose item / asset matches (or the newest ones when no pattern), names joined in."""
    ItemUnit, AssetUnit = aliased(Unit), aliased(Unit)
    q = (db.session.query(
            IndentItem.id, IndentItem.is_asset, IndentItem.item_code, IndentItem.asset_code, IndentItem.qty,
            IndentMaster.indent_no, IndentMaster.indent_date, IndentMaster.workflow_status,
            IndentMaster.project_code,
            Item.item_name, Item.item_display_code, Asset.asset_name,
            ItemUnit.short_name.label("item_unit"), AssetUnit.short_name.label("asset_unit"))
         .join(IndentMaster, IndentMaster.id == IndentItem.indent_id)
         .outerjoin(Item, Item.item_code == IndentItem.item_code)
         .outerjoin(Asset, Asset.asset_code == IndentItem.asset_code)
         .outerjoin(ItemUnit, ItemUnit.id == Item.unit_id)
         .outerjoin(AssetUnit, AssetUnit.id == Asset.unit_id))
    if pattern:
        q = q.filter(or_(
            Item.item_code.ilike(pattern, escape="\\"), Item.item_name.ilike(pattern, escape="\\"),
            Item.item_display_code.ilike(pattern, escape="\\"),
            Asset.asset_code.ilike(pattern, escape="\\"), Asset.asset_name.ilike(pattern, escape="\\")))
    if allowed is not None:
        q = q.filter(IndentMaster.project_code.in_(allowed or ["__none__"]))
    return q.order_by(IndentItem.id.desc()).limit(limit).all()


def search_documents(user_id, q, doc_type=None, project_code=None):
    """
    Search (q given) or suggest (q empty: newest documents) in at most two
    queries: one UNION ALL over every permitted document type, and one for
    indent lines when items are included.
    """
    try:
        q = (q or "").strip()
        access = TraceAccess(user_id)
        if project_code and project_code not in access.project_codes():
            return res("Access denied", [], 403)

        doc_type = (doc_type or "").upper() or None
        single = doc_type is not None
        types = [doc_type] if doc_type in DOC_TYPES else ([] if single else
                                                          [t for t, m in DOC_TYPES.items() if not m.get("legacy")])
        pattern = _like(q) if q else None
        # more rows when one type is chosen; a few per type when browsing all
        per_type = (SEARCH_LIMIT_PER_TYPE * 2 if single else SEARCH_LIMIT_PER_TYPE) if q else (15 if single else 3)

        def allowed_for(pages):
            allowed = access.projects_for_pages(pages)
            if project_code:
                allowed = [project_code] if allowed is None or project_code in allowed else []
            return allowed

        parts = []
        for dt in types:
            allowed = allowed_for(DOC_TYPES[dt]["pages"])
            if allowed is not None and not allowed:
                continue
            parts.append(_doc_select(dt, pattern, allowed, per_type))

        rows = []
        if parts:
            cols = lambda sq: select(sq.c.doc_type, sq.c.doc_id, sq.c.doc_no, sq.c.doc_date, sq.c.status,
                                     sq.c.project_code, sq.c.party)
            stmt = union_all(*[cols(sq) for sq in parts]) if len(parts) > 1 else cols(parts[0])
            rows = db.session.execute(stmt).all()

        out = []
        for r in rows:
            meta = DOC_TYPES[r.doc_type]
            out.append({
                "docType": r.doc_type, "typeLabel": meta["label"], "docId": r.doc_id, "docNo": r.doc_no,
                "date": _date(r.doc_date), "status": r.status, "projectCode": r.project_code,
                "party": r.party, "stage": meta["stage"],
            })
        # newest first inside each type, types in lifecycle order
        order = {t: i for i, t in enumerate(DOC_TYPES)}
        out.sort(key=lambda x: (order[x["docType"]], -x["docId"]))

        if doc_type in (None, "INDENT_ITEM"):
            allowed = allowed_for(DOC_TYPES["INDENT"]["pages"])
            if allowed is None or allowed:
                limit = 15 if single else (12 if q else 5)
                for ii in _item_lines(pattern, allowed, limit):
                    code = ii.asset_code if ii.is_asset else (ii.item_display_code or ii.item_code)
                    out.append({
                        "docType": "INDENT_ITEM", "typeLabel": "Indent Item", "docId": ii.id,
                        "docNo": ii.indent_no, "date": _date(ii.indent_date), "status": ii.workflow_status,
                        "projectCode": ii.project_code, "party": None, "stage": "REQUISITION",
                        "itemCode": code, "itemName": ii.asset_name if ii.is_asset else ii.item_name,
                        "qty": _num(ii.qty, 4), "unit": ii.asset_unit if ii.is_asset else ii.item_unit,
                    })
        return res("Suggestions" if not q else "Search results", out, 200)
    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ─────────────────────────────────────────────────────────────────
# document inspector
# ─────────────────────────────────────────────────────────────────

HEADER_FIELDS = {
    "INDENT": [("Priority", "priority", "text"), ("Required Within", "required_within", "date"),
               ("Placed By", "indent_placed_by", "text"), ("Site Reg. Serial", "site_reg_serial_no", "text"),
               ("Remarks", "remarks", "text")],
    "ORDER": [("Order Type", "category_code", "code"), ("Quotation No", "quotation_no", "text"),
              ("Quotation Date", "quotation_date", "date"), ("Validity", "validity_date", "date"),
              ("Taxable", "basic_amount", "amount"), ("GST", "gst_amount", "amount"),
              ("Total", "total_amount", "amount")],
    "PW_ORDER": [("Quotation No", "quotation_no", "text"), ("Quotation Date", "quotation_date", "date"),
                 ("Taxable", "basic_amount", "amount"), ("GST", "gst_amount", "amount"),
                 ("Total", "total_amount", "amount")],
    "GRN": [("Challan No", "challan_no", "text"), ("Party Bill No", "party_bill_no", "text"),
            ("Party Bill Date", "party_bill_date", "date"), ("Vehicle", "deliver_vehicle_no", "text"),
            ("Verified By", "physically_verified_by", "text")],
    "SRN": [("Challan No", "challan_no", "text"), ("Party Bill No", "party_bill_no", "text"),
            ("Party Bill Date", "party_bill_date", "date"), ("Verified By", "physically_verified_by", "text")],
    "GIN": [("Issue Category", "issue_category", "text"), ("Issue Slip No", "issue_slip_no", "text"),
            ("Handed Over To", "handed_over_to", "text"), ("Despatch From", "despatch_from", "text")],
    "DC": [("Order Type", "order_type", "code"), ("From Project", "from_project_code", "text"),
           ("To Project", "to_project_code", "text"), ("Vehicle", "vehicle_number", "text"),
           ("E-way Bill", "eway_bill_number", "text")],
    "BRR": [("Billing Type", "order_type", "text"), ("Party Bill No", "party_bill_no", "text"),
            ("Party Bill Date", "party_date", "date"), ("Received Through", "received_through", "text"),
            ("Taxable", "basic_amount", "amount"), ("GST", "gst_amount", "amount"),
            ("Total", "total_amount", "amount")],
    "BRB": [("Billing Type", "billing_type", "text"), ("Party Bill No", "party_bill_no", "text"),
            ("Taxable", "basic_amount", "amount"), ("GST", "gst_amount", "amount"),
            ("Total", "total_amount", "amount")],
    "BVS": [("Party Bill No", "party_bill_no", "text"), ("Taxable", "basic_amount", "amount"),
            ("GST", "gst_amount", "amount"), ("Total", "total_amount", "amount")],
    "BSS": [("Party Bill No", "party_bill_no", "text"), ("Taxable", "basic_amount", "amount"),
            ("GST", "gst_amount", "amount"), ("Total", "total_amount", "amount")],
    "PURCHASE_BILL": [("Mode", "mode", "text"), ("Vendor Bill No", "vendor_bill_no", "text"),
                      ("Vendor Bill Date", "vendor_bill_date", "date"), ("BRR No", "brr_no", "text"),
                      ("Taxable", "basic_amount", "amount"), ("GST", "gst_amount", "amount"),
                      ("Discount", "discount", "amount"), ("Round Off", "round_off", "amount"),
                      ("Total", "total_invoice_amount", "amount")],
    "BILL_PAYMENT": [("Payment Mode", "payment_mode", "text"), ("UTR / Voucher", "utr_voucher_no", "text"),
                     ("Vendor Bill No", "vendor_bill_no", "text"), ("Taxable", "basic_amount", "amount"),
                     ("GST", "gst_amount", "amount"), ("Discount", "discount", "amount"),
                     ("Total", "total_invoice_amount", "amount")],
    # ── Sales lifecycle ──────────────────────────────────────────────
    "OG_SALE_ORDER": [("Order Title", "order_title", "text"), ("Order No", "order_no", "text"),
                      ("Validity", "order_validity", "date"), ("Taxable", "basic_amount", "amount"),
                      ("GST", "gst_amount", "amount"), ("Total", "total_amount", "amount")],
    "CLAIM_BILL": [("Bill No", "billing_no", "text"), ("ERP No", "erp_no", "text"),
                   ("OG Sale Order", "og_sale_order_erp_no", "text"), ("Job Location", "job_location", "text"),
                   ("This Bill Claim", "this_bill_claim", "amount"), ("GST", "gst_amount", "amount"),
                   ("Total Claim", "total_claim", "amount")],
    "CERTIFIED_BILL": [("Bill No", "billing_no", "text"), ("ERP No", "erp_no", "text"),
                       ("OG Sale Order", "og_sale_order_erp_no", "text"),
                       ("Pre-certified", "pre_certified_amount", "amount"),
                       ("This Bill Claim", "this_bill_claim", "amount"), ("GST", "gst_amount", "amount"),
                       ("Total Certified", "total_claim", "amount")],
    "SALE_BILL": [("Mode", "mode", "text"), ("Sale Order No", "sale_order_no", "text"),
                  ("Certified Bill No", "certified_bill_no", "text"), ("Taxable", "basic_amount", "amount"),
                  ("GST", "gst_amount", "amount"), ("Discount", "discount", "amount"),
                  ("Round Off", "round_off", "amount"), ("Total", "total_invoice_amount", "amount")],
    "SALE_RECEIPT": [("Payment Mode", "payment_mode", "text"), ("UTR / Voucher", "utr_voucher_no", "text"),
                     ("Remarks", "payment_remarks", "text"), ("Total", "total_amount", "amount")],
    "SALE_RECEIPT_BILLING": [("Invoice No", "invoice_no", "text"), ("Invoice Date", "invoice_date", "date"),
                             ("Certified Bill No", "bill_abstract_no", "text"),
                             ("Taxable", "basic_amount", "amount"), ("GST", "gst_amount", "amount"),
                             ("Discount", "discount", "amount"), ("Round Off", "round_off", "amount"),
                             ("Total", "total_invoice_amount", "amount")],
    # ── Standalone financial documents ───────────────────────────────
    "CONTRA_ENTRY": [("Remarks", "remarks", "text"), ("Total", "total_amount", "amount")],
    "PETTY_CASH_VOUCHER": [("Expenses By", "expenses_by", "text"), ("Mode", "mode_of_payment", "text"),
                           ("Payment Ref", "payment_ref_id", "text"), ("Total", "total_amount", "amount")],
}


def _fmt_field(row, attr, kind):
    v = getattr(row, attr, None)
    if v is None or v == "":
        return None
    if kind == "date":
        return _date(v)
    if kind == "amount":
        return _num(v)
    if kind == "code":
        return str(v).replace("_", " ")
    return v


def _line_parent_link(lt):
    """[(fk, parent line type)] of exact upward links from this line type."""
    return [(fk, plt) for clt, fk, plt, _ in LINE_LINKS if clt == lt]


def _document_lines(dt, doc_id):
    lt = DOC_TYPES[dt]["line"]
    if not lt:
        return []
    meta = LINE_TYPES[lt]
    model = meta["model"]
    rows = model.query.filter(getattr(model, meta["header"]) == doc_id).order_by(model.id).all()

    # parent lines (one hop) and grand-parent lines (second hop, for item identity)
    parents = {}
    for fk, plt in _line_parent_link(lt):
        ids = {getattr(r, fk) for r in rows if getattr(r, fk, None)}
        if ids:
            pm = LINE_TYPES[plt]["model"]
            for p in pm.query.filter(pm.id.in_(ids)).all():
                parents[(plt, p.id)] = p
    grand = {}
    for (plt, _pid), p in list(parents.items()):
        for fk, gplt in _line_parent_link(plt):
            gid = getattr(p, fk, None)
            if gid:
                grand.setdefault(gplt, set()).add(gid)
    for gplt, ids in grand.items():
        gm = LINE_TYPES[gplt]["model"]
        for g in gm.query.filter(gm.id.in_(ids)).all():
            parents[(gplt, g.id)] = g

    # header numbers of the parent lines' documents
    hdr_ids = defaultdict(set)
    for (plt, _pid), p in parents.items():
        hdr_ids[LINE_TYPES[plt]["doc"]].add(getattr(p, LINE_TYPES[plt]["header"]))
    hdr_no = {}
    for pdt, ids in hdr_ids.items():
        hm = DOC_TYPES[pdt]["model"]
        for h in hm.query.filter(hm.id.in_(ids)).all():
            hdr_no[(pdt, h.id)] = getattr(h, DOC_TYPES[pdt]["no"])

    def item_of(row, row_lt, depth=0):
        if hasattr(row, "item_code") and (getattr(row, "item_code", None) or getattr(row, "asset_code", None)):
            if getattr(row, "is_asset", False):
                return ("A", row.asset_code)
            return ("I", row.item_code)
        if depth > 2:
            return None
        for fk, plt in _line_parent_link(row_lt):
            p = parents.get((plt, getattr(row, fk, None)))
            if p is not None:
                return item_of(p, plt, depth + 1)
        return None

    keys = {item_of(r, lt) for r in rows} - {None}
    names = {}
    ic = [k[1] for k in keys if k[0] == "I"]
    ac = [k[1] for k in keys if k[0] == "A"]
    if ic:
        for i in Item.query.filter(Item.item_code.in_(ic)).all():
            names[("I", i.item_code)] = (i.item_name, i.unit.short_name if i.unit else None,
                                         i.item_display_code or i.item_code)
    if ac:
        for a in Asset.query.filter(Asset.asset_code.in_(ac)).all():
            names[("A", a.asset_code)] = (a.asset_name, a.unit.short_name if a.unit else None, a.asset_code)

    out = []
    for r in rows:
        k = item_of(r, lt)
        name, unit, code = names.get(k, (None, None, k[1] if k else None))
        refs = []
        for fk, plt in _line_parent_link(lt):
            p = parents.get((plt, getattr(r, fk, None)))
            if p is not None:
                pdt = LINE_TYPES[plt]["doc"]
                pid = getattr(p, LINE_TYPES[plt]["header"])
                refs.append({"docType": pdt, "docId": pid, "docNo": hdr_no.get((pdt, pid)), "lineId": p.id})
        out.append({
            "lineId": r.id, "lineType": lt,
            "itemCode": code, "itemName": name, "unit": unit, "isAsset": bool(k and k[0] == "A"),
            "qty": _num(getattr(r, meta["qty"]), 4),
            "rate": _num(getattr(r, "rate", None)),
            "amount": _num(getattr(r, "amount", None)),
            "gstPercent": _num(getattr(r, "gst_percent", None)),
            "gstAmount": _num(getattr(r, "gst_amount", None)),
            "location": getattr(r, "location", None) or getattr(r, "store_location", None)
                        or getattr(r, "stock_location", None),
            "parentRefs": refs,
        })
    return out


def _cc_lines(dt, doc_id):
    if dt == "PURCHASE_BILL":
        items = PurchaseBillItem.query.filter_by(purchase_bill_id=doc_id).order_by(PurchaseBillItem.sl_no).all()
        gst = PurchaseBillGst.query.filter_by(purchase_bill_id=doc_id).all()
        return {
            "ccLines": [{"slNo": i.sl_no, "ccCode": i.cc_code, "ccName": i.cc_name, "description": i.description,
                         "amount": _num(i.basic_amount)} for i in items],
            "gstLines": [{"gstType": g.gst_type, "ccCode": g.cc_code, "percent": _num(g.percent),
                          "amount": _num(g.gst_amount), "selected": bool(g.is_selected)} for g in gst],
        }
    if dt == "BILL_PAYMENT":
        items = BillPaymentReceiptItem.query.filter_by(receipt_id=doc_id).order_by(BillPaymentReceiptItem.sl_no).all()
        gst = BillPaymentReceiptGst.query.filter_by(receipt_id=doc_id).all()
        return {
            "ccLines": [{"slNo": i.sl_no, "ccCode": i.cc_code, "ccName": i.cc_name,
                         "booked": _num(i.booked_amount), "amount": _num(i.current_amount)} for i in items],
            "gstLines": [{"gstType": g.gst_type, "ccCode": g.cc_code, "booked": _num(g.booked_amount),
                          "amount": _num(g.current_amount), "selected": bool(g.is_selected)} for g in gst],
        }
    if dt == "SALE_BILL":
        items = SaleBillItem.query.filter_by(sale_bill_id=doc_id).order_by(SaleBillItem.sl_no).all()
        gst = SaleBillGst.query.filter_by(sale_bill_id=doc_id).all()
        return {
            "ccLines": [{"slNo": i.sl_no, "ccCode": i.cc_code, "ccName": i.cc_name,
                         "gstPercent": _num(i.gst_percent), "amount": _num(i.basic_amount)} for i in items],
            "gstLines": [{"gstType": g.gst_type, "ccCode": g.cc_code, "percent": _num(g.percent),
                          "amount": _num(g.gst_amount), "selected": bool(g.is_selected)} for g in gst],
        }
    if dt == "SALE_RECEIPT_BILLING":
        items = SaleReceiptItem.query.filter_by(receipt_id=doc_id).order_by(SaleReceiptItem.sl_no).all()
        gst = SaleReceiptGst.query.filter_by(receipt_id=doc_id).all()
        return {
            "ccLines": [{"slNo": i.sl_no, "ccCode": i.cc_code, "ccName": i.cc_name,
                         "booked": _num(i.booked_amount), "amount": _num(i.current_amount)} for i in items],
            "gstLines": [{"gstType": g.gst_type, "ccCode": g.cc_code, "percent": _num(g.percent),
                          "booked": _num(g.booked_amount), "amount": _num(g.current_amount),
                          "selected": bool(g.is_selected)} for g in gst],
        }
    if dt in ("CLAIM_BILL", "CERTIFIED_BILL"):
        # Claim/Certified bills carry item + BOQ lines (quantity-based, with per-line GST).
        items = BillingItem.query.filter_by(billing_id=doc_id).order_by(BillingItem.sl_no).all()
        boq = BillingBoqItem.query.filter_by(billing_id=doc_id).order_by(BillingBoqItem.sl_no).all()
        def _row(i, section):
            return {"slNo": i.sl_no, "section": section, "itemCode": i.item_code,
                    "itemName": i.item_name, "unit": i.unit, "claimQty": _num(i.claim_qty, 4),
                    "rate": _num(i.rate, 4), "amount": _num(i.amount),
                    "gstPercent": _num(i.gst_percent), "gstAmount": _num(i.gst_amount)}
        return {
            "billingLines": [_row(i, "ITEM") for i in items] + [_row(i, "BOQ") for i in boq],
        }
    return {}


def get_document_detail(user_id, doc_type, doc_id):
    try:
        dt = (doc_type or "").upper()
        if dt not in DOC_TYPES:
            return res("Unknown document type", [], 400)
        meta = DOC_TYPES[dt]
        row = meta["model"].query.get(doc_id)
        if not row:
            return res("Document not found", [], 404)
        access = TraceAccess(user_id)
        projects = [p for p in doc_projects(dt, row) if p]
        if not access.can_view(meta["pages"], projects):
            return res("Access denied", [], 403)

        v = getattr(row, "vendor_id", None) or getattr(row, "from_vendor_id", None)
        vendor = Vendor.query.get(v) if v else None

        fields = []
        for label, attr, kind in HEADER_FIELDS.get(dt, []):
            val = _fmt_field(row, attr, kind)
            if val is not None:
                fields.append({"label": label, "value": val, "kind": "amount" if kind == "amount" else
                               ("date" if kind == "date" else "text")})

        data = {
            "docType": dt, "typeLabel": meta["label"], "docId": row.id,
            "docNo": getattr(row, meta["no"]), "date": _date(getattr(row, meta["date"])),
            "status": getattr(row, "workflow_status", None), "projectCodes": projects,
            "party": vendor.ledger_name if vendor else None,
            "partyGstin": vendor.gstin if vendor else None,
            "submittedAt": str(row.submitted_at) if getattr(row, "submitted_at", None) else None,
            "approvedAt": str(row.final_approved_at) if getattr(row, "final_approved_at", None) else None,
            "rejectedAt": str(row.rejected_at) if getattr(row, "rejected_at", None) else None,
            "billingType": getattr(row, "billing_type", None) if dt == "BRB" else None,
            "fields": fields,
            "lines": _document_lines(dt, row.id),
            **_cc_lines(dt, row.id),
        }
        return res("Document detail", data, 200)
    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)
