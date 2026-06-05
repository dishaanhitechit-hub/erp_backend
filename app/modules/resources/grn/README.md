# GRN (Goods Received Note) API

Base URL: `/resource/grn`
All endpoints require `Authorization: Bearer <token>`

---

## 1. Get Orders by Vendor
**Filter panel helper — fetch approved orders for a vendor.**

```
GET /resource/grn/vendor-orders
```

### Query Params
| Param | Required | Description |
|---|---|---|
| `vendorId` | ✅ | Vendor ID |
| `projectCode` | ✅ | Project code |
| `receivedCategory` | ❌ | If provided, filters by `category_code` directly |
| `itemCategory` | ❌ | Fallback filter by `sub_code` (used if `receivedCategory` is absent) |
| `costHead` | ❌ | Fallback filter by `cost_head` (used if `receivedCategory` is absent) |

### Response `200`
```json
{
    "message": "Orders fetched",
    "data": [
        {
            "id": 1,
            "orderNo": "440001",
            "orderDate": "20250101",
            "categoryCode": "MAT",
            "subCode": "CIV",
            "costHead": "Project Work/Fixed Asset",
            "basicAmount": 50000.0,
            "totalAmount": 59000.0,
            "workflowStatus": "Approved"
        }
    ]
}
```

---

## 2. Get Order Items for GRN Grid
**Loads all items of an order with live pre-received & balance qty.**

```
GET /resource/grn/order-items/<order_id>
```

### Path Param
| Param | Description |
|---|---|
| `order_id` | ID of the approved order |

### Response `200`
```json
{
    "message": "Order items fetched",
    "data": {
        "orderId": 1,
        "orderNo": "440001",
        "orderDate": "20250101",
        "vendorId": 5,
        "partyName": "ABC Suppliers Pvt Ltd",
        "partyAddress": "123, Main Road, Kolkata",
        "partyGstn": "19AABCA1234A1Z5",
        "projectCode": "PC0001",
        "billingAddress": "Site Office, Project Road",
        "shippingAddress": "Site Store, Project Road",
        "categoryCode": "MAT",
        "subCode": "CIV",
        "costHead": "Project Work/Fixed Asset",
        "items": [
            {
                "orderItemId": 10,
                "indentNo": "IND-0001",
                "itemCode": "CCWS002",
                "itemName": "Shuttering Ply 12thk",
                "itemUnit": "SqM",
                "note": null,
                "orderQty": 1000.0,
                "preReceivedQty": 200.0,
                "balanceQty": 800.0,
                "currentReceivedQty": 0,
                "useLocation": null,
                "storeLocation": null
            }
        ]
    }
}
```

### Error `404`
```json
{ "message": "Order not found", "data": [] }
```

### Error `400`
```json
{ "message": "Order is not approved", "data": [] }
```

---

## 3. Create GRN
**Create a new GRN in Draft status.**

```
POST /resource/grn/create
Content-Type: multipart/form-data
```

### Form Fields
| Field | Required | Description |
|---|---|---|
| `projectCode` | ✅ | Project code |
| `grnDate` | ✅ | GRN date (YYYY-MM-DD) |
| `orderId` | ✅ | Linked order ID |
| `vendorId` | ✅ | Vendor ID |
| `receivedCategory` | ❌ | Received category |
| `itemCategory` | ❌ | Item category |
| `costHead` | ❌ | Cost head |
| `billingAddress` | ❌ | Billing address |
| `shippingAddress` | ❌ | Shipping address |
| `challanNo` | ❌ | Challan number |
| `partyBillNo` | ❌ | Party bill number |
| `partyBillDate` | ❌ | Party bill date (YYYY-MM-DD) |
| `deliverVehicleNo` | ❌ | Delivery vehicle number |
| `deliveredConcern` | ❌ | Delivered concern person |
| `unloadingDatetime` | ❌ | Unloading date & time |
| `physicallyVerifiedBy` | ❌ | Verified by person name |
| `attachedDoc` | ❌ | File upload |
| `items` | ✅ | JSON string array of items (see below) |

