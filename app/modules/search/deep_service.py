# app/modules/search/deep_service.py
"""
Deep search ("360 view") for master records.

    quick_search      find a record by name, code, GSTIN…
    get_overview      profile of that record + the tabs the user may open
    get_documents     the documents of one tab (orders of a vendor, GRNs of an item…)
    get_table         a non-document tab (payroll of an employee…)
    get_vendor_ledger ledger statement of a vendor

Record types (SUBJECTS): vendor, item, asset, project, bank, cc, employee.
To add a document tab to a record type, add one line to its "tabs" list.

Access rules (same as the Traceability Workbench — see traceability/access.py):

* Vendor, item, asset, bank / cash and cost centre can be found by every
  logged-in user, the same as the master list endpoints.
* Projects: only the projects the user is assigned to.
* Employees: the same page permissions the HR endpoints use
  (employee_management / payroll / performance_appraisal / onboarding . VIEW).
* Documents are limited per document type to the projects where the user holds
  VIEW / EDIT / APPROVER on that document's page. A type the user may not see
  in any project is not returned as a tab at all, and asking for it directly
  gives 403.
* super_admin / admin see every project.

Everything here is read-only.
"""

from datetime import datetime

from flask_jwt_extended import get_jwt
from sqlalchemy import func, null, or_, select

from app.extensions import db
from app.response import res
from app.models.vendor import Vendor
from app.models.item import Item
from app.models.asset import Asset
from app.models.unit import Unit
from app.models.project import Project
from app.models.bankCash import BankCash
from app.models.cc_code import CCCode
from app.models.employee import Employee
from app.models.user import User
from app.models.indent_item import IndentItem
from app.models.orderMaster import OrderItem
from app.models.ORDER_projectwork import ProjectWorkOrderItem
from app.models.grnMaster import GrnItem
from app.models.srnMaster import SrnItem
from app.models.ginMaster import GinItem
from app.models.dcMaster import DcItem
from app.models.debitNote import DebitNoteMaster, DebitNoteItem
from app.models.creditNote import CreditNoteMaster, CreditNoteItem
from app.models.purchaseBill import PurchaseBillItem
from app.models.saleBill import SaleBillItem
from app.models.paymentVoucher import PaymentVoucherMaster
from app.models.journalEntry import JournalEntryMaster, JournalEntryLine
from app.models.contraEntry import ContraEntryLine
from app.models.pettyCashBudget import PettyCashBudget
from app.models.payrollModel import PayrollRun, PayrollEntry
from app.models.performanceModel import PerformanceReview, DisciplineCase
from app.models.onboarding import OnboardingTask
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
    "PAYMENT_VOUCHER": dict(
        label="Payment Voucher", model=PaymentVoucherMaster, no="payment_vouch_no", date="payment_date",
        projects=("project_code",), pages=("payment",), amount="total_invoice_amount",
    ),
    "JOURNAL": dict(
        label="Journal Entry", model=JournalEntryMaster, no="voucher_no", date="entry_date",
        projects=("project_code",), pages=("journal",), amount="total_debit",
    ),
    "PETTY_CASH_BUDGET": dict(
        label="Petty Cash Budget", model=PettyCashBudget, no="budget_no", date="budget_date",
        projects=("project_code",), pages=("petty_cash",), amount="total_budget_amount",
    ),
}

# Page codes that also grant a document type, in addition to the registry's own:
# the codes the sidebar / permission screen use for the same pages.
EXTRA_PAGES = {
    "OG_SALE_ORDER": ("sale_order",),
    "CLAIM_BILL": ("sale_claim_bill",),
    "CERTIFIED_BILL": ("sale_certified_bill",),
    "SALE_BILL": ("sale",),
    "SALE_RECEIPT": ("receipt",),
    "SALE_RECEIPT_BILLING": ("receipt",),
    "CONTRA_ENTRY": ("contra",),
}


