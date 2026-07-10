from flask import request, jsonify
from datetime import datetime, time

MAINTENANCE_SOFT_LOCK = time(23, 0)   # 11:00 PM — block new logins
MAINTENANCE_HARD_LOCK = time(23, 30)  # 11:30 PM — block all DB writes


def register_maintenance_middleware(app):

    @app.before_request
    def maintenance_guard():
        now = datetime.now().time()

        # HARD LOCK: 11:30 PM onwards — block all write operations
        # if now >= MAINTENANCE_HARD_LOCK:
        #     if request.method in ['POST', 'PUT', 'PATCH', 'DELETE']:
        #         return jsonify({
        #             "error": "maintenance",
        #             "message": "Server is going into maintenance. No changes allowed."
        #         }), 503

        # SOFT LOCK: 11:00 PM — block new logins only
        # elif now >= MAINTENANCE_SOFT_LOCK:
        #     if request.endpoint == 'auth.login':
        #         return jsonify({
        #             "error": "maintenance",
        #             "message": "Maintenance starts soon. Login disabled."
        #         }), 503
