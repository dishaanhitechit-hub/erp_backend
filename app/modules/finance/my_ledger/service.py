from app.modules.finance.accounting.ledger_service import get_voucher_register
from app.models.project import Project
from app.response import res


def _entries_from_vouchers(vouchers):
    """
    Convert central voucher-register entries to the legacy my-ledger entry format
    and compute running balance + summary.
    """
    entries = []
    for v in vouchers:
        entries.append({
            "date":       v.get("date"),
            "docType":    v.get("sourceTypeLabel") or v.get("sourceType", ""),
            "docNo":      v.get("voucherNo", ""),
            "docId":      v.get("sourceId"),
            "vendorName": None,
            "particular": v.get("remarks") or v.get("voucherNo", ""),
            "debit":      v.get("totalDebit", 0.0),
            "credit":     v.get("totalCredit", 0.0),
        })

    balance = 0.0
    for e in entries:
        balance += e["debit"] - e["credit"]
        e["balance"]     = round(abs(balance), 2)
        e["balanceType"] = "Dr" if balance >= 0 else "Cr"

    total_debit  = round(sum(e["debit"]  for e in entries), 2)
    total_credit = round(sum(e["credit"] for e in entries), 2)
    closing      = round(total_debit - total_credit, 2)
    summary = {
        "totalDebit":     total_debit,
        "totalCredit":    total_credit,
        "closingBalance": round(abs(closing), 2),
        "balanceType":    "Dr" if closing >= 0 else "Cr",
    }
    return entries, summary


def get_my_ledger(data):
    project_code = data.get("projectCode") or None
    from_date    = data.get("fromDate")
    to_date      = data.get("toDate")

    if project_code:
        proj = Project.query.filter_by(project_code=project_code).first()

        result, status = get_voucher_register({
            "project_code": project_code,
            "from_date":    from_date,
            "to_date":      to_date,
        })
        if status != 200:
            return res("My ledger fetch failed", [], status)

        entries, summary = _entries_from_vouchers(result["data"]["entries"])

        return res("My ledger fetched", {
            "mode":        "project",
            "projectCode": project_code,
            "projectName": proj.project_name if proj else None,
            "clientName":  proj.client_name  if proj else None,
            "filters":     {"fromDate": from_date, "toDate": to_date},
            "summary":     summary,
            "entries":     entries,
        }, 200)

    # All-projects mode: single query, then group by project_code in Python
    result, status = get_voucher_register({
        "from_date": from_date,
        "to_date":   to_date,
    })
    if status != 200:
        return res("My ledger fetch failed", [], status)

    # Group vouchers by project_code
    by_project = {}
    for v in result["data"]["entries"]:
        pc = v.get("projectCode") or "__none__"
        by_project.setdefault(pc, []).append(v)

    projects   = Project.query.order_by(Project.project_code).all()
    all_debit  = 0.0
    all_credit = 0.0
    proj_blocks = []

    for proj in projects:
        pv = by_project.get(proj.project_code, [])
        if not pv:
            continue
        entries, summary = _entries_from_vouchers(pv)
        all_debit  += summary["totalDebit"]
        all_credit += summary["totalCredit"]
        proj_blocks.append({
            "projectCode": proj.project_code,
            "projectName": proj.project_name,
            "clientName":  proj.client_name,
            "summary":     summary,
            "entries":     entries,
        })

    closing = round(all_debit - all_credit, 2)
    return res("My ledger fetched", {
        "mode":    "all",
        "filters": {"fromDate": from_date, "toDate": to_date},
        "summary": {
            "totalDebit":     round(all_debit, 2),
            "totalCredit":    round(all_credit, 2),
            "closingBalance": round(abs(closing), 2),
            "balanceType":    "Dr" if closing >= 0 else "Cr",
        },
        "projects": proj_blocks,
    }, 200)
