"""register Central Accounting pages in feature_pages and module_master

Each of the 19 Central Accounting report pages now has its own permission key
instead of sharing profit_loss. This migration:
  1. Ensures a 'Central Accounting' sub-module exists under Finance Management.
  2. Inserts each page into feature_pages (idempotent via WHERE NOT EXISTS).
  3. Inserts each code into module_master so approval paths can reference them
     (idempotent — skips codes already present, e.g. if the SQL was run manually).

Revision ID: cc9d1e2f3a4b
Revises: 3b7a5e16bc0e
Create Date: 2026-11-16 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = 'cc9d1e2f3a4b'
down_revision = '3b7a5e16bc0e'
branch_labels = None
depends_on = None

_PAGES = [
    ("accounting_dashboard",               "Accounting Dashboard",        "/finance-management/report/accounting"),
    ("accounting_ledger",                  "General Ledger",              "/finance-management/report/accounting/general-ledger"),
    ("accounting_trial_balance",           "Trial Balance",               "/finance-management/report/accounting/trial-balance"),
    ("accounting_profit_loss",             "Profit & Loss (Central)",     "/finance-management/report/accounting/profit-loss"),
    ("accounting_balance_sheet",           "Balance Sheet (Central)",     "/finance-management/report/accounting/balance-sheet"),
    ("accounting_vendor_ledger",           "Vendor Ledger",               "/finance-management/report/accounting/vendor-ledger"),
    ("accounting_customer_ledger",         "Customer Ledger",             "/finance-management/report/accounting/customer-ledger"),
    ("accounting_bank_ledger",             "Bank Ledger",                 "/finance-management/report/accounting/bank-ledger"),
    ("accounting_cc_ledger",               "CC-Code Ledger",              "/finance-management/report/accounting/cc-ledger"),
    ("accounting_day_book",                "Day Book",                    "/finance-management/report/accounting/day-book"),
    ("accounting_voucher_register",        "Voucher Register",            "/finance-management/report/accounting/voucher-register"),
    ("accounting_outstanding_payables",    "Outstanding Payables",        "/finance-management/report/accounting/outstanding-payables"),
    ("accounting_outstanding_receivables", "Outstanding Receivables",     "/finance-management/report/accounting/outstanding-receivables"),
    ("accounting_gst_summary",             "GST Summary",                 "/finance-management/report/accounting/gst-summary"),
    ("accounting_project_summary",         "Project Summary",             "/finance-management/report/accounting/project-summary"),
    ("accounting_group_ledger",            "Group Ledger",                "/finance-management/report/accounting/group-ledger"),
    ("accounting_financial_year",          "Financial Year",              "/finance-management/report/accounting/financial-year"),
    ("accounting_posting_status",          "Historical Posting",          "/finance-management/report/accounting/historical-posting"),
    ("accounting_opening_balance",         "Opening Balance",             "/finance-management/report/accounting/opening-balance"),
]


def upgrade():
    conn = op.get_bind()

    # 1. Ensure Finance Management main module exists
    row = conn.execute(
        sa.text("SELECT id FROM main_modules WHERE module_name = 'Finance Management' LIMIT 1")
    ).fetchone()
    if row:
        main_id = row[0]
    else:
        main_id = conn.execute(
            sa.text("INSERT INTO main_modules (module_name, icon) VALUES ('Finance Management', 'Wallet') RETURNING id")
        ).fetchone()[0]

    # 2. Ensure Central Accounting sub-module exists under Finance Management
    row = conn.execute(
        sa.text("SELECT id FROM sub_modules WHERE main_module_id = :mid AND submodule_name = 'Central Accounting' LIMIT 1"),
        {"mid": main_id},
    ).fetchone()
    if row:
        sub_id = row[0]
    else:
        sub_id = conn.execute(
            sa.text("INSERT INTO sub_modules (main_module_id, submodule_name) VALUES (:mid, 'Central Accounting') RETURNING id"),
            {"mid": main_id},
        ).fetchone()[0]

    # 3. Insert feature_pages (idempotent)
    insert_page = sa.text(
        """INSERT INTO feature_pages (submodule_id, page_name, page_code, route_path, is_menu_visible, sort_order)
        SELECT :sid, :name, :code, :route, TRUE, :sort
        WHERE NOT EXISTS (SELECT 1 FROM feature_pages WHERE page_code = :code)"""
    )
    for i, (code, name, route) in enumerate(_PAGES, start=1):
        conn.execute(insert_page, {"sid": sub_id, "name": name, "code": code, "route": route, "sort": i})

    # 4. Insert module_master (idempotent — skips rows from any manual SQL run)
    insert_module = sa.text(
        """INSERT INTO module_master (module_code, module_name, status)
        SELECT :code, :name, 'Active'
        WHERE NOT EXISTS (SELECT 1 FROM module_master WHERE module_code = :code)"""
    )
    for code, name, _ in _PAGES:
        conn.execute(insert_module, {"code": code, "name": name})


def downgrade():
    # Rows are kept intentionally: existing permissions may reference them.
    pass
