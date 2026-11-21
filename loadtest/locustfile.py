"""
ERP load test + speed check — every GET list / report / dropdown API.

Only GET (read) APIs are called, so nothing is created, approved or deleted.
APIs that need an id in the URL (/<id>) are not included.

SETUP
    pip install locust requests
    export ERP_TOKEN="eyJ..."            # Bearer token of a TEST user (DevTools > Network > any API > Authorization)
    export ERP_HOST="https://132.154.156.82/api"   # optional, this is the default
    export ERP_PROJECT="SIRO"            # optional, project code sent as projectCode / project_code

1) SPEED CHECK — 1 user, each API called a few times, sorted slowest first:
    python loadtest/locustfile.py check
    python loadtest/locustfile.py check finance        # only paths containing "finance"
    -> also writes loadtest/speed_report.csv
    Status 400 = that API needs another parameter: add it in EXTRA_PARAMS below.

2) LOAD TEST — many users at the same time:
    locust -f loadtest/locustfile.py --host "$ERP_HOST"
    open http://localhost:8089 -> users 50, ramp up 5 -> Start. Then try 100, 200.
    Only one module:   ERP_ONLY=finance locust -f loadtest/locustfile.py --host "$ERP_HOST"
    Without browser:   locust -f loadtest/locustfile.py --host "$ERP_HOST" --headless -u 100 -r 5 -t 5m --csv loadtest/run100

Run at night or against a copy of the server, never in working hours on production.
"""
import csv
import os
import statistics
import sys
import time

import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)   # self-signed HTTPS cert

TOKEN   = os.environ.get("ERP_TOKEN", "")
HOST    = os.environ.get("ERP_HOST", "https://132.154.156.82/api").rstrip("/")
PROJECT = os.environ.get("ERP_PROJECT", "SIRO")
ONLY    = os.environ.get("ERP_ONLY", "")          # filter by substring of the path

# Sent with every request (APIs ignore parameters they don't use).
COMMON_PARAMS = {
    "projectCode": PROJECT,
    "project_code": PROJECT,
    "page": 1,
    "pageSize": 50,
    "per_page": 50,
    "limit": 50,
}

# Extra parameters for APIs that return 400 without them. Fill from the browser Network tab.
EXTRA_PARAMS = {
    "/finance/accounting/ledger":               {"from_date": "2026-04-01", "to_date": "2026-11-30"},
    "/finance/accounting/trial-balance":        {"from_date": "2026-04-01", "to_date": "2026-11-30"},
    "/finance/accounting/profit-loss":          {"from_date": "2026-04-01", "to_date": "2026-11-30"},
    "/finance/accounting/balance-sheet":        {"from_date": "2026-04-01", "to_date": "2026-11-30"},
    "/finance/accounting/day-book":             {"from_date": "2026-11-01", "to_date": "2026-11-30"},
    "/finance/accounting/voucher-register":     {"from_date": "2026-11-01", "to_date": "2026-11-30"},
    "/search/quick":                            {"q": "cement"},
    "/traceability/workbench/search":           {"q": "PO"},
    # "/finance/bank-statement/available-for-docket": {"bankCashId": 1},
    # "/finance/accounting/ledger": {"account_type": "...", "account_id": 1, ...},
}

