# Concrete Registry

Base URL: `/project-mgmt/register/concrete-registry`
Auth: All endpoints require `Authorization: Bearer <JWT>` header.
Module Code: `concrete_registry`

---

## Table of Contents

1. [Create Concrete Registry](#1-create-concrete-registry)
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

## 1. Create Concrete Registry

Create a new Concrete Registry entry in **Draft** status.

**POST** `/project-mgmt/register/concrete-registry/create`

Content-Type: `multipart/form-data`

### Form Fields

| Field               | Type   | Required | Description                                              |
|---------------------|--------|----------|----------------------------------------------------------|
| projectCode         | string | Yes      | Project code                                             |
| projectSubLocation  | string | Yes      | Project sub-location / unit                              |
| segment             | string | Yes      | Segment identifier                                       |
| pouringDate         | date   | Yes      | Date of concrete pouring (`YYYY-MM-DD`)                  |
| pouringStartDate    | time   | Yes      | Pouring start time (`HH:MM:SS`)                          |
| pouringEndDate      | time   | Yes      | Pouring end time (`HH:MM:SS`)                            |
| gradeConcrete       | string | Yes      | Grade of concrete (e.g. M25, M30)                        |
| concreteVolume      | string | Yes      | Volume of concrete poured                                |
| requisitionNo       | string | Yes      | Requisition number                                       |
| requisitionBy       | string | Yes      | Name of person who raised the requisition                |
| vehicleNumber       | string | Yes      | Vehicle number used for delivery                         |
| batchNo             | string | Yes      | Batch number of the concrete                             |
| attachBatchFile     | file   | No       | Batch ticket / supporting file upload                    |

> `referenceOrderNo` is **auto-generated** as `71XXXX` (e.g. `710001`) — no need to send it.

### Success Response `200`

```json
{
  "message": "Concrete Registry created",
  "data": [
    {
      "id": 1,
      "projectCode": "PC0001",
      "referenceOrderNo": "710001",
      "projectSubLocation": "Block A",
      "segment": "Foundation",
      "pouringDate": "2025-06-01",
      "pouringStartDate": "08:00:00",
      "pouringEndDate": "14:30:00",
      "gradeConcrete": "M25",
      "concreteVolume": "12.5",
      "requisitionNo": "REQ-001",
      "requisitionBy": "Rahul Sharma",
      "vehicleNumber": "WB-01-AB-1234",
      "batchNo": "BATCH-001",
      "attachBatchFile": "https://cdn.example.com/concrete_registry/710001/attach_file",
      "workflowStatus": "Draft",
      "status": "Active",
      "currentLevel": 0,
      "locked": false
    }
  ]
}
```

### Error Responses

| Status | Message                                    |
|--------|--------------------------------------------|
| 400    | `Invalid Project Code`                     |
| 403    | `You are not Concrete Registry creator`    |
| 500    | Internal server error                      |

---

## 2. List

Get a list of all Concrete Registry entries, optionally filtered by project.

**GET** `/project-mgmt/register/concrete-registry/list`

### Query Parameters

| Parameter   | Type   | Required | Description          |
|-------------|--------|----------|----------------------|
| projectCode | string | No       | Filter by project code |

### Success Response `200`

```json
{
  "message": "Concrete Registry list",
  "data": [
    {
      "id": 1,
      "projectCode": "PC0001",
      "referenceOrderNo": "710001",
      "projectSubLocation": "Block A",
      "segment": "Foundation",
      "pouringDate": "2025-06-01",
      "pouringStartDate": "08:00:00",
      "pouringEndDate": "14:30:00",
      "gradeConcrete": "M25",
      "concreteVolume": "12.5",
      "requisitionNo": "REQ-001",
      "requisitionBy": "Rahul Sharma",
      "vehicleNumber": "WB-01-AB-1234",
      "batchNo": "BATCH-001",
      "attachBatchFile": "https://cdn.example.com/concrete_registry/710001/attach_file",
      "workflowStatus": "Draft",
      "status": "Active",
      "currentLevel": 0,
      "locked": false
    }
  ]
}
```

### Error Responses

| Status | Message               |
|--------|-----------------------|
| 500    | Internal server error |

---

## 3. Details

Get full details of a single Concrete Registry entry.

**GET** `/project-mgmt/register/concrete-registry/list/<registry_id>`

### Path Parameters

| Parameter   | Type | Description            |
|-------------|------|------------------------|
| registry_id | int  | Concrete Registry ID   |

### Success Response `200`

```json
{
  "message": "Concrete Registry details",
  "data": [
    {
      "id": 1,
      "projectCode": "PC0001",
      "referenceOrderNo": "710001",
      "projectSubLocation": "Block A",
      "segment": "Foundation",
      "pouringDate": "2025-06-01",
      "pouringStartDate": "08:00:00",
      "pouringEndDate": "14:30:00",
      "gradeConcrete": "M25",
      "concreteVolume": "12.5",
      "requisitionNo": "REQ-001",
      "requisitionBy": "Rahul Sharma",
      "vehicleNumber": "WB-01-AB-1234",
      "batchNo": "BATCH-001",
      "attachBatchFile": "https://cdn.example.com/concrete_registry/710001/attach_file",
      "workflowStatus": "Draft",
      "status": "Active",
      "currentLevel": 0,
      "locked": false
    }
  ]
}
```

### Error Responses

| Status | Message                          |
|--------|----------------------------------|
| 404    | `Concrete Registry not found`    |
| 500    | Internal server error            |

---

## 4. Edit

Edit a Concrete Registry entry that is in `Draft` or `Reback` status.
Only provided fields are updated — all fields are optional.

**PUT** `/project-mgmt/register/concrete-registry/update/<registry_id>`

Content-Type: `multipart/form-data`

### Path Parameters

| Parameter   | Type | Description          |
|-------------|------|----------------------|
| registry_id | int  | Concrete Registry ID |

### Form Fields

All fields are optional — only sent fields will be updated.

| Field              | Type   | Description                            |
|--------------------|--------|----------------------------------------|
| projectSubLocation | string | Updated sub-location / unit            |
| segment            | string | Updated segment identifier             |
| pouringDate        | date   | Updated pouring date (`YYYY-MM-DD`)    |
| pouringStartDate   | time   | Updated start time (`HH:MM:SS`)        |
| pouringEndDate     | time   | Updated end time (`HH:MM:SS`)          |
| gradeConcrete      | string | Updated concrete grade                 |
| concreteVolume     | string | Updated concrete volume                |
| requisitionNo      | string | Updated requisition number             |
| requisitionBy      | string | Updated requisition by person          |
| vehicleNumber      | string | Updated vehicle number                 |
| batchNo            | string | Updated batch number                   |
| attachBatchFile    | file   | Replace existing batch file            |

### Success Response `200`

```json
{
  "message": "Concrete Registry updated",
  "data": [
    {
      "id": 1,
      "projectCode": "PC0001",
      "referenceOrderNo": "710001",
      "projectSubLocation": "Block B",
      "segment": "Column",
      "pouringDate": "2025-06-02",
      "pouringStartDate": "09:00:00",
      "pouringEndDate": "15:00:00",
      "gradeConcrete": "M30",
      "concreteVolume": "15.0",
      "requisitionNo": "REQ-002",
      "requisitionBy": "Suresh Das",
      "vehicleNumber": "WB-02-CD-5678",
      "batchNo": "BATCH-002",
      "attachBatchFile": "https://cdn.example.com/concrete_registry/710001/attach_file",
      "workflowStatus": "Draft",
      "status": "Active",
      "currentLevel": 0,
      "locked": false
    }
  ]
}
```

### Error Responses

| Status | Message                                       |
|--------|-----------------------------------------------|
| 404    | `Concrete Registry not found`                 |
| 400    | `Concrete Registry cannot be edited` (locked) |
| 400    | `Only Draft or Reback records can be edited`  |
| 403    | `You are not Concrete Registry creator`       |
| 500    | Internal server error                         |

---

## 5. Submit

Submit a `Draft` or `Reback` Concrete Registry for approval.
Moves to `Pending_L1` if workflow is configured, or auto-approves if no approver is set.

**POST** `/project-mgmt/register/concrete-registry/submit/<registry_id>`

### Path Parameters

| Parameter   | Type | Description          |
|-------------|------|----------------------|
| registry_id | int  | Concrete Registry ID |

No request body required.

### Success Response `200`

```json
{
  "message": "Concrete Registry submitted successfully",
  "data": {
    "id": 1,
    "referenceOrderNo": "710001",
    "workflowStatus": "Pending_L1"
  }
}
```

### Error Responses

| Status | Message                                    |
|--------|--------------------------------------------|
| 404    | `Concrete Registry not found`              |
| 400    | `Concrete Registry already submitted`      |
| 500    | Internal server error                      |

---

## 6. Approve

Approve a pending Concrete Registry. Advances to next level or sets to `Approved` at final level.

**POST** `/project-mgmt/register/concrete-registry/approve/<registry_id>`

### Path Parameters

| Parameter   | Type | Description          |
|-------------|------|----------------------|
| registry_id | int  | Concrete Registry ID |

### Request Body (JSON)

```json
{
  "comments": "Batch verified and approved."
}
```

| Field    | Type   | Required | Description        |
|----------|--------|----------|--------------------|
| comments | string | No       | Approver's remarks |

### Success Response `200`

```json
{
  "message": "Concrete Registry approved successfully",
  "data": {
    "id": 1,
    "workflowStatus": "Approved",
    "currentLevel": 1
  }
}
```

### Error Responses

| Status | Message                            |
|--------|------------------------------------|
| 404    | `Concrete Registry not found`      |
| 400    | `Concrete Registry not pending`    |
| 403    | `You are not current approver`     |
| 500    | Internal server error              |

---

## 7. Reback

Send a pending Concrete Registry back for correction. Unlocks the record and sets status to `Reback`.

**POST** `/project-mgmt/register/concrete-registry/reback/<registry_id>`

### Path Parameters

| Parameter   | Type | Description          |
|-------------|------|----------------------|
| registry_id | int  | Concrete Registry ID |

### Request Body (JSON)

```json
{
  "comments": "Batch number incorrect, please verify."
}
```

| Field    | Type   | Required | Description                          |
|----------|--------|----------|--------------------------------------|
| comments | string | Yes      | Reason for sending back (mandatory)  |

### Success Response `200`

```json
{
  "message": "Concrete Registry sent for correction",
  "data": {
    "id": 1,
    "workflowStatus": "Reback"
  }
}
```

### Error Responses

| Status | Message                            |
|--------|------------------------------------|
| 404    | `Concrete Registry not found`      |
| 400    | `Concrete Registry not pending`    |
| 400    | `Comments required`                |
| 403    | `You are not current approver`     |
| 500    | Internal server error              |

---

## 8. Reject

Permanently reject a pending Concrete Registry. Locks the record and sets status to `Rejected` / `Inactive`.

**POST** `/project-mgmt/register/concrete-registry/reject/<registry_id>`

### Path Parameters

| Parameter   | Type | Description          |
|-------------|------|----------------------|
| registry_id | int  | Concrete Registry ID |

### Request Body (JSON)

```json
{
  "comments": "Concrete grade does not match specification."
}
```

| Field    | Type   | Required | Description                          |
|----------|--------|----------|--------------------------------------|
| comments | string | Yes      | Reason for rejection (mandatory)     |

### Success Response `200`

```json
{
  "message": "Concrete Registry rejected",
  "data": {
    "id": 1,
    "workflowStatus": "Rejected"
  }
}
```

### Error Responses

| Status | Message                            |
|--------|------------------------------------|
| 404    | `Concrete Registry not found`      |
| 400    | `Concrete Registry not pending`    |
| 400    | `Comments required`                |
| 403    | `You are not current approver`     |
| 500    | Internal server error              |

---

## 9. History

Get the complete workflow action history for a Concrete Registry entry.

**GET** `/project-mgmt/register/concrete-registry/history/<registry_id>`

### Path Parameters

| Parameter   | Type | Description          |
|-------------|------|----------------------|
| registry_id | int  | Concrete Registry ID |

### Success Response `200`

```json
{
  "message": "Concrete Registry history fetched",
  "data": [
    {
      "id": 1,
      "action": "SUBMIT",
      "level": 0,
      "comments": null,
      "actionBy": "john.doe",
      "createdAt": "2025-06-01 10:30:00"
    },
    {
      "id": 2,
      "action": "REBACK",
      "level": 1,
      "comments": "Batch number incorrect, please verify.",
      "actionBy": "manager.user",
      "createdAt": "2025-06-01 14:15:00"
    },
    {
      "id": 3,
      "action": "SUBMIT",
      "level": 0,
      "comments": null,
      "actionBy": "john.doe",
      "createdAt": "2025-06-02 09:00:00"
    },
    {
      "id": 4,
      "action": "FINAL_APPROVE",
      "level": 1,
      "comments": "Batch verified and approved.",
      "actionBy": "manager.user",
      "createdAt": "2025-06-02 11:45:00"
    }
  ]
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

| Status | Message                        |
|--------|--------------------------------|
| 404    | `Concrete Registry not found`  |
| 500    | Internal server error          |

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
| Rejected     | No       | Yes    | Permanently rejected, status = Inactive   |

---

## DB Table

### `concrete_registry`

| Column               | Type         | Notes                                              |
|----------------------|--------------|----------------------------------------------------|
| id                   | int PK       | Auto increment                                     |
| projectcode          | varchar(50)  | FK → projects.project_code                         |
| reference_order_no   | varchar(50)  | Unique per project, auto-generated as `71XXXX`     |
| project_sub_location | varchar(50)  | Sub-location / unit                                |
| segment              | varchar(50)  | Segment identifier                                 |
| pouring_date         | date         | Date of concrete pouring                           |
| pouring_start_date   | time         | Pouring start time                                 |
| pouring_end_date     | time         | Pouring end time                                   |
| grade_concrete       | varchar(50)  | Concrete grade e.g. M25, M30                       |
| concrete_volume      | varchar(50)  | Volume poured                                      |
| requisition_no       | varchar(50)  | Requisition number                                 |
| requisition_by       | varchar(50)  | Person who raised requisition                      |
| vehicle_number       | varchar(50)  | Delivery vehicle number                            |
| batch_no             | varchar(50)  | Concrete batch number                              |
| attach_batch_file    | varchar(255) | CDN URL of uploaded batch file                     |
| workflow_status      | varchar(30)  | Default: Draft                                     |
| status               | varchar(30)  | Default: Active / Inactive on reject               |
| current_level        | int          | Default: 0                                         |
| locked               | boolean      | Default: false                                     |
| created_by           | int          | FK → users.id                                      |
| submitted_by         | int          | FK → users.id                                      |
| approved_by          | int          | FK → users.id                                      |
| rejected_by          | int          | FK → users.id                                      |
| updated_by           | int          | FK → users.id                                      |
| submitted_at         | datetime     |                                                    |
| final_approved_at    | datetime     |                                                    |
| rejected_at          | datetime     |                                                    |
| correction_sent_at   | datetime     | Set when reback action is taken                    |
| created_at           | datetime     | Auto                                               |
| updated_at           | datetime     | Auto, on update                                    |

---

## Migration

```bash
flask db migrate -m "add concrete_registry table"
flask db upgrade
```

---

## Notes

- **`referenceOrderNo`** is auto-generated as `71XXXX` per project (e.g. `710001`, `710002`). Serial resets per `projectCode`.
- **`pouringDate`** format in payload: `YYYY-MM-DD` — returned in response as `YYYY-MM-DD`.
- **`pouringStartDate` / `pouringEndDate`** format in payload: `HH:MM:SS` — returned as `HH:MM:SS`.
- **`attachBatchFile`** is optional on create and update. Existing file is retained if no new file is sent on edit.
- On **reject**, `status` is set to `Inactive` and the record is permanently locked.
