"""Restore test (`verify`) and real restore (`restore`).

verify  — weekly: restore a set into a throw-away database and prove it is
          complete: checksums, every table's row count equals the manifest,
          the media archive reads end-to-end and matches its index, and every
          picture/document URL stored in the database has its file in the set.

restore — emergency: restore a set into a NEW database (never over the live
          one) and optionally unpack the media into a folder you choose.
"""

import json
import os
import re
import shutil
import subprocess
import tarfile
from datetime import datetime
from urllib.parse import unquote

from . import backupset, emails, notify
from . import state as st
from .remote import Remote
from .runner import local_sets
from .naming import canonical_id
from .util import BackupError, log, run, write_json_atomic


# ── finding a set ───────────────────────────────────────────────────────────

def locate_set(settings, name=None, from_remote=False):
    """Path of a local copy of the set (downloaded from Drive if asked/needed).
    `name` is a set id (PRAX-ERP_2026-11-24_0215); a Drive folder name
    (PRAX-ERP_weekly_2026-W47_…) works too. None = the newest."""
    if name:
        name = canonical_id(name) or name
    local = dict(local_sets(settings))
    if not from_remote:
        if name is None and local:
            name = list(local)[-1]
        if name in local:
            return name, local[name]
    if not settings.remote:
        raise BackupError(f"backup set {name or '(latest)'} not on the backup disk and no BACKUP_REMOTE set")
    remote = Remote(settings)
    sets = remote.list_sets()
    if not sets:
        raise BackupError("no backup sets on Google Drive")
    rs = remote.find(name, sets) if name else sets[-1]
    if rs is None:
        raise BackupError(f"backup set {name} not found on Google Drive")
    dest = os.path.join(settings.local_dir, "downloads", rs.id)
    shutil.rmtree(dest, ignore_errors=True)
    os.makedirs(dest)
    log.info("downloading %s from Google Drive", rs.path)
    remote.download_set(rs, dest)
    return rs.id, dest


# ── database helpers ────────────────────────────────────────────────────────

def _connect_admin(settings, dbname):
    import psycopg2
    return psycopg2.connect(**settings.psycopg_kwargs(admin=True, dbname=dbname))


def _db_exists(settings, name):
    conn = _connect_admin(settings, "postgres")
    try:
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (name,))
        return cur.fetchone() is not None
    finally:
        conn.close()


def _create_db(settings, name):
    run([settings.pg("createdb"), "-h", settings.db_host, "-p", str(settings.db_port),
         "-U", settings.admin_user, name], env=settings.pg_env(admin=True))


def _drop_db(settings, name):
    run([settings.pg("dropdb"), "-h", settings.db_host, "-p", str(settings.db_port),
         "-U", settings.admin_user, "--if-exists", name], env=settings.pg_env(admin=True))


def _pg_restore(settings, set_path, dbname, jobs):
    run([settings.pg("pg_restore"), *settings.pg_args(admin=True, dbname=dbname),
         "--no-owner", "--no-acl", "--exit-on-error", f"--jobs={jobs}",
         os.path.join(set_path, "db.dump")], env=settings.pg_env(admin=True))


def _row_counts(settings, dbname):
    from psycopg2 import sql
    conn = _connect_admin(settings, dbname)
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT n.nspname, c.relname FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE c.relkind IN ('r', 'p')
              AND n.nspname NOT IN ('pg_catalog', 'information_schema')
              AND n.nspname NOT LIKE 'pg_toast%%' AND n.nspname NOT LIKE 'pg_temp%%'""")
        out = {}
        for schema, name in cur.fetchall():
            cur.execute(sql.SQL("SELECT count(*) FROM {}.{}").format(
                sql.Identifier(schema), sql.Identifier(name)))
            out[name if schema == "public" else f"{schema}.{name}"] = cur.fetchone()[0]
        return out
    finally:
        conn.close()


def _strings_in(value):
    """All strings inside a column value: JSON is walked, plain text is itself."""
    try:
        data = json.loads(value)
    except (TypeError, ValueError):
        return [value]
    out, stack = [], [data]
    while stack:
        item = stack.pop()
        if isinstance(item, str):
            out.append(item)
        elif isinstance(item, list):
            stack.extend(item)
        elif isinstance(item, dict):
            stack.extend(item.values())
    return out


def extract_media_paths(value, base, pattern):
    """'media/<path>' for every file URL in one column value. A string that is
    just a URL is taken whole, so folder/file names with spaces survive
    (e.g. user/Dipak Jana_7/photo.jpg); URLs inside longer text use the regex."""
    found = set()
    for s in _strings_in(value or ""):
        s = s.strip()
        bare = re.sub(r"^https?://", "", s)
        if bare.startswith(base + "/") and "\n" not in s:
            rels = [bare[len(base) + 1:]]
        else:
            rels = pattern.findall(s)
        for rel in rels:
            rel = unquote(rel).replace("\\/", "/").strip("/")
            if rel:
                found.add("media/" + rel)
    return found


def media_urls_in_db(settings, dbname):
    """Every uploaded-file path referenced anywhere in the database, as it
    appears in the media index ('media/<folder>/<file>')."""
    if not settings.media_base_url:
        return None
    from psycopg2 import sql
    base = settings.media_base_url.split("://", 1)[-1].rstrip("/")
    pattern = re.compile(r"(?:https?://)?" + re.escape(base) + r"/([^\s\"'<>,;)\]}]+)")
    found = set()
    conn = _connect_admin(settings, dbname)
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT table_schema, table_name, column_name FROM information_schema.columns
            WHERE table_schema NOT IN ('pg_catalog', 'information_schema')
              AND data_type IN ('text', 'character varying', 'json', 'jsonb', 'ARRAY')
              AND (table_schema, table_name) IN (
                  SELECT table_schema, table_name FROM information_schema.tables
                  WHERE table_type = 'BASE TABLE')""")
        for schema, table, column in cur.fetchall():
            cur.execute(sql.SQL("SELECT {c}::text FROM {s}.{t} WHERE {c}::text LIKE %s").format(
                c=sql.Identifier(column), s=sql.Identifier(schema), t=sql.Identifier(table)),
                (f"%{base}/%",))
            for (value,) in cur.fetchall():
                found.update(extract_media_paths(value, base, pattern))
        return found
    finally:
        conn.close()


