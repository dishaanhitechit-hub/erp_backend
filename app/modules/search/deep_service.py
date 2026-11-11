# app/modules/search/deep_service.py
"""
Deep search ("360 view") for master records.

    quick_search      find a vendor / ledger or an item by name, code, GSTIN…
    get_overview      profile of that record + the tabs the user may open
    get_documents     the documents of one tab (orders of a vendor, GRNs of an item…)
    get_vendor_ledger ledger statement of a vendor

Access rules (same as the Traceability Workbench — see traceability/access.py):

* Masters (vendor, item) can be found by every logged-in user, the same as the
  master list endpoints (/master/ledger/list, /master/item/list).
* Documents are limited per document type to the projects where the user holds
  VIEW / EDIT / APPROVER on that document's page. A type the user may not see
  in any project is not returned as a tab at all, and asking for it directly
  gives 403.
* super_admin / admin see every project.

Everything here is read-only.
"""

from datetime import datetime

from sqlalchemy import func, null, or_, select

from app.extensions import db
from app.response import res
from app.models.vendor import Vendor
from app.models.item import Item
from app.models.unit import Unit
from app.models.indent_item import IndentItem
from app.models.orderMaster import OrderItem
from app.models.ORDER_projectwork import ProjectWorkOrderItem
from app.models.grnMaster import GrnItem
from app.models.srnMaster import SrnItem
from app.models.ginMaster import GinItem
from app.models.dcMaster import DcItem
from app.models.debitNote import DebitNoteMaster
from app.models.creditNote import CreditNoteMaster
from app.modules.traceability.access import TraceAccess
from app.modules.traceability.registry import DOC_TYPES
from app.modules.traceability.workbench_service import _as_date, _date, _num, _like
from app.modules.finance.vendor_ledger.service import _build_ledger, _parse_date

QUICK_LIMIT = 10
QUICK_LIMIT_MAX = 25
DOC_LIMIT = 100
DOC_LIMIT_MAX = 300
MIN_QUERY = 2
LEDGER_PAGES = ("ledger_view",)

# Documents that are not in the traceability registry (same shape as DOC_TYPES).
EXTRA_DOCS = {
    "DEBIT_NOTE": dict(
        label="Debit Note", model=DebitNoteMaster, no="debit_note_no", date="entry_date",
        projects=("project_code",), pages=("debit_note",), amount="total_amount",
    ),
    "CREDIT_NOTE": dict(
        label="Credit Note", model=CreditNoteMaster, no="credit_note_no", date="entry_date",
        projects=("project_code",), pages=("credit_note",), amount="total_amount",
    ),
}

# Page codes that also grant a document type, in addition to the registry's own.
# The Sale Order page is "sale_order" in the sidebar / permission screen.
EXTRA_PAGES = {
    "OG_SALE_ORDER": ("sale_order",),
}

# Vendor tabs, in display order: document type → column that holds the vendor id.
VENDOR_DOCS = [
    ("ORDER", "vendor_id"),
    ("PW_ORDER", "vendor_id"),
    ("GRN", "vendor_id"),
    ("SRN", "vendor_id"),
    ("GIN", "vendor_id"),
    ("DC", "from_vendor_id"),
    ("BRR", "vendor_id"),
    ("BRB", "vendor_id"),
    ("PURCHASE_BILL", "vendor_id"),
    ("DEBIT_NOTE", "vendor_id"),
    ("CREDIT_NOTE", "vendor_id"),
    ("BILL_PAYMENT", "vendor_id"),
    ("OG_SALE_ORDER", "debtor_id"),
]

# Item tabs, in display order: document type → how its lines point to the item.
#   line      line model            header   column on the line with the document id
#   qty       quantity column       rate     rate column (orders only)
#   via       (parent line model, fk on the line) when the item code is on the
#             parent order line and not on the line itself (GIN, SRN)
ITEM_DOCS = [
    ("INDENT", dict(line=IndentItem, header="indent_id", qty="qty")),
    ("ORDER", dict(line=OrderItem, header="order_id", qty="qty", rate="rate")),
    ("PW_ORDER", dict(line=ProjectWorkOrderItem, header="order_id", qty="qty", rate="rate")),
    ("GRN", dict(line=GrnItem, header="grn_id", qty="current_received_qty")),
    ("SRN", dict(line=SrnItem, header="srn_id", qty="current_received_qty",
                 via=(ProjectWorkOrderItem, "pw_order_item_id"))),
    ("GIN", dict(line=GinItem, header="gin_id", qty="issue_qty", via=(OrderItem, "order_item_id"))),
    ("DC", dict(line=DcItem, header="dc_id", qty="issue_qty")),
]