# (path, weight). Weight = how often a user opens it compared with the others.
#   5 = main list pages opened all day, 3 = common lists, 2 = dropdowns/lookups, 1 = heavy reports / rare pages
ENDPOINTS = [
    # ── login / common ──
    ("/auth/me", 3), ("/auth/consent/status", 1), ("/compny/company", 1), ("/compny/my-companies", 2),
    ("/search/quick", 2), ("/search/recent", 1),
    # ── communication (polled by the frontend) ──
    ("/comm/notifications", 5), ("/comm/pings/unread-count", 5), ("/comm/approval-pings/pending", 3),
    ("/comm/announcements", 2), ("/comm/conversations", 3), ("/comm/directory", 1), ("/comm/invites", 1),
    ("/comm/calls/history", 1), ("/comm/calls/incoming", 3), ("/comm/meetings/history", 1),
    ("/comm/meetings/mine", 1), ("/comm/pings/received", 1), ("/comm/pings/sent", 1),
    # ── delete manager ──
    ("/delete-manager/my-requests", 1), ("/delete-manager/notifications", 2), ("/delete-manager/requests", 1),
    # ── billing ──
    ("/billing/brb/list", 3), ("/billing/brr/list", 3), ("/billing/brr/vendor-orders", 2),
    ("/billing/payment-request/eligible-brrs", 2), ("/billing/payment-request/eligible-journals", 2),
    ("/billing/payment-request/list", 3),
    # ── finance: accounting reports (heavy) ──
    ("/finance/accounting/balance-sheet", 1), ("/finance/accounting/bank-ledger", 1),
    ("/finance/accounting/cancellation-status", 1), ("/finance/accounting/cc-ledger", 1),
    ("/finance/accounting/customer-ledger", 1), ("/finance/accounting/day-book", 1),
    ("/finance/accounting/financial-year", 2), ("/finance/accounting/group-ledger", 1),
    ("/finance/accounting/gst-summary", 1), ("/finance/accounting/ledger", 1),
    ("/finance/accounting/opening-balance", 1), ("/finance/accounting/outstanding-payables", 1),
    ("/finance/accounting/outstanding-receivables", 1), ("/finance/accounting/posting-status", 1),
    ("/finance/accounting/profit-loss", 1), ("/finance/accounting/project-summary", 1),
    ("/finance/accounting/stock-balance", 1), ("/finance/accounting/stock-summary", 1),
    ("/finance/accounting/trial-balance", 1), ("/finance/accounting/vendor-ledger", 1),
    ("/finance/accounting/voucher-register", 1),
    ("/finance/balance-sheet", 1), ("/finance/profit-loss", 1), ("/finance/my-ledger", 1), ("/finance/vendor-ledger", 1),
    # ── finance: bank statement ──
    ("/finance/bank-statement/accounts", 2), ("/finance/bank-statement/available-for-docket", 1),
    ("/finance/bank-statement/batches", 1), ("/finance/bank-statement/transactions", 3),
    # ── finance: vouchers ──
    ("/finance/bill-payment/list", 3), ("/finance/bill-payment/approved-journal-vouchers", 2),
    ("/finance/bill-payment/approved-purchase-bills", 2), ("/finance/bill-payment/journal-voucher-items-multi", 1),
    ("/finance/bill-payment/purchase-bill-items-multi", 1),
    ("/finance/contra-entry/list", 3), ("/finance/credit-note/list", 3), ("/finance/credit-note/sale-bill-picker", 2),
    ("/finance/debit-note/list", 3), ("/finance/debit-note/brr-picker", 2),
    ("/finance/journal-entry/list", 3), ("/finance/journal-entry/approved-dockets", 2),
    ("/finance/journal-entry/journal-voucher/list", 5), ("/finance/journal-entry/journal-voucher/available-dockets", 2),
    ("/finance/journal-entry/ref-bills", 2),
    ("/finance/payment-voucher/list", 3),
    # ── finance: petty cash ──
    ("/finance/petty-cash/budget/list", 5), ("/finance/petty-cash/docket-voucher/list", 5),
    ("/finance/petty-cash/docket-voucher/bulk/reference", 1),
    ("/finance/petty-cash/ledger/account-ledger", 1), ("/finance/petty-cash/ledger/project-accounts", 2),
    # ── finance: purchase / sale ──
    ("/finance/purchase-bill/list", 5), ("/finance/purchase-bill/available-brrs", 2),
    ("/finance/purchase-bill/brr-items", 1), ("/finance/purchase-bill/brr-list", 2),
    ("/finance/purchase-bill/vendor-orders", 2),
    ("/finance/sale-bill/list", 3), ("/finance/sale-bill/certified-bill-items", 1), ("/finance/sale-bill/certified-bills", 2),
    ("/finance/sale-receipt-billing/list", 3), ("/finance/sale-receipt-billing/list-by-project", 2),
    ("/finance/sale-receipt-billing/available-invoices", 2), ("/finance/sale-receipt-billing/invoice-lookup", 1),
    ("/finance/sale-receipt/list", 3), ("/finance/sale-receipt/og-sale-orders", 2),
    # ── HR ──
    ("/hr/employee", 3), ("/hr/employee/departments", 2), ("/hr/employee/me", 3),
    ("/hr/gang-tracker", 1), ("/hr/gang-tracker/skills", 1), ("/hr/onboarding", 1), ("/hr/onboarding/stats", 1),
    ("/hr/payroll", 1), ("/hr/payroll/department-summary", 1),
    ("/hr/performance/discipline", 1), ("/hr/performance/discipline/stats", 1),
    ("/hr/performance/reviews", 1), ("/hr/performance/reviews/stats", 1),
    ("/hr/performance/score", 1), ("/hr/performance/score/config", 1), ("/hr/performance/score/me", 2),
    ("/hr/recruitment/candidates", 1), ("/hr/recruitment/interviews", 1), ("/hr/recruitment/jobs", 1),
    ("/hr/recruitment/stats", 1),
    # ── logistics ──
    ("/logistics/bill-register/list", 2), ("/logistics/bill-register/eligible-dcs", 1),
    ("/logistics/transit-request/list", 2), ("/logistics/transit-request/approved-for-dc", 1),
    ("/logistics/transit-request/approved-orders", 1),
    # ── master ──
    ("/master/asset/list", 2), ("/master/bank-cash/list", 2), ("/master/category/list", 3),
    ("/master/cc-code/list", 3), ("/master/group/list", 2), ("/master/item/list", 5),
    ("/master/ledger/dropdown", 3), ("/master/ledger/list", 2), ("/master/sub-group/list", 2),
    ("/master/sub-group/check-code", 1), ("/master/sub-group/suggest-code", 1),
    ("/master/supplier/list", 5), ("/master/supplier/nature-of-service", 1),
    ("/master/term/list", 2), ("/master/unit/list", 3),
    # ── MIS ──
    ("/mis/compliance", 1), ("/mis/followups", 3), ("/mis/followups/access", 2),
    ("/mis/followups/assignable-users", 1), ("/mis/followups/stats", 2), ("/mis/sprints", 2),
    ("/mis/tasks", 5), ("/mis/tasks/access", 2), ("/mis/tasks/assignable-users", 1), ("/mis/tasks/owners", 1),
    ("/mis/tasks/reopen-requests", 1), ("/mis/tasks/stats", 3),
    # ── project management ──
    ("/project-mgmt/billing/list", 3), ("/project-mgmt/billing/cert-bills-for-claim", 1),
    ("/project-mgmt/billing/order-lookup", 1),
    ("/project-mgmt/contract/budget/list", 3), ("/project-mgmt/contract/budget/cc-codes", 2),
    ("/project-mgmt/contract/budget/sale-orders", 1),
    ("/project-mgmt/dpr/list", 3), ("/project-mgmt/dpr/day", 2), ("/project-mgmt/dpr/photos", 1),
    ("/project-mgmt/og-sale-order/list", 3),
    ("/project-mgmt/register/bbs-register/list", 1), ("/project-mgmt/register/concrete-registry/list", 1),
    ("/project-mgmt/register/drawing-register/list", 1), ("/project-mgmt/register/hindrance-register/list", 1),
    ("/project-mgmt/uncertain-allocation/list", 1), ("/project-mgmt/uncertain-allocation/sale-order-lookup", 1),
    # ── resource (stores / purchase / machinery) ──
    ("/resource/batching/list", 2), ("/resource/batching/approved-pw-orders", 1),
    ("/resource/bss/list", 2), ("/resource/bss/vendor-orders", 1),
    ("/resource/bvs/list", 2), ("/resource/bvs/vendor-orders", 1),
    ("/resource/dc/list", 3), ("/resource/dc/approved-orders", 1),
    ("/resource/dlr/list", 2), ("/resource/dlr/report", 1),
    ("/resource/enquiry/list", 2),
    ("/resource/gin/list", 3), ("/resource/gin/vendor-orders", 1),
    ("/resource/grn/list", 5), ("/resource/grn/vendor-orders", 2),
    ("/resource/indent/list", 5), ("/resource/indent/items-by-category", 2),
    ("/resource/machinery/log-book/list", 2), ("/resource/machinery/log-book/pw-orders", 1),
    ("/resource/machinery/log-entry/list", 2), ("/resource/machinery/pm-id/list", 1),
    ("/resource/machinery/service-history/list", 1), ("/resource/machinery/service-schedule/list", 1),
    ("/resource/manpower/list", 2), ("/resource/manpower/categories", 1),
    ("/resource/order/list", 5), ("/resource/order/indent-pending", 2),
    ("/resource/pw-order/list", 3), ("/resource/pw-order/item-list", 1),
    ("/resource/srn/list", 2), ("/resource/srn/vendor-orders", 1),
    ("/resource/stock/list", 3), ("/resource/stock/item-detail", 1),
    # ── settings ──
    ("/setting/approval-path/list", 1), ("/setting/edit-users", 1), ("/setting/project-list", 3), ("/setting/users", 1),
    # ── traceability ──
    ("/traceability/workbench/context", 1), ("/traceability/workbench/flow", 1), ("/traceability/workbench/search", 1),
]

