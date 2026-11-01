# Category, Group and Head Under: how they work

This document explains how **Category**, **Group** and **Head Under** are set up in the backend, which tables use them, and where they are used as filters.

---

## 1. Overview

```
Head Under  (plain text on Group: "Profit & Loss" / "Balance Sheet")
   └── Group          (group_master)         e.g. Direct Expenses, Fixed Asset
         └── CC Code  (cc_codes)             has a group_id AND a category_code
               └── Item / Asset              has a cc_code_id AND a category_code

Category   (category_master)  standalone list, linked by fixed_code
   ├── Item, Asset, CC Code, Vendor (Ledger), Unit
   └── Indent, Enquiry, Order (sub_code), Project-Work Order (sub_codes)
```

- **Head Under** is a text field on Group. It is not a table of its own.
- **Group** only links to **CC Code**. Items and assets reach a group through their CC code.
- **Category** is a separate list. Other tables link to it by **`fixed_code`** (for example `MAT_001`), not by `id`.

---

## 2. Tables

File: `app/models/category_group.py`

### 2.1 `group_master` (GroupMaster)

| Column       | Type        | Notes                                              |
|--------------|-------------|----------------------------------------------------|
| `id`         | Integer PK  | Used as `group_id` in `cc_codes`                   |
| `group_name` | String(150) | Unique. e.g. `Direct Expenses`, `Fixed Asset`      |
| `head_under` | String(100) | Required. Expected values: `Profit & Loss` / `Balance Sheet` (free text, not checked) |
| `status`     | String(30)  | Default `Active`                                   |
| `created_at`, `updated_at`, `created_by` | | Audit fields                    |

### 2.2 `category_master` (CategoryMaster)

| Column          | Type        | Notes                                                   |
|-----------------|-------------|---------------------------------------------------------|
| `id`            | Integer PK  | Returned to the API as `categoryId` but **not** used as a foreign key |
| `fixed_code`    | String(50)  | Unique. **This is the key other tables use** (`category_code`) |
| `category_name` | String(150) | Unique. Display name                                    |
| `status`        | String(30)  | Default `Active`                                        |
| `created_at`, `updated_at`, `created_by` | | Audit fields                         |

> There is **no** `head_under` column on Category. Head Under exists only on Group.

### 2.3 Seeded categories (`app/seed_data.py` → `seed_category_master()`)

| Use            | fixed_code | category_name |
|----------------|------------|---------------|
| Item category  | `MAT_001`  | Material      |
|                | `SER_001`  | Service       |
|                | `EXP_001`  | Expenses      |
|                | `COM_001`  | Composite     |
| CC category    | `TDS_001`  | TDS           |
|                | `GST_001`  | GST           |
|                | `REV_001`  | Revenue       |
| Ledger category| `VEN_001`  | Vendor        |
|                | `VEN_002`  | Non Vendor    |
| Unit category  | `UNIT_001` | Length        |
|                | `UNIT_002` | Area          |
|                | `UNIT_003` | Volume        |
|                | `UNIT_004` | Time          |
|                | `UNIT_005` | Weight        |
|                | `UNIT_006` | Count         |

Groups are **not** seeded. Group names the code depends on (hardcoded):
`Fixed Asset`, `Direct Expenses`, `Indirect Expenses`, `Project Overhead`, `Employee Overhead`.

---

## 3. Where they are stored (foreign keys)

