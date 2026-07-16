# Supplier & Ledger API Documentation

## Overview

Two independent but synced modules under `/master`:

| Module | Table | Code Format | Base Route |
|---|---|---|---|
| Ledger (Vendor) | `vendors` | `260001, 260002…` | `/master/ledger` |
| Supplier | `suppliers` | `SUP0001, SUP0002…` | `/master/supplier` |

---

## Supplier Types — Exact Values

These are the exact string values used in `supplierTypes` arrays and filter params. **Case-sensitive.**

| Value | UI Label |
|---|---|
| `Materials` | Materials |
| `Work_Force` | Work Force |
| `Plant_Machinery` | Plant & Machinery |
| `others` | Others |

A supplier/vendor can belong to **multiple types** simultaneously.

---

## Sync Rules

| Trigger | What happens |
|---|---|
| Vendor created with `supplierTypes` | Auto-creates a new Supplier from vendor data + links both |
| Vendor created with `supplierId` | Links vendor to that existing Supplier (no new supplier created) |
| Vendor updated | Pushes all common fields + `supplierTypes`, `natureOfService`, `serviceDescription` → all mapped Suppliers |
| Supplier updated | Pushes `supplierTypes`, `natureOfService`, `serviceDescription` → all mapped Vendors |

### Common Fields Synced (Vendor → Supplier)

| Vendor Field | Supplier Field |
|---|---|
| `ledger_name` | `supplier_name` |
| `registered_address` | `registered_address` |
| `corporate_address` | `corporate_address` |
| `primary_contact_person` | `contact_person` |
| `designation` | `designation` |
| `primary_contact_number` | `mobile_number` |
| `whatsapp_number` | `whatsapp_number` |
| `email` | `email` |
| `supplier_types` | `supplier_types` |
| `nature_of_service` | `nature_of_service` |
| `service_description` | `service_description` |

---

## Base URL

```
/master
```

---

# LEDGER (VENDOR) APIs

---

### 1. Create Ledger

**POST** `/ledger/create`

**Auth:** Login + Admin

**Content-Type:** `multipart/form-data`

**Auto-supplier behavior:**
- If `supplierId` is sent → links vendor to that existing supplier, sets `vendor.supplier_id`
- If `supplierId` not sent but `supplierTypes` present → auto-creates a new Supplier from vendor data, links it, sets `vendor.supplier_id`

#### Form Fields

| Field | Type | Required | Description |
|---|---|---|---|
| `ledgerName` | string | Yes | Vendor / company name |
| `categoryId` | string | Yes | Category code from category master |
| `supplierId` | integer | No | Link to existing supplier instead of auto-creating |
| `supplierTypes` | JSON string | No | e.g. `'["Materials","Work_Force"]'` |
| `natureOfService` | string | No | Selected value from nature-of-service list |
| `serviceDescription` | string | No | Free text service description |
| `registeredAddress` | string | No | Registered office address |
| `corporateAddress` | string | No | Corporate address |
| `primaryContactPerson` | string | No | Contact person name |
| `designation` | string | No | Designation |
| `primaryContactNumber` | string | No | Mobile number |
| `whatsappNumber` | string | No | WhatsApp number |
| `email` | string | No | Email address |
| `pan` | string | No | PAN number |
| `gstin` | string | No | GSTIN number |
| `stateCode` | string | No | State code |
| `stateName` | string | No | State name |
| `bankAccountNumber` | string | No | Bank account number |
| `bankName` | string | No | Bank name |
| `branchName` | string | No | Branch name |
| `ifscCode` | string | No | IFSC code |
| `tradeLicenceFile` | file | No | Trade licence document |
| `panFile` | file | No | PAN document |
| `gstnFile` | file | No | GSTN document |
| `bankDetailsFile` | file | No | Bank details document |

#### Response `201`

```json
{
  "message": "ledger created successfully",
  "data": [
    {
      "ledgerId": 1,
      "ledgerCode": "260001",
      "ledgerName": "ABC Suppliers Pvt Ltd",
      "tradeLicenceUrl": "https://...",
      "panUrl": "https://...",
      "gstnUrl": "https://...",
      "bankDetailsUrl": "https://..."
    }
  ],
  "status": 201
}
```

---

### 2. Get All Ledgers

**GET** `/ledger/list`

**Auth:** Login

#### Response `200`

