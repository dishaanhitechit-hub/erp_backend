

from app.response import res

from flask_jwt_extended import (
    create_access_token
)

from app.modules.setting.permission_service import (
    get_user_permissions
)

from app.models.project import Project
from app.models.user import User


def enter_project(
        project_code,
        user_id
):

    project=Project.query.filter_by(
        project_code=project_code
    ).first()

    user=User.query.get(
        user_id
    )

    permissions=(
        get_user_permissions(
            project.id,
            user.id
        )
    )

    token=create_access_token(

        identity=str(
            user.id
        ),

        additional_claims={

            "projectId":
            project.id,

            "permissions":
            permissions
        }
    )

    return res(
        "success",

        [{
            "token":token,

            "permissions":
            permissions
        }]
    )