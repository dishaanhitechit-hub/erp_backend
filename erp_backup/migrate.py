"""One-time move to the 1.2.0 names (`python -m erp_backup migrate-names`).

Before 1.2.0 sets were uploaded to a crypt remote with file-name encryption on,
as sets/erp_prod_20261118T020512+0530/, so Google Drive showed scrambled names.

This copies every old set from that remote (--from) into BACKUP_REMOTE (the new
crypt remote with readable names) under its Daily/Weekly/Monthly/Manual folder.
Contents stay encrypted the whole way; the data passes through this server
(nothing is written to its disk). Each copy is then read back in full and
compared with the original. Old sets are only deleted with --delete-old, and
only after that comparison passed.

It also renames old local set folders on the backup disk to the new ids.
Safe to run again: sets already copied are skipped (and still compared).
"""

import json
import os

from . import naming, retention
from .remote import Remote, parse_listing
from .runner import local_sets
from .util import BackupError, log, run


def _old_sets(old):
    """Old remote's sets (legacy sets/ layout and any new-style folders)."""
    return parse_listing(old._lsf_dirs(depth=3), getattr(old.s, "tz", None))


def _trigger(old, rs):
    try:
        out = run(old._cmd("cat", old.path(rs.path, "manifest.json")), capture=True, low_priority=False)
        return json.loads(out).get("trigger")
    except (BackupError, ValueError):
        return None


def plan(settings, old_sets, now, triggers):
    """[(RemoteSet, dest path)] — where each old set goes in the new layout."""
    keyed = [(rs.path, rs.when) for rs in old_sets]
    manual = [rs.path for rs in old_sets if triggers.get(rs.path) == "MANUAL" or rs.tier == "manual"]
    keep, delete = retention.types(keyed, now, settings.tz, manual=manual,
                                   daily_days=settings.keep_daily_days, weekly=settings.keep_weekly,
                                   monthly=settings.keep_monthly, min_keep=settings.min_keep)
    out = []
    for rs in old_sets:
        tier = keep.get(rs.path, "daily")          # retention will delete those it doesn't keep
        out.append((rs, naming.drive_path(settings.label, tier, rs.when.astimezone(settings.tz))))
    return out, set(delete)


def rename_local(settings, dry_run=False):
    """erp_prod_20261118T020512+0530 → PRAX-ERP_2026-11-18_0205 on the backup disk."""
    done = []
    for name, path in local_sets(settings):
        if not naming.LEGACY_RE.match(name):
            continue
        new = naming.set_id_for(settings.label, naming.parse_set_id(name).astimezone(settings.tz))
        target = os.path.join(os.path.dirname(path), new)
        if os.path.exists(target):
            log.warning("local %s: %s already exists — left as it is", name, new)
            continue
        if not dry_run:
            os.rename(path, target)
        done.append((name, new))
    return done


def migrate(settings, from_remote, now, delete_old=False, dry_run=False, say=print):
    if not settings.remote:
        raise BackupError("BACKUP_REMOTE (the new remote) is not set")
    from_remote = from_remote.rstrip("/")
    if from_remote == settings.remote:
        raise BackupError("--from is the same as BACKUP_REMOTE — point BACKUP_REMOTE at the new remote first")
    new, old = Remote(settings), Remote(settings, root=from_remote)

    old_sets = _old_sets(old)
    say(f"{len(old_sets)} backup set(s) in {from_remote}")
    triggers = {rs.path: _trigger(old, rs) for rs in old_sets}
    moves, retire = plan(settings, old_sets, now, triggers)
    existing = {rs.path for rs in new.list_sets()}
    copied = skipped = deleted = 0
    failed = []

    for rs, dest in moves:
        note = "  (older than the keep rules — the next backup will delete it)" if rs.path in retire else ""
        say(f"{rs.path}  →  {dest}{note}")
        if dry_run:
            continue
        try:
            if dest in existing:
                new.check_same(old, rs, dest)
                skipped += 1
                say("    already there, contents match")
            else:
                new.copy_set_from(old, rs, dest)
                existing.add(dest)
                copied += 1
                say("    copied, contents match")
            if delete_old:
                old.delete_set(rs)
                deleted += 1
                say("    old copy deleted")
        except BackupError as e:
            failed.append(rs.path)
            say(f"    FAILED: {e}  (old copy kept)")

    has_media = bool(old._lsf_dirs("media"))
    renamed = rename_local(settings, dry_run)
    for a, b in renamed:
        say(f"backup disk: {a}  →  {b}")

    say("")
    if dry_run:
        say("dry run — nothing was changed")
    else:
        say(f"copied {copied}, already there {skipped}, old deleted {deleted}, failed {len(failed)}")
        if not delete_old and not failed:
            say(f"Old copies are still in {from_remote}. When you are happy, run again with --delete-old.")
    if has_media:
        say(f"NOTE: {from_remote}/media (sync mode) was not copied. Copy it with:\n"
            f"  rclone copy {from_remote}/media {settings.remote}/media")
    return {"copied": copied, "skipped": skipped, "deleted": deleted, "failed": failed,
            "renamed_local": len(renamed)}
