# app/modules/traceability/flow_service.py
"""
Document Flow engine for the Traceability Workbench (read-only).

Given any start document (or a single indent item) it finds the connected
documents in two modes:

  LINEAGE  – SAP-style document flow of the start document only: its
             predecessors (upward) and its successors (downward), followed
             line-by-line, so an order that also serves other indents does
             not drag those other indents' receipts/bills into the picture.
  FULL     – the whole connected procurement flow around the start document
             (every line of every document reached), capped at MAX_DOCS.

Traversal is breadth-first per relationship: each step is ONE batched
IN (...) query per relationship, never one query per document or line.
Membership is decided first; edges and quantities are then derived from
the collected lines, so nothing is counted twice.

Item-level links are exact (FKs between line tables). Links from billing
to accounts are header level (BRR → Purchase Bill → Payment) and are
labelled as such. No item-level money is allocated here.
"""

from collections import defaultdict
from decimal import Decimal

from sqlalchemy import func

from app.extensions import db
from app.response import res
from app.models.item import Item
from app.models.asset import Asset
from app.models.vendor import Vendor
from app.models.project import Project
from app.models.indent_item import IndentItem
from app.models.orderMaster import OrderMaster, OrderItem
from app.models.ORDER_projectwork import ProjectWorkOrderMaster
from app.models.grnMaster import GrnMaster, GrnItem
from app.models.srnMaster import SrnMaster, SrnItem
from app.models.ginMaster import GinMaster, GinItem
from app.models.dcMaster import DcMaster, DcItem
from app.models.brrMaster import BrrMaster
from app.models.brbMaster import BrbMaster, BrbItem
from app.models.purchaseBill import PurchaseBillMaster
from app.models.billPaymentReceipt import BillPaymentReceiptMaster
from app.models.ogSaleOrder import OgSaleOrderMaster
from app.models.saleBill import SaleBillMaster, SaleBillSource
from app.models.saleReceipt import SaleReceiptMaster
from app.models.saleReceiptBilling import SaleReceiptBillingMaster
from app.models.billingMaster import BillingMaster

from app.modules.traceability.access import TraceAccess
from app.modules.traceability.registry import (
    DOC_TYPES, LINE_TYPES, LINE_LINKS, HEADER_LINKS, STAGES, STAGE_INDEX, doc_projects,
)

MAX_DOCS = 400
ZERO = Decimal("0")
APPROVED = "Approved"
REJECTED = "Rejected"

# line types whose FK points at an item / asset master
_ITEM_LINES = ("INDENT_LINE", "ORD_LINE", "GRN_LINE", "DC_LINE", "PW_LINE")


def _d(v):
    return Decimal(str(v)) if v is not None else ZERO


def _q(v):
    return float(round(_d(v), 4))


def _a(v):
    return float(round(_d(v), 2))


def _date(v):
    return v.strftime("%Y-%m-%d") if v else None


def _live(s):
    return s != REJECTED


def _key(dt, i):
    return f"{dt}:{i}"


# ═════════════════════════════════════════════════════════════════
# graph collection
# ═════════════════════════════════════════════════════════════════

