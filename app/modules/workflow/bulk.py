"""
Bulk workflow actions — Approve / Reback / Reject many records at once.

Every id is pushed through the module's EXISTING single-record route
(e.g. POST /finance/petty-cash/docket-voucher/approve/<id>) inside the same
process, with the caller's own token. So every check and side effect of the
single action still applies, unchanged: current-approver / level checks, gap
levels, locks, history rows, accounting posting, bank-statement reconcile on
final approval, route-level hooks, request logging.

Each id runs on its own: its route commits (or rolls back) by itself, and a
failure is rolled back before the next id starts, so one bad record never
undoes or leaks into the others.

Adding a module = one line in BULK_MODULES (its blueprint url_prefix).
"""

from flask import current_app, g, request

from app.extensions import db
from app.response import res

BULK_ACTIONS = ("approve", "reback", "reject")
MAX_BULK_IDS = 100          # per action call
MAX_ELIGIBLE_IDS = 500      # per eligibility check (read-only)

# key -> label + url prefix of the module's blueprint. The single-record
# routes are <prefix>/approve|reback|reject/<id> (POST, body {comments}) and
# <prefix>/my-approval-status/<id> (GET, data.isPendingForMe).
BULK_MODULES = {
    # ── Resources
    "indent":               {"label": "Indent",                     "prefix": "/resource/indent"},
    "order":                {"label": "Material / Service Order",   "prefix": "/resource/order"},
    "pw_order":             {"label": "Project Work Order",         "prefix": "/resource/pw-order"},
    "grn":                  {"label": "GRN",                        "prefix": "/resource/grn"},
    "gin":                  {"label": "GIN",                        "prefix": "/resource/gin"},
    "srn":                  {"label": "SRN",                        "prefix": "/resource/srn"},
    "dc":                   {"label": "Delivery Challan",           "prefix": "/resource/dc"},
    "bvs":                  {"label": "Vendor Billing (GRN)",       "prefix": "/resource/bvs"},
    "bss":                  {"label": "Vendor Billing (SRN)",       "prefix": "/resource/bss"},
    "log_book":             {"label": "Machinery Log Book",         "prefix": "/resource/machinery/log-book"},
    "log_entry":            {"label": "Machinery Log Entry",        "prefix": "/resource/machinery/log-entry"},
    "batching":             {"label": "Batching Plant",             "prefix": "/resource/batching"},
    "dlr":                  {"label": "Daily Labour Report",        "prefix": "/resource/dlr"},
    # ── Logistics
    "transit_request":      {"label": "Transit Request",            "prefix": "/logistics/transit-request"},
    "logistics_bill":       {"label": "Logistics Bill Register",    "prefix": "/logistics/bill-register"},
    # ── Sub-contractor billing
    "brr":                  {"label": "Bill Receive Register",      "prefix": "/billing/brr"},
    "brb":                  {"label": "E-Reconcile Bill",           "prefix": "/billing/brb"},
    "payment_request":      {"label": "Payment Request",            "prefix": "/billing/payment-request"},
    # ── Finance
    "sale_bill":            {"label": "Sale Bill",                  "prefix": "/finance/sale-bill"},
    "purchase_bill":        {"label": "Purchase Bill",              "prefix": "/finance/purchase-bill"},
    "sale_receipt_billing": {"label": "Receipt",                    "prefix": "/finance/sale-receipt-billing"},
    "debit_note":           {"label": "Debit Note",                 "prefix": "/finance/debit-note"},
    "credit_note":          {"label": "Credit Note",                "prefix": "/finance/credit-note"},
    "payment_voucher":      {"label": "Payment Voucher",            "prefix": "/finance/payment-voucher"},
    "bill_payment":         {"label": "Bill Payment",               "prefix": "/finance/bill-payment"},
    "contra_entry":         {"label": "Contra Entry",               "prefix": "/finance/contra-entry"},
    "journal_entry":        {"label": "Journal Entry",              "prefix": "/finance/journal-entry"},
    "journal_voucher":      {"label": "Journal Voucher",            "prefix": "/finance/journal-entry/journal-voucher"},
    "petty_cash_budget":    {"label": "Petty Cash Budget",          "prefix": "/finance/petty-cash/budget"},
    "petty_cash_docket":    {"label": "Expenses Docket",            "prefix": "/finance/petty-cash/docket-voucher"},
    # ── Project management
    "project_billing":      {"label": "Customer Billing",           "prefix": "/project-mgmt/billing"},
    "og_sale_order":        {"label": "Sale Order",                 "prefix": "/project-mgmt/og-sale-order"},
    "og_sale_order_amendment": {"label": "Sale Order Amendment",    "prefix": "/project-mgmt/og-sale-order/amendment"},
    "contract_budget":      {"label": "Contract Budget",            "prefix": "/project-mgmt/contract/budget"},
    "uncertain_allocation": {"label": "Uncertain Allocation",       "prefix": "/project-mgmt/uncertain-allocation"},
    "dpr":                  {"label": "Daily Progress Report",      "prefix": "/project-mgmt/dpr"},
    "drawing_register":     {"label": "Drawing Register",           "prefix": "/project-mgmt/register/drawing-register"},
    "concrete_registry":    {"label": "Concrete Register",          "prefix": "/project-mgmt/register/concrete-registry"},
    "hindrance_register":   {"label": "Hindrance Register",         "prefix": "/project-mgmt/register/hindrance-register"},
    "bbs_register":         {"label": "BBS Register",               "prefix": "/project-mgmt/register/bbs-register"},
}

