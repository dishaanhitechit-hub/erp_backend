import os
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))

class Config:
    SECRET_KEY = os.getenv("SECRET_KEY") or "super-secret"
    JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY") or "jwt-super-secret"
    JWT_ACCESS_TOKEN_EXPIRES = False  # testing phase — tokens don't auto-expire
    # JWT_ACCESS_TOKEN_EXPIRES = timedelta(hours=48)  # enable for production (import timedelta from datetime)
    SQLALCHEMY_DATABASE_URI = (
        f"postgresql://{os.getenv('DB_USER')}:{os.getenv('DB_PASSWORD')}@{os.getenv('DB_HOST')}:{os.getenv('DB_PORT')}/{os.getenv('DB_NAME')}"
    )
    PDF_STORAGE_PATH = os.getenv("PDF_STORAGE_PATH") or os.path.join(os.getcwd(), "storage", "pdf")
    PDF_BASE_URL = os.getenv("PDF_BASE_URL") or "/resource/order/pdf-file"
    PUBLIC_BASE_URL  = os.getenv("PUBLIC_BASE_URL") or None

    # ── Monthly Email Reports ────────────────────────────────────────────────
    MAIL_SENDER       = os.getenv("MAIL_SENDER", "dishaanhitechit@gmail.com")
    MAIL_APP_PASSWORD = os.getenv("MAIL_APP_PASSWORD", "")
    MAIL_SCHEDULE_DAY  = int(os.getenv("MAIL_SCHEDULE_DAY",  "1"))   # 1 = 1st of month
    MAIL_SCHEDULE_HOUR = int(os.getenv("MAIL_SCHEDULE_HOUR", "8"))   # 8 AM
    MAIL_TIMEZONE      = os.getenv("MAIL_TIMEZONE", "Asia/Kolkata")

    # Recipients (comma-separated for multiple addresses)
    MAIL_RECIPIENT_FINANCE      = os.getenv("MAIL_RECIPIENT_FINANCE",      "")
    MAIL_RECIPIENT_HR           = os.getenv("MAIL_RECIPIENT_HR",           "")
    MAIL_RECIPIENT_BILLING      = os.getenv("MAIL_RECIPIENT_BILLING",      "")
    MAIL_RECIPIENT_PROJECT      = os.getenv("MAIL_RECIPIENT_PROJECT",      "")
    MAIL_RECIPIENT_PROJECT_MGMT = os.getenv("MAIL_RECIPIENT_PROJECT_MGMT", "")
    MAIL_RECIPIENT_RESOURCES    = os.getenv("MAIL_RECIPIENT_RESOURCES",    "")
    MAIL_RECIPIENT_MASTER       = os.getenv("MAIL_RECIPIENT_MASTER",       "")
    MAIL_RECIPIENT_COMPANY      = os.getenv("MAIL_RECIPIENT_COMPANY",      "")