def _check_archive(set_path, manifest, index):
    """Read the whole media archive; return list of problems."""
    archive = manifest["media"].get("archive")
    if not archive:
        return []
    path = os.path.join(set_path, archive)
    seen = set()
    if archive.endswith(".zst"):
        proc = subprocess.Popen(["zstd", "-dcq", path], stdout=subprocess.PIPE)
        tar = tarfile.open(fileobj=proc.stdout, mode="r|")
    else:
        proc, tar = None, tarfile.open(path, mode="r|gz")
    problems = []
    try:
        for member in tar:
            if member.isfile():
                f = tar.extractfile(member)
                while f.read(4 * 1024 * 1024):     # read every byte
                    pass
                seen.add(member.name)
    except (tarfile.TarError, OSError) as e:
        problems.append(f"media archive unreadable: {e}")
    finally:
        tar.close()
        if proc:
            proc.stdout.close()
            if proc.wait() != 0:
                problems.append("media archive: zstd reported an error")
    if problems:
        return problems
    if seen != index:
        problems.append(f"media archive has {len(seen)} files, index lists {len(index)} "
                        f"(missing from archive: {sorted(index - seen)[:5]})")
    return problems


# ── verify ──────────────────────────────────────────────────────────────────

def verify(settings, name=None, from_remote=False, keep_db=False, email=True):
    started = datetime.now(settings.tz).replace(microsecond=0)
    report = {"at": started.isoformat(), "backup_id": name, "status": "FAILED", "problems": [], "notes": []}
    scratch = f"{settings.db_name}_restore_test"
    try:
        name, set_path = locate_set(settings, name, from_remote)
        report["backup_id"] = name
        report["source"] = "google drive" if from_remote else "backup disk"

        bad = backupset.verify_checksums(set_path)
        if bad:
            raise BackupError("checksum problems: " + "; ".join(bad))
        manifest = backupset.load_manifest(set_path)

        if scratch == settings.db_name:
            raise BackupError("refusing: scratch DB name equals live DB")
        _drop_db(settings, scratch)
        _create_db(settings, scratch)
        _pg_restore(settings, set_path, scratch, jobs=2)

        expected = manifest["database"]["tables"]
        actual = _row_counts(settings, scratch)
        diffs = [f"{t}: backup says {expected.get(t)}, restored {actual.get(t)}"
                 for t in sorted(set(expected) | set(actual)) if expected.get(t) != actual.get(t)]
        report["problems"] += diffs
        report["notes"].append(f"{len(actual)} tables, {sum(actual.values())} rows restored")

        index = backupset.read_media_index(set_path)
        report["problems"] += _check_archive(set_path, manifest, index)
        report["notes"].append(f"{len(index)} media files in set")

        urls = media_urls_in_db(settings, scratch)
        if urls is None:
            report["notes"].append("MEDIA_BASE_URL not set — skipped URL→file check")
        else:
            missing = sorted(urls - index)
            report["notes"].append(f"{len(urls)} file URLs in database, {len(missing)} without a file")
            if missing:
                report["problems"].append(
                    f"{len(missing)} file URL(s) in the database have no file in the backup "
                    f"(may already be missing on the server). First: {missing[:10]}")
        report["status"] = "PASSED" if not report["problems"] else "PROBLEMS"
    except BackupError as e:
        report["problems"].append(str(e))
    except Exception as e:
        report["problems"].append(f"{type(e).__name__}: {e}")
    finally:
        if not keep_db:
            try:
                _drop_db(settings, scratch)
            except Exception as e:
                report["notes"].append(f"could not drop {scratch}: {e}")

    report["finished_at"] = datetime.now(settings.tz).replace(microsecond=0).isoformat()
    _store_report(settings, report)
    if email:
        subject, html, text = emails.restore_test(report)
        notify.send(settings, subject, text, html, category="backup_restore_test",
                    urgent=report["status"] != "PASSED")
    return report


