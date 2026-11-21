"""
Bulk Sale Order (OG Sale Order) import — Excel with two sheets.

Same flow as the Expenses Docket / Journal bulk uploads: the frontend parses
the workbook into plain rows and posts them here.

  Sheet "Orders": one row = one Sale Order
      soRef, soDate, orderTitle, orderNo (customer order no), orderValidity, debtorCode
  Sheet "Items":  one row = one item line, linked to its order by soRef
      soRef, itemType (BOQ / Non-BOQ), itemCode, itemName, itemDescription,
      unit, qty, rate, gstPercent

Amounts are computed here exactly like the single form (`_build_rows`):
amount = qty x rate, GST = amount x GST% / 100. Orders are saved as Draft, each
in its own transaction; with ``submit: true`` every created order is then sent
through the normal `submit_og_sale_order` (if that fails it stays Draft and the
reason is returned). Attachments are not part of bulk.

Endpoints (see routes.py):
  GET  /project-mgmt/og-sale-order/bulk/reference?projectCode  → debtor list
  POST /project-mgmt/og-sale-order/bulk/validate               → dry run
  POST /project-mgmt/og-sale-order/bulk/import                 → create (+ submit)
"""

import re
import uuid as _uuid
from datetime import datetime, date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from sqlalchemy import func

from app.extensions import db
from app.response import res
from app.models.ogSaleOrder import OgSaleOrderMaster, OgSaleOrderItem, OgSaleOrderBoqItem
from app.models.project import Project
from app.models.vendor import Vendor
from app.modules.work_flow import is_creator

_MODULE = "sale_order"
MAX_ORDERS = 1000
MAX_ITEMS = 5000
_TWO = Decimal("0.01")

_DATE_FORMATS = (
    "%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%d.%m.%Y", "%Y/%m/%d",
    "%d-%b-%Y", "%d %b %Y", "%d-%B-%Y", "%d %B %Y", "%d-%b-%y", "%d/%m/%y", "%d-%m-%y",
)

_TYPE_ALIASES = {
    "boq": "BOQ",
    "nonboq": "Non-BOQ", "non": "Non-BOQ", "nboq": "Non-BOQ", "normal": "Non-BOQ",
    "item": "Non-BOQ", "items": "Non-BOQ", "regular": "Non-BOQ",
}


# ── normalisers ──────────────────────────────────────────────────

def _s(v):
    return "" if v is None else str(v).strip()


def _key(v):
    return re.sub(r"[\s_\-./]", "", _s(v).lower())


def _ref(v):
    """SO Ref as typed: '1', '1.0' (Excel numbers) and ' 1 ' are the same ref."""
    raw = _s(v)
    if re.fullmatch(r"\d+\.0+", raw):
        raw = raw.split(".")[0]
    return raw


def _parse_date(v):
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    raw = _s(v)
    if not raw:
        return None
    raw = raw.split("T")[0].split(" 00:00")[0].strip()
    for fmt in _DATE_FORMATS:
        try:
            d = datetime.strptime(raw, fmt).date()
            if 1900 <= d.year <= 9999:
                return d
        except ValueError:
            continue
    return None


def _num(v, label, *, required=True, positive=False, max_value=None):
    """Returns (Decimal|None, error|None)."""
    raw = _s(v).replace(",", "").replace("₹", "").replace("%", "").strip()
    if raw in ("", "-"):
        return (None, f"{label} is required") if required else (Decimal("0"), None)
    try:
        n = Decimal(raw)
    except InvalidOperation:
        return None, f"{label} '{_s(v)}' is not a valid number"
    if not n.is_finite():
        return None, f"{label} '{_s(v)}' is not a valid number"
    if positive and n <= 0:
        return None, f"{label} must be greater than 0"
    if n < 0:
        return None, f"{label} cannot be negative"
    if max_value is not None and n > max_value:
        return None, f"{label} cannot be more than {max_value}"
    return n, None


def _fmt(d):
    return d.strftime("%Y-%m-%d") if d else None


def _q2(d):
    return d.quantize(_TWO, rounding=ROUND_HALF_UP)


# ── validation ───────────────────────────────────────────────────

def _debtor_map():
    """LEDGER_CODE → Vendor, for every debtor ledger."""
    return {
        (v.ledger_code or "").strip().upper(): v
        for v in Vendor.query.filter(Vendor.is_debtor.is_(True)).all()
        if v.ledger_code
    }


