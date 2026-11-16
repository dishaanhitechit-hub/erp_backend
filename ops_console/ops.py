"""What each background job does. Every function prints progress lines
(shown live in the console) and returns a small result dict."""

import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import time
import urllib.request
from datetime import datetime

from erp_backup import recovery, runner
from erp_backup.remote import Remote
from erp_backup.util import BackupError, parse_set_id, write_json_atomic

DB_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{2,62}$")


def say(msg):
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)


# ── ERP .env (DB_NAME) ──────────────────────────────────────────────────────

def read_env_value(path, key):
    with open(path) as f:
        for ln in f:
            m = re.match(rf"^\s*{re.escape(key)}\s*=\s*(.*?)\s*$", ln)
            if m:
                return m.group(1).strip().strip('"').strip("'")
    return None


def write_env_value(path, key, value):
    with open(path) as f:
        lines = f.readlines()
    done = False
    for i, ln in enumerate(lines):
        if re.match(rf"^\s*{re.escape(key)}\s*=", ln):
            lines[i] = f"{key}={value}\n"
            done = True
    if not done:
        lines.append(f"{key}={value}\n")
    tmp = path + ".console-tmp"
    with open(tmp, "w") as f:
        f.writelines(lines)
    shutil.copymode(path, tmp)
    os.replace(tmp, path)


def live_db(cfg):
    return read_env_value(cfg.erp_env_file, "DB_NAME")


# ── helpers ─────────────────────────────────────────────────────────────────

