"""Google Drive through rclone.

BACKUP_REMOTE should be an rclone *crypt* remote layered on a Google Drive
remote (see deploy/backup/README.md), so names and contents are encrypted
before they leave the server. Layout under BACKUP_REMOTE:

    sets/<backup_id>/          one complete backup set
    sets/<backup_id>.partial/  upload in progress (never treated as a backup)
    media/current/<label>/     (sync mode) mirror of uploaded files
    media/versions/<id>/       (sync mode) files changed/deleted at that run
"""

import json
import subprocess
from datetime import timedelta

from .util import BackupError, log, parse_set_id, run


class Remote:
    def __init__(self, settings):
        self.s = settings
        self.root = settings.remote
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

    def is_crypt(self):
        if self._crypt is None:
            name = self.root.split(":", 1)[0]
            out = run(self._cmd("listremotes", "--long"), capture=True, low_priority=False)
            types = dict(line.split(":", 1) for line in out.splitlines() if ":" in line)
            self._crypt = types.get(name, "").strip() == "crypt"
        return self._crypt

    # ── backup sets ──
    def list_sets(self):
        try:
            out = run(self._cmd("lsf", "--dirs-only", self.path("sets")), capture=True, low_priority=False)
        except BackupError as e:
            if "not found" in str(e).lower():
                return []
            raise
        return [line.rstrip("/") for line in out.splitlines() if line.strip()]

    def upload_set(self, set_path, name):
        final = self.path("sets", name)
        partial = final + ".partial"
        if name in self.list_sets():
            log.info("%s already on remote", name)
            return
        run(self._cmd("copy", set_path, partial, *self._transfer_flags()))
        # prove every byte arrived before calling it a backup
        if self.is_crypt():
            run(self._cmd("cryptcheck", set_path, partial, "--one-way"))
        else:
            run(self._cmd("check", set_path, partial, "--one-way"))
        run(self._cmd("moveto", partial, final))
        log.info("uploaded %s", name)

    def upload_file(self, local_file, remote_dir_name):
        run(self._cmd("copy", local_file, self.path("sets", remote_dir_name)))

    def download_set(self, name, dest):
        run(self._cmd("copy", self.path("sets", name), dest, *self._transfer_flags()))

    def delete_set(self, name):
        run(self._cmd("purge", self.path("sets", name)), low_priority=False)

    def cleanup_partials(self, now, older_than=timedelta(hours=12)):
        for name in self.list_sets():
            if not name.endswith(".partial"):
                continue
            when = parse_set_id(name[:-len(".partial")])
            if when and now - when > older_than:
                log.info("removing stale upload %s", name)
                self.delete_set(name)

    # ── media in sync mode ──
    def sync_media(self, sources, backup_id):
        for src in sources:
            run(self._cmd("sync", src.path, self.path("media", "current", src.label),
                          "--backup-dir", self.path("media", "versions", backup_id, src.label),
                          *self._transfer_flags()))

    def prune_media_versions(self, now, keep_days):
        try:
            out = run(self._cmd("lsf", "--dirs-only", self.path("media", "versions")),
                      capture=True, low_priority=False)
        except BackupError as e:
            if "not found" in str(e).lower():
                return
            raise
        for line in out.splitlines():
            name = line.rstrip("/")
            when = parse_set_id(name)
            if when and now - when > timedelta(days=keep_days):
                run(self._cmd("purge", self.path("media", "versions", name)), low_priority=False)

    # ── watchdog + capacity ──
    def write_heartbeat(self, target, payload):
        proc = subprocess.run(self._cmd("rcat", target), input=json.dumps(payload, indent=2),
                              text=True, capture_output=True, timeout=300)
        if proc.returncode != 0:
            raise BackupError(f"heartbeat upload failed: {proc.stderr.strip()[-500:]}")

    def about(self):
        """{'used':…, 'total':…, 'free':…} of the Google Drive account, or None."""
        try:
            out = run(self._cmd("about", self.root.split(":", 1)[0] + ":", "--json"),
                      capture=True, low_priority=False)
            return json.loads(out)
        except (BackupError, ValueError):
            return None
