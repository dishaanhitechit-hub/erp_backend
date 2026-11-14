# app/utils/background.py
"""
One bounded pool of background threads per process, for fire-and-forget work
such as WhatsApp messages, OTPs and push notifications.

Before this, every message started a brand-new thread, with no upper limit.
A burst of approvals (or a slow WhatsApp API) could pile up hundreds of
threads in one worker.

    run_in_background(fn, *args, **kwargs)

* runs `fn` on the pool, inside the Flask app context (so `db` works) when
  called from a request, a CLI command or a scheduler job;
* at most BACKGROUND_THREADS run at once (default 8); at most
  BACKGROUND_QUEUE_LIMIT wait (default 500). When the queue is full the task
  runs right away in the caller instead — slower for that one request, but no
  message is ever dropped;
* errors are logged, never raised to the caller;
* the database session used by the task is removed when it finishes.

The pool is created on first use, so each Gunicorn worker gets its own after
the fork.
"""

import logging
import os
import threading
from concurrent.futures import ThreadPoolExecutor

log = logging.getLogger(__name__)

_MAX_THREADS = max(1, int(os.getenv("BACKGROUND_THREADS") or 8))
_QUEUE_LIMIT = max(1, int(os.getenv("BACKGROUND_QUEUE_LIMIT") or 500))

_pool = None
_pool_lock = threading.Lock()
_slots = threading.BoundedSemaphore(_MAX_THREADS + _QUEUE_LIMIT)


def _get_pool():
    global _pool
    if _pool is None:
        with _pool_lock:
            if _pool is None:
                _pool = ThreadPoolExecutor(max_workers=_MAX_THREADS, thread_name_prefix="erp-bg")
    return _pool


def _current_app():
    try:
        from flask import current_app
        return current_app._get_current_object()
    except RuntimeError:  # no app context
        return None


def _run(app, fn, args, kwargs):
    name = getattr(fn, "__qualname__", repr(fn))
    try:
        if app is None:
            fn(*args, **kwargs)
            return
        with app.app_context():
            try:
                fn(*args, **kwargs)
            finally:
                try:
                    from app.extensions import db
                    db.session.remove()
                except Exception:
                    pass
    except Exception:
        log.exception("Background task %s failed", name)


_waiting_or_running = 0
_count_lock = threading.Lock()
_ran_inline = 0


def stats():
    """Numbers for /health/modules (this process)."""
    return {
        "threads": _MAX_THREADS,
        "queueLimit": _QUEUE_LIMIT,
        "waitingOrRunning": _waiting_or_running,
        "ranInlineBecauseFull": _ran_inline,
    }


def _adjust(delta):
    global _waiting_or_running
    with _count_lock:
        _waiting_or_running += delta


def run_in_background(fn, *args, **kwargs):
    """Queue `fn(*args, **kwargs)`; never raises."""
    global _ran_inline
    app = _current_app()
    if not _slots.acquire(blocking=False):
        _ran_inline += 1
        log.warning(
            "Background queue full (%s waiting) — running %s in the request instead",
            _QUEUE_LIMIT, getattr(fn, "__qualname__", repr(fn)),
        )
        _run(app, fn, args, kwargs)
        return

    def task():
        try:
            _run(app, fn, args, kwargs)
        finally:
            _adjust(-1)
            _slots.release()

    _adjust(+1)
    try:
        _get_pool().submit(task)
    except RuntimeError:  # pool shut down (process exiting)
        _adjust(-1)
        _slots.release()
        _run(app, fn, args, kwargs)
