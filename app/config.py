import os

class Config:
    SECRET_KEY = os.getenv("SECRET_KEY") or "super-secret"
    JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY") or "jwt-super-secret"

    DB_USER = os.getenv("DB_USER")
    DB_PASSWORD = os.getenv("DB_PASSWORD")
    DB_HOST = os.getenv("DB_HOST")
    DB_NAME = os.getenv("DB_NAME")
    DB_PORT = os.getenv("DB_PORT")
    JWT_ACCESS_TOKEN_EXPIRES = False
    SQLALCHEMY_DATABASE_URI = (
        f"postgresql://postgres:JoFJPHzrFFzKosJdRnneXRYLtUxjiTWe@yamabiko.proxy.rlwy.net:57509/railway"
    )

    # SQLALCHEMY_DATABASE_URI = (
    #     f"postgresql://dishaan:Blue#Skydishaan&99!@10.0.0.2:6432/dishaan_erp"
    # )

    # SQLALCHEMY_DATABASE_URI = os.getenv("DATABASE_URL")
    # if not SQLALCHEMY_DATABASE_URI:
    #     raise Exception("DATABASE_URL is missing or invalid")
    # SQLALCHEMY_TRACK_MODIFICATIONS = False

    # ── PDF LOCAL STORAGE ──────────────────────────────────────────
    # Change this path when moving to a different disk or mount point.
    # When BunnyCDN is back, replace the save_pdf_file() function in
    # pdf_service.py with the BunnyCDN upload — no other code changes needed.
    PDF_STORAGE_PATH = os.getenv("PDF_STORAGE_PATH") or os.path.join(os.getcwd(), "storage", "pdf")
    PDF_BASE_URL     = os.getenv("PDF_BASE_URL") or "/resource/order/pdf-file"
    # ───────────────────────────────────────────────────────────────
