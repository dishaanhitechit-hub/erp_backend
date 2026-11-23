"""Google Drive through rclone.

BACKUP_REMOTE should be an rclone *crypt* remote layered on a Google Drive
remote (see deploy/backup/README.md), so file contents are encrypted before
they leave the server. From 1.2.0 the crypt remote is set up with file-name
encryption off, so folder names are readable. Layout under BACKUP_REMOTE
(names: see naming.py):

    Daily/2026-11/PRAX-ERP_daily_2026-11-24_0215/        one complete backup set
    Weekly/2026/PRAX-ERP_weekly_2026-W47_2026-11-23_2215/
    Monthly/2026/PRAX-ERP_monthly_2026-11_2026-11-30_2215/
    Manual/2026/PRAX-ERP_manual_2026-11-24_1530/
    _uploading/<name>/         upload in progress (never treated as a backup)
    sets/<old id>/             layout before 1.2.0 (moved into the folders above by retention)
    media/current/<label>/     (sync mode) mirror of uploaded files
    media/versions/<id>/       (sync mode) files changed/deleted at that run
"""

import json
import subprocess
from dataclasses import dataclass
from datetime import datetime, timedelta

from . import naming
from .util import BackupError, log, parse_set_id, run

UPLOADING = "_uploading"
LEGACY = "sets"


@dataclass(frozen=True)
class RemoteSet:
    path: str           # under BACKUP_REMOTE, e.g. Daily/2026-11/PRAX-ERP_daily_2026-11-24_0215
    name: str           # last part of path
    id: str             # set id, e.g. PRAX-ERP_2026-11-24_0215 (pre-1.2.0: the old name)
    when: datetime
    tier: str           # daily | weekly | monthly | manual | legacy

    def as_dict(self):
        return {"id": self.id, "path": self.path, "tier": self.tier, "at": self.when.isoformat()}


def parse_listing(lines, tz=None):
    """RemoteSets in the output of `rclone lsf -R --dirs-only` of the backup root."""
    out = []
    for line in lines:
        path = line.strip().rstrip("/")
        parts = path.split("/")
        if not path:
            continue
        name = parts[-1]
        when = parse_set_id(name, tz)
        if when is None:
            continue
        if len(parts) == 2 and parts[0] == LEGACY:
            tier = naming.tier_of_name(name) or "legacy"
        elif len(parts) == 3 and parts[0] in naming.FOLDER_TIERS:
            tier = naming.tier_of_name(name)
            if tier != naming.FOLDER_TIERS[parts[0]]:
                continue                       # something someone put there by hand
        else:
            continue
        out.append(RemoteSet(path, name, naming.canonical_id(name), when, tier))
    return sorted(out, key=lambda r: r.when)


