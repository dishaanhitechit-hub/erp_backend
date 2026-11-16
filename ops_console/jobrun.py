"""Runs one console job in its own process:  python -m ops_console.jobrun <job_dir>"""

import fcntl
import os
import sys
import traceback
from datetime import datetime

from erp_backup import config as backup_config
from erp_backup.util import BackupError

from . import config, jobs, ops
from .audit import notify_action, write_audit

LABELS = {
    "restore_db": "Database restored (not live yet)", "apply_media": "Missing files put back",
    "restore_file": "Single file restored", "switch_live": "LIVE ERP switched to another database",
    "switch_back": "LIVE ERP switched back", "drop_db": "Restored database deleted",
}


def main(job_dir):
    cfg = config.load()
    settings = backup_config.load()
    meta = jobs.read_meta(job_dir)
    meta.update(status="running", started=datetime.now().astimezone().isoformat(timespec="seconds"),
                pid=os.getpid())
    jobs.write_meta(job_dir, meta)

    lock_fd = os.open(os.path.join(cfg.data_dir, "job.lock"), os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        meta.update(status="failed", error="another job is running")
        jobs.write_meta(job_dir, meta)
        return 1

    try:
        ops.say(f"{meta['kind']} started by {meta['user']}")
        result = ops.JOBS[meta["kind"]](cfg, settings, meta.get("params") or {}, meta["user"], job_dir)
        meta.update(status="success", result=result)
    except BackupError as e:
        ops.say(f"FAILED: {e}")
        meta.update(status="failed", error=str(e))
    except Exception as e:
        traceback.print_exc()
        meta.update(status="failed", error=f"{type(e).__name__}: {e}")
    finally:
        meta["finished"] = datetime.now().astimezone().isoformat(timespec="seconds")
        jobs.write_meta(job_dir, meta)
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        os.close(lock_fd)

    write_audit(cfg, meta["user"], f"job {meta['kind']} {meta['status']}", "-",
                {"job": meta["id"], "params": meta.get("params"), "result": meta.get("result"),
                 "error": meta.get("error")})
    if meta["kind"] in LABELS:
        details = {"Job": meta["id"], "Result": meta["status"].upper()}
        details.update({k.replace("_", " ").capitalize(): v for k, v in (meta.get("params") or {}).items()})
        if meta.get("error"):
            details["Problem"] = meta["error"]
        notify_action(settings, LABELS[meta["kind"]] + ("" if meta["status"] == "success" else " — FAILED"),
                      meta["user"], details)
    return 0 if meta["status"] == "success" else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