def _validate_item(raw):
    r = {
        "rowNo":           raw.get("rowNo"),
        "soRef":           _ref(raw.get("soRef")),
        "itemType":        _s(raw.get("itemType")),
        "itemCode":        _s(raw.get("itemCode")),
        "itemName":        _s(raw.get("itemName")),
        "itemDescription": _s(raw.get("itemDescription")),
        "unit":            _s(raw.get("unit")),
        "qty":             _s(raw.get("qty")),
        "rate":            _s(raw.get("rate")),
        "gstPercent":      _s(raw.get("gstPercent")),
        "amount":          0.0,
        "gstAmount":       0.0,
        "errors":          [],
        "errorFields":     [],
    }

    def bad(field, msg):
        r["errors"].append(msg)
        r["errorFields"].append(field)

    t = _TYPE_ALIASES.get(_key(r["itemType"]))
    if not r["itemType"]:
        bad("itemType", "Item Type is required (BOQ or Non-BOQ)")
    elif not t:
        bad("itemType", f"Item Type '{r['itemType']}' must be BOQ or Non-BOQ")
    else:
        r["itemType"] = t
    if not r["itemName"]:
        bad("itemName", "Item Name is required")

    qty, e = _num(raw.get("qty"), "Qty", positive=True)
    if e:
        bad("qty", e)
    rate, e = _num(raw.get("rate"), "Rate")
    if e:
        bad("rate", e)
    gst, e = _num(raw.get("gstPercent"), "GST %", required=False, max_value=100)
    if e:
        bad("gstPercent", e)

    if qty is not None and rate is not None and gst is not None:
        amount = qty * rate                      # same maths as _build_rows
        r["_qty"], r["_rate"], r["_gst"] = qty, rate, gst
        r["_amount"], r["_gstAmount"] = amount, amount * gst / 100
        r["amount"] = float(_q2(r["_amount"]))
        r["gstAmount"] = float(_q2(r["_gstAmount"]))
    return r


def _validate(orders_raw, items_raw, project):
    debtors = _debtor_map()

    # items grouped by ref (file order kept)
    items_by_ref = {}
    for raw in items_raw:
        it = _validate_item(raw)
        items_by_ref.setdefault(it["soRef"].upper(), []).append(it)

    # duplicate SO Ref on the Orders sheet
    ref_rows = {}
    for o in orders_raw:
        ref_rows.setdefault(_ref(o.get("soRef")).upper(), []).append(o.get("rowNo"))

    # Customer Order No: already in this project / used twice in the file
    file_nos = {}
    for o in orders_raw:
        no = _s(o.get("orderNo")).upper()
        if no:
            file_nos.setdefault(no, []).append(_ref(o.get("soRef")))
    existing = {}
    if file_nos:
        for erp_no, ono in (
            db.session.query(OgSaleOrderMaster.erp_no, OgSaleOrderMaster.order_no)
            .filter(OgSaleOrderMaster.project_code == project.project_code,
                    func.upper(func.trim(OgSaleOrderMaster.order_no)).in_(list(file_nos)))
        ):
            existing.setdefault((ono or "").strip().upper(), []).append(erp_no)

    orders, seen_refs = [], set()
    for raw in orders_raw:
        ref = _ref(raw.get("soRef"))
        o = {
            "rowNo":         raw.get("rowNo"),
            "soRef":         ref,
            "soDate":        _s(raw.get("soDate")),
            "orderTitle":    _s(raw.get("orderTitle")),
            "orderNo":       _s(raw.get("orderNo")),
            "orderValidity": _s(raw.get("orderValidity")),
            "debtorCode":    _s(raw.get("debtorCode")),
            "debtorId":      None,
            "debtorName":    None,
            "errors":        [],
            "warnings":      [],
            "errorFields":   [],
        }

        def bad(field, msg, o=o):
            o["errors"].append(msg)
            if field:
                o["errorFields"].append(field)

        if not ref:
            bad("soRef", "SO Ref is required")
        elif len(ref_rows.get(ref.upper(), [])) > 1:
            rows = ", ".join(str(n) for n in ref_rows[ref.upper()])
            bad("soRef", f"SO Ref '{ref}' is used on more than one order (rows {rows})")

        so_date = _parse_date(raw.get("soDate"))
        if not o["soDate"]:
            bad("soDate", "SO Date is required")
        elif not so_date:
            bad("soDate", f"SO Date '{o['soDate']}' is not a valid date (use DD-MM-YYYY)")
        else:
            o["soDate"] = _fmt(so_date)

        if not o["orderTitle"]:
            bad("orderTitle", "Order Title is required")
        elif len(o["orderTitle"]) > 200:
            bad("orderTitle", "Order Title is longer than 200 characters")

        if len(o["orderNo"]) > 50:
            bad("orderNo", "Customer Order No is longer than 50 characters")
        elif o["orderNo"]:
            no = o["orderNo"].upper()
            if existing.get(no):
                o["warnings"].append(
                    f"Customer Order No '{o['orderNo']}' already exists in this project "
                    f"({', '.join(existing[no])})")
            others = [r for r in file_nos.get(no, []) if r.upper() != ref.upper()]
            if others:
                o["warnings"].append(
                    f"Customer Order No '{o['orderNo']}' is also used by SO Ref {', '.join(others)} in this file")

        if o["orderValidity"]:
            val = _parse_date(raw.get("orderValidity"))
            if not val:
                bad("orderValidity", f"Order Validity '{o['orderValidity']}' is not a valid date (use DD-MM-YYYY)")
            else:
                o["orderValidity"] = _fmt(val)
                if so_date and val < so_date:
                    bad("orderValidity", "Order Validity cannot be before the SO Date")

        if not o["debtorCode"]:
            bad("debtorCode", "Debtor Code is required")
        else:
            v = debtors.get(o["debtorCode"].upper())
            if not v:
                bad("debtorCode", f"Debtor Code '{o['debtorCode']}' is not a Sundry Debtor in the master")
            else:
                o["debtorCode"], o["debtorId"], o["debtorName"] = v.ledger_code, v.id, v.ledger_name
                if (v.status or "Active") != "Active":
                    o["warnings"].append(f"Debtor {v.ledger_code} is marked {v.status}")

        # items: the first order with a ref takes them (duplicates are errors anyway)
        items = [] if ref.upper() in seen_refs else items_by_ref.get(ref.upper(), [])
        if ref:
            seen_refs.add(ref.upper())
        if not items and ref and len(ref_rows.get(ref.upper(), [])) == 1:
            bad(None, f"No items found for SO Ref '{ref}' on the Items sheet")

        basic = sum((i.get("_amount", Decimal("0")) for i in items), Decimal("0"))
        gst = sum((i.get("_gstAmount", Decimal("0")) for i in items), Decimal("0"))
        bad_items = sum(1 for i in items if i["errors"])
        if bad_items:
            bad(None, f"{bad_items} item row{' needs' if bad_items == 1 else 's need'} correction")

        o.update({
            "items":       items,
            "itemCount":   len(items),
            "boqCount":    sum(1 for i in items if i["itemType"] == "BOQ"),
            "basicAmount": float(_q2(basic)),
            "gstAmount":   float(_q2(gst)),
            "totalAmount": float(_q2(basic + gst)),
        })
        o["valid"] = not o["errors"]
        orders.append(o)

    # items whose SO Ref is not on the Orders sheet
    orphans = []
    for ref_u, items in items_by_ref.items():
        if ref_u not in seen_refs:
            for it in items:
                it["errors"].insert(0, f"SO Ref '{it['soRef']}' is not on the Orders sheet"
                                    if it["soRef"] else "SO Ref is required")
                it["errorFields"].append("soRef")
                orphans.append(it)
    return orders, orphans