```json
{
  "message": "ledger list fetched successfully",
  "data": [
    {
      "ledgerId": 1,
      "ledgerCode": "260001",
      "ledgerName": "ABC Suppliers Pvt Ltd",
      "registeredAddress": "12, MG Road, Kolkata",
      "corporateAddress": "5, Park Street, Kolkata",
      "categoryName": "Supplier",
      "categoryId": "SUP001",
      "pan": "ABCDE1234F",
      "gstin": "19ABCDE1234F1Z5",
      "stateCode": "19",
      "stateName": "West Bengal",
      "primaryContactPerson": "Ramesh Kumar",
      "primaryContactNumber": "9800000000",
      "designation": "Sales Manager",
      "whatsappNumber": "9800000000",
      "email": "ramesh@abc.com",
      "supplierId": 1,
      "supplierTypes": ["Materials", "Work_Force"],
      "natureOfService": "Cement & Binding Materials",
      "serviceDescription": "Supply of OPC and PPC cement",
      "bankAccountNumber": "1234567890",
      "bankName": "SBI",
      "branchName": "Park Street",
      "ifscCode": "SBIN0000123",
      "tradeLicenceFile": "https://...",
      "panFile": "https://...",
      "gstnFile": "https://...",
      "bankDetailsFile": "https://...",
      "status": "Active",
      "createdAt": "2026-07-15T10:00:00"
    }
  ],
  "status": 200
}
```

---

### 3. Get Ledger by ID

**GET** `/ledger/<vendorId>`

**Auth:** Login

```
GET /master/ledger/1
```

Response structure same as a single item from list above.

#### Response `404`

```json
{ "message": "ledger not found", "data": [], "status": 404 }
```

---

### 4. Update Ledger

**PUT** `/ledger/update/<vendorId>`

**Auth:** Login + Admin

**Content-Type:** `multipart/form-data`

> On update, all common fields + `supplierTypes`, `natureOfService`, `serviceDescription` are automatically pushed to all linked Suppliers. If no supplier is linked yet, a new one is auto-created.

Send only fields to update. Fields not sent retain current values.
`supplierTypes` — if sent, replaces the full array.

| Field | Type | Description |
|---|---|---|
| `ledgerName` | string | Vendor name |
| `supplierTypes` | JSON string | e.g. `'["Materials"]'` — replaces full array |
| `natureOfService` | string | Nature of service |
| `serviceDescription` | string | Service description |
| `registeredAddress` | string | Registered address |
| `corporateAddress` | string | Corporate address |
| `primaryContactPerson` | string | Contact person |
| `designation` | string | Designation |
| `primaryContactNumber` | string | Mobile number |
| `whatsappNumber` | string | WhatsApp |
| `email` | string | Email |
| `categoryId` | string | Category code |
| `pan` | string | PAN |
| `gstin` | string | GSTIN |
| `stateCode` | string | State code |
| `stateName` | string | State name |
| `bankAccountNumber` | string | Bank account |
| `bankName` | string | Bank name |
| `branchName` | string | Branch |
| `ifscCode` | string | IFSC |
| `tradeLicenceFile` | file | Replace trade licence |
| `panFile` | file | Replace PAN file |
| `gstnFile` | file | Replace GSTN file |
| `bankDetailsFile` | file | Replace bank details |

#### Response `200`

```json
{
  "message": "ledger updated successfully",
  "data": [
    {
      "ledgerId": 1,
      "ledgerCode": "260001",
      "ledgerName": "ABC Suppliers Pvt Ltd",
      "tradeLicenceFile": "https://...",
      "panFile": "https://...",
      "gstnFile": "https://...",
      "bankDetailsFile": "https://..."
    }
  ],
  "status": 200
}
```

---

### 5. Delete Ledger

**DELETE** `/ledger/delete/<vendorId>`

**Auth:** Login + Admin

```
DELETE /master/ledger/delete/1
```

#### Response `200`

```json
{ "message": "Vendor deleted successfully", "data": [], "status": 200 }
```

---

# SUPPLIER APIs

---

### 6. Create Supplier

**POST** `/supplier/create`

**Auth:** Login + Admin

**Content-Type:** `application/json`

#### Request Body

| Field | Type | Required | Description |
|---|---|---|---|
| `supplierName` | string | Yes | Supplier name |
| `supplierTypes` | array | No | `["Materials", "Work_Force"]` |
| `natureOfService` | string | No | Nature of service |
| `serviceDescription` | string | No | Service description |
| `registeredAddress` | string | No | Registered address |
| `corporateAddress` | string | No | Corporate address |
| `contactPerson` | string | No | Contact person |
| `designation` | string | No | Designation |
| `mobileNumber` | string | No | Mobile number |
| `whatsappNumber` | string | No | WhatsApp number |
| `email` | string | No | Email |
| `ledgerIds` | array | No | Existing ledger IDs to link at creation e.g. `[1, 2]` |

#### Example Request

