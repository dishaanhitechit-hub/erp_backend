"""
PDF and Excel export for accounting reports.

Uses xhtml2pdf for PDF and openpyxl (via csv fallback) for Excel.
All exports use the same data as the screen reports.
Tally-style formatting: serif font, By/To convention, Dr/Cr balance,
Indian number format, T-format Balance Sheet.
"""

import io
import csv
from datetime import datetime
from decimal import Decimal
from flask import make_response

from .ledger_service import (
    get_general_ledger,
    get_trial_balance,
    get_profit_loss,
    get_balance_sheet_report,
)


# ═══════════════════════════════════════════════════════════════════════════
# NUMBER FORMATTING
# ═══════════════════════════════════════════════════════════════════════════

def _fmt_indian(val):
    """Format number in Indian style: 1,23,45,678.90"""
    if val is None:
        return ""
    n = float(val)
    if n == 0:
        return ""
    sign = "-" if n < 0 else ""
    n = abs(n)
    decimal_part = f"{n:.2f}".split(".")[1]
    integer_part = int(n)
    s = str(integer_part)
    if len(s) <= 3:
        return f"{sign}{s}.{decimal_part}"
    result = s[-3:]
    s = s[:-3]
    while s:
        result = s[-2:] + "," + result
        s = s[:-2]
    return f"{sign}{result}.{decimal_part}"


def _fmt_num(val):
    """Format number Indian style, dash for zero."""
    if val is None:
        return ""
    n = float(val)
    if n == 0:
        return "—"
    return _fmt_indian(n)


def _bal_dr_cr(val):
    """Format balance with Dr/Cr suffix like Tally."""
    if val is None or float(val) == 0:
        return "—"
    n = float(val)
    return f"{_fmt_indian(abs(n))} {'Dr' if n > 0 else 'Cr'}"


# ═══════════════════════════════════════════════════════════════════════════
# COMPANY INFO
# ═══════════════════════════════════════════════════════════════════════════

def _get_company_info():
    """Load company details from settings."""
    try:
        from app.models.companies import Company
        company = Company.query.first()
        if company:
            addr_parts = []
            if company.registered_address:
                addr_parts.append(company.registered_address)
            if company.corporate_address:
                addr_parts.append(company.corporate_address)
            addr = ", ".join(addr_parts) if addr_parts else ""
            return {
                "name": company.company_name or "PRAX ERP",
                "address": addr,
                "contact": getattr(company, "contact_number", "") or "",
                "email": getattr(company, "email", "") or "",
            }
    except Exception:
        pass
    return {"name": "PRAX ERP", "address": "", "contact": "", "email": ""}


# ═══════════════════════════════════════════════════════════════════════════
# PDF STYLES
# ═══════════════════════════════════════════════════════════════════════════