# ─────────────────────────────────────────────────────────────────
# how a document belongs to a record
# ─────────────────────────────────────────────────────────────────
#
#   cols(...)   the document header has a column with the record's id
#   line(...)   the document's lines carry the record:
#                 model   line model          header  column with the document id
#                 match   (column on the line, attribute of the record)
#                 qty / rate                  quantity and rate columns to show
#                 amount  expression for "amount on this record"
#                 via     (parent line model, fk on the line) when the match
#                         column is on the parent order line (GIN, SRN)
#   PROJECT     the document is in the record's project

def cols(*names):
    return {"cols": names}


def line(model, header, match, qty=None, rate=None, amount=None, via=None):
    return {"line": model, "header": header, "match": match, "qty": qty, "rate": rate, "amount": amount, "via": via}


PROJECT = {"project": True}


def _stock_tabs(code):
    """Tabs of something that is bought and stocked (item or asset): matched by its code on the lines."""
    match = (code, code)
    tabs = [
        ("INDENT", line(IndentItem, "indent_id", match, qty="qty")),
        ("ORDER", line(OrderItem, "order_id", match, qty="qty", rate="rate")),
    ]
    if code == "item_code":  # service orders have no asset lines
        tabs += [
            ("PW_ORDER", line(ProjectWorkOrderItem, "order_id", match, qty="qty", rate="rate")),
        ]
    tabs += [("GRN", line(GrnItem, "grn_id", match, qty="current_received_qty"))]
    if code == "item_code":
        tabs += [
            ("SRN", line(SrnItem, "srn_id", match, qty="current_received_qty",
                         via=(ProjectWorkOrderItem, "pw_order_item_id"))),
        ]
    tabs += [
        ("GIN", line(GinItem, "gin_id", match, qty="issue_qty", via=(OrderItem, "order_item_id"))),
        ("DC", line(DcItem, "dc_id", match, qty="issue_qty")),
    ]
    return tabs


def _journal_amount(ln):
    return func.coalesce(ln.debit_amount, 0) + func.coalesce(ln.credit_amount, 0)


SUBJECTS = {
    "vendor": dict(
        model=Vendor,
        search=("ledger_name", "ledger_code", "gstin", "pan", "primary_contact_number"),
        name="ledger_name",
        ledger=True,
        tabs=[
            ("ORDER", cols("vendor_id")),
            ("PW_ORDER", cols("vendor_id")),
            ("GRN", cols("vendor_id")),
            ("SRN", cols("vendor_id")),
            ("GIN", cols("vendor_id")),
            ("DC", cols("from_vendor_id")),
            ("BRR", cols("vendor_id")),
            ("BRB", cols("vendor_id")),
            ("PURCHASE_BILL", cols("vendor_id")),
            ("DEBIT_NOTE", cols("vendor_id")),
            ("CREDIT_NOTE", cols("vendor_id")),
            ("BILL_PAYMENT", cols("vendor_id")),
            ("PAYMENT_VOUCHER", cols("vendor_id")),
            ("JOURNAL", line(JournalEntryLine, "journal_id", ("vendor_id", "id"), amount=_journal_amount)),
            ("OG_SALE_ORDER", cols("debtor_id")),
        ],
    ),
    "item": dict(
        model=Item,
        search=("item_name", "item_code", "item_display_code", "hsn_sac"),
        name="item_name",
        tabs=_stock_tabs("item_code"),
    ),
    "asset": dict(
        model=Asset,
        search=("asset_name", "asset_code", "hsn_sac"),
        name="asset_name",
        tabs=_stock_tabs("asset_code"),
    ),
    "project": dict(
        model=Project,
        search=("project_name", "project_code", "client_name"),
        name="project_name",
        tabs=[(dt, PROJECT) for dt, m in DOC_TYPES.items() if not m.get("legacy")]
        + [(dt, PROJECT) for dt in EXTRA_DOCS],
    ),
    "bank": dict(
        model=BankCash,
        search=("bank_name", "bank_holder_name", "bank_code", "bank_account_number"),
        name="bank_name",
        line_label="On this account",
        tabs=[
            ("BILL_PAYMENT", cols("cash_ac_id", "bank_ac_id")),
            ("PAYMENT_VOUCHER", cols("cash_ac_id", "bank_ac_id")),
            ("SALE_RECEIPT", cols("cash_ac_id", "bank_ac_id")),
            ("SALE_BILL", cols("bank_ac_id")),
            ("CONTRA_ENTRY", line(ContraEntryLine, "contra_id", ("account_id", "id"),
                                  amount=lambda ln: func.coalesce(ln.debit_amount, 0) + func.coalesce(ln.credit_amount, 0))),
            ("PETTY_CASH_VOUCHER", cols("bank_cash_id")),
        ],
    ),
    "cc": dict(
        model=CCCode,
        search=("cc_name", "cc_code"),
        name="cc_name",
        line_label="On this cost centre",
        tabs=[
            ("PURCHASE_BILL", line(PurchaseBillItem, "purchase_bill_id", ("cc_code", "cc_code"),
                                   amount=lambda ln: ln.basic_amount)),
            ("SALE_BILL", line(SaleBillItem, "sale_bill_id", ("cc_code", "cc_code"), amount=lambda ln: ln.basic_amount)),
            ("DEBIT_NOTE", line(DebitNoteItem, "debit_note_id", ("cc_code", "cc_code"),
                                amount=lambda ln: ln.total_amount)),
            ("CREDIT_NOTE", line(CreditNoteItem, "credit_note_id", ("cc_code", "cc_code"),
                                 amount=lambda ln: ln.total_amount)),
            ("JOURNAL", line(JournalEntryLine, "journal_id", ("cc_id", "id"), amount=_journal_amount)),
        ],
    ),
    "employee": dict(
        model=Employee,
        search=("full_name", "emp_code", "personal_mobile", "work_email", "department"),
        name="full_name",
        claim="employee_management",  # JWT page permission needed to find / open (as /hr/employee)
        tabs=[],
        tables=[
            ("PAYROLL", "Payroll", "payroll"),
            ("PERFORMANCE", "Performance Reviews", "performance_appraisal"),
            ("DISCIPLINE", "Discipline Cases", "performance_appraisal"),
            ("ONBOARDING", "Onboarding Tasks", "onboarding"),
        ],
    ),
}


