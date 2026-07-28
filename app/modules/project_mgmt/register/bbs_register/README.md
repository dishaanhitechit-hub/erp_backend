# BBS Register API

Base URL: `/project-mgmt/register/bbs-register`
All endpoints require `Authorization: Bearer <token>` unless noted otherwise.

---

## Table of Contents

1. [Create Record](#1-create-record)
2. [List Records](#2-list-records)
3. [Record Details](#3-record-details)
4. [Record by UUID (Public)](#4-record-by-uuid-public)
5. [Edit Record](#5-edit-record)
6. [Submit Record](#6-submit-record)
7. [Approve Record](#7-approve-record)
8. [Reback Record](#8-reback-record)
9. [Reject Record](#9-reject-record)
10. [Delete Record](#10-delete-record)
11. [History](#11-history)
12. [My Approval Status](#12-my-approval-status)
13. [Workflow States](#workflow-states)
14. [Delivery Mode Values](#delivery-mode-values)
15. [DB Table](#db-table)
16. [Migration](#migration)

---

## 1. Create Record

```
POST /project-mgmt/register/bbs-register/create
Content-Type: multipart/form-data
```

> Caller must have a `CREATOR` entry in `ApprovalPath` for `module_code = "bbs_register"` and the given `projectCode`.

### Form Fields

| Field | Required | Description |
|---|---|---|
| `projectCode` | ✅ | Project code |
| `revision` | ❌ | Revision number / label |
| `bbsTitle` | ❌ | BBS title / description |
| `referenceOrderNo` | ❌ | Reference order number (free text for now) |
| `projectSubLocation` | ❌ | Project sub-location or unit |
| `segmentLayer` | ❌ | Segment / layer reference |
| `receivedDate` | ❌ | Date received (YYYY-MM-DD) |
| `receivedTime` | ❌ | Time received (HH:MM) |
| `receivedBy` | ❌ | Name of person who received |
| `deliveredBy` | ❌ | Name of person who delivered |
| `deliveryMode` | ❌ | See [Delivery Mode Values](#delivery-mode-values) |
| `deliveryReference` | ❌ | Delivery reference number / note |
| `attachment` | ❌ | File upload |

### Response `201`

```json
{
    "message": "BBS Register created",
    "data": {
        "id": 1,
        "bbsNo": "BBS001",
        "uuid": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
    }
}
```

---

## 2. List Records

```
GET /project-mgmt/register/bbs-register/list
```

### Query Params

| Param | Required | Description |
|---|---|---|
| `projectCode` | ✅ | Project code |
| `workflowStatus` | ❌ | `Draft` / `Pending_L1` / `Approved` / `Reback` / `Rejected` |
| `search` | ❌ | Search by BBS No or BBS Title |

### Response `200`

```json
{
    "message": "BBS Register list fetched",
    "data": [
        {
            "id": 1,
            "bbsNo": "BBS001",
            "uuid": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
            "projectCode": "DHLE",
            "revision": "R1",
            "bbsTitle": "Foundation RCC BBS",
            "referenceOrderNo": "SO-2026-001",
            "receivedDate": "2026-07-28",
            "receivedBy": "Site Engineer",
            "workflowStatus": "Approved",
            "createdBy": "soumyajit",
            "createdAt": "2026-07-28 10:00:00"
        }
    ]
}
```

---

## 3. Record Details

```
GET /project-mgmt/register/bbs-register/details/<id>
```

### Response `200`

```json
{
    "message": "BBS Register details fetched",
    "data": {
        "id": 1,
        "bbsNo": "BBS001",
        "uuid": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
        "projectCode": "DHLE",
        "projectName": "400KV GIS Sub Station at Dhule",
        "revision": "R1",
        "bbsTitle": "Foundation RCC BBS",
        "referenceOrderNo": "SO-2026-001",
        "projectSubLocation": "Grid A / Zone 1",
        "segmentLayer": "Footing Layer 1",
        "receivedDate": "2026-07-28",
        "receivedTime": "09:30",
        "receivedBy": "Site Engineer",
        "deliveredBy": "Vendor Rep",
        "deliveryMode": "By Hand",
        "deliveryReference": "DEL-001",
        "attachment": "https://cdn.example.com/bbs_register/BBS001/attachment",
        "workflowStatus": "Draft",
        "status": "Active",
        "currentLevel": 0,
        "locked": false,
        "createdBy": "soumyajit",
        "createdAt": "2026-07-28 09:00:00",
        "approvedBy": null,
        "finalApprovedAt": null
    }
}
```

---

## 4. Record by UUID (Public)

No JWT required — used for QR / public link access.

```
GET /project-mgmt/register/bbs-register/uuid/<uuid>
```

Returns the same shape as [Record Details](#3-record-details).

---

## 5. Edit Record

```
PUT /project-mgmt/register/bbs-register/edit/<id>
Content-Type: multipart/form-data
```

> Only `Draft` or `Reback` records can be edited (`locked = false`).
> Caller must be the creator.

Same form fields as [Create Record](#1-create-record). Only fields present in the request are updated.

### Response `200`

```json
{
    "message": "BBS Register updated",
    "data": { "id": 1, "bbsNo": "BBS001" }
}
```

---

## 6. Submit Record

```
POST /project-mgmt/register/bbs-register/submit/<id>
```

> Only `Draft` or `Reback` records can be submitted.
> If no approver is configured for this project + module, the record is auto-approved.

### Response `200`

```json
{
    "message": "BBS Register submitted successfully",
    "data": {
        "id": 1,
        "bbsNo": "BBS001",
        "workflowStatus": "Pending_L1"
    }
}
```

---

## 7. Approve Record

```
POST /project-mgmt/register/bbs-register/approve/<id>
Content-Type: application/json
```

```json
{ "comments": "Verified and approved" }
```

> Caller must be the current approver at the active level.
> Advances to the next level if one exists; otherwise sets status to `Approved`.

### Response `200`

```json
{
    "message": "BBS Register approved successfully",
    "data": {
        "id": 1,
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

## 8. Reback Record

```
POST /project-mgmt/register/bbs-register/reback/<id>
Content-Type: application/json
```

```json
{ "comments": "Revision number missing" }
```

> `comments` is **required**.

### Response `200`

```json
{
    "message": "BBS Register sent for correction",
    "data": { "id": 1, "workflowStatus": "Reback" }
}
```

---

## 9. Reject Record

```
POST /project-mgmt/register/bbs-register/reject/<id>
Content-Type: application/json
```

```json
{ "comments": "Incorrect segment reference" }
```

> `comments` is **required**.

### Response `200`

```json
{
    "message": "BBS Register rejected",
    "data": { "id": 1, "workflowStatus": "Rejected" }
}
```

---

## 10. Delete Record

```
DELETE /project-mgmt/register/bbs-register/delete/<id>
```

> Only `Draft` or `Reback` records can be deleted (`locked = false`).

### Response `200`

```json
{ "message": "BBS Register deleted", "data": [] }
```

---

## 11. History

```
GET /project-mgmt/register/bbs-register/history/<id>
```

### Response `200`

```json
{
    "message": "BBS Register history fetched",
    "data": {
        "workflowStatus": "Approved",
        "currentLevel": 1,
        "approvalSteps": [
            {
                "level": 1,
                "approver": { "userId": 3, "username": "manager01" },
                "status": "Approved",
                "actionAt": "2026-07-28 14:00:00",
                "comments": "Verified and approved"
            }
        ],
        "history": [
            {
                "id": 1,
                "action": "SUBMIT",
                "level": 0,
                "comments": null,
                "actionBy": "soumyajit",
                "createdAt": "2026-07-28 10:00:00"
            },
            {
                "id": 2,
                "action": "FINAL_APPROVE",
                "level": 1,
                "comments": "Verified and approved",
                "actionBy": "manager01",
                "createdAt": "2026-07-28 14:00:00"
            }
        ]
    }
}
```

---

## 12. My Approval Status

```
GET /project-mgmt/register/bbs-register/my-approval-status/<id>
Authorization: Bearer <token>
```

### Response `200`

```json
{
    "message": "Approval status fetched",
    "data": {
        "isPendingForMe": true,
        "myLevel": 1,
        "workflowStatus": "Pending_L1",
        "currentLevel": 1
    }
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

---

## Delivery Mode Values

| Value | Description |
|---|---|
| `By Hand` | Physical hand delivery |
| `By Letter` | Delivered via letter / post |
| `By Mail` | Sent via email |
| `WhatsApp` | Shared via WhatsApp |
| `By Data Card` | Shared via data card / USB |

---

## DB Table

Table name: `bbs_register`

| Column | Type | Description |
|---|---|---|
| `id` | integer PK | Auto increment |
| `bbs_no` | varchar(50) unique | Auto-generated — BBS001, BBS002 … |
| `bbs_uuid` | varchar(36) unique | UUID for public / QR access |
| `project_code` | varchar(50) FK → projects | |
| `revision` | varchar(50) | |
| `bbs_title` | varchar(500) | |
| `reference_order_no` | varchar(100) | Sale order ref — plain text for now |
| `project_sub_location` | varchar(200) | |
| `segment_layer` | varchar(200) | |
| `received_date` | date | |
| `received_time` | time | |
| `received_by` | varchar(200) | |
| `delivered_by` | varchar(200) | |
| `delivery_mode` | varchar(100) | See delivery mode values above |
| `delivery_reference` | varchar(200) | |
| `attachment` | text | File URL |
| `workflow_status` | varchar(30) | Draft / Pending_Lx / Approved / Reback / Rejected |
| `status` | varchar(30) | Active / Inactive |
| `current_level` | integer | Active approval level |
| `locked` | boolean | True when submitted or approved |
| `created_by` | integer FK → users | |
| `updated_by` | integer FK → users | |
| `submitted_by` | integer FK → users | |
| `approved_by` | integer FK → users | Final approver |
| `rejected_by` | integer FK → users | |
| `created_at` | datetime | |
| `updated_at` | datetime | |
| `submitted_at` | datetime | |
| `final_approved_at` | datetime | |
| `rejected_at` | datetime | |
| `correction_sent_at` | datetime | Set on reback |

---

## Migration

```bash
flask db migrate -m "add bbs register"
flask db upgrade
```

After migration, seed `ApprovalPath` rows for each project:

```sql
-- Creator
INSERT INTO approval_path (project_code, module_code, user_id, path_type, level_no)
VALUES ('DHLE', 'bbs_register', <user_id>, 'CREATOR', NULL);

-- Approver (level 1)
INSERT INTO approval_path (project_code, module_code, user_id, path_type, level_no)
VALUES ('DHLE', 'bbs_register', <approver_id>, 'APPROVER', 1);
```
