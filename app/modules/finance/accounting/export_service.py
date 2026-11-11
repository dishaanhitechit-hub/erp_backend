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
    .header h1 { font-size: 14px; margin: 0; }
    .header h2 { font-size: 11px; margin: 2px 0; font-weight: normal; }
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

def export_general_ledger(params):
    fmt = params.get("format", "excel")
    data_resp, code = get_general_ledger(params)
    if code != 200:
        return data_resp, code

    data = data_resp["data"]
    entries = data["entries"]

    filters = {
        "Account": data.get("accountName", ""),
        "From": data.get("fromDate", ""),
        "To": data.get("toDate", ""),
        "Project": data.get("projectCode", "All"),
    }

    if fmt == "pdf":
        rows_html = ""
        # Opening balance row
        rows_html += f"""
        <tr class="total-row">
            <td colspan="4">Opening Balance</td>
            <td class="num">{_fmt_num(data['openingBalance']) if data['openingBalance'] > 0 else ''}</td>
            <td class="num">{_fmt_num(abs(data['openingBalance'])) if data['openingBalance'] < 0 else ''}</td>
            <td class="num">{_fmt_num(data['openingBalance'])}</td>
        </tr>
        """
        for e in entries:
            rows_html += f"""
            <tr>
                <td>{e['date']}</td>
                <td>{e['sourceTypeLabel']}</td>
                <td>{e['voucherNo']}</td>
                <td>{e['narration'][:60]}</td>
                <td class="num">{_fmt_num(e['debit']) if e['debit'] else ''}</td>
                <td class="num">{_fmt_num(e['credit']) if e['credit'] else ''}</td>
                <td class="num">{_fmt_num(e['balance'])}</td>
            </tr>
            """
        # Closing
        rows_html += f"""
        <tr class="total-row">
            <td colspan="4">Closing Balance</td>
            <td class="num">{_fmt_num(data['totalDebit'])}</td>
            <td class="num">{_fmt_num(data['totalCredit'])}</td>
            <td class="num">{_fmt_num(data['closingBalance'])}</td>
        </tr>
        """

        html = f"""
        <html><head>{_PDF_CSS}</head><body>
        {_pdf_header("General Ledger", filters)}
        <table>
            <thead>
                <tr><th>Date</th><th>Type</th><th>Voucher No</th><th>Narration</th><th class="num">Debit</th><th class="num">Credit</th><th class="num">Balance</th></tr>
            </thead>
            <tbody>{rows_html}</tbody>
        </table>
        <div class="footer">Page <pdf:pagenumber/></div>
        </body></html>
        """
        return _render_pdf(html, "general_ledger.pdf")

    # Excel
    headers = ["Date", "Type", "Voucher No", "Narration", "Debit", "Credit", "Balance"]
    rows = [["", "", "", "Opening Balance", data["openingBalance"] if data["openingBalance"] > 0 else "", abs(data["openingBalance"]) if data["openingBalance"] < 0 else "", data["openingBalance"]]]
    for e in entries:
        rows.append([e["date"], e["sourceTypeLabel"], e["voucherNo"], e["narration"][:60], e["debit"] or "", e["credit"] or "", e["balance"]])
    rows.append(["", "", "", "Closing Balance", data["totalDebit"], data["totalCredit"], data["closingBalance"]])
    return _render_excel(headers, rows, "general_ledger.xlsx", "Ledger", "General Ledger", filters)


