import json
import time
from collections import defaultdict
from threading import Lock

from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from sqlalchemy import text

from app.extensions import db
from app.models.search_history import SearchHistory
from app.models.user import User
from .nlp import parse_query
from .executor import get_ids
from .schema import ALL_MODULES

search_bp = Blueprint("search", __name__)

# ── rate limiter ───────────────────────────────────────────────────
_rate_store = defaultdict(list)
_rate_lock = Lock()
RATE_LIMIT = 20
RATE_WINDOW = 60


def _check_rate_limit(user_id):
    now = time.time()
    with _rate_lock:
        timestamps = [t for t in _rate_store[user_id] if now - t < RATE_WINDOW]
        if len(timestamps) >= RATE_LIMIT:
            wait = int(RATE_WINDOW - (now - timestamps[0])) + 1
            _rate_store[user_id] = timestamps
            return False, wait
        timestamps.append(now)
        _rate_store[user_id] = timestamps
        return True, 0


# ── permission helpers ─────────────────────────────────────────────
def _is_super_admin(user_id: int) -> bool:
    row = db.session.execute(
        text("""
            SELECT r.name FROM users u
            JOIN roles r ON r.id = u.global_role_id
            WHERE u.id = :uid
        """),
        {"uid": user_id}
    ).fetchone()
    return row and row[0] == "super_admin"


def _get_allowed_projects(user_id: int) -> list:
    rows = db.session.execute(
        text("""
            SELECT DISTINCT p.project_code
            FROM project_user_roles pur
            JOIN projects p ON p.id = pur.project_id
            WHERE pur.user_id = :uid
        """),
        {"uid": user_id}
    ).fetchall()
    return [r[0] for r in rows]


def _get_permitted_modules(user_id: int) -> list:
    """Returns list of sub_module names the user has any permission on."""
    rows = db.session.execute(
        text("""
            SELECT DISTINCT sm.name
            FROM project_user_permissions pup
            JOIN project_user_roles pur ON pur.id = pup.project_user_role_id
            JOIN feature_pages fp ON fp.id = pup.page_id
            JOIN sub_modules sm ON sm.id = fp.submodule_id
            WHERE pur.user_id = :uid AND pup.allowed = true
        """),
        {"uid": user_id}
    ).fetchall()
    return [r[0] for r in rows]


# module key → sub_module name mapping (match your sub_modules table names)
MODULE_PERMISSION_MAP = {
    "order":    "Order",
    "pw_order": "ProjectWork_Order",
    "grn":      "GRN",
    "indent":   "Indent",
    "enquiry":  "Enquiry",
    "srn":      "SRN",
    "dc":       "DC",
}


def _limited_output(record: dict, module: str) -> dict:
    """Returns restricted summary — enough to know record exists, no sensitive data."""
    safe_keys = {
        "order":    ["id", "orderNo", "orderDate", "workflowStatus", "projectCode", "projectName", "subCode", "categoryCode"],
        "pw_order": ["id", "orderNo", "orderDate", "workflowStatus", "projectCode", "projectName"],
        "grn":      ["id", "grnNo", "grnDate", "workflowStatus", "projectCode", "projectName"],
        "indent":   ["id", "indentNo", "indentDate", "workflowStatus", "projectCode", "projectName"],
        "enquiry":  ["id", "enquiryNo", "enquiryDate", "workflowStatus", "projectCode", "projectName"],
        "srn":      ["id", "srnNo", "srnDate", "workflowStatus", "projectCode", "projectName"],
        "dc":       ["id", "dcNo", "dcDate", "workflowStatus", "projectCode", "projectName"],
    }
    keys = safe_keys.get(module, ["id"])
    summary = {k: record.get(k) for k in keys if k in record}
    summary["restricted"] = True
    summary["module"] = module
    summary["message"] = "You don't have permission to view full details of this module. Contact your admin."
    return summary


# ── detail function map ────────────────────────────────────────────
def _get_detail_fn(module: str):
    if module == "order":
        from app.modules.resources.order.service import get_order_details
        return get_order_details
    if module == "pw_order":
        from app.modules.resources.order_projectwork.service import get_pw_order_details
        return get_pw_order_details
    if module == "grn":
        from app.modules.resources.grn.service import get_grn_details
        return get_grn_details
    if module == "indent":
        from app.modules.resources.indent.service import get_indent_details
        return get_indent_details
    if module == "enquiry":
        from app.modules.resources.enquiry.service import get_enquiry_details
        return get_enquiry_details
    if module == "srn":
        from app.modules.resources.srn.service import get_srn_details
        return get_srn_details
    if module == "dc":
        from app.modules.resources.dc.service import get_dc_detail
        return get_dc_detail
    return None