SUBJECTS = ("vendor", "item")


def _meta(doc_type):
    return DOC_TYPES.get(doc_type) or EXTRA_DOCS.get(doc_type)


def _pages(doc_type):
    return tuple(_meta(doc_type)["pages"]) + EXTRA_PAGES.get(doc_type, ())


def _limit(raw, default, maximum):
    try:
        return max(1, min(int(raw), maximum))
    except (TypeError, ValueError):
        return default


# ─────────────────────────────────────────────────────────────────
# quick search
# ─────────────────────────────────────────────────────────────────

def quick_search(kind, q, limit=None):
    """GET /search/quick?type=vendor|item&q=…  — at most `limit` matches, best first."""
    try:
        kind = (kind or "").lower()
        q = (q or "").strip()
        if kind not in SUBJECTS:
            return res("type must be vendor or item", [], 400)
        if len(q) < MIN_QUERY:
            return res(f"Type at least {MIN_QUERY} characters", [], 200)
        limit = _limit(limit, QUICK_LIMIT, QUICK_LIMIT_MAX)
        pattern = _like(q)
        starts = _like(q)[1:]  # "abc%" — names that start with the text come first

        if kind == "vendor":
            rows = (
                Vendor.query.filter(or_(
                    Vendor.ledger_name.ilike(pattern, escape="\\"),
                    Vendor.ledger_code.ilike(pattern, escape="\\"),
                    Vendor.gstin.ilike(pattern, escape="\\"),
                    Vendor.pan.ilike(pattern, escape="\\"),
                    Vendor.primary_contact_number.ilike(pattern, escape="\\"),
                ))
                .order_by(Vendor.ledger_name.ilike(starts, escape="\\").desc(), Vendor.ledger_name)
                .limit(limit).all()
            )
            return res("Search results", [_vendor_brief(v) for v in rows], 200)

        rows = (
            db.session.query(Item, Unit.short_name)
            .outerjoin(Unit, Unit.id == Item.unit_id)
            .filter(or_(
                Item.item_name.ilike(pattern, escape="\\"),
                Item.item_code.ilike(pattern, escape="\\"),
                Item.item_display_code.ilike(pattern, escape="\\"),
                Item.hsn_sac.ilike(pattern, escape="\\"),
            ))
            .order_by(Item.item_name.ilike(starts, escape="\\").desc(), Item.item_name)
            .limit(limit).all()
        )
        return res("Search results", [_item_brief(i, unit) for i, unit in rows], 200)
    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


def _vendor_brief(v):
    return {
        "kind": "vendor",
        "id": v.id,
        "code": v.ledger_code,
        "name": v.ledger_name,
        "gstin": v.gstin,
        "isDebtor": bool(v.is_debtor),
        "status": v.status,
    }


def _item_brief(i, unit=None):
    return {
        "kind": "item",
        "id": i.id,
        "code": i.item_display_code or i.item_code,
        "name": i.item_name,
        "categoryCode": i.category_code,
        "unit": unit,
        "status": i.status,
    }


# ─────────────────────────────────────────────────────────────────
# which documents belong to a vendor / an item
# ─────────────────────────────────────────────────────────────────

def _tab_types(kind):
    if kind == "vendor":
        return [dt for dt, _ in VENDOR_DOCS]
    return [dt for dt, _ in ITEM_DOCS]


def _subject_filter(kind, subject, doc_type):
    """SQL condition on the document's header table: 'this document is about the subject'."""
    model = _meta(doc_type)["model"]
    if kind == "vendor":
        column = dict(VENDOR_DOCS)[doc_type]
        return getattr(model, column) == subject.id
    return model.id.in_(_item_line_query(subject, doc_type, header_only=True))


def _item_line_query(item, doc_type, header_only=False):
    """Lines of `doc_type` that carry this item: (header id, qty[, rate]) — or only the header id."""
    spec = dict(ITEM_DOCS)[doc_type]
    line = spec["line"]
    header = getattr(line, spec["header"])
    cols = [header] if header_only else [
        header.label("header_id"),
        getattr(line, spec["qty"]).label("qty"),
        (getattr(line, spec["rate"]) if spec.get("rate") else null()).label("rate"),
    ]
    stmt = select(*cols)
    if spec.get("via"):
        parent, fk = spec["via"]
        stmt = stmt.select_from(line).join(parent, parent.id == getattr(line, fk))
        stmt = stmt.where(parent.item_code == item.item_code)
    else:
        stmt = stmt.where(line.item_code == item.item_code)
    return stmt


