# app/error_handlers.py
"""
Last line of defence for errors no module handled.

Before this, an unhandled exception in any route returned Flask's HTML
"Internal Server Error" page and was not logged with any context. Now:

* the open database transaction is rolled back, so nothing half-written is
  committed later on the same worker (Flask-SQLAlchemy also removes the
  session at the end of every request);
* the full error is logged once, with the request id, module and user;
* the client gets the same JSON shape every endpoint already uses —
  {"message": ..., "data": []} — plus "requestId" so a user can quote it.
  Internal error text is never sent to the client.

HTTP errors (404 unknown route, 405 wrong method, 413 file too large…) get
the same JSON shape with their normal status code and headers.

What is NOT changed:
* errors a module already catches and answers itself (most services return
  res(str(e), [], 500)) — they never reach these handlers;
* login / token errors — Flask-JWT-Extended registers its own handlers for
  its exception classes, and Flask uses the most specific handler, so
  401 / 422 responses keep their current {"msg": ...} body.
"""

import logging

from flask import g, jsonify, request
from werkzeug.exceptions import HTTPException

logger = logging.getLogger("erp.errors")

GENERIC_MESSAGE = "Something went wrong. Please try again. If it keeps happening, report the reference number."


def _rollback():
    try:
        from app.extensions import db
        db.session.rollback()
    except Exception:  # the session itself may be broken; teardown will discard it
        logger.warning("Rollback after an error failed", exc_info=True)


def _body(message, status):
    payload = {"message": message, "data": []}
    if g.get("request_id"):
        payload["requestId"] = g.request_id
    return payload


def register_error_handlers(app):

    @app.errorhandler(HTTPException)
    def handle_http_exception(e):
        # keep the status code and headers (e.g. "Allow" on 405) of the original error
        response = e.get_response()
        response.data = jsonify(_body(e.description or e.name, e.code)).get_data()
        response.content_type = "application/json"
        if e.code is not None and e.code >= 500:
            _rollback()
            logger.error("HTTP %s on %s %s", e.code, request.method, request.path, exc_info=e)
        return response

    @app.errorhandler(Exception)
    def handle_unexpected_exception(e):
        _rollback()
        logger.exception(
            "Unhandled error in %s %s", request.method, request.path,
            extra={"error_type": type(e).__name__},
        )
        return jsonify(_body(GENERIC_MESSAGE, 500)), 500