class FlowGraph:

    def __init__(self):
        self.lines = {lt: {} for lt in LINE_TYPES}        # line type -> {id: row}
        self.docs = {dt: {} for dt in DOC_TYPES}           # doc type  -> {id: row}
        self.complete = set()                              # (dt, id) with all lines included
        self.truncated = False

    # ── membership helpers ──────────────────────────────────────
    def doc_count(self):
        return sum(len(v) for v in self.docs.values())

    def add_docs(self, dt, ids):
        """Load headers not yet in the graph. Returns the ids actually added."""
        ids = {i for i in ids if i and i not in self.docs[dt]}
        if not ids:
            return set()
        room = MAX_DOCS - self.doc_count()
        if room <= 0:
            self.truncated = True
            return set()
        if len(ids) > room:
            self.truncated = True
        model = DOC_TYPES[dt]["model"]
        q = model.query.filter(model.id.in_(ids))
        # Doc types that share a table (Claim vs Certified bill) filter by row_filter (e.g. mode).
        row_filter = DOC_TYPES[dt].get("row_filter")
        if row_filter is not None:
            q = q.filter(row_filter(model))
        rows = q.order_by(model.id).limit(room).all()
        for r in rows:
            self.docs[dt][r.id] = r
        return {r.id for r in rows}

    def add_line_rows(self, lt, rows, new_lines, new_docs):
        """Register line rows; their header documents are loaded too."""
        meta = LINE_TYPES[lt]
        fresh = [r for r in rows if r.id not in self.lines[lt]]
        if not fresh:
            return
        header_ids = {getattr(r, meta["header"]) for r in fresh}
        missing = {h for h in header_ids if h not in self.docs[meta["doc"]]}
        added = self.add_docs(meta["doc"], missing)
        new_docs[meta["doc"]] |= added
        for r in fresh:
            if getattr(r, meta["header"]) in self.docs[meta["doc"]]:
                self.lines[lt][r.id] = r
                new_lines[lt].add(r.id)

    def load_lines_by(self, lt, column, values):
        if not values:
            return []
        model = LINE_TYPES[lt]["model"]
        return model.query.filter(getattr(model, column).in_(list(values))).all()

    def complete_docs(self, dt, ids, new_lines, new_docs):
        """Pull every line of these documents into the graph."""
        lt = DOC_TYPES[dt]["line"]
        ids = {i for i in ids if (dt, i) not in self.complete}
        for i in ids:
            self.complete.add((dt, i))
        if lt and ids:
            rows = self.load_lines_by(lt, LINE_TYPES[lt]["header"], ids)
            self.add_line_rows(lt, rows, new_lines, new_docs)

    # ── downward ────────────────────────────────────────────────
    def expand_down(self, lines, docs, complete_mode=False):
        while any(lines.values()) or any(docs.values()):
            nl, nd = defaultdict(set), defaultdict(set)

            if complete_mode:
                for dt, ids in docs.items():
                    self.complete_docs(dt, ids, nl, nd)

            for child_lt, fk, parent_lt, _ in LINE_LINKS:
                pids = lines.get(parent_lt) or set()
                if pids:
                    rows = self.load_lines_by(child_lt, fk, pids)
                    self.add_line_rows(child_lt, rows, nl, nd)

            # order → bill receive register (order level)
            ords = docs.get("ORDER") or set()
            if ords:
                nd["BRR"] |= self.add_docs("BRR", {
                    r.id for r in BrrMaster.query.filter(BrrMaster.order_id.in_(ords)).all()})
            pws = docs.get("PW_ORDER") or set()
            if pws:
                nd["BRR"] |= self.add_docs("BRR", {
                    r.id for r in BrrMaster.query.filter(BrrMaster.pw_order_id.in_(pws)).all()})

            # billing document → its BRR (context) → purchase bills
            brbs = docs.get("BRB") or set()
            if brbs:
                nd["BRR"] |= self.add_docs("BRR", {self.docs["BRB"][i].brr_id for i in brbs})

            brrs = (docs.get("BRR") or set()) | nd["BRR"]
            if brrs:
                nd["PURCHASE_BILL"] |= self.add_docs("PURCHASE_BILL", {
                    r.id for r in PurchaseBillMaster.query.filter(PurchaseBillMaster.brr_id.in_(brrs)).all()})
                full_brrs = {b for b in brrs if complete_mode or ("BRR", b) in self.complete}
                if full_brrs:
                    nd["BRB"] |= self.add_docs("BRB", {
                        r.id for r in BrbMaster.query.filter(BrbMaster.brr_id.in_(full_brrs)).all()})

            pbs = (docs.get("PURCHASE_BILL") or set()) | nd["PURCHASE_BILL"]
            if pbs:
                nd["BILL_PAYMENT"] |= self.add_docs("BILL_PAYMENT", {
                    r.id for r in BillPaymentReceiptMaster.query.filter(
                        BillPaymentReceiptMaster.purchase_bill_id.in_(pbs)).all()})

            # ── Sales lifecycle (downward) ──────────────────────────────
            # OG Sale Order → Claim Bill → Certified Bill → Sales Invoice (M:N via sources)
            #              → Sale Receipt Billing → Sale Receipt
            og_sos = (docs.get("OG_SALE_ORDER") or set()) | nd["OG_SALE_ORDER"]
            if og_sos:
                nd["CLAIM_BILL"] |= self.add_docs("CLAIM_BILL", {
                    r.id for r in BillingMaster.query.filter(
                        BillingMaster.mode == "sale_claim_bill",
                        BillingMaster.og_sale_order_id.in_(og_sos)).all()})
                nd["SALE_RECEIPT_BILLING"] |= self.add_docs("SALE_RECEIPT_BILLING", {
                    r.id for r in SaleReceiptBillingMaster.query.filter(
                        SaleReceiptBillingMaster.og_sale_order_id.in_(og_sos)).all()})
                # Fallback: invoices with no sale_bill_sources still attach to the order directly
                nd["SALE_BILL"] |= self.add_docs("SALE_BILL", {
                    r.id for r in SaleBillMaster.query.filter(
                        SaleBillMaster.sale_order_id.in_(og_sos)).all()})

            claims = (docs.get("CLAIM_BILL") or set()) | nd["CLAIM_BILL"]
            if claims:
                nd["CERTIFIED_BILL"] |= self.add_docs("CERTIFIED_BILL", {
                    r.id for r in BillingMaster.query.filter(
                        BillingMaster.mode == "sale_certified_bill",
                        BillingMaster.claim_bill_id.in_(claims)).all()})

            certs = (docs.get("CERTIFIED_BILL") or set()) | nd["CERTIFIED_BILL"]
            if certs:
                # Certified Bill → Sales Invoice (many-to-many via sale_bill_sources)
                nd["SALE_BILL"] |= self.add_docs("SALE_BILL", {
                    s.sale_bill_id for s in SaleBillSource.query.filter(
                        SaleBillSource.certified_bill_id.in_(certs)).all() if s.sale_bill_id})
                # Certified Bill → Sale Receipt Billing (allocation)
                nd["SALE_RECEIPT_BILLING"] |= self.add_docs("SALE_RECEIPT_BILLING", {
                    r.id for r in SaleReceiptBillingMaster.query.filter(
                        SaleReceiptBillingMaster.certified_bill_id.in_(certs)).all()})

            srbs = (docs.get("SALE_RECEIPT_BILLING") or set()) | nd["SALE_RECEIPT_BILLING"]
            if srbs:
                nd["SALE_RECEIPT"] |= self.add_docs("SALE_RECEIPT", {
                    self.docs["SALE_RECEIPT_BILLING"][i].receipt_id
                    for i in srbs
                    if i in self.docs["SALE_RECEIPT_BILLING"]
                    and self.docs["SALE_RECEIPT_BILLING"][i].receipt_id})

            lines, docs = nl, nd

    # ── upward ──────────────────────────────────────────────────
    def expand_up(self, lines, docs, expand_order_lines=False):
        while any(lines.values()) or any(docs.values()):
            nl, nd = defaultdict(set), defaultdict(set)

            for child_lt, fk, parent_lt, _ in LINE_LINKS:
                cids = lines.get(child_lt) or set()
                if not cids:
                    continue
                pids = {getattr(self.lines[child_lt][c], fk) for c in cids}
                pids = {p for p in pids if p and p not in self.lines[parent_lt]}
                if pids:
                    rows = self.load_lines_by(parent_lt, "id", pids)
                    self.add_line_rows(parent_lt, rows, nl, nd)

            pays = docs.get("BILL_PAYMENT") or set()
            if pays:
                nd["PURCHASE_BILL"] |= self.add_docs(
                    "PURCHASE_BILL", {self.docs["BILL_PAYMENT"][i].purchase_bill_id for i in pays})

            pbs = (docs.get("PURCHASE_BILL") or set()) | nd["PURCHASE_BILL"]
            if pbs:
                brr_ids = {self.docs["PURCHASE_BILL"][i].brr_id for i in pbs} - {None}
                nd["BRR"] |= self.add_docs("BRR", brr_ids)
                # a purchase bill is prepared from the BRR's approved BRB billing
                if brr_ids:
                    brb_ids = self.add_docs("BRB", {r.id for r in BrbMaster.query.filter(
                        BrbMaster.brr_id.in_(brr_ids), BrbMaster.workflow_status == APPROVED).all()})
                    nd["BRB"] |= brb_ids
                    self.complete_docs("BRB", brb_ids, nl, nd)

            brbs = docs.get("BRB") or set()
            if brbs:
                nd["BRR"] |= self.add_docs("BRR", {self.docs["BRB"][i].brr_id for i in brbs})

            brrs = (docs.get("BRR") or set()) | nd["BRR"]
            if brrs:
                rows = [self.docs["BRR"][b] for b in brrs if b in self.docs["BRR"]]
                for dt, attr in (("ORDER", "order_id"), ("PW_ORDER", "pw_order_id")):
                    added = self.add_docs(dt, {getattr(r, attr) for r in rows} - {None})
                    nd[dt] |= added
                    if expand_order_lines and added:
                        self.complete_docs(dt, added, nl, nd)

            # ── Sales lifecycle (upward): child → … → OG Sale Order ──────
            sale_rcpts = docs.get("SALE_RECEIPT") or set()
            if sale_rcpts:
                nd["SALE_RECEIPT_BILLING"] |= self.add_docs("SALE_RECEIPT_BILLING", {
                    r.id for r in SaleReceiptBillingMaster.query.filter(
                        SaleReceiptBillingMaster.receipt_id.in_(sale_rcpts)).all()})

            # Sales Invoice → Certified Bill (many-to-many via sale_bill_sources)
            sale_bills = docs.get("SALE_BILL") or set()
            if sale_bills:
                nd["CERTIFIED_BILL"] |= self.add_docs("CERTIFIED_BILL", {
                    s.certified_bill_id for s in SaleBillSource.query.filter(
                        SaleBillSource.sale_bill_id.in_(sale_bills)).all() if s.certified_bill_id})

            # Sale Receipt Billing → Certified Bill + its Sale Receipt
            srb_up = (docs.get("SALE_RECEIPT_BILLING") or set()) | nd["SALE_RECEIPT_BILLING"]
            if srb_up:
                nd["CERTIFIED_BILL"] |= self.add_docs("CERTIFIED_BILL", {
                    self.docs["SALE_RECEIPT_BILLING"][i].certified_bill_id
                    for i in srb_up
                    if i in self.docs["SALE_RECEIPT_BILLING"]
                    and self.docs["SALE_RECEIPT_BILLING"][i].certified_bill_id})
                nd["SALE_RECEIPT"] |= self.add_docs("SALE_RECEIPT", {
                    self.docs["SALE_RECEIPT_BILLING"][i].receipt_id
                    for i in srb_up
                    if i in self.docs["SALE_RECEIPT_BILLING"]
                    and self.docs["SALE_RECEIPT_BILLING"][i].receipt_id})

            # Certified Bill → Claim Bill (claim_bill_id)
            certs = (docs.get("CERTIFIED_BILL") or set()) | nd["CERTIFIED_BILL"]
            if certs:
                nd["CLAIM_BILL"] |= self.add_docs("CLAIM_BILL", {
                    self.docs["CERTIFIED_BILL"][i].claim_bill_id
                    for i in certs
                    if i in self.docs["CERTIFIED_BILL"]
                    and self.docs["CERTIFIED_BILL"][i].claim_bill_id})

            # Claim / Certified / Invoice / SRB → OG Sale Order
            og_so_ids = set()
            for i in sale_bills:
                r = self.docs["SALE_BILL"].get(i)
                if r and getattr(r, "sale_order_id", None):
                    og_so_ids.add(r.sale_order_id)
            for dt_ in ("CLAIM_BILL", "CERTIFIED_BILL"):
                for i in (docs.get(dt_) or set()) | nd[dt_]:
                    r = self.docs[dt_].get(i)
                    if r and getattr(r, "og_sale_order_id", None):
                        og_so_ids.add(r.og_sale_order_id)
            for i in srb_up:
                r = self.docs["SALE_RECEIPT_BILLING"].get(i)
                if r and getattr(r, "og_sale_order_id", None):
                    og_so_ids.add(r.og_sale_order_id)
            if og_so_ids:
                nd["OG_SALE_ORDER"] |= self.add_docs("OG_SALE_ORDER", og_so_ids)

            lines, docs = nl, nd


