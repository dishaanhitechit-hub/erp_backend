# app/modules/auth/otp_store.py
"""
Password-reset OTP codes, shared by every worker (app/utils/runtime_store.py).
Same rules as before: 6 digits, valid 10 minutes, a correct code works once,
a wrong code does not use it up.
"""

import hmac
import secrets

from app.utils import runtime_store

OTP_TTL = 600  # 10 minutes


def _key(login_username: str) -> str:
    return f"otp:{login_username}"


def generate_and_store(login_username: str) -> str:
    otp = f"{secrets.randbelow(900000) + 100000}"  # 100000–999999, from a secure random source
    runtime_store.put(_key(login_username), {"otp": otp}, OTP_TTL)
    return otp


def verify_and_consume(login_username: str, otp: str) -> bool:
    entry = runtime_store.get(_key(login_username))
    if not entry or not otp:
        return False
    if not hmac.compare_digest(str(entry.get("otp", "")), str(otp)):
        return False
    # pop is atomic: if two requests send the right code at once, only one wins
    return runtime_store.pop(_key(login_username)) is not None
