# Custom Billing

**Directory:** `app/modules/project_mgmt/custom_billing/`

Sub-modules for client-side billing under Project Management.

---

## Modules

| Module | Directory | Prefix | Bill No | module_code |
|--------|-----------|--------|---------|-------------|
| Sale Order & BOQ | `sale_order/` | `/project-mgmt/sale-order` | `SO001` | `sale_order` |
| Certified Bill | `certified_bill/` | `/project-mgmt/certified-bill` | `CB001` | `certified_bill` |

---

## Common Structure

Both modules share the same pattern:

- User enters an **Order No** → system validates it belongs to the project
- `orderType` flag (`normal` / `pw`) tells which table to look up (`order_master` or `pw_order_master`)
- BOQ items are entered manually with item code, description, unit, qty, rate, and GST%
- `pre_certified_amount` is auto-calculated from all previously **Approved** bills for the same order
- `total_claim = pre_certified_amount + this_bill_claim`
- Full approval workflow: Draft → Pending → Approved / Reback / Rejected
- Public UUID endpoint (no JWT) for each record

---

## Models

| Model file | Tables |
|-----------|--------|
| `app/models/saleOrderMaster.py` | `sale_order_master`, `sale_order_items` |
| `app/models/certifiedBillMaster.py` | `certified_bill_master`, `certified_bill_items` |

---

## See Also

- [`sale_order/README.md`](sale_order/README.md)
- [`certified_bill/README.md`](certified_bill/README.md)