_PDF_CSS_TALLY = """
<style>
    @page { size: A4 landscape; margin: 1.2cm; }
    body { font-family: 'Times New Roman', Times, serif; font-size: 10px; color: #000; margin: 0; }

    /* Header */
    .header { text-align: center; margin-bottom: 8px; }
    .header h1 { font-size: 14px; margin: 0; font-weight: bold; }
    .header .addr { font-size: 8px; margin: 1px 0; }
    .header h2 { font-size: 12px; margin: 4px 0 1px; font-weight: bold; }
    .header .sub { font-size: 10px; margin: 2px 0; }
    .header .period { font-size: 9px; margin: 1px 0; }

    /* Ledger table */
    table.ledger { width: 100%; border-collapse: collapse; margin-top: 4px; }
    table.ledger th {
        border-top: 1px solid #000; border-bottom: 1px solid #000;
        padding: 3px 5px; text-align: left; font-size: 9px; font-weight: bold;
    }
    table.ledger th.r { text-align: right; }
    table.ledger td { padding: 1px 5px; font-size: 9px; vertical-align: top; }
    table.ledger td.r { text-align: right; font-family: 'Courier New', monospace; font-size: 8.5px; }
    table.ledger td.byto { width: 18px; }
    table.ledger tr.closing td { border-top: 1px solid #000; font-weight: bold; }
    table.ledger tr.grand td { border-top: 2px solid #000; border-bottom: 2px solid #000; font-weight: bold; }
    table.ledger tr.grp td { font-weight: bold; padding-top: 4px; }
    table.ledger tr.sg td { font-weight: bold; font-style: italic; }
    .i1 { padding-left: 18px !important; }
    .i2 { padding-left: 32px !important; }
    .i3 { padding-left: 46px !important; }

    /* Balance Sheet T-format */
    table.bs-wrap { width: 100%; border-collapse: collapse; }
    table.bs-wrap > tbody > tr > td { width: 50%; vertical-align: top; padding: 0; }
    table.bs-wrap > tbody > tr > td.left { border-right: 1px solid #000; padding-right: 4px; }
    table.bs-wrap > tbody > tr > td.right { padding-left: 4px; }
    table.bs-side { width: 100%; border-collapse: collapse; }
    table.bs-side th { border-bottom: 1px solid #000; padding: 3px 4px; font-size: 9px; font-weight: bold; }
    table.bs-side th.r { text-align: right; }
    table.bs-side td { padding: 1px 4px; font-size: 9px; vertical-align: top; }
    table.bs-side td.r { text-align: right; font-family: 'Courier New', monospace; font-size: 8.5px; }
    table.bs-side tr.grp td { font-weight: bold; padding-top: 4px; }
    table.bs-side tr.closing td { border-top: 1px solid #000; font-weight: bold; }
    table.bs-side tr.grand td { border-top: 2px solid #000; border-bottom: 2px solid #000; font-weight: bold; }
    .bi1 { padding-left: 14px !important; font-style: italic; }
    .bi2 { padding-left: 26px !important; font-style: italic; }
    .bi3 { padding-left: 38px !important; font-style: italic; }

    .footer { text-align: center; font-size: 7px; color: #999; margin-top: 6px; }
</style>
"""


def _render_pdf(html_content, filename):
    """Render HTML to PDF and return Flask response."""
    try:
        from xhtml2pdf import pisa
    except ImportError:
        return {"message": "xhtml2pdf not installed", "data": []}, 500

    result = io.BytesIO()
    pisa_status = pisa.CreatePDF(io.StringIO(html_content), dest=result)

    if pisa_status.err:
        return {"message": "PDF generation failed", "data": []}, 500

    response = make_response(result.getvalue())
    response.headers["Content-Type"] = "application/pdf"
    response.headers["Content-Disposition"] = f"attachment; filename={filename}"
    return response


def _company_header_html(title, subtitle="", period="", project=""):
    """Tally-style company header matching the reference PDF."""
    c = _get_company_info()
    lines = [f'<h1>{c["name"]}</h1>']
    if c["address"]:
        lines.append(f'<div class="addr">{c["address"]}</div>')
    contact_parts = []
    if c["contact"]:
        contact_parts.append(f'Contact : {c["contact"]}')
    if c["email"]:
        contact_parts.append(f'E-Mail : {c["email"]}')
    if contact_parts:
        lines.append(f'<div class="addr">{" | ".join(contact_parts)}</div>')
    lines.append(f'<h2>{title}</h2>')
    if subtitle:
        lines.append(f'<div class="sub">{subtitle}</div>')
    if period:
        lines.append(f'<div class="period">{period}</div>')
    if project and project != "All":
        lines.append(f'<div class="period">Project: {project}</div>')
    return '<div class="header">' + "\n".join(lines) + "</div>"


# ═══════════════════════════════════════════════════════════════════════════
# EXCEL GENERATION
# ═══════════════════════════════════════════════════════════════════════════

def _render_excel(headers, rows, filename, sheet_name="Sheet1", title=None, filters=None):
    """Generate Excel file. Try openpyxl, fall back to CSV."""
    try:
        import openpyxl
        return _render_excel_openpyxl(headers, rows, filename, sheet_name, title, filters)
    except ImportError:
        return _render_csv(headers, rows, filename)