class Remote:
    def __init__(self, settings, root=None):
        self.s = settings
        self.root = (root or settings.remote).rstrip("/")
        self._crypt = None

    # ── plumbing ──
    def _cmd(self, *args):
        cmd = [self.s.rclone_bin]
        if self.s.rclone_config:
            cmd += ["--config", self.s.rclone_config]
        return cmd + list(args)

    def _transfer_flags(self):
        flags = ["--transfers", "4", "--checkers", "8", "--retries", "5",
                 "--low-level-retries", "20", "--stats", "0"]
        if self.s.rclone_bwlimit:
            flags += ["--bwlimit", self.s.rclone_bwlimit]
        return flags

    def path(self, *parts):
        return "/".join([self.root, *parts])

    def _lsf_dirs(self, *parts, depth=1):
        args = ["lsf", "--dirs-only", self.path(*parts)]
        if depth > 1:
            args[1:1] = ["-R", "--max-depth", str(depth)]
        try:
            out = run(self._cmd(*args), capture=True, low_priority=False)
        except BackupError as e:
            if "not found" in str(e).lower():
                return []
            raise
        return [line.rstrip("/") for line in out.splitlines() if line.strip()]

    def is_crypt(self):
        if self._crypt is None:
            name = self.root.split(":", 1)[0]
            out = run(self._cmd("listremotes", "--long"), capture=True, low_priority=False)
            types = dict(line.split(":", 1) for line in out.splitlines() if ":" in line)
            self._crypt = types.get(name, "").strip() == "crypt"
        return self._crypt

    # ── backup sets ──
    def list_sets(self):
        """Every finished set, oldest first (RemoteSet)."""
        return parse_listing(self._lsf_dirs(depth=3), getattr(self.s, "tz", None))

    def find(self, set_id, sets=None):
        set_id = naming.canonical_id(set_id) or set_id
        for rs in reversed(sets if sets is not None else self.list_sets()):
            if rs.id == set_id:
                return rs
        return None

    def upload_set(self, set_path, dest, existing=None):
        """Upload a local set folder to `dest` (path under the root); verify every
        byte before it gets its real name."""
        existing = self.list_sets() if existing is None else existing
        if any(rs.path == dest for rs in existing):
            log.info("%s already on remote", dest)
            return
        partial = self.path(UPLOADING, dest.rsplit("/", 1)[-1])
        run(self._cmd("copy", set_path, partial, *self._transfer_flags()))
        if self.is_crypt():
            run(self._cmd("cryptcheck", set_path, partial, "--one-way"))
        else:
            run(self._cmd("check", set_path, partial, "--one-way"))
        run(self._cmd("moveto", partial, self.path(dest)))
        log.info("uploaded %s", dest)

    def copy_set_from(self, other, rs, dest):
        """Copy a set from another remote (e.g. the pre-1.2.0 encrypted one) to `dest`,
        then read both copies in full to prove they are the same."""
        partial = self.path(UPLOADING, dest.rsplit("/", 1)[-1])
        run(self._cmd("copy", other.path(rs.path), partial, *self._transfer_flags()))
        run(self._cmd("check", other.path(rs.path), partial, "--download", "--one-way"))
        run(self._cmd("moveto", partial, self.path(dest)))

    def check_same(self, other, rs, dest):
        run(self._cmd("check", other.path(rs.path), self.path(dest), "--download", "--one-way"))

    def move(self, src, dest):
        """Server-side move/rename of a set folder (no data is transferred)."""
        log.info("moving %s → %s", src, dest)
        run(self._cmd("moveto", self.path(src), self.path(dest)), low_priority=False)

    def upload_file(self, local_file, rs):
        run(self._cmd("copy", local_file, self.path(rs.path)))

    def download_set(self, rs, dest):
        run(self._cmd("copy", self.path(rs.path), dest, *self._transfer_flags()))

    def delete_set(self, rs):
        path = rs.path if isinstance(rs, RemoteSet) else rs
        run(self._cmd("purge", self.path(path)), low_priority=False)

    def remove_empty_folders(self):
        for folder in naming.TIER_FOLDERS.values():
            try:
                run(self._cmd("rmdirs", self.path(folder), "--leave-root"), low_priority=False)
            except BackupError as e:
                if "not found" not in str(e).lower():
                    log.warning("could not tidy %s: %s", folder, e)

    def cleanup_partials(self, now, older_than=timedelta(hours=12)):
        stale = [(UPLOADING, n) for n in self._lsf_dirs(UPLOADING)]
        stale += [(LEGACY, n) for n in self._lsf_dirs(LEGACY) if n.endswith(".partial")]
        for folder, name in stale:
            when = parse_set_id(name.removesuffix(".partial"), getattr(self.s, "tz", None))
            if when and now - when > older_than:
                log.info("removing stale upload %s/%s", folder, name)
                self.delete_set(f"{folder}/{name}")

    # ── media in sync mode ──
    def sync_media(self, sources, backup_id):
        for src in sources:
            run(self._cmd("sync", src.path, self.path("media", "current", src.label),
                          "--backup-dir", self.path("media", "versions", backup_id, src.label),
                          *self._transfer_flags()))

    def prune_media_versions(self, now, keep_days):
        for name in self._lsf_dirs("media", "versions"):
            when = parse_set_id(name, getattr(self.s, "tz", None))
            if when and now - when > timedelta(days=keep_days):
                run(self._cmd("purge", self.path("media", "versions", name)), low_priority=False)

    # ── watchdog + capacity ──
    def write_text(self, target, text):
        proc = subprocess.run(self._cmd("rcat", target), input=text,
                              text=True, capture_output=True, timeout=300)
        if proc.returncode != 0:
            raise BackupError(f"upload of {target} failed: {proc.stderr.strip()[-500:]}")

    def write_heartbeat(self, target, payload):
        self.write_text(target, json.dumps(payload, indent=2))

    def about(self):
        """{'used':…, 'total':…, 'free':…} of the Google Drive account, or None."""
        try:
            out = run(self._cmd("about", self.root.split(":", 1)[0] + ":", "--json"),
                      capture=True, low_priority=False)
            return json.loads(out)
        except (BackupError, ValueError):
            return None
