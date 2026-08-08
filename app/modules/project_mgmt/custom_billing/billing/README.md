# Billing Module

**Base URL:** `/project-mgmt/billing`  
**Blueprint:** `billing_bp`  
**Auth:** JWT required on all routes except UUID lookup

---

## Overview

Unified billing module handling two bill types in one table (`billing_master` / `billing_items`).

| Mode | Description |
|------|-------------|
| `sale_claim_bill` | Rough/interim claim bill raised against an OG Sale Order. Approved values are frozen. |
| `sale_certified_bill` | Final certified bill. Must link to an **Approved** `sale_claim_bill`. Gets the **same billing number**. Items pre-populated from claim bill but qty/rate are editable. |

---

## Business Flow

```
OG Sale Order
    └──> sale_claim_bill  (Draft → Submitted → Approved)  →  billing_no: 001
              └──> sale_certified_bill  (Draft → Submitted → Approved)  →  billing_no: 001  (same)
```

**Constraints enforced:**
- Certified bill requires an **Approved** `sale_claim_bill` (`claimBillId`)
- `claim_bill.project_code` must match the certified bill's project
- Only **one active** certified bill per claim bill — re-certification allowed only if previous certified was Rejected
- Claim bill `billing_no` is copied to certified bill — no new number generated
- Race condition on duplicate check handled via `with_for_update()` on the claim bill row

---

## Database Tables

### `billing_master`

| Column | Type | Notes |
|--------|------|-------|
| `id` | Integer PK | |
| `billing_no` | String(50) | Sequential `001`, `002`… Certified bill copies claim bill's number. No unique constraint (same number exists for both modes of a pair). |
| `billing_uuid` | String(36) | UUID v4 — unique, indexed. Used for public shareable link. |
| `billing_date` | Date | |
| `mode` | String(30) | `sale_claim_bill` or `sale_certified_bill` |
| `claim_bill_id` | Integer FK → `billing_master.id` | NULL on claim bills. Points to parent claim bill on certified bills. `ondelete=SET NULL`. |
| `og_sale_order_no` | String(50) | OG Sale Order number. On certified bill: copied from claim bill. |
| `og_sale_order_id` | Integer FK → `og_sale_order_master.id` | Copied from claim bill on certified. |
| `project_code` | String(50) FK → `projects` | |
| `title` | String(500) | On certified: defaults to claim bill's title if not provided |
| `job_location` | String(500) | On certified: defaults to claim bill's job_location if not provided |
| `attachment` | Text | BunnyCDN URL. Path: `billing/<billing_no>/attachment` |
| `pre_certified_amount` | Numeric(14,2) | Sum of `this_bill_claim` of all **Approved** bills for same `og_sale_order_no + project_code + mode` |
| `this_bill_claim` | Numeric(14,2) | SUM of item `amount` |
| `gst_amount` | Numeric(14,2) | SUM of item `gst_amount` |
| `total_claim` | Numeric(14,2) | `pre_certified_amount + this_bill_claim` |
| `workflow_status` | String(30) | `Draft` / `Pending_L1` / `Pending_L2` / `Approved` / `Reback` / `Rejected` |
| `current_level` | Integer | Active approval level |
| `locked` | Boolean | True when submitted/approved — blocks editing |
| Audit columns | DateTime / FK | `created_by/at`, `updated_by/at`, `submitted_by/at`, `approved_by`, `final_approved_at`, `rejected_by/at`, `correction_sent_at` |

### `billing_items`

| Column | Type | Notes |
|--------|------|-------|
| `id` | Integer PK | |
| `billing_id` | Integer FK → `billing_master.id` | Cascade delete |
| `sl_no` | Integer | |
| `og_sale_order_item_id` | Integer FK → `og_sale_order_items.id` | Nullable |
| `item_code` | String(50) | Snapshotted from `OgSaleOrderItem.item_code` |
| `item_name` | Text | Snapshotted from `OgSaleOrderItem.item_name` |
| `item_name_desc` | Text | Snapshotted from `OgSaleOrderItem.item_description` |
| `unit` | String(30) | Snapshotted |
| `claim_qty` | Numeric(12,2) | |
| `rate` | Numeric(12,2) | |
| `amount` | Numeric(14,2) | Server-computed: `claim_qty × rate` |
| `gst_percent` | Numeric(5,2) | |
| `gst_amount` | Numeric(14,2) | Server-computed: `amount × gst_percent / 100` |

> **Snapshot chain:** Item Master → OG Sale Order Items (stores `item_name`, `item_description`) → Billing Items (snapshots from OG SO item at create/edit). `itemDisplayCode` (`cc_code + item_code`) is computed live from Item Master on every read — not stored.

---

## Workflow States

```
Draft ──[Submit]──> Pending_L1 ──[Approve]──> Pending_L2 ──[Approve]──> Approved
                         │
                         ├──[Reback]──> Reback ──[Edit + Submit]──> Pending_L1
                         └──[Reject]──> Rejected
```

- **Draft / Reback** → editable (create/edit allowed)
- **Pending / Approved / Rejected** → locked

**Workflow module codes:**

| Mode | Module code |
|------|-------------|
| `sale_claim_bill` | `sale_order_billing` |
| `sale_certified_bill` | `sale_certified_bill` |

---

## API Endpoints

