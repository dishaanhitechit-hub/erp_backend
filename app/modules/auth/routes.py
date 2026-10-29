# app/modules/auth/routes.py

from flask import Blueprint, request
from .service import login_user, logout_user, forgot_password, verify_otp, reset_password
from app.middleware.auth_middleware import login_required

auth_bp = Blueprint("auth", __name__)

@auth_bp.route("/login", methods=["POST"])
def login():
    data = request.get_json()

    loginUserName = data.get("loginUserName")
    password = data.get("password")

    return login_user(loginUserName, password)


@auth_bp.route("/logout", methods=["POST"])
@login_required
def logout():
    return logout_user()


@auth_bp.route("/forgot-password", methods=["POST"])
def forgot_password_route():
    data = request.get_json()
    return forgot_password(data.get("loginUserName", "").strip())


@auth_bp.route("/verify-otp", methods=["POST"])
def verify_otp_route():
    data = request.get_json()
    return verify_otp(
        data.get("loginUserName", "").strip(),
        data.get("otp", "").strip(),
    )


@auth_bp.route("/reset-password", methods=["POST"])
def reset_password_route():
    data = request.get_json()
    return reset_password(
        data.get("reset_token", "").strip(),
        data.get("new_password", ""),
    )