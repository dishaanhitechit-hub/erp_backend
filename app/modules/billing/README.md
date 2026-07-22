# Billing Module — API Reference

## Overview

Billing flow through BRR (Bill Receive Register):

```
BRR (Bill Receive Register)
 ├── BRG — BRR Billing GRN  (purchase order → GRN items)
 └── BRS — BRR Billing SRN  (project-work order → SRN items)
```

A BRR is created first. Once a BRR is approved, billing (BRG or BRS) is raised against the order linked to that BRR. The BRR list now returns all BRG and BRS records nested inside each BRR row.

---

## Serial Number Ranges

| Document | Base   | Example    |
|----------|--------|------------|
| BRR      | 900000 | `900001`   |
| BRG      | 910000 | `910001`   |
| BRS      | 920000 | `920001`   |

---

## Module Codes (for approval path setup)

| Document | Module Code            |
|----------|------------------------|
| BRR      | `bill_receive_register` |
| BRG      | `billing_by_brr_grn`   |
| BRS      | `billing_by_brr_srn`   |

---

## Workflow States

`Draft` → `Pending_L1` → `Pending_L2` → ... → `Approved`
                                              ↘ `Reback` → (edit) → resubmit
                                              ↘ `Rejected`

---

---

# 1. BRR — Bill Receive Register

**Base URL:** `/billing/brr`

---

### GET `/billing/brr/vendor-orders`

Fetch approved orders for a vendor + project (filter panel).

**Query params:**
| Param         | Required | Description              |
|---------------|----------|--------------------------|
| `vendorId`    | Yes      |                          |
| `projectCode` | Yes      |                          |
| `orderCategory` | No     | Filter by category code  |

**Response:**
```json
{
  "data": [
    {
      "id": 1,
      "orderNo": "810001",
      "orderDate": "2025-01-05",
      "categoryCode": "CIVIL",
      "basicAmount": 50000,
      "totalAmount": 59000
    }
  ]
}
```

---

### POST `/billing/brr/create`

Create a new BRR. Accepts `multipart/form-data` (supports file upload).

**Form fields:**
| Field              | Type   | Required | Description                    |
|--------------------|--------|----------|--------------------------------|
| `projectCode`      | string | Yes      |                                |
| `vendorId`         | int    | No       |                                |
| `orderCategory`    | string | No       |                                |
| `orderId`          | int    | No       | FK → `order_master` (GRN)      |
| `pwOrderId`        | int    | No       | FK → `pw_order_master` (SRN)   |
| `orderType`        | string | No       | `"GRN"` or `"SRN"`             |
| `partyBillNo`      | string | No       |                                |
| `partyDate`        | date   | No       |                                |
| `receivedCategory` | string | No       |                                |
| `submittedByName`  | string | No       |                                |
| `submissionDate`   | date   | No       |                                |
| `receivedThrough`  | string | No       |                                |
| `receivedReference`| string | No       |                                |
| `basicAmount`      | number | No       |                                |
| `gstAmount`        | number | No       |                                |
| `attachedDoc`      | file   | No       | Uploaded to CDN                |

**Response `201`:**
```json
{ "brrId": 1, "brrNo": "900001", "attachedDoc": "https://..." }
```

---

### GET `/billing/brr/list`

List BRRs with nested GRN and SRN billing records.

**Query params:**
| Param            | Required |
|------------------|----------|
| `projectCode`    | Yes      |
| `vendorId`       | No       |
| `workflowStatus` | No       |
| `search`         | No       |

**Response:**
```json
{
  "data": [
    {
      "id": 1,
      "brrNo": "900001",
      "brrDate": "2025-01-10",
      "projectCode": "PRJ001",
      "partyName": "ABC Suppliers",
      "orderCategory": "CIVIL",
      "orderNo": "810001",
      "orderDate": "2025-01-05",
      "partyBillNo": "INV-001",
      "partyDate": "2025-01-09",
      "basicAmount": 50000,
      "totalAmount": 59000,
      "bookedAmount": 59000,
      "workflowStatus": "Approved",

      "grnBillings": [
        {
          "brgId": 1,
          "brgNo": "910001",
          "brgDate": "2025-01-11",
          "workflowStatus": "Approved",
          "basicAmount": 30000,
          "gstAmount": 5400,
          "totalAmount": 35400,
          "itemCount": 3
        }
      ],

      "srnBillings": [
        {
          "brsId": 1,
          "brsNo": "920001",
          "brsDate": "2025-01-12",
          "workflowStatus": "Draft",
          "basicAmount": 20000,
          "gstAmount": 3600,
          "totalAmount": 23600,
          "itemCount": 2
        }
      ]
    }
  ]
}
```