| Table / Model                         | Column          | Points to                         | Meaning                    |
|---------------------------------------|-----------------|-----------------------------------|----------------------------|
| `cc_codes` (CCCode)                   | `group_id`      | `group_master.id` (required)      | Group of the CC code       |
| `cc_codes` (CCCode)                   | `category_code` | `category_master.fixed_code` (required) | Category of the CC code |
| `items` (Item)                        | `category_code` | `category_master.fixed_code`      | Item category (MAT/SER/…)  |
| `items` (Item)                        | `cc_code_id`    | `cc_codes.id`                     | Group is reached via this  |
| `assets` (Asset)                      | `category_code` | `category_master.fixed_code`      | Asset category             |
| `vendors` (Vendor / Ledger)           | `category_code` | `category_master.fixed_code`      | Vendor / Non Vendor        |
| `units` (Unit)                        | `category_code` | `category_master.fixed_code`      | Length / Area / …          |
| `indent_master` (IndentMaster)        | `category_code` | `category_master.fixed_code`      | Indent category            |
| `enquiry_master` (EnquiryMaster)      | `category_code` | `category_master.fixed_code`      | Copied from indent         |
| `order_master` (OrderMaster)          | `sub_code`      | `category_master.fixed_code`      | **Item category** of order |
| `order_master` (OrderMaster)          | `category_code` | none (plain text)                 | **Order type**, e.g. `Site_Transfer_Order`, `Customer_Supply_Order` |
| `order_master` (OrderMaster)          | `cost_head`     | none (plain text)                 | Cost head                  |
| Project-work order master             | `sub_codes`     | none (JSON text list, e.g. `["SER_001","COM_001"]`) | Item categories |
| Project-work order master             | `category_code`, `cost_head` | none (plain text)    | Order type / cost head     |

> Watch out: in **Orders**, `sub_code` is the Category Master link and `category_code` is the order type. In every other table, `category_code` is the Category Master link.

---

## 4. Master APIs (create / list / update)

Routes: `app/modules/master/routes.py` · Logic: `app/modules/master/service.py`

### Group

| Method | URL                               | Body / Params                      | Notes |
|--------|-----------------------------------|------------------------------------|-------|
| POST   | `/group/create`                   | `{ groupName, headUnder }`         | Admin only. Rejects duplicate `groupName` |
| GET    | `/group/list`                     | –                                  | Returns `groupId, groupName, headUnder, status`. No filters |
| PUT    | `/group/update/<groupId>`         | `{ groupName?, headUnder? }`       | Admin only |

### Category

| Method | URL                               | Body / Params                      | Notes |
|--------|-----------------------------------|------------------------------------|-------|
| POST   | `/category/create`                | `{ categoryCode, categoryName }`   | Admin only. `categoryCode` is saved as `fixed_code` |
| GET    | `/category/list`                  | query params accepted but **ignored** | Returns `categoryId, categoryCode, categoryName, status` |
| PUT    | `/category/update/<categoryId>`   | `{ categoryCode?, categoryName? }` | Uses numeric `id` in URL |

### CC Code

| Method | URL                         | Body / Params                                   |
|--------|-----------------------------|-------------------------------------------------|
| POST   | `/cc-code/create`           | `{ ccCode, ccName, groupId, categoryId }` — `categoryId` must be the **fixed_code** |
| GET    | `/cc-code/list`             | `?categoryId=&key=&search=` (see filters below) |
| GET    | `/cc-code/<ccId>`           | –                                               |
| PUT    | `/cc-code/update/<ccId>`    | `{ ccCode?, ccName?, groupId?, categoryId? }`   |

### Item / Asset / Vendor / Unit
All send and receive the category as **fixed_code**:
- Item & Asset: `itemCategoryId` → `category_code`
- Vendor (Ledger): `categoryId` → `category_code`
- Unit: `categoryId` → `category_code`

> Naming note: the API calls it `categoryId` / `itemCategoryId`, but the value is the **fixed_code** string (e.g. `MAT_001`), not the numeric id.

---

## 5. Filters: where and how they are used

### 5.1 Head Under
- Saved and returned on Group create / update / list.
- **Not used in any filter** or report. Profit & Loss and Balance Sheet services do not read `head_under`.

### 5.2 Group filters

| API | Param | Logic | File |
|-----|-------|-------|------|
| `GET /cc-code/list` | `key=asset` | Only CC codes whose group is `Fixed Asset` | `master/service.py` `get_all_cc_codes` |
| `GET /cc-code/list` | `key=item` (and no `categoryId`) | Only groups in `Direct Expenses`, `Indirect Expenses`, `Project Overhead`, `Employee Overhead` | same |
| `GET /cc-code/list` | `key=item` + `categoryId` | Group filter skipped; category decides | same |
| Budget `GET /cc-codes` | `group=<group name>` | Active CC codes, optional exact `group_name` match. Returns group + category names | `project_mgmt/contract/budget/service.py` `get_cc_codes_list` |
| Indent `GET /items-by-category` | `assetOnly=true` | Items whose CC code group = `Fixed Asset` | `resources/indent/service.py` `get_items_by_category` |
| Indent `GET /items-by-category` | `assetOnly=false` | Items whose group ≠ `Fixed Asset` (or no group) | same |
| Indent `GET /items-by-category` | not passed | No group filter. If `categoryCode=MAT_001`, assets are added to the list too | same |

