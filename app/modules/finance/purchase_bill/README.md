# Finance > Accounts > Purchases > Bill Processing

**Module Code:** `purchase_bill`
**URL Prefix:** `/finance/purchase-bill`
**DB Tables:** `purchase_bill_master`, `purchase_bill_items`, `purchase_bill_gst`

---

## Overview

Creates a formal purchase invoice under Finance > Accounts > Purchases by linking
to an approved Bill Received Register (BRR) entry. Items in the BASIC section are
automatically grouped by CC Code, aggregated from all Approved BRR Billing (BRB)
records under the selected BRR.

---

## Frontend Flow (Step by Step)

### Step 1 — Mode
Select mode from dropdown. No API call triggered.

| Value | UI Label |
|-------|----------|
| `purchase_invoice` | Purchase Invoice |
| `proforma_invoice` | Proforma Invoice |

---

### Step 2 — Select Party (Vendor)

Vendor is selected from the vendor master list (existing vendor list API).
Once a vendor is chosen, trigger:

```
GET /finance/purchase-bill/vendor-orders
  ?vendorId={id}
  &projectCode={code}
  &orderType=GRN|SRN        ← optional filter; omit to get both
```

**Optional `orderType` filter:**
| Value | Shows |
|-------|-------|
| `GRN` | Only orders from `order_master` (material/purchase orders) |
| `SRN` | Only orders from `pw_order_master` (work/service orders) |
| *(blank)* | Both GRN and SRN orders combined |

**GRN order row (order_master):**
```json
{
  "id":              42,
  "orderNo":         "ORD-2026-042",
  "orderDate":       "2026-06-01",
  "orderType":       "GRN",
  "categoryCode":    "Purchases_Order",
  "subCategoryCode": "RAW_MATERIAL",
  "subCategoryName": "Raw Material",
  "costHead":        "Civil"
}
```

**SRN order row (pw_order_master):**
```json
{
  "id":               18,
  "orderNo":          "PW-2026-018",
  "orderDate":        "2026-05-15",
  "orderType":        "SRN",
  "categoryCode":     "Work_Order",
  "subCategoryCodes": ["SVC", "COMP"],
  "subCategoryNames": ["Civil Service", "Compaction"],
  "costHead":         "Labour"
}
```

> GRN has single `subCategoryCode/Name` (one FK in order_master).
> SRN has arrays `subCategoryCodes/Names` (JSON list in pw_order_master).

Populate the **Order Number** dropdown. Suggest showing `orderNo | subCategoryName | costHead` as label.
Store `id + orderType` together for the next step.

---

### Step 3 — Select Order Number

Once an order is selected, trigger:

```
GET /finance/purchase-bill/brr-list
  ?orderId={id}
  &orderType=GRN|SRN
  &projectCode={code}
```

Returns Approved BRR (Bill Received Register) entries for that order.

**Response row:**
```json
{
  "id":          7,
  "brrNo":       "900001",
  "brrDate":     "2026-07-15",
  "orderType":   "GRN",
  "partyBillNo": "INV-2026-001",
  "partyDate":   "2026-07-14",
  "basicAmount": 10000.00,
  "totalAmount": 11800.00
}
```

Populate the **BRR Number** dropdown (UI label: "BVS Number").

---

### Step 4 — Select BRR Number

Once a BRR is selected, trigger:

```
GET /finance/purchase-bill/brr-items
  ?brrId={id}
  &projectCode={code}
```

This single call returns everything needed to auto-fill the form:

**Response:**
```json
{
  "brrId":          7,
  "brrNo":          "900001",
  "brrDate":        "2026-07-15",
  "orderType":      "GRN",
  "vendorBillNo":   "INV-2026-001",
  "vendorBillDate": "2026-07-14",
  "items": [
    {
      "slNo":        1,
      "ccCode":      "CCWS",
      "ccName":      "Civil Works",
      "description": "",
      "hsnSac":      "",
      "basicAmount": 10000.00
    }
  ]
}
```

**Auto-fill the form fields:**
| Form Field | Source Field |
|------------|-------------|
| BRR Date | `brrDate` |
| Vendor Bill No | `vendorBillNo` |
| Vendor Bill Date | `vendorBillDate` |
| BASIC table rows | `items` array |

---

### Step 5 — GST Section (frontend calculated)

Pre-populate 3 unchecked rows. When user checks a row, compute `gstAmount` live:

```
gstAmount = (basicTotal × percent) / 100
```

| GST Type | % | Default |
|----------|---|---------|
| IGST | 18 | unchecked |
| CGST | 9 | unchecked |
| SGST | 9 | unchecked |

---

### Step 6 — Summary (frontend calculated, live)

```
Basic Amount       = Σ item.basicAmount
GST Amount         = Σ selected gstLine.gstAmount
Discount           = manual entry
Round On/Off       = manual entry
Total Invoice Amt  = Basic + GST − Discount + RoundOff
Amount (In Word)   = number-to-words of Total
```

---

### Step 7 — Save as Draft

```
POST /finance/purchase-bill/create
```

