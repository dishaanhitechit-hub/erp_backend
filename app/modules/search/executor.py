from app.extensions import db
from sqlalchemy import text
from .schema import MODULES, ALL_MODULES


def _resolve_project_name(name: str):
    rows = db.session.execute(
        text("SELECT project_code FROM projects WHERE project_name ILIKE :n"),
        {"n": f"%{name}%"}
    ).fetchall()
    return [r[0] for r in rows]


def _resolve_vendor_name(name: str):
    rows = db.session.execute(
        text("SELECT id FROM vendors WHERE ledger_name ILIKE :n"),
        {"n": f"%{name}%"}
    ).fetchall()
    return [r[0] for r in rows]


def _resolve_creator_name(name: str):
    rows = db.session.execute(
        text("SELECT id FROM users WHERE username ILIKE :n"),
        {"n": f"%{name}%"}
    ).fetchall()
    return [r[0] for r in rows]


def _resolve_multi_vendor(names: list):
    all_ids = []
    for name in names:
        rows = db.session.execute(
            text("SELECT id FROM vendors WHERE ledger_name ILIKE :n"),
            {"n": f"%{name}%"}
        ).fetchall()
        all_ids.extend([r[0] for r in rows])
    return list(set(all_ids))


def _resolve_multi_project(names: list):
    all_codes = []
    for name in names:
        rows = db.session.execute(
            text("SELECT project_code FROM projects WHERE project_name ILIKE :n"),
            {"n": f"%{name}%"}
        ).fetchall()
        all_codes.extend([r[0] for r in rows])
    return list(set(all_codes))


def _resolve_linked_order_no(order_no: str, linked_order_table: str, linked_order_fk: str, linked_order_no_field: str):
    row = db.session.execute(
        text(f"SELECT id FROM {linked_order_table} WHERE {linked_order_no_field} ILIKE :n"),
        {"n": f"%{order_no}%"}
    ).fetchone()
    if not row:
        return []
    order_id = row[0]
    return [order_id]


def _resolve_item_name(name: str, item_table: str, item_fk: str):
    rows = db.session.execute(
        text(f"""
            SELECT DISTINCT t.{item_fk}
            FROM {item_table} t
            JOIN items i ON i.item_code = t.item_code
            WHERE i.item_name ILIKE :n
        """),
        {"n": f"%{name}%"}
    ).fetchall()
    return [r[0] for r in rows]


