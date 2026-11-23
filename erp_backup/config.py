"""All settings come from environment variables (the backend .env is loaded too).

Only the variables in .env.backup.example need to be set; everything else has a
safe default.
"""

import os
from dataclasses import dataclass, field
from datetime import time
from zoneinfo import ZoneInfo

from .naming import LABEL_RE

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load_env_file():
    path = os.getenv("BACKUP_ENV_FILE") or os.path.join(ROOT, ".env")
    try:
        from dotenv import load_dotenv
    except ImportError:  # pragma: no cover - dotenv is in requirements.txt
        return
    if os.path.isfile(path):
        load_dotenv(path, override=False)


def _int(name, default):
    raw = (os.getenv(name) or "").strip()
    return int(raw) if raw else default


def _float(name, default):
    raw = (os.getenv(name) or "").strip()
    return float(raw) if raw else default


def _list(name, default=""):
    raw = os.getenv(name)
    raw = default if raw is None else raw
    return [p.strip() for p in raw.split(",") if p.strip()]


@dataclass(frozen=True)
class Window:
    """A daily backup window, e.g. 22:00-04:00 (may cross midnight)."""
    start: time
    end: time

    @classmethod
    def parse(cls, text):
        a, b = text.split("-")
        h1, m1 = (int(x) for x in a.strip().split(":"))
        h2, m2 = (int(x) for x in b.strip().split(":"))
        return cls(time(h1, m1), time(h2, m2))

    def __str__(self):
        return f"{self.start:%H:%M}-{self.end:%H:%M}"


@dataclass(frozen=True)
class MediaSource:
    """A folder of uploaded files; `label` is its top-level name inside the archive."""
    label: str
    path: str


@dataclass
class Settings:
    env_name: str
    tz: ZoneInfo
    local_dir: str
    local_keep: int

    # database (a read-only role is enough for backups)
    db_host: str
    db_port: str
    db_name: str
    db_user: str
    db_password: str
    # admin connection for `verify` / `restore` (needs CREATEDB); defaults to the app's DB_USER
    admin_user: str
    admin_password: str

    media_sources: list
    media_base_url: str
    media_mode: str             # "full" = whole archive every run, "sync" = rclone mirror
    media_full_warn_gb: float

    remote: str                 # rclone remote path, e.g. erpcrypt:prod  ("" = local only)
    heartbeat_remote: str       # plain (unencrypted) file the Drive watchdog reads
    rclone_bin: str
    rclone_bwlimit: str
    rclone_config: str

    windows: list
    max_gap_hours: float
    skip_if_recent_hours: float
    retry_minutes: int
    deadline_margin_minutes: int
    idle_minutes: int
    idle_max_db_active: int
    idle_max_load: float
    idle_max_iowait: float
    idle_quiet_minutes: int
    access_log: str

    keep_daily_days: int
    keep_weekly: int
    keep_monthly: int
    min_keep: int
    media_versions_days: int

    plain_sql_weekday: int      # 0=Mon … 6=Sun; -1 = never
    alert_emails: list
    mail_sender: str
    mail_password: str
    smtp_host: str
    smtp_port: int
    summary_hour: int

    pg_bin_dir: str = ""
    label: str = "PRAX-ERP"     # start of every backup name, e.g. PRAX-ERP_daily_2026-11-24_0215
    extra: dict = field(default_factory=dict)

    def pg(self, tool):
        return os.path.join(self.pg_bin_dir, tool) if self.pg_bin_dir else tool

    def pg_env(self, admin=False):
        env = dict(os.environ)
        env["PGPASSWORD"] = self.admin_password if admin else self.db_password
        env.setdefault("PGCONNECT_TIMEOUT", "20")
        return env

    def pg_args(self, admin=False, dbname=None):
        return ["-h", self.db_host, "-p", str(self.db_port),
                "-U", self.admin_user if admin else self.db_user,
                "-d", dbname or self.db_name]

    def psycopg_kwargs(self, admin=False, dbname=None):
        return dict(host=self.db_host, port=self.db_port, dbname=dbname or self.db_name,
                    user=self.admin_user if admin else self.db_user,
                    password=self.admin_password if admin else self.db_password,
                    connect_timeout=20, application_name="erp_backup")


def _media_sources():
    explicit = _list("BACKUP_MEDIA_DIRS")
    sources = []
    if explicit:
        for item in explicit:
            label, _, path = item.partition("=")
            if not path:
                path, label = label, os.path.basename(os.path.normpath(label)) or "media"
            sources.append(MediaSource(label.strip(), os.path.abspath(path.strip())))
    else:
        base = os.getenv("MEDIA_BASE_PATH")
        if base:
            sources.append(MediaSource("media", os.path.abspath(base)))
        uploads = os.path.join(ROOT, "uploads")       # signatures, company logos
        if os.path.isdir(uploads):
            sources.append(MediaSource("uploads", uploads))
    labels = [s.label for s in sources]
    if len(labels) != len(set(labels)):
        raise ValueError(f"BACKUP_MEDIA_DIRS labels must be unique: {labels}")
    return sources


