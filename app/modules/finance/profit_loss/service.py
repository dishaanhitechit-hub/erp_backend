from decimal import Decimal
from app.extensions import db
from app.models.ogSaleOrder import OgSaleOrderMaster
from app.models.budget import BudgetMaster, BudgetItem, BudgetItemCCCode
from app.response import res

# P&L row definitions — order matches the PDF format
_PL_ROWS = [
    # ref        code    particulars
    ("A",    None,   "SALE",                                    "header"),
    ("A.1",  "CRIN", "Certified Invoice Sale",                  "sale"),
    ("A.2",  "CRHL", "Certified but Hold",                      "sale"),
    ("A.3",  "CRAP", "Certified Amendment Pending",             "sale"),
    ("A.4",  "UCAP", "Work Done Uncertified Amendment Pending", "sale"),
    ("A.5",  "WIPS", "Job Work in Progress",                    "sale"),
    ("A.6",  "INOC", "Head Office Bearing Share",               "sale"),

    ("B",    None,   "Expenses",                                "header"),
    ("B.1",  None,   "Direct Expenses",                         "header"),
    ("B.1.1","DRCW", "Composite Work Charges",                  "expense"),
    ("B.1.2","DRMC", "Consumable Materials",                    "expense"),
    ("B.1.3","DRFD", "Diesel & Others Fuels",                   "expense"),
    ("B.1.4","DRMH", "Hardware Materials",                      "expense"),
    ("B.1.5","DRUS", "Uniform & Safety Materials",              "expense"),
    ("B.1.6","DRMR", "Machinery Rental/Hire Charges",           "expense"),
    ("B.1.7","DRLC", "PRW Work Charges",                        "expense"),
    ("B.1.8","DRLS", "Lumsum Work Charges",                     "expense"),
    ("B.1.9","DRMS", "Shuttering Materials",                    "expense"),

    ("B.2",      None,   "Indirect Expenses",        "header"),
    ("B.2.1",    None,   "Project Overhead",          "header"),
    ("B.2.1.1",  "IRDC", "Assets Depreciation Charges",         "expense"),
    ("B.2.1.2",  "IRAD", "Assets Rental Charges",               "expense"),
    ("B.2.1.3",  "IRLE", "Electricity & Water",                 "expense"),
    ("B.2.1.4",  "IRFS", "Food at Site Office",                 "expense"),
    ("B.2.1.5",  "IRMR", "Machinery Repair & Maintenance",      "expense"),
    ("B.2.1.6",  "IRLU", "Materials Loading & Unloading",       "expense"),
    ("B.2.1.7",  "IRMT", "Materials Transport Charges",         "expense"),
    ("B.2.1.8",  "IRPS", "Printing & Stationery",               "expense"),
    ("B.2.1.9",  "IRSD", "Scrap & Demolition for Defective work","expense"),
    ("B.2.1.10", "IRIM", "Site Infra Materials",                "expense"),
    ("B.2.1.11", "IRIL", "Site Infra Work Charges",             "expense"),
    ("B.2.1.12", "IRFM", "Site Office Maintenance",             "expense"),
    ("B.2.1.13", "IRTT", "Hand Tools & Tackles",                "expense"),
    ("B.2.1.14", "IRLH", "Worker Hospitality & Hygiene",        "expense"),
    ("B.2.1.15", "IRLM", "Worker Mobilization Expenses",        "expense"),
    ("B.2.1.16", "IRLT", "Worker Tifin & Foods",                "expense"),

    ("B.2.2",    None,   "Employee Overhead",         "header"),
    ("B.2.2.1",  "IOFM", "Food Exp. at Guest House",            "expense"),
    ("B.2.2.2",  "IOHR", "House Rent & Electricity",            "expense"),
    ("B.2.2.3",  "IOME", "Medical & Hospitalization",           "expense"),
    ("B.2.2.4",  "IOMS", "Miscellaneous Expenses",              "expense"),
    ("B.2.2.5",  "IOMB", "Mobile & Internet",                   "expense"),
    ("B.2.2.6",  "IOSS", "Staff Salary & Bonus",                "expense"),
    ("B.2.2.7",  "IOVR", "Staff Vehicles Running",              "expense"),
    ("B.2.2.8",  "IOTV", "Tour & Travelling",                   "expense"),

    ("B.2.3",    None,   "Office Overhead",           "header"),
    ("B.2.3.1",  "IOCR", "Head Office Expenses",                "expense"),
    ("B.2.3.2",  "CRBC", "Bank Charges",                        "expense"),
    ("B.2.3.3",  "CRBD", "Business Development",                "expense"),
    ("B.2.3.4",  "CRCC", "Consultancy Charges",                 "expense"),
    ("B.2.3.5",  "CRDR", "Director Remuneration",               "expense"),
    ("B.2.3.6",  "CRES", "Employee Insurance",                  "expense"),
    ("B.2.3.7",  "CRIC", "Insurance Charges",                   "expense"),
    ("B.2.3.8",  "CRIP", "Interest Paid",                       "expense"),
    ("B.2.3.9",  "CRLC", "Legal Charges",                       "expense"),
    ("B.2.3.10", "CRPF", "Provident Fund",                      "expense"),
    ("B.2.3.11", "CRIT", "Income Tax Paid",                     "expense"),

    ("C",    None,   "Profit & Loss",                           "header"),
]


