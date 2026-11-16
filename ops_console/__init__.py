"""
PRAX ERP Ops Console — a small separate web app (own login, own port) for:

  • Backups      run history, success/failure counts, run logs, restore tests
  • Restore      restore a backup into a new database, put pictures back,
                 switch the live ERP to a restored database (and back)
  • Alerts       who receives which alert email (all senders share one file)
  • Activity     audit log of every console action, background jobs

Separate from the ERP on purpose: it keeps working when the ERP database is
broken. Run:  gunicorn -w 1 --threads 8 -b 127.0.0.1:6791 "ops_console.app:create_app()"
Users:        python -m ops_console adduser <name>
"""

from erp_backup import __version__ as BACKUP_VERSION  # noqa: F401

__version__ = "1.1.0"