def _public(order):
    """Strip the internal Decimal keys before sending to the client."""
    out = dict(order)
    out["items"] = [{k: v for k, v in i.items() if not k.startswith("_")} for i in order["items"]]
    return out


def _clean_item(i):
    return {k: v for k, v in i.items() if not k.startswith("_")}


def _summary(orders, orphans):
    valid = [o for o in orders if o["valid"]]
    return {
        "totalOrders":   len(orders),
        "validOrders":   len(valid),
        "invalidOrders": len(orders) - len(valid),
        "totalItems":    sum(o["itemCount"] for o in orders) + len(orphans),
        "orphanItems":   len(orphans),
        "validAmount":   round(sum(o["totalAmount"] for o in valid), 2),
    }


def _precheck(data, user_id, need_rows=True):
    project_code = data.get("projectCode")
    if not project_code:
        return None, None, None, res("projectCode required", [], 400)
    project = Project.query.filter_by(project_code=project_code).first()
    if not project:
        return None, None, None, res("Project not found", [], 404)
    if not is_creator(project_code, _MODULE, user_id):
        return None, None, None, res("You are not a Sale Order creator for this project", [], 403)
    if not need_rows:
        return project, None, None, None
    orders = data.get("orders") or []
    items = data.get("items") or []
    if not isinstance(orders, list) or not isinstance(items, list):
        return None, None, None, res("orders and items must be lists", [], 400)
    if not orders:
        return None, None, None, res("No orders found on the Orders sheet", [], 400)
    if len(orders) > MAX_ORDERS:
        return None, None, None, res(
            f"Too many orders ({len(orders)}). Max {MAX_ORDERS} per upload — split the file.", [], 400)
    if len(items) > MAX_ITEMS:
        return None, None, None, res(
            f"Too many item rows ({len(items)}). Max {MAX_ITEMS} per upload — split the file.", [], 400)
    return project, orders, items, None


# ══════════════════════════════════════════════════════════════════
# PUBLIC
# ══════════════════════════════════════════════════════════════════

