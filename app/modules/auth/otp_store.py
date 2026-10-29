import random
import time

# { login_username: {"otp": "123456", "expires_at": timestamp} }
_store: dict = {}

OTP_TTL = 600  # 10 minutes


def generate_and_store(login_username: str) -> str:
    otp = str(random.randint(100000, 999999))
    _store[login_username] = {"otp": otp, "expires_at": time.time() + OTP_TTL}
    return otp


def verify_and_consume(login_username: str, otp: str) -> bool:
    entry = _store.get(login_username)
    if not entry:
        return False
    if time.time() > entry["expires_at"]:
        _store.pop(login_username, None)
        return False
    if entry["otp"] != otp:
        return False
    _store.pop(login_username, None)
    return True
