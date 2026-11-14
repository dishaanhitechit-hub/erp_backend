# gunicorn.conf.py — read automatically when gunicorn is started from this folder
# (the Procfile does: `gunicorn run:app --bind 0.0.0.0:$PORT`).
#
# Every value can be changed with an environment variable, without a code change.
#
# The defaults keep today's concurrency (1 worker, 1 thread, 30 s timeout).
#
# More workers are safe once the `runtime_store` table exists — OTP codes,
# password-reset tokens, the search rate limit and the scheduler "run once"
# markers are shared through it (Phase 2). Steps:
#   1. flask db upgrade            (creates runtime_store)
#   2. GUNICORN_WORKERS=8          (good start for the i7 / 32 GB server)
#   3. optional: SCHEDULER_MODE=off here + `python scheduler_main.py`
#      as its own service, so the web workers only serve requests.
# If step 1 is skipped, the app logs "runtime_store unavailable" and falls
# back to per-worker memory — then keep GUNICORN_WORKERS=1.

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
# Restarting a worker after N requests protects against slow memory leaks.
# Safe after Phase 2 (nothing important lives in worker memory): e.g. 2000.
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