---

### GET `/billing/brr/details/<brr_id>`

Full BRR details (header only, no billing lines).

---

### PUT `/billing/brr/edit/<brr_id>`

Edit a Draft or Reback BRR. Accepts `multipart/form-data`.

---

### POST `/billing/brr/submit/<brr_id>`

Submit BRR for approval.

---

### POST `/billing/brr/approve/<brr_id>`

**Body:** `{ "comments": "..." }`

---

### POST `/billing/brr/reback/<brr_id>`

**Body:** `{ "comments": "..." }` *(required)*

---

### POST `/billing/brr/reject/<brr_id>`

**Body:** `{ "comments": "..." }` *(required)*

---

### GET `/billing/brr/history/<brr_id>`

Approval history for a BRR.

---

---

# 2. BRG — BRR Billing GRN

Bills GRN items against a BRR that is linked to a purchase order (`order_master`).

**Base URL:** `/billing/brg`

---

### GET `/billing/brg/grns-by-brr/<brr_id>`

Fetches the purchase order and all its approved GRNs from the given BRR. Returns available qty per GRN line (already-billed BRG qty is deducted).

**Response:**
```json
{
  "data": {
    "brrId": 1,
    "brrNo": "900001",
    "orderId": 5,
    "orderNo": "810001",
    "orderDate": "2025-01-05",
    "vendorId": 10,
    "partyName": "ABC Suppliers",
    "partyAddress": "...",
    "partyGstn": "22AAAAA...",
    "projectCode": "PRJ001",
    "site": "PRJ001",
    "billingAddress": "...",
    "shippingAddress": "...",
    "grns": [
      {
        "grnId": 3,
        "grnNo": "830001",
        "grnDate": "2025-01-08",
        "items": [
          {
            "grnItemId": 12,
            "grnl": "GRNL001",
            "itemCode": "ITM001",
            "itemName": "Cement",
            "itemUnit": "Bag",
            "note": "OPC 43 grade",
            "receivedQty": 100,
            "alreadyBilled": 40,
            "availableQty": 60,
            "billingQty": 0,
            "rate": 350,
            "gstPercent": 18
          }
        ]
      }
    ]
  }
}
```

---

### POST `/billing/brg/create`

**Body (JSON):**
```json
{
  "brrId": 1,
  "brgDate": "2025-01-11",
  "projectCode": "PRJ001",
  "vendorId": 10,
  "orderId": 5,
  "receivedCategory": "CIVIL",
  "itemCategory": "CEMENT",
  "costHead": "MATERIAL",
  "partyBillNo": "INV-001",
  "partyDate": "2025-01-09",
  "site": "PRJ001",
  "billingAddress": "...",
  "shippingAddress": "...",
  "items": [
    { "grnItemId": 12, "billingQty": 60 }
  ]
}
```

**Response `201`:**
```json
{
  "brgId": 1,
  "brgNo": "910001",
  "ccSummary": [
    { "ccCode": "CC01", "ccName": "Civil", "basicAmount": 21000, "gstAmount": 3780, "totalAmount": 24780 }
  ]
}
```

> `rate` and `gstPercent` are pulled automatically from the order item — do not send them in the request.

---

### GET `/billing/brg/list`

**Query params:**
| Param            | Required |
|------------------|----------|
| `projectCode`    | Yes      |
| `vendorId`       | No       |
| `brrId`          | No       |
| `orderId`        | No       |
| `workflowStatus` | No       |
| `search`         | No       |

---

### GET `/billing/brg/details/<brg_id>`

Full BRG details including all item lines, CC summary, and available qty per line.

---

### PUT `/billing/brg/edit/<brg_id>`

Edit a Draft or Reback BRG. Same JSON body as create (items are wiped and rebuilt).

---

### POST `/billing/brg/submit/<brg_id>`

---

### POST `/billing/brg/approve/<brg_id>`

**Body:** `{ "comments": "..." }`

---

### POST `/billing/brg/reback/<brg_id>`

**Body:** `{ "comments": "..." }` *(required)*