def _meta(doc_type):
    return DOC_TYPES.get(doc_type) or EXTRA_DOCS.get(doc_type)


def _pages(doc_type):
    return tuple(_meta(doc_type)["pages"]) + EXTRA_PAGES.get(doc_type, ())


def _limit(raw, default, maximum):
    try:
        return max(1, min(int(raw), maximum))
    except (TypeError, ValueError):
        return default


def _has_claim(page):
    """Page permission from the login token — the same check the HR endpoints make."""
    return bool((get_jwt().get("permissions") or {}).get(f"{page}.VIEW"))


def _subject_denied(kind):
    """True when this record type needs a page permission the user does not hold."""
    claim = SUBJECTS[kind].get("claim")
    return bool(claim) and not _has_claim(claim)


# ─────────────────────────────────────────────────────────────────
# quick search
# ─────────────────────────────────────────────────────────────────

def quick_search(user_id, kind, q, limit=None):
    """GET /search/quick?type=<record type>&q=…  — at most `limit` matches, best first."""
    try:
        kind = (kind or "").lower()
        q = (q or "").strip()
        if kind not in SUBJECTS:
            return res("Unknown search type", [], 400)
        if _subject_denied(kind):
            return res("Access denied", [], 403)
        if len(q) < MIN_QUERY:
            return res(f"Type at least {MIN_QUERY} characters", [], 200)
        limit = _limit(limit, QUICK_LIMIT, QUICK_LIMIT_MAX)
        pattern = _like(q)
        starts = pattern[1:]  # "abc%" — names that start with the text come first

        spec = SUBJECTS[kind]
        model = spec["model"]
        name_col = getattr(model, spec["name"])
        query = model.query.filter(or_(*[getattr(model, c).ilike(pattern, escape="\\") for c in spec["search"]]))
        if kind == "project":
            access = TraceAccess(user_id)
            if not access.is_global:
                query = query.filter(Project.project_code.in_(access.project_codes() or ["__none__"]))
        rows = query.order_by(name_col.ilike(starts, escape="\\").desc(), name_col).limit(limit).all()
        return res("Search results", [_brief(kind, r) for r in rows], 200)
    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


