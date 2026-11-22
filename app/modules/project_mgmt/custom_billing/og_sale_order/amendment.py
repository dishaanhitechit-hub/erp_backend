"""
Sale Order amendments — add extra items to an Approved Sale Order.

Flow
  Approved Sale Order → [Amend] → amendment (Draft) with new lines
  → Submit → same approvers as the Sale Order → final approval
  → the new lines are appended to the order (next Sl. No. of each table,
    tagged with amendment_id = "AMD-n") and the order totals go up.

Existing order lines are never changed or renumbered, so bills already raised
against the order (claim / certified bills match lines by Sl. No., budgets and
uncertain allocations by line id) stay exactly as they were, and the next claim
bill picks the new lines up automatically.

Rules
  * only an Approved, Active order can be amended
  * one open (Draft / Pending / Reback) amendment per order at a time
  * only a Sale Order creator of the project may raise / edit / submit / delete
  * approvers = the Sale Order's approvers (module "sale_order")
  * history is kept under module "sale_order_amendment"
"""

import json
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from sqlalchemy import func
from sqlalchemy.exc import SQLAlchemyError

from app.extensions import db
from app.response import res
from app.models.user import User
from app.models.ogSaleOrder import (
    OgSaleOrderMaster, OgSaleOrderItem, OgSaleOrderBoqItem,
    OgSaleOrderAmendment, OgSaleOrderAmendmentItem,
)
from app.modules.work_flow import (
    is_creator, is_current_approver, get_first_approver, get_next_approver,
    get_gap_level, create_history, get_history, get_approval_steps, get_my_approval_status,
)

_APPROVAL = "sale_order"             # creators / approvers come from the Sale Order path
_HISTORY = "sale_order_amendment"    # approval_history.module_code for amendments
OPEN_STATUSES = ("Draft", "Reback")  # + any Pending_Lx
MAX_LINES = 1000
_TWO = Decimal("0.01")


def amd_label(seq):
    return f"AMD-{seq}" if seq else None


def _is_open(status):
    return (status or "") in OPEN_STATUSES or (status or "").startswith("Pending")


def _fmt_date(d):
    if d is None:
        return None
    if isinstance(d, datetime):
        return d.strftime("%Y-%m-%d %H:%M")
    return d.strftime("%Y-%m-%d")


def _parse_date(val):
    if not val:
        return None
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(str(val).strip(), fmt).date()
        except (ValueError, TypeError):
            continue
    return None


def _user(uid):
    try:
        return int(uid)
    except (TypeError, ValueError):
        return uid


def _name(u):
    return u.username if u else None


# ── serialisation ────────────────────────────────────────────────

def _item_payload(i):
    return {
        "id":              i.id,
        "slNo":            i.sl_no,
        "type":            i.item_type,
        "itemCode":        i.item_code,
        "itemName":        i.item_name,
        "itemDescription": i.item_description,
        "unit":            i.unit,
        "orderQty":        float(i.order_qty or 0),
        "rate":            float(i.rate or 0),
        "amount":          float(i.amount or 0),
        "gstPercent":      float(i.gst_percent or 0),
        "gstAmount":       float(i.gst_amount or 0),
        "orderSlNo":       i.so_item_sl_no,
    }


def amendment_payload(a, with_items=True):
    so = a.og_sale_order
    out = {
        "id":               a.id,
        "seq":              a.amendment_seq,
        "label":            amd_label(a.amendment_seq),
        "amendmentNo":      a.amendment_no,
        "amendmentDate":    _fmt_date(a.amendment_date),
        "reason":           a.reason,
        "customerRef":      a.customer_ref,
        "attachment":       a.attachment,
        "ogSaleOrderId":    a.og_sale_order_id,
        "ogSaleOrderNo":    so.erp_no if so else None,
        "orderTitle":       so.order_title if so else None,
        "projectCode":      a.project_code,
        "basicAmount":      float(a.basic_amount or 0),
        "gstAmount":        float(a.gst_amount or 0),
        "totalAmount":      float(a.total_amount or 0),
        "orderTotalBefore": float(a.order_total_before) if a.order_total_before is not None else None,
        "orderTotalAfter":  float(a.order_total_after) if a.order_total_after is not None else None,
        "workflowStatus":   a.workflow_status,
        "currentLevel":     a.current_level,
        "locked":           a.locked,
        "itemCount":        len(a.items),
        "createdBy":        _name(a.creator),
        "createdAt":        _fmt_date(a.created_at),
        "submittedBy":      _name(a.submitter),
        "submittedAt":      _fmt_date(a.submitted_at),
        "approvedBy":       _name(a.approver),
        "finalApprovedAt":  _fmt_date(a.final_approved_at),
        "rejectedBy":       _name(a.rejector),
        "rejectedAt":       _fmt_date(a.rejected_at),
    }
    if with_items:
        out["items"] = [_item_payload(i) for i in a.items]
    return out


