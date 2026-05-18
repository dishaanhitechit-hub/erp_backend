from app.models.approval_path import (
    ApprovalPath,
    ApprovalHistory
)

from app.extensions import db


# ==========================================
# FIRST APPROVER
# ==========================================

def get_first_approver(
        project_code,
        module_code
):

    return (

        ApprovalPath.query

        .filter(

            ApprovalPath.project_code ==
            project_code,

            ApprovalPath.module_code ==
            module_code,

            ApprovalPath.path_type ==
            "APPROVER"

        )

        .order_by(
            ApprovalPath.level_no.asc()
        )

        .first()

    )


# ==========================================
# NEXT APPROVER
# ==========================================

def get_next_approver(
        project_code,
        module_code,
        current_level
):

    return (

        ApprovalPath.query

        .filter(

            ApprovalPath.project_code ==
            project_code,

            ApprovalPath.module_code ==
            module_code,

            ApprovalPath.path_type ==
            "APPROVER",

            ApprovalPath.level_no >
            current_level

        )

        .order_by(
            ApprovalPath.level_no.asc()
        )

        .first()

    )


# ==========================================
# LAST APPROVER
# ==========================================

def get_last_approver(
        project_code,
        module_code
):

    return (

        ApprovalPath.query

        .filter(

            ApprovalPath.project_code ==
            project_code,

            ApprovalPath.module_code ==
            module_code,

            ApprovalPath.path_type ==
            "APPROVER"

        )

        .order_by(
            ApprovalPath.level_no.desc()
        )

        .first()

    )


# ==========================================
# ALL LEVELS
# ==========================================

def get_approval_levels(
        project_code,
        module_code
):

    return (

        ApprovalPath.query

        .filter(

            ApprovalPath.project_code ==
            project_code,

            ApprovalPath.module_code ==
            module_code,

            ApprovalPath.path_type ==
            "APPROVER"

        )

        .order_by(
            ApprovalPath.level_no.asc()
        )

        .all()

    )


# ==========================================
# CREATOR CHECK
# ==========================================

def is_creator(
        project_code,
        module_code,
        user_id
):

    creator = (

        ApprovalPath.query

        .filter_by(

            project_code=
            project_code,

            module_code=
            module_code,

            user_id=
            user_id,

            path_type=
            "CREATOR"

        )

        .first()

    )

    return True if creator else False


# ==========================================
# CURRENT APPROVER CHECK
# ==========================================

def is_current_approver(
        project_code,
        module_code,
        level_no,
        user_id
):

    approver=(

        ApprovalPath.query

        .filter_by(

            project_code=
            project_code,

            module_code=
            module_code,

            level_no=
            level_no,

            user_id=
            user_id,

            path_type=
            "APPROVER"

        )

        .first()

    )

    return True if approver else False


# ==========================================
# CURRENT APPROVER
# ==========================================

def get_current_approver(
        project_code,
        module_code,
        level_no
):

    return (

        ApprovalPath.query

        .filter_by(

            project_code=
            project_code,

            module_code=
            module_code,

            level_no=
            level_no,

            path_type=
            "APPROVER"

        )

        .first()

    )


# ==========================================
# APPROVER EXISTS?
# ==========================================

def has_approver(
        project_code,
        module_code
):

    approver=(

        ApprovalPath.query

        .filter_by(

            project_code=
            project_code,

            module_code=
            module_code,

            path_type=
            "APPROVER"

        )

        .first()

    )

    return True if approver else False


# ==========================================
# CREATE HISTORY
# ==========================================

def create_history(

        project_code,
        module_code,
        record_id,
        level_no,
        action,
        action_by,
        comments=None
):

    history=ApprovalHistory(

        project_code=
        project_code,

        module_code=
        module_code,

        record_id=
        record_id,

        level_no=
        level_no,

        action=
        action,

        comments=
        comments,

        action_by=
        action_by
    )

    db.session.add(
        history
    )


# ==========================================
# GET HISTORY
# ==========================================

def get_history(
        module_code,
        record_id
):

    return (

        ApprovalHistory.query

        .filter_by(

            module_code=
            module_code,

            record_id=
            record_id

        )

        .order_by(
            ApprovalHistory.id.asc()
        )

        .all()

    )
def has_workflow_access(

        project_code,
        module_code,
        user_id,
        path_type=None
):

    query=(

        ApprovalPath.query

        .filter(

            ApprovalPath.project_code==
            project_code,

            ApprovalPath.module_code==
            module_code,

            ApprovalPath.user_id==
            user_id
        )
    )

    if path_type:

        query=query.filter(

            ApprovalPath.path_type==
            path_type
        )

    return True if query.first() else False

def validate_approver(

        project_code,
        module_code,
        current_level,
        user_id
):

    return (

        is_current_approver(

            project_code,

            module_code,

            current_level,

            user_id
        )

    )


def validate_creator(

        project_code,
        module_code,
        user_id
):

    return (

        is_creator(

            project_code,

            module_code,

            user_id
        )

    )