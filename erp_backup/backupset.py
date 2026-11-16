"""Create one complete backup set on the local backup disk.

A set is a folder  <local_dir>/sets/<backup_id>/  holding:

    db.dump               pg_dump custom format — every table, sequence, index…
    db.sql.gz             plain SQL copy (once a week, made from db.dump)
    globals.sql           roles / grants (pg_dumpall --globals-only)
    media.tar.zst         every uploaded file (BACKUP_MEDIA_MODE=full)
    media-index.jsonl.gz  list of every uploaded file: path, size, mtime
    manifest.json         what is in the set: row count of every table, versions…
    SHA256SUMS            checksum of every file above

Consistency: the row counts are taken inside the very snapshot pg_dump uses
(pg_export_snapshot), and the media is archived *after* the dump, so every
file URL stored in the dump already exists on disk when it is archived (the
app saves a file before it stores its URL).
"""

import gzip
import json
import os
import shutil
import socket
import subprocess
import tarfile
from datetime import datetime

from .util import BackupError, log, run, set_id_for, sha256_file, write_json_atomic, human_bytes

MANIFEST_FORMAT = 1


def sets_dir(settings):
    return os.path.join(settings.local_dir, "sets")


def create(settings, trigger, now=None, want_plain_sql=False):
    """Make a new set. Returns (set_path, manifest). Raises BackupError."""
    now = (now or datetime.now(settings.tz)).replace(microsecond=0)
    backup_id = set_id_for(settings.env_name, now)
    final = os.path.join(sets_dir(settings), backup_id)
    work = final + ".partial"
    if os.path.exists(final):
        raise BackupError(f"backup set {backup_id} already exists")
    shutil.rmtree(work, ignore_errors=True)
    os.makedirs(work)

    from . import __version__
    manifest = {
        "format": MANIFEST_FORMAT,
        "tool_version": __version__,
        "backup_id": backup_id,
        "environment": settings.env_name,
        "trigger": trigger,
        "host": socket.gethostname(),
        "started_at": now.isoformat(),
        "warnings": [],
    }
    try:
        _check_free_space(settings)
        manifest["database"] = dump_database(settings, work, manifest["warnings"])
        dump_globals(settings, work, manifest["warnings"])
        if want_plain_sql:
            make_plain_sql(settings, work, manifest["warnings"])
        manifest["media"] = backup_media(settings, work, manifest["warnings"])
        manifest["git_commit"] = _git_commit()
        manifest["tool_versions"] = _tool_versions(settings)
        manifest["finished_at"] = datetime.now(settings.tz).replace(microsecond=0).isoformat()
        manifest["files"] = _checksums(work)
        write_json_atomic(os.path.join(work, "manifest.json"), manifest)
        os.replace(work, final)        # only a finished set gets its real name
    except BaseException:
        shutil.rmtree(work, ignore_errors=True)
        raise
    log.info("backup set %s ready (%s)", backup_id, human_bytes(set_size(final)))
    return final, manifest


# ── database ────────────────────────────────────────────────────────────────

def dump_database(settings, work, warnings):
    import psycopg2
    from psycopg2 import extensions, sql

    out = os.path.join(work, "db.dump")
    try:
        conn = psycopg2.connect(**settings.psycopg_kwargs())
    except psycopg2.Error as e:
        raise BackupError(f"cannot connect to database: {str(e).strip()}") from e
    try:
        conn.set_session(isolation_level=extensions.ISOLATION_LEVEL_REPEATABLE_READ, readonly=True)
        cur = conn.cursor()
        cur.execute("SELECT pg_export_snapshot(), current_setting('server_version')")
        snapshot, server_version = cur.fetchone()

        # pg_dump reads the same snapshot this transaction holds open
        cmd =[settings.pg("pg_dump"), *settings.pg_args(), "--format=custom",
               f"--snapshot={snapshot}", "--file", out]
        try:
            run(cmd, env=settings.pg_env())
        except BackupError as e:
            raise BackupError(_explain_dump_error(str(e))) from e

        # row count of every table, in the same snapshot as the dump
        cur.execute("""
            SELECT n.nspname, c.relname FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE c.relkind IN ('r', 'p')
              AND n.nspname NOT IN ('pg_catalog', 'information_schema')
              AND n.nspname NOT LIKE 'pg_toast%%' AND n.nspname NOT LIKE 'pg_temp%%'
            ORDER BY 1, 2""")
        tables = {}
        for schema, name in cur.fetchall():
            cur.execute(sql.SQL("SELECT count(*) FROM {}.{}").format(
                sql.Identifier(schema), sql.Identifier(name)))
            key = name if schema == "public" else f"{schema}.{name}"
            tables[key] = cur.fetchone()[0]

        alembic = None
        if "alembic_version" in tables:
            cur.execute("SELECT version_num FROM alembic_version")
            row = cur.fetchone()
            alembic = row[0] if row else None
        cur.execute("SELECT pg_database_size(current_database())")
        db_size = cur.fetchone()[0]
        conn.rollback()
    except psycopg2.Error as e:
        raise BackupError(f"database error during backup: {str(e).strip()}") from e
    finally:
        conn.close()

    if not tables:
        warnings.append("database has no tables")
    return {
        "name": settings.db_name,
        "server_version": server_version,
        "alembic_revision": alembic,
        "size_bytes": db_size,
        "dump_file": "db.dump",
        "dump_bytes": os.path.getsize(out),
        "table_count": len(tables),
        "total_rows": sum(tables.values()),
        "tables": tables,
    }