def _doc_query(kind, subject, doc_type, allowed):
    """Base filter list for the documents of one tab, limited to the allowed projects."""
    meta = _meta(doc_type)
    model = meta["model"]
    conditions = [_subject_filter(kind, subject, doc_type)]
    row_filter = meta.get("row_filter")
    if row_filter is not None:
        conditions.append(row_filter(model))
    if allowed is not None:
        cols = [getattr(model, c) for c in meta["projects"]]
        conditions.append(or_(*[c.in_(allowed or ["__none__"]) for c in cols]))
    return conditions


def _allowed_projects(access, doc_type):
    """None = every project; [] = no access; else the project codes."""
    return access.projects_for_pages(_pages(doc_type))


def _load_subject(kind, subject_id):
    if kind == "vendor":
        return Vendor.query.get(subject_id)
    if kind == "item":
        return Item.query.get(subject_id)
    return None


# ─────────────────────────────────────────────────────────────────
# overview: profile + tabs
# ─────────────────────────────────────────────────────────────────

def get_overview(user_id, kind, subject_id):
    """GET /search/360/<kind>/<id> — profile and the tabs (with counts) this user may open."""
    try:
        if kind not in SUBJECTS:
            return res("Unknown record type", [], 404)
        subject = _load_subject(kind, subject_id)
        if not subject:
            return res("Record not found", [], 404)
        access = TraceAccess(user_id)

        tabs = []
        if kind == "vendor":
            ledger_projects = access.projects_for_pages(LEDGER_PAGES)
            if ledger_projects is None or ledger_projects:
                tabs.append({"key": "LEDGER", "label": "Ledger", "kind": "ledger"})

        for doc_type in _tab_types(kind):
            allowed = _allowed_projects(access, doc_type)
            if allowed is not None and not allowed:
                continue  # no access to this document type anywhere → no tab
            meta = _meta(doc_type)
            count = db.session.execute(
                select(func.count()).select_from(meta["model"]).where(*_doc_query(kind, subject, doc_type, allowed))
            ).scalar() or 0
            tabs.append({"key": doc_type, "label": meta["label"], "kind": "documents", "count": count})

        profile = _vendor_profile(subject, access) if kind == "vendor" else _item_profile(subject)
        return res("Overview", {"kind": kind, "profile": profile, "tabs": tabs}, 200)
    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


def _vendor_profile(v, access):
    profile = {
        "id": v.id,
        "code": v.ledger_code,
        "name": v.ledger_name,
        "type": "Debtor (customer)" if v.is_debtor else "Creditor (vendor)",
        "categoryCode": v.category_code,
        "gstin": v.gstin,
        "pan": v.pan,
        "state": v.state_name,
        "registeredAddress": v.registered_address,
        "contactPerson": v.primary_contact_person,
        "contactNumber": v.primary_contact_number,
        "email": v.email,
        "status": v.status,
    }
    # bank details only for the roles that maintain the vendor master
    if access.is_global:
        profile.update({
            "bankName": v.bank_name,
            "bankAccountNumber": v.bank_account_number,
            "ifscCode": v.ifsc_code,
            "branchName": v.branch_name,
        })
    return profile


def _item_profile(i):
    unit = Unit.query.get(i.unit_id) if i.unit_id else None
    return {
        "id": i.id,
        "code": i.item_display_code or i.item_code,
        "itemCode": i.item_code,
        "name": i.item_name,
        "description": i.item_description,
        "categoryCode": i.category_code,
        "unit": unit.short_name if unit else None,
        "hsnSac": i.hsn_sac,
        "gstPercentage": _num(i.gst_percentage) if i.gst_percentage is not None else None,
        "status": i.status,
    }


# ─────────────────────────────────────────────────────────────────
# documents of one tab
# ─────────────────────────────────────────────────────────────────

