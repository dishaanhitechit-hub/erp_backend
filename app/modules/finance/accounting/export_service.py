"""
PDF and Excel export for accounting reports.

Uses xhtml2pdf for PDF and openpyxl (via csv fallback) for Excel.
All exports use the same data as the screen reports.
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


def _fmt_num(val):
    """Format number Indian style."""
    if val is None:
        return ""
    n = float(val)
    if n == 0:
        return "—"
    return f"{n:,.2f}"


def _get_company_info():
    """Load company name from settings."""
    try:
        from app.models.companies import Company
        company = Company.query.first()
        if company:
            return {
                "name": company.company_name or "PRAX ERP",
                "address": getattr(company, "address", "") or "",
            }
    except Exception:
        pass
    return {"name": "PRAX ERP", "address": ""}


# ═══════════════════════════════════════════════════════════════════════════
# PDF GENERATION (xhtml2pdf)
# ═══════════════════════════════════════════════════════════════════════════

_PDF_CSS = """
<style>
    @page { size: A4 landscape; margin: 1cm; }
    body { font-family: Helvetica, Arial, sans-serif; font-size: 9px; color: #222; }
    .header { text-align: center; margin-bottom: 10px; }
    .header h1 { font-size: 14px; margin: 0; font-weight: bold; }
    .header h2 { font-size: 11px; margin: 2px 0; font-weight: bold; }
    .header .meta { font-size: 8px; color: #666; }
    table { width: 100%; border-collapse: collapse; margin-top: 8px; }
    th { background: #2c3e50; color: white; padding: 4px 6px; text-align: left; font-size: 8px; }
    td { padding: 3px 6px; border-bottom: 1px solid #ddd; font-size: 8px; }
    tr:nth-child(even) { background: #f9f9f9; }
    .num { text-align: right; }
    .total-row { font-weight: bold; background: #eee !important; border-top: 2px solid #333; }
    .group-header { font-weight: bold; background: #e8e8e8; }
    .footer { text-align: center; font-size: 7px; color: #999; margin-top: 10px; }
</style>
"""

_PDF_CSS_TALLY = """
<style>
    @page { size: A4; margin: 1.5cm; }
    body { font-family: 'Times New Roman', Times, serif; font-size: 10px; color: #000; }
    .header { text-align: center; margin-bottom: 12px; }
    .header h1 { font-size: 15px; margin: 0; font-weight: bold; }
    .header .addr { font-size: 9px; margin: 2px 0; }
    .header h2 { font-size: 13px; margin: 4px 0 2px; font-weight: bold; }
    .header .period { font-size: 9px; }
    table.ledger { width: 100%; border-collapse: collapse; margin-top: 6px; }
    table.ledger th { border-top: 1px solid #000; border-bottom: 1px solid #000; padding: 4px 6px; text-align: left; font-size: 9px; font-weight: bold; }
    table.ledger th.num { text-align: right; }
    table.ledger td { padding: 2px 6px; font-size: 9px; vertical-align: top; }
    table.ledger td.num { text-align: right; font-family: 'Courier New', monospace; font-size: 9px; }
    table.ledger tr.total td { border-top: 1px solid #000; font-weight: bold; }
    table.ledger tr.grand-total td { border-top: 2px solid #000; border-bottom: 2px solid #000; font-weight: bold; }
    table.ledger tr.group-row td { font-weight: bold; padding-top: 6px; }
    table.ledger tr.subgroup-row td { font-weight: bold; font-style: italic; }
    .indent1 { padding-left: 20px !important; }
    .indent2 { padding-left: 36px !important; }
    .indent3 { padding-left: 52px !important; }
    table.bs-layout { width: 100%; border-collapse: collapse; }
    table.bs-layout > tbody > tr > td { width: 50%; vertical-align: top; padding: 0; }
    table.bs-layout > tbody > tr > td:first-child { border-right: 1px solid #000; padding-right: 6px; }
    table.bs-layout > tbody > tr > td:last-child { padding-left: 6px; }
    table.bs-side { width: 100%; border-collapse: collapse; }
    table.bs-side th { border-bottom: 1px solid #000; padding: 3px 4px; font-size: 9px; font-weight: bold; }
    table.bs-side th.num { text-align: right; }
    table.bs-side td { padding: 2px 4px; font-size: 9px; vertical-align: top; }
    table.bs-side td.num { text-align: right; font-family: 'Courier New', monospace; }
    table.bs-side tr.group-row td { font-weight: bold; padding-top: 5px; }
    table.bs-side tr.total td { border-top: 1px solid #000; font-weight: bold; }
    table.bs-side tr.grand-total td { border-top: 2px solid #000; border-bottom: 2px solid #000; font-weight: bold; }
    .bs-indent1 { padding-left: 16px !important; }
    .bs-indent2 { padding-left: 28px !important; }
    .bs-indent3 { padding-left: 40px !important; }
    .footer { text-align: center; font-size: 7px; color: #999; margin-top: 10px; }
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


def _pdf_header(title, filters=None):
    company = _get_company_info()
    filter_str = ""
    if filters:
        filter_parts = [f"{k}: {v}" for k, v in filters.items() if v]
        filter_str = " | ".join(filter_parts)
    return f"""
    <div class="header">
        <h1>{company['name']}</h1>
        <h2>{title}</h2>
        <div class="meta">{filter_str}</div>
        <div class="meta">Generated: {datetime.now().strftime('%d-%b-%Y %H:%M')}</div>
    </div>
    """


def _tally_header(title, period="", project=""):
    company = _get_company_info()
    addr = company.get("address", "")
    period_line = f'<div class="period">{period}</div>' if period else ""
    proj_line = f'<div class="period">Project: {project}</div>' if project and project != "All" else ""
    return f"""
    <div class="header">
        <h1>{company['name']}</h1>
        {'<div class="addr">' + addr + '</div>' if addr else ''}
        <h2>{title}</h2>
        {period_line}
        {proj_line}
    </div>
    """


def _flatten_subgroups_html(subgroups, depth=1, css_prefix=""):
    """Recursively render subgroup tree rows for PDF."""
    html = ""
    indent_cls = f"{css_prefix}indent{min(depth, 3)}"
    for sg in subgroups:
        html += f'<tr class="subgroup-row"><td class="{indent_cls}">{sg["name"]}</td>'
        html += f'<td class="num"></td><td class="num">{_fmt_num(sg["total"])}</td></tr>'
        if sg.get("children"):
            html += _flatten_subgroups_html(sg["children"], depth + 1, css_prefix)
        for acc in sg.get("accounts", []):
            acc_indent = f"{css_prefix}indent{min(depth + 1, 3)}"
            html += f'<tr><td class="{acc_indent}">{acc["ccCode"]} - {acc["ccName"]}</td>'
            html += f'<td class="num">{_fmt_num(acc["net"])}</td><td class="num"></td></tr>'
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
# EXCEL GENERATION
# ═══════════════════════════════════════════════════════════════════════════

def _render_excel(headers, rows, filename, sheet_name="Sheet1", title=None, filters=None):
    """Generate Excel file. Try openpyxl, fall back to CSV."""
    try:
        import openpyxl
        from openpyxl.styles import Font, Alignment, PatternFill, Border, Side, numbers
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

    # Company header
    company = _get_company_info()
    ws.merge_cells(start_row=row_num, start_column=1, end_row=row_num, end_column=len(headers))
    cell = ws.cell(row=row_num, column=1, value=company["name"])
    cell.font = Font(size=14, bold=True)
    cell.alignment = Alignment(horizontal="center")
    row_num += 1

    # Report title
    if title:
        ws.merge_cells(start_row=row_num, start_column=1, end_row=row_num, end_column=len(headers))
        cell = ws.cell(row=row_num, column=1, value=title)
        cell.font = Font(size=12, bold=True)
        cell.alignment = Alignment(horizontal="center")
        row_num += 1

    # Filters
    if filters:
        filter_str = " | ".join(f"{k}: {v}" for k, v in filters.items() if v)
        ws.merge_cells(start_row=row_num, start_column=1, end_row=row_num, end_column=len(headers))
        ws.cell(row=row_num, column=1, value=filter_str).font = Font(size=9, italic=True)
        row_num += 1

    row_num += 1  # blank row

    # Column headers
    header_fill = PatternFill(start_color="2C3E50", end_color="2C3E50", fill_type="solid")
    header_font = Font(color="FFFFFF", bold=True, size=10)
    thin_border = Border(
        bottom=Side(style="thin"),
        top=Side(style="thin"),
        left=Side(style="thin"),
        right=Side(style="thin"),
    )

    for col_idx, header in enumerate(headers, start=1):
        cell = ws.cell(row=row_num, column=col_idx, value=header)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal="center")
        cell.border = thin_border
    row_num += 1

    # Data rows
    for row_data in rows:
        for col_idx, val in enumerate(row_data, start=1):
            cell = ws.cell(row=row_num, column=col_idx, value=val)
            if isinstance(val, (int, float, Decimal)):
                cell.number_format = "#,##0.00"
                cell.alignment = Alignment(horizontal="right")
            cell.border = thin_border
        row_num += 1

    # Freeze panes
    ws.freeze_panes = ws.cell(row=row_num - len(rows), column=1)

    # Auto-width
    for col_idx in range(1, len(headers) + 1):
        max_len = len(str(headers[col_idx - 1]))
        for row_data in rows[:50]:
            if col_idx - 1 < len(row_data):
                max_len = max(max_len, len(str(row_data[col_idx - 1] or "")))
        ws.column_dimensions[openpyxl.utils.get_column_letter(col_idx)].width = min(max_len + 4, 40)

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
# EXPORT FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════════

def _bal_suffix(val):
    """Format balance with Dr/Cr suffix like Tally."""
    if val is None or val == 0:
        return "—"
    n = float(val)
    return f"{abs(n):,.2f} {'Dr' if n > 0 else 'Cr'}"


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
        rows_html += f'<tr class="total"><td colspan="4">Opening Balance</td>'
        rows_html += f'<td class="num"></td><td class="num"></td><td class="num">{_bal_suffix(ob)}</td></tr>'

        for e in entries:
            by_to = "By" if e.get("debit") else "To"
            part = e.get("particulars") or e.get("sourceTypeLabel", "")
            rows_html += f"""
            <tr>
                <td>{e['date']}</td>
                <td>{by_to}</td>
                <td><b>{part}</b></td>
                <td>{e.get('sourceTypeLabel', '')}</td>
                <td>{e.get('voucherNo', '')}</td>
                <td class="num">{_fmt_num(e['debit']) if e.get('debit') else ''}</td>
                <td class="num">{_fmt_num(e['credit']) if e.get('credit') else ''}</td>
                <td class="num">{_bal_suffix(e.get('balance', 0))}</td>
            </tr>
            """

        rows_html += f'<tr class="total"><td colspan="5">Closing Balance</td>'
        rows_html += f'<td class="num"></td><td class="num"></td><td class="num">{_bal_suffix(data.get("closingBalance", 0))}</td></tr>'
        rows_html += f'<tr class="grand-total"><td colspan="5"></td>'
        rows_html += f'<td class="num">{_fmt_num(data["totalDebit"])}</td>'
        rows_html += f'<td class="num">{_fmt_num(data["totalCredit"])}</td>'
        rows_html += f'<td class="num">{_fmt_num(data["totalDebit"])}</td></tr>'

        html = f"""
        <html><head>{_PDF_CSS_TALLY}</head><body>
        {_tally_header("Ledger Account", period, project)}
        <div style="text-align:center;font-size:11px;font-weight:bold;margin-bottom:6px;">{account_name}</div>
        <table class="ledger">
            <thead>
                <tr><th>Date</th><th></th><th>Particulars</th><th>Vch Type</th><th>Vch No.</th><th class="num">Debit</th><th class="num">Credit</th><th class="num">Balance</th></tr>
            </thead>
            <tbody>{rows_html}</tbody>
        </table>
        <div class="footer">Page <pdf:pagenumber/></div>
        </body></html>
        """
        return _render_pdf(html, "general_ledger.pdf")

    # Excel
    headers = ["Date", "Particulars", "Vch Type", "Vch No", "Debit", "Credit", "Balance"]
    rows = [["", "Opening Balance", "", "", "", "", _bal_suffix(data.get("openingBalance", 0))]]
    for e in entries:
        rows.append([
            e["date"],
            e.get("particulars") or e.get("sourceTypeLabel", ""),
            e.get("sourceTypeLabel", ""),
            e.get("voucherNo", ""),
            e["debit"] or "",
            e["credit"] or "",
            _bal_suffix(e.get("balance", 0)),
        ])
    rows.append(["", "Closing Balance", "", "", data["totalDebit"], data["totalCredit"], _bal_suffix(data.get("closingBalance", 0))])

    filters = {"Account": account_name, "Period": period, "Project": project}
    return _render_excel(headers, rows, "general_ledger.xlsx", "Ledger", "Ledger Account", filters)


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
            head = r.get("headUnder", "")
            rows_html += f"""
            <tr>
                <td>{r.get('accountType', '')}</td>
                <td>{r['accountName']}</td>
                <td>{r.get('groupName', '') or ''}</td>
                <td>{head}</td>
                <td class="num">{_fmt_num(r['closingDebit']) if r.get('closingDebit') else ''}</td>
                <td class="num">{_fmt_num(r['closingCredit']) if r.get('closingCredit') else ''}</td>
            </tr>
            """
        rows_html += f"""
        <tr class="grand-total">
            <td colspan="4">Grand Total</td>
            <td class="num">{_fmt_num(data.get('grandTotalDebit', 0))}</td>
            <td class="num">{_fmt_num(data.get('grandTotalCredit', 0))}</td>
        </tr>
        """

        html = f"""
        <html><head>{_PDF_CSS_TALLY}</head><body>
        {_tally_header("Trial Balance", period, project)}
        <table class="ledger">
            <thead>
                <tr><th>Type</th><th>Account Name</th><th>Group</th><th>Head Under</th><th class="num">Debit</th><th class="num">Credit</th></tr>
            </thead>
            <tbody>{rows_html}</tbody>
        </table>
        <div class="footer">Page <pdf:pagenumber/></div>
        </body></html>
        """
        return _render_pdf(html, "trial_balance.pdf")

    headers = ["Type", "Account Name", "Group", "Head Under", "Debit", "Credit"]
    rows = [[r.get("accountType", ""), r["accountName"], r.get("groupName", ""), r.get("headUnder", ""), r.get("closingDebit", ""), r.get("closingCredit", "")] for r in rows_data]
    rows.append(["", "Grand Total", "", "", data.get("grandTotalDebit", 0), data.get("grandTotalCredit", 0)])

    filters = {"Period": period, "Project": project}
    return _render_excel(headers, rows, "trial_balance.xlsx", "Trial Balance", "Trial Balance", filters)


def _render_pl_section_html(section_name, groups):
    """Render a P&L section (Income or Expense) as HTML table rows."""
    html = f'<tr class="group-row"><td colspan="3"><b>{section_name}</b></td></tr>'
    for grp in groups:
        html += f'<tr class="group-row"><td class="indent1">{grp["groupName"]}</td>'
        html += f'<td class="num"></td><td class="num">{_fmt_num(grp["total"])}</td></tr>'
        if grp.get("subGroups"):
            html += _flatten_subgroups_html(grp["subGroups"], depth=2)
        for acc in grp.get("accounts", []):
            html += f'<tr><td class="indent2">{acc["ccCode"]} - {acc["ccName"]}</td>'
            html += f'<td class="num">{_fmt_num(acc["net"])}</td><td class="num"></td></tr>'
    return html


def _render_pl_section_rows(section_name, groups):
    """Flatten a P&L section (Income or Expense) for Excel."""
    rows = []
    rows.append({"name": section_name, "amount": "", "is_header": True})
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
        rows_html = _render_pl_section_html("INCOME", data.get("income", []))
        rows_html += f'<tr class="total"><td>Total Income</td><td class="num"></td><td class="num">{_fmt_num(data["totalIncome"])}</td></tr>'
        rows_html += '<tr><td colspan="3">&nbsp;</td></tr>'
        rows_html += _render_pl_section_html("EXPENSE", data.get("expense", []))
        rows_html += f'<tr class="total"><td>Total Expense</td><td class="num"></td><td class="num">{_fmt_num(data["totalExpense"])}</td></tr>'
        rows_html += '<tr><td colspan="3">&nbsp;</td></tr>'
        net = data["netProfit"]
        label = "Net Profit" if net >= 0 else "Net Loss"
        rows_html += f'<tr class="grand-total"><td>{label}</td><td class="num"></td><td class="num">{_fmt_num(abs(net))}</td></tr>'

        html = f"""
        <html><head>{_PDF_CSS_TALLY}</head><body>
        {_tally_header("Profit &amp; Loss Statement", period, project)}
        <table class="ledger">
            <thead><tr><th>Particulars</th><th class="num">Amount</th><th class="num">Total</th></tr></thead>
            <tbody>{rows_html}</tbody>
        </table>
        <div class="footer">Page <pdf:pagenumber/></div>
        </body></html>
        """
        return _render_pdf(html, "profit_loss.pdf")

    # Excel — with tree nesting
    headers = ["Particulars", "Amount", "Total"]
    excel_rows = []
    for r in _render_pl_section_rows("INCOME", data.get("income", [])):
        if r.get("is_header"):
            excel_rows.append([r["name"], "", ""])
        elif r.get("is_group"):
            excel_rows.append([r["name"], "", r["amount"]])
        else:
            excel_rows.append([r["name"], r["amount"], ""])
    excel_rows.append(["Total Income", "", data["totalIncome"]])
    excel_rows.append(["", "", ""])
    for r in _render_pl_section_rows("EXPENSE", data.get("expense", [])):
        if r.get("is_header"):
            excel_rows.append([r["name"], "", ""])
        elif r.get("is_group"):
            excel_rows.append([r["name"], "", r["amount"]])
        else:
            excel_rows.append([r["name"], r["amount"], ""])
    excel_rows.append(["Total Expense", "", data["totalExpense"]])
    excel_rows.append(["", "", ""])
    net = data["netProfit"]
    label = "Net Profit" if net >= 0 else "Net Loss"
    excel_rows.append([label, "", abs(net)])

    filters = {"Period": period, "Project": project}
    return _render_excel(headers, excel_rows, "profit_loss.xlsx", "P&L", "Profit & Loss Statement", filters)


def _render_bs_side_html(groups, extra_items=None):
    """Render one side (Assets or Liabilities) of the BS as table rows."""
    html = ""
    for grp in groups:
        html += f'<tr class="group-row"><td><b>{grp["groupName"]}</b></td><td class="num"></td><td class="num">{_fmt_num(grp["total"])}</td></tr>'
        if grp.get("subGroups"):
            html += _flatten_subgroups_html(grp["subGroups"], depth=1, css_prefix="bs-")
        for acc in grp.get("accounts", []):
            html += f'<tr><td class="bs-indent1">{acc["ccCode"]} - {acc["ccName"]}</td>'
            html += f'<td class="num">{_fmt_num(acc["net"])}</td><td class="num"></td></tr>'
    for item in (extra_items or []):
        if item.get("type") == "vendorSummary":
            html += f'<tr class="group-row"><td><b>{item["name"]}</b></td><td class="num"></td><td class="num">{_fmt_num(item["balance"])}</td></tr>'
            for d in item.get("details", []):
                html += f'<tr><td class="bs-indent1">{d.get("code", "")} - {d["name"]}</td>'
                html += f'<td class="num">{_fmt_num(d["balance"])}</td><td class="num"></td></tr>'
        elif item.get("type") == "bankCash":
            html += f'<tr><td class="bs-indent1">{item.get("code", "")} - {item["name"]}</td>'
            html += f'<td class="num">{_fmt_num(item["balance"])}</td><td class="num"></td></tr>'
        elif item.get("type") == "plResult":
            html += f'<tr class="group-row"><td><b>{item["name"]}</b></td><td class="num"></td><td class="num">{_fmt_num(item["balance"])}</td></tr>'
    return html


def _flatten_bs_side_rows(groups, extra_items=None):
    """Flatten one BS side for Excel."""
    rows = []
    for grp in groups:
        rows.append({"name": grp["groupName"], "sub": "", "total": grp["total"], "is_group": True})
        if grp.get("subGroups"):
            for sr in _flatten_subgroups_rows(grp["subGroups"], depth=1):
                rows.append({"name": sr["name"], "sub": sr["amount"] if not sr["is_group"] else "", "total": sr["amount"] if sr["is_group"] else "", "is_group": sr["is_group"]})
        for acc in grp.get("accounts", []):
            rows.append({"name": f"  {acc['ccCode']} - {acc['ccName']}", "sub": acc["net"], "total": "", "is_group": False})
    for item in (extra_items or []):
        if item.get("type") == "vendorSummary":
            rows.append({"name": item["name"], "sub": "", "total": item["balance"], "is_group": True})
            for d in item.get("details", []):
                rows.append({"name": f"  {d.get('code', '')} - {d['name']}", "sub": d["balance"], "total": "", "is_group": False})
        elif item.get("type") == "bankCash":
            rows.append({"name": f"  {item.get('code', '')} - {item['name']}", "sub": item["balance"], "total": "", "is_group": False})
        elif item.get("type") == "plResult":
            rows.append({"name": item["name"], "sub": "", "total": item["balance"], "is_group": True})
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

    # Collect extras for each side
    asset_extras = []
    for va in data.get("vendorAssets", []):
        asset_extras.append(va)
    for ba in data.get("bankAssets", []):
        asset_extras.append(ba)
    pl = data.get("plResult")
    if pl and pl.get("code") == "NET_LOSS":
        asset_extras.append(pl)

    liability_extras = []
    for vl in data.get("vendorLiabilities", []):
        liability_extras.append(vl)
    for bl in data.get("bankLiabilities", []):
        liability_extras.append(bl)
    if pl and pl.get("code") == "NET_PROFIT":
        liability_extras.append(pl)

    if fmt == "pdf":
        # T-format: Liabilities on left, Assets on right (like the reference)
        liab_html = _render_bs_side_html(data.get("liabilityGroups", []), liability_extras)
        liab_html += f'<tr class="grand-total"><td>Total</td><td class="num"></td><td class="num">{_fmt_num(data["totalLiabilities"])}</td></tr>'

        asset_html = _render_bs_side_html(data.get("assetGroups", []), asset_extras)
        asset_html += f'<tr class="grand-total"><td>Total</td><td class="num"></td><td class="num">{_fmt_num(data["totalAssets"])}</td></tr>'

        html = f"""
        <html><head>{_PDF_CSS_TALLY}</head><body>
        {_tally_header("Balance Sheet", period, project)}
        <table class="bs-layout">
            <thead>
                <tr>
                    <td>
                        <table class="bs-side">
                            <thead><tr><th>Liabilities</th><th class="num" style="width:90px">Amount</th><th class="num" style="width:100px">as at {as_of}</th></tr></thead>
                            <tbody>{liab_html}</tbody>
                        </table>
                    </td>
                    <td>
                        <table class="bs-side">
                            <thead><tr><th>Assets</th><th class="num" style="width:90px">Amount</th><th class="num" style="width:100px">as at {as_of}</th></tr></thead>
                            <tbody>{asset_html}</tbody>
                        </table>
                    </td>
                </tr>
            </thead>
        </table>
        <div class="footer">Page <pdf:pagenumber/></div>
        </body></html>
        """
        return _render_pdf(html, "balance_sheet.pdf")

    # Excel — two-column layout is hard, so use sequential with clear sections
    headers = ["Particulars", "Amount", "Total"]
    excel_rows = []

    excel_rows.append(["LIABILITIES", "", ""])
    for r in _flatten_bs_side_rows(data.get("liabilityGroups", []), liability_extras):
        if r["is_group"]:
            excel_rows.append([r["name"], "", r["total"]])
        else:
            excel_rows.append([r["name"], r["sub"], ""])
    excel_rows.append(["Total Liabilities", "", data["totalLiabilities"]])
    excel_rows.append(["", "", ""])

    excel_rows.append(["ASSETS", "", ""])
    for r in _flatten_bs_side_rows(data.get("assetGroups", []), asset_extras):
        if r["is_group"]:
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