def _mask(value):
    value = str(value or "")
    return ("•" * max(len(value) - 4, 0) + value[-4:]) if value else None


def _brief(kind, r):
    """One search result: what the search box shows."""
    if kind == "vendor":
        code, name = r.ledger_code, r.ledger_name
        hint = [("Debtor" if r.is_debtor else "Vendor / Ledger"), r.gstin]
    elif kind == "item":
        code, name = r.item_display_code or r.item_code, r.item_name
        unit = Unit.query.get(r.unit_id) if r.unit_id else None
        hint = ["Item", unit.short_name if unit else None]
    elif kind == "asset":
        code, name, hint = r.asset_code, r.asset_name, ["Asset"]
    elif kind == "project":
        code, name, hint = r.project_code, r.project_name, ["Project", r.client_name]
    elif kind == "bank":
        code, name = r.bank_code, r.bank_name or r.bank_holder_name
        hint = [(r.type or "Bank / Cash").title(), _mask(r.bank_account_number)]
    elif kind == "cc":
        code, name, hint = r.cc_code, r.cc_name, ["Cost Centre"]
    else:  # employee
        code, name, hint = r.emp_code, r.full_name, ["Employee", r.designation, r.department]
    return {
        "kind": kind,
        "id": r.id,
        "code": code,
        "name": name,
        "hint": " · ".join(str(h) for h in hint if h),
        "status": getattr(r, "status", None) or getattr(r, "employee_status", None),
    }


# ─────────────────────────────────────────────────────────────────
# which documents belong to a record
# ─────────────────────────────────────────────────────────────────

def _tab_spec(kind, doc_type):
    return dict(SUBJECTS[kind]["tabs"]).get(doc_type)


def _line_query(subject, spec, header_only=False):
    """Lines that carry the record: (header id, qty, rate, amount) — or only the header id."""
    ln = spec["line"]
    header = getattr(ln, spec["header"])
    match_col, subject_attr = spec["match"]
    columns = [header] if header_only else [
        header.label("header_id"),
        (getattr(ln, spec["qty"]) if spec["qty"] else null()).label("qty"),
        (getattr(ln, spec["rate"]) if spec["rate"] else null()).label("rate"),
        (spec["amount"](ln) if spec["amount"] else null()).label("amount"),
    ]
    stmt = select(*columns)
    value = getattr(subject, subject_attr)
    if spec["via"]:
        parent, fk = spec["via"]
        stmt = stmt.select_from(ln).join(parent, parent.id == getattr(ln, fk))
        return stmt.where(getattr(parent, match_col) == value)
    return stmt.where(getattr(ln, match_col) == value)


def _doc_conditions(subject, doc_type, spec, allowed):
    """SQL conditions: 'this document is about the record' + the allowed projects."""
    meta = _meta(doc_type)
    model = meta["model"]
    project_cols = [getattr(model, c) for c in meta["projects"]]

    if spec.get("project"):
        conditions = [or_(*[c == subject.project_code for c in project_cols])]
    elif spec.get("cols"):
        conditions = [or_(*[getattr(model, c) == subject.id for c in spec["cols"]])]
    else:
        conditions = [model.id.in_(_line_query(subject, spec, header_only=True))]

    row_filter = meta.get("row_filter")
    if row_filter is not None:
        conditions.append(row_filter(model))
    if allowed is not None:
        conditions.append(or_(*[c.in_(allowed or ["__none__"]) for c in project_cols]))
    return conditions


def _allowed_projects(access, doc_type, kind, subject):
    """None = every project; [] = no access; else the project codes."""
    allowed = access.projects_for_pages(_pages(doc_type))
    if kind == "project" and allowed is not None:
        # a project's own view: only if the user holds this page in that project
        allowed = [subject.project_code] if subject.project_code in allowed else []
    return allowed


def _load_subject(user_id, kind, subject_id):
    """The record, or None when it does not exist or is not visible to this user."""
    subject = SUBJECTS[kind]["model"].query.get(subject_id)
    if subject is not None and kind == "project":
        access = TraceAccess(user_id)
        if not access.is_global and subject.project_code not in access.project_codes():
            return None
    return subject


