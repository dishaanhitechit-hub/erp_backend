# app/logging_config.py
"""
Central logging for the backend.

* One handler on the root logger, writing to stdout (Gunicorn / systemd /
  Docker collect stdout). Every existing `logging.getLogger(__name__)` in the
  modules flows through it — before this, their INFO lines were not shown.
* Every request gets an ID: taken from the `X-Request-ID` header (set by
  Nginx or a client) or generated. It is returned in the `X-Request-ID`
  response header and added to every log line written during the request,
  so one request can be followed across modules.
* One line per request: method, route, status, duration, module (blueprint),
  user id.

Environment:
    LOG_LEVEL   DEBUG | INFO (default) | WARNING | ERROR
    LOG_FORMAT  json (default) | text  — text is easier to read locally

Nothing here reads request bodies, so passwords, amounts and bank details are
never logged. Routes are logged by their pattern (`/indent/<int:indent_id>`),
not the real path, so tokens inside URLs are not logged either.
"""

import json
import logging
import os
import re
import sys
import time
import uuid
from datetime import datetime, timezone

from flask import g, has_request_context, request

REQUEST_ID_HEADER = "X-Request-ID"
_VALID_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
_HANDLER_MARK = "_erp_log_handler"

# attributes every LogRecord has — anything else was passed with `extra=`
_STANDARD_ATTRS = set(vars(logging.LogRecord("", 0, "", 0, "", None, None))) | {"message", "asctime"}


# ─────────────────────────────────────────────────────────────────
# request context on every log line
# ─────────────────────────────────────────────────────────────────

def _current_user_id():
    """Logged-in user id for this request, or None. Never raises."""
    user = g.get("current_user")
    if isinstance(user, dict) and user.get("id") is not None:
        return user.get("id")
    try:  # routes protected by @jwt_required() instead of @login_required
        from flask_jwt_extended import get_jwt_identity
        return get_jwt_identity()
    except Exception:
        return None


def _route():
    """The route pattern (`/resource/indent/<int:indent_id>`), or the path when no route matched."""
    rule = getattr(request, "url_rule", None)
    return rule.rule if rule is not None else request.path


class RequestContextFilter(logging.Filter):
    """Adds request_id / module / user_id to records written during a request."""

    def filter(self, record):
        if has_request_context():
            record.request_id = g.get("request_id")
            record.module_name = request.blueprint or "-"
            record.user_id = _current_user_id()
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record):
        out = {
            "time": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key, value in vars(record).items():
            if key not in _STANDARD_ATTRS and not key.startswith("_") and value is not None:
                out[key] = value
        if record.exc_info:
            out["exception"] = self.formatException(record.exc_info)
        return json.dumps(out, default=str, ensure_ascii=False)


class TextFormatter(logging.Formatter):
    def __init__(self):
        super().__init__("%(asctime)s %(levelname)-7s %(name)s [%(request_id)s] %(message)s")

    def format(self, record):
        if not hasattr(record, "request_id"):
            record.request_id = "-"
        return super().format(record)


# ─────────────────────────────────────────────────────────────────
# setup
# ─────────────────────────────────────────────────────────────────

def configure_logging():
    """Install the stdout handler on the root logger (once per process)."""
    root = logging.getLogger()
    if any(getattr(h, _HANDLER_MARK, False) for h in root.handlers):
        return  # already done (create_app called twice, e.g. in tests)

    level = getattr(logging, (os.getenv("LOG_LEVEL") or "INFO").upper(), logging.INFO)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(TextFormatter() if (os.getenv("LOG_FORMAT") or "json").lower() == "text" else JsonFormatter())
    handler.addFilter(RequestContextFilter())
    setattr(handler, _HANDLER_MARK, True)

    root.addHandler(handler)
    root.setLevel(level)
    # chatty libraries: keep their warnings, drop their info lines
    for name in ("werkzeug", "urllib3", "apscheduler", "PIL", "fontTools", "xhtml2pdf"):
        logging.getLogger(name).setLevel(max(level, logging.WARNING))


request_logger = logging.getLogger("erp.request")


def register_request_logging(app):
    """Request id + one log line per request."""

    @app.before_request
    def _start_request():
        incoming = request.headers.get(REQUEST_ID_HEADER, "")
        g.request_id = incoming if _VALID_REQUEST_ID.match(incoming) else uuid.uuid4().hex
        g.request_started = time.perf_counter()

    @app.after_request
    def _finish_request(response):
        request_id = g.get("request_id")
        if request_id:
            response.headers[REQUEST_ID_HEADER] = request_id
        started = g.get("request_started")
        duration_ms = round((time.perf_counter() - started) * 1000, 1) if started else None
        status = response.status_code
        level = logging.ERROR if status >= 500 else logging.WARNING if status >= 400 else logging.INFO
        if request.method == "OPTIONS":  # CORS pre-flight: noise
            level = logging.DEBUG
        request_logger.log(
            level,
            "%s %s %s",
            request.method, _route(), status,
            extra={"method": request.method, "route": _route(), "status": status, "duration_ms": duration_ms},
        )
        return response
