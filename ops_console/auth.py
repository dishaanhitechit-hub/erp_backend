"""Console users (separate from ERP users), stored as password hashes in a
JSON file. Brute-force protection: 5 wrong passwords → 15 minutes locked."""

import json
import os
import re
import threading
import time
from datetime import datetime

from werkzeug.security import check_password_hash, generate_password_hash

MAX_FAILS = 5
LOCK_SECONDS = 15 * 60
MIN_PASSWORD = 12

_fails = {}
_fails_lock = threading.Lock()
# compared against when the user does not exist, so timing does not reveal names
_DUMMY_HASH = generate_password_hash("not-a-real-password-0000")


def _read(path):
    try:
        with open(path) as f:
            return json.load(f)
    except (FileNotFoundError, ValueError):
        return {"users": {}}


def _write(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2)
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)


def set_password(path, username, password):
    username = username.strip().lower()
    if not re.fullmatch(r"[a-z0-9._-]{2,40}", username):
        raise ValueError("username: 2-40 letters, digits, . - _")
    if len(password) < MIN_PASSWORD:
        raise ValueError(f"password must be at least {MIN_PASSWORD} characters")
    data = _read(path)
    user = data["users"].get(username, {"created": datetime.now().isoformat(timespec="seconds")})
    user["hash"] = generate_password_hash(password)
    data["users"][username] = user
    _write(path, data)


def remove_user(path, username):
    data = _read(path)
    if data["users"].pop(username.strip().lower(), None) is None:
        raise ValueError("no such user")
    _write(path, data)


def list_users(path):
    return sorted(_read(path)["users"])


def locked_for(key):
    with _fails_lock:
        entry = _fails.get(key)
        if entry and entry["count"] >= MAX_FAILS:
            left = entry["until"] - time.time()
            if left > 0:
                return int(left)
            _fails.pop(key, None)
    return 0


def check(path, username, password, client_ip):
    """(ok: bool, message). Counts failures per username+IP."""
    username = (username or "").strip().lower()
    key = f"{username}|{client_ip}"
    wait = locked_for(key)
    if wait:
        return False, f"Too many wrong passwords. Try again in {wait // 60 + 1} min."
    user = _read(path)["users"].get(username)
    ok = check_password_hash(user["hash"] if user else _DUMMY_HASH, password or "") and bool(user)
    with _fails_lock:
        if ok:
            _fails.pop(key, None)
        else:
            entry = _fails.setdefault(key, {"count": 0, "until": 0})
            entry["count"] += 1
            if entry["count"] >= MAX_FAILS:
                entry["until"] = time.time() + LOCK_SECONDS
    if ok:
        data = _read(path)
        data["users"][username]["last_login"] = datetime.now().isoformat(timespec="seconds")
        _write(path, data)
        return True, ""
    return False, "Wrong username or password."


def verify_password(path, username, password):
    """Re-check the logged-in user's password before a dangerous action."""
    user = _read(path)["users"].get((username or "").lower())
    return bool(user) and check_password_hash(user["hash"], password or "")
