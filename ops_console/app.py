"""Flask app for the PRAX Ops Console."""

import gzip
import json
import os
import re
import shutil
import time
from datetime import datetime, timedelta
from functools import wraps

from flask import Flask, abort, jsonify, redirect, render_template, request, send_file, session

from erp_backup import __version__ as BACKUP_VERSION
from erp_backup import backupset, schedule
from erp_backup import config as backup_config
from erp_backup import state as backup_state
from erp_backup.runner import local_sets
from erp_backup.util import parse_set_id
from prax_ops import recipients

from . import __version__, auth, config, jobs, ops
from .audit import read_audit, write_audit

CSRF_HEADER = "X-Prax-Console"


def create_app(cfg=None):
    cfg = cfg or config.load()
    os.makedirs(cfg.data_dir, mode=0o700, exist_ok=True)
    app = Flask(__name__)
    app.config.update(
        SECRET_KEY=cfg.secret_key,
        SESSION_COOKIE_NAME="prax_console",
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Strict",
        SESSION_COOKIE_SECURE=cfg.cookie_secure,
        PERMANENT_SESSION_LIFETIME=timedelta(minutes=cfg.session_minutes),
        MAX_CONTENT_LENGTH=1024 * 1024,
    )
    app.config["CONSOLE"] = cfg

    def settings():
        return backup_config.load()

    def client_ip():
        return request.headers.get("X-Real-IP") or request.remote_addr or "-"

    # ── security ────────────────────────────────────────────────────────────
    @app.after_request
    def headers(resp):
        resp.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
            "frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["X-Frame-Options"] = "DENY"
        resp.headers["Referrer-Policy"] = "no-referrer"
        resp.headers["Cache-Control"] = "no-store"
        return resp

    @app.before_request
    def guard():
        if request.method not in ("GET", "HEAD") and request.headers.get(CSRF_HEADER) != "1":
            abort(400, "missing console header")
        if session.get("user"):
            last = session.get("seen", 0)
            if time.time() - last > cfg.session_minutes * 60:
                session.clear()
            else:
                session["seen"] = time.time()
                session.permanent = True

    def login_required(fn):
        @wraps(fn)
        def wrapper(*a, **kw):
            if not session.get("user"):
                if request.path.startswith("/api/"):
                    return jsonify(error="login required"), 401
                return redirect("login")
            return fn(*a, **kw)
        return wrapper

    @app.errorhandler(400)
    @app.errorhandler(404)
    @app.errorhandler(413)
    def http_error(e):
        return jsonify(error=getattr(e, "description", str(e))), e.code

    # ── pages ───────────────────────────────────────────────────────────────
    @app.get("/login")
    def login_page():
        return render_template("login.html", version=__version__)

    @app.get("/")
    @login_required
    def index():
        return render_template("index.html", version=__version__, user=session["user"])

    # ── auth ────────────────────────────────────────────────────────────────
    @app.post("/api/login")
    def login():
        body = request.get_json(silent=True) or {}
        ok, msg = auth.check(cfg.users_file, body.get("username"), body.get("password"), client_ip())
        write_audit(cfg, (body.get("username") or "?")[:40], "login " + ("ok" if ok else "FAILED"), client_ip())
        if not ok:
            time.sleep(1)
            return jsonify(error=msg), 401
        session.clear()
        session["user"] = body["username"].strip().lower()
        session["seen"] = time.time()
        session.permanent = True
        return jsonify(ok=True)

    @app.post("/api/logout")
    def logout():
        if session.get("user"):
            write_audit(cfg, session["user"], "logout", client_ip())
        session.clear()
        return jsonify(ok=True)

    @app.get("/api/me")
    @login_required
    def me():
        return jsonify(user=session["user"], version=__version__, backup_version=BACKUP_VERSION,
                       session_minutes=cfg.session_minutes)

    def require_password(body):
        if not auth.verify_password(cfg.users_file, session["user"], body.get("password")):
            write_audit(cfg, session["user"], "password re-check FAILED", client_ip())
            abort(403)

    @app.errorhandler(403)
    def forbidden(e):
        return jsonify(error="Wrong password."), 403

    # ── backups: overview, runs, logs ───────────────────────────────────────
    @app.get("/api/overview")
    @login_required
    def overview():
        s = settings()
        st = backup_state.load(s)
        now = datetime.now(s.tz)
        hist = st.get("history", [])

        def counts(days):
            cut = now - timedelta(days=days)
            sel = [h for h in hist if h.get("started_at") and datetime.fromisoformat(h["started_at"]) >= cut]
            return {k: sum(1 for h in sel if h["status"] == k) for k in ("SUCCESS", "PARTIAL", "FAILED")} | {"total": len(sel)}

        durations = [h["duration_s"] for h in hist[-50:] if h.get("duration_s")]
        last = st.get("last_success_at")
        usage = shutil.disk_usage(s.local_dir) if os.path.isdir(s.local_dir) else None
        remote = _remote_cache(s)
        return jsonify(
            now=now.isoformat(), environment=s.env_name, live_db=ops.live_db(cfg),
            last_success_at=last, last_success_id=st.get("last_success_id"),
            hours_since_success=round((now - datetime.fromisoformat(last)).total_seconds() / 3600, 1) if last else None,
            max_gap_hours=s.max_gap_hours,
            last_error=st.get("last_error") if not st.get("last_attempt_ok", True) else None,
            last_decision=st.get("last_decision"),
            next_window=schedule.next_window_start(now, s.windows).isoformat(),
            windows=[str(w) for w in s.windows],
            counts={"7d": counts(7), "30d": counts(30), "all": counts(36500)},
            avg_duration_s=round(sum(durations) / len(durations)) if durations else None,
            last_verify=st.get("last_verify"),
            disk={"path": s.local_dir, "total": usage.total, "used": usage.used, "free": usage.free} if usage else None,
            local_sets=len(local_sets(s)),
            remote={"configured": bool(s.remote), "count": len(remote["sets"]) if remote else None,
                    "listed_at": remote["at"] if remote else None},
            retention={"daily_days": s.keep_daily_days, "weekly": s.keep_weekly, "monthly": s.keep_monthly},
            media_mode=s.media_mode,
            sources=[{"label": m.label, "path": m.path} for m in s.media_sources],
            job=jobs.busy(cfg),
        )

    @app.get("/api/runs")
    @login_required
    def runs():
        s = settings()
        st = backup_state.load(s)
        return jsonify(runs=list(reversed(st.get("history", []))),
                       verifies=list(reversed(st.get("verify_history", []))))

    @app.get("/api/log")
    @login_required
    def log():
        s = settings()
        since, until = request.args.get("since"), request.args.get("until")
        q = (request.args.get("q") or "").lower()
        level = request.args.get("level") or ""
        limit = min(int(request.args.get("limit") or 1500), 5000)
        lines = _read_logs(s, since, until)
        if level:
            lines = [ln for ln in lines if f" {level} " in ln]
        if q:
            lines = [ln for ln in lines if q in ln.lower()]
        return jsonify(lines=lines[-limit:], total=len(lines))

    # ── sets / databases / files ────────────────────────────────────────────
    @app.get("/api/sets")
    @login_required
    def sets():
        s = settings()
        local = []
        for name, path in reversed(local_sets(s)):
            try:
                m = backupset.load_manifest(path)
            except (OSError, ValueError):
                continue
            local.append({"id": name, "at": parse_set_id(name).isoformat(), "size": backupset.set_size(path),
                          "tables": m["database"]["table_count"], "rows": m["database"]["total_rows"],
                          "files": m["media"]["file_count"], "trigger": m.get("trigger"),
                          "on_drive": os.path.exists(os.path.join(path, ".uploaded")),
                          "verified": os.path.exists(os.path.join(path, "verified.json"))})
        remote = _remote_cache(s)
        local_ids = {x["id"] for x in local}
        drive = [{"id": n, "at": parse_set_id(n).isoformat(), "local": n in local_ids}
                 for n in reversed((remote or {}).get("sets", [])) if parse_set_id(n)]
        return jsonify(local=local, drive=drive, drive_listed_at=(remote or {}).get("at"))

    @app.get("/api/sets/<set_id>/files")
    @login_required
    def set_files(set_id):
        s = settings()
        path = dict(local_sets(s)).get(set_id)
        if not path:
            return jsonify(error="file search works on backups stored on the server disk"), 404
        q = (request.args.get("q") or "").lower().strip()
        out = []
        with gzip.open(os.path.join(path, "media-index.jsonl.gz"), "rt") as f:
            for ln in f:
                item = json.loads(ln)
                if not q or q in item["p"].lower():
                    out.append(item)
                    if len(out) >= 200:
                        break
        return jsonify(files=out)

    @app.get("/api/databases")
    @login_required
    def databases():
        s = settings()
        created = ops._load_json(cfg.created_dbs_file, {})
        live = ops.live_db(cfg)
        rows = []
        try:
            import psycopg2
            conn = psycopg2.connect(**s.psycopg_kwargs(admin=True, dbname="postgres"))
            try:
                cur = conn.cursor()
                cur.execute("""SELECT datname, pg_database_size(datname) FROM pg_database
                               WHERE NOT datistemplate AND datname <> 'postgres' ORDER BY datname""")
                for name, size in cur.fetchall():
                    if name == live or name in created or name.startswith(s.db_name.split("_restore")[0]):
                        rows.append({"name": name, "size": size, "live": name == live,
                                     "created_by_console": created.get(name)})
            finally:
                conn.close()
            error = None
        except Exception as e:
            error = f"cannot list databases: {type(e).__name__}"
        hist = ops._load_json(cfg.switch_file, [])
        return jsonify(databases=rows, live=live, switch_history=list(reversed(hist)),
                       can_switch_back=bool(hist) and hist[-1]["to"] == live, error=error)

    # ── jobs ────────────────────────────────────────────────────────────────
    @app.post("/api/jobs")
    @login_required
    def start_job():
        body = request.get_json(silent=True) or {}
        kind, params = body.get("kind"), body.get("params") or {}
        if kind not in jobs.KINDS:
            return jsonify(error="unknown action"), 400
        if kind in jobs.DANGEROUS:
            require_password(body)
        if kind in ("switch_live", "drop_db"):
            want = params.get("target_db") if kind == "switch_live" else params.get("name")
            if (body.get("confirm") or "").strip() != want:
                return jsonify(error="type the database name exactly to confirm"), 400
        if kind == "switch_back" and (body.get("confirm") or "").strip().upper() != "SWITCH BACK":
            return jsonify(error="type SWITCH BACK to confirm"), 400
        try:
            meta = jobs.start(cfg, kind, params, session["user"])
        except (RuntimeError, ValueError) as e:
            return jsonify(error=str(e)), 409
        write_audit(cfg, session["user"], f"start {kind}", client_ip(), {"job": meta["id"], "params": params})
        return jsonify(job=meta)

    @app.get("/api/jobs")
    @login_required
    def list_jobs():
        return jsonify(jobs=jobs.list_jobs(cfg, limit=100))

    @app.get("/api/jobs/<job_id>")
    @login_required
    def job(job_id):
        try:
            d = jobs.job_dir(cfg, job_id)
            text, offset = jobs.output(cfg, job_id, int(request.args.get("offset") or 0))
        except (ValueError, FileNotFoundError):
            abort(404)
        return jsonify(job=jobs.read_meta(d), output=text, offset=offset)

    @app.get("/api/jobs/<job_id>/file")
    @login_required
    def job_file(job_id):
        try:
            d = jobs.job_dir(cfg, job_id)
        except (ValueError, FileNotFoundError):
            abort(404)
        meta = jobs.read_meta(d)
        name = (meta.get("result") or {}).get("file")
        path = os.path.join(d, "file", name or "")
        if meta["kind"] != "restore_file" or not name or not os.path.isfile(path):
            abort(404)
        write_audit(cfg, session["user"], "download restored file", client_ip(), {"job": job_id, "file": name})
        return send_file(path, as_attachment=True, download_name=name)

    # ── alert recipients ────────────────────────────────────────────────────
    @app.get("/api/recipients")
    @login_required
    def get_recipients():
        data = recipients.load()
        configured = data is not None
        if not configured:   # show what the senders use today
            from .__main__ import current_lists
            data = {"contacts": {}, "categories": {k: recipients.split_emails(v)
                                                   for k, v in current_lists().items()}}
        return jsonify(
            configured=configured, path=recipients.path(), data=data,
            categories=[{"key": k, "group": g, "label": lab, "description": d}
                        for k, (g, lab, d) in recipients.CATEGORIES.items()])

    @app.put("/api/recipients")
    @login_required
    def put_recipients():
        body = request.get_json(silent=True) or {}
        before = recipients.load() or {"categories": {}}
        try:
            saved = recipients.save({"contacts": body.get("contacts") or {},
                                     "categories": body.get("categories") or {}}, session["user"])
        except ValueError as e:
            return jsonify(error=str(e)), 400
        changes = {k: {"before": before["categories"].get(k), "after": v}
                   for k, v in saved["categories"].items() if before["categories"].get(k) != v}
        write_audit(cfg, session["user"], "alert recipients changed", client_ip(), changes)
        return jsonify(data=saved, changed=len(changes))

    @app.post("/api/recipients/test")
    @login_required
    def test_recipients():
        body = request.get_json(silent=True) or {}
        cat = body.get("category")
        if cat not in recipients.CATEGORIES:
            return jsonify(error="unknown alert type"), 400
        from erp_backup import emails, notify
        s = settings()
        subject, html, text = emails.test_message(s, cat)
        to = recipients.get(cat, fallback=s.alert_emails)
        sent = notify.send(s, subject, text, html, category=cat)
        write_audit(cfg, session["user"], "test email", client_ip(), {"category": cat, "to": to, "sent": sent})
        if not sent:
            return jsonify(error="not sent — no recipients or mail settings missing (see backup log)"), 400
        return jsonify(sent_to=to)

    @app.get("/api/audit")
    @login_required
    def audit():
        return jsonify(entries=read_audit(cfg, 500))

    return app


