import os

class Config:
    SECRET_KEY = os.getenv("SECRET_KEY")
    JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY")

    DB_USER = os.getenv("DB_USER")
    DB_PASSWORD = os.getenv("DB_PASSWORD")
    DB_HOST = os.getenv("DB_HOST")
    DB_NAME = os.getenv("DB_NAME")
    DB_PORT = os.getenv("DB_PORT")
    JWT_ACCESS_TOKEN_EXPIRES = False
    SQLALCHEMY_DATABASE_URI = (
        f"postgresql://postgres:RdhKCuXIPXHDwIMGfTfSfOLPyWjRazSc@hopper.proxy.rlwy.net:18844/railway"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False