def export_trial_balance(params):
    fmt = params.get("format", "excel")
    data_resp, code = get_trial_balance(params)
    if code != 200:
        return data_resp, code

    data = data_resp["data"]
    rows_data = data["rows"]

    filters = {
        "From": data.get("fromDate", ""),
        "To": data.get("toDate", ""),
        "Project": data.get("projectCode", "All"),
    }

    if fmt == "pdf":
        rows_html = ""
        for r in rows_data:
            rows_html += f"""
            <tr>
                <td>{r['accountName']}</td>
                <td>{r['groupName'] or ''}</td>
                <td class="num">{_fmt_num(r['debit'])}</td>
                <td class="num">{_fmt_num(r['credit'])}</td>
                <td class="num">{_fmt_num(r['closingDebit']) if r['closingDebit'] else ''}</td>
                <td class="num">{_fmt_num(r['closingCredit']) if r['closingCredit'] else ''}</td>
            </tr>
            """
        rows_html += f"""
        <tr class="total-row">
            <td colspan="2">Grand Total</td>
            <td class="num">{_fmt_num(data['grandTotalDebit'])}</td>
            <td class="num">{_fmt_num(data['grandTotalCredit'])}</td>
            <td colspan="2"></td>
        </tr>
        """

        html = f"""
        <html><head>{_PDF_CSS}</head><body>
        {_pdf_header("Trial Balance", filters)}
        <table>
            <thead>
                <tr><th>Account</th><th>Group</th><th class="num">Debit</th><th class="num">Credit</th><th class="num">Closing Dr</th><th class="num">Closing Cr</th></tr>
            </thead>
            <tbody>{rows_html}</tbody>
        </table>
        <div class="footer">Page <pdf:pagenumber/></div>
        </body></html>
        """
        return _render_pdf(html, "trial_balance.pdf")

    headers = ["Account", "Group", "Debit", "Credit", "Closing Dr", "Closing Cr"]
    rows = [[r["accountName"], r.get("groupName", ""), r["debit"], r["credit"], r["closingDebit"], r["closingCredit"]] for r in rows_data]
    rows.append(["Grand Total", "", data["grandTotalDebit"], data["grandTotalCredit"], "", ""])
    return _render_excel(headers, rows, "trial_balance.xlsx", "Trial Balance", "Trial Balance", filters)


def export_profit_loss(params):
    fmt = params.get("format", "excel")
    data_resp, code = get_profit_loss(params)
    if code != 200:
        return data_resp, code

    data = data_resp["data"]
    filters = {
        "From": data.get("fromDate", ""),
        "To": data.get("toDate", ""),
        "Project": data.get("projectCode", "All"),
    }

    if fmt == "pdf":
        rows_html = ""
        rows_html += '<tr class="group-header"><td colspan="3">INCOME</td></tr>'
        for grp in data["income"]:
            rows_html += f'<tr class="group-header"><td colspan="2">{grp["group"]}</td><td class="num">{_fmt_num(grp["total"])}</td></tr>'
            for a in grp["accounts"]:
                rows_html += f'<tr><td style="padding-left:20px">{a["ccCode"]} - {a["ccName"]}</td><td></td><td class="num">{_fmt_num(a["net"])}</td></tr>'

        rows_html += f'<tr class="total-row"><td colspan="2">Total Income</td><td class="num">{_fmt_num(data["totalIncome"])}</td></tr>'

        rows_html += '<tr class="group-header"><td colspan="3">EXPENSE</td></tr>'
        for grp in data["expense"]:
            rows_html += f'<tr class="group-header"><td colspan="2">{grp["group"]}</td><td class="num">{_fmt_num(grp["total"])}</td></tr>'
            for a in grp["accounts"]:
                rows_html += f'<tr><td style="padding-left:20px">{a["ccCode"]} - {a["ccName"]}</td><td></td><td class="num">{_fmt_num(a["net"])}</td></tr>'

        rows_html += f'<tr class="total-row"><td colspan="2">Total Expense</td><td class="num">{_fmt_num(data["totalExpense"])}</td></tr>'
        rows_html += f'<tr class="total-row"><td colspan="2">Net Profit / (Loss)</td><td class="num">{_fmt_num(data["netProfit"])}</td></tr>'

        html = f"""
        <html><head>{_PDF_CSS}</head><body>
        {_pdf_header("Profit & Loss Statement", filters)}
        <table>
            <thead><tr><th>Particulars</th><th>Group</th><th class="num">Amount</th></tr></thead>
            <tbody>{rows_html}</tbody>
        </table>
        <div class="footer">Page <pdf:pagenumber/></div>
        </body></html>
        """
        return _render_pdf(html, "profit_loss.pdf")

    # Excel
    headers = ["Particulars", "Group", "Amount"]
    rows = []
    rows.append(["INCOME", "", ""])
    for grp in data["income"]:
        rows.append([grp["group"], "", grp["total"]])
        for a in grp["accounts"]:
            rows.append([f"  {a['ccCode']} - {a['ccName']}", "", a["net"]])
    rows.append(["Total Income", "", data["totalIncome"]])
    rows.append(["", "", ""])
    rows.append(["EXPENSE", "", ""])
    for grp in data["expense"]:
        rows.append([grp["group"], "", grp["total"]])
        for a in grp["accounts"]:
            rows.append([f"  {a['ccCode']} - {a['ccName']}", "", a["net"]])
    rows.append(["Total Expense", "", data["totalExpense"]])
    rows.append(["", "", ""])
    rows.append(["Net Profit / (Loss)", "", data["netProfit"]])
    return _render_excel(headers, rows, "profit_loss.xlsx", "P&L", "Profit & Loss Statement", filters)


