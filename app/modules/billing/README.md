# Billing Module — API Reference

## Overview

```
BRR (Bill Receive Register)
 └── BRB — BRR Billing  (unified for GRN and SRN, driven by order category)
```

BRR is created first and linked to an order. The order's **category** automatically determines whether billing works through GRN items or SRN items — no separate BRG/BRS endpoints exist anymore.

---

## Category → Billing Type Rule

| Order Category          | Billing Type | Order Table       | Items From  |
|-------------------------|--------------|-------------------|-------------|
| `Purchases_Order`       | GRN          | `order_master`    | `grn_items` |
| `Customer_Supply_Order` | GRN          | `order_master`    | `grn_items` |
| `Site_Transfer_Order`   | GRN          | `order_master`    | `grn_items` |
| `Hire_Order`            | SRN          | `pw_order_master` | `srn_items` |
| `Job_Contract_Order`    | SRN          | `pw_order_master` | `srn_items` |
| `Work_Order`            | SRN          | `pw_order_master` | `srn_items` |

---

## Serial Number Ranges

| Document | Base   | Example  |
|----------|--------|----------|
| BRR      | 900000 | `900001` |
| BRB      | 910000 | `910001` |

---

## Module Codes (approval path setup)

| Document       | Module Code             |
|----------------|-------------------------|
| BRR            | `bill_receive_register` |
| BRB (GRN type) | `billing_by_grn`        |
| BRB (SRN type) | `billing_by_srn`        |

---

## Workflow States

```
Draft → Pending_L1 → Pending_L2 → ... → Approved
                                      ↘ Reback → (edit) → resubmit
                                      ↘ Rejected
```

---

---

# 1. BRR — Bill Receive Register

**Base URL:** `/billing/brr`

---

### GET `/billing/brr/vendor-orders`

Fetch approved orders for a vendor + project (order dropdown when creating BRR).

**Query params:**
| Param           | Required | Description       |
|-----------------|----------|-------------------|
| `vendorId`      | Yes      |                   |
| `projectCode`   | Yes      |                   |
| `orderCategory` | No       | Filter by category |

**Response:**
```json
{
  "data": [
    {
      "id": 30,
      "orderNo": "440022",
      "orderDate": "2025-01-05",
      "categoryCode": "Purchases_Order",
      "basicAmount": 50000,
      "totalAmount": 59000
    }
  ]
}
```

---

### POST `/billing/brr/create`

Create a new BRR. Accepts `multipart/form-data`.

**Form fields:**
| Field               | Type   | Required | Description                              |
|---------------------|--------|----------|------------------------------------------|
| `projectCode`       | string | Yes      |                                          |
| `vendorId`          | int    | No       |                                          |
| `orderCategory`     | string | No       | Must match one of the defined categories |
| `orderId`           | int    | No       | FK → `order_master` (GRN categories)     |
| `pwOrderId`         | int    | No       | FK → `pw_order_master` (SRN categories)  |
| `partyBillNo`       | string | No       |                                          |
| `partyDate`         | date   | No       |                                          |
| `receivedCategory`  | string | No       |                                          |
| `submittedByName`   | string | No       |                                          |
| `submissionDate`    | date   | No       |                                          |
| `receivedThrough`   | string | No       |                                          |
| `receivedReference` | string | No       |                                          |
| `basicAmount`       | number | No       |                                          |
| `gstAmount`         | number | No       |                                          |
| `attachedDoc`       | file   | No       |                                          |

**Response `201`:**
```json
{ "brrId": 1, "brrNo": "900001", "attachedDoc": "https://..." }
```

---

### GET `/billing/brr/list`

List BRRs with nested billing records split by type.