def get_bulk_sale_order_reference(data, user_id):
    try:
        _, _, _, err = _precheck(data, user_id, need_rows=False)
        if err:
            return err
        debtors = sorted(
            ({"code": v.ledger_code, "name": v.ledger_name, "gstin": v.gstin, "status": v.status}
             for v in _debtor_map().values()),
            key=lambda d: (d["name"] or "").lower(),
        )
        return res("Reference data fetched", {"debtors": debtors}, 200)
    except Exception as e:
        return res(str(e), [], 500)


def validate_bulk_sale_order(data, user_id):
    try:
        project, orders_raw, items_raw, err = _precheck(data, user_id)
        if err:
            return err
        orders, orphans = _validate(orders_raw, items_raw, project)
        return res("Validated", {
            "summary":     _summary(orders, orphans),
            "orders":      [_public(o) for o in orders],
            "orphanItems": [_clean_item(i) for i in orphans],
        }, 200)
    except Exception as e:
        return res(str(e), [], 500)


def import_bulk_sale_order(data, user_id):
    try:
        project, orders_raw, items_raw, err = _precheck(data, user_id)
        if err:
            return err
        do_submit = data.get("submit") in (True, "true", "1", 1)
        orders, orphans = _validate(orders_raw, items_raw, project)

        from app.modules.project_mgmt.custom_billing.og_sale_order.service import (
            _build_rows, generate_erp_no, submit_og_sale_order,
        )

        created, failed = [], []
        for o in orders:
            if not o["valid"]:
                failed.append(_public(o))
                continue
            try:
                so = OgSaleOrderMaster(
                    erp_no             = generate_erp_no(),
                    og_sale_order_uuid = str(_uuid.uuid4()),
                    og_sale_order_date = datetime.strptime(o["soDate"], "%Y-%m-%d").date(),
                    order_no           = o["orderNo"] or None,
                    order_validity     = (datetime.strptime(o["orderValidity"], "%Y-%m-%d").date()
                                          if o["orderValidity"] else None),
                    order_title        = o["orderTitle"],
                    project_code       = project.project_code,
                    debtor_id          = o["debtorId"],
                    workflow_status    = "Draft",
                    current_level      = 0,
                    locked             = False,
                    created_by         = user_id,
                )
                db.session.add(so)
                db.session.flush()

                def rows_of(kind):
                    return [{
                        "slNo": sl, "itemCode": i["itemCode"], "itemName": i["itemName"],
                        "itemDescription": i["itemDescription"] or None, "unit": i["unit"] or None,
                        "orderQty": str(i["_qty"]), "rate": str(i["_rate"]), "gstPercent": str(i["_gst"]),
                    } for sl, i in enumerate((x for x in o["items"] if x["itemType"] == kind), start=1)]

                items, basic_i, gst_i = _build_rows(rows_of("Non-BOQ"), so.id, OgSaleOrderItem)
                boq, basic_b, gst_b = _build_rows(rows_of("BOQ"), so.id, OgSaleOrderBoqItem)
                db.session.add_all(items + boq)
                so.basic_amount = basic_i + basic_b
                so.gst_amount = gst_i + gst_b
                so.total_amount = so.basic_amount + so.gst_amount
                db.session.commit()
            except Exception as e:
                db.session.rollback()
                o["valid"] = False
                o["errors"] = o["errors"] + [f"Could not save: {e}"]
                failed.append(_public(o))
                continue

            row = {
                "soRef":          o["soRef"],
                "id":             so.id,
                "erpNo":          so.erp_no,
                "uuid":           so.og_sale_order_uuid,
                "soDate":         o["soDate"],
                "orderTitle":     o["orderTitle"],
                "debtorName":     o["debtorName"],
                "amount":         o["totalAmount"],
                "itemCount":      o["itemCount"],
                "workflowStatus": "Draft",
                "submitError":    None,
            }
            if do_submit:
                body, code = submit_og_sale_order(so.id, user_id)
                if code == 200:
                    row["workflowStatus"] = (body.get("data") or {}).get("workflowStatus") or "Submitted"
                else:
                    row["submitError"] = body.get("message") or "Submit failed"
            created.append(row)

        submitted = sum(1 for c in created if c["workflowStatus"] != "Draft")
        if do_submit:
            msg = f"{len(created)} sale order{'' if len(created) == 1 else 's'} created, {submitted} submitted"
        else:
            msg = f"{len(created)} sale order{'' if len(created) == 1 else 's'} created as Draft"
        if failed or orphans:
            msg += f", {len(failed)} need correction"
        return res(msg, {
            "created":     created,
            "failed":      failed,
            "orphanItems": [_clean_item(i) for i in orphans],
            "summary": {
                "createdCount":   len(created),
                "submittedCount": submitted,
                "submitFailed":   sum(1 for c in created if c["submitError"]),
                "failedCount":    len(failed),
                "createdAmount":  round(sum(c["amount"] for c in created), 2),
            },
        }, 200)
    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)
