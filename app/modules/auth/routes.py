# app/modules/auth/routes.py

from flask import Blueprint, request
from .service import login_user, logout_user
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