### `items` JSON Array
```json
[
    {
        "orderItemId": 10,
        "currentReceivedQty": 150,
        "useLocation": "Block A",
        "storeLocation": "Store 1"
    },
    {
        "orderItemId": 11,
        "currentReceivedQty": 50,
        "useLocation": "Block B",
        "storeLocation": "Store 2"
    }
]
```
> `grnl` is auto-generated as `GRNL001`, `GRNL002`... based on item order.

### Response `201`
```json
{
    "message": "GRN created",
    "data": {
        "grnId": 1,
        "grnNo": "720001"
    }
}
```

### Error `400`
```json
{ "message": "Only 800.0 qty remaining for item CCWS002", "data": [] }
```

### Error `403`
```json
{ "message": "You are not GRN creator", "data": [] }
```

---

## 4. GRN List

```
GET /resource/grn/list
```

### Query Params
| Param | Required | Description |
|---|---|---|
| `projectCode` | ✅ | Project code |
| `vendorId` | ❌ | Filter by vendor |
| `orderId` | ❌ | Filter by order |
| `workflowStatus` | ❌ | `Draft` / `Pending_L1` / `Approved` / `Reback` / `Rejected` |
| `search` | ❌ | Search by GRN number |

### Response `200`
```json
{
    "message": "GRN list fetched",
    "data": [
        {
            "id": 1,
            "grnNo": "720001",
            "grnDate": "20250601",
            "projectCode": "PC0001",
            "orderNo": "440001",
            "partyName": "ABC Suppliers Pvt Ltd",
            "receivedCategory": "MAT",
            "itemCategory": "CIV",
            "costHead": "Project Work/Fixed Asset",
            "workflowStatus": "Draft"
        }
    ]
}
```

---

## 5. GRN Details

```
GET /resource/grn/details/<grn_id>
```

### Response `200`
```json
{
    "message": "GRN details fetched",
    "data": {
        "id": 1,
        "grnNo": "720001",
        "grnDate": "20250601",
        "projectCode": "PC0001",
        "receivedCategory": "MAT",
        "itemCategory": "CIV",
        "costHead": "Project Work/Fixed Asset",
        "orderId": 1,
        "orderNo": "440001",
        "vendorId": 5,
        "partyName": "ABC Suppliers Pvt Ltd",
        "partyAddress": "123, Main Road, Kolkata",
        "partyGstn": "19AABCA1234A1Z5",
        "billingAddress": "Site Office",
        "shippingAddress": "Site Store",
        "challanNo": "CH-001",
        "partyBillNo": "BILL-001",
        "partyBillDate": "20250530",
        "deliverVehicleNo": "WB-01-AB-1234",
        "deliveredConcern": "Rahul Sharma",
        "unloadingDatetime": "20250601 10:30",
        "physicallyVerifiedBy": "Suresh Das",
        "attachedDoc": "https://cdn.example.com/grn/720001/attached_doc",
        "workflowStatus": "Draft",
        "currentLevel": 0,
        "locked": false,
        "items": [
            {
                "id": 1,
                "orderItemId": 10,
                "grnl": "GRNL001",
                "indentNo": "IND-0001",
                "itemCode": "CCWS002",
                "itemName": "Shuttering Ply 12thk",
                "itemUnit": "SqM",
                "note": null,
                "orderQty": 1000.0,
                "preReceivedQty": 200.0,
                "balanceQty": 800.0,
                "currentReceivedQty": 150.0,
                "useLocation": "Block A",
                "storeLocation": "Store 1"
            }
        ]
    }
}
```

### Error `404`
```json
{ "message": "GRN not found", "data": [] }
```

---

## 6. Submit GRN

```
POST /resource/grn/submit/<grn_id>
```

> Only `Draft` or `Reback` GRNs can be submitted.

### Response `200`
```json
{
    "message": "GRN submitted successfully",
    "data": {
        "grnId": 1,
        "grnNo": "720001",
        "workflowStatus": "Pending_L1"
    }
}
```

---

## 7. Approve GRN

```
POST /resource/grn/approve/<grn_id>
Content-Type: application/json
```

### Body
```json
{
    "comments": "Looks good"
}
```

### Response `200`
```json
{
    "message": "GRN approved successfully",
    "data": {
        "grnId": 1,
        "workflowStatus": "Approved",
        "currentLevel": 0
    }
}
```