def get_ids(parsed: dict, module: str, allowed_projects: list = None) -> list:
    if module not in MODULES:
        return []

    meta = MODULES[module]
    table = meta["table"]
    valid_fields = meta["fields"]
    virtual_fields = meta.get("virtual_fields", {})

    conditions = []
    params = {}

    # ── project-level permission filter ───────────────────────────
    if allowed_projects is not None and "project_code" in valid_fields:
        if not allowed_projects:
            return []
        placeholders = ", ".join([f":ap_{j}" for j in range(len(allowed_projects))])
        conditions.append(f"project_code IN ({placeholders})")
        for j, c in enumerate(allowed_projects):
            params[f"ap_{j}"] = c

    for i, f in enumerate(parsed.get("filters", [])):
        field = f.get("field")
        op = f.get("op")
        value = f.get("value")
        key = f"p{i}"

        # ── virtual field resolution ───────────────────────────────
        if field in virtual_fields:
            target = virtual_fields[field]

            if field == "project_name":
                codes = _resolve_project_name(str(value))
                if not codes:
                    return []
                placeholders = ", ".join([f":{key}_{j}" for j in range(len(codes))])
                conditions.append(f"project_code IN ({placeholders})")
                for j, c in enumerate(codes):
                    params[f"{key}_{j}"] = c

            elif field == "vendor_name":
                ids = _resolve_vendor_name(str(value))
                if not ids:
                    return []
                placeholders = ", ".join([f":{key}_{j}" for j in range(len(ids))])
                conditions.append(f"vendor_id IN ({placeholders})")
                for j, v in enumerate(ids):
                    params[f"{key}_{j}"] = v

            elif field == "creator_name":
                ids = _resolve_creator_name(str(value))
                if not ids:
                    return []
                placeholders = ", ".join([f":{key}_{j}" for j in range(len(ids))])
                conditions.append(f"created_by IN ({placeholders})")
                for j, v in enumerate(ids):
                    params[f"{key}_{j}"] = v

            elif field == "item_name":
                item_table = meta.get("item_table")
                item_fk = meta.get("item_fk")
                if not item_table or not item_fk:
                    continue
                ids = _resolve_item_name(str(value), item_table, item_fk)
                if not ids:
                    return []
                placeholders = ", ".join([f":{key}_{j}" for j in range(len(ids))])
                conditions.append(f"id IN ({placeholders})")
                for j, v in enumerate(ids):
                    params[f"{key}_{j}"] = v

            elif field == "vendor_names":
                names = value if isinstance(value, list) else [value]
                ids = _resolve_multi_vendor(names)
                if not ids:
                    return []
                placeholders = ", ".join([f":{key}_{j}" for j in range(len(ids))])
                conditions.append(f"vendor_id IN ({placeholders})")
                for j, v in enumerate(ids):
                    params[f"{key}_{j}"] = v

            elif field == "project_names":
                names = value if isinstance(value, list) else [value]
                codes = _resolve_multi_project(names)
                if not codes:
                    return []
                placeholders = ", ".join([f":{key}_{j}" for j in range(len(codes))])
                conditions.append(f"project_code IN ({placeholders})")
                for j, c in enumerate(codes):
                    params[f"{key}_{j}"] = c

            elif field == "linked_order_no":
                linked_order_table = meta.get("linked_order_table")
                linked_order_fk = meta.get("linked_order_fk")
                linked_order_no_field = meta.get("linked_order_no_field")
                if not linked_order_table or not linked_order_fk:
                    continue
                order_ids = _resolve_linked_order_no(str(value), linked_order_table, linked_order_fk, linked_order_no_field)
                if not order_ids:
                    return []
                placeholders = ", ".join([f":{key}_{j}" for j in range(len(order_ids))])
                conditions.append(f"{linked_order_fk} IN ({placeholders})")
                for j, v in enumerate(order_ids):
                    params[f"{key}_{j}"] = v
            continue

        # ── regular fields ─────────────────────────────────────────
        if field not in valid_fields:
            continue

        if op == "eq":
            conditions.append(f"{field} = :{key}")
            params[key] = value
        elif op == "gt":
            conditions.append(f"{field} > :{key}")
            params[key] = value
        elif op == "gte":
            conditions.append(f"{field} >= :{key}")
            params[key] = value
        elif op == "lt":
            conditions.append(f"{field} < :{key}")
            params[key] = value
        elif op == "lte":
            conditions.append(f"{field} <= :{key}")
            params[key] = value
        elif op == "like":
            conditions.append(f"{field} ILIKE :{key}")
            params[key] = f"%{value}%"
        elif op == "between" and isinstance(value, list) and len(value) == 2:
            conditions.append(f"{field} BETWEEN :{key}_a AND :{key}_b")
            params[f"{key}_a"] = value[0]
            params[f"{key}_b"] = value[1]
        elif op == "in" and isinstance(value, list):
            placeholders = ", ".join([f":{key}_{j}" for j in range(len(value))])
            conditions.append(f"{field} IN ({placeholders})")
            for j, v in enumerate(value):
                params[f"{key}_{j}"] = v

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    sort = parsed.get("sort", {})
    sort_field = sort.get("field", "id")
    sort_dir = sort.get("dir", "desc").upper()
    if sort_field not in valid_fields and sort_field != "id":
        sort_field = "id"
    if sort_dir not in ("ASC", "DESC"):
        sort_dir = "DESC"

    limit = min(int(parsed.get("limit", 50)), 200)

    sql = f"SELECT id FROM {table} {where} ORDER BY {sort_field} {sort_dir} LIMIT {limit}"
    rows = db.session.execute(text(sql), params).fetchall()
    return [row[0] for row in rows]
