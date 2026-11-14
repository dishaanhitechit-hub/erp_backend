# app/health.py
"""
Health checks.

    GET /health/live     the process answers (no database). For Gunicorn /
                         systemd / Docker restarts and uptime monitors.
    GET /health/ready    the database answers. 503 when it does not — a load
                         balancer or Nginx should stop sending traffic here.
    GET /health/modules  admin only: outside-service breakers, error counts
                         per module (blueprint), background pool, scheduler,
                         runtime_store. All numbers are for THIS worker
                         process (the response says which pid).

live and ready return no data about the business, so they need no login.
"""

import os
import threading
import time

from flask import Blueprint, jsonify, request
from sqlalchemy import text

from app.extensions import db

health_bp = Blueprint("health", __name__)

_STARTED = time.time()

# per-module request / error counters for this process
_stats_lock = threading.Lock()
_module_stats = {}  # blueprint → {"requests", "errors5xx", "lastErrorAt", "lastErrorRoute"}


def record_request(module, status, route):
    """Called for every request by app/logging_config.py."""
    module = module or "-"
    with _stats_lock:
        s = _module_stats.setdefault(module, {"requests": 0, "errors5xx": 0, "lastErrorAt": None, "lastErrorRoute": None})
        s["requests"] += 1
        if status >= 500:
            s["errors5xx"] += 1
            s["lastErrorAt"] = time.time()
            s["lastErrorRoute"] = route


@health_bp.route("/live", methods=["GET"])
def live():
    return jsonify({"status": "ok", "pid": os.getpid()}), 200


def _check_database():
    started = time.perf_counter()
    try:
        db.session.execute(text("SELECT 1"))
        db.session.rollback()
        return {"ok": True, "ms": round((time.perf_counter() - started) * 1000, 1)}
    except Exception as exc:
        db.session.rollback()
        return {"ok": False, "error": type(exc).__name__}


@health_bp.route("/ready", methods=["GET"])
def ready():
    database = _check_database()
    status = 200 if database["ok"] else 503
    return jsonify({"status": "ok" if database["ok"] else "unavailable", "database": database, "pid": os.getpid()}), status


def _runtime_store_status():
    try:
        db.session.execute(text("SELECT 1 FROM runtime_store LIMIT 1"))
        db.session.rollback()
        return {"ok": True}
    except Exception as exc:
        db.session.rollback()
        return {"ok": False, "error": type(exc).__name__, "hint": "run `flask db upgrade`"}


@health_bp.route("/modules", methods=["GET"])
def modules():
    from flask_jwt_extended import get_jwt, verify_jwt_in_request

    verify_jwt_in_request()
    if get_jwt().get("role") not in ("admin", "super_admin"):
        return jsonify({"message": "Access denied", "data": []}), 403

    from app import scheduler as sch
    from app.utils import background
    from app.utils.resilience import all_breakers

    with _stats_lock:
        modules_ = [
            {"module": name, **values}
            for name, values in sorted(_module_stats.items(), key=lambda kv: (-kv[1]["errors5xx"], kv[0]))
        ]
    breakers = all_breakers()
    database = _check_database()
    return jsonify({
        "message": "Health",
        "data": {
            "pid": os.getpid(),
            "uptimeSeconds": round(time.time() - _STARTED),
            "database": database,
            "runtimeStore": _runtime_store_status(),
            "scheduler": {
                "mode": sch._scheduler_mode(),
                "runningInThisProcess": sch._started is not None and sch._started.running,
            },
            "backgroundPool": background.stats(),
            "services": breakers,
            "modules": modules_,
            "degraded": (not database["ok"]) or any(b["state"] != "closed" for b in breakers),
        },
    }), 200
