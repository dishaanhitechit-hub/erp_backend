import os
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))

class Config:
    SECRET_KEY = os.getenv("SECRET_KEY") or "super-secret"
    JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY") or "jwt-super-secret"
    JWT_ACCESS_TOKEN_EXPIRES = False
    SQLALCHEMY_DATABASE_URI = (
        f"postgresql://{os.getenv('DB_USER')}:{os.getenv('DB_PASSWORD')}@{os.getenv('DB_HOST')}:{os.getenv('DB_PORT')}/{os.getenv('DB_NAME')}"
    )
    PDF_STORAGE_PATH = os.getenv("PDF_STORAGE_PATH") or os.path.join(os.getcwd(), "storage", "pdf")
    PDF_BASE_URL = os.getenv("PDF_BASE_URL") or "/resource/order/pdf-file"