# ─────────────────────────────────────────────────────────────────
# overview: profile + tabs
# ─────────────────────────────────────────────────────────────────

def get_overview(user_id, kind, subject_id):
    """GET /search/360/<kind>/<id> — profile and the tabs (with counts) this user may open."""
    try:
        if kind not in SUBJECTS:
            return res("Unknown record type", [], 404)
        if _subject_denied(kind):
            return res("Access denied", [], 403)
        subject = _load_subject(user_id, kind, subject_id)
        if not subject:
            return res("Record not found", [], 404)
        access = TraceAccess(user_id)
        spec = SUBJECTS[kind]

        tabs = []
        if spec.get("ledger"):
            ledger_projects = access.projects_for_pages(LEDGER_PAGES)
            if ledger_projects is None or ledger_projects:
                tabs.append({"key": "LEDGER", "label": "Ledger", "kind": "ledger"})

        for doc_type, tab_spec in spec["tabs"]:
            allowed = _allowed_projects(access, doc_type, kind, subject)
            if allowed is not None and not allowed:
                continue  # no access to this document type → no tab
            meta = _meta(doc_type)
            count = db.session.execute(
                select(func.count()).select_from(meta["model"])
                .where(*_doc_conditions(subject, doc_type, tab_spec, allowed))
            ).scalar() or 0
            tabs.append({"key": doc_type, "label": meta["label"], "kind": "documents", "count": count})

        for key, label, claim in spec.get("tables", []):
            if _has_claim(claim):
                tabs.append({"key": key, "label": label, "kind": "table",
                             "count": _table_count(key, subject)})

        return res("Overview", {"kind": kind, "profile": _profile(kind, subject, access), "tabs": tabs}, 200)
    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


def _profile(kind, r, access):
    """{name, code, status, typeLabel, fields: [[label, value], …]} — empty values are dropped."""
    if kind == "vendor":
        name, code, status, type_label = r.ledger_name, r.ledger_code, r.status, "Vendor / Ledger"
        fields = [
            ("Type", "Debtor (customer)" if r.is_debtor else "Creditor (vendor)"),
            ("GSTIN", r.gstin), ("PAN", r.pan), ("State", r.state_name),
            ("Contact", " · ".join(x for x in (r.primary_contact_person, r.primary_contact_number) if x)),
            ("Email", r.email), ("Address", r.registered_address),
        ]
        if access.is_global:  # bank details only for the roles that maintain the vendor master
            fields += [
                ("Bank", ", ".join(x for x in (r.bank_name, r.branch_name) if x)),
                ("Account No", r.bank_account_number), ("IFSC", r.ifsc_code),
            ]
    elif kind in ("item", "asset"):
        is_item = kind == "item"
        unit = Unit.query.get(r.unit_id) if r.unit_id else None
        name = r.item_name if is_item else r.asset_name
        code = (r.item_display_code or r.item_code) if is_item else r.asset_code
        status, type_label = r.status, "Item" if is_item else "Asset"
        fields = [
            ("Unit", unit.short_name if unit else None), ("Category", r.category_code), ("HSN / SAC", r.hsn_sac),
            ("GST %", f"{_num(r.gst_percentage)}%" if r.gst_percentage is not None else None),
            ("Description", r.item_description if is_item else r.asset_description),
        ]
        if not is_item:
            fields += [
                ("Purchase value", _num(r.purchase_value) if r.purchase_value is not None else None),
                ("Depreciation %", _num(r.depreciation_percentage) if r.depreciation_percentage is not None else None),
                ("Useful life (years)", r.useful_life_years),
            ]
    elif kind == "project":
        name, code, status, type_label = r.project_name, r.project_code, r.status, "Project"
        fields = [
            ("Client", r.client_name), ("Project manager", r.project_manager),
            ("Commercial manager", r.commercial_manager), ("GSTIN", r.gstn), ("State", r.state),
            ("Start date", _date(r.original_start_date or r.schedule_date)),
            ("Completion date", _date(r.extended_complete_date or r.schedule_completion_date)),
            ("Order value", r.revised_order_value or r.initial_order_value),
            ("Address", r.registered_address),
        ]
    elif kind == "bank":
        name, code, status = r.bank_name or r.bank_holder_name, r.bank_code, r.status
        type_label = (r.type or "Bank / Cash").title()
        fields = [
            ("Holder", r.bank_holder_name), ("Branch", r.branch_name), ("IFSC", r.ifsc_code),
            # full account number only for the roles that maintain the master
            ("Account No", r.bank_account_number if access.is_global else _mask(r.bank_account_number)),
        ]
    elif kind == "cc":
        name, code, status, type_label = r.cc_name, r.cc_code, r.status, "Cost Centre"
        fields = [("Category", r.category_code), ("Linked to P&L", "Yes" if r.pl_linked else "No")]
    else:  # employee — no salary, bank or identity numbers here
        name, code, status, type_label = r.full_name, r.emp_code, r.employee_status, "Employee"
        manager = User.query.get(r.reporting_manager_id) if r.reporting_manager_id else None
        fields = [
            ("Designation", r.designation), ("Department", r.department),
            ("Joined", _date(r.date_of_joining)), ("Employment", r.employment_type),
            ("Grade", r.grade_band), ("Location", r.work_location),
            ("Reports to", manager.username if manager else None),
            ("Work email", r.work_email), ("Mobile", r.personal_mobile),
        ]
    return {
        "id": r.id, "name": name, "code": code, "status": status, "typeLabel": type_label,
        "fields": [[label, value] for label, value in fields if value not in (None, "")],
    }