# Left out on purpose:
#   /finance/accounting/export/*  — builds Excel files, very heavy; test alone if needed
#   /ai/insights/finance          — calls the AI service (costs money)
#   /drive-bridge/*               — talks to the file drive
#   /comm/turn-credentials        — creates call credentials
#   /webhook/whatsapp, /health/*  — not user pages

if ONLY:
    ENDPOINTS = [e for e in ENDPOINTS if ONLY in e[0]]


def _params(path):
    return {**COMMON_PARAMS, **EXTRA_PARAMS.get(path, {})}


def _headers():
    return {"Authorization": f"Bearer {TOKEN}", "Accept": "application/json"}


# ══════════════════════════════════════════════════════════════════
# 2) LOCUST LOAD TEST
# ══════════════════════════════════════════════════════════════════
CHECK_MODE = __name__ == "__main__" and len(sys.argv) >= 2 and sys.argv[1] == "check"

try:
    if CHECK_MODE:                         # locust patches ssl on import, which breaks plain requests
        raise ImportError
    from locust import HttpUser, between

    def _make_task(path):
        def _t(user):
            with user.client.get(path, params=_params(path), name=path, catch_response=True) as r:
                if r.status_code == 401:
                    r.failure("401 — token expired, set a new ERP_TOKEN")
                elif r.status_code >= 400:
                    r.failure(f"HTTP {r.status_code}")
        _t.__name__ = "get_" + path.strip("/").replace("/", "_").replace("-", "_")
        return _t

    class ErpUser(HttpUser):
        """One simulated person clicking around the ERP, pausing 1–3 s between clicks."""
        wait_time = between(1, 3)
        tasks = {_make_task(p): w for p, w in ENDPOINTS}

        def on_start(self):
            if not TOKEN:
                raise SystemExit("Set ERP_TOKEN first (Bearer token of a test user)")
            self.client.verify = False
            self.client.headers.update(_headers())