# ── input ────────────────────────────────────────────────────────

def _num(v, label, *, positive=False, max_value=None, required=True):
    raw = str(v if v is not None else "").replace(",", "").strip()
    if raw == "":
        return (None, f"{label} is required") if required else (Decimal("0"), None)
    try:
        n = Decimal(raw)
    except InvalidOperation:
        return None, f"{label} '{v}' is not a number"
    if not n.is_finite() or n < 0:
        return None, f"{label} cannot be negative"
    if positive and n <= 0:
        return None, f"{label} must be greater than 0"
    if max_value is not None and n > max_value:
        return None, f"{label} cannot be more than {max_value}"
    return n, None


def _parse_lines(raw):
    """→ (lines, errors). Each line keeps the same maths as the Sale Order form."""
    if isinstance(raw, str):
        try:
            raw = json.loads(raw or "[]")
        except ValueError:
            return [], ["Items are not valid JSON"]
    raw = [r for r in (raw or []) if isinstance(r, dict)
           and (str(r.get("itemName") or "").strip() or str(r.get("itemCode") or "").strip())]
    if not raw:
        return [], ["Add at least one item"]
    if len(raw) > MAX_LINES:
        return [], [f"Too many items (max {MAX_LINES})"]

    lines, errors = [], []
    for n, r in enumerate(raw, start=1):
        t = str(r.get("type") or "non-boq").strip().lower().replace("_", "-").replace(" ", "-")
        t = "boq" if t == "boq" else "non-boq" if t in ("non-boq", "nonboq", "item") else None
        name = str(r.get("itemName") or "").strip()
        qty, e1 = _num(r.get("orderQty"), "Qty", positive=True)
        rate, e2 = _num(r.get("rate"), "Rate")
        gst, e3 = _num(r.get("gstPercent"), "GST %", max_value=100, required=False)
        errs = [e for e in (e1, e2, e3) if e]
        if t is None:
            errs.append("Type must be BOQ or Non-BOQ")
        if not name:
            errs.append("Item Name is required")
        if errs:
            errors.append(f"Item {n}: " + "; ".join(errs))
            continue
        amount = qty * rate
        lines.append({
            "type": t, "itemCode": str(r.get("itemCode") or "").strip() or None, "itemName": name,
            "itemDescription": (str(r.get("itemDescription") or "").strip() or None),
            "unit": (str(r.get("unit") or "").strip() or None),
            "qty": qty, "rate": rate, "gst": gst, "amount": amount, "gstAmount": amount * gst / 100,
        })
    return lines, errors


def _set_lines(a, lines):
    a.items.clear()
    db.session.flush()
    basic = gst = Decimal("0")
    for sl, ln in enumerate(lines, start=1):
        a.items.append(OgSaleOrderAmendmentItem(
            sl_no=sl, item_type=ln["type"], item_code=ln["itemCode"], item_name=ln["itemName"],
            item_description=ln["itemDescription"], unit=ln["unit"], order_qty=ln["qty"],
            rate=ln["rate"], amount=ln["amount"], gst_percent=ln["gst"], gst_amount=ln["gstAmount"],
        ))
        basic += ln["amount"]
        gst += ln["gstAmount"]
    a.basic_amount = basic.quantize(_TWO, rounding=ROUND_HALF_UP)
    a.gst_amount = gst.quantize(_TWO, rounding=ROUND_HALF_UP)
    a.total_amount = a.basic_amount + a.gst_amount