def _seed(graph, start_type, start_id):
    """Put the start document in the graph. Returns (lines, docs) frontier or None."""
    lines, docs = defaultdict(set), defaultdict(set)
    if start_type == "INDENT_ITEM":
        row = IndentItem.query.get(start_id)
        if not row:
            return None
        graph.add_line_rows("INDENT_LINE", [row], lines, docs)
        return lines, docs, ("INDENT", row.indent_id)

    if start_type not in DOC_TYPES:
        return None
    if not graph.add_docs(start_type, {start_id}):
        return None
    docs[start_type].add(start_id)
    graph.complete_docs(start_type, {start_id}, lines, docs)
    return lines, docs, (start_type, start_id)


def collect_flow(start_type, start_id, mode="LINEAGE"):
    graph = FlowGraph()
    seeded = _seed(graph, start_type, start_id)
    if not seeded:
        return None, None
    lines, docs, start_doc = seeded

    copy = lambda d: defaultdict(set, {k: set(v) for k, v in d.items()})
    expand_orders = start_type == "BRR"

    if mode == "FULL":
        # Each round: walk up from the frontier, then walk down (completing every
        # document) from the frontier plus the ancestors just found. Whatever the
        # downward walk discovers becomes the next frontier, because it may have
        # other ancestors (e.g. another indent feeding the same order).
        snap = lambda store: {k: set(v) for k, v in store.items()}
        diff = lambda now, old: defaultdict(set, {k: v - old.get(k, set()) for k, v in now.items()
                                                  if v - old.get(k, set())})
        union = lambda a, b: defaultdict(set, {k: a.get(k, set()) | b.get(k, set()) for k in set(a) | set(b)})
        fl, fd = copy(lines), copy(docs)
        for _ in range(25):
            l0, d0 = snap(graph.lines), snap(graph.docs)
            graph.expand_up(copy(fl), copy(fd), expand_order_lines=True)
            l1, d1 = snap(graph.lines), snap(graph.docs)
            graph.expand_down(union(fl, diff(l1, l0)), union(fd, diff(d1, d0)), complete_mode=True)
            fl, fd = diff(snap(graph.lines), l1), diff(snap(graph.docs), d1)
            if graph.truncated or not (any(fl.values()) or any(fd.values())):
                break
    else:
        graph.expand_up(copy(lines), copy(docs), expand_order_lines=expand_orders)
        graph.expand_down(copy(lines), copy(docs))

    return graph, start_doc


# ═════════════════════════════════════════════════════════════════
# presentation
# ═════════════════════════════════════════════════════════════════

def _item_lookup(graph):
    codes, assets = set(), set()
    for lt in _ITEM_LINES:
        for r in graph.lines[lt].values():
            if getattr(r, "is_asset", False) and getattr(r, "asset_code", None):
                assets.add(r.asset_code)
            elif getattr(r, "item_code", None):
                codes.add(r.item_code)
    items = {}
    if codes:
        for it in Item.query.filter(Item.item_code.in_(codes)).all():
            items[("I", it.item_code)] = (it.item_name, it.unit.short_name if it.unit else None,
                                          it.item_display_code or it.item_code)
    if assets:
        for a in Asset.query.filter(Asset.asset_code.in_(assets)).all():
            items[("A", a.asset_code)] = (a.asset_name, a.unit.short_name if a.unit else None, a.asset_code)
    return items


