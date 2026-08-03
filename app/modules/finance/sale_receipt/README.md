# Finance > Accounts > Sales > Sale Receipt

**Module Code:** `sale_receipt`
**URL Prefix:** `/finance/sale-receipt`
**DB Tables:** `sale_receipt_master`, `sale_receipt_items`, `sale_receipt_gst`

---

## Overview

A Sale Receipt records payment received against a certified bill. It is always linked to an OG Sale Order → Certified Bill chain.

Items are fetched grouped by CC Code from the certified bill. Each row carries four accounting columns:

| Column | Meaning |
|---|---|
| **Booked** | Total amount billed in the certified bill for this CC Code |
| **Received** | Sum of `current_amount` from all previous non-Rejected receipts for the same certified bill + CC Code |
| **Balance** | Booked − Received |
| **Current** | Amount being received in this entry (user fills) |

Every time a new receipt is created for the same certified bill, `Received` auto-accumulates — standard running ledger.

GST **Booked** is pulled from the approved Sale Bill's selected GST lines. `Received` for GST follows the same running-total logic per GST type.

---

## Frontend Flow (Step by Step)

### Step 1 — Select Sale Order

Call the sale order list API (existing `og_sale_order_bp`) to let the user pick an OG Sale Order.

---

### Step 2 — Select Certified Bill

```
GET /finance/sale-receipt/certified-bills?ogSaleOrderNo={no}&projectCode={code}
```

Returns all **Approved** `sale_certified_bill` records under that sale order.

**Response:**
```json
[
  {
    "id":            12,
    "billingNo":     "CB-2026-001",
    "billingDate":   "2026-07-01",
    "thisBillClaim": 41952.00
  }
]
```

Auto-fill:
- **Sale Order Date** → from the OG Sale Order record
- **Bill Abstract No** → `billingNo` of the selected certified bill
- **Bill Abstract Date** → `billingDate` of the selected certified bill

---

### Step 3 — Fetch Receipt Items (accounting columns)

```
GET /finance/sale-receipt/receipt-items?certifiedBillId={id}&projectCode={code}
```

This is the key accounting endpoint. It returns:
- **BASIC items** grouped by CC Code, each with Booked / Received / Balance / Current (Current = 0, user fills)
- **GST lines** with Booked from the approved Sale Bill's GST, Received from prior receipts

**Response:**
```json
{
  "certifiedBillId": 12,
  "certifiedBillNo": "CB-2026-001",
  "ogSaleOrderNo":   "SO-2026-001",
  "saleOrderDate":   "2026-01-15",
  "items": [
    {
      "slNo":           1,
      "ccCode":         "DRLC",
      "ccName":         "Work Charges-PRW",
      "bookedAmount":   25000.00,
      "receivedAmount": 25000.00,
      "balanceAmount":  0.00,
      "currentAmount":  0
    },
    {
      "slNo":           2,
      "ccCode":         "DRLC",
      "ccName":         "Work Charges-PRW",
      "bookedAmount":   15410.00,
      "receivedAmount": 5000.00,
      "balanceAmount":  10410.00,
      "currentAmount":  0
    }
  ],
  "gstLines": [
    {
      "gstType":        "IGST",
      "ccCode":         "IGST",
      "ccName":         "Input-IGST",
      "percent":        18,
      "bookedAmount":   0,
      "receivedAmount": 0,
      "balanceAmount":  0,
      "currentAmount":  0,
      "isSelected":     false
    },
    {
      "gstType":        "CGST",
      "ccCode":         "CGST",
      "ccName":         "Input-CGST",
      "percent":        9,
      "bookedAmount":   3775.68,
      "receivedAmount": 0,
      "balanceAmount":  3775.68,
      "currentAmount":  0,
      "isSelected":     true
    },
    {
      "gstType":        "SGST",
      "ccCode":         "SGST",
      "ccName":         "Input-SGST",
      "percent":        9,
      "bookedAmount":   3775.68,
      "receivedAmount": 0,
      "balanceAmount":  3775.68,
      "currentAmount":  0,
      "isSelected":     true
    }
  ]
}
```

> **Note:** If no approved Sale Bill exists yet for this certified bill, GST lines are returned with all amounts = 0 and `isSelected: false`.

---

### Step 4 — Fill Header Fields