def _upload(file, a):
    if not file or not getattr(file, "filename", None):
        return None
    from app.cloudinary_uploader import upload_file_to_bunny
    return upload_file_to_bunny(file=file, mainFolder="og_sale_order",
                                subFolder=f"{a.og_sale_order.erp_no}/amendments",
                                fileName=f"AMD-{a.amendment_seq}")


def _open_amendment(so_id, exclude_id=None):
    q = OgSaleOrderAmendment.query.filter(OgSaleOrderAmendment.og_sale_order_id == so_id)
    if exclude_id:
        q = q.filter(OgSaleOrderAmendment.id != exclude_id)
    return next((a for a in q.all() if _is_open(a.workflow_status)), None)


def amend_block_reason(so, user_id=None):
    """Why this order cannot be amended now (None = it can)."""
    if so.workflow_status != "Approved" or (so.status or "Active") != "Active":
        return "Only an Approved, Active Sale Order can be amended"
    open_a = _open_amendment(so.id)
    if open_a:
        return f"{amd_label(open_a.amendment_seq)} is still {open_a.workflow_status} — finish it first"
    if user_id is not None and not is_creator(so.project_code, _APPROVAL, user_id):
        return "You are not a Sale Order creator for this project"
    return None


# ══════════════════════════════════════════════════════════════════
# LIST (per order) / DETAIL
# ══════════════════════════════════════════════════════════════════

def list_amendments(so_id, user_id):
    try:
        so = OgSaleOrderMaster.query.get(so_id)
        if not so:
            return res("Sale Order not found", [], 404)
        approved = [a for a in so.amendments if a.workflow_status == "Approved"]
        original_total = float(so.total_amount or 0) - sum(float(a.total_amount or 0) for a in approved)
        reason = amend_block_reason(so, user_id)
        return res("Amendments fetched", {
            "ogSaleOrderId":   so.id,
            "ogSaleOrderNo":   so.erp_no,
            "workflowStatus":  so.workflow_status,
            "originalDate":    _fmt_date(so.og_sale_order_date),
            "originalTotal":   round(original_total, 2),
            "currentTotal":    float(so.total_amount or 0),
            "canAmend":        reason is None,
            "cannotAmendReason": reason,
            "isCreator":       is_creator(so.project_code, _APPROVAL, user_id),
            "amendments":      [amendment_payload(a) for a in so.amendments],
        }, 200)
    except Exception as e:
        return res(str(e), [], 500)


def get_amendment(amd_id):
    a = OgSaleOrderAmendment.query.get(amd_id)
    if not a:
        return res("Amendment not found", [], 404)
    return res("Amendment fetched", amendment_payload(a), 200)


# ══════════════════════════════════════════════════════════════════
# CREATE / EDIT / DELETE  (creator, Draft / Reback)
# ══════════════════════════════════════════════════════════════════

def create_amendment(so_id, form, files, user_id):
    try:
        so = (OgSaleOrderMaster.query.filter_by(id=so_id).with_for_update().first())
        if not so:
            return res("Sale Order not found", [], 404)
        reason = amend_block_reason(so, user_id)
        if reason:
            return res(reason, [], 403 if "creator" in reason else 400)

        amd_date = _parse_date(form.get("amendmentDate"))
        if not amd_date:
            return res("Amendment Date is required", [], 400)
        if so.og_sale_order_date and amd_date < so.og_sale_order_date:
            return res("Amendment Date cannot be before the Sale Order date", [], 400)
        why = (form.get("reason") or "").strip()
        if not why:
            return res("Reason is required", [], 400)
        lines, errors = _parse_lines(form.get("items"))
        if errors:
            return res(errors[0], {"errors": errors}, 400)

        seq = (db.session.query(func.max(OgSaleOrderAmendment.amendment_seq))
               .filter(OgSaleOrderAmendment.og_sale_order_id == so.id).scalar() or 0) + 1
        a = OgSaleOrderAmendment(
            og_sale_order_id=so.id, amendment_seq=seq, amendment_no=f"{so.erp_no}/AMD-{seq}",
            amendment_date=amd_date, reason=why, customer_ref=(form.get("customerRef") or "").strip()[:100] or None,
            project_code=so.project_code, workflow_status="Draft", current_level=0, locked=False,
            created_by=user_id, updated_by=user_id,
        )
        a.og_sale_order = so
        db.session.add(a)
        _set_lines(a, lines)
        a.attachment = _upload((files or {}).get("attachment"), a)
        db.session.commit()
        return res(f"{amd_label(seq)} created as Draft", amendment_payload(a), 201)
    except SQLAlchemyError as e:
        db.session.rollback()
        return res(str(e), [], 500)
    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


