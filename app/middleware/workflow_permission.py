from functools import wraps
from flask import request,g
from app.response import res
from app.modules.work_flow import (
    has_workflow_access,validate_approver
)


def require_creator(
        module_code
):

    def decorator(f):

        @wraps(f)
        def wrapper(
            *args,
            **kwargs
        ):

            data=(

                request.get_json(
                    silent=True
                )

                or {}

            )

            project_code=(

                data.get(
                    "projectCode"
                )

                or

                request.args.get(
                    "projectCode"
                )
            )

            if not project_code:

                return res(

                    "projectCode required",

                    [],

                    400
                )

            user_id=(

                g.current_user.get(
                    "id"
                )
            )

            allowed=(

                has_workflow_access(

                    project_code,

                    module_code,

                    user_id,

                    "CREATOR"
                )
            )

            if not allowed:

                return res(

                    "No creator permission",

                    [],

                    403
                )

            return f(
                *args,
                **kwargs
            )

        return wrapper

    return decorator

def require_approver(
        module_code
):

    def decorator(f):

        @wraps(f)
        def wrapper(
            *args,
            **kwargs
        ):

            data=(

                request.get_json(
                    silent=True
                )

                or {}

            )

            project_code=(

                data.get(
                    "projectCode"
                )

                or

                request.args.get(
                    "projectCode"
                )
            )

            current_level=(

                data.get(
                    "currentLevel"
                )
            )

            if not project_code:

                return res(

                    "projectCode required",

                    [],

                    400
                )

            if current_level is None:

                return res(

                    "currentLevel required",

                    [],

                    400
                )

            user_id=(

                g.current_user.get(
                    "id"
                )
            )

            allowed=(

                validate_approver(

                    project_code,

                    module_code,

                    current_level,

                    user_id
                )
            )

            if not allowed:

                return res(

                    "You are not current approver",

                    [],

                    403
                )

            return f(
                *args,
                **kwargs
            )

        return wrapper

    return decorator