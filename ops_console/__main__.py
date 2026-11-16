"""python -m ops_console <command>

  adduser NAME          create a console user / set a new password (asks twice)
  deluser NAME          remove a console user
  users                 list console users
  seed-recipients       create the alert recipients file from today's settings
                        (only if it does not exist yet)
"""

import argparse
import getpass
import os
import sys

from prax_ops import recipients

from . import auth, config


def current_lists(admin="", managers=""):
    """Today's lists, as the senders use them while no recipients file exists."""
    from erp_backup import config as backup_config
    s = backup_config.load()
    every = recipients.split_emails(admin) + [m for m in recipients.split_emails(managers)
                                              if m not in recipients.split_emails(admin)]
    fallbacks = {
        "server_alert": admin, "server_critical": managers, "server_recovery": every,
        "server_daily": every, "server_migration": every, "server_startup": every,
        "backup_failure": s.alert_emails, "backup_daily": s.alert_emails,
        "backup_restore_test": s.alert_emails, "console_activity": s.alert_emails,
    }
    for name in ("finance", "hr", "billing", "project", "project_mgmt", "resources", "master", "company"):
        fallbacks[f"monthly_{name}"] = os.getenv(f"MAIL_RECIPIENT_{name.upper()}", "")
    return fallbacks


def _seed(admin, managers):
    fallbacks = current_lists(admin, managers)
    if recipients.load() is not None:
        print(f"{recipients.path()} already exists — not changed")
        return
    recipients.seed(fallbacks, updated_by="seed")
    print(f"created {recipients.path()}")


def main(argv=None):
    p = argparse.ArgumentParser(prog="ops_console", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("adduser")
    a.add_argument("name")
    d = sub.add_parser("deluser")
    d.add_argument("name")
    sub.add_parser("users")
    sr = sub.add_parser("seed-recipients")
    sr.add_argument("--server-admin", default="", help="today's ADMIN_EMAIL of /opt/alerts/alert.py")
    sr.add_argument("--server-managers", default="", help="today's MANAGER_EMAILS, comma separated")
    args = p.parse_args(argv)
    cfg = config.load()
    try:
        if args.cmd == "adduser":
            pw = getpass.getpass(f"New password for {args.name} (min {auth.MIN_PASSWORD} chars): ")
            if pw != getpass.getpass("Again: "):
                raise ValueError("passwords do not match")
            auth.set_password(cfg.users_file, args.name, pw)
            print(f"user {args.name.lower()} saved")
        elif args.cmd == "deluser":
            auth.remove_user(cfg.users_file, args.name)
            print("removed")
        elif args.cmd == "users":
            print("\n".join(auth.list_users(cfg.users_file)) or "(no users)")
        elif args.cmd == "seed-recipients":
            _seed(args.server_admin, args.server_managers)
    except ValueError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
