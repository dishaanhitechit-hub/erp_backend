# GIN — Goods Issue Note

Base URL: `/resource/gin`
Auth: All endpoints require `Authorization: Bearer <JWT>` header.

---

## Table of Contents

1. [Get Orders by Vendor](#1-get-orders-by-vendor)
2. [Get Order Items for GIN Grid](#2-get-order-items-for-gin-grid)
3. [Create GIN](#3-create-gin)
4. [GIN List](#4-gin-list)
5. [GIN Details](#5-gin-details)
6. [Submit GIN](#6-submit-gin)
7. [Approve GIN](#7-approve-gin)
8. [Reback GIN](#8-reback-gin)
9. [Reject GIN](#9-reject-gin)
10. [Edit GIN](#10-edit-gin)
11. [GIN History](#11-gin-history)
12. [Workflow States](#workflow-states)
13. [Stock Qty Calculation](#stock-qty-calculation)

---

## 1. Get Orders by Vendor

Fetch approved orders for a vendor/project combination. Used to populate the Order No filter dropdown.

**GET** `/resource/gin/vendor-orders`

### Query Parameters

| Parameter     | Type   | Required | Description                                      |
|---------------|--------|----------|--------------------------------------------------|
| vendorId      | int    | Yes      | Vendor ID                                        |
| projectCode   | string | Yes      | Project code                                     |
| issueCategory | string | No       | Filters by `order_master.category_code` |
| itemCategory  | string | No       | Filters by `order_master.sub_code`      |
| costHead      | string | No       | Filters by `order_master.cost_head`     |

> All provided filters are applied together with AND logic. **Fallback behaviour:** if `issueCategory` is provided but yields no results, the query automatically retries using only `itemCategory` + `costHead` so valid orders are never silently missed.

### Success Response `200`

```json
{
  "message": "Orders fetched",
  "data": [
    {
      "id": 12,
      "orderNo": "ORD-2024-012",
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

| Status | Message               |
|--------|-----------------------|
| 400    | `vendorId required`   |
| 400    | `projectCode required`|
| 500    | Internal server error |

---

## 2. Get Order Items for GIN Grid

Fetch items of a specific order to populate the GIN item grid.
Returns `stockQty` (current available stock) and `preIssuedQty` for each item.
**Indent info is intentionally excluded from this response.**

**GET** `/resource/gin/order-items/<order_id>`

### Path Parameters

| Parameter | Type | Description  |
|-----------|------|--------------|
| order_id  | int  | Order master ID |

### Success Response `200`

```json
{
  "message": "Order items fetched",
  "data": {
    "orderId": 12,
    "orderNo": "ORD-2024-012",
    "orderDate": "2024-03-15",
    "vendorId": 5,
    "partyName": "ABC Suppliers Pvt Ltd",
    "partyAddress": "123, Main Road, Kolkata - 700001",
    "partyGstn": "19AABCA1234A1Z5",
    "projectCode": "PROJ-001",
    "site": "PROJ-001",
    "categoryCode": "Material",
    "subCode": "Civil",
    "costHead": "Project Work /Fixed Asset",
    "items": [
      {
        "orderItemId": 45,
        "itemCode": "CCWS002",
        "itemName": "Shuttering Ply 12thk",
        "itemUnit": "SqM",
        "note": null,
        "stockQty": 10.0,
        "preIssuedQty": 2.0,
        "issueQty": 0,
        "stockLocation": null,
        "itemUsedLocation": null
      }
    ]
  },
  "status": 200
}
```

### Error Responses

| Status | Message                   |
|--------|---------------------------|
| 404    | `Order not found`         |
| 400    | `Order is not approved`   |
| 500    | Internal server error     |

---

## 3. Create GIN

Create a new Goods Issue Note in **Draft** status.

**POST** `/resource/gin/create`

Content-Type: `multipart/form-data`

### Form Fields

| Field           | Type   | Required | Description                              |
|-----------------|--------|----------|------------------------------------------|
| ginDate         | date   | Yes      | GIN date (`YYYY-MM-DD`)                  |
| projectCode     | string | Yes      | Project code                             |
| issueCategory   | string | No       | Issue category (e.g. "As per List")      |
| itemCategory    | string | No       | Item category (e.g. "Material")          |
| costHead        | string | No       | Cost head (e.g. "Project Work /Fixed Asset") |
| costFactor      | string | No       | Cost factor (e.g. "Chargeable /Non Chargeable") |
| orderId         | int    | No       | Linked order ID                          |
| vendorId        | int    | No       | Vendor / party ID                        |
| site            | string | No       | Site (auto-filled from project)          |
| despatchFrom    | string | No       | Despatch from location                   |
| shippingTo      | string | No       | Shipping / delivery address              |
| recommendationBy| string | No       | Recommended by person name               |
| issueSlipNo     | string | No       | Issue slip reference number              |
| handedOverTo    | string | No       | Person items are handed over to          |
| attachedDoc     | file   | No       | Supporting document (any file type)      |
| items           | JSON string | Yes | Array of item objects (see below)      |

### `items` JSON Array

```json
[
  {
    "orderItemId": 45,
    "issueQty": 8,
    "stockLocation": "Warehouse A - Rack 3",
    "itemUsedLocation": "Block B - 2nd Floor"
  }
]
```

| Field            | Type   | Required | Description                               |
|------------------|--------|----------|-------------------------------------------|
| orderItemId      | int    | Yes      | Order item ID from order-items endpoint   |
| issueQty         | number | Yes      | Qty to issue (must be > 0 and ≤ stockQty) |
| stockLocation    | string | No       | Where the item is being issued from       |
| itemUsedLocation | string | No       | Where the item will be used               |

### Success Response `201`

```json
{
  "message": "GIN created",
  "data": {
    "ginId": 1,
    "ginNo": "810001"
  },
  "status": 201
}
```

### Error Responses

| Status | Message                                                   |
|--------|-----------------------------------------------------------|
| 403    | `You are not GIN creator`                                 |
| 400    | `No items provided`                                       |
| 400    | `Invalid issueQty for orderItemId {id}`                   |
| 404    | `Order item {id} not found`                               |
| 400    | `Only {n} qty in stock for item {itemCode}`               |
| 500    | Internal server error                                     |

---

## 4. GIN List

Get a filtered list of GINs for a project.

**GET** `/resource/gin/list`

### Query Parameters

| Parameter      | Type   | Required | Description                          |
|----------------|--------|----------|--------------------------------------|
| projectCode    | string | Yes      | Project code                         |
| vendorId       | int    | No       | Filter by vendor                     |
| orderId        | int    | No       | Filter by linked order               |
| workflowStatus | string | No       | Filter by status (Draft, Approved …) |
| search         | string | No       | Partial match on GIN number          |

### Success Response `200`

```json
{
  "message": "GIN list fetched",
  "data": [
    {
      "id": 1,
      "ginNo": "810001",
      "ginDate": "2024-06-05",
      "projectCode": "PROJ-001",
      "orderNo": "ORD-2024-012",
      "partyName": "ABC Suppliers Pvt Ltd",
      "issueCategory": "As per List",
      "itemCategory": "Material",
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

## 5. GIN Details

Get full details of a single GIN including all items.

**GET** `/resource/gin/details/<gin_id>`

### Path Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| gin_id    | int  | GIN master ID |

### Success Response `200`

```json
{
  "message": "GIN details fetched",
  "data": {
    "id": 1,
    "ginNo": "810001",
    "ginDate": "2024-06-05",
    "projectCode": "PROJ-001",
    "issueCategory": "As per List",
    "itemCategory": "Material",
    "costHead": "Project Work /Fixed Asset",
    "costFactor": "Chargeable /Non Chargeable",
    "orderId": 12,
    "orderNo": "ORD-2024-012",
    "orderDate": "2024-03-15",
    "vendorId": 5,
    "partyName": "ABC Suppliers Pvt Ltd",
    "partyAddress": "123, Main Road, Kolkata - 700001",
    "partyGstn": "19AABCA1234A1Z5",
    "site": "PROJ-001",
    "despatchFrom": "Main Store",
    "shippingTo": "Site Office, Block B",
    "recommendationBy": "Rahul Sharma",
    "issueSlipNo": "SLIP-2024-001",
    "handedOverTo": "Suresh Kumar",
    "attachedDoc": "https://cdn.example.com/gin/810001/attached_doc",
    "workflowStatus": "Draft",
    "currentLevel": 0,
    "locked": false,
    "items": [
      {
        "id": 1,
        "orderItemId": 45,
        "ginl": "GINL001",
        "itemCode": "CCWS002",
        "itemName": "Shuttering Ply 12thk",
        "itemUnit": "SqM",
        "note": null,
        "stockQty": 10.0,
        "preIssuedQty": 2.0,
        "issueQty": 8.0,
        "stockLocation": "Warehouse A - Rack 3",
        "itemUsedLocation": "Block B - 2nd Floor"
      }
    ]
  },
  "status": 200
}
```

### Error Responses

| Status | Message           |
|--------|-------------------|
| 404    | `GIN not found`   |
| 500    | Internal server error |

---

## 6. Submit GIN

Submit a Draft or Reback GIN for approval. Moves GIN to `Pending_L1` (or auto-approves if no workflow is configured).

**POST** `/resource/gin/submit/<gin_id>`

### Path Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| gin_id    | int  | GIN master ID |

No request body required.

### Success Response `200`

```json
{
  "message": "GIN submitted successfully",
  "data": {
    "ginId": 1,
    "ginNo": "810001",
    "workflowStatus": "Pending_L1"
  },
  "status": 200
}
```

### Error Responses

| Status | Message                   |
|--------|---------------------------|
| 404    | `GIN not found`           |
| 400    | `GIN already submitted`   |
| 400    | `GIN has no items`        |
| 500    | Internal server error     |

---

## 7. Approve GIN

Approve a pending GIN. Advances to next approval level or sets status to `Approved` at final level.

**POST** `/resource/gin/approve/<gin_id>`

### Path Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| gin_id    | int  | GIN master ID |

### Request Body (JSON)

```json
{
  "comments": "Approved after physical verification."
}
```

| Field    | Type   | Required | Description         |
|----------|--------|----------|---------------------|
| comments | string | No       | Approver's remarks  |

### Success Response `200`

```json
{
  "message": "GIN approved successfully",
  "data": {
    "ginId": 1,
    "workflowStatus": "Approved",
    "currentLevel": 1
  },
  "status": 200
}
```

### Error Responses

| Status | Message                          |
|--------|----------------------------------|
| 404    | `GIN not found`                  |
| 400    | `GIN not pending`                |
| 403    | `You are not current approver`   |
| 500    | Internal server error            |

---

## 8. Reback GIN

Send an approved-pending GIN back for correction. Sets status to `Reback` and unlocks the GIN.

**POST** `/resource/gin/reback/<gin_id>`

### Path Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| gin_id    | int  | GIN master ID |

### Request Body (JSON)

```json
{
  "comments": "Issue qty needs correction for item CCWS002."
}
```

| Field    | Type   | Required | Description                      |
|----------|--------|----------|----------------------------------|
| comments | string | Yes      | Reason for sending back (mandatory) |

### Success Response `200`

```json
{
  "message": "GIN sent for correction",
  "data": {
    "ginId": 1,
    "workflowStatus": "Reback"
  },
  "status": 200
}
```

### Error Responses

| Status | Message                          |
|--------|----------------------------------|
| 404    | `GIN not found`                  |
| 400    | `GIN not pending`                |
| 400    | `Comments required`              |
| 403    | `You are not current approver`   |
| 500    | Internal server error            |

---

## 9. Reject GIN

Permanently reject a pending GIN. Locks it and sets status to `Rejected`.

**POST** `/resource/gin/reject/<gin_id>`

### Path Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| gin_id    | int  | GIN master ID |

### Request Body (JSON)

```json
{
  "comments": "Items not matching the work order requirements."
}
```

| Field    | Type   | Required | Description                         |
|----------|--------|----------|-------------------------------------|
| comments | string | Yes      | Reason for rejection (mandatory)    |

### Success Response `200`

```json
{
  "message": "GIN rejected",
  "data": {
    "ginId": 1,
    "workflowStatus": "Rejected"
  },
  "status": 200
}
```

### Error Responses

| Status | Message                          |
|--------|----------------------------------|
| 404    | `GIN not found`                  |
| 400    | `GIN not pending`                |
| 400    | `Comments required`              |
| 403    | `You are not current approver`   |
| 500    | Internal server error            |

---

## 10. Edit GIN

Edit a GIN that is in `Draft` or `Reback` status. Replaces all existing items with the new items list.

**PUT** `/resource/gin/edit/<gin_id>`

Content-Type: `multipart/form-data`

### Path Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| gin_id    | int  | GIN master ID |

### Form Fields

All fields are optional — only provided fields will be updated. `items` is required.

| Field           | Type        | Required | Description                          |
|-----------------|-------------|----------|--------------------------------------|
| ginDate         | date        | No       | Updated GIN date (`YYYY-MM-DD`)      |
| issueCategory   | string      | No       | Updated issue category               |
| itemCategory    | string      | No       | Updated item category                |
| costHead        | string      | No       | Updated cost head                    |
| costFactor      | string      | No       | Updated cost factor                  |
| orderId         | int         | No       | Updated linked order ID              |
| vendorId        | int         | No       | Updated vendor ID                    |
| site            | string      | No       | Updated site                         |
| despatchFrom    | string      | No       | Updated despatch from                |
| shippingTo      | string      | No       | Updated shipping to                  |
| recommendationBy| string      | No       | Updated recommendation by            |
| issueSlipNo     | string      | No       | Updated issue slip number            |
| handedOverTo    | string      | No       | Updated handed over to               |
| attachedDoc     | file        | No       | Replace attached document            |
| items           | JSON string | Yes      | Full replacement items array         |

### `items` JSON Array (same as Create)

```json
[
  {
    "orderItemId": 45,
    "issueQty": 6,
    "stockLocation": "Warehouse A - Rack 3",
    "itemUsedLocation": "Block C - Ground Floor"
  }
]
```

### Success Response `200`

```json
{
  "message": "GIN updated successfully",
  "data": {
    "ginId": 1,
    "ginNo": "810001"
  },
  "status": 200
}
```

### Error Responses

| Status | Message                                             |
|--------|-----------------------------------------------------|
| 404    | `GIN not found`                                     |
| 400    | `GIN cannot be edited` (locked)                     |
| 400    | `Only Draft or Reback GIN can be edited`            |
| 403    | `You are not GIN creator`                           |
| 400    | `Items required`                                    |
| 400    | `Invalid issueQty for orderItemId {id}`             |
| 404    | `Order item {id} not found`                         |
| 400    | `Only {n} qty in stock for item {itemCode}`         |
| 500    | Internal server error                               |

---

## 11. GIN History

Get the full workflow action history for a GIN.

**GET** `/resource/gin/history/<gin_id>`

### Path Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| gin_id    | int  | GIN master ID |

### Success Response `200`

```json
{
  "message": "GIN history fetched",
  "data": [
    {
      "id": 1,
      "action": "SUBMIT",
      "level": 0,
      "comments": null,
      "actionBy": "john.doe",
      "createdAt": "20240605 14:32:10"
    },
    {
      "id": 2,
      "action": "APPROVE",
      "level": 1,
      "comments": "Approved after physical verification.",
      "actionBy": "manager.user",
      "createdAt": "20240605 16:05:44"
    },
    {
      "id": 3,
      "action": "FINAL_APPROVE",
      "level": 2,
      "comments": null,
      "actionBy": "senior.manager",
      "createdAt": "20240606 09:15:22"
    }
  ],
  "status": 200
}
```

### History Action Values

| Action       | Description                                    |
|--------------|------------------------------------------------|
| SUBMIT       | GIN submitted for approval                     |
| APPROVE      | Approved at intermediate level                 |
| FINAL_APPROVE| Final approval — GIN becomes Approved          |
| REBACK       | Sent back for correction                       |
| REJECT       | Permanently rejected                           |

### Error Responses

| Status | Message           |
|--------|-------------------|
| 404    | `GIN not found`   |
| 500    | Internal server error |

---

## Workflow States

```
Draft → [Submit] → Pending_L1 → [Approve] → Pending_L2 → ... → Approved
                                           → [Reback]  → Reback → [Submit] → Pending_L1
                                           → [Reject]  → Rejected
```

| Status      | Editable | Locked | Description                              |
|-------------|----------|--------|------------------------------------------|
| Draft       | Yes      | No     | Created, not yet submitted               |
| Pending_L{n}| No       | Yes    | Awaiting approval at level n             |
| Reback      | Yes      | No     | Sent back for correction by approver     |
| Approved    | No       | Yes    | Final approval done; stock deducted      |
| Rejected    | No       | Yes    | Permanently rejected; stock not affected |

---

## Stock Qty Calculation

`stockQty` shown in item grids and details is computed dynamically — never stored:

```
stockQty = Total GRN received qty (Approved GRNs) − Total GIN issued qty (non-Rejected GINs)
```

- `preIssuedQty` = sum of `issue_qty` from all GINs with status ≠ `Rejected` for that `order_item_id`
- Issue qty validation on create/edit: `issueQty ≤ stockQty`

---

## DB Tables

### `gin_master`

| Column           | Type         | Notes                              |
|------------------|--------------|------------------------------------|
| id               | int PK       | Auto increment                     |
| gin_no           | varchar(50)  | Unique, auto-generated serial      |
| gin_date         | date         | Required                           |
| project_code     | varchar(50)  | FK → projects.project_code         |
| issue_category   | varchar(100) |                                    |
| item_category    | varchar(100) |                                    |
| cost_head        | varchar(100) |                                    |
| cost_factor      | varchar(100) |                                    |
| order_id         | int          | FK → order_master.id               |
| vendor_id        | int          | FK → vendors.id                    |
| site             | varchar(200) |                                    |
| despatch_from    | varchar(200) |                                    |
| shipping_to      | text         |                                    |
| recommendation_by| varchar(200) |                                    |
| issue_slip_no    | varchar(100) |                                    |
| handed_over_to   | varchar(200) |                                    |
| attached_doc     | text         | CDN URL                            |
| workflow_status  | varchar(30)  | Default: Draft                     |
| current_level    | int          | Default: 0                         |
| locked           | boolean      | Default: false                     |
| created_by       | int          | FK → users.id                      |
| submitted_by     | int          | FK → users.id                      |
| approved_by      | int          | FK → users.id                      |
| rejected_by      | int          | FK → users.id                      |
| updated_by       | int          | FK → users.id                      |
| submitted_at     | datetime     |                                    |
| final_approved_at| datetime     |                                    |
| rejected_at      | datetime     |                                    |
| correction_sent_at| datetime    | Set when reback action is taken    |
| created_at       | datetime     | Auto                               |
| updated_at       | datetime     | Auto                               |

### `gin_items`

| Column            | Type         | Notes                            |
|-------------------|--------------|----------------------------------|
| id                | int PK       | Auto increment                   |
| gin_id            | int          | FK → gin_master.id               |
| order_item_id     | int          | FK → order_items.id              |
| ginl              | varchar(50)  | Line code e.g. GINL001           |
| issue_qty         | numeric(12,2)| Qty being issued                 |
| stock_location    | varchar(150) | Where item is issued from        |
| item_used_location| varchar(150) | Where item will be used          |
| created_at        | datetime     | Auto                             |

---

## Migration

```bash
flask db migrate -m "add gin tables"
flask db upgrade
```

---

## Workflow Module Code

`goods_issue_note` — used in approval path and history tables.