def export_balance_sheet(params):
    fmt = params.get("format", "excel")
    data_resp, code = get_balance_sheet_report(params)
    if code != 200:
        return data_resp, code

    data = data_resp["data"]
    filters = {
        "As of": data.get("asOfDate", ""),
        "Project": data.get("projectCode", "All"),
    }

    if fmt == "pdf":
        rows_html = ""
        rows_html += '<tr class="group-header"><td colspan="2">ASSETS</td></tr>'
        for a in data["assets"]:
            name = a.get("name", a.get("code", ""))
            rows_html += f'<tr><td>{name}</td><td class="num">{_fmt_num(a["balance"])}</td></tr>'
        rows_html += f'<tr class="total-row"><td>Total Assets</td><td class="num">{_fmt_num(data["totalAssets"])}</td></tr>'

        rows_html += '<tr class="group-header"><td colspan="2">LIABILITIES & EQUITY</td></tr>'
        for l in data["liabilities"]:
            name = l.get("name", l.get("code", ""))
            rows_html += f'<tr><td>{name}</td><td class="num">{_fmt_num(l["balance"])}</td></tr>'
        rows_html += f'<tr class="total-row"><td>Total Liabilities</td><td class="num">{_fmt_num(data["totalLiabilities"])}</td></tr>'

        diff = data.get("difference", 0)
        if abs(diff) > 0.01:
            rows_html += f'<tr class="total-row"><td>Difference (Assets - Liabilities)</td><td class="num">{_fmt_num(diff)}</td></tr>'

        html = f"""
        <html><head>{_PDF_CSS}</head><body>
        {_pdf_header("Balance Sheet", filters)}
        <table>
            <thead><tr><th>Particulars</th><th class="num">Amount</th></tr></thead>
            <tbody>{rows_html}</tbody>
        </table>
        <div class="footer">Page <pdf:pagenumber/></div>
        </body></html>
        """
        return _render_pdf(html, "balance_sheet.pdf")

    headers = ["Particulars", "Amount"]
    rows = []
    rows.append(["ASSETS", ""])
    for a in data["assets"]:
        rows.append([a.get("name", a.get("code", "")), a["balance"]])
    rows.append(["Total Assets", data["totalAssets"]])
    rows.append(["", ""])
    rows.append(["LIABILITIES & EQUITY", ""])
    for l in data["liabilities"]:
        rows.append([l.get("name", l.get("code", "")), l["balance"]])
    rows.append(["Total Liabilities", data["totalLiabilities"]])
    diff = data.get("difference", 0)
    if abs(diff) > 0.01:
        rows.append(["Difference", diff])
    return _render_excel(headers, rows, "balance_sheet.xlsx", "Balance Sheet", "Balance Sheet", filters)