def _explain_dump_error(msg):
    corruption = ("invalid page", "could not read block", "corrupt", "unexpected zero page",
                  "missing chunk", "invalid memory alloc")
    if any(word in msg.lower() for word in corruption):
        return ("POSSIBLE DATABASE CORRUPTION — do NOT delete any old backups. " + msg)
    return msg


def dump_globals(settings, work, warnings):
    out = os.path.join(work, "globals.sql")
    cmd = [settings.pg("pg_dumpall"), "-h", settings.db_host, "-p", str(settings.db_port),
           "-U", settings.db_user, "-l", settings.db_name,
           "--globals-only", "--no-role-passwords", "--file", out]
    try:
        run(cmd, env=settings.pg_env())
    except BackupError as e:
        # needs extra rights on some setups; the data itself is still complete
        warnings.append(f"roles/grants (globals.sql) not saved: {e}")
        if os.path.exists(out):
            os.remove(out)


def make_plain_sql(settings, work, warnings):
    """Readable .sql.gz made from db.dump (no second read of the live DB)."""
    dump = os.path.join(work, "db.dump")
    out = os.path.join(work, "db.sql.gz")
    proc = subprocess.Popen([settings.pg("pg_restore"), "--file=-", dump],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    with gzip.open(out, "wb", compresslevel=6) as gz:
        shutil.copyfileobj(proc.stdout, gz, 4 * 1024 * 1024)
    err = proc.stderr.read().decode(errors="replace")
    if proc.wait() != 0:
        os.remove(out)
        warnings.append(f"plain SQL copy failed: {err.strip()[-500:]}")


# ── media (pictures and documents) ──────────────────────────────────────────

def backup_media(settings, work, warnings):
    index_path = os.path.join(work, "media-index.jsonl.gz")
    sources = settings.media_sources
    if not sources:
        warnings.append("no media folders configured (MEDIA_BASE_PATH / BACKUP_MEDIA_DIRS)")
    for src in sources:
        if not os.path.isdir(src.path):
            raise BackupError(f"media folder missing: {src.path} ({src.label})")

    archive_name = None
    if settings.media_mode == "full":
        zstd = shutil.which("zstd")
        archive_name = "media.tar.zst" if zstd else "media.tar.gz"
        stats = _write_archive(sources, os.path.join(work, archive_name), index_path, zstd)
    else:
        stats = _write_index_only(sources, index_path)

    if stats["missing"]:
        warnings.append(f"{stats['missing']} file(s) were deleted while the backup ran (skipped)")
    for path in stats["unreadable"][:20]:
        warnings.append(f"cannot read file: {path}")
    if stats["unreadable"]:
        raise BackupError(f"{len(stats['unreadable'])} media file(s) could not be read "
                          f"(first: {stats['unreadable'][0]}) — check file permissions")
    gb = stats["bytes"] / 1024 ** 3
    if settings.media_mode == "full" and gb > settings.media_full_warn_gb:
        warnings.append(f"media is {gb:.1f} GB — a full copy every run is getting heavy; "
                        f"consider BACKUP_MEDIA_MODE=sync (see deploy/backup/README.md)")
    return {
        "mode": settings.media_mode,
        "sources": [{"label": s.label, "path": s.path} for s in sources],
        "archive": archive_name,
        "index": "media-index.jsonl.gz",
        "file_count": stats["files"],
        "total_bytes": stats["bytes"],
        "skipped_deleted": stats["missing"],
    }


def _walk(sources):
    """Yield (abs_path, archive_name, is_dir) in a stable order."""
    for src in sources:
        yield src.path, src.label, True
        for root, dirs, files in os.walk(src.path):
            dirs.sort()
            rel_root = os.path.relpath(root, src.path)
            for d in dirs:
                arc = os.path.normpath(os.path.join(src.label, rel_root, d))
                yield os.path.join(root, d), arc, True
            for f in sorted(files):
                arc = os.path.normpath(os.path.join(src.label, rel_root, f))
                yield os.path.join(root, f), arc, False


def _write_archive(sources, out, index_path, zstd):
    stats = {"files": 0, "bytes": 0, "missing": 0, "unreadable": []}
    if zstd:
        comp = subprocess.Popen([zstd, "-q", "-T0", "-3", "-f", "-o", out],
                                stdin=subprocess.PIPE, stderr=subprocess.PIPE)
        tar_target = dict(fileobj=comp.stdin, mode="w|")
    else:
        comp = None
        tar_target = dict(name=out, mode="w|gz")

    with gzip.open(index_path, "wt") as index, \
            tarfile.open(format=tarfile.PAX_FORMAT, **tar_target) as tar:
        for path, arc, is_dir in _walk(sources):
            try:
                st = os.lstat(path)
                tar.add(path, arcname=arc, recursive=False)
            except FileNotFoundError:
                stats["missing"] += 1
                continue
            except PermissionError:
                stats["unreadable"].append(path)
                continue
            if not is_dir:
                stats["files"] += 1
                stats["bytes"] += st.st_size
                index.write(json.dumps({"p": arc, "s": st.st_size, "m": int(st.st_mtime)}) + "\n")
    if comp:
        comp.stdin.close()
        err = comp.stderr.read().decode(errors="replace")
        if comp.wait() != 0:
            raise BackupError(f"zstd failed: {err.strip()[-500:]}")
    return stats


def _write_index_only(sources, index_path):
    stats = {"files": 0, "bytes": 0, "missing": 0, "unreadable": []}
    with gzip.open(index_path, "wt") as index:
        for path, arc, is_dir in _walk(sources):
            if is_dir:
                continue
            try:
                st = os.lstat(path)
            except FileNotFoundError:
                stats["missing"] += 1
                continue
            if not os.access(path, os.R_OK):
                stats["unreadable"].append(path)
                continue
            stats["files"] += 1
            stats["bytes"] += st.st_size
            index.write(json.dumps({"p": arc, "s": st.st_size, "m": int(st.st_mtime)}) + "\n")
    return stats


def read_media_index(set_path):
    with gzip.open(os.path.join(set_path, "media-index.jsonl.gz"), "rt") as f:
        return {json.loads(line)["p"] for line in f if line.strip()}


# ── helpers ─────────────────────────────────────────────────────────────────

def _checksums(work):
    files = []
    lines = []
    for name in sorted(os.listdir(work)):
        path = os.path.join(work, name)
        if name in ("manifest.json", "SHA256SUMS") or not os.path.isfile(path):
            continue
        digest = sha256_file(path)
        files.append({"name": name, "bytes": os.path.getsize(path), "sha256": digest})
        lines.append(f"{digest}  {name}\n")
    with open(os.path.join(work, "SHA256SUMS"), "w") as f:
        f.writelines(lines)
    return files


def verify_checksums(set_path):
    """List of problems (empty = all files match SHA256SUMS)."""
    problems = []
    sums = os.path.join(set_path, "SHA256SUMS")
    if not os.path.exists(sums):
        return ["SHA256SUMS missing"]
    with open(sums) as f:
        for line in f:
            if not line.strip():
                continue
            digest, name = line.rstrip("\n").split("  ", 1)
            path = os.path.join(set_path, name)
            if not os.path.exists(path):
                problems.append(f"{name}: missing")
            elif sha256_file(path) != digest:
                problems.append(f"{name}: checksum mismatch")
    return problems


def load_manifest(set_path):
    with open(os.path.join(set_path, "manifest.json")) as f:
        return json.load(f)


def set_size(path):
    return sum(os.path.getsize(os.path.join(path, n)) for n in os.listdir(path)
               if os.path.isfile(os.path.join(path, n)))


def _check_free_space(settings):
    """Refuse to start when the backup disk cannot hold another set."""
    os.makedirs(sets_dir(settings), exist_ok=True)
    free = shutil.disk_usage(settings.local_dir).free
    last = [os.path.join(sets_dir(settings), n) for n in os.listdir(sets_dir(settings))
            if not n.endswith(".partial")]
    need = int(max((set_size(p) for p in last), default=0) * 1.2)
    if free < need:
        raise BackupError(f"backup disk {settings.local_dir} has {human_bytes(free)} free, "
                          f"about {human_bytes(need)} needed — free space or add a bigger disk")


def _git_commit():
    try:
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        return subprocess.run(["git", "-C", root, "rev-parse", "HEAD"], capture_output=True,
                              text=True, timeout=10).stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


def _tool_versions(settings):
    out = {}
    for name, cmd in (("pg_dump", [settings.pg("pg_dump"), "--version"]),
                      ("zstd", ["zstd", "--version"]),
                      ("rclone", [settings.rclone_bin, "version"])):
        try:
            out[name] = subprocess.run(cmd, capture_output=True, text=True,
                                       timeout=10).stdout.strip().splitlines()[0]
        except (OSError, IndexError, subprocess.SubprocessError):
            out[name] = None
    return out
