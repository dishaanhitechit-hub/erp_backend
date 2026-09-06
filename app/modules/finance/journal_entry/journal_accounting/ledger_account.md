# Journal Accounting API

## Base URL

```
/finance/journal-entry/journal-accounting
```

All endpoints require `@login_required` except UUID.

---

## Endpoints

| # | Method | Endpoint | Description |
|---|---|---|---|
| 0 | GET | `/approved-vouchers` | Approved journal vouchers available for accounting |
| 1 | POST | `/create` | Create journal accounting |
| 2 | GET | `/list` | Paginated list |
| 3 | GET | `/<id>` | Full detail |
| 3b | GET | `/uuid/<uuid>` | Public — no auth required |
| 4 | PUT | `/<id>/edit` | Edit (Draft / Reback only) |
| 5 | POST | `/<id>/submit` | Submit for approval |
| 6 | POST | `/<id>/approve` | Approve |
| 7 | POST | `/<id>/reback` | Send back for correction |
| 8 | POST | `/<id>/reject` | Reject |
| 9 | GET | `/<id>/history` | Approval history |
| 10 | GET | `/<id>/my-status` | My approval status |

> **Alternate URL pattern** (frontend-style) also supported for workflow actions:
> `/submit/<id>`, `/approve/<id>`, `/reback/<id>`, `/reject/<id>`

---

## 0. Approved Vouchers

**GET** `/finance/journal-entry/journal-accounting/approved-vouchers`

Returns approved `PettyCashJournalVoucher` records that have **not yet** been accounted (one-to-one constraint).

| Param | Required | Description |
|---|---|---|
| `projectCode` | ✅ | Project |

**Response:**
```json
{
  "message": "Approved journal vouchers fetched",
  "data": {
    "vouchers": [
      {
        "journalVoucherId": 2,
        "voucherNo": "JV00002",
        "voucherDate": "2026-09-05",
        "fundSource": "Cash",
        "totalAmount": 18000.0,
        "lines": [
          {
            "journalLineId": 3,
            "slNo": 1,
            "ccCode": "CC001",
            "ccName": "Site Labour",
            "shortDescription": "Daily wages",
            "amount": 18000.0
          }
        ]
      }
    ]
  }
}
```

---

## 1. Create

**POST** `/finance/journal-entry/journal-accounting/create`
**Content-Type:** `multipart/form-data`

| Field | Required | Description |
|---|---|---|
| `projectCode` | ✅ | Project |
| `journalVoucherId` | ✅ | Source journal voucher (must be Approved) |
| `voucherDate` | ✅ | Date (YYYY-MM-DD) |
| `lines` | ✅ | JSON string — array of line objects |

**`lines` item:**
```json
{
  "journalLineId": 3,
  "slNo": 1,
  "ccCode": "CC001",
  "ccName": "Site Labour",
  "shortDescription": "Daily wages",
  "originalAmount": 18000.0,
  "amount": 17500.0
}
```

> User can modify `amount`. `originalAmount` is stored from the source journal line.
> One journal accounting per journal voucher — attempting to account an already-accounted voucher returns 400.

**Response:**
```json
{
  "message": "Journal accounting created",
  "data": { "id": 1, "voucherNo": "JA00001", "voucherUuid": "..." }
}
```

---

## 2. List

**GET** `/finance/journal-entry/journal-accounting/list`

| Param | Default | Description |
|---|---|---|
| `projectCode` | — | Filter by project |
| `page` | `1` | — |
| `pageSize` | `10` | — |
| `workflowStatus` | — | Optional filter |
| `fundSource` | — | `Cash` or `Bank` |

**Response:**
```json
{
  "data": {
    "list": [
      {
        "id": 1,
        "voucherNo": "JA00001",
        "voucherDate": "2026-09-06",
        "journalVoucherNo": "JV00002",
        "fundSource": "Cash",
        "totalAmount": 17500.0,
        "workflowStatus": "Draft",
        "createdBy": "ankandas",
        "createdAt": "2026-09-06 10:00"
      }
    ],
    "pagination": { "page": 1, "pageSize": 10, "total": 5, "totalPages": 1 }
  }
}
```

---

## 3. Detail

**GET** `/finance/journal-entry/journal-accounting/<id>`

```json
{
  "data": {
    "id": 1,
    "voucherNo": "JA00001",
    "voucherUuid": "...",
    "voucherDate": "2026-09-06",
    "projectCode": "PC0001",
    "totalAmount": 17500.0,
    "workflowStatus": "Approved",
    "currentLevel": 1,
    "locked": true,
    "journalVoucherId": 2,
    "journalVoucherNo": "JV00002",
    "fundSource": "Cash",
    "createdBy": "ankandas",
    "createdAt": "2026-09-06 10:00",
    "submittedBy": "ankandas",
    "submittedAt": "2026-09-06 10:05",
    "approvedBy": "manager1",
    "finalApprovedAt": "2026-09-06 11:00",
    "rejectedBy": null,
    "rejectedAt": null,
    "lines": [
      {
        "id": 1,
        "slNo": 1,
        "journalLineId": 3,
        "ccCode": "CC001",
        "ccName": "Site Labour",
        "shortDescription": "Daily wages",
        "originalAmount": 18000.0,
        "amount": 17500.0
      }
    ]
  }
}
```

---

## 3b. UUID (Public)

**GET** `/finance/journal-entry/journal-accounting/uuid/<voucher_uuid>`

No `@login_required`. Returns same payload as detail.

---

## 4. Edit

**PUT** `/finance/journal-entry/journal-accounting/<id>/edit`

Same form-data as Create (except `journalVoucherId` is fixed — cannot change the source voucher).
Only when `workflowStatus = Draft` or `Reback`. Replaces all existing lines.

---

## 5–8. Workflow

| Endpoint | Method | Body | Notes |
|---|---|---|---|
| `/<id>/submit` | POST | none | Draft/Reback → Pending_L1 |
| `/<id>/approve` | POST | `{"comments": "..."}` | JSON |
| `/<id>/reback` | POST | `{"comments": "..."}` | JSON, comments required |
| `/<id>/reject` | POST | `{"comments": "..."}` | JSON, comments required |

---

## 9. History

**GET** `/finance/journal-entry/journal-accounting/<id>/history`

```json
{
  "data": {
    "workflowStatus": "Approved",
    "currentLevel": 1,
    "approvalSteps": [ "..." ],
    "history": [
      { "id": 1, "action": "SUBMIT",        "level": 0, "comments": null,       "actionBy": "ankandas", "createdAt": "2026-09-06 10:05:00" },
      { "id": 2, "action": "FINAL_APPROVE", "level": 1, "comments": "Verified", "actionBy": "manager1", "createdAt": "2026-09-06 11:00:00" }
    ]
  }
}
```

---

## Workflow States

| Status | Editable |
|---|---|
| `Draft` | ✅ |
| `Pending_L1 / L2 …` | ❌ |
| `Reback` | ✅ |
| `Approved` | ❌ |
| `Rejected` | ❌ |

---

## Migration

```bash
flask db migrate -m "petty cash journal accounting"
flask db upgrade
```

---

## Related Modules

| Module | Base URL |
|---|---|
| Petty Cash Budget | `/finance/petty-cash/budget` |
| Petty Cash Docket Voucher | `/finance/petty-cash/docket-voucher` |
| Petty Cash Ledger | `/finance/petty-cash/ledger` |
| Journal Voucher | `/finance/journal-entry/journal-voucher` |
| Journal Accounting (this) | `/finance/journal-entry/journal-accounting` |
