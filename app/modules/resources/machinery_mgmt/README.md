# Machinery Management — Log Book & Log Entry

Base URL: `/resource/machinery`
Auth: All endpoints require `Authorization: Bearer <JWT>` header.
Module Code: `log_sheet`
Content-Type: `application/json`

---

## Overview

Two-level structure:

```
Machinery Log Book  (master — linked to a PW Order)
      ↓
Log Book Entry  (daily running record against a Log Book)
```

Both go through the same workflow: `Draft → Pending_L{n} → Approved / Reback / Rejected`

**View permission:** GET endpoints require `log_sheet.view` or `log_sheet.edit` in JWT claims.
Set via the project permission system when user enters the project.

---

## Table of Contents

**Log Book**
1. [Get PW Orders](#1-get-pw-orders)
2. [Create Log Book](#2-create-log-book)
3. [List Log Books](#3-list-log-books)
4. [Log Book Details](#4-log-book-details)
5. [Edit Log Book](#5-edit-log-book)
6. [Submit Log Book](#6-submit-log-book)
7. [Approve Log Book](#7-approve-log-book)
8. [Reback Log Book](#8-reback-log-book)
9. [Reject Log Book](#9-reject-log-book)
10. [Log Book History](#10-log-book-history)

**Log Entry**
11. [Create Log Entry](#11-create-log-entry)
12. [List Log Entries](#12-list-log-entries)
13. [Log Entry Details](#13-log-entry-details)
14. [Edit Log Entry](#14-edit-log-entry)
15. [Submit Log Entry](#15-submit-log-entry)
16. [Approve Log Entry](#16-approve-log-entry)
17. [Reback Log Entry](#17-reback-log-entry)
18. [Reject Log Entry](#18-reject-log-entry)
19. [Log Entry History](#19-log-entry-history)

20. [Workflow States](#workflow-states)
21. [DB Tables](#db-tables)

---

## LOG BOOK

---

## 1. Get PW Orders

Fetch approved PW orders for a project (used to populate the Party Order No dropdown).

**GET** `/resource/machinery/log-book/pw-orders`

### Query Parameters

| Parameter   | Type   | Required | Description   |
|-------------|--------|----------|---------------|
| projectCode | string | Yes      | Project code  |

### Success Response `200`

```json
{
  "message": "PW Orders fetched",
  "data": [
    {
      "id": 5,
      "orderNo": "550001",
      "orderDate": "2024-04-10",
      "partyName": "XYZ Services Pvt Ltd"
    }
  ],
  "status": 200
}
```

### Error Responses

| Status | Message                |
|--------|------------------------|
| 400    | `projectCode required` |
| 403    | `Access denied`        |
| 500    | Internal server error  |

---

## 2. Create Log Book

**POST** `/resource/machinery/log-book/create`

Content-Type: `application/json`

### Request Body

```json
{
  "createDate": "2024-06-20",
  "projectCode": "PROJ-001",
  "partyOrderId": 5,
  "machineryName": "JCB 3CX Backhoe Loader",
  "machineryRegNo": "WB-12-AB-3456",
  "fuelConsumptionUnit": "Litre",
  "fuelConsumptionPerUnit": 8.5
}
```

### Request Fields

| Field                  | Type   | Required | Description                        |
|------------------------|--------|----------|------------------------------------|
| createDate             | date   | Yes      | Log book create date (`YYYY-MM-DD`) |
| projectCode            | string | Yes      | Project code                       |
| partyOrderId           | int    | No       | FK → pw_order_master.id            |
| machineryName          | string | No       | Machinery name                     |
| machineryRegNo         | string | No       | Machinery registration number      |
| fuelConsumptionUnit    | string | No       | Unit of fuel (e.g. Litre)          |
| fuelConsumptionPerUnit | number | No       | Fuel consumption per unit          |

### Success Response `201`

```json
{
  "message": "Log Book created",
  "data": {
    "logBookId": 1,
    "logBookNo": "870001"
  },
  "status": 201
}
```

### Error Responses

| Status | Message                         |
|--------|---------------------------------|
| 403    | `You are not Log Book creator`  |
| 500    | Internal server error           |

---

## 3. List Log Books

**GET** `/resource/machinery/log-book/list`

### Query Parameters

| Parameter      | Type   | Required | Description                    |
|----------------|--------|----------|--------------------------------|
| projectCode    | string | Yes      | Project code                   |
| workflowStatus | string | No       | Filter by workflow status      |
| search         | string | No       | Partial match on log book no   |

### Success Response `200`

```json
{
  "message": "Log Book list fetched",
  "data": [
    {
      "id": 1,
      "logBookNo": "870001",
      "createDate": "2024-06-20",
      "projectCode": "PROJ-001",
      "partyOrderId": 5,
      "partyOrderNo": "550001",
      "partyName": "XYZ Services Pvt Ltd",
      "machineryName": "JCB 3CX Backhoe Loader",
      "machineryRegNo": "WB-12-AB-3456",
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
| 403    | `Access denied`        |
| 500    | Internal server error  |

---

## 4. Log Book Details

**GET** `/resource/machinery/log-book/details/<log_book_id>`

### Success Response `200`

```json
{
  "message": "Log Book details fetched",
  "data": {
    "id": 1,
    "logBookNo": "870001",
    "createDate": "2024-06-20",
    "projectCode": "PROJ-001",
    "partyOrderId": 5,
    "partyOrderNo": "550001",
    "partyName": "XYZ Services Pvt Ltd",
    "partyAddress": "45, Park Street, Kolkata - 700016",
    "machineryName": "JCB 3CX Backhoe Loader",
    "machineryRegNo": "WB-12-AB-3456",
    "fuelConsumptionUnit": "Litre",
    "fuelConsumptionPerUnit": 8.5,
    "workflowStatus": "Draft",
    "currentLevel": 0,
    "locked": false
  },
  "status": 200
}
```

### Error Responses

| Status | Message              |
|--------|----------------------|
| 403    | `Access denied`      |
| 404    | `Log Book not found` |
| 500    | Internal server error |

---

## 5. Edit Log Book

Only allowed when `workflowStatus` is `Draft` or `Reback` and `locked = false`.

**PUT** `/resource/machinery/log-book/edit/<log_book_id>`

```json
{
  "machineryName": "Updated Machinery Name",
  "machineryRegNo": "WB-12-AB-9999",
  "fuelConsumptionUnit": "Litre",
  "fuelConsumptionPerUnit": 9.0
}
```

> All fields optional.

### Success Response `200`

```json
{
  "message": "Log Book updated successfully",
  "data": { "logBookId": 1, "logBookNo": "870001" },
  "status": 200
}
```

### Error Responses

| Status | Message                                        |
|--------|------------------------------------------------|
| 404    | `Log Book not found`                           |
| 400    | `Log Book cannot be edited` (locked)           |
| 400    | `Only Draft or Reback Log Book can be edited`  |
| 403    | `You are not Log Book creator`                 |
| 500    | Internal server error                          |

---

## 6. Submit Log Book

**POST** `/resource/machinery/log-book/submit/<log_book_id>`

No request body.

### Success Response `200`

```json
{
  "message": "Log Book submitted successfully",
  "data": { "logBookId": 1, "logBookNo": "870001", "workflowStatus": "Pending_L1" },
  "status": 200
}
```

### Error Responses

| Status | Message                       |
|--------|-------------------------------|
| 404    | `Log Book not found`          |
| 400    | `Log Book already submitted`  |
| 500    | Internal server error         |

---

## 7. Approve Log Book

**POST** `/resource/machinery/log-book/approve/<log_book_id>`

```json
{ "comments": "Log book verified." }
```

### Success Response `200`

```json
{
  "message": "Log Book approved successfully",
  "data": { "logBookId": 1, "workflowStatus": "Approved", "currentLevel": 1 },
  "status": 200
}
```

---

## 8. Reback Log Book

**POST** `/resource/machinery/log-book/reback/<log_book_id>`

```json
{ "comments": "Registration number incorrect." }
```

| Field    | Required |
|----------|----------|
| comments | Yes      |

### Success Response `200`

```json
{
  "message": "Log Book sent for correction",
  "data": { "logBookId": 1, "workflowStatus": "Reback" },
  "status": 200
}
```

---

## 9. Reject Log Book

**POST** `/resource/machinery/log-book/reject/<log_book_id>`

```json
{ "comments": "Invalid machinery details." }
```

| Field    | Required |
|----------|----------|
| comments | Yes      |

### Success Response `200`

```json
{
  "message": "Log Book rejected",
  "data": { "logBookId": 1, "workflowStatus": "Rejected" },
  "status": 200
}
```

---

## 10. Log Book History

**GET** `/resource/machinery/log-book/history/<log_book_id>`

### Success Response `200`

```json
{
  "message": "Log Book history fetched",
  "data": [
    { "id": 1, "action": "SUBMIT",        "level": 0, "comments": null,                        "actionBy": "john.doe", "createdAt": "2024-06-20 10:00:00" },
    { "id": 2, "action": "FINAL_APPROVE", "level": 1, "comments": "Log book verified.",         "actionBy": "manager",  "createdAt": "2024-06-20 14:00:00" }
  ],
  "status": 200
}
```

---

## LOG BOOK ENTRY

---

## 11. Create Log Entry

**POST** `/resource/machinery/log-entry/create`

Content-Type: `application/json`

### Request Body

```json
{
  "projectCode": "PROJ-001",
  "logBookId": 1,
  "runningDate": "2024-06-21",
  "runningStartTime": "08:00",
  "runningFinishTime": "17:00",
  "projectSubLocation": "Block B - Foundation",
  "segmentLayer": "Layer 1",
  "workMonitoringBy": "Rahul Sharma",
  "operatorName": "Suresh Kumar"
}
```

### Request Fields

| Field               | Type   | Required | Description                        |
|---------------------|--------|----------|------------------------------------|
| projectCode         | string | Yes      | Project code                       |
| logBookId           | int    | Yes      | FK → machinery_log_book.id         |
| runningDate         | date   | No       | Running date (`YYYY-MM-DD`)        |
| runningStartTime    | time   | No       | Start time (`HH:MM`)               |
| runningFinishTime   | time   | No       | Finish time (`HH:MM`)              |
| projectSubLocation  | string | No       | Project sub-location               |
| segmentLayer        | string | No       | Segment / Layer                    |
| workMonitoringBy    | string | No       | Work monitoring by (name)          |
| operatorName        | string | No       | Operator name                      |

### Success Response `201`

```json
{
  "message": "Log Entry created",
  "data": { "entryId": 1, "logUid": "860001" },
  "status": 201
}
```

### Error Responses

| Status | Message                          |
|--------|----------------------------------|
| 403    | `You are not Log Entry creator`  |
| 400    | `logBookId required`             |
| 404    | `Log Book not found`             |
| 500    | Internal server error            |

---

## 12. List Log Entries

**GET** `/resource/machinery/log-entry/list`

### Query Parameters

| Parameter      | Type   | Required | Description                    |
|----------------|--------|----------|--------------------------------|
| projectCode    | string | Yes      | Project code                   |
| logBookId      | int    | No       | Filter by log book             |
| workflowStatus | string | No       | Filter by workflow status      |
| search         | string | No       | Partial match on log UID       |

### Success Response `200`

```json
{
  "message": "Log Entry list fetched",
  "data": [
    {
      "id": 1,
      "logUid": "860001",
      "logBookId": 1,
      "logBookNo": "870001",
      "machineryName": "JCB 3CX Backhoe Loader",
      "machineryRegNo": "WB-12-AB-3456",
      "partyName": "XYZ Services Pvt Ltd",
      "runningDate": "2024-06-21",
      "runningStartTime": "08:00",
      "runningFinishTime": "17:00",
      "workflowStatus": "Draft"
    }
  ],
  "status": 200
}
```

---

## 13. Log Entry Details

**GET** `/resource/machinery/log-entry/details/<entry_id>`

### Success Response `200`

```json
{
  "message": "Log Entry details fetched",
  "data": {
    "id": 1,
    "logUid": "860001",
    "logBookId": 1,
    "logBookNo": "870001",
    "partyOrderId": 5,
    "partyOrderNo": "550001",
    "partyName": "XYZ Services Pvt Ltd",
    "machineryName": "JCB 3CX Backhoe Loader",
    "machineryRegNo": "WB-12-AB-3456",
    "projectCode": "PROJ-001",
    "runningDate": "2024-06-21",
    "runningStartTime": "08:00",
    "runningFinishTime": "17:00",
    "projectSubLocation": "Block B - Foundation",
    "segmentLayer": "Layer 1",
    "workMonitoringBy": "Rahul Sharma",
    "operatorName": "Suresh Kumar",
    "workflowStatus": "Draft",
    "currentLevel": 0,
    "locked": false
  },
  "status": 200
}
```

### Error Responses

| Status | Message                 |
|--------|-------------------------|
| 403    | `Access denied`         |
| 404    | `Log Entry not found`   |
| 500    | Internal server error   |

---

## 14. Edit Log Entry

Only allowed when `workflowStatus` is `Draft` or `Reback` and `locked = false`.

**PUT** `/resource/machinery/log-entry/edit/<entry_id>`

```json
{
  "runningDate": "2024-06-21",
  "runningStartTime": "09:00",
  "runningFinishTime": "18:00",
  "projectSubLocation": "Block C",
  "segmentLayer": "Layer 2",
  "workMonitoringBy": "Amit Singh",
  "operatorName": "Rajesh Kumar"
}
```

> All fields optional.

### Success Response `200`

```json
{
  "message": "Log Entry updated successfully",
  "data": { "entryId": 1, "logUid": "860001" },
  "status": 200
}
```

### Error Responses

| Status | Message                                           |
|--------|---------------------------------------------------|
| 404    | `Log Entry not found`                             |
| 400    | `Log Entry cannot be edited` (locked)             |
| 400    | `Only Draft or Reback entries can be edited`      |
| 403    | `You are not Log Entry creator`                   |
| 500    | Internal server error                             |

---

## 15. Submit Log Entry

**POST** `/resource/machinery/log-entry/submit/<entry_id>`

No request body.

### Success Response `200`

```json
{
  "message": "Log Entry submitted successfully",
  "data": { "entryId": 1, "logUid": "860001", "workflowStatus": "Pending_L1" },
  "status": 200
}
```

---

## 16. Approve Log Entry

**POST** `/resource/machinery/log-entry/approve/<entry_id>`

```json
{ "comments": "Entry verified." }
```

### Success Response `200`

```json
{
  "message": "Log Entry approved successfully",
  "data": { "entryId": 1, "workflowStatus": "Approved", "currentLevel": 1 },
  "status": 200
}
```

---

## 17. Reback Log Entry

**POST** `/resource/machinery/log-entry/reback/<entry_id>`

```json
{ "comments": "Running time incorrect." }
```

| Field    | Required |
|----------|----------|
| comments | Yes      |

### Success Response `200`

```json
{
  "message": "Log Entry sent for correction",
  "data": { "entryId": 1, "workflowStatus": "Reback" },
  "status": 200
}
```

---

## 18. Reject Log Entry

**POST** `/resource/machinery/log-entry/reject/<entry_id>`

```json
{ "comments": "Entry does not match site records." }
```

| Field    | Required |
|----------|----------|
| comments | Yes      |

### Success Response `200`

```json
{
  "message": "Log Entry rejected",
  "data": { "entryId": 1, "workflowStatus": "Rejected" },
  "status": 200
}
```

---

## 19. Log Entry History

**GET** `/resource/machinery/log-entry/history/<entry_id>`

### Success Response `200`

```json
{
  "message": "Log Entry history fetched",
  "data": [
    { "id": 1, "action": "SUBMIT",        "level": 0, "comments": null,                    "actionBy": "john.doe", "createdAt": "2024-06-21 09:00:00" },
    { "id": 2, "action": "REBACK",        "level": 1, "comments": "Running time incorrect.","actionBy": "manager",  "createdAt": "2024-06-21 12:00:00" },
    { "id": 3, "action": "SUBMIT",        "level": 0, "comments": null,                    "actionBy": "john.doe", "createdAt": "2024-06-22 08:30:00" },
    { "id": 4, "action": "FINAL_APPROVE", "level": 1, "comments": "Entry verified.",        "actionBy": "manager",  "createdAt": "2024-06-22 10:00:00" }
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
                              → [Reject]  → Rejected
```

| Status       | Editable | Locked |
|--------------|----------|--------|
| Draft        | Yes      | No     |
| Pending_L{n} | No       | Yes    |
| Reback       | Yes      | No     |
| Approved     | No       | Yes    |
| Rejected     | No       | Yes    |

---

## DB Tables

### `machinery_log_book`

| Column                  | Type          | Notes                             |
|-------------------------|---------------|-----------------------------------|
| id                      | int PK        |                                   |
| log_book_no             | varchar(50)   | Unique serial starting from 870001|
| create_date             | date          | Required                          |
| project_code            | varchar(50)   | FK → projects.project_code        |
| party_order_id          | int           | FK → pw_order_master.id           |
| machinery_name          | varchar(200)  |                                   |
| machinery_reg_no        | varchar(100)  |                                   |
| fuel_consumption_unit   | varchar(50)   |                                   |
| fuel_consumption_per_unit | numeric(10,2)|                                   |
| workflow_status         | varchar(30)   | Default: Draft                    |
| current_level           | int           | Default: 0                        |
| locked                  | boolean       | Default: false                    |
| status                  | varchar(30)   | Default: Active                   |
| created_by              | int           | FK → users.id                     |
| submitted_by            | int           | FK → users.id                     |
| approved_by             | int           | FK → users.id                     |
| rejected_by             | int           | FK → users.id                     |
| updated_by              | int           | FK → users.id                     |
| submitted_at            | datetime      |                                   |
| final_approved_at       | datetime      |                                   |
| rejected_at             | datetime      |                                   |
| correction_sent_at      | datetime      |                                   |
| created_at              | datetime      | Auto                              |
| updated_at              | datetime      | Auto                              |

### `log_book_entries`

| Column              | Type         | Notes                              |
|---------------------|--------------|------------------------------------|
| id                  | int PK       |                                    |
| log_uid             | varchar(50)  | Unique serial starting from 860001 |
| log_book_id         | int          | FK → machinery_log_book.id         |
| project_code        | varchar(50)  | FK → projects.project_code         |
| running_date        | date         |                                    |
| running_start_time  | time         |                                    |
| running_finish_time | time         |                                    |
| project_sub_location| varchar(200) |                                    |
| segment_layer       | varchar(200) |                                    |
| work_monitoring_by  | varchar(200) |                                    |
| operator_name       | varchar(200) |                                    |
| workflow_status     | varchar(30)  | Default: Draft                     |
| current_level       | int          | Default: 0                         |
| locked              | boolean      | Default: false                     |
| status              | varchar(30)  | Default: Active                    |
| created_by          | int          | FK → users.id                      |
| submitted_by        | int          | FK → users.id                      |
| approved_by         | int          | FK → users.id                      |
| rejected_by         | int          | FK → users.id                      |
| updated_by          | int          | FK → users.id                      |
| submitted_at        | datetime     |                                    |
| final_approved_at   | datetime     |                                    |
| rejected_at         | datetime     |                                    |
| correction_sent_at  | datetime     |                                    |
| created_at          | datetime     | Auto                               |
| updated_at          | datetime     | Auto                               |

---

## Migration

```bash
flask db migrate -m "add machinery log book tables"
flask db upgrade
```

### module_master entry (required before workflow actions work)

```sql
INSERT INTO module_master (module_code, module_name)
VALUES ('log_sheet', 'Machinery Log Sheet');
```

### Permission setup

Users need `log_sheet.view` or `log_sheet.edit` assigned in the project permission system to access GET endpoints.