def _line_item_key(graph, lt, row):
    """(kind, code) of the item a line moves, walking up exact links if the line has no own code."""
    if lt in _ITEM_LINES:
        if getattr(row, "is_asset", False):
            return ("A", row.asset_code)
        return ("I", row.item_code)
    if lt == "GIN_LINE" and row.order_item_id in graph.lines["ORD_LINE"]:
        return _line_item_key(graph, "ORD_LINE", graph.lines["ORD_LINE"][row.order_item_id])
    if lt == "SRN_LINE" and row.pw_order_item_id in graph.lines["PW_LINE"]:
        return _line_item_key(graph, "PW_LINE", graph.lines["PW_LINE"][row.pw_order_item_id])
    for fk, plt in (("grn_item_id", "GRN_LINE"), ("srn_item_id", "SRN_LINE")):
        pid = getattr(row, fk, None)
        if pid and pid in graph.lines[plt]:
            return _line_item_key(graph, plt, graph.lines[plt][pid])
    return None


def _build_edges(graph):
    edges = {}

    def edge(pdt, pid, cdt, cid, kind, meaning):
        k = (pdt, pid, cdt, cid)
        if k not in edges:
            edges[k] = {"from": _key(pdt, pid), "to": _key(cdt, cid), "kind": kind,
                        "meaning": meaning, "qty": ZERO, "lineCount": 0, "items": set()}
        return edges[k]

    for child_lt, fk, parent_lt, meaning in LINE_LINKS:
        cmeta, pmeta = LINE_TYPES[child_lt], LINE_TYPES[parent_lt]
        for row in graph.lines[child_lt].values():
            pid = getattr(row, fk, None)
            if not pid or pid not in graph.lines[parent_lt]:
                continue
            prow = graph.lines[parent_lt][pid]
            e = edge(pmeta["doc"], getattr(prow, pmeta["header"]), cmeta["doc"],
                     getattr(row, cmeta["header"]), "ITEM", meaning)
            e["qty"] += _d(getattr(row, cmeta["qty"]))
            e["lineCount"] += 1
            e["items"].add(_line_item_key(graph, child_lt, row))

    for child_dt, fk, parent_dt, kind, meaning in HEADER_LINKS:
        for cid, row in graph.docs[child_dt].items():
            pid = getattr(row, fk, None)
            if pid and pid in graph.docs[parent_dt]:
                edge(parent_dt, pid, child_dt, cid, kind, meaning)

    # BRB → Purchase Bill: the bill is prepared from the BRR's APPROVED billing (CC-level)
    pb_by_brr = defaultdict(list)
    for pid, pb in graph.docs["PURCHASE_BILL"].items():
        pb_by_brr[pb.brr_id].append(pid)
    for bid, brb in graph.docs["BRB"].items():
        if brb.workflow_status == APPROVED:
            for pid in pb_by_brr.get(brb.brr_id, []):
                edge("BRB", bid, "PURCHASE_BILL", pid, "VIA_BRR", "Booked (CC-level)")

    # Certified Bill → Sales Invoice (many-to-many via sale_bill_sources).
    # One edge per (certified, invoice) pair; de-duplicated by the edge() key.
    sb_ids = set(graph.docs["SALE_BILL"])
    cert_ids = set(graph.docs["CERTIFIED_BILL"])
    invoices_with_cert = set()
    if sb_ids and cert_ids:
        for s in SaleBillSource.query.filter(
                SaleBillSource.sale_bill_id.in_(sb_ids),
                SaleBillSource.certified_bill_id.in_(cert_ids)).all():
            if s.sale_bill_id in graph.docs["SALE_BILL"] and s.certified_bill_id in graph.docs["CERTIFIED_BILL"]:
                edge("CERTIFIED_BILL", s.certified_bill_id, "SALE_BILL", s.sale_bill_id, "ASSOC", "Invoiced")
                invoices_with_cert.add(s.sale_bill_id)

    # Fallback direct → OG Sale Order edges, drawn ONLY when the certified-bill chain is
    # absent in-graph (keeps the lifecycle path clean when claim/certified bills are present).
    for sid, sb in graph.docs["SALE_BILL"].items():
        og = getattr(sb, "sale_order_id", None)
        if sid not in invoices_with_cert and og and og in graph.docs["OG_SALE_ORDER"]:
            edge("OG_SALE_ORDER", og, "SALE_BILL", sid, "HEADER", "Invoiced")
    for rid, srb in graph.docs["SALE_RECEIPT_BILLING"].items():
        cert = getattr(srb, "certified_bill_id", None)
        og = getattr(srb, "og_sale_order_id", None)
        has_cert_parent = cert and cert in graph.docs["CERTIFIED_BILL"]
        if not has_cert_parent and og and og in graph.docs["OG_SALE_ORDER"]:
            edge("OG_SALE_ORDER", og, "SALE_RECEIPT_BILLING", rid, "HEADER", "Receipt")

    out = []
    for e in edges.values():
        single = len(e["items"]) == 1 and None not in e["items"]
        out.append({
            "from": e["from"], "to": e["to"], "kind": e["kind"], "meaning": e["meaning"],
            "lineCount": e["lineCount"],
            # quantities of different items are never added together
            "qty": _q(e["qty"]) if e["kind"] == "ITEM" and single else None,
            "itemKey": "{}:{}".format(*next(iter(e["items"]))) if e["kind"] == "ITEM" and single else None,
        })
    return out


def _vendors(graph):
    ids = set()
    for dt, rows in graph.docs.items():
        for r in rows.values():
            v = (getattr(r, "vendor_id", None)
                 or getattr(r, "from_vendor_id", None)
                 or getattr(r, "debtor_id", None))  # OgSaleOrderMaster.debtor_id is the client
            if v:
                ids.add(v)
    if not ids:
        return {}
    return {v.id: v.ledger_name for v in Vendor.query.filter(Vendor.id.in_(ids)).all()}


def _party(dt, row, vendors):
    v = (getattr(row, "vendor_id", None)
         or getattr(row, "from_vendor_id", None)
         or getattr(row, "debtor_id", None))
    if v:
        return vendors.get(v)
    if dt == "INDENT":
        return row.indent_placed_by
    if dt == "DC":
        return f"{row.from_project_code or '—'} → {row.to_project_code or '—'}"
    if dt == "ORDER" and row.transfer_project_site:
        return f"Transfer to {row.transfer_project_site}"
    return None