| Form Field | API Field | Note |
|---|---|---|
| ERP Doc No | `receiptNo` | Auto-generated on create, read-only |
| Entry Date | `entryDate` | Auto today — read-only |
| Invoice No | `invoiceNo` | Text — manual reference |
| Invoice Date | `invoiceDate` | Date — manual |
| Sale Order Number | `ogSaleOrderNo` | Auto-filled from certified bill |
| Sale Order Date | `saleOrderDate` | Auto-filled |
| Bill To Address | `billToAddress` | Text |
| Ship To Address | `shipToAddress` | Text |
| Bill Abstract No | `billAbstractNo` | Auto-filled from certified bill no |
| Bill Abstract Date | `billAbstractDate` | Auto-filled from certified bill date |
| Payment Mode | `paymentMode` | `Cash` or `Bank` |
| Cash A/c | `cashAcId` | FK → `bank_cash.id` (show only if Cash) |
| Bank A/c | `bankAcId` | FK → `bank_cash.id` (show only if Bank) |
| UTR / Voucher No | `utrVoucherNo` | Text |
| Payment Remarks | `paymentRemarks` | Text |

---

### Step 5 — Fill BASIC Table

Populate the table from the `/receipt-items` response. User fills only the **Current** column.

| Column | Editable | Note |
|---|---|---|
| SL No | No | Auto from response |
| CC Code | No | From certified bill grouping |
| CC Name | No | From certified bill grouping |
| Booked | No | From certified bill |
| Received | No | Auto-computed from prior receipts |
| Balance | No | Booked − Received (live: Balance − Current as user types) |
| Current | **Yes** | User enters the amount being received now |

Frontend should validate: `currentAmount ≤ balanceAmount` per row.

---

### Step 6 — Fill GST Table

Same four-column structure as BASIC. User fills only **Current**.

| Column | Editable | Note |
|---|---|---|
| GST Type | No | IGST / CGST / SGST |
| CC Code / Name | No | From sale bill GST lines |
| Booked | No | From approved sale bill |
| Received | No | Prior receipts |
| Balance | No | Booked − Received |
| Current | **Yes** | User enters |
| Is Selected | **Yes** | Check/uncheck row |

---

### Step 7 — Summary (frontend calculated, live)

```
Basic Amount      = Σ item.currentAmount
GST Amount        = Σ selected gstLine.currentAmount
Discount          = manual entry
Round On/Off      = manual entry
Total Invoice Amt = Basic + GST − Discount + RoundOff
Amount (In Word)  = number-to-words of Total
```

---

### Step 8 — Save as Draft

```
POST /finance/sale-receipt/create
```

**Request body:**
```json
{
  "projectCode":       "PRJ001",
  "certifiedBillId":   12,
  "invoiceNo":         "INV-2026-001",
  "invoiceDate":       "2026-08-03",
  "billToAddress":     "Client Address",
  "shipToAddress":     "Site Address",
  "billAbstractNo":    "CB-2026-001",
  "billAbstractDate":  "2026-07-01",
  "paymentMode":       "Bank",
  "cashAcId":          null,
  "bankAcId":          3,
  "utrVoucherNo":      "UTR123456",
  "paymentRemarks":    "Partial payment",
  "items": [
    {
      "slNo":           1,
      "ccCode":         "DRLC",
      "ccName":         "Work Charges-PRW",
      "bookedAmount":   15410.00,
      "receivedAmount": 5000.00,
      "balanceAmount":  10410.00,
      "currentAmount":  10000.00
    }
  ],
  "gstLines": [
    {
      "gstType":        "IGST",
      "ccCode":         "IGST",
      "ccName":         "Input-IGST",
      "percent":        18,
      "bookedAmount":   0,
      "receivedAmount": 0,
      "balanceAmount":  0,
      "currentAmount":  0,
      "isSelected":     false
    },
    {
      "gstType":        "CGST",
      "ccCode":         "CGST",
      "ccName":         "Input-CGST",
      "percent":        9,
      "bookedAmount":   3775.68,
      "receivedAmount": 0,
      "balanceAmount":  3775.68,
      "currentAmount":  900.00,
      "isSelected":     true
    },
    {
      "gstType":        "SGST",
      "ccCode":         "SGST",
      "ccName":         "Input-SGST",
      "percent":        9,
      "bookedAmount":   3775.68,
      "receivedAmount": 0,
      "balanceAmount":  3775.68,
      "currentAmount":  900.00,
      "isSelected":     true
    }
  ],
  "discount": 0,
  "roundOff": 0
}
```

