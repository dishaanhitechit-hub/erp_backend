import fcntl
import hashlib
import json
import logging
import os
import shutil
import subprocess

log = logging.getLogger("erp_backup")

# set names live in naming.py; kept here for older imports
from .naming import parse_set_id, set_id_for  # noqa: E402,F401


class BackupError(Exception):
    """A step failed; the message is safe to put in an alert e-mail."""


def low_priority_prefix():
    """nice/ionice so a backup never slows the ERP for users (Linux)."""
    prefix = []
    if shutil.which("ionice"):
        prefix += ["ionice", "-c2", "-n7"]
    if shutil.which("nice"):
        prefix += ["nice", "-n", "10"]
    return prefix


def run(cmd, env=None, timeout=None, low_priority=True, capture=False):
    """Run a command; raise BackupError with the end of stderr on failure."""
    full = (low_priority_prefix() if low_priority else []) + list(cmd)
    log.info("run: %s", " ".join(_redact(full)))
    proc = subprocess.run(full, env=env, timeout=timeout,
                          stdout=subprocess.PIPE if capture else subprocess.DEVNULL,
                          stderr=subprocess.PIPE, text=True)
    if proc.returncode != 0:
        tail = (proc.stderr or "").strip()[-1500:]
        raise BackupError(f"{os.path.basename(cmd[0])} failed (exit {proc.returncode}): {tail}")
    return proc.stdout if capture else None


def _redact(args):
    return ["***" if "pass" in a.lower() and "=" in a else a for a in args]


def sha256_file(path, chunk=4 * 1024 * 1024):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def write_json_atomic(path, data):
    tmp = f"{path}.tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2, default=str)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def human_bytes(n):
    n = float(n or 0)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024


def dir_size(path):
    total = 0
    for root, _dirs, files in os.walk(path):
        for name in files:
            try:
                total += os.lstat(os.path.join(root, name)).st_size
            except OSError:
                pass
    return total


class Lock:
    """Only one backup process at a time (non-blocking flock)."""

    def __init__(self, path):
        self.path = path
        self.fd = None

    def acquire(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        self.fd = os.open(self.path, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            os.close(self.fd)
            self.fd = None
            return False
        os.ftruncate(self.fd, 0)
        os.write(self.fd, str(os.getpid()).encode())
        return True

    def release(self):
        if self.fd is not None:
            fcntl.flock(self.fd, fcntl.LOCK_UN)
            os.close(self.fd)
            self.fd = None

    def __enter__(self):
        return self.acquire()

    def __exit__(self, *exc):
        self.release()