def _fetch_details(module: str, ids: list, has_permission: bool) -> list:
    detail_fn = _get_detail_fn(module)
    if not detail_fn:
        return []
    results = []
    for record_id in ids:
        try:
            resp = detail_fn(record_id)
            data = resp.get_json()
            if data and data.get("data"):
                item = data["data"]
                if isinstance(item, list) and item:
                    record = item[0]
                elif isinstance(item, dict):
                    record = item
                else:
                    continue
                if has_permission:
                    results.append(record)
                else:
                    results.append(_limited_output(record, module))
        except Exception:
            continue
    return results


def _save_history(user_id, query, parsed, modules, count):
    try:
        db.session.add(SearchHistory(
            user_id=user_id,
            query=query,
            parsed=json.dumps(parsed),
            modules=",".join(modules) if modules else "",
            result_count=count,
        ))
        db.session.commit()
    except Exception:
        db.session.rollback()


# ── main search endpoint ───────────────────────────────────────────
@search_bp.post("/nl")
@jwt_required()
def natural_language_search():
    user_id = get_jwt_identity()

    allowed, wait = _check_rate_limit(user_id)
    if not allowed:
        return jsonify({
            "message": f"Too many requests. Try again in {wait} seconds.",
            "data": []
        }), 429

    body = request.get_json(silent=True) or {}
    query = (body.get("query") or "").strip()

    if not query:
        return jsonify({"message": "query is required", "data": []}), 400

    try:
        parsed = parse_query(query)

        # ── resolve permissions ────────────────────────────────────
        is_admin = _is_super_admin(user_id)
        allowed_projects = None if is_admin else _get_allowed_projects(user_id)
        permitted_modules = None if is_admin else _get_permitted_modules(user_id)

        # ── resolve modules ────────────────────────────────────────
        modules = parsed.get("modules") or [parsed.get("module")]
        modules = [m for m in modules if m]
        if "all" in modules:
            modules = ALL_MODULES

        if len(modules) == 1:
            module = modules[0]
            has_perm = is_admin or (MODULE_PERMISSION_MAP.get(module, module) in (permitted_modules or []))
            ids = get_ids(parsed, module, allowed_projects)
            results = _fetch_details(module, ids, has_perm)
            total = len(results)
            _save_history(user_id, query, parsed, modules, total)
            return jsonify({
                "message": "success",
                "module": module,
                "parsed": parsed,
                "count": total,
                "data": results,
            }), 200

        else:
            grouped = {}
            total = 0
            for module in modules:
                has_perm = is_admin or (MODULE_PERMISSION_MAP.get(module, module) in (permitted_modules or []))
                ids = get_ids(parsed, module, allowed_projects)
                results = _fetch_details(module, ids, has_perm)
                grouped[module] = results
                total += len(results)
            _save_history(user_id, query, parsed, modules, total)
            return jsonify({
                "message": "success",
                "modules": modules,
                "parsed": parsed,
                "count": total,
                "data": grouped,
            }), 200

    except Exception as e:
        return jsonify({"message": str(e), "data": []}), 500


# ── recent searches ────────────────────────────────────────────────
@search_bp.get("/recent")
@jwt_required()
def get_recent_searches():
    user_id = get_jwt_identity()
    rows = (
        SearchHistory.query
        .filter_by(user_id=user_id)
        .order_by(SearchHistory.created_at.desc())
        .limit(10)
        .all()
    )
    return jsonify({
        "message": "success",
        "data": [
            {
                "id": r.id,
                "query": r.query,
                "modules": r.modules.split(",") if r.modules else [],
                "resultCount": r.result_count,
                "createdAt": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ]
    }), 200


@search_bp.delete("/recent/<int:history_id>")
@jwt_required()
def delete_recent_search(history_id):
    user_id = get_jwt_identity()
    row = SearchHistory.query.filter_by(id=history_id, user_id=user_id).first()
    if not row:
        return jsonify({"message": "Not found"}), 404
    db.session.delete(row)
    db.session.commit()
    return jsonify({"message": "Deleted"}), 200


@search_bp.delete("/recent")
@jwt_required()
def clear_recent_searches():
    user_id = get_jwt_identity()
    SearchHistory.query.filter_by(user_id=user_id).delete()
    db.session.commit()
    return jsonify({"message": "Search history cleared"}), 200