> `basic_amount` and `gst_amount` stored on master = sum of `currentAmount` (this receipt only).
> `booked_amount`, `received_amount`, `balance_amount` are stored as snapshots at creation time.

**Response:**
```json
{
  "id":          1,
  "receiptNo":   "001",
  "receiptUuid": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
}
```

---

### Step 9 — Edit (Draft or Reback only)

```
PUT /finance/sale-receipt/edit/{id}
```

Same body as create. `certifiedBillId`, `projectCode`, `receiptNo` cannot be changed.
Only header fields, items, and gstLines are updated.

---

### Step 10 — Submit

```
POST /finance/sale-receipt/submit/{id}
```

Locks the receipt. Moves to `Pending_L1` if approvers configured, else directly `Approved`.

---

## Accounting — Running Ledger Example

**Scenario:** Certified bill CB-001 has CC Code DRLC with Booked = 50,000.

| Receipt | Current | Received (next time) | Balance (next time) |
|---|---|---|---|
| Receipt #001 | 20,000 | 20,000 | 30,000 |
| Receipt #002 | 15,000 | 35,000 | 15,000 |
| Receipt #003 | 15,000 | 50,000 | 0 |

`Received` is always computed live by querying `SUM(current_amount)` from all non-Rejected receipts for the same `certified_bill_id` + `cc_code`. It does **not** depend on static data.

---

## Detail Response (GET `/<id>`)

```json
{
  "id":                  1,
  "receiptNo":           "001",
  "receiptUuid":         "...",
  "entryDate":           "2026-08-03",
  "ogSaleOrderNo":       "SO-2026-001",
  "ogSaleOrderId":       5,
  "saleOrderDate":       "2026-01-15",
  "certifiedBillId":     12,
  "certifiedBillNo":     "CB-2026-001",
  "projectCode":         "PRJ001",
  "invoiceNo":           "INV-2026-001",
  "invoiceDate":         "2026-08-03",
  "billToAddress":       "Client Address",
  "shipToAddress":       "Site Address",
  "billAbstractNo":      "CB-2026-001",
  "billAbstractDate":    "2026-07-01",
  "paymentMode":         "Bank",
  "cashAcId":            null,
  "cashAcName":          null,
  "bankAcId":            3,
  "bankAcName":          "HDFC Current A/c",
  "bankCode":            "HDFC0001234",
  "utrVoucherNo":        "UTR123456",
  "paymentRemarks":      "Partial payment",
  "basicAmount":         10000.00,
  "gstAmount":           1800.00,
  "discount":            0,
  "roundOff":            0,
  "totalInvoiceAmount":  11800.00,
  "workflowStatus":      "Draft",
  "currentLevel":        0,
  "locked":              false,
  "createdBy":           "john_doe",
  "createdAt":           "2026-08-03",
  "submittedBy":         null,
  "submittedAt":         null,
  "approvedBy":          null,
  "finalApprovedAt":     null,
  "rejectedBy":          null,
  "rejectedAt":          null,
  "items": [
    {
      "id":             1,
      "slNo":           1,
      "ccCode":         "DRLC",
      "ccName":         "Work Charges-PRW",
      "bookedAmount":   15410.00,
      "receivedAmount": 5000.00,
      "balanceAmount":  10410.00,
      "currentAmount":  10000.00
    }
  ],
  "gstLines": [
    { "id": 1, "gstType": "IGST", "percent": 18, "bookedAmount": 0,       "receivedAmount": 0, "balanceAmount": 0,       "currentAmount": 0,   "isSelected": false },
    { "id": 2, "gstType": "CGST", "percent": 9,  "bookedAmount": 3775.68, "receivedAmount": 0, "balanceAmount": 3775.68, "currentAmount": 900, "isSelected": true  },
    { "id": 3, "gstType": "SGST", "percent": 9,  "bookedAmount": 3775.68, "receivedAmount": 0, "balanceAmount": 3775.68, "currentAmount": 900, "isSelected": true  }
  ]
}
```

---