```json
{
  "supplierName": "ABC Suppliers Pvt Ltd",
  "supplierTypes": ["Materials", "Work_Force"],
  "natureOfService": "Cement & Binding Materials",
  "serviceDescription": "Supply of OPC and PPC cement",
  "registeredAddress": "12, MG Road, Kolkata",
  "contactPerson": "Ramesh Kumar",
  "designation": "Sales Manager",
  "mobileNumber": "9800000000",
  "whatsappNumber": "9800000000",
  "email": "ramesh@abc.com",
  "ledgerIds": [1, 3]
}
```

#### Response `201`

```json
{
  "message": "supplier created successfully",
  "data": [
    {
      "supplierId": 1,
      "supplierCode": "SUP0001",
      "supplierName": "ABC Suppliers Pvt Ltd",
      "registeredAddress": "12, MG Road, Kolkata",
      "corporateAddress": null,
      "contactPerson": "Ramesh Kumar",
      "designation": "Sales Manager",
      "mobileNumber": "9800000000",
      "whatsappNumber": "9800000000",
      "email": "ramesh@abc.com",
      "supplierTypes": ["Materials", "Work_Force"],
      "natureOfService": "Cement & Binding Materials",
      "serviceDescription": "Supply of OPC and PPC cement",
      "linkedLedgers": [
        { "ledgerId": 1, "ledgerCode": "260001", "ledgerName": "ABC Vendors" },
        { "ledgerId": 3, "ledgerCode": "260003", "ledgerName": "ABC Labour" }
      ],
      "status": "Active",
      "createdAt": "2026-07-15T10:00:00"
    }
  ],
  "status": 201
}
```

---

### 7. Get All Suppliers

**GET** `/supplier/list`

**Auth:** Login

#### Query Params (all optional, combinable)

| Param | Type | Description |
|---|---|---|
| `search` | string | Partial, case-insensitive search on supplier name |
| `supplierType` | string | Filter by exact type value (case-sensitive): `Materials`, `Work_Force`, `Plant_Machinery`, `others` |

#### Examples

```
GET /master/supplier/list
GET /master/supplier/list?search=ABC
GET /master/supplier/list?supplierType=Materials
GET /master/supplier/list?search=ABC&supplierType=Materials
GET /master/supplier/list?supplierType=Work_Force
```

#### Response `200`

```json
{
  "message": "supplier list fetched successfully",
  "data": [ ...array of supplier objects... ],
  "status": 200
}
```

Each object has the same structure as the create response above.

---

### 8. Get Supplier by ID

**GET** `/supplier/<supplierId>`

**Auth:** Login

```
GET /master/supplier/1
```

#### Response `200`

```json
{
  "message": "supplier fetched successfully",
  "data": [ ...supplier object... ],
  "status": 200
}
```

#### Response `404`

```json
{ "message": "supplier not found", "data": [], "status": 404 }
```

---

### 9. Update Supplier

**PUT** `/supplier/update/<supplierId>`

**Auth:** Login + Admin

**Content-Type:** `application/json`

> On update, `supplierTypes`, `natureOfService`, `serviceDescription` are automatically pushed to all linked Vendors.

Send only fields to update. `supplierTypes` if sent replaces the full array.

#### Example Request

```json
{
  "supplierName": "ABC Suppliers Ltd",
  "supplierTypes": ["Materials"],
  "natureOfService": "Reinforcement Steel",
  "serviceDescription": "TMT bars supply"
}
```

#### Response `200`

```json
{
  "message": "supplier updated successfully",
  "data": [ ...updated supplier object... ],
  "status": 200
}
```

---

### 10. Delete Supplier

**DELETE** `/supplier/delete/<supplierId>`

**Auth:** Login + Admin

All ledger mappings deleted automatically (CASCADE). `vendor.supplier_id` is set to `NULL`.

```
DELETE /master/supplier/delete/1
```

#### Response `200`

```json
{ "message": "supplier deleted successfully", "data": [], "status": 200 }
```

---

### 11. Link a Ledger to Supplier

**POST** `/supplier/<supplierId>/link-ledger`

**Auth:** Login + Admin

**Content-Type:** `application/json`

Links an existing Ledger to this Supplier. Duplicate links return `409`.

#### Request Body

```json
{ "ledgerId": 5 }
```

#### Response `200`

```json
{
  "message": "ledger linked successfully",
  "data": [ ...updated supplier object... ],
  "status": 200
}
```

#### Response `409`

```json
{ "message": "ledger already linked to this supplier", "data": [], "status": 409 }
```

---

### 12. Unlink a Ledger from Supplier

**DELETE** `/supplier/<supplierId>/unlink-ledger/<ledgerId>`

**Auth:** Login + Admin