def _nodes(graph, access, start_doc, items):
    vendors = _vendors(graph)
    nodes, visible = [], set()
    by_header = {}
    for lt, rows in graph.lines.items():
        grouped = defaultdict(list)
        for r in rows.values():
            grouped[getattr(r, LINE_TYPES[lt]["header"])].append(r)
        by_header[lt] = grouped
    for dt, rows in graph.docs.items():
        meta = DOC_TYPES[dt]
        lt = meta["line"]
        for did, row in rows.items():
            k = _key(dt, did)
            projects = [p for p in doc_projects(dt, row) if p]
            base = {
                "key": k, "docType": dt, "typeLabel": meta["label"], "stage": meta["stage"],
                "flow": meta["flow"], "legacy": bool(meta.get("legacy")),
                "isStart": (dt, did) == start_doc,
            }
            if not access.can_view(meta["pages"], projects):
                nodes.append({**base, "restricted": True, "docId": None, "docNo": None,
                              "projectCode": None, "status": None, "date": None})
                continue
            visible.add(k)

            node = {
                **base, "restricted": False, "docId": did,
                "docNo": getattr(row, meta["no"]),
                "date": _date(getattr(row, meta["date"])),
                "status": getattr(row, "workflow_status", None),
                "projectCode": projects[0] if projects else None,
                "projectCodes": projects,
                "party": _party(dt, row, vendors),
                "amount": _a(getattr(row, meta["amount"])) if meta["amount"] and getattr(row, meta["amount"]) is not None else None,
                "complete": (dt, did) in graph.complete,
                "billingType": getattr(row, "billing_type", None) if dt == "BRB" else (getattr(row, "order_type", None) if dt == "BRR" else None),
            }
            if lt:
                in_scope = by_header[lt].get(did, [])
                keys = {_line_item_key(graph, lt, r) for r in in_scope}
                node["lineCount"] = len(in_scope)
                node["itemCount"] = len(keys - {None})
                if len(keys) == 1 and None not in keys:
                    ik = next(iter(keys))
                    name, unit, code = items.get(ik, (None, None, ik[1]))
                    node["qty"] = _q(sum((_d(getattr(r, LINE_TYPES[lt]["qty"])) for r in in_scope), ZERO))
                    node["unit"] = unit
                    node["itemName"] = name
                    node["itemCode"] = code
            nodes.append(node)

    nodes.sort(key=lambda n: (STAGE_INDEX[n["stage"]], n.get("date") or "9999", n["key"]))
    return nodes, visible


def _reconciliation(graph, items, visible):
    """Exact quantity reconciliation of every indent / order line in the flow,
    computed over ALL their transactions (not just those in view)."""
    ind = {i: r for i, r in graph.lines["INDENT_LINE"].items() if _key("INDENT", r.indent_id) in visible}
    ords = {i: r for i, r in graph.lines["ORD_LINE"].items() if _key("ORDER", r.order_id) in visible}
    pws = {i: r for i, r in graph.lines["PW_LINE"].items() if _key("PW_ORDER", r.order_id) in visible}

    def item_info(kind, code):
        name, unit, disp = items.get((kind, code), (None, None, code))
        return {"itemCode": disp, "itemName": name, "unit": unit, "isAsset": kind == "A"}

    # ── indent lines: ordered on non-rejected orders ──
    ordered_by_indent = {}
    if ind:
        rows = (db.session.query(OrderItem.indent_item_id, func.sum(OrderItem.qty))
                .join(OrderMaster, OrderMaster.id == OrderItem.order_id)
                .filter(OrderItem.indent_item_id.in_(list(ind)), OrderMaster.workflow_status != REJECTED)
                .group_by(OrderItem.indent_item_id).all())
        ordered_by_indent = {r[0]: _d(r[1]) for r in rows}

    indent_rows = []
    for i, r in ind.items():
        hdr = graph.docs["INDENT"][r.indent_id]
        ordered = ordered_by_indent.get(i, ZERO)
        indent_rows.append({
            "indentItemId": i, "indentId": r.indent_id, "indentNo": hdr.indent_no,
            "indentStatus": hdr.workflow_status,
            **item_info("A" if r.is_asset else "I", r.asset_code if r.is_asset else r.item_code),
            "indentQty": _q(r.qty), "orderedQty": _q(ordered),
            "pendingOrderQty": _q(max(_d(r.qty) - ordered, ZERO)),
            "overOrderedQty": _q(max(ordered - _d(r.qty), ZERO)),
        })

    # ── material order lines ──
    order_rows = []
    if ords:
        oi_ids = list(ords)
        grn_lines = (db.session.query(GrnItem.id, GrnItem.order_item_id, GrnItem.current_received_qty,
                                      GrnMaster.workflow_status)
                     .join(GrnMaster, GrnMaster.id == GrnItem.grn_id)
                     .filter(GrnItem.order_item_id.in_(oi_ids)).all())
        grn_ids = [g.id for g in grn_lines]
        billed = {}
        if grn_ids:
            billed = {r[0]: _d(r[1]) for r in (
                db.session.query(BrbItem.grn_item_id, func.sum(BrbItem.billing_qty))
                .join(BrbMaster, BrbMaster.id == BrbItem.brb_id)
                .filter(BrbItem.grn_item_id.in_(grn_ids), BrbMaster.workflow_status != REJECTED)
                .group_by(BrbItem.grn_item_id).all())}
        issued = {r[0]: _d(r[1]) for r in (
            db.session.query(GinItem.order_item_id, func.sum(GinItem.issue_qty))
            .join(GinMaster, GinMaster.id == GinItem.gin_id)
            .filter(GinItem.order_item_id.in_(oi_ids), GinMaster.workflow_status != REJECTED)
            .group_by(GinItem.order_item_id).all())}
        dispatched = {r[0]: _d(r[1]) for r in (
            db.session.query(DcItem.order_item_id, func.sum(DcItem.issue_qty))
            .join(DcMaster, DcMaster.id == DcItem.dc_id)
            .filter(DcItem.order_item_id.in_(oi_ids), DcMaster.workflow_status != REJECTED)
            .group_by(DcItem.order_item_id).all())}

        agg = defaultdict(lambda: defaultdict(lambda: ZERO))
        for g in grn_lines:
            a = agg[g.order_item_id]
            q = _d(g.current_received_qty)
            b = billed.get(g.id, ZERO)
            if _live(g.workflow_status):
                a["received"] += q
                a["billed"] += b
            if g.workflow_status == APPROVED:
                a["accepted"] += q
                a["pendingBilling"] += max(q - b, ZERO)

        for i, r in ords.items():
            hdr = graph.docs["ORDER"][r.order_id]
            a = agg[i]
            qty = _d(r.qty)
            live = _live(hdr.workflow_status)
            order_rows.append({
                "orderItemId": i, "orderId": r.order_id, "orderNo": hdr.order_no,
                "orderStatus": hdr.workflow_status, "indentItemId": r.indent_item_id,
                **item_info("A" if r.is_asset else "I", r.asset_code if r.is_asset else r.item_code),
                "orderedQty": _q(qty), "rate": _a(r.rate),
                "receivedQty": _q(a["received"]), "acceptedQty": _q(a["accepted"]),
                "issuedQty": _q(issued.get(i, ZERO)), "dispatchedQty": _q(dispatched.get(i, ZERO)),
                "stockQty": _q(a["accepted"] - issued.get(i, ZERO)),
                "billedQty": _q(a["billed"]), "pendingBillingQty": _q(a["pendingBilling"]),
                "pendingReceiptQty": _q(max(qty - a["received"], ZERO)) if live else 0.0,
            })

    # ── service order lines ──
    service_rows = []
    if pws:
        pw_ids = list(pws)
        srn_lines = (db.session.query(SrnItem.id, SrnItem.pw_order_item_id, SrnItem.current_received_qty,
                                      SrnMaster.workflow_status)
                     .join(SrnMaster, SrnMaster.id == SrnItem.srn_id)
                     .filter(SrnItem.pw_order_item_id.in_(pw_ids)).all())
        srn_ids = [s.id for s in srn_lines]
        billed = {}
        if srn_ids:
            billed = {r[0]: _d(r[1]) for r in (
                db.session.query(BrbItem.srn_item_id, func.sum(BrbItem.billing_qty))
                .join(BrbMaster, BrbMaster.id == BrbItem.brb_id)
                .filter(BrbItem.srn_item_id.in_(srn_ids), BrbMaster.workflow_status != REJECTED)
                .group_by(BrbItem.srn_item_id).all())}
        agg = defaultdict(lambda: defaultdict(lambda: ZERO))
        for s in srn_lines:
            a = agg[s.pw_order_item_id]
            q = _d(s.current_received_qty)
            b = billed.get(s.id, ZERO)
            if _live(s.workflow_status):
                a["received"] += q
                a["billed"] += b
            if s.workflow_status == APPROVED:
                a["accepted"] += q
                a["pendingBilling"] += max(q - b, ZERO)
        for i, r in pws.items():
            hdr = graph.docs["PW_ORDER"][r.order_id]
            a = agg[i]
            qty = _d(r.qty)
            service_rows.append({
                "pwOrderItemId": i, "orderId": r.order_id, "orderNo": hdr.order_no,
                "orderStatus": hdr.workflow_status, **item_info("I", r.item_code),
                "orderedQty": _q(qty), "rate": _a(r.rate),
                "receivedQty": _q(a["received"]), "acceptedQty": _q(a["accepted"]),
                "billedQty": _q(a["billed"]), "pendingBillingQty": _q(a["pendingBilling"]),
                "pendingReceiptQty": _q(max(qty - a["received"], ZERO)) if _live(hdr.workflow_status) else 0.0,
            })

    return {"indentLines": indent_rows, "orderLines": order_rows, "serviceLines": service_rows}


