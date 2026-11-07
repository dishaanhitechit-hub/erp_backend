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


def _find_user_by_identifier(identifier: str, password: str = None):
    """Find user by login_username or mobile/wp_mobile number."""
    from sqlalchemy import or_
    clean = identifier.strip().replace(" ", "").replace("-", "")
    is_mobile = (
        (clean.isdigit() and len(clean) in (10, 12))
        or (clean.startswith("+91") and clean[3:].isdigit() and len(clean[3:]) == 10)
    )
    if is_mobile:
        if clean.startswith("+91"):
            digits = clean[3:]
        elif clean.startswith("91") and len(clean) == 12:
            digits = clean[2:]
        else:
            digits = clean
        candidates = User.query.filter(
            or_(
                User.mobile == digits,
                User.mobile == "+91" + digits,
                User.wp_mobile == digits,
                User.wp_mobile == "+91" + digits,
            )
        ).all()
        if not candidates:
            return None
        # if multiple users share the same mobile, match by password
        if password:
            for u in candidates:
                if u.check_password(password):
                    return u
            return None
        return candidates[0]
    return User.query.filter_by(login_username=identifier.strip()).first()


def login_user(loginUserName, password):
    user = _find_user_by_identifier(loginUserName, password)

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


# ── Profile picture ──────────────────────────────────────────────────────────

PROFILE_PIC_EXTENSIONS = {"jpg", "jpeg", "png", "webp"}
PROFILE_PIC_MAX_BYTES = 5 * 1024 * 1024


def save_user_profile_picture(user, file):
    """Validate + upload `file` as `user`'s profile picture (does not commit).
    Returns (url, error_message). Used by /auth/profile-picture and the
    Settings → User create/update forms."""
    import time
    from app.cloudinary_uploader import upload_file_to_bunny, delete_file_from_storage

    if not file or not file.filename:
        return None, "No file provided"

    extension = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
    if extension not in PROFILE_PIC_EXTENSIONS:
        return None, "Profile photo: only JPG, PNG or WEBP images are allowed"

    file.stream.seek(0, 2)
    size = file.stream.tell()
    file.stream.seek(0)
    if size > PROFILE_PIC_MAX_BYTES:
        return None, "Profile photo must be 5 MB or smaller"

    # Same folder as the user's signature: users/<username>_<id>/
    url = upload_file_to_bunny(
        file=file,
        mainFolder="users",
        subFolder=f"{user.username}_{user.id}",
        fileName=f"profile_{int(time.time())}",
    )
    if not url:
        return None, "Profile photo upload failed"

    old_url = user.profile_picture
    user.profile_picture = url
    if old_url and old_url != url:
        delete_file_from_storage(old_url)
    return url, None


def upload_profile_picture(file):
    """Upload/replace the logged-in user's own profile picture."""
    from flask import g

    user = User.query.get(g.current_user["id"])
    if not user:
        return res("User not found", code=404)

    url, error = save_user_profile_picture(user, file)
    if error:
        return res(error, code=500 if error.endswith("failed") else 400)

    db.session.commit()
    return res("Profile picture updated", [{"id": user.id, "profilePicture": url}])


def get_me():
    """Basic info about the logged-in user (used for the navbar avatar)."""
    from flask import g

    user = User.query.get(g.current_user["id"])
    if not user:
        return res("User not found", code=404)
    return res("User fetched", [{
        "id": user.id,
        "username": user.username,
        "role": user.global_role.name if user.global_role else None,
        "profilePicture": user.profile_picture,
    }])


def get_user_file(user_id, kind):
    """Stream a user's profile picture / signature through the API (https),
    so the browser never needs the raw media URL."""
    import os
    from flask import g, send_file
    from app.cloudinary_uploader import local_path_from_url

    if kind not in ("profile", "signature"):
        return res("Not found", code=404)

    # Signatures are sensitive: only the owner or a super admin
    # (role read from the DB — project tokens don't carry the role claim)
    if kind == "signature" and g.current_user["id"] != user_id:
        me = User.query.get(g.current_user["id"])
        if not me or not me.global_role or me.global_role.name != "super_admin":
            return res("Forbidden", code=403)

    user = User.query.get(user_id)
    if not user:
        return res("User not found", code=404)

    url = user.profile_picture if kind == "profile" else user.signature
    path = local_path_from_url(url)
    if not path or not os.path.isfile(path):
        return res("File not found", code=404)

    response = send_file(path, max_age=0)
    response.headers["Cache-Control"] = "private, no-cache"
    return response