def get_pl_report(args):
    try:
        project_code = args.get("projectCode")
        if not project_code:
            return res("projectCode required", [], 400)

        # ── A. SALE — total of all approved sale orders ──────────────
        sale_total = (
            db.session.query(db.func.coalesce(db.func.sum(OgSaleOrderMaster.total_amount), 0))
            .filter(
                OgSaleOrderMaster.project_code    == project_code,
                OgSaleOrderMaster.workflow_status == "Approved",
                OgSaleOrderMaster.status          == "Active",
            )
            .scalar()
        )
        sale_order_value = float(sale_total or 0)

        # ── B. EXPENSES — sum cc_total grouped by cc_code ────────────
        # across all approved budgets for the project
        cc_rows = (
            db.session.query(
                BudgetItemCCCode.cc_code,
                db.func.sum(BudgetItemCCCode.cc_total).label("total"),
            )
            .join(BudgetItem,   BudgetItemCCCode.budget_item_id == BudgetItem.id)
            .join(BudgetMaster, BudgetItem.budget_id            == BudgetMaster.id)
            .filter(
                BudgetMaster.project_code    == project_code,
                BudgetMaster.workflow_status == "Approved",
                BudgetMaster.status          == "Active",
            )
            .group_by(BudgetItemCCCode.cc_code)
            .all()
        )

        # build lookup {cc_code: order_value}
        cc_map = {row.cc_code: float(row.total or 0) for row in cc_rows}

        # ── Build P&L rows ───────────────────────────────────────────
        total_expense = Decimal("0")
        rows_out      = []

        for (ref, code, particulars, row_type) in _PL_ROWS:
            if row_type == "header":
                rows_out.append({
                    "ref":         ref,
                    "code":        code,
                    "particulars": particulars,
                    "type":        "header",
                    "order":       None,
                })

            elif row_type == "sale":
                # Sale breakdown rows — Order column shows combined total only on section A
                rows_out.append({
                    "ref":         ref,
                    "code":        code,
                    "particulars": particulars,
                    "type":        "sale",
                    "order":       sale_order_value if ref == "A.1" else 0,
                })

            elif row_type == "expense":
                val = cc_map.get(code, 0)
                total_expense += Decimal(str(val))
                rows_out.append({
                    "ref":         ref,
                    "code":        code,
                    "particulars": particulars,
                    "type":        "expense",
                    "order":       val,
                })

        total_expense_val = float(total_expense)
        profit_loss_val   = sale_order_value - total_expense_val

        # Attach totals to Section A, B, C header rows
        summary = {
            "totalSale":    sale_order_value,
            "totalExpense": total_expense_val,
            "profitLoss":   profit_loss_val,
        }

        return res("P&L report fetched", {
            "projectCode": project_code,
            "summary":     summary,
            "rows":        rows_out,
        }, 200)

    except Exception as e:
        return res(str(e), [], 500)
