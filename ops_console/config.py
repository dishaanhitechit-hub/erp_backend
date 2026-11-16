"""Console settings — from /srv/prax-config/console.env (CONSOLE_ENV_FILE)
plus the backend .env (for the backup settings)."""

import os
import shlex
from dataclasses import dataclass


def _load_env_file():
    path = os.getenv("CONSOLE_ENV_FILE") or "/srv/prax-config/console.env"
    if os.path.isfile(path):
        from dotenv import load_dotenv
        load_dotenv(path, override=False)


@dataclass
class ConsoleConfig:
    secret_key: str
    data_dir: str
    users_file: str
    erp_env_file: str
    stop_cmd: list
    start_cmd: list
    health_url: str
    session_minutes: int
    cookie_secure: bool
    python: str
    backend_dir: str

    @property
    def audit_file(self):
        return os.path.join(self.data_dir, "audit.log")

    @property
    def jobs_dir(self):
        return os.path.join(self.data_dir, "jobs")

    @property
    def staging_dir(self):
        return os.path.join(self.data_dir, "staging")

    @property
    def switch_file(self):
        return os.path.join(self.data_dir, "switch_history.json")

    @property
    def created_dbs_file(self):
        return os.path.join(self.data_dir, "created_databases.json")


def load():
    _load_env_file()
    secret = os.getenv("CONSOLE_SECRET_KEY") or ""
    if len(secret) < 32:
        raise RuntimeError("CONSOLE_SECRET_KEY missing or shorter than 32 characters "
                           "(set it in /srv/prax-config/console.env)")
    backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    data_dir = os.path.abspath(os.getenv("CONSOLE_DATA_DIR") or "/srv/prax-config/console")
    return ConsoleConfig(
        secret_key=secret,
        data_dir=data_dir,
        users_file=os.getenv("CONSOLE_USERS_FILE") or os.path.join(data_dir, "users.json"),
        erp_env_file=os.getenv("ERP_ENV_FILE") or os.path.join(backend_dir, ".env"),
        stop_cmd=shlex.split(os.getenv("CONSOLE_ERP_STOP_CMD") or "sudo -n systemctl stop backend.service"),
        start_cmd=shlex.split(os.getenv("CONSOLE_ERP_START_CMD") or "sudo -n systemctl start backend.service"),
        health_url=os.getenv("CONSOLE_ERP_HEALTH_URL") or "http://127.0.0.1:5000/health/ready",
        session_minutes=int(os.getenv("CONSOLE_SESSION_MINUTES") or 30),
        cookie_secure=(os.getenv("CONSOLE_COOKIE_SECURE") or "false").lower() == "true",
        python=os.getenv("CONSOLE_PYTHON") or os.path.join(backend_dir, "venv", "bin", "python"),
        backend_dir=backend_dir,
    )