def edit_amendment(amd_id, form, files, user_id):
    try:
        a = OgSaleOrderAmendment.query.get(amd_id)
        if not a:
            return res("Amendment not found", [], 404)
        if a.workflow_status not in OPEN_STATUSES:
            return res("Only a Draft or Reback amendment can be edited", [], 400)
        if not is_creator(a.project_code, _APPROVAL, user_id):
            return res("You are not a Sale Order creator for this project", [], 403)

        if form.get("amendmentDate"):
            d = _parse_date(form.get("amendmentDate"))
            if not d:
                return res("Amendment Date is not valid", [], 400)
            if a.og_sale_order.og_sale_order_date and d < a.og_sale_order.og_sale_order_date:
                return res("Amendment Date cannot be before the Sale Order date", [], 400)
            a.amendment_date = d
        if form.get("reason") is not None:
            why = (form.get("reason") or "").strip()
            if not why:
                return res("Reason is required", [], 400)
            a.reason = why
        if form.get("customerRef") is not None:
            a.customer_ref = (form.get("customerRef") or "").strip()[:100] or None
        if form.get("items") is not None:
            lines, errors = _parse_lines(form.get("items"))
            if errors:
                return res(errors[0], {"errors": errors}, 400)
            _set_lines(a, lines)
        new_file = _upload((files or {}).get("attachment"), a)
        if new_file:
            a.attachment = new_file
        elif form.get("clearAttachment") == "true":
            a.attachment = None
        a.updated_by = user_id
        a.updated_at = datetime.utcnow()
        db.session.commit()
        return res("Amendment saved", amendment_payload(a), 200)
    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


def delete_amendment(amd_id, user_id):
    try:
        a = OgSaleOrderAmendment.query.get(amd_id)
        if not a:
            return res("Amendment not found", [], 404)
        if a.workflow_status not in OPEN_STATUSES:
            return res("Only a Draft or Reback amendment can be deleted", [], 400)
        if not is_creator(a.project_code, _APPROVAL, user_id):
            return res("You are not a Sale Order creator for this project", [], 403)
        label = amd_label(a.amendment_seq)
        db.session.delete(a)
        db.session.commit()
        return res(f"{label} deleted", {"id": amd_id}, 200)
    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


# ══════════════════════════════════════════════════════════════════
# APPLY / UNDO on the order
# ══════════════════════════════════════════════════════════════════

def _apply_to_order(a):
    """Final approval: append the lines to the order and raise its totals. Caller commits."""
    so = OgSaleOrderMaster.query.filter_by(id=a.og_sale_order_id).with_for_update().first()
    if so.workflow_status != "Approved":
        raise ValueError(f"Sale Order {so.erp_no} is {so.workflow_status}, not Approved — cannot add the items now")

    next_sl = {}
    for kind, model in (("non-boq", OgSaleOrderItem), ("boq", OgSaleOrderBoqItem)):
        next_sl[kind] = (db.session.query(func.max(model.sl_no))
                         .filter(model.og_sale_order_id == so.id).scalar() or 0)
    for i in a.items:
        model = OgSaleOrderBoqItem if i.item_type == "boq" else OgSaleOrderItem
        next_sl[i.item_type] += 1
        line = model(
            og_sale_order_id=so.id, sl_no=next_sl[i.item_type], item_code=i.item_code,
            item_name=i.item_name, item_description=i.item_description, item_name_desc=i.item_name,
            unit=i.unit, order_qty=i.order_qty, rate=i.rate, amount=i.amount,
            gst_percent=i.gst_percent, gst_amount=i.gst_amount, amendment_id=a.id,
        )
        db.session.add(line)
        db.session.flush()
        i.so_item_id, i.so_item_sl_no = line.id, line.sl_no

    a.order_total_before = so.total_amount or 0
    so.basic_amount = (so.basic_amount or 0) + (a.basic_amount or 0)
    so.gst_amount = (so.gst_amount or 0) + (a.gst_amount or 0)
    so.total_amount = so.basic_amount + so.gst_amount
    a.order_total_after = so.total_amount
    so.updated_at = datetime.utcnow()


