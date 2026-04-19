# app/middleware/role_middleware.py

from flask_jwt_extended import get_jwt,get_jwt_identity
from functools import wraps

def require_super_admin(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        user = get_jwt_identity()

        user_id = get_jwt_identity()
        claims = get_jwt()

        if not user_id or claims.get("role") != "super_admin":
            return {"msg": "Access denied"}, 403

        return fn(*args, **kwargs)
    return wrapper