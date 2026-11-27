from app.modules.finance.accounting.ledger_service import get_vendor_ledger_central
from app.models.vendor import Vendor
from app.response import res


def _central_to_legacy(central_data):
    """
    Transform central ledger response format to legacy vendor ledger format
    so the existing frontend contract is preserved.
    """
    entries = []
    for e in central_data.get("entries", []):
        central_balance = e.get("balance", 0.0)
        entries.append({
            "date":        e.get("date"),
            "docType":     e.get("sourceTypeLabel") or e.get("sourceType", ""),
            "docNo":       e.get("voucherNo", ""),
            "docId":       e.get("sourceId"),
            "projectCode": e.get("projectCode"),
            "particular":  e.get("particulars") or e.get("narration") or e.get("voucherNo", ""),
            "debit":       e["debit"],
            "credit":      e["credit"],
            "balance":     abs(central_balance),
            # central running = Dr - Cr; negative means more Cr (we owe vendor) → "Cr"
            "balanceType": "Cr" if central_balance < 0 else "Dr",
        })

    total_debit  = round(sum(e["debit"]  for e in entries), 2)
    total_credit = round(sum(e["credit"] for e in entries), 2)
    closing      = round(total_credit - total_debit, 2)

    summary = {
        "totalDebit":     total_debit,
        "totalCredit":    total_credit,
        "closingBalance": round(abs(closing), 2),
        "balanceType":    "Cr" if closing >= 0 else "Dr",
    }
    return summary, entries


def get_vendor_ledger(data):
    vendor_id    = data.get("vendorId")
    project_code = data.get("projectCode") or None
    from_date    = data.get("fromDate")
    to_date      = data.get("toDate")

    if not vendor_id:
        return res("vendorId required", [], 400)

    vendor = Vendor.query.get(int(vendor_id))
    if not vendor:
        return res("Vendor not found", [], 404)

    result, status = get_vendor_ledger_central({
        "vendor_id":    vendor_id,
        "project_code": project_code,
        "from_date":    from_date,
        "to_date":      to_date,
    })
    if status != 200:
        return res(result.get("message", "Ledger error"), [], status)

    summary, entries = _central_to_legacy(result["data"])

    return res("Vendor ledger fetched", {
        "vendor":  {
            "id":         vendor.id,
            "ledgerCode": vendor.ledger_code,
            "ledgerName": vendor.ledger_name,
            "gstin":      vendor.gstin,
        },
        "filters": {
            "projectCode": project_code,
            "fromDate":    from_date,
            "toDate":      to_date,
        },
        "summary": summary,
        "entries": entries,
    }, 200)


def get_vendor_ledger_by_uuid(vendor_uuid, data):
    vendor = Vendor.query.filter_by(vendor_uuid=vendor_uuid).first()
    if not vendor:
        return res("Vendor not found", [], 404)

    project_code = data.get("projectCode") or None
    from_date    = data.get("fromDate")
    to_date      = data.get("toDate")

    result, status = get_vendor_ledger_central({
        "vendor_id":    vendor.id,
        "project_code": project_code,
        "from_date":    from_date,
        "to_date":      to_date,
    })
    if status != 200:
        return res(result.get("message", "Ledger error"), [], status)

    summary, entries = _central_to_legacy(result["data"])

    return res("Vendor ledger fetched", {
        "vendor":  {
            "id":         vendor.id,
            "ledgerCode": vendor.ledger_code,
            "ledgerName": vendor.ledger_name,
            "gstin":      vendor.gstin,
        },
        "filters": {
            "projectCode": project_code,
            "fromDate":    from_date,
            "toDate":      to_date,
        },
        "summary": summary,
        "entries": entries,
    }, 200)