# ─────────────────────────────────────────────────────────────────
# documents of one tab
# ─────────────────────────────────────────────────────────────────

def get_documents(user_id, kind, subject_id, doc_type, limit=None):
    """GET /search/360/<kind>/<id>/docs?type=ORDER — newest first."""
    try:
        if kind not in SUBJECTS:
            return res("Unknown record type", [], 404)
        if _subject_denied(kind):
            return res("Access denied", [], 403)
        doc_type = (doc_type or "").upper()
        tab_spec = _tab_spec(kind, doc_type)
        if not tab_spec:
            return res("Unknown document type", [], 400)
        subject = _load_subject(user_id, kind, subject_id)
        if not subject:
            return res("Record not found", [], 404)

        access = TraceAccess(user_id)
        allowed = _allowed_projects(access, doc_type, kind, subject)
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
            .where(*_doc_conditions(subject, doc_type, tab_spec, allowed))
            .order_by(model.id.desc())
            .limit(limit)
        )
        docs = db.session.execute(stmt).all()

        # line tabs: quantity / rate / amount of this record on each document
        is_line = bool(tab_spec.get("line"))
        per_doc = {}
        if is_line and docs:
            line_sq = _line_query(subject, tab_spec).subquery()
            for header_id, qty, rate, amount in db.session.execute(
                select(line_sq.c.header_id, func.sum(line_sq.c.qty), func.max(line_sq.c.rate),
                       func.sum(line_sq.c.amount))
                .where(line_sq.c.header_id.in_([d.doc_id for d in docs]))
                .group_by(line_sq.c.header_id)
            ).all():
                per_doc[header_id] = (qty, rate, amount)

        extra = []
        if is_line:
            extra = [k for k in ("qty", "rate") if tab_spec[k]] + (["lineAmount"] if tab_spec["amount"] else [])

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
            if is_line:
                qty, rate, amount = per_doc.get(d.doc_id, (None, None, None))
                row["qty"] = _num(qty, 4) if qty is not None else None
                row["rate"] = _num(rate) if rate is not None else None
                row["lineAmount"] = _num(amount) if amount is not None else None
            out.append(row)

        return res("Documents", {
            "rows": out, "limit": limit, "hasMore": len(out) == limit,
            "extra": extra, "lineLabel": SUBJECTS[kind].get("line_label", "On this record"),
        }, 200)
    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ─────────────────────────────────────────────────────────────────
# table tabs (employee)
# ─────────────────────────────────────────────────────────────────
# Each returns (columns, rows). Column type tells the page how to show a value:
# text | date | amount | number | status.

def _col(header, accessor, kind="text"):
    return {"header": header, "accessor": accessor, "type": kind}