### 5.3 Category filters

| API / Function | Param | Filters on | File |
|----------------|-------|-----------|------|
| `GET /cc-code/list` | `categoryId` | `CCCode.category_code` | `master/service.py` |
| `GET /unit/list` | `categoryId`, `unitType` | `Unit.category_code` | `master/service.py` `get_all_units` |
| Indent `GET /items-by-category` | `categoryCode` | `Item.category_code` | `resources/indent/service.py` |
| Indent create / update | `categoryCode` | Checks it exists in Category Master; every item/asset must have the same category | `resources/indent/service.py` |
| Indent list | `categoryCode` | `IndentMaster.category_code` | `resources/indent/service.py` |
| Enquiry list | `categoryCode` | `EnquiryMaster.category_code` | `resources/enquiry/service.py` |
| Order `GET /indent-pending` | `subCategoryCode`, `assetOnly` | `IndentMaster.category_code == subCategoryCode` (approved indents) | `resources/order/service.py` |
| Order `GET /list` | `subCategoryCode`, `categoryCode` | `OrderMaster.sub_code`, `OrderMaster.category_code` (order type) | `resources/order/service.py` |
| Project-work order items | `subCodes=SER_001,COM_001` | `Item.category_code IN (...)`, joins Category Master for names | `resources/order_projectwork/service.py` `get_item_list_by_subcategories` |
| Project-work order list | `categoryCode` | `ProjectWorkOrderMaster.category_code` | `resources/order_projectwork/service.py` |
| GRN – orders by vendor | `receivedCategory` | `OrderMaster.category_code` | `resources/grn/service.py` |
| GIN | issue category | `OrderMaster.category_code` | `resources/gin/service.py` |
| SRN | `receivedCategory`, `itemCategory` (comma list) | `ProjectWorkOrderMaster.category_code` + sub codes | `resources/srn/service.py` |
| DC | – | `OrderMaster.category_code == "Site_Transfer_Order"` (or not) | `resources/dc/service.py` |
| Vendor Billing GRN | `receivedCategory`, `itemCategory`, `costHead` | `OrderMaster.category_code`, `sub_code`, `cost_head` | `resources/vendor_billing_grn/service.py` |
| Vendor Billing SRN | `receivedCategory` | `ProjectWorkOrderMaster.category_code` | `resources/vendor_billing_srn/service.py` |
| Bill Receive Register | order category | `OrderMaster.category_code` / `ProjectWorkOrderMaster.category_code` | `billing/bill_receive_register/service.py` |

### 5.4 Category name lookups (display only)
These read Category Master to turn a `fixed_code` into a name:
- `finance/purchase_bill/service.py` – code → name map for orders
- `billing/brr_billing/service.py` – code → name map
- `resources/order/service.py` – sub-category name for order details
- `resources/order_projectwork/service.py` – category name per code
- Order PDF (`order_pdf_rl_service.py`) – prints `order.category_code` (name lookup is commented out)
- Search schema (`search/schema.py`) – exposes `category_code` as a searchable "Category" field

---

## 6. Known issues

1. **`app/modules/helper.py` → `get_category_by_head_under()`** filters `CategoryMaster.head_under`, but Category has no such column. It would crash if called. It is imported in `master/service.py` but not used by any route.
2. **`app/modules/helper.py` → `get_cc_code_list()`** filters `CCCode.category_id`, but the column is `category_code`. Same: imported, not used.
3. **Head Under is free text.** Nothing stops values other than `Profit & Loss` / `Balance Sheet`, and no report uses it.
4. **Hardcoded group names** (`Fixed Asset`, `Direct Expenses`, …) in CC code list and indent item filters. Renaming a group in the UI will silently break these filters.
5. **`/category/list`** accepts query params but does not filter by them.
6. **Naming mismatch:** APIs call the field `categoryId`, but it holds the `fixed_code` string.