def amendment_usage(a):
    """Where the lines this amendment added are already used (blocks undoing it)."""
    from app.models.billingMaster import BillingMaster, BillingItem, BillingBoqItem
    from app.models.budget import BudgetMaster, BudgetItem
    from app.models.uncertainAllocation import UncertainAllocationMaster, UncertainAllocationLine

    found = []
    later = (OgSaleOrderAmendment.query
             .filter(OgSaleOrderAmendment.og_sale_order_id == a.og_sale_order_id,
                     OgSaleOrderAmendment.amendment_seq > a.amendment_seq).all())
    for b in later:
        if b.workflow_status == "Approved" or _is_open(b.workflow_status):
            found.append(f"Later amendment {amd_label(b.amendment_seq)} ({b.workflow_status})")

    items = OgSaleOrderItem.query.filter_by(amendment_id=a.id).all()
    boq = OgSaleOrderBoqItem.query.filter_by(amendment_id=a.id).all()
    live = lambda q, m: q.filter(~m.workflow_status.in_(("Rejected", "Cancelled")))  # noqa: E731

    for model, lines in ((BillingItem, items), (BillingBoqItem, boq)):
        if not lines:
            continue
        rows = live(db.session.query(BillingMaster.erp_no, BillingMaster.billing_no)
                    .join(model, model.billing_id == BillingMaster.id)
                    .filter(BillingMaster.og_sale_order_id == a.og_sale_order_id,
                            model.sl_no.in_([x.sl_no for x in lines]),
                            model.claim_qty > 0), BillingMaster).distinct().all()
        found.extend(f"Bill {bn or en}" for en, bn in rows)

    ids_i, ids_b = [x.id for x in items], [x.id for x in boq]
    if ids_i or ids_b:
        cond = []
        if ids_i:
            cond.append(BudgetItem.og_sale_order_item_id.in_(ids_i))
        if ids_b:
            cond.append(BudgetItem.og_sale_order_boq_item_id.in_(ids_b))
        rows = live(db.session.query(BudgetMaster.budget_no).join(BudgetItem, BudgetItem.budget_id == BudgetMaster.id)
                    .filter(db.or_(*cond)), BudgetMaster).distinct().all()
        found.extend(f"Budget {n}" for (n,) in rows)

        cond = []
        if ids_i:
            cond.append(db.and_(UncertainAllocationLine.item_type == "item",
                                UncertainAllocationLine.og_sale_order_item_id.in_(ids_i)))
        if ids_b:
            cond.append(db.and_(UncertainAllocationLine.item_type == "boq_item",
                                UncertainAllocationLine.og_sale_order_item_id.in_(ids_b)))
        rows = live(db.session.query(UncertainAllocationMaster.ua_no)
                    .join(UncertainAllocationLine, UncertainAllocationLine.ua_id == UncertainAllocationMaster.id)
                    .filter(db.or_(*cond)), UncertainAllocationMaster).distinct().all()
        found.extend(f"Uncertain Allocation {n}" for (n,) in rows)
    return list(dict.fromkeys(found))


def undo_from_order(a, user_id=None):
    """Reback after approval: remove the lines it added and lower the order totals. Caller commits."""
    so = OgSaleOrderMaster.query.filter_by(id=a.og_sale_order_id).with_for_update().first()
    for model in (OgSaleOrderItem, OgSaleOrderBoqItem):
        model.query.filter_by(amendment_id=a.id).delete(synchronize_session=False)
    so.basic_amount = (so.basic_amount or 0) - (a.basic_amount or 0)
    so.gst_amount = (so.gst_amount or 0) - (a.gst_amount or 0)
    so.total_amount = so.basic_amount + so.gst_amount
    so.updated_at = datetime.utcnow()
    for i in a.items:
        i.so_item_id = i.so_item_sl_no = None
    a.order_total_before = a.order_total_after = None
    db.session.expire(so, ["items", "boq_items"])


# ══════════════════════════════════════════════════════════════════
# WORKFLOW
# ══════════════════════════════════════════════════════════════════