def _financials(graph, visible):
    """Exact document-level money: bills received, reconciled, booked and paid."""
    brr_ids = [i for i in graph.docs["BRR"] if _key("BRR", i) in visible]
    pb_ids = [i for i in graph.docs["PURCHASE_BILL"] if _key("PURCHASE_BILL", i) in visible]

    brb_tot = defaultdict(lambda: defaultdict(lambda: ZERO))
    pb_tot = defaultdict(lambda: ZERO)
    pb_count = defaultdict(int)
    if brr_ids:
        for brr_id, status, total in (db.session.query(BrbMaster.brr_id, BrbMaster.workflow_status,
                                                       func.sum(BrbMaster.total_amount))
                                      .filter(BrbMaster.brr_id.in_(brr_ids))
                                      .group_by(BrbMaster.brr_id, BrbMaster.workflow_status).all()):
            if _live(status):
                brb_tot[brr_id]["billed"] += _d(total)
            if status == APPROVED:
                brb_tot[brr_id]["approved"] += _d(total)
        for brr_id, status, total in (db.session.query(PurchaseBillMaster.brr_id, PurchaseBillMaster.workflow_status,
                                                       func.sum(PurchaseBillMaster.total_invoice_amount),
                                                       ).filter(PurchaseBillMaster.brr_id.in_(brr_ids))
                                      .group_by(PurchaseBillMaster.brr_id, PurchaseBillMaster.workflow_status).all()):
            if _live(status):
                pb_tot[brr_id] += _d(total)

    paid = defaultdict(lambda: defaultdict(lambda: ZERO))
    if pb_ids:
        for pb_id, status, total in (db.session.query(BillPaymentReceiptMaster.purchase_bill_id,
                                                      BillPaymentReceiptMaster.workflow_status,
                                                      func.sum(BillPaymentReceiptMaster.total_invoice_amount))
                                     .filter(BillPaymentReceiptMaster.purchase_bill_id.in_(pb_ids))
                                     .group_by(BillPaymentReceiptMaster.purchase_bill_id,
                                               BillPaymentReceiptMaster.workflow_status).all()):
            if status == APPROVED:
                paid[pb_id]["paid"] += _d(total)
            elif _live(status):
                paid[pb_id]["inProcess"] += _d(total)

    for pb in graph.docs["PURCHASE_BILL"].values():
        if _live(pb.workflow_status):
            pb_count[pb.brr_id] += 1

    brr_rows = []
    for i in brr_ids:
        b = graph.docs["BRR"][i]
        brr_rows.append({
            "brrId": i, "brrNo": b.brr_no, "brrDate": _date(b.brr_date), "status": b.workflow_status,
            "billingType": b.order_type, "partyBillNo": b.party_bill_no,
            "billReceived": _a(b.total_amount),
            "reconciled": _a(brb_tot[i]["billed"]), "reconciledApproved": _a(brb_tot[i]["approved"]),
            "unreconciled": _a(_d(b.total_amount) - brb_tot[i]["billed"]),
            "booked": _a(pb_tot[i]), "purchaseBillCount": pb_count[i],
        })

    pb_rows = []
    for i in pb_ids:
        p = graph.docs["PURCHASE_BILL"][i]
        total = _d(p.total_invoice_amount)
        pd = paid[i]["paid"]
        pb_rows.append({
            "purchaseBillId": i, "purchaseBillNo": p.purchase_bill_no, "date": _date(p.processing_date),
            "status": p.workflow_status, "brrId": p.brr_id, "vendorBillNo": p.vendor_bill_no,
            "basic": _a(p.basic_amount), "gst": _a(p.gst_amount), "discount": _a(p.discount),
            "roundOff": _a(p.round_off), "total": _a(total),
            "paid": _a(pd), "inProcess": _a(paid[i]["inProcess"]),
            "outstanding": _a(max(total - pd, ZERO)) if p.workflow_status == APPROVED else None,
        })

    live_pbs = [r for r in pb_rows if _live(r["status"])]
    totals = {
        "billReceived": _a(sum((_d(r["billReceived"]) for r in brr_rows if _live(r["status"])), ZERO)),
        "reconciled": _a(sum((_d(r["reconciled"]) for r in brr_rows), ZERO)),
        "booked": _a(sum((_d(r["total"]) for r in live_pbs), ZERO)),
        "paid": _a(sum((_d(r["paid"]) for r in pb_rows), ZERO)),
        "inProcess": _a(sum((_d(r["inProcess"]) for r in pb_rows), ZERO)),
        "outstanding": _a(sum((_d(r["outstanding"]) for r in pb_rows if r["outstanding"] is not None), ZERO)),
    }
    return {"brrs": brr_rows, "purchaseBills": pb_rows, "totals": totals}