def _render_excel_openpyxl(headers, rows, filename, sheet_name, title, filters):
    import openpyxl
    from openpyxl.styles import Font, Alignment, PatternFill, Border, Side

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = sheet_name

    row_num = 1
    company = _get_company_info()

    ws.merge_cells(start_row=row_num, start_column=1, end_row=row_num, end_column=len(headers))
    cell = ws.cell(row=row_num, column=1, value=company["name"])
    cell.font = Font(name="Times New Roman", size=14, bold=True)
    cell.alignment = Alignment(horizontal="center")
    row_num += 1

    if title:
        ws.merge_cells(start_row=row_num, start_column=1, end_row=row_num, end_column=len(headers))
        cell = ws.cell(row=row_num, column=1, value=title)
        cell.font = Font(name="Times New Roman", size=12, bold=True)
        cell.alignment = Alignment(horizontal="center")
        row_num += 1

    if filters:
        filter_str = " | ".join(f"{k}: {v}" for k, v in filters.items() if v)
        ws.merge_cells(start_row=row_num, start_column=1, end_row=row_num, end_column=len(headers))
        ws.cell(row=row_num, column=1, value=filter_str).font = Font(name="Times New Roman", size=9, italic=True)
        row_num += 1

    row_num += 1

    header_fill = PatternFill(start_color="2C3E50", end_color="2C3E50", fill_type="solid")
    header_font = Font(name="Times New Roman", color="FFFFFF", bold=True, size=10)
    thin_border = Border(
        bottom=Side(style="thin"), top=Side(style="thin"),
        left=Side(style="thin"), right=Side(style="thin"),
    )

    for col_idx, header in enumerate(headers, start=1):
        cell = ws.cell(row=row_num, column=col_idx, value=header)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal="center")
        cell.border = thin_border
    row_num += 1

    body_font = Font(name="Times New Roman", size=10)
    bold_font = Font(name="Times New Roman", size=10, bold=True)

    for row_data in rows:
        is_total = False
        if row_data and isinstance(row_data[0], str):
            lbl = row_data[0].strip().lower()
            is_total = lbl.startswith("total") or lbl.startswith("net ") or lbl.startswith("grand") or lbl == "closing balance"
        for col_idx, val in enumerate(row_data, start=1):
            cell = ws.cell(row=row_num, column=col_idx, value=val)
            cell.font = bold_font if is_total else body_font
            if isinstance(val, (int, float, Decimal)):
                cell.number_format = "#,##0.00"
                cell.alignment = Alignment(horizontal="right")
            cell.border = thin_border
        row_num += 1

    data_start = row_num - len(rows)
    ws.freeze_panes = ws.cell(row=data_start, column=1)

    for col_idx in range(1, len(headers) + 1):
        max_len = len(str(headers[col_idx - 1]))
        for row_data in rows[:50]:
            if col_idx - 1 < len(row_data):
                max_len = max(max_len, len(str(row_data[col_idx - 1] or "")))
        ws.column_dimensions[openpyxl.utils.get_column_letter(col_idx)].width = min(max_len + 4, 45)

    output = io.BytesIO()
    wb.save(output)
    output.seek(0)

    response = make_response(output.getvalue())
    response.headers["Content-Type"] = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    response.headers["Content-Disposition"] = f"attachment; filename={filename}"
    return response


def _render_csv(headers, rows, filename):
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(headers)
    for row in rows:
        writer.writerow(row)
    response = make_response(output.getvalue())
    response.headers["Content-Type"] = "text/csv"
    response.headers["Content-Disposition"] = f"attachment; filename={filename.replace('.xlsx', '.csv')}"
    return response


# ═══════════════════════════════════════════════════════════════════════════
# TREE HELPERS (for P&L and BS)
# ═══════════════════════════════════════════════════════════════════════════

