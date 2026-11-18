"""/drive-bridge — the ERP side of Edox Drive.

For the ERP website (signed-in ERP user):
    GET  /status                  is my ERP account linked to Drive?
    POST /connect/start           URL of Drive's Connect page (signed, 10 minutes)
    POST /connect/finish          finish linking with the code Drive gave back
    GET  /browse                  folders and files in my Drive (for "Pick from Edox Drive")
    GET  /file/<id>               a Drive file's bytes (the picked file goes into the normal upload)
    POST /save                    copy an ERP attachment into a Drive folder ("Save to Edox Drive")
For Edox Drive's server (shared secret):
    GET  /tree, /check            ERP documents a person may see

Nothing here changes how the ERP stores or uploads files.
"""

import hmac
import os
from functools import wraps

from flask import Blueprint, Response, jsonify, request, stream_with_context
from flask_jwt_extended import get_jwt_identity, jwt_required

from app.modules.drive_bridge import documents
from app.modules.drive_bridge import drive_client as drive
from app.response import res

drive_bridge_bp = Blueprint("drive_bridge", __name__)


def _fail(e):
    return res(e.message, {"code": e.code}, e.status if 400 <= e.status < 600 else 502)


def _me():
    from app.models.user import User
    uid = int(get_jwt_identity())
    return uid, User.query.get(uid)


def handles_drive_errors(fn):
    @wraps(fn)
    def wrapper(*a, **kw):
        try:
            return fn(*a, **kw)
        except drive.DriveError as e:
            return _fail(e)
    return wrapper


# ══ for the ERP website ═══════════════════════════════════════════
@drive_bridge_bp.route("/status", methods=["GET"])
@jwt_required()
@handles_drive_errors
def status():
    if not drive.enabled():
        return res("", {"enabled": False, "linked": False})
    uid, _ = _me()
    data = drive.call("GET", "/api/erp/status", uid)
    return res("", {"enabled": True, **data})


@drive_bridge_bp.route("/connect/start", methods=["POST"])
@jwt_required()
@handles_drive_errors
def connect_start():
    if not drive.enabled():
        raise drive.DriveError("Edox Drive is not set up for this ERP.", 409, "drive_off")
    uid, user = _me()
    req = drive.connect_request(uid, getattr(user, "username", ""), getattr(user, "email", ""))
    from urllib.parse import quote
    return res("", {"url": f"{drive.public_url()}/connect?req={quote(req)}"})


@drive_bridge_bp.route("/connect/finish", methods=["POST"])
@jwt_required()
@handles_drive_errors
def connect_finish():
    uid, _ = _me()
    code = (request.get_json(silent=True) or {}).get("code", "")
    data = drive.call("POST", "/api/erp/links/confirm", None, json={"code": code, "erp_user_id": str(uid)})
    return res("Connected to Edox Drive", data)


# Only these Drive lists can be read through the ERP (all read-only).
@drive_bridge_bp.route("/browse", methods=["GET"])
@jwt_required()
@handles_drive_errors
def browse():
    uid, _ = _me()
    folder, q, view = request.args.get("folder"), request.args.get("q"), request.args.get("view")
    if q:
        return res("", drive.call("GET", "/api/search", uid, params={"q": q[:200]}))
    if view in ("recent", "starred", "shared-with-me", "drives"):
        return res("", drive.call("GET", f"/api/{view}", uid))
    if folder:
        _check_id(folder)
        node = drive.call("GET", f"/api/nodes/{folder}", uid)
        kids = drive.call("GET", f"/api/nodes/{folder}/children", uid)
        return res("", {**node, "items": kids["items"]})
    me = drive.call("GET", "/api/auth/me", uid)
    return res("", {"root_id": me["user"]["root_id"], "user": me["user"]})


def _check_id(value):
    import uuid
    try:
        uuid.UUID(str(value))
    except ValueError:
        raise drive.DriveError("Bad item id.", 400, "bad_id")


@drive_bridge_bp.route("/file/<node_id>", methods=["GET"])
@jwt_required()
@handles_drive_errors
def file(node_id):
    uid, _ = _me()
    _check_id(node_id)
    r = drive.call("GET", f"/api/nodes/{node_id}/content", uid, stream=True)
    headers = {k: r.headers[k] for k in ("Content-Disposition", "Content-Length") if k in r.headers}
    headers["Cache-Control"] = "private, no-store"
    headers["X-Content-Type-Options"] = "nosniff"
    return Response(stream_with_context(r.iter_content(64 * 1024)), status=200,
                    content_type="application/octet-stream", headers=headers)


@drive_bridge_bp.route("/save", methods=["POST"])
@jwt_required()
@handles_drive_errors
def save():
    """Copy an ERP attachment (by its normal file URL) into a Drive folder."""
    from app.cloudinary_uploader import local_path_from_url
    uid, _ = _me()
    body = request.get_json(silent=True) or {}
    folder = body.get("folder_id")
    _check_id(folder)
    path = local_path_from_url(body.get("url") or "")
    if not path or not os.path.isfile(path):
        return res("That file isn't stored on this server.", [], 404)
    name = (body.get("name") or os.path.basename(path)).replace("/", "-").strip()[:255] or os.path.basename(path)
    node = drive.upload(uid, folder, name, path)
    return res("Saved to Edox Drive", {"node": node})


# ══ for Edox Drive's server ═══════════════════════════════════════
def drive_server_only(fn):
    @wraps(fn)
    def wrapper(*a, **kw):
        given = request.headers.get("X-Drive-Secret", "")
        if not drive.secret() or len(drive.secret()) < 32 or not hmac.compare_digest(given, drive.secret()):
            return jsonify({"message": "Not allowed."}), 403
        try:
            return fn(*a, **kw)
        except documents.Denied as e:
            return jsonify({"message": str(e)}), 404
    return wrapper


@drive_bridge_bp.route("/tree", methods=["GET"])
@drive_server_only
def tree():
    return jsonify(documents.tree(request.args.get("user", "0"), request.args.get("path", "")))


@drive_bridge_bp.route("/check", methods=["GET"])
@drive_server_only
def check():
    return jsonify(documents.check(request.args.get("user", "0"), request.args.get("path", "")))
