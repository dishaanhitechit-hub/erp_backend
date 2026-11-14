# gunicorn.conf.py — read automatically when gunicorn is started from this folder
# (the Procfile does: `gunicorn run:app --bind 0.0.0.0:$PORT`).
#
# Every value can be changed with an environment variable, without a code change.
#
# PHASE 1 DEFAULTS KEEP TODAY'S CONCURRENCY (1 worker, 1 thread, 30 s timeout).
# Do NOT raise GUNICORN_WORKERS / WEB_CONCURRENCY or GUNICORN_THREADS until
# Phase 2 is done, because these still live inside each worker process:
#   * the APScheduler jobs — the monthly email report has no lock and would be
#     sent once per worker;
#   * the OTP store (auth/otp_store.py) and password-reset tokens
#     (auth/service.py) — a code made on one worker is unknown to another;
#   * the search rate limiter.
# After Phase 2: GUNICORN_WORKERS=8 is a good start on the i7 / 32 GB server.

import os


def _int(name, default):
    try:
        return int(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


# ── processes ───────────────────────────────────────────────────────
workers = _int("GUNICORN_WORKERS", _int("WEB_CONCURRENCY", 1))
threads = _int("GUNICORN_THREADS", 1)            # > 1 switches to the gthread worker
worker_class = "gthread" if threads > 1 else "sync"

# ── time limits ─────────────────────────────────────────────────────
# A request running longer than this is killed and its worker restarted
# (same 30 s as Gunicorn's own default today).
timeout = _int("GUNICORN_TIMEOUT", 30)
# On reload / shutdown, running requests get this long to finish.
graceful_timeout = _int("GUNICORN_GRACEFUL_TIMEOUT", 30)
# Keep idle client connections (Nginx) open this long.
keepalive = _int("GUNICORN_KEEPALIVE", 5)

# ── worker recycling (off by default) ───────────────────────────────
# Restarting a worker after N requests protects against slow memory leaks,
# but also wipes the in-memory OTP / reset tokens — leave at 0 until Phase 2.
max_requests = _int("GUNICORN_MAX_REQUESTS", 0)
max_requests_jitter = _int("GUNICORN_MAX_REQUESTS_JITTER", 50 if max_requests else 0)

# ── misc ────────────────────────────────────────────────────────────
# Heartbeat files in RAM: avoids false worker timeouts on a slow disk.
worker_tmp_dir = "/dev/shm" if os.path.isdir("/dev/shm") else None
# Trust X-Forwarded-* only from the local reverse proxy.
forwarded_allow_ips = os.getenv("GUNICORN_FORWARDED_ALLOW_IPS", "127.0.0.1")

# ── logs ────────────────────────────────────────────────────────────
# The app writes one JSON line per request (app/logging_config.py), so the
# Gunicorn access log stays off; Gunicorn's own messages go to stderr.
accesslog = None
errorlog = "-"
loglevel = os.getenv("GUNICORN_LOG_LEVEL", "info")