**Request body:**
```json
{
  "projectCode":   "PRJ001",
  "mode":          "purchase_invoice",
  "brrId":         7,
  "processingDate": "2026-08-03",
  "remarks":       "August material bill",
  "items": [
    {
      "slNo":        1,
      "ccCode":      "CCWS",
      "ccName":      "Civil Works",
      "description": "",
      "hsnSac":      "",
      "basicAmount": 10000.00
    }
  ],
  "gstLines": [
    { "gstType": "IGST", "percent": 18, "gstAmount": 1800.00, "isSelected": false },
    { "gstType": "CGST", "percent": 9,  "gstAmount": 900.00,  "isSelected": true  },
    { "gstType": "SGST", "percent": 9,  "gstAmount": 900.00,  "isSelected": true  }
  ],
  "discount": 0,
  "roundOff": 0
}
```

> `vendorId`, `orderId`, `orderType`, `brrNo`, `brrDate`, `vendorBillNo`, `vendorBillDate`
> are all **auto-filled from the BRR record** on the backend — do not send them in the body.

**Response:**
```json
{
  "id":               1,
  "purchaseBillNo":   "001",
  "purchaseBillUuid": "...",
  "mode":             "purchase_invoice"
}
```

The `purchaseBillNo` is the **ERP Doc. No** shown top-left in the form.

---

### Step 8 — Edit (Draft or Reback only)

```
PUT /finance/purchase-bill/edit/{id}
```

Same body as create. BRR link does not change on edit — only items, GST, mode, remarks, discount, roundOff can be updated.

---

### Step 9 — Submit

```
POST /finance/purchase-bill/submit/{id}
```

Locks the bill. Moves to `Pending_L1` if approvers are configured, or directly to `Approved` if none.

---

## All API Endpoints

### Lookup

| Method | Path | Query Params | Description |
|--------|------|-------------|-------------|
| GET | `/vendor-orders` | `vendorId`, `projectCode`, `orderType?` (GRN\|SRN\|blank) | Orders for vendor with category, sub-category, cost head |
| GET | `/brr-list` | `orderId`, `orderType`, `projectCode` | Approved BRR entries for an order |
| GET | `/brr-items` | `brrId`, `projectCode` | CC-grouped items + BRR meta (auto-fill data) |

### CRUD & Workflow

| Method | Path | Description |
|--------|------|-------------|
| POST | `/create` | Create purchase bill (Draft) |
| GET | `/list` | List with filters: `projectCode`, `mode`, `workflowStatus`, `vendorId`, `search` |
| GET | `/<id>` | Full detail — header + items + GST lines |
| PUT | `/edit/<id>` | Edit Draft or Reback bill |
| POST | `/submit/<id>` | Submit for approval |
| POST | `/approve/<id>` | Approve `{ comments }` |
| POST | `/reback/<id>` | Send for correction `{ comments }` |
| POST | `/reject/<id>` | Reject `{ comments }` |
| GET | `/history/<id>` | Approval history + steps |
| GET | `/my-approval-status/<id>` | Caller's approval role and status |

---

## Workflow States

```
Draft → Pending_L1 → Pending_L2 → ... → Approved
                  ↘ Reback → (edit) → re-submit
                  ↘ Rejected
```

---

## DB Model Summary

### purchase_bill_master

| Column | Type | Notes |
|--------|------|-------|
| purchase_bill_no | String(50) | Auto-generated sequential (001, 002, …) |
| purchase_bill_uuid | String(36) | UUID |
| mode | String(30) | `purchase_invoice` / `proforma_invoice` |
| processing_date | Date | Defaults to today |
| project_code | FK → projects | |
| vendor_id | FK → vendors | Copied from BRR |
| order_type | String(10) | `GRN` or `SRN` |
| order_id | FK → order_master | Populated for GRN orders |
| pw_order_id | FK → pw_order_master | Populated for SRN orders |
| brr_id | FK → brr_master | |
| brr_no | String(50) | Snapshot of BRR number |
| brr_date | Date | Snapshot of BRR date |
| vendor_bill_no | String(100) | Snapshot of `party_bill_no` from BRR |
| vendor_bill_date | Date | Snapshot of `party_date` from BRR |
| remarks | Text | |
| basic_amount | Numeric(14,2) | Sum of item basic amounts |
| gst_amount | Numeric(14,2) | Sum of selected GST amounts |
| discount | Numeric(14,2) | Manual entry |
| round_off | Numeric(10,2) | Manual entry |
| total_invoice_amount | Numeric(14,2) | basic + gst − discount + round_off |
| workflow_status | String(30) | Draft / Pending_Lx / Approved / Reback / Rejected |
| locked | Boolean | True when submitted/approved |

### purchase_bill_items

One row per CC Code group (BASIC table in the form).

| Column | Notes |
|--------|-------|
| sl_no | Sequential row number |
| cc_code | CC Code |
| cc_name | CC Name |
| description | Optional — editable by user |
| hsn_sac | Optional — editable by user |
| basic_amount | Aggregated from BRB items |

### purchase_bill_gst

Up to 3 rows per bill (IGST / CGST / SGST).

| Column | Notes |
|--------|-------|
| gst_type | `IGST` / `CGST` / `SGST` |
| percent | Tax rate |
| gst_amount | Calculated on frontend, stored here |
| is_selected | Only selected rows contribute to gst_amount total |

---

## Item CC Grouping Logic

Items are derived from Approved BRB (BRR Billing) records linked to the selected BRR.
Basic amounts are summed per CC Code across all Approved BRBs under the BRR.

**GRN path:**
```
BrbItem → grn_items → order_items → items → cc_codes
```

**SRN path:**
```
BrbItem → srn_items → pw_order_items → items → cc_codes
```