MONTHS = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def _payroll(emp):
    rows = (
        db.session.query(PayrollEntry, PayrollRun)
        .join(PayrollRun, PayrollRun.id == PayrollEntry.payroll_run_id)
        .filter(PayrollEntry.employee_id == emp.id)
        .order_by(PayrollRun.year.desc(), PayrollRun.month.desc()).limit(DOC_LIMIT).all()
    )
    columns = [
        _col("Month", "period"), _col("Days worked", "days", "number"), _col("Gross", "gross", "amount"),
        _col("Deductions", "deductions", "amount"), _col("Net pay", "net", "amount"), _col("Status", "status", "status"),
    ]
    return columns, [{
        "period": f"{MONTHS[run.month] if 1 <= (run.month or 0) <= 12 else run.month} {run.year}",
        "days": _num(e.days_worked), "gross": _num(e.gross), "deductions": _num(e.total_deductions),
        "net": _num(e.net_pay), "status": e.status or run.status,
    } for e, run in rows]


def _performance(emp):
    rows = (PerformanceReview.query.filter_by(employee_id=emp.id)
            .order_by(PerformanceReview.id.desc()).limit(DOC_LIMIT).all())
    columns = [
        _col("Cycle", "cycle"), _col("Rating", "rating", "number"), _col("Goals done %", "goals", "number"),
        _col("Next review", "next", "date"), _col("PIP", "pip"), _col("Status", "status", "status"),
    ]
    return columns, [{
        "cycle": r.cycle_name, "rating": _num(r.rating), "goals": _num(r.goals_completion_pct),
        "next": _date(r.next_review_date), "pip": "Yes" if r.pip_active else "No", "status": r.status,
    } for r in rows]


def _discipline(emp):
    rows = (DisciplineCase.query.filter_by(employee_id=emp.id)
            .order_by(DisciplineCase.id.desc()).limit(DOC_LIMIT).all())
    columns = [
        _col("Case", "code"), _col("Date", "date", "date"), _col("Incident", "incident"),
        _col("Severity", "severity"), _col("Action taken", "action"), _col("Status", "status", "status"),
    ]
    return columns, [{
        "code": r.case_code, "date": _date(r.incident_date), "incident": r.incident_type,
        "severity": r.severity, "action": r.action_taken, "status": r.status,
    } for r in rows]


def _onboarding(emp):
    rows = (OnboardingTask.query.filter_by(employee_id=emp.id)
            .order_by(OnboardingTask.id).limit(DOC_LIMIT).all())
    columns = [
        _col("Task", "task"), _col("Category", "category"), _col("Due", "due", "date"),
        _col("Completed", "completed", "date"), _col("Status", "status", "status"),
    ]
    return columns, [{
        "task": r.task_name, "category": r.category, "due": _date(r.due_date),
        "completed": _date(r.completed_at), "status": r.status,
    } for r in rows]


TABLES = {
    "PAYROLL": (_payroll, PayrollEntry),
    "PERFORMANCE": (_performance, PerformanceReview),
    "DISCIPLINE": (_discipline, DisciplineCase),
    "ONBOARDING": (_onboarding, OnboardingTask),
}


def _table_count(key, subject):
    model = TABLES[key][1]
    return db.session.execute(
        select(func.count()).select_from(model).where(model.employee_id == subject.id)
    ).scalar() or 0


def get_table(user_id, kind, subject_id, key):
    """GET /search/360/<kind>/<id>/table?key=PAYROLL"""
    try:
        if kind not in SUBJECTS:
            return res("Unknown record type", [], 404)
        if _subject_denied(kind):
            return res("Access denied", [], 403)
        key = (key or "").upper()
        table = next((t for t in SUBJECTS[kind].get("tables", []) if t[0] == key), None)
        if not table:
            return res("Unknown tab", [], 400)
        if not _has_claim(table[2]):
            return res("Access denied", [], 403)
        subject = _load_subject(user_id, kind, subject_id)
        if not subject:
            return res("Record not found", [], 404)
        columns, rows = TABLES[key][0](subject)
        return res("Rows", {"columns": columns, "rows": rows}, 200)
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
