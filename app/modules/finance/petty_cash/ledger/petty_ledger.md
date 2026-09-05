# Petty Cash Ledger API

## Overview

A **read-only reporting API** that provides a ledger-style view of Petty Cash activity per project. It is budget-centric — each budget acts as a parent, and all docket vouchers created under that budget are shown as child transactions. Includes CC-wise used/remaining breakdown, approval histories for both budgets and vouchers, and voucher-status summary counts.

No new database tables. No migrations required. Reads from existing `petty_cash_budget`, `petty_cash_budget_detail`, `petty_cash_budget_revision`, `petty_cash_docket_voucher`, and `petty_cash_docket_voucher_detail` tables.

---

## Base URL

```
/finance/petty-cash/ledger
```

All endpoints require `@login_required`.

---

## Endpoints

| # | Method | Endpoint | Description |
|---|---|---|---|
| 1 | GET | `/list` | Budget summary cards for a project |
| 2 | GET | `/budget/<budget_id>` | Full ledger detail for one budget |

---

## Endpoint 1 — Budget List

**GET** `/finance/petty-cash/ledger/list`

### Query Parameters

| Parameter | Required | Description |
|---|---|---|
| `projectCode` | ✅ Yes | Project to fetch budgets for |
| `workflowStatus` | No | Filter by budget status (e.g. `Approved`) |
| `fromDate` | No | Filter budgets whose `from_date >= value` |
| `toDate` | No | Filter budgets whose `to_date <= value` |

### Response

```json
{
  "message": "Petty cash ledger list fetched",
  "data": {
    "list": [
      {
        "id": 1,
        "budgetNo": "PCB00001",
        "budgetDate": "2026-09-01",
        "budgetFrequency": "Monthly",
        "fromDate": "2026-09-01",
        "toDate": "2026-09-30",
        "totalBudgetAmount": 75000.0,
        "totalUsed": 18000.0,
        "totalRemaining": 57000.0,
        "voucherCount": 2,
        "workflowStatus": "Approved",
        "createdBy": "ankandas",
        "createdAt": "2026-09-01 09:00"
      }
    ]
  }
}
```

### Field Descriptions

| Field | Description |
|---|---|
| `totalBudgetAmount` | Original approved budget total |
| `totalUsed` | Sum of all docket voucher amounts under this budget (excludes Draft & Rejected vouchers) |
| `totalRemaining` | `totalBudgetAmount - totalUsed` |
| `voucherCount` | Total docket vouchers created under this budget (all statuses) |

---

## Endpoint 2 — Full Budget Ledger

**GET** `/finance/petty-cash/ledger/budget/<budget_id>`

Returns the complete ledger for one budget: budget info, CC-wise breakdown, all linked vouchers with their detail rows and approval histories, and an overall summary.

### Response Structure

```json
{
  "message": "Petty cash ledger fetched",
  "data": {
    "budget": { ... },
    "ccSummary": [ ... ],
    "vouchers": [ ... ],
    "summary": { ... }
  }
}
```

---

### `budget` block

```json
{
  "id": 1,
  "budgetNo": "PCB00001",
  "budgetDate": "2026-09-01",
  "budgetFrequency": "Monthly",
  "fromDate": "2026-09-01",
  "toDate": "2026-09-30",
  "attachment": "https://cdn.example.com/petty_cash/budget/file.pdf",
  "projectCode": "PC0001",
  "totalBudgetAmount": 75000.0,
  "workflowStatus": "Approved",
  "currentLevel": 1,
  "createdBy": "ankandas",
  "createdAt": "2026-09-01 09:00",
  "submittedBy": "ankandas",
  "submittedAt": "2026-09-01 09:05",
  "approvedBy": "manager1",
  "finalApprovedAt": "2026-09-01 10:00",
  "rejectedBy": null,
  "rejectedAt": null,
  "approvalHistory": [
    { "id": 1, "action": "SUBMIT",        "level": 0, "comments": null,           "actionBy": "ankandas", "createdAt": "2026-09-01 09:05:00" },
    { "id": 2, "action": "FINAL_APPROVE", "level": 1, "comments": "Looks good",   "actionBy": "manager1", "createdAt": "2026-09-01 10:00:00" }
  ],
  "revisionHistory": [
    { "id": 1, "ccName": "Fuel", "oldAmount": 20000.0, "newAmount": 25000.0, "remark": "Price hike", "revisedBy": "manager1", "revisedAt": "2026-09-03 11:00:00" }
  ]
}
```