def _flatten_subgroups_html(subgroups, depth=1, prefix="i"):
    """Recursively render subgroup tree rows for PDF."""
    html = ""
    cls = f"{prefix}{min(depth, 3)}"
    for sg in subgroups:
        html += f'<tr class="sg"><td class="{cls}">{sg["name"]}</td>'
        html += f'<td class="r"></td><td class="r">{_fmt_num(sg["total"])}</td></tr>'
        if sg.get("children"):
            html += _flatten_subgroups_html(sg["children"], depth + 1, prefix)
        for acc in sg.get("accounts", []):
            acls = f"{prefix}{min(depth + 1, 3)}"
            html += f'<tr><td class="{acls}">{acc["ccCode"]} - {acc["ccName"]}</td>'
            html += f'<td class="r">{_fmt_num(acc["net"])}</td><td class="r"></td></tr>'
    return html


def _flatten_subgroups_rows(subgroups, depth=1):
    """Recursively flatten subgroup tree for Excel rows."""
    rows = []
    prefix = "  " * depth
    for sg in subgroups:
        rows.append({"name": f"{prefix}{sg['name']}", "amount": sg["total"], "is_group": True})
        if sg.get("children"):
            rows.extend(_flatten_subgroups_rows(sg["children"], depth + 1))
        for acc in sg.get("accounts", []):
            rows.append({"name": f"{prefix}  {acc['ccCode']} - {acc['ccName']}", "amount": acc["net"], "is_group": False})
    return rows


# ═══════════════════════════════════════════════════════════════════════════
# GENERAL LEDGER EXPORT
# ═══════════════════════════════════════════════════════════════════════════

def export_general_ledger(params):
    fmt = params.get("format", "excel")
    data_resp, code = get_general_ledger(params)
    if code != 200:
        return data_resp, code

    data = data_resp["data"]
    entries = data["entries"]
    account_name = data.get("accountName", "")
    from_d = data.get("fromDate", "")
    to_d = data.get("toDate", "")
    project = data.get("projectCode", "All")
    period = f"{from_d} to {to_d}" if from_d and to_d else ""

    if fmt == "pdf":
        rows_html = ""
        ob = data.get("openingBalance", 0)
        if ob:
            ob_side = "By" if ob < 0 else "To"
            rows_html += f'<tr><td></td><td class="byto">{ob_side}</td>'
            rows_html += f'<td><b>Opening Balance</b></td><td></td><td></td>'
            rows_html += f'<td class="r"></td><td class="r"></td>'
            rows_html += f'<td class="r">{_bal_dr_cr(ob)}</td></tr>'

        for e in entries:
            # Tally: By = Credit to this account, To = Debit from this account
            is_cr = bool(e.get("credit"))
            by_to = "By" if is_cr else "To"
            # Particulars = counterparty account name(s), fallback to narration
            part = e.get("particulars") or e.get("narration", "")
            if len(part) > 55:
                part = part[:55] + "…"
            rows_html += f"""<tr>
                <td>{e['date']}</td>
                <td class="byto">{by_to}</td>
                <td><b>{part}</b></td>
                <td>{e.get('sourceTypeLabel', '')}</td>
                <td>{e.get('voucherNo', '')}</td>
                <td class="r">{_fmt_num(e['debit']) if e.get('debit') else ''}</td>
                <td class="r">{_fmt_num(e['credit']) if e.get('credit') else ''}</td>
                <td class="r">{_bal_dr_cr(e.get('balance', 0))}</td>
            </tr>"""

        # Closing balance row
        cb = data.get("closingBalance", 0)
        rows_html += '<tr class="closing"><td></td><td class="byto"></td>'
        rows_html += f'<td><b>Closing Balance</b></td><td></td><td></td>'
        rows_html += f'<td class="r"></td><td class="r"></td>'
        rows_html += f'<td class="r">{_bal_dr_cr(cb)}</td></tr>'

        # Grand totals
        td = data.get("totalDebit", 0)
        tc = data.get("totalCredit", 0)
        grand = max(td, tc)
        rows_html += f'<tr class="grand"><td colspan="5"></td>'
        rows_html += f'<td class="r">{_fmt_indian(td)}</td>'
        rows_html += f'<td class="r">{_fmt_indian(tc)}</td>'
        rows_html += f'<td class="r">{_fmt_indian(grand)}</td></tr>'

        html = f"""<html><head>{_PDF_CSS_TALLY}</head><body>
        {_company_header_html("Ledger Account", subtitle=account_name, period=period, project=project)}
        <table class="ledger">
            <thead><tr>
                <th style="width:65px">Date</th><th class="byto"></th>
                <th>Particulars</th><th>Vch Type</th><th>Vch No.</th>
                <th class="r" style="width:85px">Debit</th>
                <th class="r" style="width:85px">Credit</th>
                <th class="r" style="width:100px">Balance</th>
            </tr></thead>
            <tbody>{rows_html}</tbody>
        </table>
        <div class="footer">Page <pdf:pagenumber/></div>
        </body></html>"""
        return _render_pdf(html, "general_ledger.pdf")

    # Excel
    headers = ["Date", "By/To", "Particulars", "Vch Type", "Vch No", "Debit", "Credit", "Balance"]
    rows = []
    ob = data.get("openingBalance", 0)
    rows.append(["", "By" if ob < 0 else "To", "Opening Balance", "", "", "", "", _bal_dr_cr(ob)])
    for e in entries:
        is_cr = bool(e.get("credit"))
        part = e.get("particulars") or e.get("narration", "")
        rows.append([
            e["date"],
            "By" if is_cr else "To",
            part,
            e.get("sourceTypeLabel", ""),
            e.get("voucherNo", ""),
            e["debit"] or "",
            e["credit"] or "",
            _bal_dr_cr(e.get("balance", 0)),
        ])
    rows.append(["", "", "Closing Balance", "", "", data.get("totalDebit", 0), data.get("totalCredit", 0), _bal_dr_cr(data.get("closingBalance", 0))])

    filters = {"Account": account_name, "Period": period, "Project": project}
    return _render_excel(headers, rows, "general_ledger.xlsx", "Ledger", "Ledger Account", filters)


