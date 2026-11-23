"""python -m erp_backup <command>

  tick                      run by the systemd timer every 5 min (decides by itself)
  run                       take a backup now (e.g. before an upgrade)
  status                    last runs, next window, disk usage
  list [--remote]           backup sets on the backup disk / Google Drive
  verify [--set ID] [--from-remote] [--keep-db]
                            restore test into a throw-away DB (weekly timer)
  restore --set ID --target-db NEW_DB [--media-dir DIR] [--from-remote]
                            emergency restore into a NEW database
  migrate-names --from OLD_REMOTE [--dry-run] [--delete-old]
                            one-time: copy pre-1.2.0 sets (scrambled names) into
                            BACKUP_REMOTE with readable names and Daily/Weekly/Monthly folders
  idle                      show whether the server counts as idle now
  test-email                send a test alert e-mail
"""

import argparse
import json
import logging
import logging.handlers
import os
import sys
from datetime import datetime

from . import __version__, config, emails, idle, notify, recovery, runner, schedule
from . import state as st
from .remote import Remote
from .util import BackupError, log


def _setup_logging(settings, verbose):
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    log.setLevel(logging.INFO)
    console = logging.StreamHandler()
    console.setFormatter(fmt)
    console.setLevel(logging.INFO if verbose else logging.WARNING)
    log.addHandler(console)
    try:
        log_dir = os.path.join(settings.local_dir, "logs")
        os.makedirs(log_dir, exist_ok=True)
        fh = logging.handlers.TimedRotatingFileHandler(
            os.path.join(log_dir, "backup.log"), when="midnight", backupCount=90)
        fh.setFormatter(fmt)
        log.addHandler(fh)
    except OSError as e:
        log.warning("cannot write log file: %s", e)


def cmd_status(settings):
    state = st.load(settings)
    now = datetime.now(settings.tz)
    print(runner.summary_text(settings, state, now))
    d = state.get("last_decision")
    if d:
        print(f"Last scheduler check: {d['at'][:16]} → {d['reason']}")
    win = schedule.active_window(now, settings.windows)
    print(f"Backup windows: {', '.join(map(str, settings.windows))}"
          f"  (now {'inside ' + str(win[0]) if win else 'outside'})")
    print(f"Tool version: {__version__}")
    print(f"Media mode: {settings.media_mode}   Sources: "
          + (", ".join(f"{m.label}={m.path}" for m in settings.media_sources) or "NONE"))


def cmd_list(settings, remote):
    if remote:
        if not settings.remote:
            raise BackupError("BACKUP_REMOTE not set")
        for rs in Remote(settings).list_sets():
            print(f"{rs.id:<28} {rs.tier:<8} {rs.path}")
        return
    for name, path in runner.local_sets(settings):
        uploaded = os.path.exists(os.path.join(path, runner.UPLOADED_MARK))
        verified = os.path.exists(os.path.join(path, "verified.json"))
        print(f"{name}  drive={'yes' if uploaded else 'no '}  verified={'yes' if verified else 'no'}")


def main(argv=None):
    p = argparse.ArgumentParser(prog="erp_backup", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("-v", "--verbose", action="store_true")
    p.add_argument("--version", action="version", version=f"erp_backup {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("tick")
    sub.add_parser("run")
    sub.add_parser("status")
    pl = sub.add_parser("list")
    pl.add_argument("--remote", action="store_true")
    pv = sub.add_parser("verify")
    pv.add_argument("--set")
    pv.add_argument("--from-remote", action="store_true")
    pv.add_argument("--keep-db", action="store_true")
    pv.add_argument("--no-email", action="store_true")
    pr = sub.add_parser("restore")
    pr.add_argument("--set", help="backup id (default: newest)")
    pr.add_argument("--target-db", required=True)
    pr.add_argument("--media-dir")
    pr.add_argument("--from-remote", action="store_true")
    pr.add_argument("--jobs", type=int, default=4)
    pm = sub.add_parser("migrate-names")
    pm.add_argument("--from", dest="from_remote", required=True,
                    help="the old rclone remote, e.g. erpcrypt:prod")
    pm.add_argument("--dry-run", action="store_true", help="only show what would happen")
    pm.add_argument("--delete-old", action="store_true",
                    help="delete each old set after its copy was compared and matches")
    sub.add_parser("idle")
    pt = sub.add_parser("test-email")
    pt.add_argument("--category", default="backup_failure")
    args = p.parse_args(argv)

    settings = config.load()
    _setup_logging(settings, args.verbose or args.cmd not in ("tick",))

    try:
        if args.cmd == "tick":
            runner.tick(settings)
        elif args.cmd == "run":
            with runner.lock_for(settings) as got:
                if not got:
                    raise BackupError("another backup is running")
                result = runner.run_backup(settings, "MANUAL", st.load(settings))
            print(json.dumps({k: result.get(k) for k in
                              ("backup_id", "status", "uploaded", "error", "warnings")}, indent=2))
            return 0 if result["status"] == "SUCCESS" else 1
        elif args.cmd == "status":
            cmd_status(settings)
        elif args.cmd == "list":
            cmd_list(settings, args.remote)
        elif args.cmd == "verify":
            with runner.lock_for(settings) as got:
                if not got:
                    raise BackupError("a backup is running — try later")
                report = recovery.verify(settings, args.set, args.from_remote,
                                         keep_db=args.keep_db, email=not args.no_email)
            print(recovery.format_report(report))
            return 0 if report["status"] == "PASSED" else 1
        elif args.cmd == "restore":
            out = recovery.restore(settings, args.set, args.target_db, args.media_dir,
                                   args.from_remote, args.jobs)
            print(json.dumps(out, indent=2, ensure_ascii=False))
            print("\nNext: check the data, then set DB_NAME to the new database in .env, "
                  "move the media folders into place, and restart the app.")
        elif args.cmd == "migrate-names":
            from . import migrate
            with runner.lock_for(settings) as got:
                if not got:
                    raise BackupError("a backup is running — try later")
                out = migrate.migrate(settings, args.from_remote, datetime.now(settings.tz),
                                      delete_old=args.delete_old, dry_run=args.dry_run)
            return 1 if out["failed"] else 0
        elif args.cmd == "idle":
            ok, details = idle.probe(settings)
            print(json.dumps({"idle": ok, **details}, indent=2))
        elif args.cmd == "test-email":
            subject, html, text = emails.test_message(settings, args.category)
            sent = notify.send(settings, subject, text, html, category=args.category)
            print("sent" if sent else "NOT sent — see log above")
            return 0 if sent else 1
    except BackupError as e:
        log.error("%s", e)
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