---

### `ccSummary` block

CC-wise budget vs used vs remaining. `usedAmount` sums only vouchers that are **not** Draft or Rejected.

```json
[
  {
    "budgetDetailId": 1,
    "slNo": 1,
    "ccCode": "CC001",
    "ccName": "Site Labour",
    "shortDescription": "Daily wage payments",
    "budgetAmount": 50000.0,
    "usedAmount": 18000.0,
    "remaining": 32000.0
  },
  {
    "budgetDetailId": 2,
    "slNo": 2,
    "ccCode": "CC002",
    "ccName": "Fuel",
    "shortDescription": "Diesel for machinery",
    "budgetAmount": 25000.0,
    "usedAmount": 0.0,
    "remaining": 25000.0
  }
]
```

> **Note:** `usedAmount` is accurate only for voucher detail rows that have `budgetDetailId` set (i.e. vouchers created after the tracking feature was added). Older rows without `budgetDetailId` are excluded from the used sum.

---

### `vouchers` block

All docket vouchers linked to this budget (all statuses), ordered oldest first.

```json
[
  {
    "id": 1,
    "voucherNo": "DV00001",
    "voucherDate": "2026-09-04",
    "expensesBy": "Rajan Kumar",
    "modeOfPayment": "Cash",
    "fundSource": "Project Fund",
    "paymentRefId": null,
    "attachment": null,
    "totalAmount": 18000.0,
    "workflowStatus": "Approved",
    "createdBy": "ankandas",
    "createdAt": "2026-09-04 10:00",
    "submittedBy": "ankandas",
    "submittedAt": "2026-09-04 10:05",
    "approvedBy": "manager1",
    "finalApprovedAt": "2026-09-04 11:00",
    "approvalHistory": [
      { "id": 5, "action": "SUBMIT",        "level": 0, "comments": null,         "actionBy": "ankandas", "createdAt": "2026-09-04 10:05:00" },
      { "id": 6, "action": "FINAL_APPROVE", "level": 1, "comments": "Verified",   "actionBy": "manager1", "createdAt": "2026-09-04 11:00:00" }
    ],
    "details": [
      {
        "slNo": 1,
        "budgetDetailId": 1,
        "ccCode": "CC001",
        "ccName": "Site Labour",
        "shortDescription": "Daily wages",
        "amount": 18000.0
      }
    ]
  }
]
```

---

### `summary` block

```json
{
  "totalBudgetAmount": 75000.0,
  "totalUsed": 18000.0,
  "totalRemaining": 57000.0,
  "voucherCount": 2,
  "approvedVouchers": 1,
  "pendingVouchers": 0,
  "draftVouchers": 1,
  "rejectedVouchers": 0,
  "rebackVouchers": 0
}
```

| Field | Description |
|---|---|
| `totalUsed` | Sum of all active (non-Draft, non-Rejected) voucher amounts |
| `totalRemaining` | `totalBudgetAmount - totalUsed` |
| `voucherCount` | All vouchers regardless of status |
| `approvedVouchers` | Count with `workflowStatus = Approved` |
| `pendingVouchers` | Count with `workflowStatus` starting with `Pending` |
| `draftVouchers` | Count with `workflowStatus = Draft` |
| `rejectedVouchers` | Count with `workflowStatus = Rejected` |
| `rebackVouchers` | Count with `workflowStatus = Reback` |

---

## "Used Amount" Counting Rules

| Voucher Status | Counts as Used? |
|---|---|
| Draft | ❌ No |
| Pending_L1 / L2 / … | ✅ Yes (committed) |
| Approved | ✅ Yes |
| Reback | ✅ Yes (still active) |
| Rejected | ❌ No |

---

## Registration (`app/__init__.py`)

```python
from .modules.finance.petty_cash.ledger.routes import petty_cash_ledger_bp
app.register_blueprint(petty_cash_ledger_bp, url_prefix="/finance/petty-cash/ledger")
```

---

## Related Modules

| Module | Base URL |
|---|---|
| Petty Cash Budget | `/finance/petty-cash/budget` |
| Petty Cash Docket Voucher | `/finance/petty-cash/docket-voucher` |
| Petty Cash Ledger (this) | `/finance/petty-cash/ledger` |
