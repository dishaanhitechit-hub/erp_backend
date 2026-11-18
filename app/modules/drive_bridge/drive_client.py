"""Calls from the ERP server to Edox Drive.

Settings (ERP .env):
    DRIVE_ERP_SECRET     same long random value as in Drive's drive.env
    DRIVE_INTERNAL_URL   Drive's API on this server, e.g. http://127.0.0.1:7001
    DRIVE_PUBLIC_URL     Drive's website, e.g. https://drive.example.com
    ERP_PUBLIC_URL       this ERP's website (where Drive sends people back)
"""

import base64
import hashlib
import hmac
import json
import os
import time

import requests

TIMEOUT = 30
PIECE = 8 * 1024 * 1024


class DriveError(Exception):
    def __init__(self, message, status=502, code=None):
        super().__init__(message)
        self.message, self.status, self.code = message, status, code


def secret():
    return os.getenv("DRIVE_ERP_SECRET", "")


def enabled():
    return len(secret()) >= 32 and bool(os.getenv("DRIVE_INTERNAL_URL")) and bool(os.getenv("DRIVE_PUBLIC_URL"))


def public_url():
    return (os.getenv("DRIVE_PUBLIC_URL") or "").rstrip("/")


def _url(path):
    return (os.getenv("DRIVE_INTERNAL_URL") or "").rstrip("/") + path


def headers(erp_user_id=None):
    h = {"Authorization": f"ErpClient {secret()}"}
    if erp_user_id is not None:
        h["X-Erp-User"] = str(erp_user_id)
    return h


def call(method, path, erp_user_id=None, **kw):
    if not enabled():
        raise DriveError("Edox Drive is not set up for this ERP.", 409, "drive_off")
    try:
        r = requests.request(method, _url(path), headers=headers(erp_user_id), timeout=TIMEOUT, **kw)
    except requests.RequestException:
        raise DriveError("Can't reach Edox Drive right now. Try again later.", 502, "drive_down")
    if kw.get("stream") and r.ok:
        return r
    try:
        data = r.json()
    except ValueError:
        data = {}
    if not r.ok:
        raise DriveError(data.get("error") or f"Edox Drive said no ({r.status_code}).", r.status_code, data.get("code"))
    return data


def connect_request(erp_user_id, name, email):
    """A signed request (10 minutes) for Drive's Connect page."""
    payload = {"u": str(erp_user_id), "n": name or "", "e": email or "", "x": int(time.time()) + 600,
               "r": (os.getenv("ERP_PUBLIC_URL") or "").rstrip("/") + "/drive/connected"}
    body = base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode()).decode().rstrip("=")
    mac = hmac.new(secret().encode(), body.encode(), hashlib.sha256).hexdigest()
    return f"{body}.{mac}"


def upload(erp_user_id, folder_id, name, path):
    """Send a file from this server to a Drive folder, in pieces."""
    size = os.path.getsize(path)
    up = call("POST", "/api/uploads", erp_user_id,
              json={"parent_id": folder_id, "relative_path": name, "size": size})
    offset = 0
    with open(path, "rb") as f:
        while offset < size:
            piece = f.read(min(PIECE, up.get("chunk_bytes") or PIECE))
            offset = _put(up["id"], offset, piece, erp_user_id)["received"]
    return call("POST", f"/api/uploads/{up['id']}/complete", erp_user_id)["node"]


def _put(upload_id, offset, piece, erp_user_id):
    try:
        r = requests.put(_url(f"/api/uploads/{upload_id}?offset={offset}"), data=piece,
                         headers={**headers(erp_user_id), "Content-Type": "application/octet-stream"},
                         timeout=TIMEOUT)
    except requests.RequestException:
        raise DriveError("Lost the connection to Edox Drive while sending the file.", 502, "drive_down")
    data = r.json() if r.content else {}
    if not r.ok:
        raise DriveError(data.get("error") or "Upload to Edox Drive failed.", r.status_code, data.get("code"))
    return data