def _sales_financials(graph, visible):
    """OG Sale Order level: amount invoiced vs received (Sales lifecycle)."""
    og_so_ids = [i for i in graph.docs["OG_SALE_ORDER"] if _key("OG_SALE_ORDER", i) in visible]
    if not og_so_ids:
        return {"ogSaleOrders": [], "totals": {}}

    invoiced = defaultdict(lambda: defaultdict(lambda: ZERO))
    for og_id, status, total in (
        db.session.query(SaleBillMaster.sale_order_id, SaleBillMaster.workflow_status,
                         func.sum(SaleBillMaster.total_invoice_amount))
        .filter(SaleBillMaster.sale_order_id.in_(og_so_ids))
        .group_by(SaleBillMaster.sale_order_id, SaleBillMaster.workflow_status).all()
    ):
        if _live(status):
            invoiced[og_id]["invoiced"] += _d(total)
        if status == APPROVED:
            invoiced[og_id]["invoicedApproved"] += _d(total)

    received = defaultdict(lambda: defaultdict(lambda: ZERO))
    for og_id, status, total in (
        db.session.query(SaleReceiptBillingMaster.og_sale_order_id,
                         SaleReceiptBillingMaster.workflow_status,
                         func.sum(SaleReceiptBillingMaster.total_invoice_amount))
        .filter(SaleReceiptBillingMaster.og_sale_order_id.in_(og_so_ids))
        .group_by(SaleReceiptBillingMaster.og_sale_order_id,
                  SaleReceiptBillingMaster.workflow_status).all()
    ):
        if _live(status):
            received[og_id]["received"] += _d(total)
        if status == APPROVED:
            received[og_id]["receivedApproved"] += _d(total)
        elif _live(status):
            received[og_id]["inProcess"] += _d(total)

    rows = []
    for i in og_so_ids:
        o = graph.docs["OG_SALE_ORDER"][i]
        total = _d(o.total_amount)
        inv = invoiced[i]
        rec = received[i]
        inv_approved = inv["invoicedApproved"]
        rec_approved = rec["receivedApproved"]
        rows.append({
            "ogSaleOrderId": i,
            "erpDocNo": o.erp_no,
            "date": _date(o.og_sale_order_date),
            "status": o.workflow_status,
            "orderAmount": _a(total),
            "invoiced": _a(inv["invoiced"]),
            "invoicedApproved": _a(inv_approved),
            "received": _a(rec["received"]),
            "receivedApproved": _a(rec_approved),
            "inProcess": _a(rec["inProcess"]),
            "outstanding": _a(max(inv_approved - rec_approved, ZERO))
                if inv_approved > 0 else None,
        })

    live = [r for r in rows if _live(r["status"])]
    totals = {
        "orderAmount": _a(sum((_d(r["orderAmount"]) for r in live), ZERO)),
        "invoiced": _a(sum((_d(r["invoiced"]) for r in live), ZERO)),
        "received": _a(sum((_d(r["received"]) for r in live), ZERO)),
        "outstanding": _a(sum((_d(r["outstanding"]) for r in rows
                               if r["outstanding"] is not None), ZERO)),
    }
    return {"ogSaleOrders": rows, "totals": totals}


def _fq(v):
    return f"{_d(v):,.3f}"


def _fa(v):
    return f"₹ {_d(v):,.2f}"


