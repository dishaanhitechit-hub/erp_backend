# BVS — Vendor Billing by GRN

Base URL: `/resource/bvs`
Auth: All endpoints require `Authorization: Bearer <JWT>` header.
Module Code: `billing_by_grn`
Content-Type: `application/json` (all endpoints — no file upload)

---

## How it Works

```
Vendor + Project
      ↓  filter (receivedCategory / itemCategory / costHead)
  Order List
      ↓  select one order
  GRNs + Items  (approved GRNs for that order)
      ↓  select multiple GRNs, pick items and set billingQty
  BVS created  →  workflow  →  Approved
```

**Available Qty rule:**
- `availableQty = grn_item.receivedQty − sum(billingQty from non-Rejected BVS)`
- Draft / Pending / Reback / Approved BVS **counts** → reduces available qty
- Rejected BVS **does not count** → qty is freed back
- Items with `availableQty = 0` are still returned (for visibility)

---

## Table of Contents

1. [Get Orders by Vendor](#1-get-orders-by-vendor)
2. [Get GRNs by Order](#2-get-grns-by-order)
3. [Create BVS](#3-create-bvs)
4. [List](#4-bvs-list)
5. [Details](#5-bvs-details)
6. [Edit](#6-edit-bvs)
7. [Submit](#7-submit-bvs)
8. [Approve](#8-approve-bvs)
9. [Reback](#9-reback-bvs)
10. [Reject](#10-reject-bvs)
11. [History](#11-bvs-history)
12. [Workflow States](#workflow-states)
13. [DB Tables](#db-tables)

---

## 1. Get Orders by Vendor

**GET** `/resource/bvs/vendor-orders`

### Query Parameters

| Parameter        | Type   | Required | Description                            |
|------------------|--------|----------|----------------------------------------|
| vendorId         | int    | Yes      | Vendor ID                              |
| projectCode      | string | Yes      | Project code                           |
| receivedCategory | string | No       | Filter by `order_master.category_code` |
| itemCategory     | string | No       | Filter by `order_master.sub_code`      |
| costHead         | string | No       | Filter by `order_master.cost_head`     |

**Filter logic (AND + fallback):**
1. Apply all provided filters together (AND)
2. If `receivedCategory` was given but result is empty → retry with `itemCategory` + `costHead` only
3. If none provided → returns all approved orders for that vendor + project

### Success Response `200`

```json
{
  "message": "Orders fetched",
  "data": [
    {
      "id": 12,
      "orderNo": "440001",
      "orderDate": "2024-03-15",
      "categoryCode": "Material",
      "subCode": "Civil",
      "costHead": "Project Work /Fixed Asset",
      "basicAmount": 150000.00,
      "totalAmount": 177000.00,
      "workflowStatus": "Approved"
    }
  ],
  "status": 200
}
```

### Error Responses

| Status | Message                  |
|--------|--------------------------|
| 400    | `vendorId required`      |
| 400    | `projectCode required`   |
| 500    | Internal server error    |

---

## 2. Get GRNs by Order

Fetch all **Approved** GRNs for an order with each item's available billing qty.

**GET** `/resource/bvs/grns-by-order/<order_id>`

### Success Response `200`

```json
{
  "message": "GRNs fetched for order",
  "data": {
    "orderId": 12,
    "orderNo": "440001",
    "orderDate": "2024-03-15",
    "vendorId": 5,
    "partyName": "ABC Suppliers Pvt Ltd",
    "partyAddress": "123, Main Road, Kolkata - 700001",
    "partyGstn": "19AABCA1234A1Z5",
    "projectCode": "PROJ-001",
    "site": "PROJ-001",
    "billingAddress": "Site Office, Block A",
    "shippingAddress": "Site Office, Block A",
    "grns": [
      {
        "grnId": 3,
        "grnNo": "720001",
        "grnDate": "2024-05-10",
        "items": [
          {
            "grnItemId": 7,
            "grnl": "GRNL001",
            "itemCode": "CCWS002",
            "itemName": "Shuttering Ply 12thk",
            "itemUnit": "SqM",
            "note": null,
            "receivedQty": 100.0,
            "alreadyBilled": 40.0,
            "availableQty": 60.0,
            "billingQty": 0,
            "rate": 250.00,
            "gstPercent": 18.0,
            "useLocation": "Block B",
            "storeLocation": "Store 1"
          }
        ]
      }
    ]
  },
  "status": 200
}
```

> `rate` and `gstPercent` are from the linked `order_item`. Frontend shows these as read-only.

### Error Responses

| Status | Message           |
|--------|-------------------|
| 404    | `Order not found` |
| 500    | Internal server error |

---

## 3. Create BVS

**POST** `/resource/bvs/create`

Content-Type: `application/json`

### Request Body

```json
{
  "bvsDate": "2024-06-12",
  "projectCode": "PROJ-001",
  "vendorId": 5,
  "partyBillNo": "INV-2024-099",
  "partyDate": "2024-06-10",
  "receivedCategory": "Material",
  "itemCategory": "Civil",
  "costHead": "Project Work /Fixed Asset",
  "orderId": 12,
  "site": "PROJ-001",
  "billingAddress": "Site Office, Block A",
  "shippingAddress": "Site Office, Block A",
  "items": [
    { "grnItemId": 7, "billingQty": 50 },
    { "grnItemId": 9, "billingQty": 20 }
  ]
}
```

### Request Fields

| Field            | Type   | Required | Description                                      |
|------------------|--------|----------|--------------------------------------------------|
| bvsDate          | date   | Yes      | BVS date (`YYYY-MM-DD`)                          |
| projectCode      | string | Yes      | Project code                                     |
| vendorId         | int    | No       | Vendor ID                                        |
| partyBillNo      | string | No       | Party invoice number                             |
| partyDate        | date   | No       | Party invoice date (`YYYY-MM-DD`)                |
| receivedCategory | string | No       | Saved on BVS for reference                       |
| itemCategory     | string | No       | Saved on BVS for reference                       |
| costHead         | string | No       | Saved on BVS for reference                       |
| orderId          | int    | No       | Linked order ID                                  |
| site             | string | No       | Site                                             |
| billingAddress   | string | No       | Billing address                                  |
| shippingAddress  | string | No       | Shipping address                                 |
| items            | array  | Yes      | Array of `{ grnItemId, billingQty }`             |

> `rate` and `gstPercent` are pulled automatically from the `order_item` — do **not** send them.

### Success Response `201`

```json
{
  "message": "BVS created",
  "data": {
    "bvsId": 1,
    "bvsNo": "840001",
    "ccSummary": [
      {
        "ccCode": "CC001",
        "ccName": "Civil Works",
        "basicAmount": 12500.00,
        "gstAmount": 2250.00,
        "totalAmount": 14750.00
      }
    ]
  },
  "status": 201
}
```

### Error Responses

| Status | Message                                         |
|--------|-------------------------------------------------|
| 403    | `You are not BVS creator`                       |
| 400    | `No items provided`                             |
| 400    | `Invalid billingQty for grnItemId {id}`         |
| 404    | `GRN item {id} not found`                       |
| 400    | `Only {n} qty available for GRN item {id}`      |
| 500    | Internal server error                           |

---

## 4. BVS List

**GET** `/resource/bvs/list`

### Query Parameters

| Parameter      | Type   | Required | Description                      |
|----------------|--------|----------|----------------------------------|
| projectCode    | string | Yes      | Project code                     |
| vendorId       | int    | No       | Filter by vendor                 |
| orderId        | int    | No       | Filter by linked order           |
| workflowStatus | string | No       | Filter by workflow status        |
| search         | string | No       | Partial match on BVS number      |

### Success Response `200`

```json
{
  "message": "BVS list fetched",
  "data": [
    {
      "id": 1,
      "bvsNo": "840001",
      "bvsDate": "2024-06-12",
      "projectCode": "PROJ-001",
      "recievedCategory": "Material",
      "itemCategory": "Civil",
      "costHead": "Project Work /Fixed Asset",
      "orderNo": "440001",
      "partyName": "ABC Suppliers Pvt Ltd",
      "partyBillNo": "INV-2024-099",
      "basicAmount": 12500.00,
      "totalAmount": 14750.00,
      "workflowStatus": "Draft"
    }
  ],
  "status": 200
}
```

### Error Responses

| Status | Message                |
|--------|------------------------|
| 400    | `projectCode required` |
| 500    | Internal server error  |

---

## 5. BVS Details

**GET** `/resource/bvs/details/<bvs_id>`

### Success Response `200`

```json
{
  "message": "BVS details fetched",
  "data": {
    "id": 1,
    "bvsNo": "840001",
    "bvsDate": "2024-06-12",
    "projectCode": "PROJ-001",
    "vendorId": 5,
    "recievedCategory": "Material",
    "itemCategory": "Civil",
    "costHead": "Project Work /Fixed Asset",
    "partyName": "ABC Suppliers Pvt Ltd",
    "partyAddress": "123, Main Road, Kolkata - 700001",
    "partyGstn": "19AABCA1234A1Z5",
    "partyBillNo": "INV-2024-099",
    "partyDate": "2024-06-10",
    "orderId": 12,
    "orderNo": "440001",
    "orderDate": "2024-03-15",
    "site": "PROJ-001",
    "billingAddress": "Site Office, Block A",
    "shippingAddress": "Site Office, Block A",
    "basicAmount": 12500.00,
    "gstAmount": 2250.00,
    "totalAmount": 14750.00,
    "workflowStatus": "Draft",
    "currentLevel": 0,
    "locked": false,
    "items": [
      {
        "id": 1,
        "grnItemId": 7,
        "grnNo": "720001",
        "grnl": "GRNL001",
        "itemCode": "CCWS002",
        "itemName": "Shuttering Ply 12thk",
        "itemUnit": "SqM",
        "note": null,
        "receivedQty": 100.0,
        "alreadyBilled": 40.0,
        "availableQty": 60.0,
        "billingQty": 50.0,
        "rate": 250.00,
        "amount": 12500.00,
        "gstPercent": 18.0,
        "gstAmount": 2250.00
      }
    ],
    "ccSummary": [
      {
        "ccCode": "CC001",
        "ccName": "Civil Works",
        "basicAmount": 12500.00,
        "gstAmount": 2250.00,
        "totalAmount": 14750.00
      }
    ]
  },
  "status": 200
}
```

### Error Responses

| Status | Message           |
|--------|-------------------|
| 404    | `BVS not found`   |
| 500    | Internal server error |

---

## 6. Edit BVS

Only allowed when `workflowStatus` is `Draft` or `Reback` and `locked = false`.
Replaces all items on every edit.

**PUT** `/resource/bvs/edit/<bvs_id>`

Content-Type: `application/json`

```json
{
  "partyBillNo": "INV-2024-100",
  "partyDate": "2024-06-11",
  "billingAddress": "Updated Address",
  "items": [
    { "grnItemId": 7, "billingQty": 60 },
    { "grnItemId": 9, "billingQty": 10 }
  ]
}
```

> All header fields are optional. `items` is required.
> During edit, old items are wiped first — so `availableQty` is recalculated excluding current BVS before validating new items.

### Success Response `200`

```json
{
  "message": "BVS updated successfully",
  "data": {
    "bvsId": 1,
    "bvsNo": "840001",
    "ccSummary": [...]
  },
  "status": 200
}
```

### Error Responses

| Status | Message                                         |
|--------|-------------------------------------------------|
| 404    | `BVS not found`                                 |
| 400    | `BVS cannot be edited` (locked)                 |
| 400    | `Only Draft or Reback BVS can be edited`        |
| 403    | `You are not BVS creator`                       |
| 400    | `Items required`                                |
| 400    | `Invalid billingQty for grnItemId {id}`         |
| 404    | `GRN item {id} not found`                       |
| 400    | `Only {n} qty available for GRN item {id}`      |
| 500    | Internal server error                           |

---

## 7. Submit BVS

**POST** `/resource/bvs/submit/<bvs_id>`

No request body.

> If no approver is configured for `billing_by_grn` in the project, BVS is auto-approved immediately.
> On Reback re-submit, `current_level` resets to 0 (back to L1).

### Success Response `200`

```json
{
  "message": "BVS submitted successfully",
  "data": {
    "bvsId": 1,
    "bvsNo": "840001",
    "workflowStatus": "Pending_L1"
  },
  "status": 200
}
```

### Error Responses

| Status | Message                    |
|--------|----------------------------|
| 404    | `BVS not found`            |
| 400    | `BVS already submitted`    |
| 400    | `BVS has no items`         |
| 500    | Internal server error      |

---

## 8. Approve BVS

**POST** `/resource/bvs/approve/<bvs_id>`

```json
{ "comments": "Bill verified against GRNs." }
```

> If more approval levels exist → moves to `Pending_L{next}`.
> If this is the final level → `workflowStatus = Approved`, `locked = true`.

### Success Response `200`

```json
{
  "message": "BVS approved successfully",
  "data": {
    "bvsId": 1,
    "workflowStatus": "Approved",
    "currentLevel": 1
  },
  "status": 200
}
```

### Error Responses

| Status | Message                      |
|--------|------------------------------|
| 404    | `BVS not found`              |
| 400    | `BVS not pending`            |
| 403    | `You are not current approver` |
| 500    | Internal server error        |

---

## 9. Reback BVS

**POST** `/resource/bvs/reback/<bvs_id>`

```json
{ "comments": "Billing qty mismatch for item CCWS002." }
```

| Field    | Required |
|----------|----------|
| comments | Yes      |

> Sets `locked = false` so creator can edit and resubmit.

### Success Response `200`

```json
{
  "message": "BVS sent for correction",
  "data": { "bvsId": 1, "workflowStatus": "Reback" },
  "status": 200
}
```

### Error Responses

| Status | Message                        |
|--------|--------------------------------|
| 404    | `BVS not found`                |
| 400    | `BVS not pending`              |
| 400    | `Comments required`            |
| 403    | `You are not current approver` |
| 500    | Internal server error          |

---

## 10. Reject BVS

**POST** `/resource/bvs/reject/<bvs_id>`

```json
{ "comments": "Invoice does not match GRN records." }
```

| Field    | Required |
|----------|----------|
| comments | Yes      |

> On rejection `locked = true`, `status = Inactive`. All `billingQty` in this BVS is freed — `availableQty` increases for other BVS referencing those GRN items.

### Success Response `200`

```json
{
  "message": "BVS rejected",
  "data": { "bvsId": 1, "workflowStatus": "Rejected" },
  "status": 200
}
```

### Error Responses

| Status | Message                        |
|--------|--------------------------------|
| 404    | `BVS not found`                |
| 400    | `BVS not pending`              |
| 400    | `Comments required`            |
| 403    | `You are not current approver` |
| 500    | Internal server error          |

---

## 11. BVS History

**GET** `/resource/bvs/history/<bvs_id>`

### Success Response `200`

```json
{
  "message": "BVS history fetched",
  "data": [
    { "id": 1, "action": "SUBMIT",        "level": 0, "comments": null,                          "actionBy": "john.doe", "createdAt": "2024-06-12 10:00:00" },
    { "id": 2, "action": "REBACK",        "level": 1, "comments": "Billing qty mismatch.",        "actionBy": "manager",  "createdAt": "2024-06-12 14:22:00" },
    { "id": 3, "action": "SUBMIT",        "level": 0, "comments": null,                          "actionBy": "john.doe", "createdAt": "2024-06-13 09:10:00" },
    { "id": 4, "action": "FINAL_APPROVE", "level": 1, "comments": "Bill verified against GRNs.", "actionBy": "manager",  "createdAt": "2024-06-13 11:45:00" }
  ],
  "status": 200
}
```

**Possible `action` values:** `SUBMIT`, `APPROVE`, `FINAL_APPROVE`, `REBACK`, `REJECT`

---

## Workflow States

```
Draft → [Submit] → Pending_L1 → [Approve] → Pending_L2 → ... → Approved
                              → [Reback]  → Reback → [Submit] → Pending_L1
                              → [Reject]  → Rejected  ← billingQty freed back
```

| Status       | Editable | Locked | billingQty counted in alreadyBilled |
|--------------|----------|--------|-------------------------------------|
| Draft        | Yes      | No     | Yes                                 |
| Pending_L{n} | No       | Yes    | Yes                                 |
| Reback       | Yes      | No     | Yes                                 |
| Approved     | No       | Yes    | Yes                                 |
| Rejected     | No       | Yes    | **No** (freed back)                 |

---

## DB Tables

### `bvs_master`

| Column             | Type          | Notes                               |
|--------------------|---------------|-------------------------------------|
| id                 | int PK        |                                     |
| bvs_no             | varchar(50)   | Unique serial starting from 840001  |
| bvs_date           | date          |                                     |
| project_code       | varchar(50)   | FK → projects.project_code          |
| vendor_id          | int           | FK → vendors.id                     |
| party_bill_no      | varchar(100)  |                                     |
| party_date         | date          |                                     |
| received_category  | varchar(100)  | Saved from filter for reference     |
| item_category      | varchar(100)  | Saved from filter for reference     |
| cost_head          | varchar(100)  | Saved from filter for reference     |
| order_id           | int           | FK → order_master.id                |
| site               | varchar(200)  |                                     |
| billing_address    | text          |                                     |
| shipping_address   | text          |                                     |
| basic_amount       | numeric(14,2) |                                     |
| gst_amount         | numeric(14,2) |                                     |
| total_amount       | numeric(14,2) |                                     |
| workflow_status    | varchar(30)   | Default: Draft                      |
| current_level      | int           | Default: 0                          |
| locked             | boolean       | Default: false                      |
| status             | varchar(20)   | Set to Inactive on Reject           |
| created_by         | int           | FK → users.id                       |
| submitted_by       | int           | FK → users.id                       |
| approved_by        | int           | FK → users.id                       |
| rejected_by        | int           | FK → users.id                       |
| updated_by         | int           | FK → users.id                       |
| submitted_at       | datetime      |                                     |
| final_approved_at  | datetime      |                                     |
| rejected_at        | datetime      |                                     |
| correction_sent_at | datetime      |                                     |
| created_at         | datetime      | Auto                                |
| updated_at         | datetime      | Auto                                |

### `bvs_items`

| Column      | Type          | Notes                                |
|-------------|---------------|--------------------------------------|
| id          | int PK        |                                      |
| bvs_id      | int           | FK → bvs_master.id                   |
| grn_item_id | int           | FK → grn_items.id                    |
| billing_qty | numeric(12,2) |                                      |
| rate        | numeric(12,2) | Copied from order_item at save time  |
| amount      | numeric(14,2) | billing_qty × rate                   |
| gst_percent | numeric(5,2)  | Copied from order_item               |
| gst_amount  | numeric(14,2) | amount × gst_percent / 100           |
| created_at  | datetime      | Auto                                 |

---

## Migration

```bash
flask db migrate -m "add bvs tables"
flask db upgrade
```

### module_master entry (required before workflow actions work)

```sql
INSERT INTO module_master (module_code, module_name)
VALUES ('billing_by_grn', 'Vendor Billing by GRN');
```

---

## Notes

- **No file upload** — BVS uses `application/json` (no `multipart/form-data`)
- **rate & gst pulled automatically** from `order_item` — do not send from frontend
- **CC Summary** returned on create, edit, and details responses
- **alreadyBilled** counts Draft + Pending + Reback + Approved BVS items, excludes Rejected
- **Module code** is `billing_by_grn` (not `vendor_billing_grn`) — use this for workflow alias setup