```
DELETE /master/supplier/1/unlink-ledger/5
```

#### Response `200`

```json
{ "message": "ledger unlinked successfully", "data": [], "status": 200 }
```

#### Response `404`

```json
{ "message": "mapping not found", "data": [], "status": 404 }
```

---

### 13. Get Nature of Service List

**GET** `/supplier/nature-of-service?types=<comma-separated>`

**Auth:** Login

Returns a merged, deduplicated list for one or more supplier types.
Call this every time the supplier type checkboxes change on the UI to refresh the Nature of Service dropdown.

**`types` param values are case-sensitive and must match exactly:**

| types value | Items returned |
|---|---|
| `Materials` | 20 items |
| `Work_Force` | 20 items |
| `Plant_Machinery` | Empty — list to be added later |
| `others` | Empty — list to be added later |

#### Examples

```
GET /master/supplier/nature-of-service?types=Materials
GET /master/supplier/nature-of-service?types=Work_Force
GET /master/supplier/nature-of-service?types=Materials,Work_Force
GET /master/supplier/nature-of-service?types=Materials,Work_Force,Plant_Machinery
```

#### Response `200` — `?types=Materials,Work_Force`

```json
{
  "message": "nature of service list",
  "data": [
    "Cement & Binding Materials",
    "Reinforcement Steel",
    "Aggregates",
    "Bricks & Blocks",
    "Ready-mix Concrete",
    "Structural Steel Materials",
    "Shuttering & Formwork Materials",
    "Doors & Windows",
    "Waterproofing Materials",
    "Hardware",
    "Roofing & Cladding Materials",
    "Machinery & Spare Parts",
    "Tools & Tackles",
    "Safety Items (PPE)",
    "Electrical Materials",
    "Machinery Materials",
    "Plumbing Materials",
    "Fabrication Materials",
    "Fuels & Lubricants",
    "Construction Chemicals",
    "Aluminum Glazing Gang",
    "Concreting Gang",
    "Electrical Fitting Gang",
    "EPBX Gang",
    "Facade or Cladding Gang",
    "False Ceiling Gang",
    "Fire Fighting Gang",
    "Masonry Gang",
    "Others Specialized Gang",
    "Painting Gang",
    "Plumbing Gang",
    "Road Construction Gang",
    "Scaffolding Gang",
    "Shuttering & Reinforcement Gang",
    "Structural Fabrication & Erection Gang",
    "Tiles Flooring Gang",
    "Un-Skill Gang",
    "VDF Flooring Gang",
    "Welding Gang",
    "Wooden Carpentry Gang"
  ],
  "status": 200
}
```

#### Response `400`

```json
{ "message": "types query param is required", "data": [], "status": 400 }
```

---

## DB Tables

```
vendors
  id, ledger_code, ledger_name, registered_address, corporate_address,
  category_code, pan, gstin, state_code, state_name,
  primary_contact_person, primary_contact_number, designation,
  whatsapp_number, email,
  supplier_id (FK → suppliers.id, ON DELETE SET NULL),
  supplier_types (JSON), nature_of_service, service_description,
  trade_licence_file, pan_file, gstn_file, bank_details_file,
  bank_account_number, bank_name, branch_name, ifsc_code,
  status, created_at, updated_at, created_by

suppliers
  id, supplier_code, supplier_name, registered_address, corporate_address,
  contact_person, designation, mobile_number, whatsapp_number, email,
  supplier_types (JSON), nature_of_service, service_description,
  status, created_at, updated_at, created_by

supplier_ledger_map
  id, supplier_id → suppliers.id (CASCADE DELETE),
      ledger_id  → vendors.id   (CASCADE DELETE)
  UNIQUE (supplier_id, ledger_id)
```

---

## Important Notes

- `ledgerCode` and `supplierCode` are auto-generated. Never send on create.
- `supplierTypes` stored as JSON array. **Values are case-sensitive** — use exact values: `Materials`, `Work_Force`, `Plant_Machinery`, `others`.
- On the Ledger create/update API, `supplierTypes` is sent as a **JSON string** (multipart form): `'["Materials","Work_Force"]'`.
- On the Supplier create/update API, `supplierTypes` is a plain **JSON array** (application/json body): `["Materials", "Work_Force"]`.
- `natureOfService` is a single selected string. The dropdown list comes from `GET /supplier/nature-of-service?types=...` — pass all currently selected types to get the merged list.
- Sync is **automatic** — no separate sync endpoint needed.
- Deleting a Supplier cascades and removes all mappings. `vendor.supplier_id` becomes `NULL`.
- Linking the same ledger to the same supplier twice returns `409 Conflict`.