def _exceptions(graph, recon, fin, sales_fin, nodes, visible):
    out = []

    def add(code, severity, msg, key=None):
        out.append({"code": code, "severity": severity, "message": msg, "docKey": key})

    for r in recon["indentLines"]:
        k = _key("INDENT", r["indentId"])
        if r["overOrderedQty"] > 0:
            add("OVER_ORDERED", "error", f"{r['indentNo']} · {r['itemName'] or r['itemCode']}: ordered "
                f"{_fq(r['orderedQty'])} exceeds indent {_fq(r['indentQty'])} {r['unit'] or ''}.", k)
        elif r["indentStatus"] == APPROVED and r["pendingOrderQty"] > 0:
            add("NOT_ORDERED", "warning", f"{r['indentNo']} · {r['itemName'] or r['itemCode']}: "
                f"{_fq(r['pendingOrderQty'])} {r['unit'] or ''} not yet on any order.", k)

    for rows, dt in ((recon["orderLines"], "ORDER"), (recon["serviceLines"], "PW_ORDER")):
        for r in rows:
            k = _key(dt, r["orderId"])
            label = f"{r['orderNo']} · {r['itemName'] or r['itemCode']}"
            u = r["unit"] or ""
            if r["orderStatus"] == APPROVED and r["pendingReceiptQty"] > 0:
                add("PENDING_RECEIPT", "warning",
                    f"{label}: {_fq(r['pendingReceiptQty'])} {u} still to be received "
                    f"({_fq(r['receivedQty'])} of {_fq(r['orderedQty'])}).", k)
            if _live(r["orderStatus"]) and r["receivedQty"] > r["orderedQty"]:
                add("OVER_RECEIVED", "error", f"{label}: received {_fq(r['receivedQty'])} exceeds ordered "
                    f"{_fq(r['orderedQty'])}.", k)
            if r["billedQty"] > r["receivedQty"]:
                add("OVER_BILLED", "error", f"{label}: billed {_fq(r['billedQty'])} exceeds received "
                    f"{_fq(r['receivedQty'])}.", k)
            if r["pendingBillingQty"] > 0:
                add("PENDING_BILLING", "warning", f"{label}: {_fq(r['pendingBillingQty'])} {u} accepted but not "
                    f"yet billed.", k)
            if r.get("issuedQty", 0) > r["acceptedQty"]:
                add("OVER_ISSUED", "error", f"{label}: issued {_fq(r['issuedQty'])} exceeds accepted "
                    f"{_fq(r['acceptedQty'])}.", k)
            if r.get("stockQty", 0) > 0:
                add("IN_STOCK", "info", f"{label}: {_fq(r['stockQty'])} {u} accepted but not yet issued.", k)

    for b in fin["brrs"]:
        k = _key("BRR", b["brrId"])
        if not _live(b["status"]):
            continue
        if b["reconciled"] == 0:
            add("BILL_NOT_RECONCILED", "warning", f"{b['brrNo']}: bill of {_fa(b['billReceived'])} received but "
                "not yet reconciled with receipts (no BRB).", k)
        elif abs(b["unreconciled"]) > 0.01:
            add("PARTLY_RECONCILED", "warning", f"{b['brrNo']}: {_fa(b['unreconciled'])} of the "
                f"{_fa(b['billReceived'])} bill is not covered by BRB billing.", k)
        if b["reconciledApproved"] > 0 and b["purchaseBillCount"] == 0:
            add("NOT_BOOKED", "warning", f"{b['brrNo']}: approved billing of {_fa(b['reconciledApproved'])} has "
                "no Purchase Bill yet.", k)
        if b["purchaseBillCount"] > 1:
            add("MULTIPLE_PURCHASE_BILLS", "warning", f"{b['brrNo']} has {b['purchaseBillCount']} active Purchase "
                "Bills. Check it is not booked twice.", k)
        if b["purchaseBillCount"] and b["reconciledApproved"] and abs(b["booked"] - b["reconciledApproved"]) > 1:
            add("BOOKED_VS_BILLED", "info", f"{b['brrNo']}: booked {_fa(b['booked'])} vs approved BRB billing "
                f"{_fa(b['reconciledApproved'])} (difference may be discount / round-off / edits).", k)

    for p in fin["purchaseBills"]:
        k = _key("PURCHASE_BILL", p["purchaseBillId"])
        if p["outstanding"] and p["outstanding"] > 0.01:
            add("PAYMENT_OUTSTANDING", "warning", f"{p['purchaseBillNo']}: {_fa(p['outstanding'])} outstanding "
                f"of {_fa(p['total'])}.", k)
        if p["paid"] > p["total"] + 0.01:
            add("OVER_PAID", "error", f"{p['purchaseBillNo']}: paid {_fa(p['paid'])} exceeds bill {_fa(p['total'])}.", k)

    for o in sales_fin["ogSaleOrders"]:
        k = _key("OG_SALE_ORDER", o["ogSaleOrderId"])
        if not _live(o["status"]):
            continue
        if o["invoicedApproved"] > 0 and o["outstanding"] and o["outstanding"] > 0.01:
            add("SALE_RECEIPT_OUTSTANDING", "warning",
                f"{o['erpDocNo']}: {_fa(o['outstanding'])} outstanding on approved invoices.", k)
        if o["invoiced"] == 0 and o["status"] == APPROVED:
            add("SALE_NOT_INVOICED", "info",
                f"{o['erpDocNo']}: approved OG Sale Order has no Sales Invoice yet.", k)

    for n in nodes:
        if n["restricted"]:
            continue
        if n["status"] == REJECTED:
            add("REJECTED", "info", f"{n['typeLabel']} {n['docNo']} was rejected; excluded from quantities "
                "and amounts.", n["key"])
        if n["legacy"]:
            add("LEGACY", "info", f"{n['typeLabel']} {n['docNo']} is legacy billing; shown for reference only.",
                n["key"])

    restricted = sum(1 for n in nodes if n["restricted"])
    if restricted:
        add("RESTRICTED", "info", f"{restricted} linked document(s) are in projects or modules you do not have "
            "access to. They are shown without details.")
    if graph.truncated:
        add("TRUNCATED", "warning", f"This flow is larger than {MAX_DOCS} documents; only the first "
            f"{MAX_DOCS} are shown. Trace from a more specific document.")

    sev = {"error": 0, "warning": 1, "info": 2}
    out.sort(key=lambda e: sev[e["severity"]])
    return out


# ═════════════════════════════════════════════════════════════════
# entry point
# ═════════════════════════════════════════════════════════════════

def get_document_flow(user_id, start_type, start_id, mode="LINEAGE"):
    try:
        start_type = (start_type or "").upper()
        mode = "FULL" if (mode or "").upper() == "FULL" else "LINEAGE"
        if start_type not in DOC_TYPES and start_type != "INDENT_ITEM":
            return res("Unknown document type", [], 400)

        access = TraceAccess(user_id)
        graph, start_doc = collect_flow(start_type, start_id, mode)
        if graph is None:
            return res("Document not found", [], 404)

        sdt, sid = start_doc
        srow = graph.docs[sdt].get(sid)
        if not srow or not access.can_view(DOC_TYPES[sdt]["pages"], doc_projects(sdt, srow)):
            return res("Access denied", [], 403)

        items = _item_lookup(graph)
        nodes, visible = _nodes(graph, access, start_doc, items)
        edges = _build_edges(graph)
        # hide quantities on edges that touch a restricted document
        for e in edges:
            if e["from"] not in visible or e["to"] not in visible:
                e["qty"] = None
                e["itemKey"] = None
        recon = _reconciliation(graph, items, visible)
        fin = _financials(graph, visible)
        sales_fin = _sales_financials(graph, visible)
        exceptions = _exceptions(graph, recon, fin, sales_fin, nodes, visible)

        start_item = None
        if start_type == "INDENT_ITEM":
            r = graph.lines["INDENT_LINE"].get(start_id)
            if r:
                ik = ("A", r.asset_code) if r.is_asset else ("I", r.item_code)
                name, unit, code = items.get(ik, (None, None, ik[1]))
                start_item = {"indentItemId": start_id, "itemCode": code, "itemName": name, "unit": unit,
                              "qty": _q(r.qty)}

        return res("Document flow fetched", {
            "start": {"docType": sdt, "docId": sid, "key": _key(sdt, sid), "requestedType": start_type,
                      "requestedId": start_id, "item": start_item},
            "mode": mode,
            "stages": [{"key": k, "label": l} for k, l in STAGES],
            "nodes": nodes,
            "edges": edges,
            "reconciliation": recon,
            "financials": fin,
            "salesFinancials": sales_fin,
            "exceptions": exceptions,
            "truncated": graph.truncated,
            "limits": {"maxDocs": MAX_DOCS},
        }, 200)
    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)
