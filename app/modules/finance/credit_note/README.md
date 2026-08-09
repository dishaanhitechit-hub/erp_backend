# Finance > Accounts > Credit Note

**Module Code (workflow):** `credit_note`
**Base URL:** `/finance/credit-note`

---

## Overview

Credit Note is a fully manual entry module. All fields are typed by the user — no auto-fill from any other module. GST is entered as grouped lines (IGST or CGST + SGST) same as other finance modules. Full workflow (Draft → Pending → Approved) with history and approval status.

---

## DB Tables

| Table | Description |
|---|---|
| `credit_note_master` | Header — all fields + workflow + audit |
| `credit_note_items` | Line items — CC Code, Basic, GST%, Total |
| `credit_note_gst` | GST lines — IGST / CGST / SGST |

### FK Chain

```
credit_note_master.id
  ├── credit_note_items.credit_note_id
  └── credit_note_gst.credit_note_id

credit_note_master.project_code → projects.project_code
```

---

## Workflow States

```
Draft → Pending_L1 → Pending_L2 → ... → Approved
               ↘ Reback → (edit) → re-submit
               ↘ Rejected
```

- Locked on submit. Unlocked on Reback.
- Admin must configure `ApprovalPath` for module code `credit_note` per project.
- If no approvers configured, submit auto-approves immediately.

---

## All Endpoints

| Method | Path | Description |
|---|---|---|
| POST | `/create` | Create credit note |
| GET | `/list` | List credit notes |
| GET | `/<cn_id>` | Full details with items + GST |
| PUT | `/edit/<cn_id>` | Edit Draft or Reback |
| POST | `/submit/<cn_id>` | Submit for approval |
| POST | `/approve/<cn_id>` | Approve `{ "comments": "..." }` |
| POST | `/reback/<cn_id>` | Reback `{ "comments": "..." }` |
| POST | `/reject/<cn_id>` | Reject `{ "comments": "..." }` |
| GET | `/history/<cn_id>` | Approval history + steps |
| GET | `/my-approval-status/<cn_id>` | Caller's approval role |
| GET | `/uuid/<cn_uuid>` | Public UUID lookup (no JWT) |

---

## POST `/finance/credit-note/create`

**Request body:**
```json
{
  "projectCode":   "DHLE",
  "entryDate":     "2026-08-09",
  "billNumber":    "BILL-2026-001",
  "billDate":      "2026-07-15",
  "orderNumber":   "ORD-2026-001",
  "orderDate":     "2026-06-01",
  "vendorName":    "Techno Electrical & Engineers Company Ltd.",
  "vendorGstn":    "27AABCT1234A1Z5",
  "debitNoteNo":   "DN-001",
  "debitNoteDate": "2026-08-01",
  "items": [
    {
      "slNo":        1,
      "ccCode":      "WORK",
      "ccName":      "Work Charges",
      "description": "Credit against excess deduction",
      "basicAmount": 2000.00,
      "gstPercent":  18
    }
  ],
  "gstLines": [
    { "gstType": "IGST", "ccCode": "IGST", "ccName": "Output-IGST", "percent": 18, "gstAmount": 0,      "isSelected": false },
    { "gstType": "CGST", "ccCode": "CGST", "ccName": "Output-CGST", "percent": 9,  "gstAmount": 180.00, "isSelected": true  },
    { "gstType": "SGST", "ccCode": "SGST", "ccName": "Output-SGST", "percent": 9,  "gstAmount": 180.00, "isSelected": true  }
  ],
  "remarks": "Credit against debit note DN-001"
}
```

> **Totals (computed server-side):**
> ```
> basicAmount      = Σ item.basicAmount
> gstAmount        = Σ selected gstLine.gstAmount
> totalAmount      = basicAmount + gstAmount
> item.totalAmount = item.basicAmount + (item.basicAmount × item.gstPercent / 100)
> ```

**Response `201`:**
```json
{
  "id":             1,
  "creditNoteNo":   "001",
  "creditNoteUuid": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
}
```

---

## GET `/finance/credit-note/list`

**Query params:**

| Param | Required | Description |
|---|---|---|
| `projectCode` | Yes | |
| `workflowStatus` | No | Draft / Pending_L1 / Approved / Reback / Rejected |
| `search` | No | Searches `credit_note_no`, `bill_number`, `vendor_name` |