---

### POST `/billing/brg/reject/<brg_id>`

**Body:** `{ "comments": "..." }` *(required)*

---

### GET `/billing/brg/history/<brg_id>`

---

---

# 3. BRS — BRR Billing SRN

Bills SRN items against a BRR that is linked to a project-work order (`pw_order_master`).

**Base URL:** `/billing/brs`

---

### GET `/billing/brs/srns-by-brr/<brr_id>`

Fetches the PW order and all its approved SRNs from the given BRR.

**Response:**
```json
{
  "data": {
    "brrId": 1,
    "brrNo": "900001",
    "orderId": 7,
    "orderNo": "820001",
    "orderDate": "2025-01-06",
    "vendorId": 10,
    "partyName": "XYZ Works",
    "projectCode": "PRJ001",
    "subCategoryCodes": ["SVC", "LABOUR"],
    "billingAddress": "...",
    "shippingAddress": "...",
    "srns": [
      {
        "srnId": 2,
        "srnNo": "840001",
        "srnDate": "2025-01-09",
        "items": [
          {
            "srnItemId": 8,
            "srnl": "SRNL001",
            "itemCode": "SVC001",
            "itemName": "Plastering Work",
            "itemUnit": "Sqft",
            "receivedQty": 500,
            "alreadyBilled": 0,
            "availableQty": 500,
            "billingQty": 0,
            "rate": 45,
            "gstPercent": 18
          }
        ]
      }
    ]
  }
}
```

---

### POST `/billing/brs/create`

**Body (JSON):**
```json
{
  "brrId": 1,
  "brsDate": "2025-01-12",
  "projectCode": "PRJ001",
  "vendorId": 10,
  "orderId": 7,
  "receivedCategory": "CIVIL",
  "itemCategory": ["SVC", "LABOUR"],
  "costHead": "LABOUR",
  "partyBillNo": "INV-002",
  "partyDate": "2025-01-11",
  "site": "PRJ001",
  "billingAddress": "...",
  "shippingAddress": "...",
  "items": [
    { "srnItemId": 8, "billingQty": 500 }
  ]
}
```

> `itemCategory` can be a JSON array or comma-separated string. `rate` and `gstPercent` are pulled from the PW order item automatically.

**Response `201`:**
```json
{
  "brsId": 1,
  "brsNo": "920001",
  "ccSummary": [
    { "ccCode": "CC02", "ccName": "Labour", "basicAmount": 22500, "gstAmount": 4050, "totalAmount": 26550 }
  ]
}
```

---

### GET `/billing/brs/list`

**Query params:** `projectCode` (required), `vendorId`, `brrId`, `orderId`, `workflowStatus`, `search`

---

### GET `/billing/brs/details/<brs_id>`

Full BRS details including all item lines and CC summary.

---

### PUT `/billing/brs/edit/<brs_id>`

Edit a Draft or Reback BRS. Same JSON body as create.

---

### POST `/billing/brs/submit/<brs_id>`

---

### POST `/billing/brs/approve/<brs_id>`

**Body:** `{ "comments": "..." }`

---

### POST `/billing/brs/reback/<brs_id>`

**Body:** `{ "comments": "..." }` *(required)*

---

### POST `/billing/brs/reject/<brs_id>`

**Body:** `{ "comments": "..." }` *(required)*

---

### GET `/billing/brs/history/<brs_id>`

---

---

## DB Tables

| Table           | Description                        |
|-----------------|------------------------------------|
| `brr_master`    | Bill Receive Register header       |
| `brg_master`    | BRR Billing GRN header             |
| `brg_items`     | BRR Billing GRN line items         |
| `brs_master`    | BRR Billing SRN header             |
| `brs_items`     | BRR Billing SRN line items         |

## FK Chain

```
brr_master.order_id      → order_master.id
brr_master.pw_order_id   → pw_order_master.id

brg_master.brr_id        → brr_master.id
brg_master.order_id      → order_master.id
brg_items.brg_id         → brg_master.id
brg_items.grn_id         → grn_master.id
brg_items.grn_item_id    → grn_items.id

brs_master.brr_id        → brr_master.id
brs_master.order_id      → pw_order_master.id
brs_items.brs_id         → brs_master.id
brs_items.srn_id         → srn_master.id
brs_items.srn_item_id    → srn_items.id
```
