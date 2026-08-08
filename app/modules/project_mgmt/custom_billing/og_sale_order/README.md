# Project Mgmt > OG Sale Order

**Module Code:** `sale_order`
**URL Prefix:** `/project-mgmt/og-sale-order`
**DB Tables:** `og_sale_order_master`, `og_sale_order_items`, `og_sale_order_boq_items`

---

## Overview

Records an Outgoing (OG) Sale Order issued to a client. Supports two item tables:

| Table | Purpose |
|---|---|
| **Items** (`og_sale_order_items`) | Regular line items |
| **BOQ Items** (`og_sale_order_boq_items`) | Bill of Quantities items |

Both tables have identical field structure. The frontend controls which table a row lives in — switching a row between tables on edit is handled by sending it in a different array.

All item fields are **manual entry** — no FK to the item master, no lookup or validation against any master table.

`basic_amount` and `gst_amount` on the master are the combined totals of both tables.

---

## Frontend Flow

### Step 1 — Fill Header

| Form Field | API Field | Note |
|---|---|---|
| ERP Doc No | `ogSaleOrderNo` | Auto-generated (OSO001, OSO002…) — read-only |
| OG Sale Order Date | `ogSaleOrderDate` | Required, `YYYY-MM-DD` |
| Order No | `orderNo` | Client's PO / work order reference |
| Order Validity | `orderValidity` | Date |
| Order Title | `orderTitle` | Required |
| Attachment 1/2/3 | `attachment_1/2/3` | File upload (multipart) |

---

### Step 2 — Fill Items Table

Frontend sends rows in the `items` JSON string. Each row:

| Field | Key | Note |
|---|---|---|
| SL No | `slNo` | Row number |
| Item Code | `itemCode` | Plain text — no master validation |
| Item Name | `itemName` | Plain text |
| Item Description | `itemDescription` | Free text |
| Unit | `unit` | Plain text |
| Order Qty | `orderQty` | Numeric |
| Rate | `rate` | Numeric |
| Amount | computed | `orderQty × rate` — server computes |
| GST % | `gstPercent` | Numeric |
| GST Amount | computed | `amount × gstPercent / 100` — server computes |

---

### Step 3 — Fill BOQ Items Table

Frontend sends rows in the `boqItems` JSON string. **Identical fields to items table.**

---

### Step 4 — Save as Draft

```
POST /project-mgmt/og-sale-order/create
Content-Type: multipart/form-data
```

**Form fields:**

```
projectCode:     PRJ001
orderTitle:      Supply of Civil Materials
ogSaleOrderDate: 2026-08-04
orderNo:         PO-2026-001
orderValidity:   2027-03-31
items:           [{"slNo":1,"itemCode":"CI001","itemName":"Cement","unit":"Bag","orderQty":100,"rate":350,"gstPercent":18}]
boqItems:        [{"slNo":1,"itemCode":"BQ001","itemName":"Earthwork","unit":"CUM","orderQty":200,"rate":120,"gstPercent":0}]
attachment_1:    <file>
```

> `items` and `boqItems` are **JSON-stringified arrays** sent as plain form fields alongside file uploads.
> Either array may be empty `[]` but at least one must have rows.

**Response:**
```json
{
  "id":              1,
  "ogSaleOrderNo":   "OSO001",
  "ogSaleOrderUuid": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
}
```

---

### Step 5 — Edit (Draft or Reback only)

```
PUT /project-mgmt/og-sale-order/edit/{id}
Content-Type: multipart/form-data
```

Same fields as create. `ogSaleOrderNo` and `projectCode` cannot be changed.

**Switching a row between tables on edit:**

Both tables are fully wiped and rebuilt on every edit. To move a row from BOQ → Items, the frontend simply sends that row inside `items` instead of `boqItems`. The backend has no memory of the previous table — it stores exactly what it receives.

| User action | Frontend sends | Result |
|---|---|---|
| Move row from BOQ → Items | Row in `items`, removed from `boqItems` | Saved in `og_sale_order_items` |
| Move row from Items → BOQ | Row in `boqItems`, removed from `items` | Saved in `og_sale_order_boq_items` |

---

### Step 6 — Submit

```
POST /project-mgmt/og-sale-order/submit/{id}
```