### Error `403`
```json
{ "message": "You are not current approver", "data": [] }
```

---

## 8. Reback GRN

```
POST /resource/grn/reback/<grn_id>
Content-Type: application/json
```

### Body
```json
{
    "comments": "Please recheck quantities"
}
```
> `comments` is **required**.

### Response `200`
```json
{
    "message": "GRN sent for correction",
    "data": {
        "grnId": 1,
        "workflowStatus": "Reback"
    }
}
```

---

## 9. Reject GRN

```
POST /resource/grn/reject/<grn_id>
Content-Type: application/json
```

### Body
```json
{
    "comments": "Items do not match PO"
}
```
> `comments` is **required**.

### Response `200`
```json
{
    "message": "GRN rejected",
    "data": {
        "grnId": 1,
        "workflowStatus": "Rejected"
    }
}
```

---

## 10. Edit GRN

```
PUT /resource/grn/edit/<grn_id>
Content-Type: multipart/form-data
```

> Only `Draft` or `Reback` GRNs can be edited. Locked GRNs are rejected.

### Form Fields
| Field | Required | Description |
|---|---|---|
| `items` | ✅ | JSON string array of items (same structure as create) |
| `grnDate` | ❌ | Updated GRN date (YYYY-MM-DD) |
| `orderId` | ❌ | Updated linked order ID |
| `vendorId` | ❌ | Updated vendor ID |
| `receivedCategory` | ❌ | Updated received category |
| `itemCategory` | ❌ | Updated item category |
| `costHead` | ❌ | Updated cost head |
| `billingAddress` | ❌ | Updated billing address |
| `shippingAddress` | ❌ | Updated shipping address |
| `challanNo` | ❌ | Updated challan number |
| `partyBillNo` | ❌ | Updated party bill number |
| `partyBillDate` | ❌ | Updated party bill date (YYYY-MM-DD) |
| `deliverVehicleNo` | ❌ | Updated delivery vehicle number |
| `deliveredConcern` | ❌ | Updated delivered concern person |
| `unloadingDatetime` | ❌ | Updated unloading date & time |
| `physicallyVerifiedBy` | ❌ | Updated verified by person name |
| `attachedDoc` | ❌ | Updated file upload |

### `items` JSON Array
```json
[
    {
        "orderItemId": 10,
        "currentReceivedQty": 200,
        "useLocation": "Block A",
        "storeLocation": "Store 1"
    }
]
```
> Old items are wiped and rebuilt. `grnl` is re-generated as `GRNL001`, `GRNL002`...

### Response `200`
```json
{
    "message": "GRN updated successfully",
    "data": {
        "grnId": 1,
        "grnNo": "720001"
    }
}
```

### Errors
| Code | Message |
|---|---|
| `404` | GRN not found |
| `400` | GRN cannot be edited (locked) |
| `400` | Only Draft or Reback GRN can be edited |
| `403` | You are not GRN creator |
| `400` | Items required |
| `400` | Invalid currentReceivedQty for orderItemId X |
| `400` | Only {balance} qty remaining for item {code} |

---

## 11. GRN History

```
GET /resource/grn/history/<grn_id>
```

### Response `200`
```json
{
    "message": "GRN history fetched",
    "data": [
        {
            "id": 1,
            "action": "SUBMIT",
            "level": 0,
            "comments": null,
            "actionBy": "soumyajit",
            "createdAt": "20250601 10:30:00"
        },
        {
            "id": 2,
            "action": "APPROVE",
            "level": 1,
            "comments": "Looks good",
            "actionBy": "manager01",
            "createdAt": "20250601 14:00:00"
        }
    ]
}
```

---

## Workflow States

```
Draft → Pending_L1 → Pending_L2 → ... → Approved
          ↓                ↓
        Reback           Rejected
          ↓
        Draft (resubmit)
```

| Status | Locked | Who can act |
|---|---|---|
| `Draft` | ❌ | Creator (edit / submit) |
| `Pending_Lx` | ✅ | Approver at level x |
| `Reback` | ❌ | Creator (edit / resubmit) |
| `Approved` | ✅ | — |
| `Rejected` | ✅ | — |
