from app.models.project_role import ProjectUserRole
from app.models.project_designation_permission import ProjectDesignationPermission
from app.models.project_user_permission import ProjectUserPermission
from app.models.feature_page import FeaturePage
from app.models.permission_action import PermissionAction
from app.extensions import db


def get_user_permissions(
        project_id,
        user_id
):

    permission_map={}

    roles=ProjectUserRole.query.filter_by(
        project_id=project_id,
        user_id=user_id
    ).all()

    designation_ids=[
        r.designation_id
        for r in roles
    ]

    role_ids=[r.id for r in roles]

    designation_permissions=(

        db.session.query(
            FeaturePage.page_code,
            PermissionAction.action_name,
            ProjectDesignationPermission.allowed
        )

        .join(
            ProjectDesignationPermission,
            ProjectDesignationPermission.page_id
            ==FeaturePage.id
        )

        .join(
            PermissionAction,
            PermissionAction.id==
            ProjectDesignationPermission.action_id
        )

        .filter(
            ProjectDesignationPermission.project_id
            ==project_id,

            ProjectDesignationPermission
            .designation_id
            .in_(designation_ids)
        )

        .all()
    )

    for p in designation_permissions:

        key=(
            f"{p.page_code}."
            f"{p.action_name}"
        )

        permission_map[key]=p.allowed

    user_permissions=(

        db.session.query(
            FeaturePage.page_code,
            PermissionAction.action_name,
            ProjectUserPermission.allowed
        )

        .join(
            ProjectUserPermission,
            ProjectUserPermission.page_id
            ==FeaturePage.id
        )

        .join(
            PermissionAction,
            PermissionAction.id
            ==ProjectUserPermission.action_id
        )

        .filter(
            ProjectUserPermission
            .project_user_role_id
            .in_(role_ids)
        )

        .all()
    )

    for p in user_permissions:

        key=(
            f"{p.page_code}."
            f"{p.action_name}"
        )

        permission_map[key]=p.allowed

    return permission_map