# ═══════════════════════════════════════════════════════════════════════════
# TRIAL BALANCE EXPORT
# ═══════════════════════════════════════════════════════════════════════════

def export_trial_balance(params):
    fmt = params.get("format", "excel")
    data_resp, code = get_trial_balance(params)
    if code != 200:
        return data_resp, code

    data = data_resp["data"]
    rows_data = data["rows"]
    from_d = data.get("fromDate", "")
    to_d = data.get("toDate", "")
    project = data.get("projectCode", "All")
    period = f"{from_d} to {to_d}" if from_d and to_d else ""

    if fmt == "pdf":
        rows_html = ""
        for r in rows_data:
            rows_html += f"""<tr>
                <td>{r.get('accountType', '')}</td>
                <td>{r['accountName']}</td>
                <td>{r.get('groupName', '') or ''}</td>
                <td>{r.get('headUnder', '')}</td>
                <td class="r">{_fmt_num(r.get('closingDebit')) if r.get('closingDebit') else ''}</td>
                <td class="r">{_fmt_num(r.get('closingCredit')) if r.get('closingCredit') else ''}</td>
            </tr>"""

        gd = data.get("grandTotalDebit", 0)
        gc = data.get("grandTotalCredit", 0)
        rows_html += f"""<tr class="grand">
            <td colspan="4">Grand Total</td>
            <td class="r">{_fmt_num(gd)}</td>
            <td class="r">{_fmt_num(gc)}</td>
        </tr>"""

        html = f"""<html><head>{_PDF_CSS_TALLY}</head><body>
        {_company_header_html("Trial Balance", period=period, project=project)}
        <table class="ledger">
            <thead><tr>
                <th>Type</th><th>Account Name</th><th>Group</th>
                <th>Head Under</th><th class="r">Debit</th><th class="r">Credit</th>
            </tr></thead>
            <tbody>{rows_html}</tbody>
        </table>
        <div class="footer">Page <pdf:pagenumber/></div>
        </body></html>"""
        return _render_pdf(html, "trial_balance.pdf")

    headers = ["Type", "Account Name", "Group", "Head Under", "Debit", "Credit"]
    rows = [[r.get("accountType", ""), r["accountName"], r.get("groupName", ""), r.get("headUnder", ""), r.get("closingDebit", ""), r.get("closingCredit", "")] for r in rows_data]
    rows.append(["", "Grand Total", "", "", data.get("grandTotalDebit", 0), data.get("grandTotalCredit", 0)])
    filters = {"Period": period, "Project": project}
    return _render_excel(headers, rows, "trial_balance.xlsx", "Trial Balance", "Trial Balance", filters)