def get_documents(user_id, kind, subject_id, doc_type, limit=None):
    """GET /search/360/<kind>/<id>/docs?type=ORDER — newest first."""
    try:
        if kind not in SUBJECTS:
            return res("Unknown record type", [], 404)
        doc_type = (doc_type or "").upper()
        if doc_type not in _tab_types(kind):
            return res("Unknown document type", [], 400)
        subject = _load_subject(kind, subject_id)
        if not subject:
            return res("Record not found", [], 404)

        access = TraceAccess(user_id)
        allowed = _allowed_projects(access, doc_type)
        if allowed is not None and not allowed:
            return res("Access denied", [], 403)

        limit = _limit(limit, DOC_LIMIT, DOC_LIMIT_MAX)
        meta = _meta(doc_type)
        model = meta["model"]
        proj_cols = [getattr(model, c) for c in meta["projects"]]
        status_col = getattr(model, "workflow_status", None)
        amount_col = getattr(model, meta["amount"]) if meta.get("amount") else None

        stmt = (
            select(
                model.id.label("doc_id"),
                getattr(model, meta["no"]).label("doc_no"),
                _as_date(getattr(model, meta["date"])).label("doc_date"),
                (status_col if status_col is not None else null()).label("status"),
                (amount_col if amount_col is not None else null()).label("amount"),
                *[c.label(f"project_{n}") for n, c in enumerate(proj_cols)],
                *([model.billing_type.label("billing_type")] if doc_type == "BRB" else []),
            )
            .where(*_doc_query(kind, subject, doc_type, allowed))
            .order_by(model.id.desc())
            .limit(limit)
        )
        docs = db.session.execute(stmt).all()

        # item tabs: quantity (and order rate) of this item on each document
        qty_by_doc = {}
        if kind == "item" and docs:
            line_sq = _item_line_query(subject, doc_type).subquery()
            for header_id, qty, rate in db.session.execute(
                select(line_sq.c.header_id, func.sum(line_sq.c.qty), func.max(line_sq.c.rate))
                .where(line_sq.c.header_id.in_([d.doc_id for d in docs]))
                .group_by(line_sq.c.header_id)
            ).all():
                qty_by_doc[header_id] = (qty, rate)

        out = []
        for d in docs:
            projects = [getattr(d, f"project_{n}") for n in range(len(proj_cols))]
            row = {
                "docType": doc_type,
                "typeLabel": meta["label"],
                "docId": d.doc_id,
                "docNo": d.doc_no,
                "date": _date(d.doc_date),
                "status": d.status,
                "projectCode": " → ".join(p for p in projects if p),
                "amount": _num(d.amount) if d.amount is not None else None,
            }
            if doc_type == "BRB":
                row["billingType"] = d.billing_type
            if kind == "item":
                qty, rate = qty_by_doc.get(d.doc_id, (None, None))
                row["qty"] = _num(qty, 4) if qty is not None else None
                row["rate"] = _num(rate) if rate is not None else None
            out.append(row)

        return res("Documents", {"rows": out, "limit": limit, "hasMore": len(out) == limit}, 200)
    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ─────────────────────────────────────────────────────────────────
# vendor ledger
# ─────────────────────────────────────────────────────────────────

def get_vendor_ledger(user_id, vendor_id, from_date=None, to_date=None):
    """
    GET /search/360/vendor/<id>/ledger — the vendor's ledger statement
    (approved purchase bills, payments, debit and credit notes), limited to the
    projects where the user may open Ledger View.
    """
    try:
        vendor = Vendor.query.get(vendor_id)
        if not vendor:
            return res("Record not found", [], 404)
        access = TraceAccess(user_id)
        allowed = access.projects_for_pages(LEDGER_PAGES)
        if allowed is not None and not allowed:
            return res("Access denied", [], 403)

        _, entries = _build_ledger(vendor.id, None, _parse_date(from_date), _parse_date(to_date))
        if allowed is not None:
            entries = [e for e in entries if e["projectCode"] in allowed]

        # running balance over what this user may see: credit = we owe the vendor
        balance = 0.0
        for e in entries:
            balance += e["credit"] - e["debit"]
            e["balance"] = round(abs(balance), 2)
            e["balanceType"] = "Cr" if balance >= 0 else "Dr"
        total_debit = round(sum(e["debit"] for e in entries), 2)
        total_credit = round(sum(e["credit"] for e in entries), 2)
        closing = round(total_credit - total_debit, 2)

        return res("Vendor ledger", {
            "summary": {
                "totalDebit": total_debit,
                "totalCredit": total_credit,
                "closingBalance": round(abs(closing), 2),
                "balanceType": "Cr" if closing >= 0 else "Dr",
            },
            "entries": entries,
            "allProjects": allowed is None,
            "generatedAt": datetime.utcnow().strftime("%Y-%m-%d %H:%M"),
        }, 200)
    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)