def _store_report(settings, report):
    state = st.load(settings)
    state["last_verify"] = report
    hist = state.setdefault("verify_history", [])
    hist.append({k: report.get(k) for k in ("at", "finished_at", "backup_id", "source", "status", "notes", "problems")})
    del hist[:-200]
    st.save(settings, state)
    if not report.get("backup_id"):
        return
    local = dict(local_sets(settings)).get(report["backup_id"])
    if local and os.path.isdir(local):
        out = os.path.join(local, "verified.json")
        write_json_atomic(out, report)
        if settings.remote and report["status"] == "PASSED":
            try:
                remote = Remote(settings)
                rs = remote.find(report["backup_id"])
                if rs:
                    remote.upload_file(out, rs)
            except BackupError as e:
                log.warning("could not upload verify report: %s", e)


def format_report(r):
    lines = [f"Backup set: {r.get('backup_id')}", f"Source:     {r.get('source', '-')}",
             f"Result:     {r['status']}", f"Time:       {r['at']} → {r.get('finished_at')}", ""]
    lines += [f"  - {n}" for n in r["notes"]]
    if r["problems"]:
        lines += ["", "PROBLEMS:"] + [f"  ! {p}" for p in r["problems"][:50]]
    return "\n".join(lines) + "\n"


def _safe_extract(tar, dest):
    try:
        tar.extractall(dest, filter="data")      # blocks ../ and absolute paths
    except TypeError:                            # Python without extraction filters
        root = os.path.realpath(dest)
        for m in tar:
            target = os.path.realpath(os.path.join(dest, m.name))
            if not target.startswith(root + os.sep) or m.issym() or m.islnk():
                raise BackupError(f"unsafe path in archive: {m.name}")
            tar.extract(m, dest)


# ── restore ─────────────────────────────────────────────────────────────────

def restore(settings, name, target_db, media_dir=None, from_remote=False, jobs=4):
    if not target_db:
        raise BackupError("give --target-db (a NEW database name)")
    if target_db == settings.db_name:
        raise BackupError("refusing to restore over the live database — restore into a new "
                          "name, check it, then point DB_NAME at it")
    name, set_path = locate_set(settings, name, from_remote)
    bad = backupset.verify_checksums(set_path)
    if bad:
        raise BackupError("checksum problems, set is damaged: " + "; ".join(bad))
    manifest = backupset.load_manifest(set_path)
    if _db_exists(settings, target_db):
        raise BackupError(f"database {target_db} already exists — choose a new name")

    log.info("restoring %s into new database %s", name, target_db)
    _create_db(settings, target_db)
    _pg_restore(settings, set_path, target_db, jobs)
    actual = _row_counts(settings, target_db)
    expected = manifest["database"]["tables"]
    diffs = [t for t in expected if expected[t] != actual.get(t)]

    media_note = "media not extracted (use --media-dir)"
    if media_dir:
        archive = manifest["media"].get("archive")
        if not archive:
            media_note = ("set was made in sync mode: copy media from Google Drive "
                          "media/current with  rclone copy <remote>/media/current <dir>")
        else:
            if os.path.exists(media_dir) and os.listdir(media_dir):
                raise BackupError(f"{media_dir} is not empty — give an empty folder")
            os.makedirs(media_dir, exist_ok=True)
            path = os.path.join(set_path, archive)
            if archive.endswith(".zst"):
                proc = subprocess.Popen(["zstd", "-dcq", path], stdout=subprocess.PIPE)
                with tarfile.open(fileobj=proc.stdout, mode="r|") as tar:
                    _safe_extract(tar, media_dir)
                proc.wait()
            else:
                with tarfile.open(path, mode="r|gz") as tar:
                    _safe_extract(tar, media_dir)
            labels = ", ".join(f"{m['label']}/ → {m['path']}" for m in manifest["media"]["sources"])
            media_note = f"media extracted to {media_dir}  (move: {labels})"

    return {
        "backup_id": name, "target_db": target_db, "tables": len(actual),
        "row_mismatches": diffs, "media": media_note,
        "alembic_revision": manifest["database"].get("alembic_revision"),
        "git_commit": manifest.get("git_commit"),
        "backup_time": manifest["started_at"],
    }
