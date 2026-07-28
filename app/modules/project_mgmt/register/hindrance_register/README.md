# Hindrance Register API

Base URL: `/project-mgmt/register/hindrance-register`
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
13. [Total Effected Amount Logic](#total-effected-amount-logic)
14. [Workflow States](#workflow-states)
15. [DB Table](#db-table)
16. [Migration](#migration)

---

## 1. Create Record

```
POST /project-mgmt/register/hindrance-register/create
Content-Type: multipart/form-data
```

> Caller must have a `CREATOR` entry in `ApprovalPath` for `module_code = "hindrance_register"` and the given `projectCode`.

### Form Fields

| Field | Required | Description |
|---|---|---|
| `projectCode` | ✅ | Project code |
| `hindranceDate` | ❌ | Date of hindrance (YYYY-MM-DD) |
| `titleOfHindrance` | ❌ | Short title |
| `causeOfHindrance` | ❌ | Detailed cause description |
| `manpowerDetails` | ❌ | Description of manpower impact |
| `manpowerAmount` | ❌ | Manpower effected amount (numeric) |
| `plantMachineryDetails` | ❌ | Description of plant & machinery impact |
| `plantMachineryAmount` | ❌ | Plant & machinery effected amount (numeric) |
| `materialsDetails` | ❌ | Description of materials impact |
| `materialsAmount` | ❌ | Materials effected amount (numeric) |
| `intimationTo` | ❌ | Person / authority intimated |
| `intimationVia` | ❌ | Mode of intimation |
| `attachment` | ❌ | File upload |

> `totalEffectedAmount` is calculated automatically as `manpowerAmount + plantMachineryAmount + materialsAmount`.

### Response `201`

```json
{
    "message": "Hindrance Register created",
    "data": {
        "id": 1,
        "hindranceNo": "HIN001",
        "uuid": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
    }
}
```

---

## 2. List Records

```
GET /project-mgmt/register/hindrance-register/list
```

### Query Params

| Param | Required | Description |
|---|---|---|
| `projectCode` | ✅ | Project code |
| `workflowStatus` | ❌ | `Draft` / `Pending_L1` / `Approved` / `Reback` / `Rejected` |
| `search` | ❌ | Search by Hindrance No or Title |

### Response `200`

```json
{
    "message": "Hindrance Register list fetched",
    "data": [
        {
            "id": 1,
            "hindranceNo": "HIN001",
            "uuid": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
            "hindranceDate": "2026-07-28",
            "titleOfHindrance": "Rain water logging",
            "manpowerAmount": 5000.0,
            "plantMachineryAmount": 12000.0,
            "materialsAmount": 3000.0,
            "totalEffectedAmount": 20000.0,
            "intimationTo": "Project Manager",
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
GET /project-mgmt/register/hindrance-register/details/<id>
```

### Response `200`

```json
{
    "message": "Hindrance Register details fetched",
    "data": {
        "id": 1,
        "hindranceNo": "HIN001",
        "uuid": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
        "projectCode": "DHLE",
        "projectName": "400KV GIS Sub Station at Dhule",
        "hindranceDate": "2026-07-28",
        "titleOfHindrance": "Rain water logging",
        "causeOfHindrance": "Heavy rainfall blocked access to Grid A",
        "manpowerDetails": "50 workers idle for 6 hours",
        "manpowerAmount": 5000.0,
        "plantMachineryDetails": "2 excavators and 1 crane idle",
        "plantMachineryAmount": 12000.0,
        "materialsDetails": "Concrete delivery delayed",
        "materialsAmount": 3000.0,
        "totalEffectedAmount": 20000.0,
        "attachment": "https://cdn.example.com/hindrance_register/HIN001/attachment",
        "intimationTo": "Project Manager",
        "intimationVia": "Email",
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
GET /project-mgmt/register/hindrance-register/uuid/<uuid>
```

Returns the same shape as [Record Details](#3-record-details).

---

## 5. Edit Record

```
PUT /project-mgmt/register/hindrance-register/edit/<id>
Content-Type: multipart/form-data
```

> Only `Draft` or `Reback` records can be edited (`locked = false`).
> Caller must be the creator.
> If any amount field is updated, `totalEffectedAmount` is recalculated automatically.

Same form fields as [Create Record](#1-create-record). Only fields present in the request are updated.

### Response `200`

```json
{
    "message": "Hindrance Register updated",
    "data": { "id": 1, "hindranceNo": "HIN001" }
}
```

---

## 6. Submit Record

```
POST /project-mgmt/register/hindrance-register/submit/<id>
```

> Only `Draft` or `Reback` records can be submitted.
> If no approver is configured for this project + module, the record is auto-approved.

### Response `200`

```json
{
    "message": "Hindrance Register submitted successfully",
    "data": {
        "id": 1,
        "hindranceNo": "HIN001",
        "workflowStatus": "Pending_L1"
    }
}
```

---

## 7. Approve Record

```
POST /project-mgmt/register/hindrance-register/approve/<id>
Content-Type: application/json
```

```json
{ "comments": "Verified on site" }
```

> Caller must be the current approver at the active level.

### Response `200`

```json
{
    "message": "Hindrance Register approved successfully",
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
POST /project-mgmt/register/hindrance-register/reback/<id>
Content-Type: application/json
```

```json
{ "comments": "Cause of hindrance needs more detail" }
```

> `comments` is **required**.

### Response `200`

```json
{
    "message": "Hindrance Register sent for correction",
    "data": { "id": 1, "workflowStatus": "Reback" }
}
```

---

## 9. Reject Record

```
POST /project-mgmt/register/hindrance-register/reject/<id>
Content-Type: application/json
```

```json
{ "comments": "Amounts not justified" }
```

> `comments` is **required**.

### Response `200`

```json
{
    "message": "Hindrance Register rejected",
    "data": { "id": 1, "workflowStatus": "Rejected" }
}
```

---

## 10. Delete Record

```
DELETE /project-mgmt/register/hindrance-register/delete/<id>
```

> Only `Draft` or `Reback` records can be deleted (`locked = false`).

### Response `200`

```json
{ "message": "Hindrance Register deleted", "data": [] }
```

---

## 11. History

```
GET /project-mgmt/register/hindrance-register/history/<id>
```

### Response `200`

```json
{
    "message": "Hindrance Register history fetched",
    "data": {
        "workflowStatus": "Approved",
        "currentLevel": 1,
        "approvalSteps": [
            {
                "level": 1,
                "approver": { "userId": 3, "username": "manager01" },
                "status": "Approved",
                "actionAt": "2026-07-28 14:00:00",
                "comments": "Verified on site"
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
                "comments": "Verified on site",
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
GET /project-mgmt/register/hindrance-register/my-approval-status/<id>
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

## Total Effected Amount Logic

`totalEffectedAmount` is always stored as:

```
totalEffectedAmount = manpowerAmount + plantMachineryAmount + materialsAmount
```

It is recalculated on every create and edit. The list endpoint returns all three individual amounts plus the total, matching the list page columns shown in the UI.

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

## DB Table

Table name: `hindrance_register`

| Column | Type | Description |
|---|---|---|
| `id` | integer PK | Auto increment |
| `hindrance_no` | varchar(50) unique | Auto-generated — HIN001, HIN002 … |
| `hindrance_uuid` | varchar(36) unique | UUID for public / QR access |
| `project_code` | varchar(50) FK → projects | |
| `hindrance_date` | date | |
| `title_of_hindrance` | varchar(500) | |
| `cause_of_hindrance` | text | |
| `manpower_details` | text | |
| `manpower_amount` | numeric(14,2) | |
| `plant_machinery_details` | text | |
| `plant_machinery_amount` | numeric(14,2) | |
| `materials_details` | text | |
| `materials_amount` | numeric(14,2) | |
| `total_effected_amount` | numeric(14,2) | Sum of three amounts — stored on save |
| `attachment` | text | BunnyCDN file URL |
| `intimation_to` | varchar(200) | |
| `intimation_via` | varchar(100) | |
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
flask db migrate -m "add hindrance register"
flask db upgrade
```

After migration, seed `ApprovalPath` rows for each project:

```sql
-- Creator
INSERT INTO approval_path (project_code, module_code, user_id, path_type, level_no)
VALUES ('DHLE', 'hindrance_register', <user_id>, 'CREATOR', NULL);

-- Approver (level 1)
INSERT INTO approval_path (project_code, module_code, user_id, path_type, level_no)
VALUES ('DHLE', 'hindrance_register', <approver_id>, 'APPROVER', 1);
```