| Method | URL | Auth | Description |
|--------|-----|------|-------------|
| GET | `/order-lookup` | JWT | Lookup OG SO or claim bill, get pre-populated items |
| POST | `/create` | JWT | Create a claim or certified bill |
| GET | `/list` | JWT | List bills with filters |
| GET | `/<id>` | JWT | Full details |
| PUT | `/edit/<id>` | JWT | Edit header + rebuild items (Draft/Reback only) |
| POST | `/submit/<id>` | JWT | Submit for approval |
| POST | `/approve/<id>` | JWT | Approve at current level |
| POST | `/reback/<id>` | JWT | Return for correction |
| POST | `/reject/<id>` | JWT | Reject permanently |
| GET | `/history/<id>` | JWT | Approval history + steps |
| GET | `/my-approval-status/<id>` | JWT | Current user's approval role |
| GET | `/uuid/<uuid>` | **None** | Public shareable view |

---

## 1. Order Lookup

**GET** `/order-lookup`

**For `sale_claim_bill`** — looks up OG Sale Order:
```
?projectCode=PROJ01&mode=sale_claim_bill&ogSaleOrderNo=OSO001
```

**For `sale_certified_bill`** — looks up Approved claim bill:
```
?projectCode=PROJ01&mode=sale_certified_bill&claimBillId=5
```

**Certified bill response:** items pre-populated from the claim bill's approved items (with `claimQty`, `rate` filled — user can change before saving).

---

## 2. Create

**POST** `/create` — `multipart/form-data`

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `projectCode` | string | Yes | |
| `mode` | string | Yes | `sale_claim_bill` or `sale_certified_bill` |
| `billingDate` | string | Yes | `YYYY-MM-DD` |
| `ogSaleOrderNo` | string | Claim only | Ignored for certified (copied from claim) |
| `claimBillId` | integer | Certified only | Must be an Approved `sale_claim_bill` in same project |
| `title` | string | No | |
| `jobLocation` | string | No | |
| `items` | JSON string | Yes | Array — see format below |
| `attachment` | file | No | Single file upload |

**Items JSON string:**
```json
[
  {
    "slNo": 1,
    "ogSaleOrderItemId": 12,
    "claimQty": 50.0,
    "rate": 5500.0,
    "gstPercent": 18.0
  }
]
```

- `amount` and `gstAmount` are always computed server-side — do not send
- If `ogSaleOrderItemId` provided, `item_code`, `item_name`, `unit` are snapshotted from OG SO item
- For certified bill: `billing_no` copied from claim bill — not auto-generated

---

## 3. List

**GET** `/list`

| Param | Required | Notes |
|-------|----------|-------|
| `projectCode` | Yes | |
| `mode` | No | Filter by mode |
| `ogSaleOrderNo` | No | Partial match |
| `workflowStatus` | No | Exact match |
| `search` | No | Matches `billing_no`, `og_sale_order_no`, `title` |

---

## 4. Details

**GET** `/<id>`

Key response fields:

```json
{
  "id": 7,
  "billingNo": "001",
  "mode": "sale_certified_bill",
  "claimBillId": 5,
  "claimBillingNo": "001",
  "ogSaleOrderNo": "OSO001",
  "preCertifiedAmount": 100000.0,
  "thisBillClaim": 275000.0,
  "gstAmount": 49500.0,
  "totalClaim": 375000.0,
  "orderBasicAmount": 550000.0,
  "billedAmount": 275000.0,
  "jobBalance": 275000.0,
  "workflowStatus": "Draft",
  "attachment": "https://cdn.bunny.net/billing/001/attachment",
  "items": [
    {
      "id": 1,
      "slNo": 1,
      "itemCode": "0042",
      "itemName": "Cement",
      "itemDisplayCode": "CC0010042",
      "itemDescription": "OPC 53 Grade",
      "orderQty": 100.0,
      "claimQty": 50.0,
      "rate": 5500.0,
      "amount": 275000.0,
      "gstPercent": 18.0,
      "gstAmount": 49500.0
    }
  ],
  "billsUnderOgSo": [
    { "id": 5, "billingNo": "001", "thisBillClaim": 275000.0, "workflowStatus": "Approved" }
  ]
}
```

---

## 5. Edit

**PUT** `/edit/<id>` — `multipart/form-data`

Same fields as Create. Restrictions:
- Only allowed when `workflow_status` is `Draft` or `Reback`
- `mode`, `ogSaleOrderNo`, `claimBillId` cannot be changed
- Attachment: kept unchanged if no new file uploaded

---

## 6–9. Workflow Actions

```
POST /submit/<id>                          → no body needed
POST /approve/<id>   { "comments": "ok" }
POST /reback/<id>    { "comments": "..." }   ← comments required
POST /reject/<id>    { "comments": "..." }   ← comments required
```

---

## Financial Logic

```
Per item (server-computed):
  amount     = claim_qty × rate
  gst_amount = amount × gst_percent / 100

Bill totals:
  this_bill_claim = SUM(item.amount)
  gst_amount      = SUM(item.gst_amount)
  total_claim     = pre_certified_amount + this_bill_claim

pre_certified_amount = SUM(this_bill_claim)
                       of all Approved bills
                       WHERE og_sale_order_no = X AND project_code = Y AND mode = Z
                       AND id != current_bill  (excluded on edit)
```

---

## File Structure

```
billing/
├── __init__.py
├── routes.py    — Flask Blueprint (12 routes)
├── service.py   — All business logic, helpers, workflow calls
└── README.md
```