def _hist(a, action, by, comments=None, level=None):
    create_history(project_code=a.project_code, module_code=_HISTORY, record_id=a.id,
                   level_no=a.current_level if level is None else level,
                   action=action, action_by=by, comments=comments)


def _final(a, by):
    _apply_to_order(a)
    a.workflow_status = "Approved"
    a.locked = True
    a.approved_by = by
    a.final_approved_at = datetime.utcnow()


def _notify(kind, a, actor_id, **kw):
    try:
        from app.modules.communication import whatsapp_events as wa
        so = a.og_sale_order
        actor = User.query.get(actor_id)
        common = dict(module_code="og_sale_order", doc_no=a.amendment_no, uuid=str(so.og_sale_order_uuid),
                      project_code=a.project_code, record_id=so.id)
        if kind == "submit":
            wa.on_submit(submitter_name=_name(actor) or str(actor_id), **kw, **common)
        elif kind == "approve":
            wa.on_approve(approver_name=_name(actor) or str(actor_id), **kw, **common)
        elif kind == "final":
            wa.on_final_approve(approver_name=_name(actor) or str(actor_id),
                                creator_user=User.query.get(a.created_by), **common)
        elif kind in ("reback", "reject"):
            fn = wa.on_reback if kind == "reback" else wa.on_reject
            fn(approver_name=_name(actor) or str(actor_id), creator_user=User.query.get(a.created_by), **kw, **common)
    except Exception:
        pass


def submit_amendment(amd_id, user_id):
    try:
        a = OgSaleOrderAmendment.query.filter_by(id=amd_id).with_for_update().first()
        if not a:
            return res("Amendment not found", [], 404)
        if a.workflow_status not in OPEN_STATUSES:
            return res("Amendment already submitted", [], 400)
        if not is_creator(a.project_code, _APPROVAL, user_id):
            return res("You are not a Sale Order creator for this project", [], 403)
        if not a.items:
            return res("Amendment has no items", [], 400)
        so = a.og_sale_order
        if so.workflow_status != "Approved":
            return res(f"Sale Order {so.erp_no} is {so.workflow_status}, not Approved", [], 400)

        a.current_level = 0
        first = get_first_approver(a.project_code, _APPROVAL)
        a.submitted_by, a.submitted_at = user_id, datetime.utcnow()
        _hist(a, "SUBMIT", user_id)
        if first:
            a.workflow_status = f"Pending_L{first.level_no}"
            a.current_level = first.level_no
            a.locked = True
        else:
            _final(a, user_id)
        a.updated_by, a.updated_at = user_id, datetime.utcnow()
        db.session.commit()
        if first:
            _notify("submit", a, user_id, approver_user=first.user, current_level=first.level_no)
        return res(f"{amd_label(a.amendment_seq)} submitted", {
            "id": a.id, "workflowStatus": a.workflow_status, "currentLevel": a.current_level}, 200)
    except ValueError as e:
        db.session.rollback()
        return res(str(e), [], 400)
    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


def approve_amendment(amd_id, user_id, comments=None):
    try:
        a = OgSaleOrderAmendment.query.filter_by(id=amd_id).with_for_update().first()
        if not a:
            return res("Amendment not found", [], 404)
        if not (a.workflow_status or "").startswith("Pending"):
            return res("Amendment is not pending", [], 400)
        if not is_current_approver(a.project_code, _APPROVAL, a.current_level, user_id):
            return res("You are not the current approver", [], 403)
        gap = get_gap_level(a.project_code, _APPROVAL, a.current_level)
        if gap:
            return res(f"L{gap} is not assigned. Please assign it before approving.", [], 400)

        nxt = get_next_approver(a.project_code, _APPROVAL, a.current_level)
        prev_level = a.current_level
        if nxt:
            _hist(a, "APPROVE", user_id, comments)
            a.current_level = nxt.level_no
            a.workflow_status = f"Pending_L{nxt.level_no}"
        else:
            _hist(a, "FINAL_APPROVE", user_id, comments)
            _final(a, user_id)
        a.updated_by, a.updated_at = user_id, datetime.utcnow()
        db.session.commit()
        if nxt:
            _notify("approve", a, user_id, prev_level=prev_level, next_approver_user=nxt.user,
                    next_level=nxt.level_no)
        else:
            _notify("final", a, user_id)
        return res(f"{amd_label(a.amendment_seq)} approved" + ("" if nxt else " — items added to the Sale Order"), {
            "id": a.id, "workflowStatus": a.workflow_status, "currentLevel": a.current_level}, 200)
    except ValueError as e:
        db.session.rollback()
        return res(str(e), [], 400)
    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


