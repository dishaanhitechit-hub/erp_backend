# app/middleware/auth_middleware.py

from functools import wraps
from flask import g
from flask_jwt_extended import (
    verify_jwt_in_request,
    get_jwt_identity,
    get_jwt
)

def login_required(fn):

    @wraps(fn)
    def wrapper(
            *args,
            **kwargs
    ):

        verify_jwt_in_request()

        claims = get_jwt()

        g.current_user = {

            "id":
            int(
                get_jwt_identity()
            ),

            "username":
            claims.get(
                "username"
            ),

            "role":
            claims.get(
                "role"
            ),

            "projectId":
            claims.get(
                "projectId"
            )
        }

        return fn(
            *args,
            **kwargs
        )

    return wrapper