def _stream(cmd, cwd):
    """Run a command, echo its output live, return (exit code, full output)."""
    say("$ " + " ".join(cmd[2:] if cmd[:2] == [sys.executable, "-m"] else cmd))
    proc = subprocess.Popen(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    out = []
    for ln in proc.stdout:
        out.append(ln)
        print(ln.rstrip(), flush=True)
    return proc.wait(), "".join(out)


def _erp_backup(cfg, *args):
    return _stream([sys.executable, "-m", "erp_backup", "-v", *args], cfg.backend_dir)


def _load_json(path, default):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def _remember_db(cfg, name, set_id, user):
    data = _load_json(cfg.created_dbs_file, {})
    data[name] = {"created": datetime.now().astimezone().isoformat(timespec="seconds"),
                  "from_backup": set_id, "by": user}
    write_json_atomic(cfg.created_dbs_file, data)


def database_has_tables(settings, name):
    import psycopg2
    conn = psycopg2.connect(**settings.psycopg_kwargs(admin=True, dbname=name))
    try:
        cur = conn.cursor()
        cur.execute("SELECT count(*) FROM information_schema.tables WHERE table_schema='public'")
        return cur.fetchone()[0]
    finally:
        conn.close()


# ── jobs ────────────────────────────────────────────────────────────────────

def backup_now(cfg, settings, params, user, job_dir):
    code, _ = _erp_backup(cfg, "run")
    if code:
        raise BackupError("backup did not succeed — see the output above")
    return {"done": True}


def verify(cfg, settings, params, user, job_dir):
    args = ["verify"]
    if params.get("set"):
        args += ["--set", params["set"]]
    if params.get("from_remote"):
        args.append("--from-remote")
    code, _ = _erp_backup(cfg, *args)
    return {"passed": code == 0}


def refresh_remote(cfg, settings, params, user, job_dir):
    if not settings.remote:
        raise BackupError("Google Drive is not configured (BACKUP_REMOTE)")
    say("listing backups on Google Drive (can take a few minutes)…")
    names = sorted((n for n in Remote(settings).list_sets() if parse_set_id(n)), key=parse_set_id)
    runner.write_remote_cache(settings, names, datetime.now(settings.tz))
    say(f"{len(names)} backups on Google Drive")
    return {"count": len(names)}


def restore_db(cfg, settings, params, user, job_dir):
    set_id, target = params.get("set"), (params.get("target_db") or "").strip()
    if not parse_set_id(set_id or ""):
        raise BackupError("choose a backup")
    if not DB_NAME_RE.match(target):
        raise BackupError("database name: lowercase letters, digits and _ (start with a letter)")
    if target == live_db(cfg):
        raise BackupError("that is the LIVE database — choose a new name")
    args = ["restore", "--set", set_id, "--target-db", target]
    media_dir = None
    if params.get("with_media"):
        media_dir = os.path.join(cfg.staging_dir, os.path.basename(job_dir))
        args += ["--media-dir", media_dir]
    if params.get("from_remote"):
        args.append("--from-remote")
    code, out = _erp_backup(cfg, *args)
    if code:
        raise BackupError("restore failed — see the output above")
    _remember_db(cfg, target, set_id, user)
    summary = {}
    m = re.search(r"\{.*\}", out, re.S)
    if m:
        try:
            summary = json.loads(m.group(0))
        except ValueError:
            pass
    say(f"database {target} is ready. It is NOT live yet — check it, then use 'Switch live'.")
    return {"target_db": target, "backup": set_id, "media_staging": media_dir,
            "tables": summary.get("tables"), "row_mismatches": summary.get("row_mismatches")}


def apply_media(cfg, settings, params, user, job_dir):
    """Copy restored files into the live folders — ONLY files that are missing.
    Existing files are never overwritten or deleted."""
    staging = os.path.join(cfg.staging_dir, os.path.basename(params.get("staging") or ""))
    if not params.get("staging") or not os.path.isdir(staging):
        raise BackupError("no restored files found — run a restore with pictures first")
    copied = skipped = 0
    for src in settings.media_sources:
        root = os.path.join(staging, src.label)
        if not os.path.isdir(root):
            say(f"{src.label}: nothing restored")
            continue
        for dirpath, _dirs, files in os.walk(root):
            rel_dir = os.path.relpath(dirpath, root)
            for name in files:
                dest = os.path.normpath(os.path.join(src.path, rel_dir, name))
                if not dest.startswith(os.path.normpath(src.path) + os.sep):
                    continue
                if os.path.exists(dest):
                    skipped += 1
                    continue
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                shutil.copy2(os.path.join(dirpath, name), dest)
                copied += 1
                if copied <= 200:
                    say(f"put back: {src.label}/{os.path.join(rel_dir, name)}")
    say(f"done: {copied} missing file(s) put back, {skipped} already present (left untouched)")
    return {"copied": copied, "skipped_existing": skipped}


def restore_file(cfg, settings, params, user, job_dir):
    """One picture/document from a backup: saved for download, and optionally
    put back in its live folder if it is missing there."""
    set_id, member = params.get("set"), (params.get("path") or "").strip().lstrip("/")
    if not parse_set_id(set_id or "") or not member or ".." in member.split("/"):
        raise BackupError("choose a backup and a file")
    name, set_path = recovery.locate_set(settings, set_id, bool(params.get("from_remote")))
    manifest = recovery.backupset.load_manifest(set_path)
    archive = manifest["media"].get("archive")
    if not archive:
        raise BackupError("this backup was made in sync mode — files are in Google Drive media/current")
    out_dir = os.path.join(job_dir, "file")
    os.makedirs(out_dir)
    path = os.path.join(set_path, archive)
    say(f"searching {archive} for {member} …")
    found = None
    if archive.endswith(".zst"):
        proc = subprocess.Popen(["zstd", "-dcq", path], stdout=subprocess.PIPE)
        tar = tarfile.open(fileobj=proc.stdout, mode="r|")
    else:
        proc, tar = None, tarfile.open(path, mode="r|gz")
    with tar:
        for m in tar:
            if m.name == member and m.isfile():
                found = os.path.join(out_dir, os.path.basename(member))
                with tar.extractfile(m) as src, open(found, "wb") as dst:
                    shutil.copyfileobj(src, dst)
                os.utime(found, (m.mtime, m.mtime))
                break
    if proc:
        proc.kill()
        proc.wait()
    if not found:
        raise BackupError(f"{member} is not in backup {set_id}")
    say(f"found ({os.path.getsize(found)} bytes) — ready to download")
    result = {"file": os.path.basename(found), "member": member, "put_back": False}
    if params.get("put_back"):
        label, _, rel = member.partition("/")
        src = next((s for s in settings.media_sources if s.label == label), None)
        if not src:
            raise BackupError(f"unknown folder {label}")
        dest = os.path.normpath(os.path.join(src.path, rel))
        if not dest.startswith(src.path + os.sep):
            raise BackupError("bad path")
        if os.path.exists(dest):
            say("the file already exists in the live folder — NOT overwritten (download it instead)")
        else:
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            shutil.copy2(found, dest)
            result["put_back"] = True
            say(f"put back at {dest}")
    return result


def _health(cfg, timeout=90):
    """True when the ERP answers /health/ready with the database OK."""
    deadline = time.time() + timeout
    last = ""
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(cfg.health_url, timeout=5) as r:
                body = json.loads(r.read().decode() or "{}")
                if r.status == 200 and body.get("database", {}).get("ok", True):
                    return True, "ok"
                last = f"HTTP {r.status} {body}"
        except Exception as e:  # not up yet
            last = str(e)
        time.sleep(3)
    return False, last


def _service(cmd):
    say("$ " + " ".join(cmd))
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if proc.returncode != 0:
        raise BackupError(f"{' '.join(cmd)} failed: {(proc.stderr or proc.stdout).strip()[-400:]}")


def _switch(cfg, settings, target, user, reason, check_tables=True):
    current = live_db(cfg)
    if not current:
        raise BackupError(f"DB_NAME not found in {cfg.erp_env_file}")
    if target == current:
        raise BackupError(f"{target} is already live")
    if not DB_NAME_RE.match(target or ""):
        raise BackupError("bad database name")
    tables = database_has_tables(settings, target)
    if check_tables and tables < 10:
        raise BackupError(f"{target} has only {tables} tables — refusing to switch to it")
    if tables == 0:
        raise BackupError(f"{target} is empty — refusing to switch to it")
    say(f"{target}: {tables} tables — OK")

    backup_env = os.path.join(cfg.data_dir, "env-backups", f".env.{datetime.now():%Y%m%d-%H%M%S}")
    os.makedirs(os.path.dirname(backup_env), exist_ok=True)
    shutil.copy2(cfg.erp_env_file, backup_env)
    os.chmod(backup_env, 0o600)
    say(f"saved current settings to {backup_env}")

    say("stopping the ERP …")
    _service(cfg.stop_cmd)
    try:
        write_env_value(cfg.erp_env_file, "DB_NAME", target)
        say(f"DB_NAME: {current} → {target}")
        say("starting the ERP …")
        _service(cfg.start_cmd)
        ok, detail = _health(cfg)
        if not ok:
            raise BackupError(f"ERP did not become healthy on {target}: {detail}")
    except Exception as e:
        say(f"PROBLEM: {e}")
        say(f"rolling back to {current} …")
        shutil.copy2(backup_env, cfg.erp_env_file)
        try:
            _service(cfg.stop_cmd)
        except BackupError:
            pass
        _service(cfg.start_cmd)
        ok, _ = _health(cfg)
        say("rolled back — ERP is running on the old database" if ok
            else "ROLLBACK DONE BUT ERP IS NOT HEALTHY — check the server now")
        raise BackupError(f"switch failed and was rolled back: {e}")

    say(f"ERP is live on {target} and healthy ✔")
    hist = _load_json(cfg.switch_file, [])
    hist.append({"at": datetime.now().astimezone().isoformat(timespec="seconds"), "by": user,
                 "from": current, "to": target, "reason": reason})
    write_json_atomic(cfg.switch_file, hist[-100:])
    return {"from": current, "to": target}


def switch_live(cfg, settings, params, user, job_dir):
    return _switch(cfg, settings, (params.get("target_db") or "").strip(), user, "switch")


def switch_back(cfg, settings, params, user, job_dir):
    hist = _load_json(cfg.switch_file, [])
    if not hist:
        raise BackupError("no earlier switch to undo")
    last = hist[-1]
    if last["to"] != live_db(cfg):
        raise BackupError(f"live database is {live_db(cfg)}, not {last['to']} — switch back manually")
    # it was the live database a moment ago, so only check it still exists
    return _switch(cfg, settings, last["from"], user, "switch back", check_tables=False)


def drop_db(cfg, settings, params, user, job_dir):
    name = (params.get("name") or "").strip()
    created = _load_json(cfg.created_dbs_file, {})
    if name not in created:
        raise BackupError("only databases created by this console can be deleted here")
    if name == live_db(cfg):
        raise BackupError("that database is LIVE — it cannot be deleted")
    if any(h.get("from") == name for h in _load_json(cfg.switch_file, [])[-1:]):
        raise BackupError("that database is the 'switch back' target — keep it until you are sure")
    from erp_backup.recovery import _drop_db
    _drop_db(settings, name)
    created.pop(name, None)
    write_json_atomic(cfg.created_dbs_file, created)
    say(f"database {name} deleted")
    return {"dropped": name}


JOBS = {
    "backup_now": backup_now, "verify": verify, "refresh_remote": refresh_remote,
    "restore_db": restore_db, "apply_media": apply_media, "restore_file": restore_file,
    "switch_live": switch_live, "switch_back": switch_back, "drop_db": drop_db,
}