# ═══════════════════════════════════════════════════════════════════════════
# PROFIT & LOSS EXPORT
# ═══════════════════════════════════════════════════════════════════════════

def _pl_section_html(label, groups):
    """Render one P&L section (INCOME or EXPENSE) as table rows."""
    html = f'<tr class="grp"><td colspan="3"><b>{label}</b></td></tr>'
    for grp in groups:
        html += f'<tr class="grp"><td class="i1">{grp["groupName"]}</td>'
        html += f'<td class="r"></td><td class="r">{_fmt_num(grp["total"])}</td></tr>'
        if grp.get("subGroups"):
            html += _flatten_subgroups_html(grp["subGroups"], depth=2, prefix="i")
        for acc in grp.get("accounts", []):
            html += f'<tr><td class="i2">{acc["ccCode"]} - {acc["ccName"]}</td>'
            html += f'<td class="r">{_fmt_num(acc["net"])}</td><td class="r"></td></tr>'
    return html


def _pl_section_rows(label, groups):
    """Flatten one P&L section for Excel."""
    rows = [{"name": label, "amount": "", "is_header": True}]
    for grp in groups:
        rows.append({"name": f"  {grp['groupName']}", "amount": grp["total"], "is_group": True})
        if grp.get("subGroups"):
            rows.extend(_flatten_subgroups_rows(grp["subGroups"], depth=2))
        for acc in grp.get("accounts", []):
            rows.append({"name": f"    {acc['ccCode']} - {acc['ccName']}", "amount": acc["net"], "is_group": False})
    return rows


def export_profit_loss(params):
    fmt = params.get("format", "excel")
    data_resp, code = get_profit_loss(params)
    if code != 200:
        return data_resp, code

    data = data_resp["data"]
    from_d = data.get("fromDate", "")
    to_d = data.get("toDate", "")
    project = data.get("projectCode", "All")
    period = f"{from_d} to {to_d}" if from_d and to_d else ""

    if fmt == "pdf":
        body = _pl_section_html("INCOME", data.get("income", []))
        body += f'<tr class="closing"><td>Total Income</td><td class="r"></td><td class="r">{_fmt_num(data["totalIncome"])}</td></tr>'
        body += '<tr><td colspan="3">&nbsp;</td></tr>'
        body += _pl_section_html("EXPENSE", data.get("expense", []))
        body += f'<tr class="closing"><td>Total Expense</td><td class="r"></td><td class="r">{_fmt_num(data["totalExpense"])}</td></tr>'
        body += '<tr><td colspan="3">&nbsp;</td></tr>'
        net = data["netProfit"]
        lbl = "Net Profit" if net >= 0 else "Net Loss"
        body += f'<tr class="grand"><td>{lbl}</td><td class="r"></td><td class="r">{_fmt_num(abs(net))}</td></tr>'

        html = f"""<html><head>{_PDF_CSS_TALLY}</head><body>
        {_company_header_html("Profit &amp; Loss Statement", period=period, project=project)}
        <table class="ledger">
            <thead><tr><th>Particulars</th><th class="r" style="width:100px">Amount</th><th class="r" style="width:110px">Total</th></tr></thead>
            <tbody>{body}</tbody>
        </table>
        <div class="footer">Page <pdf:pagenumber/></div>
        </body></html>"""
        return _render_pdf(html, "profit_loss.pdf")

    headers = ["Particulars", "Amount", "Total"]
    excel_rows = []
    for r in _pl_section_rows("INCOME", data.get("income", [])):
        if r.get("is_header"):
            excel_rows.append([r["name"], "", ""])
        elif r.get("is_group"):
            excel_rows.append([r["name"], "", r["amount"]])
        else:
            excel_rows.append([r["name"], r["amount"], ""])
    excel_rows.append(["Total Income", "", data["totalIncome"]])
    excel_rows.append(["", "", ""])
    for r in _pl_section_rows("EXPENSE", data.get("expense", [])):
        if r.get("is_header"):
            excel_rows.append([r["name"], "", ""])
        elif r.get("is_group"):
            excel_rows.append([r["name"], "", r["amount"]])
        else:
            excel_rows.append([r["name"], r["amount"], ""])
    excel_rows.append(["Total Expense", "", data["totalExpense"]])
    excel_rows.append(["", "", ""])
    net = data["netProfit"]
    excel_rows.append(["Net Profit" if net >= 0 else "Net Loss", "", abs(net)])
    filters = {"Period": period, "Project": project}
    return _render_excel(headers, excel_rows, "profit_loss.xlsx", "P&L", "Profit & Loss Statement", filters)


