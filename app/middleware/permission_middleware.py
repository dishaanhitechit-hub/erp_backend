from functools import wraps

from flask_jwt_extended import (
    verify_jwt_in_request,
    get_jwt
)

from app.response import res


def page_permission(
        page_code,
        action
):

    def decorator(fn):

        @wraps(fn)

        def wrapper(
                *args,
                **kwargs
        ):

            verify_jwt_in_request()

            claims=get_jwt()

            permissions=claims.get(
                "permissions",
                {}
            )

            key=(
                f"{page_code}."
                f"{action}"
            )

            if not permissions.get(
                key,
                False
            ):

                return res(
                    "Access denied",
                    [],
                    403
                )

            return fn(
                *args,
                **kwargs
            )

        return wrapper

    return decorator