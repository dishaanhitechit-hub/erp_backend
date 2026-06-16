# BSS — Vendor Billing by SRN

Base URL: `/resource/bss`
Auth: All endpoints require `Authorization: Bearer <JWT>` header.
Module Code: `billing_by_srn`
Content-Type: `application/json` (all endpoints — no file upload)

---

## How it Works

```
Vendor + Project
      ↓  filter (receivedCategory / itemCategory / costHead)
  PW Order List  (pw_order_master)
      ↓  select one order
  SRNs + Items  (approved SRNs for that pw_order)
      ↓  select multiple SRNs, pick items and set billingQty
  BSS created  →  workflow  →  Approved
```

**Available Qty rule:**
- `availableQty = srn_item.current_received_qty − sum(billingQty from non-Rejected BSS)`
- Draft / Pending / Reback / Approved BSS **counts** → reduces available qty
- Rejected BSS **does not count** → qty is freed back

---

## Table of Contents

1. [Get PW Orders by Vendor](#1-get-pw-orders-by-vendor)
2. [Get SRNs by Order](#2-get-srns-by-order)
3. [Create BSS](#3-create-bss)
4. [List](#4-bss-list)
5. [Details](#5-bss-details)
6. [Edit](#6-edit-bss)
7. [Submit](#7-submit-bss)
8. [Approve](#8-approve-bss)
9. [Reback](#9-reback-bss)
10. [Reject](#10-reject-bss)
11. [History](#11-bss-history)
12. [Workflow States](#workflow-states)
13. [DB Tables](#db-tables)

---

## 1. Get PW Orders by Vendor

Fetch approved PW orders for a vendor + project.

**GET** `/resource/bss/vendor-orders`

### Query Parameters

| Parameter        | Type   | Required | Description                                          |
|------------------|--------|----------|------------------------------------------------------|
| vendorId         | int    | Yes      | Vendor ID                                            |
| projectCode      | string | Yes      | Project code                                         |
| receivedCategory | string | No       | Filter by `pw_order_master.category_code`            |
| itemCategory     | string | No       | Filter by `pw_order_master.sub_codes` (JSON contains)|
| costHead         | string | No       | Filter by `pw_order_master.cost_head`                |

> **Note:** `sub_codes` is a JSON array string (e.g. `["SVC","COMP"]`) — filter uses ILIKE contains match.

**Filter logic (AND + fallback):**
1. Apply all provided filters together (AND)
2. If `receivedCategory` given but result is empty → retry with `itemCategory` + `costHead` only
3. If none provided → returns all approved PW orders for that vendor + project

### Success Response `200`

```json
{
  "message": "PW Orders fetched",
  "data": [
    {
      "id": 5,
      "orderNo": "550001",
      "orderDate": "2024-04-10",
      "categoryCode": "Service",
      "subCategoryCodes": ["SVC", "COMP"],
      "costHead": "Project_Work",
      "basicAmount": 80000.00,
      "totalAmount": 94400.00,
      "workflowStatus": "Approved"
    }
  ],
  "status": 200
}
```

### Error Responses

| Status | Message                |
|--------|------------------------|
| 400    | `vendorId required`    |
| 400    | `projectCode required` |
| 500    | Internal server error  |

---

## 2. Get SRNs by Order

Fetch all **Approved** SRNs for a PW order, with each item's available billing qty.

**GET** `/resource/bss/srns-by-order/<order_id>`

### Path Parameters

| Parameter | Type | Description       |
|-----------|------|-------------------|
| order_id  | int  | PW Order master ID |

### Success Response `200`

```json
{
  "message": "SRNs fetched for order",
  "data": {
    "orderId": 5,
    "orderNo": "550001",
    "orderDate": "2024-04-10",
    "vendorId": 3,
    "partyName": "XYZ Services Pvt Ltd",
    "partyAddress": "45, Park Street, Kolkata - 700016",
    "partyGstn": "19AABCX5678B1Z3",
    "projectCode": "PROJ-001",
    "site": "PROJ-001",
    "subCategoryCodes": ["SVC", "COMP"],
    "billingAddress": "Site Office, Block A",
    "shippingAddress": "Site Office, Block A",
    "srns": [
      {
        "srnId": 2,
        "srnNo": "730001",
        "srnDate": "2024-05-20",
        "items": [
          {
            "srnItemId": 4,
            "srnl": "SRNL001",
            "itemCode": "SVC001",
            "itemName": "Civil Repair Work",
            "itemUnit": "Job",
            "note": null,
            "receivedQty": 1.0,
            "alreadyBilled": 0.0,
            "availableQty": 1.0,
            "billingQty": 0,
            "rate": 50000.00,
            "gstPercent": 18.0,
            "useLocation": "Block B",
            "storeLocation": null
          }
        ]
      }
    ]
  },
  "status": 200
}
```

> `rate` and `gstPercent` are from the linked `pw_order_item`. Frontend shows these as read-only.

### Error Responses

| Status | Message               |
|--------|-----------------------|
| 404    | `PW Order not found`  |
| 500    | Internal server error |

---

## 3. Create BSS

**POST** `/resource/bss/create`

Content-Type: `application/json`

### Request Body

```json
{
  "bssDate": "2024-06-15",
  "projectCode": "PROJ-001",
  "vendorId": 3,
  "partyBillNo": "INV-SRV-099",
  "partyDate": "2024-06-12",
  "receivedCategory": "Service",
  "itemCategory": "SVC",
  "costHead": "Project_Work",
  "orderId": 5,
  "site": "PROJ-001",
  "billingAddress": "Site Office, Block A",
  "shippingAddress": "Site Office, Block A",
  "items": [
    { "srnItemId": 4, "billingQty": 1 },
    { "srnItemId": 6, "billingQty": 0.5 }
  ]
}
```

### Request Fields

| Field            | Type   | Required | Description                                  |
|------------------|--------|----------|----------------------------------------------|
| bssDate          | date   | Yes      | BSS date (`YYYY-MM-DD`)                      |
| projectCode      | string | Yes      | Project code                                 |
| vendorId         | int    | No       | Vendor ID                                    |
| partyBillNo      | string | No       | Party invoice number                         |
| partyDate        | date   | No       | Party invoice date (`YYYY-MM-DD`)            |
| receivedCategory | string | No       | Saved on BSS for reference                   |
| itemCategory     | string | No       | Saved on BSS for reference                   |
| costHead         | string | No       | Saved on BSS for reference                   |
| orderId          | int    | No       | Linked PW order ID                           |
| site             | string | No       | Site                                         |
| billingAddress   | string | No       | Billing address                              |
| shippingAddress  | string | No       | Shipping address                             |
| items            | array  | Yes      | Array of `{ srnItemId, billingQty }`         |

> `rate` and `gstPercent` are pulled automatically from the `pw_order_item` — do **not** send them.

### Success Response `201`

```json
{
  "message": "BSS created",
  "data": {
    "bssId": 1,
    "bssNo": "850001",
    "ccSummary": [
      {
        "ccCode": "CC002",
        "ccName": "Service Works",
        "basicAmount": 50000.00,
        "gstAmount": 9000.00,
        "totalAmount": 59000.00
      }
    ]
  },
  "status": 201
}
```

### Error Responses

| Status | Message                                          |
|--------|--------------------------------------------------|
| 403    | `You are not BSS creator`                        |
| 400    | `No items provided`                              |
| 400    | `Invalid billingQty for srnItemId {id}`          |
| 404    | `SRN item {id} not found`                        |
| 400    | `Only {n} qty available for SRN item {id}`       |
| 500    | Internal server error                            |

---

## 4. BSS List

**GET** `/resource/bss/list`

### Query Parameters

| Parameter      | Type   | Required | Description                      |
|----------------|--------|----------|----------------------------------|
| projectCode    | string | Yes      | Project code                     |
| vendorId       | int    | No       | Filter by vendor                 |
| orderId        | int    | No       | Filter by linked PW order        |
| workflowStatus | string | No       | Filter by workflow status        |
| search         | string | No       | Partial match on BSS number      |

### Success Response `200`

```json
{
  "message": "BSS list fetched",
  "data": [
    {
      "id": 1,
      "bssNo": "850001",
      "bssDate": "2024-06-15",
      "projectCode": "PROJ-001",
      "receivedCategory": "Service",
      "itemCategory": "SVC",
      "costHead": "Project_Work",
      "orderNo": "550001",
      "partyName": "XYZ Services Pvt Ltd",
      "partyBillNo": "INV-SRV-099",
      "basicAmount": 50000.00,
      "totalAmount": 59000.00,
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

## 5. BSS Details

**GET** `/resource/bss/details/<bss_id>`

### Success Response `200`

```json
{
  "message": "BSS details fetched",
  "data": {
    "id": 1,
    "bssNo": "850001",
    "bssDate": "2024-06-15",
    "projectCode": "PROJ-001",
    "vendorId": 3,
    "receivedCategory": "Service",
    "itemCategory": "SVC",
    "costHead": "Project_Work",
    "partyName": "XYZ Services Pvt Ltd",
    "partyAddress": "45, Park Street, Kolkata - 700016",
    "partyGstn": "19AABCX5678B1Z3",
    "partyBillNo": "INV-SRV-099",
    "partyDate": "2024-06-12",
    "orderId": 5,
    "orderNo": "550001",
    "orderDate": "2024-04-10",
    "site": "PROJ-001",
    "billingAddress": "Site Office, Block A",
    "shippingAddress": "Site Office, Block A",
    "basicAmount": 50000.00,
    "gstAmount": 9000.00,
    "totalAmount": 59000.00,
    "workflowStatus": "Draft",
    "currentLevel": 0,
    "locked": false,
    "items": [
      {
        "id": 1,
        "srnItemId": 4,
        "srnNo": "730001",
        "srnDate": "2024-05-20",
        "srnl": "SRNL001",
        "itemCode": "SVC001",
        "itemName": "Civil Repair Work",
        "itemUnit": "Job",
        "note": null,
        "receivedQty": 1.0,
        "alreadyBilled": 0.0,
        "availableQty": 1.0,
        "billingQty": 1.0,
        "rate": 50000.00,
        "amount": 50000.00,
        "gstPercent": 18.0,
        "gstAmount": 9000.00
      }
    ],
    "ccSummary": [
      {
        "ccCode": "CC002",
        "ccName": "Service Works",
        "basicAmount": 50000.00,
        "gstAmount": 9000.00,
        "totalAmount": 59000.00
      }
    ]
  },
  "status": 200
}
```

### Error Responses

| Status | Message           |
|--------|-------------------|
| 404    | `BSS not found`   |
| 500    | Internal server error |

---

## 6. Edit BSS

Only allowed when `workflowStatus` is `Draft` or `Reback` and `locked = false`.
Replaces all items on every edit.

**PUT** `/resource/bss/edit/<bss_id>`

Content-Type: `application/json`

```json
{
  "partyBillNo": "INV-SRV-100",
  "partyDate": "2024-06-13",
  "billingAddress": "Updated Address",
  "items": [
    { "srnItemId": 4, "billingQty": 1 },
    { "srnItemId": 6, "billingQty": 0.5 }
  ]
}
```

> All header fields optional. `items` is required.
> Old items are wiped first — `availableQty` recalculated excluding current BSS before validating new items.

### Success Response `200`

```json
{
  "message": "BSS updated successfully",
  "data": {
    "bssId": 1,
    "bssNo": "850001",
    "ccSummary": [...]
  },
  "status": 200
}
```

### Error Responses

| Status | Message                                          |
|--------|--------------------------------------------------|
| 404    | `BSS not found`                                  |
| 400    | `BSS cannot be edited` (locked)                  |
| 400    | `Only Draft or Reback BSS can be edited`         |
| 403    | `You are not BSS creator`                        |
| 400    | `Items required`                                 |
| 400    | `Invalid billingQty for srnItemId {id}`          |
| 404    | `SRN item {id} not found`                        |
| 400    | `Only {n} qty available for SRN item {id}`       |
| 500    | Internal server error                            |

---

## 7. Submit BSS

**POST** `/resource/bss/submit/<bss_id>`

No request body.

> If no approver configured for `billing_by_srn` → BSS auto-approved immediately.
> On Reback re-submit, `current_level` resets to 0.

### Success Response `200`

```json
{
  "message": "BSS submitted successfully",
  "data": {
    "bssId": 1,
    "bssNo": "850001",
    "workflowStatus": "Pending_L1"
  },
  "status": 200
}
```

### Error Responses

| Status | Message                 |
|--------|-------------------------|
| 404    | `BSS not found`         |
| 400    | `BSS already submitted` |
| 400    | `BSS has no items`      |
| 500    | Internal server error   |

---

## 8. Approve BSS

**POST** `/resource/bss/approve/<bss_id>`

```json
{ "comments": "Service bill verified." }
```

> More levels exist → moves to `Pending_L{next}`. Final level → `Approved`, `locked = true`.

### Success Response `200`

```json
{
  "message": "BSS approved successfully",
  "data": {
    "bssId": 1,
    "workflowStatus": "Approved",
    "currentLevel": 1
  },
  "status": 200
}
```

### Error Responses

| Status | Message                        |
|--------|--------------------------------|
| 404    | `BSS not found`                |
| 400    | `BSS not pending`              |
| 403    | `You are not current approver` |
| 500    | Internal server error          |

---

## 9. Reback BSS

**POST** `/resource/bss/reback/<bss_id>`

```json
{ "comments": "Qty mismatch for item SVC001." }
```

| Field    | Required |
|----------|----------|
| comments | Yes      |

> Sets `locked = false` so creator can edit and resubmit.

### Success Response `200`

```json
{
  "message": "BSS sent for correction",
  "data": { "bssId": 1, "workflowStatus": "Reback" },
  "status": 200
}
```

### Error Responses

| Status | Message                        |
|--------|--------------------------------|
| 404    | `BSS not found`                |
| 400    | `BSS not pending`              |
| 400    | `Comments required`            |
| 403    | `You are not current approver` |
| 500    | Internal server error          |

---

## 10. Reject BSS

**POST** `/resource/bss/reject/<bss_id>`

```json
{ "comments": "Invoice does not match SRN records." }
```

| Field    | Required |
|----------|----------|
| comments | Yes      |

> `locked = true`, `status = Inactive`. All `billingQty` freed — `availableQty` restored for other BSS.

### Success Response `200`

```json
{
  "message": "BSS rejected",
  "data": { "bssId": 1, "workflowStatus": "Rejected" },
  "status": 200
}
```

### Error Responses

| Status | Message                        |
|--------|--------------------------------|
| 404    | `BSS not found`                |
| 400    | `BSS not pending`              |
| 400    | `Comments required`            |
| 403    | `You are not current approver` |
| 500    | Internal server error          |

---

## 11. BSS History

**GET** `/resource/bss/history/<bss_id>`

### Success Response `200`

```json
{
  "message": "BSS history fetched",
  "data": [
    { "id": 1, "action": "SUBMIT",        "level": 0, "comments": null,                    "actionBy": "john.doe", "createdAt": "2024-06-15 10:00:00" },
    { "id": 2, "action": "REBACK",        "level": 1, "comments": "Qty mismatch.",          "actionBy": "manager",  "createdAt": "2024-06-15 14:30:00" },
    { "id": 3, "action": "SUBMIT",        "level": 0, "comments": null,                    "actionBy": "john.doe", "createdAt": "2024-06-16 09:00:00" },
    { "id": 4, "action": "FINAL_APPROVE", "level": 1, "comments": "Service bill verified.", "actionBy": "manager",  "createdAt": "2024-06-16 11:00:00" }
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

### `bss_master`

| Column             | Type          | Notes                                      |
|--------------------|---------------|--------------------------------------------|
| id                 | int PK        |                                            |
| bss_no             | varchar(50)   | Unique serial starting from 850001         |
| bss_date           | date          | Required                                   |
| project_code       | varchar(50)   | FK → projects.project_code                 |
| vendor_id          | int           | FK → vendors.id                            |
| received_category  | varchar(100)  | Saved from filter for reference            |
| item_category      | varchar(100)  | Saved from filter for reference            |
| cost_head          | varchar(100)  | Saved from filter for reference            |
| party_bill_no      | varchar(100)  |                                            |
| party_date         | date          |                                            |
| order_id           | int           | FK → pw_order_master.id                    |
| site               | varchar(200)  |                                            |
| billing_address    | text          |                                            |
| shipping_address   | text          |                                            |
| basic_amount       | numeric(14,2) |                                            |
| gst_amount         | numeric(14,2) |                                            |
| total_amount       | numeric(14,2) |                                            |
| workflow_status    | varchar(30)   | Default: Draft                             |
| current_level      | int           | Default: 0                                 |
| locked             | boolean       | Default: false                             |
| status             | varchar(20)   | Set to Inactive on Reject                  |
| created_by         | int           | FK → users.id                              |
| submitted_by       | int           | FK → users.id                              |
| approved_by        | int           | FK → users.id                              |
| rejected_by        | int           | FK → users.id                              |
| updated_by         | int           | FK → users.id                              |
| submitted_at       | datetime      |                                            |
| final_approved_at  | datetime      |                                            |
| rejected_at        | datetime      |                                            |
| correction_sent_at | datetime      |                                            |
| created_at         | datetime      | Auto                                       |
| updated_at         | datetime      | Auto                                       |

### `bss_items`

| Column      | Type          | Notes                                |
|-------------|---------------|--------------------------------------|
| id          | int PK        |                                      |
| bss_id      | int           | FK → bss_master.id                   |
| srn_item_id | int           | FK → srn_items.id                    |
| billing_qty | numeric(12,2) |                                      |
| rate        | numeric(12,2) | Copied from pw_order_item at save    |
| amount      | numeric(14,2) | billing_qty × rate                   |
| gst_percent | numeric(5,2)  | Copied from pw_order_item            |
| gst_amount  | numeric(14,2) | amount × gst_percent / 100           |
| created_at  | datetime      | Auto                                 |

---

## Migration

```bash
flask db migrate -m "add bss tables"
flask db upgrade
```

### module_master entry (required before workflow actions work)

```sql
INSERT INTO module_master (module_code, module_name)
VALUES ('billing_by_srn', 'Vendor Billing by SRN');
```

---

## Notes

- **No file upload** — BSS uses `application/json` (no `multipart/form-data`)
- **rate & gst pulled automatically** from `pw_order_item` — do not send from frontend
- **CC Summary** returned on create, edit, and details responses
- **alreadyBilled** counts Draft + Pending + Reback + Approved BSS items, excludes Rejected
- **itemCategory filter** uses ILIKE JSON contains match on `sub_codes` (stored as JSON array string)
- **Module code** is `billing_by_srn` — use this for workflow alias and module_master setup
