# Sale Bill Module

**Base URL:** `/finance/sale-bill`  
**Blueprint:** `sale_bill_bp`  
**Auth:** JWT required on all routes except UUID lookup  
**Workflow module code:** `sale_bill`

---

## Overview

Generates Sale Invoices or Proforma Invoices against an Approved Certified Bill.  
Items from the certified bill are grouped by **CC Code** and presented as the BASIC section.  
GST is applied on top as selectable rows (IGST / CGST / SGST).

---

## Business Flow

```
OG Sale Order
    └──> sale_claim_bill (Approved)
              └──> sale_certified_bill (Approved)
                        └──> Sale Bill (Invoice / Proforma)
                             ├── BASIC section: items grouped by CC Code
                             └── GST section: IGST / CGST / SGST (checkbox select)
```

**Steps to create a sale bill:**
1. Call `/certified-bills?ogSaleOrderNo=X&projectCode=Y` → get list of Approved certified bills
2. Call `/certified-bill-items?certifiedBillId=Z&projectCode=Y` → items grouped by CC Code (pre-fills BASIC section)
3. User fills in header fields, description/HSN per CC group, selects GST types
4. POST `/create` with full payload

---

## Database Tables

### `sale_bill_master`

| Column | Type | Notes |
|--------|------|-------|
| `id` | Integer PK | |
| `sale_bill_no` | String(50) | Auto-generated sequential `001`, `002`… |
| `sale_bill_uuid` | String(36) | UUID — unique, indexed. Public shareable link. |
| `mode` | String(30) | `sale_invoice` or `proforma_invoice` |
| `invoice_date` | Date | |
| `reference_no` | String(200) | |
| `reference_date` | Date | |
| `sale_order_no` | String(50) | Copied from certified bill's OG Sale Order |
| `sale_order_id` | FK → `og_sale_order_master.id` | |
| `certified_bill_id` | FK → `billing_master.id` | The Approved certified bill this invoice is raised against |
| `certified_bill_no` | String(50) | Snapshot of certified bill number |
| `project_code` | FK → `projects` | |
| `bill_to_address` | Text | |
| `ship_to_address` | Text | |
| `bill_abstract_no` | String(200) | |
| `bill_abstract_date` | Date | |
| `bank_ac` | String(200) | Bank account reference |
| `payment_terms` | Text | |
| `declaration` | Text | |
| `basic_amount` | Numeric(14,2) | SUM of all BASIC item amounts |
| `gst_amount` | Numeric(14,2) | SUM of selected GST line amounts |
| `discount` | Numeric(14,2) | Manual entry |
| `round_off` | Numeric(10,2) | Manual entry (positive or negative) |
| `total_invoice_amount` | Numeric(14,2) | `basic_amount + gst_amount - discount + round_off` |
| `workflow_status` | String(30) | `Draft` / `Pending_L1` / `Approved` / `Reback` / `Rejected` |
| `current_level` | Integer | |
| `locked` | Boolean | |
| Audit columns | | `created_by/at`, `updated_by/at`, `submitted_by/at`, `approved_by`, `final_approved_at`, `rejected_by/at`, `correction_sent_at` |

### `sale_bill_items` (BASIC section)

| Column | Type | Notes |
|--------|------|-------|
| `sale_bill_id` | FK → `sale_bill_master.id` | Cascade delete |
| `sl_no` | Integer | |
| `cc_code` | String(50) | Snapshotted from CC Code master |
| `cc_name` | String(200) | Snapshotted |
| `description` | Text | User-entered description for this CC group |
| `hsn_sac` | String(50) | User-entered HSN/SAC code |
| `basic_amount` | Numeric(14,2) | Sum of billing item amounts for this CC Code group |

### `sale_bill_gst` (GST section)

| Column | Type | Notes |
|--------|------|-------|
| `sale_bill_id` | FK → `sale_bill_master.id` | Cascade delete |
| `gst_type` | String(10) | `IGST` / `CGST` / `SGST` |
| `cc_code` | String(50) | e.g. Output-IGST |
| `cc_name` | String(200) | |
| `description` | Text | |
| `percent` | Numeric(5,2) | 18 / 9 / 9 |
| `gst_amount` | Numeric(14,2) | Computed: `basic_amount × percent / 100` (0 if not selected) |
| `is_selected` | Boolean | User checkbox — only selected rows contribute to `gst_amount` total |

---

## CC Code Grouping Logic

```
BillingItem.item_code
    → Item.cc_code_id
    → CCCode.cc_code, CCCode.cc_name

Group all billing items with same cc_code_id → SUM(amount) → one SaleBillItem row
```

Items without a CC Code are grouped as "Uncategorized".

---

## Financial Logic

```
BASIC:
  SaleBillItem.basic_amount = SUM(BillingItem.amount) per CC Code group

GST (per selected row):
  gst_amount = basic_amount × percent / 100

Bill totals:
  basic_amount         = SUM(SaleBillItem.basic_amount)
  gst_amount           = SUM(SaleBillGst.gst_amount where is_selected=True)
  total_invoice_amount = basic_amount + gst_amount - discount + round_off
```

---

## API Endpoints