# request-scoped values on `g` that the inner request's hooks overwrite
_G_KEYS = ("request_id", "request_started", "current_user")


# ==========================================
# INPUT
# ==========================================

def _clean_ids(raw, cap):
    """List of unique positive ints (order kept) or an error message."""
    if not isinstance(raw, list) or not raw:
        return None, "ids must be a non-empty list"
    ids, seen = [], set()
    for v in raw:
        if isinstance(v, int) and not isinstance(v, bool):
            i = v
        elif isinstance(v, str) and v.strip().isdigit():
            i = int(v.strip())
        else:
            return None, f"Invalid id: {v!r}"
        if i <= 0:
            return None, f"Invalid id: {v!r}"
        if i not in seen:
            seen.add(i)
            ids.append(i)
    if len(ids) > cap:
        return None, f"Too many records: {len(ids)} (max {cap} at a time)"
    return ids, None


# ==========================================
# IN-PROCESS DISPATCH
# Runs one existing route as if the same user had called it directly.
# ==========================================

def _dispatch(method, path, body=None):
    app = current_app._get_current_object()
    headers = {k: request.headers[k] for k in ("Authorization", "Cookie", "X-Request-Id") if k in request.headers}
    saved = {k: g.get(k) for k in _G_KEYS}
    try:
        with app.test_request_context(path, method=method, json=body, headers=headers):
            response = app.full_dispatch_request()
    finally:
        for k, v in saved.items():
            if v is None:
                g.pop(k, None)
            else:
                setattr(g, k, v)
    payload = response.get_json(silent=True) or {}
    return response.status_code, payload


def _discard_leftovers():
    """A failed action must not leave pending changes for the next id's commit."""
    try:
        db.session.rollback()
    except Exception:  # pragma: no cover — broken session; next request gets a new one
        db.session.remove()


# ==========================================
# BULK ACTION
# ==========================================

def run_bulk_action(data):
    data = data or {}
    module = data.get("module")
    action = str(data.get("action") or "").lower()
    remarks = (data.get("remarks") if data.get("remarks") is not None else data.get("comments")) or ""
    remarks = str(remarks).strip()

    entry = BULK_MODULES.get(module)
    if not entry:
        return res(f"Unknown module: {module}", [], 400)
    if action not in BULK_ACTIONS:
        return res("action must be approve, reback or reject", [], 400)
    if action in ("reback", "reject") and not remarks:
        return res(f"Remarks are required to {action}", [], 400)

    ids, err = _clean_ids(data.get("ids"), MAX_BULK_IDS)
    if err:
        return res(err, [], 400)

    results = []
    for record_id in ids:
        try:
            status, payload = _dispatch("POST", f"{entry['prefix']}/{action}/{record_id}",
                                        {"comments": remarks or None})
            ok = 200 <= status < 300
            message = payload.get("message") or ("Done" if ok else f"Failed (HTTP {status})")
        except Exception:  # pragma: no cover — full_dispatch_request handles route errors
            current_app.logger.exception("Bulk %s %s #%s crashed", action, module, record_id)
            ok, status, message = False, 500, "Something went wrong"
        if not ok:
            _discard_leftovers()
        results.append({"id": record_id, "ok": ok, "status": status, "message": message})

    done = sum(1 for r in results if r["ok"])
    failed = len(results) - done
    past = {"approve": "approved", "reback": "sent back", "reject": "rejected"}[action]
    msg = f"{done} {past}" + (f", {failed} failed" if failed else "")

    return res(msg, {
        "module":    module,
        "action":    action,
        "total":     len(results),
        "succeeded": done,
        "failed":    failed,
        "results":   results,
    }, 200)


# ==========================================
# ELIGIBILITY — which of these ids are waiting on me right now
# (the module's own my-approval-status rule, per id)
# ==========================================

def find_eligible(data):
    data = data or {}
    module = data.get("module")
    entry = BULK_MODULES.get(module)
    if not entry:
        return res(f"Unknown module: {module}", [], 400)

    ids, err = _clean_ids(data.get("ids"), MAX_ELIGIBLE_IDS)
    if err:
        return res(err, [], 400)

    eligible = []
    for record_id in ids:
        try:
            status, payload = _dispatch("GET", f"{entry['prefix']}/my-approval-status/{record_id}")
        except Exception:  # pragma: no cover
            current_app.logger.exception("Eligibility %s #%s crashed", module, record_id)
            status, payload = 500, {}
        if 200 <= status < 300 and isinstance(payload.get("data"), dict) \
                and payload["data"].get("isPendingForMe"):
            eligible.append(record_id)
        elif status >= 400:
            _discard_leftovers()

    return res("Eligible records", {"module": module, "eligibleIds": eligible}, 200)


def list_bulk_modules():
    return res("Bulk workflow modules", {
        "maxIds":  MAX_BULK_IDS,
        "actions": list(BULK_ACTIONS),
        "modules": [{"module": k, "label": v["label"]} for k, v in BULK_MODULES.items()],
    }, 200)