**Response:**
```json
{
  "data": [
    {
      "id":             1,
      "creditNoteNo":   "001",
      "entryDate":      "2026-08-09",
      "billNumber":     "BILL-2026-001",
      "vendorName":     "Techno Electrical & Engineers Company Ltd.",
      "basicAmount":    2000.00,
      "gstAmount":      360.00,
      "totalAmount":    2360.00,
      "workflowStatus": "Draft",
      "createdBy":      "john_doe",
      "createdAt":      "2026-08-09"
    }
  ]
}
```

---

## GET `/finance/credit-note/<cn_id>`

Full details including all items and GST lines.

**Response:**
```json
{
  "id":              1,
  "creditNoteNo":    "001",
  "creditNoteUuid":  "...",
  "entryDate":       "2026-08-09",
  "projectCode":     "DHLE",
  "billNumber":      "BILL-2026-001",
  "billDate":        "2026-07-15",
  "orderNumber":     "ORD-2026-001",
  "orderDate":       "2026-06-01",
  "vendorName":      "Techno Electrical & Engineers Company Ltd.",
  "vendorGstn":      "27AABCT1234A1Z5",
  "debitNoteNo":     "DN-001",
  "debitNoteDate":   "2026-08-01",
  "basicAmount":     2000.00,
  "gstAmount":       360.00,
  "totalAmount":     2360.00,
  "remarks":         "Credit against debit note DN-001",
  "workflowStatus":  "Draft",
  "currentLevel":    0,
  "locked":          false,
  "createdBy":       "john_doe",
  "createdAt":       "2026-08-09",
  "submittedBy":     null,
  "submittedAt":     null,
  "approvedBy":      null,
  "finalApprovedAt": null,
  "rejectedBy":      null,
  "rejectedAt":      null,
  "items": [
    {
      "id":          1,
      "slNo":        1,
      "ccCode":      "WORK",
      "ccName":      "Work Charges",
      "description": "Credit against excess deduction",
      "basicAmount": 2000.00,
      "gstPercent":  18.0,
      "totalAmount": 2360.00
    }
  ],
  "gstLines": [
    { "id": 1, "gstType": "IGST", "ccCode": "IGST", "ccName": "Output-IGST", "percent": 18, "gstAmount": 0,      "isSelected": false },
    { "id": 2, "gstType": "CGST", "ccCode": "CGST", "ccName": "Output-CGST", "percent": 9,  "gstAmount": 180.00, "isSelected": true  },
    { "id": 3, "gstType": "SGST", "ccCode": "SGST", "ccName": "Output-SGST", "percent": 9,  "gstAmount": 180.00, "isSelected": true  }
  ]
}
```

---

## PUT `/finance/credit-note/edit/<cn_id>`

Only allowed when `workflowStatus` is `Draft` or `Reback`. Items and GST lines are wiped and rebuilt on every edit.

**Editable fields:** all header fields + `items[]` + `gstLines[]`

---

## POST `/finance/credit-note/submit/<cn_id>`

Locks the record. Moves to `Pending_L1` if approvers are configured, else directly `Approved`.

---

## POST `/finance/credit-note/approve/<cn_id>`

**Body:** `{ "comments": "Approved after review" }` *(optional)*

---

## POST `/finance/credit-note/reback/<cn_id>`

**Body:** `{ "comments": "..." }` *(required)*

Unlocks the record. Creator can edit and re-submit.

---

## POST `/finance/credit-note/reject/<cn_id>`

**Body:** `{ "comments": "..." }` *(required)*

---

## GET `/finance/credit-note/history/<cn_id>`

**Response:**
```json
{
  "workflowStatus": "Pending_L1",
  "currentLevel":   1,
  "approvalSteps":  [...],
  "history": [
    {
      "id":        1,
      "action":    "SUBMIT",
      "level":     1,
      "comments":  null,
      "actionBy":  "john_doe",
      "createdAt": "2026-08-09 10:30:00"
    }
  ]
}
```

---

## GET `/finance/credit-note/my-approval-status/<cn_id>`

Returns the caller's role and action options for this record.

---

## GET `/finance/credit-note/uuid/<cn_uuid>`

Public lookup by UUID — no JWT required. Returns full credit note payload.