# ── helpers ─────────────────────────────────────────────────────────────────

def _remote_cache(s):
    try:
        with open(os.path.join(s.local_dir, "remote_sets.json")) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


LOG_LINE = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})")


def _read_logs(s, since=None, until=None):
    log_dir = os.path.join(s.local_dir, "logs")
    if not os.path.isdir(log_dir):
        return []
    files = sorted((f for f in os.listdir(log_dir) if f.startswith("backup.log")),
                   key=lambda f: (f != "backup.log", f))
    files = [f for f in files if f != "backup.log"] + (["backup.log"] if "backup.log" in files else [])
    lo = since[:19].replace("T", " ") if since else None
    hi = until[:19].replace("T", " ") if until else None
    if hi and len(hi) == 19:
        hi = hi[:17] + "59"
    out = []
    for name in files:
        if lo and name != "backup.log" and name.split(".")[-1] < lo[:10]:
            continue
        ts = None
        with open(os.path.join(log_dir, name), errors="replace") as f:
            for ln in f:
                m = LOG_LINE.match(ln)
                if m:                      # lines without a time continue the entry above
                    ts = m.group(1)
                if ts and lo and ts < lo:
                    continue
                if ts and hi and ts > hi:
                    continue
                out.append(ln.rstrip("\n"))
    return out