def load():
    _load_env_file()
    tz = ZoneInfo(os.getenv("BACKUP_TIMEZONE") or os.getenv("MAIL_TIMEZONE") or "Asia/Kolkata")
    db_user = os.getenv("BACKUP_DB_USER") or os.getenv("DB_USER") or ""
    db_password = os.getenv("BACKUP_DB_PASSWORD") or os.getenv("DB_PASSWORD") or ""
    media_mode = (os.getenv("BACKUP_MEDIA_MODE") or "full").strip().lower()
    if media_mode not in ("full", "sync"):
        raise ValueError("BACKUP_MEDIA_MODE must be 'full' or 'sync'")
    env_name = os.getenv("BACKUP_ENV") or "prod"
    label = (os.getenv("BACKUP_LABEL") or ("PRAX-ERP" if env_name == "prod" else f"PRAX-ERP-{env_name}")).strip()
    if not LABEL_RE.match(label):
        raise ValueError("BACKUP_LABEL: letters, digits and '-' only, starting with a letter (no spaces or _)")
    return Settings(
        env_name=env_name,
        label=label,
        tz=tz,
        local_dir=os.path.abspath(os.getenv("BACKUP_LOCAL_DIR") or "/backup/erp"),
        local_keep=_int("BACKUP_LOCAL_KEEP", 2),
        db_host=os.getenv("BACKUP_DB_HOST") or os.getenv("DB_HOST") or "127.0.0.1",
        db_port=os.getenv("BACKUP_DB_PORT") or os.getenv("DB_PORT") or "5432",
        db_name=os.getenv("BACKUP_DB_NAME") or os.getenv("DB_NAME") or "",
        db_user=db_user,
        db_password=db_password,
        admin_user=os.getenv("BACKUP_ADMIN_DB_USER") or os.getenv("DB_USER") or db_user,
        admin_password=os.getenv("BACKUP_ADMIN_DB_PASSWORD") or os.getenv("DB_PASSWORD") or db_password,
        media_sources=_media_sources(),
        media_base_url=os.getenv("MEDIA_BASE_URL") or "",
        media_mode=media_mode,
        media_full_warn_gb=_float("BACKUP_MEDIA_FULL_WARN_GB", 20),
        remote=(os.getenv("BACKUP_REMOTE") or "").rstrip("/"),
        heartbeat_remote=os.getenv("BACKUP_HEARTBEAT_REMOTE") or "",
        rclone_bin=os.getenv("BACKUP_RCLONE_BIN") or "rclone",
        rclone_bwlimit=os.getenv("BACKUP_RCLONE_BWLIMIT") or "",
        rclone_config=os.getenv("BACKUP_RCLONE_CONFIG") or "",
        windows=[Window.parse(w) for w in _list("BACKUP_WINDOWS", "12:30-16:30,22:00-04:00")],
        max_gap_hours=_float("BACKUP_MAX_GAP_HOURS", 12),
        skip_if_recent_hours=_float("BACKUP_SKIP_IF_RECENT_HOURS", 6),
        retry_minutes=_int("BACKUP_RETRY_MINUTES", 30),
        deadline_margin_minutes=_int("BACKUP_DEADLINE_MARGIN_MINUTES", 15),
        idle_minutes=_int("BACKUP_IDLE_MINUTES", 10),
        idle_max_db_active=_int("BACKUP_IDLE_MAX_DB_ACTIVE", 2),
        idle_max_load=_float("BACKUP_IDLE_MAX_LOAD", 0.5),
        idle_max_iowait=_float("BACKUP_IDLE_MAX_IOWAIT", 10),
        idle_quiet_minutes=_int("BACKUP_IDLE_QUIET_MINUTES", 5),
        access_log=os.getenv("BACKUP_ACCESS_LOG") or "",
        keep_daily_days=_int("BACKUP_KEEP_DAILY_DAYS", 7),
        keep_weekly=_int("BACKUP_KEEP_WEEKLY", 4),
        keep_monthly=_int("BACKUP_KEEP_MONTHLY", 6),
        min_keep=_int("BACKUP_MIN_KEEP", 3),
        media_versions_days=_int("BACKUP_MEDIA_VERSIONS_DAYS", 90),
        plain_sql_weekday=_int("BACKUP_PLAIN_SQL_WEEKDAY", 6),
        alert_emails=_list("BACKUP_ALERT_EMAILS"),
        mail_sender=os.getenv("BACKUP_MAIL_SENDER") or os.getenv("MAIL_SENDER") or "",
        mail_password=os.getenv("BACKUP_MAIL_PASSWORD") or os.getenv("MAIL_APP_PASSWORD") or "",
        smtp_host=os.getenv("BACKUP_SMTP_HOST") or "smtp.gmail.com",
        smtp_port=_int("BACKUP_SMTP_PORT", 465),
        summary_hour=_int("BACKUP_SUMMARY_HOUR", 9),
        pg_bin_dir=os.getenv("BACKUP_PG_BIN_DIR") or "",
    )