# ═══════════════════════════════════════════════════════════════════════════
# BALANCE SHEET EXPORT
# ═══════════════════════════════════════════════════════════════════════════

def _bs_side_html(groups, extras=None):
    """Render one BS side (Assets or Liabilities) as table rows."""
    html = ""
    for grp in groups:
        html += f'<tr class="grp"><td><b>{grp["groupName"]}</b></td><td class="r"></td><td class="r">{_fmt_num(grp["total"])}</td></tr>'
        if grp.get("subGroups"):
            html += _flatten_subgroups_html(grp["subGroups"], depth=1, prefix="bi")
        for acc in grp.get("accounts", []):
            html += f'<tr><td class="bi1">{acc["ccCode"]} - {acc["ccName"]}</td>'
            html += f'<td class="r">{_fmt_num(acc["net"])}</td><td class="r"></td></tr>'
    for item in (extras or []):
        if item.get("type") == "vendorSummary":
            html += f'<tr class="grp"><td><b>{item["name"]}</b></td><td class="r"></td><td class="r">{_fmt_num(item["balance"])}</td></tr>'
            for d in item.get("details", []):
                html += f'<tr><td class="bi1">{d.get("code", "")} - {d["name"]}</td>'
                html += f'<td class="r">{_fmt_num(d["balance"])}</td><td class="r"></td></tr>'
        elif item.get("type") == "bankCash":
            html += f'<tr><td class="bi1">{item.get("code", "")} - {item["name"]}</td>'
            html += f'<td class="r">{_fmt_num(item["balance"])}</td><td class="r"></td></tr>'
        elif item.get("type") == "plResult":
            html += f'<tr class="grp"><td><b>Profit &amp; Loss A/c</b></td><td class="r"></td><td class="r">{_fmt_num(item["balance"])}</td></tr>'
            html += f'<tr><td class="bi1">{item["name"]}</td>'
            html += f'<td class="r">{_fmt_num(item["balance"])}</td><td class="r"></td></tr>'
    return html


def _bs_side_rows(groups, extras=None):
    """Flatten one BS side for Excel."""
    rows = []
    for grp in groups:
        rows.append({"name": grp["groupName"], "sub": "", "total": grp["total"], "bold": True})
        if grp.get("subGroups"):
            for sr in _flatten_subgroups_rows(grp["subGroups"], depth=1):
                rows.append({"name": sr["name"], "sub": sr["amount"] if not sr["is_group"] else "", "total": sr["amount"] if sr["is_group"] else "", "bold": sr["is_group"]})
        for acc in grp.get("accounts", []):
            rows.append({"name": f"  {acc['ccCode']} - {acc['ccName']}", "sub": acc["net"], "total": "", "bold": False})
    for item in (extras or []):
        if item.get("type") == "vendorSummary":
            rows.append({"name": item["name"], "sub": "", "total": item["balance"], "bold": True})
            for d in item.get("details", []):
                rows.append({"name": f"  {d.get('code', '')} - {d['name']}", "sub": d["balance"], "total": "", "bold": False})
        elif item.get("type") == "bankCash":
            rows.append({"name": f"  {item.get('code', '')} - {item['name']}", "sub": item["balance"], "total": "", "bold": False})
        elif item.get("type") == "plResult":
            rows.append({"name": "Profit & Loss A/c", "sub": "", "total": item["balance"], "bold": True})
            rows.append({"name": f"  {item['name']}", "sub": item["balance"], "total": "", "bold": False})
    return rows


