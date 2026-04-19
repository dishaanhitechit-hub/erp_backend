# app/modules/auth/routes.py

from flask import Blueprint, request
from .service import login_user

auth_bp = Blueprint("auth", __name__)

@auth_bp.route("/login", methods=["POST"])
def login():
    data = request.get_json()

    loginUserName = data.get("loginUserName")
    password = data.get("password")

    return login_user(loginUserName, password)