def _send_back(amd_id, user_id, comments, action):
    try:
        a = OgSaleOrderAmendment.query.filter_by(id=amd_id).with_for_update().first()
        if not a:
            return res("Amendment not found", [], 404)
        if not (a.workflow_status or "").startswith("Pending"):
            return res("Amendment is not pending", [], 400)
        if not comments:
            return res(f"Comments required for {'reback' if action == 'REBACK' else 'rejection'}", [], 400)
        if not is_current_approver(a.project_code, _APPROVAL, a.current_level, user_id):
            return res("You are not the current approver", [], 403)
        _hist(a, action, user_id, comments)
        now = datetime.utcnow()
        if action == "REBACK":
            a.workflow_status, a.locked, a.correction_sent_at = "Reback", False, now
        else:
            a.workflow_status, a.locked, a.rejected_by, a.rejected_at = "Rejected", True, user_id, now
        a.updated_by, a.updated_at = user_id, now
        db.session.commit()
        _notify("reback" if action == "REBACK" else "reject", a, user_id, comments=comments)
        return res(f"{amd_label(a.amendment_seq)} {'sent for correction' if action == 'REBACK' else 'rejected'}",
                   {"id": a.id, "workflowStatus": a.workflow_status}, 200)
    except Exception as e:
        db.session.rollback()
        return res(str(e), [], 500)


def reback_amendment(amd_id, user_id, comments=None):
    return _send_back(amd_id, user_id, comments, "REBACK")


def reject_amendment(amd_id, user_id, comments=None):
    return _send_back(amd_id, user_id, comments, "REJECT")


def amendment_history(amd_id):
    try:
        a = OgSaleOrderAmendment.query.get(amd_id)
        if not a:
            return res("Amendment not found", [], 404)
        rows = get_history(_HISTORY, a.id)
        return res("History fetched", {
            "workflowStatus": a.workflow_status,
            "currentLevel":   a.current_level,
            "approvalSteps":  get_approval_steps(a.project_code, _APPROVAL, a, rows),
            "history": [{
                "id": r.id, "action": r.action, "level": r.level_no, "comments": r.comments,
                "actionBy": r.user.username if r.user else None,
                "createdAt": r.created_at.strftime("%Y-%m-%d %H:%M:%S") if r.created_at else None,
            } for r in rows],
        }, 200)
    except Exception as e:
        return res(str(e), [], 500)


def amendment_my_approval_status(amd_id, user_id):
    a = OgSaleOrderAmendment.query.get(amd_id)
    if not a:
        return res("Amendment not found", [], 404)
    return res("Approval status", get_my_approval_status(a.project_code, _APPROVAL, a, user_id), 200)


# ══════════════════════════════════════════════════════════════════
# helpers used by other modules (badges on Sale Order / bill lines)
# ══════════════════════════════════════════════════════════════════

def amendment_tags(og_sale_order_id):
    """{('non-boq'|'boq', sl_no): 'AMD-n'} for lines of an order that came from amendments."""
    if not og_sale_order_id:
        return {}
    out = {}
    for kind, model in (("non-boq", OgSaleOrderItem), ("boq", OgSaleOrderBoqItem)):
        rows = (db.session.query(model.sl_no, OgSaleOrderAmendment.amendment_seq)
                .join(OgSaleOrderAmendment, OgSaleOrderAmendment.id == model.amendment_id)
                .filter(model.og_sale_order_id == og_sale_order_id).all())
        out.update({(kind, sl): amd_label(seq) for sl, seq in rows})
    return out


def tag_rows(og_sale_order_id, items, boq_items):
    """Adds 'amendmentNo' to bill / lookup row dicts (matched by slNo, same as billing)."""
    tags = amendment_tags(og_sale_order_id)
    for kind, rows in (("non-boq", items), ("boq", boq_items)):
        for r in rows or []:
            if isinstance(r, dict):
                r["amendmentNo"] = tags.get((kind, r.get("slNo")))
    return items, boq_items