def export_balance_sheet(params):
    fmt = params.get("format", "excel")
    data_resp, code = get_balance_sheet_report(params)
    if code != 200:
        return data_resp, code

    data = data_resp["data"]
    as_of = data.get("asOfDate", "")
    from_d = data.get("fromDate", "")
    project = data.get("projectCode", "All")
    period = f"{from_d} to {as_of}" if from_d else f"as at {as_of}"

    # Build extras for each side
    asset_extras = list(data.get("vendorAssets", []))
    for ba in data.get("bankAssets", []):
        asset_extras.append(ba)
    pl = data.get("plResult")
    if pl and pl.get("code") == "NET_LOSS":
        asset_extras.append(pl)

    liability_extras = list(data.get("vendorLiabilities", []))
    for bl in data.get("bankLiabilities", []):
        liability_extras.append(bl)
    if pl and pl.get("code") == "NET_PROFIT":
        liability_extras.append(pl)

    if fmt == "pdf":
        # T-format: Liabilities LEFT, Assets RIGHT (matching reference)
        liab_body = _bs_side_html(data.get("liabilityGroups", []), liability_extras)
        liab_body += f'<tr class="grand"><td>T o t a l</td><td class="r"></td><td class="r">{_fmt_num(data["totalLiabilities"])}</td></tr>'

        asset_body = _bs_side_html(data.get("assetGroups", []), asset_extras)
        asset_body += f'<tr class="grand"><td>T o t a l</td><td class="r"></td><td class="r">{_fmt_num(data["totalAssets"])}</td></tr>'

        html = f"""<html><head>{_PDF_CSS_TALLY}</head><body>
        {_company_header_html("Balance Sheet", period=period, project=project)}
        <table class="bs-wrap">
            <tbody><tr>
                <td class="left">
                    <table class="bs-side">
                        <thead><tr><th>L i a b i l i t i e s</th><th class="r" style="width:80px"></th><th class="r" style="width:95px">as at {as_of}</th></tr></thead>
                        <tbody>{liab_body}</tbody>
                    </table>
                </td>
                <td class="right">
                    <table class="bs-side">
                        <thead><tr><th>A s s e t s</th><th class="r" style="width:80px"></th><th class="r" style="width:95px">as at {as_of}</th></tr></thead>
                        <tbody>{asset_body}</tbody>
                    </table>
                </td>
            </tr></tbody>
        </table>
        <div class="footer">Page <pdf:pagenumber/></div>
        </body></html>"""
        return _render_pdf(html, "balance_sheet.pdf")

    # Excel — sequential layout
    headers = ["Particulars", "Amount", "Total"]
    excel_rows = []

    excel_rows.append(["LIABILITIES", "", ""])
    for r in _bs_side_rows(data.get("liabilityGroups", []), liability_extras):
        if r["bold"]:
            excel_rows.append([r["name"], "", r["total"]])
        else:
            excel_rows.append([r["name"], r["sub"], ""])
    excel_rows.append(["Total Liabilities", "", data["totalLiabilities"]])
    excel_rows.append(["", "", ""])

    excel_rows.append(["ASSETS", "", ""])
    for r in _bs_side_rows(data.get("assetGroups", []), asset_extras):
        if r["bold"]:
            excel_rows.append([r["name"], "", r["total"]])
        else:
            excel_rows.append([r["name"], r["sub"], ""])
    excel_rows.append(["Total Assets", "", data["totalAssets"]])

    diff = data.get("difference", 0)
    if abs(float(diff)) > 0.01:
        excel_rows.append(["", "", ""])
        excel_rows.append(["Difference (Assets - Liabilities)", "", diff])

    filters = {"Period": period, "Project": project}
    return _render_excel(headers, excel_rows, "balance_sheet.xlsx", "Balance Sheet", "Balance Sheet", filters)
