# app/utils/runtime_store.py
"""
Shared short-lived key/value store (table `runtime_store`), safe with many
Gunicorn workers, a separate scheduler process and PgBouncer.

    put(key, value, ttl_seconds)          save / replace
    get(key)                              value, or None when missing / expired
    pop(key)                              get and delete in one step (one-time codes)
    claim(key, ttl_seconds)               True for exactly one caller until it expires
                                          or is released — a lock / "run once" marker
    release(key)                          give a claim back
    hit_rate(key, limit, window_seconds)  sliding-window rate limit → (allowed, wait)
    purge_expired()                       delete old rows

Every call runs in its OWN short transaction on its own connection, so it is
never committed or rolled back together with the request's business data.
All statements are single-transaction, so they work through PgBouncer in
transaction mode.

If the table is missing (migration not run yet) or the database cannot be
reached, the store falls back to this process's memory — the same behaviour
as before this change — and logs an error, so nothing that worked before
stops working.
"""

import logging
import threading
import time
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select, update
from sqlalchemy.exc import SQLAlchemyError

from app.extensions import db

log = logging.getLogger(__name__)

_TABLE = None
_mem = {}  # fallback: key → (value, expires_at)
_mem_lock = threading.Lock()
_last_fallback_log = 0.0


def _table():
    global _TABLE
    if _TABLE is None:
        from app.models.runtime_store import RuntimeStore
        _TABLE = RuntimeStore.__table__
    return _TABLE


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _insert():
    """INSERT that supports ON CONFLICT on the database in use."""
    if db.engine.dialect.name == "postgresql":
        from sqlalchemy.dialects.postgresql import insert
    else:  # tests run on SQLite
        from sqlalchemy.dialects.sqlite import insert
    return insert(_table())


def _fallback(action, exc):
    """Log (at most once a minute) that the shared store is not usable."""
    global _last_fallback_log
    if time.monotonic() - _last_fallback_log > 60:
        _last_fallback_log = time.monotonic()
        log.error(
            "runtime_store unavailable during %s — using this worker's memory instead "
            "(values are not shared between workers). Run `flask db upgrade`. Cause: %s",
            action, exc.__class__.__name__,
        )


def _mem_get(key, now):
    item = _mem.get(key)
    if item is None:
        return None
    if item[1] <= now:
        _mem.pop(key, None)
        return None
    return item


# ─────────────────────────────────────────────────────────────────
# basic values
# ─────────────────────────────────────────────────────────────────

def put(key, value, ttl_seconds):
    now = _now()
    expires = now + timedelta(seconds=ttl_seconds)
    try:
        stmt = _insert().values(key=key, value=value, expires_at=expires, updated_at=now)
        stmt = stmt.on_conflict_do_update(
            index_elements=["key"], set_={"value": value, "expires_at": expires, "updated_at": now},
        )
        with db.engine.begin() as conn:
            conn.execute(stmt)
    except SQLAlchemyError as exc:
        _fallback("put", exc)
        with _mem_lock:
            _mem[key] = (value, expires)


def get(key):
    now = _now()
    t = _table()
    try:
        with db.engine.begin() as conn:
            row = conn.execute(select(t.c.value).where(t.c.key == key, t.c.expires_at > now)).first()
        return row[0] if row else None
    except SQLAlchemyError as exc:
        _fallback("get", exc)
        with _mem_lock:
            item = _mem_get(key, now)
            return item[0] if item else None


def pop(key):
    """Return the value and delete it, atomically: two callers can never both get it."""
    now = _now()
    t = _table()
    try:
        with db.engine.begin() as conn:
            row = conn.execute(
                delete(t).where(t.c.key == key).returning(t.c.value, t.c.expires_at)
            ).first()
        if row is None or row[1] <= now:
            return None
        return row[0]
    except SQLAlchemyError as exc:
        _fallback("pop", exc)
        with _mem_lock:
            item = _mem_get(key, now)
            _mem.pop(key, None)
            return item[0] if item else None


# ─────────────────────────────────────────────────────────────────
# claims (locks / run-once markers)
# ─────────────────────────────────────────────────────────────────

def claim(key, ttl_seconds, owner=None):
    """
    True when this caller got the claim. Nobody else gets it until it expires
    or release(key) is called. An expired claim (e.g. its process crashed) can
    be taken over.
    """
    now = _now()
    expires = now + timedelta(seconds=ttl_seconds)
    t = _table()
    try:
        stmt = _insert().values(key=key, value={"owner": owner}, expires_at=expires, updated_at=now)
        stmt = stmt.on_conflict_do_update(
            index_elements=["key"],
            set_={"value": {"owner": owner}, "expires_at": expires, "updated_at": now},
            where=t.c.expires_at <= now,  # only take over an expired claim
        ).returning(t.c.key)
        with db.engine.begin() as conn:
            return conn.execute(stmt).first() is not None
    except SQLAlchemyError as exc:
        _fallback("claim", exc)
        with _mem_lock:
            if _mem_get(key, now):
                return False
            _mem[key] = ({"owner": owner}, expires)
            return True


def release(key):
    t = _table()
    try:
        with db.engine.begin() as conn:
            conn.execute(delete(t).where(t.c.key == key))
    except SQLAlchemyError as exc:
        _fallback("release", exc)
        with _mem_lock:
            _mem.pop(key, None)


# ─────────────────────────────────────────────────────────────────
# rate limit
# ─────────────────────────────────────────────────────────────────

def hit_rate(key, limit, window_seconds):
    """
    Sliding window: at most `limit` hits in the last `window_seconds`.
    Returns (allowed, wait_seconds). A refused hit is not counted.
    Same rule as the old in-memory limiter, but shared by all workers.
    """
    now_ts = time.time()
    now = _now()
    expires = now + timedelta(seconds=window_seconds)
    t = _table()
    try:
        with db.engine.begin() as conn:
            # make sure the row exists, then lock it for this read-modify-write
            conn.execute(
                _insert().values(key=key, value=[], expires_at=expires, updated_at=now)
                .on_conflict_do_nothing(index_elements=["key"])
            )
            query = select(t.c.value).where(t.c.key == key)
            if conn.dialect.name == "postgresql":
                query = query.with_for_update()
            hits = conn.execute(query).scalar() or []
            hits = [h for h in hits if now_ts - h < window_seconds]
            if len(hits) >= limit:
                allowed, wait = False, int(window_seconds - (now_ts - hits[0])) + 1
            else:
                hits.append(now_ts)
                allowed, wait = True, 0
            conn.execute(update(t).where(t.c.key == key).values(value=hits, expires_at=expires, updated_at=now))
        return allowed, wait
    except SQLAlchemyError as exc:
        _fallback("hit_rate", exc)
        with _mem_lock:
            item = _mem_get(key, now)
            hits = [h for h in (item[0] if item else []) if now_ts - h < window_seconds]
            if len(hits) >= limit:
                _mem[key] = (hits, expires)
                return False, int(window_seconds - (now_ts - hits[0])) + 1
            hits.append(now_ts)
            _mem[key] = (hits, expires)
            return True, 0


# ─────────────────────────────────────────────────────────────────
# housekeeping
# ─────────────────────────────────────────────────────────────────

def purge_expired():
    """Delete expired rows. Returns how many were deleted (0 when unavailable)."""
    t = _table()
    try:
        with db.engine.begin() as conn:
            return conn.execute(delete(t).where(t.c.expires_at <= _now())).rowcount or 0
    except SQLAlchemyError as exc:
        _fallback("purge_expired", exc)
        return 0
