# Drawing Register

Base URL: `/project-mgmt/register/drawing-register`
Auth: All endpoints require `Authorization: Bearer <JWT>` header.
Module Code: `drawing_register`

---

## Table of Contents

1. [Create Drawing Register](#1-create-drawing-register)
2. [List](#2-list)
3. [Details](#3-details)
4. [Edit](#4-edit)
5. [Submit](#5-submit)
6. [Approve](#6-approve)
7. [Reback](#7-reback)
8. [Reject](#8-reject)
9. [History](#9-history)
10. [Workflow States](#workflow-states)
11. [DB Table](#db-table)

---

## 1. Create Drawing Register

Create a new Drawing Register entry in **Draft** status.

**POST** `/project-mgmt/register/drawing-register/create`

Content-Type: `multipart/form-data`

### Form Fields

| Field               | Type   | Required | Description                                                             |
|---------------------|--------|----------|-------------------------------------------------------------------------|
| projectCode         | string | Yes      | Project code                                                            |
| drawingNo           | string | No       | Drawing number                                                          |
| revision            | string | No       | Revision identifier (e.g. R0, R1)                                       |
| drawingTitle        | string | No       | Full title of the drawing                                               |
| referenceOrderNo    | string | No       | Sale order reference — plain text for now, lookup to be wired later     |
| projectSubLocation  | string | No       | Project sub-location / unit                                             |
| segmentLayer        | string | No       | Segment or layer reference                                              |
| receivedDate        | date   | No       | Date drawing was received (`YYYY-MM-DD`)                                |
| receivedTime        | time   | No       | Time drawing was received (`HH:MM`)                                     |
| receivedBy          | string | No       | Name of person who received the drawing                                 |
| deliveredBy         | string | No       | Name of person who delivered the drawing                                |
| deliveryMode        | string | No       | Mode of delivery — `By Hand` / `By Letter` / `By Mail` / `WhatsApp` / `By Data Card` |
| deliveryReference   | string | No       | Reference number/note for delivery                                      |
| attachment          | file   | No       | Any supporting document/file                                            |

### Success Response `201`

```json
{
  "message": "Drawing Register created",
  "data": {
    "drId": 1,
    "drNo": "900001"
  },
  "status": 201
}
```

### Error Responses

| Status | Message                                  |
|--------|------------------------------------------|
| 403    | `You are not Drawing Register creator`   |
| 500    | Internal server error                    |

---

## 2. List

Get a filtered list of Drawing Register entries for a project.

**GET** `/project-mgmt/register/drawing-register/list`

### Query Parameters

| Parameter      | Type   | Required | Description                                              |
|----------------|--------|----------|----------------------------------------------------------|
| projectCode    | string | Yes      | Project code                                             |
| workflowStatus | string | No       | Filter by status (`Draft`, `Pending_L1`, `Approved` …)  |
| search         | string | No       | Partial match on `drNo`, `drawingNo`, or `drawingTitle`  |

### Success Response `200`

```json
{
  "message": "Drawing Register list fetched",
  "data": [
    {
      "id": 1,
      "drNo": "900001",
      "projectCode": "PROJ-001",
      "drawingNo": "DWG-STRUCT-001",
      "revision": "R1",
      "drawingTitle": "Foundation Layout Plan",
      "referenceOrderNo": "SO-2024-045",
      "receivedDate": "2024-06-05",
      "receivedBy": "Rahul Sharma",
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

## 3. Details

Get full details of a single Drawing Register entry.

**GET** `/project-mgmt/register/drawing-register/details/<dr_id>`

### Path Parameters

| Parameter | Type | Description           |
|-----------|------|-----------------------|
| dr_id     | int  | Drawing Register ID   |

### Success Response `200`

```json
{
  "message": "Drawing Register details fetched",
  "data": {
    "id": 1,
    "drNo": "900001",
    "projectCode": "PROJ-001",

    "drawingNo": "DWG-STRUCT-001",
    "revision": "R1",
    "drawingTitle": "Foundation Layout Plan",

    "referenceOrderNo": "SO-2024-045",
    "projectSubLocation": "Block B / Unit 3",
    "segmentLayer": "Layer 2 - Structural",

    "receivedDate": "2024-06-05",
    "receivedTime": "14:30",
    "receivedBy": "Rahul Sharma",
    "deliveredBy": "Courier Agent",
    "deliveryMode": "By Hand",
    "deliveryReference": "REF-2024-001",

    "attachment": "https://cdn.example.com/drawing_register/900001/attachment",
    "workflowStatus": "Draft",
    "currentLevel": 0,
    "locked": false
  },
  "status": 200
}
```

### Error Responses

| Status | Message                          |
|--------|----------------------------------|
| 404    | `Drawing Register not found`     |
| 500    | Internal server error            |

---

## 4. Edit

Edit a Drawing Register entry that is in `Draft` or `Reback` status.
Only provided fields are updated — all fields are optional except the record must exist and be unlocked.

**PUT** `/project-mgmt/register/drawing-register/edit/<dr_id>`

Content-Type: `multipart/form-data`

### Path Parameters

| Parameter | Type | Description         |
|-----------|------|---------------------|
| dr_id     | int  | Drawing Register ID |

### Form Fields

All fields are optional — only sent fields will be updated.

| Field               | Type   | Description                                   |
|---------------------|--------|-----------------------------------------------|
| drawingNo           | string | Updated drawing number                        |
| revision            | string | Updated revision                              |
| drawingTitle        | string | Updated drawing title                         |
| referenceOrderNo    | string | Updated sale order reference                  |
| projectSubLocation  | string | Updated sub-location / unit                   |
| segmentLayer        | string | Updated segment / layer                       |
| receivedDate        | date   | Updated received date (`YYYY-MM-DD`)          |
| receivedTime        | time   | Updated received time (`HH:MM`)               |
| receivedBy          | string | Updated received by                           |
| deliveredBy         | string | Updated delivered by                          |
| deliveryMode        | string | Updated delivery mode                         |
| deliveryReference   | string | Updated delivery reference                    |
| attachment          | file   | Replace existing attachment                   |

### Success Response `200`

```json
{
  "message": "Drawing Register updated successfully",
  "data": {
    "drId": 1,
    "drNo": "900001"
  },
  "status": 200
}
```

### Error Responses

| Status | Message                                       |
|--------|-----------------------------------------------|
| 404    | `Drawing Register not found`                  |
| 400    | `Drawing Register cannot be edited` (locked)  |
| 400    | `Only Draft or Reback records can be edited`  |
| 403    | `You are not Drawing Register creator`        |
| 500    | Internal server error                         |

---

## 5. Submit

Submit a `Draft` or `Reback` Drawing Register for approval.
Moves to `Pending_L1` if workflow is configured, or auto-approves if no approver is set.

**POST** `/project-mgmt/register/drawing-register/submit/<dr_id>`

### Path Parameters

| Parameter | Type | Description         |
|-----------|------|---------------------|
| dr_id     | int  | Drawing Register ID |

No request body required.

### Success Response `200`

```json
{
  "message": "Drawing Register submitted successfully",
  "data": {
    "drId": 1,
    "drNo": "900001",
    "workflowStatus": "Pending_L1"
  },
  "status": 200
}
```

### Error Responses

| Status | Message                                  |
|--------|------------------------------------------|
| 404    | `Drawing Register not found`             |
| 400    | `Drawing Register already submitted`     |
| 500    | Internal server error                    |

---

## 6. Approve

Approve a pending Drawing Register. Advances to next level or sets to `Approved` at final level.

**POST** `/project-mgmt/register/drawing-register/approve/<dr_id>`

### Path Parameters

| Parameter | Type | Description         |
|-----------|------|---------------------|
| dr_id     | int  | Drawing Register ID |

### Request Body (JSON)

```json
{
  "comments": "Drawing verified and approved."
}
```

| Field    | Type   | Required | Description        |
|----------|--------|----------|--------------------|
| comments | string | No       | Approver's remarks |

### Success Response `200`

```json
{
  "message": "Drawing Register approved successfully",
  "data": {
    "drId": 1,
    "workflowStatus": "Approved",
    "currentLevel": 1
  },
  "status": 200
}
```

### Error Responses

| Status | Message                          |
|--------|----------------------------------|
| 404    | `Drawing Register not found`     |
| 400    | `Drawing Register not pending`   |
| 403    | `You are not current approver`   |
| 500    | Internal server error            |

---

## 7. Reback

Send a pending Drawing Register back for correction. Unlocks the record and sets status to `Reback`.

**POST** `/project-mgmt/register/drawing-register/reback/<dr_id>`

### Path Parameters

| Parameter | Type | Description         |
|-----------|------|---------------------|
| dr_id     | int  | Drawing Register ID |

### Request Body (JSON)

```json
{
  "comments": "Drawing title incorrect, please revise."
}
```

| Field    | Type   | Required | Description                         |
|----------|--------|----------|-------------------------------------|
| comments | string | Yes      | Reason for sending back (mandatory) |

### Success Response `200`

```json
{
  "message": "Drawing Register sent for correction",
  "data": {
    "drId": 1,
    "workflowStatus": "Reback"
  },
  "status": 200
}
```

### Error Responses

| Status | Message                          |
|--------|----------------------------------|
| 404    | `Drawing Register not found`     |
| 400    | `Drawing Register not pending`   |
| 400    | `Comments required`              |
| 403    | `You are not current approver`   |
| 500    | Internal server error            |

---

## 8. Reject

Permanently reject a pending Drawing Register. Locks the record and sets status to `Rejected`.

**POST** `/project-mgmt/register/drawing-register/reject/<dr_id>`

### Path Parameters

| Parameter | Type | Description         |
|-----------|------|---------------------|
| dr_id     | int  | Drawing Register ID |

### Request Body (JSON)

```json
{
  "comments": "Drawing does not meet project specifications."
}
```

| Field    | Type   | Required | Description                         |
|----------|--------|----------|-------------------------------------|
| comments | string | Yes      | Reason for rejection (mandatory)    |

### Success Response `200`

```json
{
  "message": "Drawing Register rejected",
  "data": {
    "drId": 1,
    "workflowStatus": "Rejected"
  },
  "status": 200
}
```

### Error Responses

| Status | Message                          |
|--------|----------------------------------|
| 404    | `Drawing Register not found`     |
| 400    | `Drawing Register not pending`   |
| 400    | `Comments required`              |
| 403    | `You are not current approver`   |
| 500    | Internal server error            |

---

## 9. History

Get the complete workflow action history for a Drawing Register entry.

**GET** `/project-mgmt/register/drawing-register/history/<dr_id>`

### Path Parameters

| Parameter | Type | Description         |
|-----------|------|---------------------|
| dr_id     | int  | Drawing Register ID |

### Success Response `200`

```json
{
  "message": "Drawing Register history fetched",
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
      "action": "REBACK",
      "level": 1,
      "comments": "Drawing title incorrect, please revise.",
      "actionBy": "manager.user",
      "createdAt": "20240605 16:10:22"
    },
    {
      "id": 3,
      "action": "SUBMIT",
      "level": 0,
      "comments": null,
      "actionBy": "john.doe",
      "createdAt": "20240606 09:05:00"
    },
    {
      "id": 4,
      "action": "FINAL_APPROVE",
      "level": 1,
      "comments": "Drawing verified and approved.",
      "actionBy": "manager.user",
      "createdAt": "20240606 11:30:45"
    }
  ],
  "status": 200
}
```

### History Action Values

| Action        | Description                                     |
|---------------|-------------------------------------------------|
| SUBMIT        | Record submitted for approval                   |
| APPROVE       | Approved at an intermediate level               |
| FINAL_APPROVE | Final approval — status becomes `Approved`      |
| REBACK        | Sent back for correction                        |
| REJECT        | Permanently rejected                            |

### Error Responses

| Status | Message                      |
|--------|------------------------------|
| 404    | `Drawing Register not found` |
| 500    | Internal server error        |

---

## Workflow States

```
Draft → [Submit] → Pending_L1 → [Approve] → Pending_L2 → ... → Approved
                              → [Reback]  → Reback → [Submit] → Pending_L1
                              → [Reject]  → Rejected
```

| Status       | Editable | Locked | Description                               |
|--------------|----------|--------|-------------------------------------------|
| Draft        | Yes      | No     | Newly created, not yet submitted          |
| Pending_L{n} | No       | Yes    | Awaiting approval at level n              |
| Reback       | Yes      | No     | Sent back for correction by approver      |
| Approved     | No       | Yes    | Final approval done                       |
| Rejected     | No       | Yes    | Permanently rejected                      |

---

## DB Table

### `drawing_register`

| Column              | Type         | Notes                                          |
|---------------------|--------------|------------------------------------------------|
| id                  | int PK       | Auto increment                                 |
| dr_no               | varchar(50)  | Unique, auto-generated serial (starts 900001)  |
| project_code        | varchar(50)  | FK → projects.project_code                     |
| drawing_no          | varchar(100) | Drawing number                                 |
| revision            | varchar(50)  | Revision e.g. R0, R1                           |
| drawing_title       | varchar(500) | Full drawing title                             |
| reference_order_no  | varchar(100) | Sale order ref — plain text, lookup TBD        |
| project_sub_location| varchar(200) | Sub-location / unit                            |
| segment_layer       | varchar(200) | Segment or layer                               |
| received_date       | date         |                                                |
| received_time       | time         |                                                |
| received_by         | varchar(200) |                                                |
| delivered_by        | varchar(200) |                                                |
| delivery_mode       | varchar(100) | By Hand / By Letter / By Mail / WhatsApp / By Data Card |
| delivery_reference  | varchar(200) |                                                |
| attachment          | text         | CDN URL of uploaded file                       |
| workflow_status     | varchar(30)  | Default: Draft                                 |
| status              | varchar(30)  | Default: Active / Inactive on reject           |
| current_level       | int          | Default: 0                                     |
| locked              | boolean      | Default: false                                 |
| created_by          | int          | FK → users.id                                  |
| submitted_by        | int          | FK → users.id                                  |
| approved_by         | int          | FK → users.id                                  |
| rejected_by         | int          | FK → users.id                                  |
| updated_by          | int          | FK → users.id                                  |
| submitted_at        | datetime     |                                                |
| final_approved_at   | datetime     |                                                |
| rejected_at         | datetime     |                                                |
| correction_sent_at  | datetime     | Set when reback action is taken                |
| created_at          | datetime     | Auto                                           |
| updated_at          | datetime     | Auto                                           |

---

## Migration

```bash
flask db migrate -m "add drawing_register table"
flask db upgrade
```

---

## Notes

- **`referenceOrderNo`** is stored as plain text for now. When Sale Order lookup is ready, this will be converted to a proper FK with a fetch endpoint.
- **`drNo`** is auto-generated as a serial number starting from `900001`.
- **`deliveryMode`** accepted values: `By Hand`, `By Letter`, `By Mail`, `WhatsApp`, `By Data Card`.
- **`receivedTime`** format in payload: `HH:MM` — returned in response as `HH:MM`.