**Query params:** `projectCode` (required), `vendorId`, `workflowStatus`, `search`

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
      "orderCategory": "Purchases_Order",
      "orderNo": "440022",
      "orderDate": "2025-01-05",
      "partyBillNo": "INV-001",
      "basicAmount": 50000,
      "totalAmount": 59000,
      "workflowStatus": "Approved",
      "grnBillings": [
        {
          "brbId": 1,
          "brbNo": "910001",
          "brbDate": "2025-01-11",
          "billingType": "GRN",
          "workflowStatus": "Approved",
          "basicAmount": 30000,
          "gstAmount": 5400,
          "totalAmount": 35400,
          "itemCount": 3
        }
      ],
      "srnBillings": []
    }
  ]
}
```

---

### GET `/billing/brr/details/<brr_id>`

Full BRR header details.

---

### PUT `/billing/brr/edit/<brr_id>`

Edit a Draft or Reback BRR. Accepts `multipart/form-data`.

---

### POST `/billing/brr/submit/<brr_id>`

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

---

---

# 2. BRB — BRR Billing (Unified)

Handles both GRN and SRN billing in a single set of endpoints.
`billingType` (`"GRN"` or `"SRN"`) is derived automatically from the BRR's `orderCategory`.

**Base URL:** `/billing/brb`

---

### GET `/billing/brb/items-by-brr/<brr_id>`

Fetches available items for billing under a BRR.
- GRN category BRR → returns `grns[]` with GRN items and available qty
- SRN category BRR → returns `srns[]` with SRN items and available qty

Also returns BRR budget summary.

**Response (GRN example):**
```json
{
  "data": {
    "brrId": 1,
    "brrNo": "900001",
    "billingType": "GRN",
    "brrTotal": 59000,
    "billedSoFar": 20000,
    "remainingAmount": 39000,
    "orderId": 30,
    "orderNo": "440022",
    "orderDate": "2025-01-05",
    "vendorId": 10,
    "partyName": "ABC Suppliers",
    "partyAddress": "123 Main St",
    "partyGstn": "22AAAAA0000A1Z5",
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

**Response (SRN example):**
```json
{
  "data": {
    "brrId": 2,
    "brrNo": "900002",
    "billingType": "SRN",
    "brrTotal": 30000,
    "billedSoFar": 0,
    "remainingAmount": 30000,
    "orderId": 7,
    "orderNo": "820001",
    "orderDate": "2025-01-06",
    "vendorId": 11,
    "partyName": "XYZ Works",
    "partyAddress": "...",
    "partyGstn": "...",
    "projectCode": "PRJ001",
    "site": "PRJ001",
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

### POST `/billing/brb/create`

**Body (JSON) — GRN billing:**
```json
{
  "brrId": 1,
  "brbDate": "2025-01-11",
  "projectCode": "PRJ001",
  "itemCategory": ["CEMENT"],
  "costHead": "MATERIAL",
  "partyBillNo": "INV-001",
  "partyDate": "2025-01-09",
  "items": [
    { "grnItemId": 12, "billingQty": 60 }
  ]
}
```

**Body (JSON) — SRN billing:**
```json
{
  "brrId": 2,
  "brbDate": "2025-01-12",
  "projectCode": "PRJ001",
  "itemCategory": ["SVC", "LABOUR"],
  "costHead": "LABOUR",
  "partyBillNo": "INV-002",
  "partyDate": "2025-01-11",
  "items": [
    { "srnItemId": 8, "billingQty": 500 }
  ]
}
```

> `billingType`, `vendorId`, `orderId`, `billingAddress`, `shippingAddress` — all auto-derived from BRR → Order chain. Do NOT send them.

> `rate` and `gstPercent` are pulled from the order item automatically. Do NOT send them.

**Validations:**
- `billingQty` must not exceed `availableQty` per item
- Total amount must not exceed `remainingAmount` on the BRR

**Response `201`:**
```json
{
  "brbId": 1,
  "brbNo": "910001",
  "billingType": "GRN",
  "ccSummary": [
    {
      "ccCode": "CC01",
      "ccName": "Civil",
      "basicAmount": 21000,
      "gstAmount": 3780,
      "totalAmount": 24780
    }
  ]
}
```

---

### GET `/billing/brb/list`

**Query params:**
| Param            | Required | Description          |
|------------------|----------|----------------------|
| `projectCode`    | Yes      |                      |
| `billingType`    | No       | `"GRN"` or `"SRN"`  |
| `vendorId`       | No       |                      |
| `brrId`          | No       |                      |
| `orderId`        | No       |                      |
| `workflowStatus` | No       |                      |
| `search`         | No       | Search by BRB number |

**Response:**
```json
{
  "data": [
    {
      "id": 1,
      "brbNo": "910001",
      "brbDate": "2025-01-11",
      "billingType": "GRN",
      "projectCode": "PRJ001",
      "brrNo": "900001",
      "orderNo": "440022",
      "partyName": "ABC Suppliers",
      "itemCategory": ["CEMENT"],
      "costHead": "MATERIAL",
      "partyBillNo": "INV-001",
      "basicAmount": 21000,
      "totalAmount": 24780,
      "workflowStatus": "Draft"
    }
  ]
}
```

---

### GET `/billing/brb/details/<brb_id>`

Full BRB details. All vendor/order/address fields derived from BRR → Order chain.

**Response:**
```json
{
  "data": {
    "id": 1,
    "brbNo": "910001",
    "brbDate": "2025-01-11",
    "billingType": "GRN",
    "projectCode": "PRJ001",
    "brrId": 1,
    "brrNo": "900001",
    "vendorId": 10,
    "partyName": "ABC Suppliers",
    "partyAddress": "123 Main St",
    "partyGstn": "22AAAAA0000A1Z5",
    "orderId": 30,
    "orderNo": "440022",
    "orderDate": "2025-01-05",
    "orderCategory": "Purchases_Order",
    "site": "PRJ001",
    "billingAddress": "...",
    "shippingAddress": "...",
    "itemCategory": ["CEMENT"],
    "costHead": "MATERIAL",
    "partyBillNo": "INV-001",
    "partyDate": "2025-01-09",
    "basicAmount": 21000,
    "gstAmount": 3780,
    "totalAmount": 24780,
    "workflowStatus": "Draft",
    "currentLevel": 0,
    "locked": false,
    "items": [
      {
        "id": 1,
        "grnItemId": 12,
        "grnId": 3,
        "grnNo": "830001",
        "grnDate": "2025-01-08",
        "grnl": "GRNL001",
        "itemCode": "ITM001",
        "itemName": "Cement",
        "itemUnit": "Bag",
        "receivedQty": 100,
        "alreadyBilled": 60,
        "availableQty": 0,
        "billingQty": 60,
        "rate": 350,
        "amount": 21000,
        "gstPercent": 18,
        "gstAmount": 3780
      }
    ],
    "ccSummary": [
      {
        "ccCode": "CC01",
        "ccName": "Civil",
        "basicAmount": 21000,
        "gstAmount": 3780,
        "totalAmount": 24780
      }
    ]
  }
}
```

> For SRN billing, items contain `srnItemId`, `srnId`, `srnNo`, `srnDate`, `srnl` instead of GRN fields.

---

### PUT `/billing/brb/edit/<brb_id>`

Edit a Draft or Reback BRB. Items are wiped and rebuilt from scratch.

**Editable fields only:**
```json
{
  "brbDate": "2025-01-12",
  "partyBillNo": "INV-001-REV",
  "partyDate": "2025-01-10",
  "itemCategory": ["CEMENT", "STEEL"],
  "costHead": "MATERIAL",
  "items": [
    { "grnItemId": 12, "billingQty": 50 }
  ]
}
```

> `billingType`, `vendorId`, `orderId`, `billingAddress`, `shippingAddress` are not editable — always derived from the BRR → Order chain.

---

### POST `/billing/brb/submit/<brb_id>`

Submit for approval. Internally uses `billing_by_grn` or `billing_by_srn` module code depending on `billingType`.

---

### POST `/billing/brb/approve/<brb_id>`

**Body:** `{ "comments": "..." }`

---

### POST `/billing/brb/reback/<brb_id>`

**Body:** `{ "comments": "..." }` *(required)*

---

### POST `/billing/brb/reject/<brb_id>`

**Body:** `{ "comments": "..." }` *(required)*

---

### GET `/billing/brb/history/<brb_id>`

**Response:**
```json
{
  "data": [
    {
      "id": 1,
      "action": "SUBMIT",
      "level": 1,
      "comments": null,
      "actionBy": "john.doe",
      "createdAt": "2025-01-11 10:30:00"
    }
  ]
}
```

---

---

## DB Tables

| Table        | Description                                      |
|--------------|--------------------------------------------------|
| `brr_master` | Bill Receive Register header                     |
| `brb_master` | BRR Billing header — unified GRN + SRN           |
| `brb_items`  | BRR Billing line items                           |

## FK Chain

```
brr_master.order_id     → order_master.id        (GRN categories)
brr_master.pw_order_id  → pw_order_master.id     (SRN categories)

brb_master.brr_id       → brr_master.id
brb_items.brb_id        → brb_master.id
brb_items.grn_id        → grn_master.id          (GRN only, else NULL)
brb_items.grn_item_id   → grn_items.id           (GRN only, else NULL)
brb_items.srn_id        → srn_master.id          (SRN only, else NULL)
brb_items.srn_item_id   → srn_items.id           (SRN only, else NULL)
```

## brb_items — Two FK pairs, only one filled per row

| billing_type | grn_item_id | srn_item_id |
|--------------|-------------|-------------|
| GRN          | filled      | NULL        |
| SRN          | NULL        | filled      |

Same numeric ID in both columns (e.g. both = 5) is **not a collision** — they reference entirely different tables (`grn_items` vs `srn_items`) via separate FK constraints.
