"""
Uniform pagination for every list API.

Contract
--------
Request (query string, all optional):
    page   1-based page number. Pagination is OFF unless ``page`` is sent, so
           dropdowns / exports that call a list API without it still get every
           row, exactly as before.
    limit  rows per page (default 25, max 500). Aliases accepted for older
           callers: pageSize, page_size, per_page, perPage.
           ``limit=all`` (or 0) returns every row on one page.

Response (always the same shape when paginated):
    {
      "message": "...",
      "data": [ ...rows of this page... ],
      "pagination": {
        "page": 2, "limit": 25, "total": 312, "totalPages": 13,
        "hasNext": true, "hasPrev": true
      }
    }

How endpoints get it
--------------------
1. Nothing to do (most list APIs): a GET whose JSON body has a list in
   ``data`` is sliced by ``register_pagination`` after the view returns.
2. Heavy lists page in the database with ``paginate_query(query)`` - the view
   returns only that page and the hook leaves it alone.
3. Endpoints with their own paging (custom body shape) call
   ``set_pagination(total, page, limit)`` so the standard ``pagination`` block
   is added to their body too.
"""

from math import ceil

from flask import g, json, request

DEFAULT_LIMIT = 25
MAX_LIMIT = 500
LIMIT_KEYS = ("limit", "pageSize", "page_size", "per_page", "perPage")


def _to_int(value, default):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def get_page_params(args=None, default_limit=DEFAULT_LIMIT):
    """(page, limit) from the query string, or None when the caller did not ask
    for a page. limit is None for "all rows"."""
    args = request.args if args is None else args
    if args.get("page") in (None, ""):
        return None
    page = max(_to_int(args.get("page"), 1), 1)

    raw = next((args.get(k) for k in LIMIT_KEYS if args.get(k) not in (None, "")), None)
    if raw is None:
        limit = default_limit
    elif str(raw).lower() == "all" or _to_int(raw, default_limit) == 0:
        limit = None
    else:
        limit = min(max(_to_int(raw, default_limit), 1), MAX_LIMIT)
    return page, limit


def build_meta(total, page, limit):
    total = int(total or 0)
    if limit is None:  # "all"
        return {"page": 1, "limit": total, "total": total,
                "totalPages": 1 if total else 0, "hasNext": False, "hasPrev": False}
    total_pages = ceil(total / limit) if total else 0
    return {
        "page": page,
        "limit": limit,
        "total": total,
        "totalPages": total_pages,
        "hasNext": page < total_pages,
        "hasPrev": page > 1,
    }


def set_pagination(total, page, limit):
    """Mark this request as already paginated and record the meta block that
    the hook adds to the response body as ``pagination``."""
    meta = build_meta(total, page, limit)
    g._pagination_meta = meta
    return meta


def paginate_query(query, default_limit=DEFAULT_LIMIT):
    """Page a SQLAlchemy query in the database.

    Returns (rows, meta). With no ``page`` in the request it returns every row
    and meta None, so callers behave exactly as before.
    """
    params = get_page_params(default_limit=default_limit)
    if params is None:
        return query.all(), None
    page, limit = params
    total = query.order_by(None).count()
    if limit is None:
        rows = query.all()
    else:
        rows = query.limit(limit).offset((page - 1) * limit).all()
    return rows, set_pagination(total, page, limit)


def paginate_list(rows, default_limit=DEFAULT_LIMIT):
    """Same as paginate_query for an in-memory list. Returns (rows, meta)."""
    params = get_page_params(default_limit=default_limit)
    if params is None:
        return rows, None
    page, limit = params
    meta = set_pagination(len(rows), page, limit)
    if limit is not None:
        start = (page - 1) * limit
        rows = rows[start:start + limit]
    return rows, meta


def register_pagination(app):
    @app.after_request
    def _apply_pagination(response):
        if request.method != "GET" or response.status_code != 200:
            return response
        meta = g.get("_pagination_meta")
        params = None if meta else get_page_params()
        if meta is None and params is None:
            return response
        if response.direct_passthrough or not response.is_json:
            return response

        body = response.get_json(silent=True)
        if not isinstance(body, dict):
            return response

        if meta is None:
            rows = body.get("data")
            if not isinstance(rows, list):
                return response  # detail / summary endpoints: nothing to page
            page, limit = params
            meta = build_meta(len(rows), page, limit)
            if limit is not None:
                start = (page - 1) * limit
                body["data"] = rows[start:start + limit]
        elif "pagination" in body and body["pagination"] == meta:
            return response

        body["pagination"] = meta
        response.set_data(json.dumps(body))
        return response
