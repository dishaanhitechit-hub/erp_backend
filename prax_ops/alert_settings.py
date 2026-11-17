"""SMTP settings for the server alert scripts, kept OUT of the code in
/srv/prax-config/alerts.env (chmod 600):

    ALERT_SMTP_USER=dishaanhitechit.server@gmail.com
    ALERT_SMTP_PASSWORD=<gmail app password>
    ALERT_SMTP_HOST=smtp.gmail.com
    ALERT_SMTP_PORT=587

Standard library only (the alert scripts run with the system python3).
"""

import os

DEFAULT_PATH = "/srv/prax-config/alerts.env"


def read_env_file(path):
    values = {}
    try:
        with open(path) as f:
            for ln in f:
                ln = ln.strip()
                if not ln or ln.startswith("#") or "=" not in ln:
                    continue
                k, v = ln.split("=", 1)
                values[k.strip()] = v.strip().strip('"').strip("'")
    except OSError:
        pass
    return values


def db_env(app_dir):
    """PG* variables for one app's database, from its .env (DB_* or DATABASE_URL).
    Lets the alert scripts read a database as the app's own user (no sudo).
    DB_* wins: the ERP builds its connection from DB_* and its DATABASE_URL is stale."""
    from urllib.parse import unquote, urlparse
    env = read_env_file(os.path.join(app_dir, ".env"))
    url = env.get("DATABASE_URL") or env.get("SQLALCHEMY_DATABASE_URI")
    if env.get("DB_NAME"):
        out = {"PGHOST": env.get("DB_HOST", "127.0.0.1"), "PGPORT": env.get("DB_PORT", "5432"),
               "PGUSER": env.get("DB_USER", ""), "PGPASSWORD": env.get("DB_PASSWORD", ""),
               "PGDATABASE": env["DB_NAME"]}
    elif url:
        u = urlparse(url)
        out = {"PGHOST": u.hostname or "127.0.0.1", "PGPORT": str(u.port or 5432),
               "PGUSER": unquote(u.username or ""), "PGPASSWORD": unquote(u.password or ""),
               "PGDATABASE": u.path.lstrip("/")}
    else:
        return {}
    return {k: v for k, v in out.items() if v}


def alembic_version(app_dir):
    """The app's current migration version, or "" if it cannot be read."""
    import subprocess
    env = db_env(app_dir)
    if not env.get("PGDATABASE"):
        return ""
    try:
        r = subprocess.run(["psql", "-tAc", "SELECT version_num FROM alembic_version;"],
                           env={**os.environ, **env}, capture_output=True, text=True, timeout=10)
        return r.stdout.strip() if r.returncode == 0 else ""
    except Exception:
        return ""


def smtp_settings(path=None):
    env = read_env_file(path or os.getenv("PRAX_ALERTS_ENV") or DEFAULT_PATH)
    get = lambda k, d="": os.getenv(k) or env.get(k) or d  # noqa: E731
    return {
        "user": get("ALERT_SMTP_USER"),
        "password": get("ALERT_SMTP_PASSWORD"),
        "host": get("ALERT_SMTP_HOST", "smtp.gmail.com"),
        "port": int(get("ALERT_SMTP_PORT", "587")),
    }
