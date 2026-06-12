# SRN — Service Received Note

Base URL: `/resource/srn`
Auth: All endpoints require `Authorization: Bearer <JWT>` header.
Workflow Module Code: `srn` (resolved via `workflow_module_alias` — set your alias there)
Order Source: `pw_order_master` / `pw_order_items`

---

## Key Difference from GRN

| | GRN | SRN |
|---|---|---|
| Order source | `order_master` / `order_items` | `pw_order_master` / `pw_order_items` |
| Filter panel | `vendorId`, `receivedCategory`, `itemCategory`, `costHead` | `vendorId`, `categoryCode`, `subCategoryCode`, `costHead` |
| Indent info | Shown (`indentNo`) | Not shown (pw_order has no indent linkage) |
| Workflow alias | hardcoded `goods_received_note` | resolves via `workflow_module_alias` table for `srn` |
| Item key | `orderItemId` | `pwOrderItemId` |

---

## Table of Contents

1. [Get PW Orders by Vendor](#1-get-pw-orders-by-vendor)
2. [Get PW Order Items for SRN Grid](#2-get-pw-order-items-for-srn-grid)
3. [Create SRN](#3-create-srn)
4. [SRN List](#4-srn-list)
5. [SRN Details](#5-srn-details)
6. [Submit SRN](#6-submit-srn)
7. [Approve SRN](#7-approve-srn)
8. [Reback SRN](#8-reback-srn)
9. [Reject SRN](#9-reject-srn)
10. [Edit SRN](#10-edit-srn)
11. [History](#11-srn-history)
12. [Workflow States](#workflow-states)
13. [DB Tables](#db-tables)

---

## 1. Get PW Orders by Vendor

Fetch approved PW orders for a vendor + project. Used to populate the Order No filter dropdown.

**GET** `/resource/srn/vendor-orders`

### Query Parameters

| Parameter       | Type   | Required | Description                                          |
|-----------------|--------|----------|------------------------------------------------------|
| vendorId        | int    | Yes      | Vendor ID                                            |
| projectCode     | string | Yes      | Project code                                         |
| categoryCode    | string | No       | Filter by `pw_order_master.category_code`            |
| subCategoryCode | string | No       | Filter by JSON contains in `pw_order_master.sub_codes` |
| costHead        | string | No       | Filter by `pw_order_master.cost_head`                |

> All filters apply as AND. **Fallback:** if `categoryCode` is provided but yields no results, the query retries using only `subCategoryCode` + `costHead`.

### Success Response `200`

```json
{
  "message": "PW Orders fetched",
  "data": [
    {
      "id": 8,
      "orderNo": "550001",
      "orderDate": "2024-04-10",
      "categoryCode": "Service",
      "subCategoryCodes": ["SVC", "COMP"],
      "costHead": "Project Work /Fixed Asset",
      "basicAmount": 200000.00,
      "totalAmount": 236000.00,
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

## 2. Get PW Order Items for SRN Grid

Fetch items of a PW order to populate the SRN item grid.
Returns `preReceivedQty` (already received in other SRNs) and `balanceQty`.
**No indent info** — pw_order has no indent linkage.

**GET** `/resource/srn/order-items/<order_id>`

### Path Parameters

| Parameter | Type | Description       |
|-----------|------|-------------------|
| order_id  | int  | PW Order master ID |

### Success Response `200`

```json
{
  "message": "PW Order items fetched",
  "data": {
    "orderId": 8,
    "orderNo": "550001",
    "orderDate": "2024-04-10",
    "vendorId": 5,
    "partyName": "XYZ Services Pvt Ltd",
    "partyAddress": "45, Park Street, Kolkata - 700016",
    "partyGstn": "19AABCX5678B1Z2",
    "projectCode": "PROJ-001",
    "billingAddress": "Site Office, Block A",
    "shippingAddress": "Site Office, Block A",
    "categoryCode": "Service",
    "subCategoryCodes": ["SVC", "COMP"],
    "costHead": "Project Work /Fixed Asset",
    "items": [
      {
        "pwOrderItemId": 22,
        "itemCode": "SVC001",
        "itemName": "Shuttering Work",
        "itemUnit": "SqM",
        "note": null,
        "orderQty": 500.0,
        "preReceivedQty": 100.0,
        "balanceQty": 400.0,
        "currentReceivedQty": 0,
        "useLocation": null,
        "storeLocation": null
      }
    ]
  },
  "status": 200
}
```

### Error Responses

| Status | Message                   |
|--------|---------------------------|
| 404    | `PW Order not found`      |
| 400    | `PW Order is not approved`|
| 500    | Internal server error     |

---

## 3. Create SRN

Create a new Service Received Note in **Draft** status.

**POST** `/resource/srn/create`

Content-Type: `multipart/form-data`

### Form Fields

| Field                 | Type        | Required | Description                           |
|-----------------------|-------------|----------|---------------------------------------|
| srnDate               | date        | Yes      | SRN date (`YYYY-MM-DD`)               |
| projectCode           | string      | Yes      | Project code                          |
| receivedCategory      | string      | No       | Received category label               |
| itemCategory          | string      | No       | Item category label                   |
| costHead              | string      | No       | Cost head                             |
| orderId               | int         | No       | Linked PW order ID                    |
| vendorId              | int         | No       | Vendor / party ID                     |
| billingAddress        | string      | No       | Billing address                       |
| shippingAddress       | string      | No       | Shipping address                      |
| challanNo             | string      | No       | Challan reference number              |
| partyBillNo           | string      | No       | Party bill / invoice number           |
| partyBillDate         | date        | No       | Party bill date (`YYYY-MM-DD`)        |
| deliverVehicleNo      | string      | No       | Delivery vehicle number               |
| deliveredConcern      | string      | No       | Delivered to (person/department)      |
| unloadingDatetime     | datetime    | No       | Unloading date & time                 |
| physicallyVerifiedBy  | string      | No       | Physically verified by (name)         |
| attachedDoc           | file        | No       | Supporting document                   |
| items                 | JSON string | Yes      | Array of item objects (see below)     |

### `items` JSON Array

```json
[
  {
    "pwOrderItemId": 22,
    "currentReceivedQty": 150,
    "useLocation": "Site Block B",
    "storeLocation": "Store Room 3"
  }
]
```

| Field               | Type   | Required | Description                                     |
|---------------------|--------|----------|-------------------------------------------------|
| pwOrderItemId       | int    | Yes      | PW Order item ID from order-items endpoint      |
| currentReceivedQty  | number | Yes      | Qty received now (must be > 0 and ≤ balanceQty) |
| useLocation         | string | No       | Where the service/item will be used             |
| storeLocation       | string | No       | Where the item is stored                        |

### Success Response `201`

```json
{
  "message": "SRN created",
  "data": {
    "srnId": 1,
    "srnNo": "730001"
  },
  "status": 201
}
```

### Error Responses

| Status | Message                                                      |
|--------|--------------------------------------------------------------|
| 403    | `You are not SRN creator`                                    |
| 400    | `No items provided`                                          |
| 400    | `Invalid currentReceivedQty for pwOrderItemId {id}`          |
| 404    | `PW Order item {id} not found`                               |
| 400    | `Only {n} qty remaining for item {itemCode}`                 |
| 500    | Internal server error                                        |

---

## 4. SRN List

Get a filtered list of SRNs for a project.

**GET** `/resource/srn/list`

### Query Parameters

| Parameter      | Type   | Required | Description                         |
|----------------|--------|----------|-------------------------------------|
| projectCode    | string | Yes      | Project code                        |
| vendorId       | int    | No       | Filter by vendor                    |
| orderId        | int    | No       | Filter by linked PW order           |
| workflowStatus | string | No       | Filter by workflow status           |
| search         | string | No       | Partial match on SRN number         |

### Success Response `200`

```json
{
  "message": "SRN list fetched",
  "data": [
    {
      "id": 1,
      "srnNo": "730001",
      "srnDate": "2024-06-10",
      "projectCode": "PROJ-001",
      "orderNo": "550001",
      "partyName": "XYZ Services Pvt Ltd",
      "receivedCategory": "As per List",
      "itemCategory": "Service",
      "costHead": "Project Work /Fixed Asset",
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

## 5. SRN Details

Get full details of a single SRN including all items.

**GET** `/resource/srn/details/<srn_id>`

### Path Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| srn_id    | int  | SRN master ID |

### Success Response `200`

```json
{
  "message": "SRN details fetched",
  "data": {
    "id": 1,
    "srnNo": "730001",
    "srnDate": "2024-06-10",
    "projectCode": "PROJ-001",
    "receivedCategory": "As per List",
    "itemCategory": "Service",
    "costHead": "Project Work /Fixed Asset",
    "orderId": 8,
    "orderNo": "550001",
    "orderDate": "2024-04-10",
    "vendorId": 5,
    "partyName": "XYZ Services Pvt Ltd",
    "partyAddress": "45, Park Street, Kolkata - 700016",
    "partyGstn": "19AABCX5678B1Z2",
    "billingAddress": "Site Office, Block A",
    "shippingAddress": "Site Office, Block A",
    "challanNo": "CH-2024-001",
    "partyBillNo": "INV-2024-055",
    "partyBillDate": "2024-06-08",
    "deliverVehicleNo": "WB-01-AB-1234",
    "deliveredConcern": "Store Incharge",
    "unloadingDatetime": "2024-06-10 10:30",
    "physicallyVerifiedBy": "Site Engineer",
    "attachedDoc": "https://cdn.example.com/srn/730001/attached_doc",
    "workflowStatus": "Draft",
    "currentLevel": 0,
    "locked": false,
    "items": [
      {
        "id": 1,
        "pwOrderItemId": 22,
        "srnl": "SRNL001",
        "itemCode": "SVC001",
        "itemName": "Shuttering Work",
        "itemUnit": "SqM",
        "note": null,
        "orderQty": 500.0,
        "preReceivedQty": 100.0,
        "balanceQty": 400.0,
        "currentReceivedQty": 150.0,
        "useLocation": "Site Block B",
        "storeLocation": "Store Room 3"
      }
    ]
  },
  "status": 200
}
```

### Error Responses

| Status | Message           |
|--------|-------------------|
| 404    | `SRN not found`   |
| 500    | Internal server error |

---

## 6. Submit SRN

Submit a Draft or Reback SRN for approval.

**POST** `/resource/srn/submit/<srn_id>`

### Path Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| srn_id    | int  | SRN master ID |

No request body required.

### Success Response `200`

```json
{
  "message": "SRN submitted successfully",
  "data": {
    "srnId": 1,
    "srnNo": "730001",
    "workflowStatus": "Pending_L1"
  },
  "status": 200
}
```

### Error Responses

| Status | Message                  |
|--------|--------------------------|
| 404    | `SRN not found`          |
| 400    | `SRN already submitted`  |
| 400    | `SRN has no items`       |
| 500    | Internal server error    |

---

## 7. Approve SRN

**POST** `/resource/srn/approve/<srn_id>`

### Request Body (JSON)

```json
{ "comments": "Verified on site." }
```

| Field    | Type   | Required |
|----------|--------|----------|
| comments | string | No       |

### Success Response `200`

```json
{
  "message": "SRN approved successfully",
  "data": {
    "srnId": 1,
    "workflowStatus": "Approved",
    "currentLevel": 1
  },
  "status": 200
}
```

### Error Responses

| Status | Message                         |
|--------|---------------------------------|
| 404    | `SRN not found`                 |
| 400    | `SRN not pending`               |
| 403    | `You are not current approver`  |
| 500    | Internal server error           |

---

## 8. Reback SRN

**POST** `/resource/srn/reback/<srn_id>`

### Request Body (JSON)

```json
{ "comments": "Qty mismatch in item SVC001." }
```

| Field    | Type   | Required |
|----------|--------|----------|
| comments | string | Yes      |

### Success Response `200`

```json
{
  "message": "SRN sent for correction",
  "data": {
    "srnId": 1,
    "workflowStatus": "Reback"
  },
  "status": 200
}
```

### Error Responses

| Status | Message                         |
|--------|---------------------------------|
| 404    | `SRN not found`                 |
| 400    | `SRN not pending`               |
| 400    | `Comments required`             |
| 403    | `You are not current approver`  |
| 500    | Internal server error           |

---

## 9. Reject SRN

**POST** `/resource/srn/reject/<srn_id>`

### Request Body (JSON)

```json
{ "comments": "Service not matching specifications." }
```

| Field    | Type   | Required |
|----------|--------|----------|
| comments | string | Yes      |

### Success Response `200`

```json
{
  "message": "SRN rejected",
  "data": {
    "srnId": 1,
    "workflowStatus": "Rejected"
  },
  "status": 200
}
```

### Error Responses

| Status | Message                         |
|--------|---------------------------------|
| 404    | `SRN not found`                 |
| 400    | `SRN not pending`               |
| 400    | `Comments required`             |
| 403    | `You are not current approver`  |
| 500    | Internal server error           |

---

## 10. Edit SRN

Edit a Draft or Reback SRN. Replaces all existing items.

**PUT** `/resource/srn/edit/<srn_id>`

Content-Type: `multipart/form-data`

All header fields optional — only provided fields updated. `items` is required.

| Field                 | Type        | Description                        |
|-----------------------|-------------|------------------------------------|
| srnDate               | date        | Updated SRN date                   |
| receivedCategory      | string      | Updated received category          |
| itemCategory          | string      | Updated item category              |
| costHead              | string      | Updated cost head                  |
| orderId               | int         | Updated PW order ID                |
| vendorId              | int         | Updated vendor ID                  |
| billingAddress        | string      | Updated billing address            |
| shippingAddress       | string      | Updated shipping address           |
| challanNo             | string      | Updated challan number             |
| partyBillNo           | string      | Updated party bill number          |
| partyBillDate         | date        | Updated party bill date            |
| deliverVehicleNo      | string      | Updated vehicle number             |
| deliveredConcern      | string      | Updated delivered concern          |
| unloadingDatetime     | datetime    | Updated unloading datetime         |
| physicallyVerifiedBy  | string      | Updated verifier name              |
| attachedDoc           | file        | Replace attached document          |
| items                 | JSON string | Full replacement items array       |

### Success Response `200`

```json
{
  "message": "SRN updated successfully",
  "data": {
    "srnId": 1,
    "srnNo": "730001"
  },
  "status": 200
}
```

### Error Responses

| Status | Message                                              |
|--------|------------------------------------------------------|
| 404    | `SRN not found`                                      |
| 400    | `SRN cannot be edited` (locked)                      |
| 400    | `Only Draft or Reback SRN can be edited`             |
| 403    | `You are not SRN creator`                            |
| 400    | `Items required`                                     |
| 400    | `Invalid currentReceivedQty for pwOrderItemId {id}`  |
| 404    | `PW Order item {id} not found`                       |
| 400    | `Only {n} qty remaining for item {itemCode}`         |
| 500    | Internal server error                                |

---

## 11. SRN History

**GET** `/resource/srn/history/<srn_id>`

### Success Response `200`

```json
{
  "message": "SRN history fetched",
  "data": [
    {
      "id": 1,
      "action": "SUBMIT",
      "level": 0,
      "comments": null,
      "actionBy": "john.doe",
      "createdAt": "20240610 11:00:00"
    },
    {
      "id": 2,
      "action": "FINAL_APPROVE",
      "level": 1,
      "comments": "Verified on site.",
      "actionBy": "manager.user",
      "createdAt": "20240610 15:30:22"
    }
  ],
  "status": 200
}
```

| Action        | Description                              |
|---------------|------------------------------------------|
| SUBMIT        | SRN submitted for approval               |
| APPROVE       | Approved at intermediate level           |
| FINAL_APPROVE | Final approval — status becomes Approved |
| REBACK        | Sent back for correction                 |
| REJECT        | Permanently rejected                     |

### Error Responses

| Status | Message           |
|--------|-------------------|
| 404    | `SRN not found`   |
| 500    | Internal server error |

---

## Workflow States

```
Draft → [Submit] → Pending_L1 → [Approve] → Pending_L2 → ... → Approved
                              → [Reback]  → Reback → [Submit] → Pending_L1
                              → [Reject]  → Rejected
```

| Status       | Editable | Locked | Description                        |
|--------------|----------|--------|------------------------------------|
| Draft        | Yes      | No     | Newly created                      |
| Pending_L{n} | No       | Yes    | Awaiting approval at level n       |
| Reback       | Yes      | No     | Sent back for correction           |
| Approved     | No       | Yes    | Final approval done                |
| Rejected     | No       | Yes    | Permanently rejected               |

---

## DB Tables

### `srn_master`

| Column                | Type         | Notes                                 |
|-----------------------|--------------|---------------------------------------|
| id                    | int PK       |                                       |
| srn_no                | varchar(50)  | Unique, serial starting from 730001   |
| srn_date              | date         | Required                              |
| project_code          | varchar(50)  | FK → projects.project_code            |
| received_category     | varchar(100) |                                       |
| item_category         | varchar(100) |                                       |
| cost_head             | varchar(100) |                                       |
| order_id              | int          | FK → pw_order_master.id               |
| vendor_id             | int          | FK → vendors.id                       |
| billing_address       | text         |                                       |
| shipping_address      | text         |                                       |
| challan_no            | varchar(100) |                                       |
| party_bill_no         | varchar(100) |                                       |
| party_bill_date       | date         |                                       |
| deliver_vehicle_no    | varchar(100) |                                       |
| delivered_concern     | varchar(200) |                                       |
| unloading_datetime    | datetime     |                                       |
| physically_verified_by| varchar(200) |                                       |
| attached_doc          | text         | CDN URL                               |
| workflow_status       | varchar(30)  | Default: Draft                        |
| current_level         | int          | Default: 0                            |
| locked                | boolean      | Default: false                        |
| created_by            | int          | FK → users.id                         |
| submitted_by          | int          | FK → users.id                         |
| approved_by           | int          | FK → users.id                         |
| rejected_by           | int          | FK → users.id                         |
| updated_by            | int          | FK → users.id                         |
| submitted_at          | datetime     |                                       |
| final_approved_at     | datetime     |                                       |
| rejected_at           | datetime     |                                       |
| correction_sent_at    | datetime     |                                       |
| created_at            | datetime     | Auto                                  |
| updated_at            | datetime     | Auto                                  |

### `srn_items`

| Column              | Type         | Notes                          |
|---------------------|--------------|--------------------------------|
| id                  | int PK       |                                |
| srn_id              | int          | FK → srn_master.id             |
| pw_order_item_id    | int          | FK → pw_order_items.id         |
| srnl                | varchar(50)  | Line code e.g. SRNL001         |
| current_received_qty| numeric(12,2)|                                |
| use_location        | varchar(150) |                                |
| store_location      | varchar(150) |                                |
| created_at          | datetime     | Auto                           |

---

## Migration

```bash
flask db migrate -m "add srn tables"
flask db upgrade
```

---

## Workflow Alias Setup

Insert into `workflow_module_alias`:

```sql
INSERT INTO workflow_module_alias (module_code, approval_module_code)
VALUES ('srn', '<your_target_module_code>');
```

Until the alias is set, `srn` is used as-is — make sure `module_master` has a row for it (or the aliased code).