except ImportError:                       # check mode, or locust not installed
    pass


# ══════════════════════════════════════════════════════════════════
# 1) SPEED CHECK (single user)
# ══════════════════════════════════════════════════════════════════
def speed_check(only="", rounds=3):
    import requests
    if not TOKEN:
        sys.exit("Set ERP_TOKEN first:  export ERP_TOKEN='eyJ...'")
    s = requests.Session()
    s.verify = False
    s.headers.update(_headers())
    eps = [p for p, _ in ENDPOINTS if only in p]
    print(f"Checking {len(eps)} APIs on {HOST} (project {PROJECT}), {rounds} call(s) each...\n")
    rows = []
    for i, path in enumerate(eps, 1):
        times, status, size, err = [], None, 0, ""
        for _ in range(rounds):
            t0 = time.perf_counter()
            try:
                r = s.get(HOST + path, params=_params(path), timeout=60)
                status, size = r.status_code, len(r.content)
                if r.status_code >= 400:
                    try:
                        err = (r.json() or {}).get("message", "")[:80]
                    except ValueError:
                        err = r.text[:80]
            except requests.RequestException as e:
                status, err = "ERR", str(e)[:80]
            times.append((time.perf_counter() - t0) * 1000)
            if status == 401:
                sys.exit("401 Unauthorized: token expired or wrong. Set a new ERP_TOKEN.")
            if status != 200:
                break                      # no point repeating a failing call
        rows.append({"path": path, "status": status, "avg_ms": round(statistics.mean(times)),
                     "max_ms": round(max(times)), "kb": round(size / 1024, 1), "error": err})
        print(f"\r  {i}/{len(eps)} {path[:70]:<70}", end="", flush=True)
    print("\n")

    rows.sort(key=lambda r: r["avg_ms"], reverse=True)
    print(f"{'AVG ms':>7} {'MAX ms':>7} {'KB':>7}  {'STATUS':<6} PATH")
    for r in rows:
        flag = "  <-- SLOW" if r["avg_ms"] >= 1000 else ("  <-- check" if r["avg_ms"] >= 500 else "")
        extra = f"   [{r['error']}]" if r["status"] != 200 and r["error"] else ""
        print(f"{r['avg_ms']:>7} {r['max_ms']:>7} {r['kb']:>7}  {str(r['status']):<6} {r['path']}{flag}{extra}")

    ok = [r for r in rows if r["status"] == 200]
    print(f"\n{len(ok)} OK, {len(rows) - len(ok)} failed (400 = needs a parameter, add it in EXTRA_PARAMS; "
          f"403 = this user has no permission). Slow (>=1 s): {sum(r['avg_ms'] >= 1000 for r in ok)}")
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "speed_report.csv")
    with open(out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(f"Saved: {out}")


if __name__ == "__main__":
    if CHECK_MODE:
        speed_check(sys.argv[2] if len(sys.argv) > 2 else "")
    else:
        print(__doc__)
