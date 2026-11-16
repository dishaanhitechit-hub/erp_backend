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


def smtp_settings(path=None):
    env = read_env_file(path or os.getenv("PRAX_ALERTS_ENV") or DEFAULT_PATH)
    get = lambda k, d="": os.getenv(k) or env.get(k) or d  # noqa: E731
    return {
        "user": get("ALERT_SMTP_USER"),
        "password": get("ALERT_SMTP_PASSWORD"),
        "host": get("ALERT_SMTP_HOST", "smtp.gmail.com"),
        "port": int(get("ALERT_SMTP_PORT", "587")),
    }