Locks the record. Moves to `Pending_L1` if approvers configured, else directly `Approved`.

---

## Detail Response (GET `/<id>`)

```json
{
  "id":              1,
  "ogSaleOrderNo":   "OSO001",
  "ogSaleOrderUuid": "...",
  "ogSaleOrderDate": "2026-08-04",
  "orderNo":         "PO-2026-001",
  "orderValidity":   "2027-03-31",
  "orderTitle":      "Supply of Civil Materials",
  "projectCode":     "PRJ001",
  "basicAmount":     59000.00,
  "gstAmount":       10620.00,
  "totalAmount":     69620.00,
  "attachment1":     "https://cdn.example.com/og_sale_order/OSO001/attachment_1",
  "attachment2":     null,
  "attachment3":     null,
  "workflowStatus":  "Draft",
  "currentLevel":    0,
  "locked":          false,
  "createdBy":       "john_doe",
  "createdAt":       "2026-08-04",
  "submittedBy":     null,
  "submittedAt":     null,
  "approvedBy":      null,
  "finalApprovedAt": null,
  "rejectedBy":      null,
  "rejectedAt":      null,
  "items": [
    {
      "id":              1,
      "slNo":            1,
      "itemCode":        "CI001",
      "itemName":        "Cement",
      "itemDescription": null,
      "unit":            "Bag",
      "orderQty":        100.0,
      "rate":            350.0,
      "amount":          35000.0,
      "gstPercent":      18.0,
      "gstAmount":       6300.0
    }
  ],
  "boqItems": [
    {
      "id":              2,
      "slNo":            1,
      "itemCode":        "BQ001",
      "itemName":        "Earthwork",
      "itemDescription": null,
      "unit":            "CUM",
      "orderQty":        200.0,
      "rate":            120.0,
      "amount":          24000.0,
      "gstPercent":      18.0,
      "gstAmount":       4320.0
    }
  ]
}
```

---

## Totals Calculation

```
basic_amount = Σ items.amount    + Σ boqItems.amount
gst_amount   = Σ items.gstAmount + Σ boqItems.gstAmount
total_amount = basic_amount + gst_amount
```

`amount` and `gstAmount` are **computed by the server** — frontend does not send them.

---

## All API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/create` | Create (Draft) — `multipart/form-data` |
| GET | `/list` | List — filters: `projectCode`, `workflowStatus`, `search` |
| GET | `/<id>` | Full detail with items + boqItems |
| GET | `/uuid/<uuid>` | Public lookup by UUID (no JWT) |
| PUT | `/edit/<id>` | Edit Draft or Reback — `multipart/form-data` |
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

---

## DB Model Summary

### og_sale_order_master

| Column | Type | Notes |
|--------|------|-------|
| og_sale_order_no | String(50) | Auto-generated (OSO001…), unique |
| og_sale_order_uuid | String(36) | UUID, unique |
| og_sale_order_date | Date | Required |
| order_no | String(50) | Client PO reference |
| order_validity | Date | |
| order_title | String(200) | Required |
| project_code | FK → projects | |
| basic_amount | Numeric(14,2) | Σ items + boqItems basic |
| gst_amount | Numeric(14,2) | Σ items + boqItems GST |
| total_amount | Numeric(14,2) | basic + gst |
| attachment_1/2/3 | Text | CDN URLs |
| workflow_status | String(30) | Draft / Pending_Lx / Approved / Reback / Rejected |
| locked | Boolean | True after submit/approve |

### og_sale_order_items  &  og_sale_order_boq_items

Both tables share the same schema. All fields are plain manual entry — no FK to item master.

| Column | Type | Notes |
|--------|------|-------|
| og_sale_order_id | FK → master | |
| sl_no | Integer | Row number |
| item_code | String(50) | Plain text, no validation |
| item_name | String(2000) | |
| item_description | Text | |
| unit | String(30) | |
| order_qty | Numeric(12,2) | |
| rate | Numeric(12,2) | |
| amount | Numeric(14,2) | Server-computed: `order_qty × rate` |
| gst_percent | Numeric(5,2) | |
| gst_amount | Numeric(14,2) | Server-computed: `amount × gst_percent / 100` |