## All API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/certified-bills` | Approved certified bills — params: `ogSaleOrderNo`, `projectCode` |
| GET | `/receipt-items` | CC-grouped items with Booked/Received/Balance — params: `certifiedBillId`, `projectCode` |
| POST | `/create` | Create receipt (Draft) |
| GET | `/list` | List — filters: `projectCode`, `workflowStatus`, `ogSaleOrderNo`, `search` |
| GET | `/<id>` | Full detail with items + GST lines |
| GET | `/uuid/<uuid>` | Public lookup by UUID (no JWT) |
| PUT | `/edit/<id>` | Edit Draft or Reback receipt |
| POST | `/submit/<id>` | Submit for approval |
| POST | `/approve/<id>` | Approve `{ "comments": "..." }` |
| POST | `/reback/<id>` | Send for correction `{ "comments": "..." }` |
| POST | `/reject/<id>` | Reject `{ "comments": "..." }` |
| GET | `/history/<id>` | Approval history + steps |
| GET | `/my-approval-status/<id>` | Caller's approval role and status |

---

## Workflow States

```
Draft → Pending_L1 → Pending_L2 → ... → Approved
                  ↘ Reback → (edit) → re-submit
                  ↘ Rejected
```

Rejected receipts are excluded from the `Received` running total.

---

## DB Model Summary

### sale_receipt_master

| Column | Type | Notes |
|--------|------|-------|
| receipt_no | String(50) | Auto-generated sequential (001, 002, …) |
| receipt_uuid | String(36) | UUID, unique |
| entry_date | Date | Auto today on create |
| og_sale_order_no | String(50) | Snapshot from certified bill |
| og_sale_order_id | FK → og_sale_order_master | |
| sale_order_date | Date | Snapshot from OG Sale Order |
| certified_bill_id | FK → billing_master | Required |
| certified_bill_no | String(50) | Snapshot |
| project_code | FK → projects | |
| invoice_no | String(200) | Manual reference |
| invoice_date | Date | Manual |
| bill_to_address | Text | |
| ship_to_address | Text | |
| bill_abstract_no | String(200) | Auto-filled from certified bill no |
| bill_abstract_date | Date | Auto-filled from certified bill date |
| payment_mode | String(10) | `Cash` / `Bank` |
| cash_ac_id | FK → bank_cash | Cash A/c — used when paymentMode = Cash |
| bank_ac_id | FK → bank_cash | Bank A/c — used when paymentMode = Bank |
| utr_voucher_no | String(200) | UTR / Voucher reference |
| payment_remarks | Text | |
| basic_amount | Numeric(14,2) | Σ item.current_amount (this receipt) |
| gst_amount | Numeric(14,2) | Σ selected gst.current_amount |
| discount | Numeric(14,2) | Manual |
| round_off | Numeric(10,2) | Manual |
| total_invoice_amount | Numeric(14,2) | basic + gst − discount + round_off |
| workflow_status | String(30) | Draft / Pending_Lx / Approved / Reback / Rejected |
| locked | Boolean | True after submit/approve |

### sale_receipt_items

One row per CC Code group. All four accounting columns stored as snapshots.

| Column | Type | Notes |
|--------|------|-------|
| sl_no | Integer | Row number |
| cc_code | String(50) | CC Code snapshot |
| cc_name | String(200) | CC Name snapshot |
| booked_amount | Numeric(14,2) | From certified bill items |
| received_amount | Numeric(14,2) | Snapshot of prior receipts at create time |
| balance_amount | Numeric(14,2) | booked − received at create time |
| current_amount | Numeric(14,2) | This receipt entry — used in running total |

### sale_receipt_gst

Up to 3 rows per receipt (IGST / CGST / SGST).

| Column | Type | Notes |
|--------|------|-------|
| gst_type | String(10) | `IGST` / `CGST` / `SGST` |
| cc_code | String(50) | |
| cc_name | String(200) | |
| percent | Numeric(5,2) | |
| booked_amount | Numeric(14,2) | From approved sale bill's GST |
| received_amount | Numeric(14,2) | Snapshot of prior receipts |
| balance_amount | Numeric(14,2) | booked − received at create time |
| current_amount | Numeric(14,2) | This receipt — used in running total |
| is_selected | Boolean | Only selected rows contribute to gst_amount |

---

## Key Differences from Sale Bill

| | Sale Bill | Sale Receipt |
|---|---|---|
| Purpose | Issue invoice to client | Record payment received from client |
| Items source | Certified bill CC grouping | Certified bill CC grouping + accounting columns |
| Accounting columns | None — just basicAmount | Booked / Received / Balance / Current per CC |
| GST Booked source | User fills (frontend computed) | Pulled from approved Sale Bill's GST |
| basic_amount stored | Sum of item.basicAmount | Sum of item.**currentAmount** (this receipt only) |
| Running total | N/A | `Received` accumulates across receipts for same cert bill |