| Method | URL | Auth | Description |
|--------|-----|------|-------------|
| GET | `/certified-bills` | JWT | List Approved certified bills for an OG Sale Order |
| GET | `/certified-bill-items` | JWT | Items from a certified bill grouped by CC Code |
| POST | `/create` | JWT | Create a sale bill (JSON body) |
| GET | `/list` | JWT | List sale bills with filters |
| GET | `/<id>` | JWT | Full details with items and GST lines |
| PUT | `/edit/<id>` | JWT | Edit header + rebuild items/GST (Draft/Reback only) |
| POST | `/submit/<id>` | JWT | Submit for approval |
| POST | `/approve/<id>` | JWT | Approve at current level |
| POST | `/reback/<id>` | JWT | Return for correction (comments required) |
| POST | `/reject/<id>` | JWT | Reject permanently (comments required) |
| GET | `/history/<id>` | JWT | Approval history + steps |
| GET | `/my-approval-status/<id>` | JWT | Current user's approval role |
| GET | `/uuid/<uuid>` | **None** | Public shareable view |

---

## 1. Certified Bills Lookup

**GET** `/certified-bills`

```
?ogSaleOrderNo=OSO001&projectCode=PROJ01
```

Returns all Approved `sale_certified_bill` records for that OG Sale Order.

---

## 2. Certified Bill Items (Grouped)

**GET** `/certified-bill-items`

```
?certifiedBillId=7&projectCode=PROJ01
```

Returns items from the certified bill grouped by CC Code. Use this to pre-fill the BASIC section in the UI.

Response:
```json
{
  "certifiedBillId": 7,
  "certifiedBillNo": "001",
  "ogSaleOrderNo": "OSO001",
  "items": [
    {
      "slNo": 1,
      "ccCode": "CCWS",
      "ccName": "Certified Work done Sale",
      "description": "",
      "hsnSac": "",
      "basicAmount": 275000.00
    }
  ]
}
```

---

## 3. Create

**POST** `/create` — `application/json`

```json
{
  "projectCode":      "PROJ01",
  "mode":             "sale_invoice",
  "certifiedBillId":  7,
  "invoiceDate":      "2026-08-02",
  "referenceNo":      "REF-001",
  "referenceDate":    "2026-08-01",
  "billToAddress":    "Client address...",
  "shipToAddress":    "Site address...",
  "billAbstractNo":   "BA-001",
  "billAbstractDate": "2026-08-02",
  "bankAc":           "SBI-MAIN",
  "paymentTerms":     "30 days",
  "declaration":      "Certified that the work is done...",
  "discount":         0,
  "roundOff":         0.5,
  "items": [
    {
      "slNo":        1,
      "ccCode":      "CCWS",
      "ccName":      "Certified Work done Sale",
      "description": "Electrical work at site A",
      "hsnSac":      "9954",
      "basicAmount": 275000.00
    }
  ],
  "gstLines": [
    { "gstType": "IGST", "ccCode": "IGST", "ccName": "Output-IGST", "description": "", "percent": 18, "gstAmount": 49500.00, "isSelected": true },
    { "gstType": "CGST", "ccCode": "CGST", "ccName": "Output-CGST", "description": "", "percent": 9,  "gstAmount": 0,        "isSelected": false },
    { "gstType": "SGST", "ccCode": "SGST", "ccName": "Output-SGST", "description": "", "percent": 9,  "gstAmount": 0,        "isSelected": false }
  ]
}
```

- `sale_order_no` and `sale_order_id` are **not required** — copied automatically from the certified bill
- Only selected GST lines contribute to `gst_amount`
- `total_invoice_amount = basic_amount + gst_amount - discount + round_off`

---

## 4. List Filters

| Param | Notes |
|-------|-------|
| `projectCode` | Required |
| `mode` | `sale_invoice` or `proforma_invoice` |
| `workflowStatus` | Exact match |
| `saleOrderNo` | Partial match |
| `search` | Matches `sale_bill_no`, `sale_order_no`, `certified_bill_no` |

---

## 5. Details Response

```json
{
  "id": 1,
  "saleBillNo": "001",
  "mode": "sale_invoice",
  "invoiceDate": "2026-08-02",
  "saleOrderNo": "OSO001",
  "certifiedBillId": 7,
  "certifiedBillNo": "001",
  "basicAmount": 275000.0,
  "gstAmount": 49500.0,
  "discount": 0.0,
  "roundOff": 0.5,
  "totalInvoiceAmount": 324500.5,
  "workflowStatus": "Draft",
  "items": [ ... ],
  "gstLines": [ ... ]
}
```

---

## Workflow Actions

```
POST /submit/<id>
POST /approve/<id>   { "comments": "ok" }
POST /reback/<id>    { "comments": "fix description" }   ← required
POST /reject/<id>    { "comments": "reason" }             ← required
```

---

## File Structure

```
app/modules/finance/sale_bill/
├── __init__.py
├── routes.py    — Blueprint (sale_bill_bp), 13 routes
├── service.py   — All business logic
└── README.md

app/models/
└── saleBill.py  — SaleBillMaster, SaleBillItem, SaleBillGst
```

**Blueprint registered at:** `/finance/sale-bill`
