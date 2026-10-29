# app/modules/auth/service.py

import secrets
from app.models.user import User
from app.models.tokenBlocklist import TokenBlocklist
from app.extensions import db
from app.response import res
from flask_jwt_extended import create_access_token, get_jwt
from app.modules.auth import otp_store
from app.modules.communication.whatsapp_service import send_otp

# { reset_token: login_username }
_reset_tokens: dict = {}


def logout_user():
    jti = get_jwt().get("jti")
    try:
        db.session.add(TokenBlocklist(jti=jti))
        db.session.commit()
        return res("Logged out successfully", [])
    except Exception:
        db.session.rollback()
        return res("Logout failed", [], code=500)


def login_user(loginUserName, password):
    user = User.query.filter_by(login_username =  loginUserName).first()

    if not user or not user.check_password(password):
        return res ("Invalid Credential", code = 401)

    #  info in token

    token = create_access_token(
        identity = str(user.id),
        additional_claims={
            "username": user.login_username,
            "role": user.global_role.name if user.global_role else None

        }
        
    )

    data = [ {"token" : token ,"id": user.id,
            "username": user.username,
            "role": user.global_role.name if user.global_role else None
        }
    ]


    return res("Succesfully Loggin", data)


def forgot_password(login_username: str):
    user = User.query.filter_by(login_username=login_username).first()
    if not user:
        return res("If this account exists, an OTP has been sent", [])

    otp = otp_store.generate_and_store(login_username)

    import threading
    t = threading.Thread(target=send_otp, args=(user.wp_mobile, otp), daemon=True)
    t.start()

    return res("OTP sent to your registered WhatsApp number", [])


def verify_otp(login_username: str, otp: str):
    if not otp_store.verify_and_consume(login_username, otp):
        return res("Invalid or expired OTP", code=400)

    reset_token = secrets.token_urlsafe(32)
    _reset_tokens[reset_token] = login_username
    return res("OTP verified", [{"reset_token": reset_token}])


def reset_password(reset_token: str, new_password: str):
    login_username = _reset_tokens.pop(reset_token, None)
    if not login_username:
        return res("Invalid or expired reset token", code=400)

    user = User.query.filter_by(login_username=login_username).first()
    if not user:
        return res("User not found", code=404)

    try:
        user.set_password(new_password)
        db.session.commit()
        return res("Password reset successfully", [])
    except Exception:
        db.session.rollback()
        return res("Failed to reset password", code=500)

