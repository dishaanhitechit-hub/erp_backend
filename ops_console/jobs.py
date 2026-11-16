"""Background jobs. Each job is a folder  <data_dir>/jobs/<id>/  with
meta.json + output.log, run by a detached process (`python -m
ops_console.jobrun <dir>`), so a long restore keeps going even if the
console restarts. Only one job runs at a time (job.lock)."""

import json
import os
import secrets
import subprocess
import sys
from datetime import datetime

DANGEROUS = {"restore_db", "apply_media", "restore_file", "switch_live", "switch_back", "drop_db"}
KINDS = DANGEROUS | {"backup_now", "verify", "refresh_remote"}


def _now():
    return datetime.now().astimezone().isoformat(timespec="seconds")


def write_meta(job_dir, meta):
    tmp = os.path.join(job_dir, "meta.json.tmp")
    with open(tmp, "w") as f:
        json.dump(meta, f, indent=2, default=str)
    os.replace(tmp, os.path.join(job_dir, "meta.json"))


def read_meta(job_dir):
    with open(os.path.join(job_dir, "meta.json")) as f:
        meta = json.load(f)
    if meta.get("status") in ("queued", "running") and meta.get("pid") and not _alive(meta["pid"]):
        meta["status"] = "interrupted"
        meta["error"] = meta.get("error") or "the job process stopped unexpectedly"
    return meta


def _alive(pid):
    try:
        os.kill(int(pid), 0)
        return True
    except (OSError, ValueError):
        return False


def busy(cfg):
    """meta of the running job, or None."""
    for meta in list_jobs(cfg, limit=20):
        if meta["status"] in ("queued", "running"):
            return meta
    return None


def start(cfg, kind, params, user):
    if kind not in KINDS:
        raise ValueError(f"unknown job type {kind}")
    running = busy(cfg)
    if running:
        raise RuntimeError(f"another job is running ({running['kind']} by {running['user']})")
    job_id = datetime.now().strftime("%Y%m%d-%H%M%S-") + secrets.token_hex(3)
    job_dir = os.path.join(cfg.jobs_dir, job_id)
    os.makedirs(job_dir, mode=0o700)
    meta = {"id": job_id, "kind": kind, "params": params, "user": user,
            "status": "queued", "created": _now()}
    write_meta(job_dir, meta)
    out = open(os.path.join(job_dir, "output.log"), "ab")
    proc = subprocess.Popen([sys.executable, "-m", "ops_console.jobrun", job_dir],
                            cwd=cfg.backend_dir, stdout=out, stderr=subprocess.STDOUT,
                            stdin=subprocess.DEVNULL, start_new_session=True)
    out.close()
    meta["pid"] = proc.pid
    write_meta(job_dir, meta)
    return meta


def list_jobs(cfg, limit=50):
    if not os.path.isdir(cfg.jobs_dir):
        return []
    out = []
    for name in sorted(os.listdir(cfg.jobs_dir), reverse=True)[:limit]:
        try:
            out.append(read_meta(os.path.join(cfg.jobs_dir, name)))
        except (OSError, ValueError):
            continue
    return out


def job_dir(cfg, job_id):
    if not job_id.replace("-", "").isalnum():
        raise ValueError("bad job id")
    path = os.path.join(cfg.jobs_dir, job_id)
    if not os.path.isdir(path):
        raise FileNotFoundError(job_id)
    return path


def output(cfg, job_id, offset=0):
    path = os.path.join(job_dir(cfg, job_id), "output.log")
    with open(path, "rb") as f:
        f.seek(offset)
        data = f.read(256 * 1024)
    return data.decode(errors="replace"), offset + len(data)
