"""
ERP backup tool — full backup of the PostgreSQL database and every uploaded
file (pictures, documents, signatures, logos), kept on a local backup disk and
copied (encrypted, via rclone) to Google Drive.

Runs on its own, outside the web app:  python -m erp_backup <command>
See deploy/backup/README.md for setup and DB_BACKUP_PLAN.md for the design.
Version history and the files of each release: erp_backup/CHANGELOG.md
"""

__version__ = "1.2.0"
