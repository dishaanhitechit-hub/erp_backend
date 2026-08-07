from app.models.approval_path import (
    ApprovalPath,
    ApprovalHistory
)

from app.alias_helper import *
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
# GAP LEVEL CHECK
# ==========================================

def get_gap_level(project_code, module_code, current_level):
    next_path = get_next_approver(project_code, module_code, current_level)
    if next_path and next_path.level_no != current_level + 1:
        return current_level + 1
    return None


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
    module_code = get_approval_module(
        module_code
    )

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
    module_code = get_approval_module(
        module_code
    )

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
    print(
        "approver result:",
        approver
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
    module_code = get_approval_module(
        module_code
    )

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
    module_code = get_approval_module(
        module_code
    )

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
    module_code = get_approval_module(
        module_code
    )

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


# ==========================================
# FULL APPROVAL STEPS
# ==========================================

def get_approval_steps(
        project_code,
        module_code,
        record,
        history_rows
):

    approval_code = get_approval_module(
        module_code
    )

    levels = (

        ApprovalPath.query

        .filter_by(

            project_code=
            project_code,

            module_code=
            approval_code,

            path_type=
            "APPROVER"

        )

        .order_by(
            ApprovalPath.level_no.asc()
        )

        .all()

    )

    # latest APPROVE / REJECT / REBACK action per level
    level_history = {}
    for row in history_rows:
        if (
            row.action in ("APPROVE", "REJECT", "REBACK")
            and row.level_no
        ):
            existing = level_history.get(row.level_no)
            if not existing or row.id > existing.id:
                level_history[row.level_no] = row

    ACTION_STATUS = {
        "APPROVE": "Approved",
        "REJECT":  "Rejected",
        "REBACK":  "Rebacked",
    }

    steps = []

    if not levels:
        return steps

    levels_map = {path.level_no: path for path in levels}
    max_level  = max(levels_map.keys())

    for lvl in range(1, max_level + 1):

        path = levels_map.get(lvl)

        if path is None:
            steps.append({
                "level": lvl,
                "approver": {
                    "userId":   None,
                    "username": "Not Assigned",
                },
                "status":   "Not Assigned",
                "actionAt": None,
                "comments": None,
            })
            continue

        h = level_history.get(lvl)

        is_pending = (
            record.workflow_status
            and record.workflow_status.startswith("Pending")
            and lvl == record.current_level
        )

        if is_pending:
            status    = "Pending"
            action_at = None
            comments  = None

        elif h:
            status    = ACTION_STATUS.get(h.action, h.action)
            action_at = (
                h.created_at.strftime("%Y-%m-%d %H:%M:%S")
                if h.created_at else None
            )
            comments  = h.comments

        else:
            status    = "Not Reached"
            action_at = None
            comments  = None

        steps.append({

            "level": lvl,

            "approver": {
                "userId":   path.user_id,
                "username": (
                    path.user.username
                    if path.user else None
                ),
            },

            "status":   status,
            "actionAt": action_at,
            "comments": comments,

        })

    return steps


# ==========================================
# MY APPROVAL STATUS
# ==========================================

def get_my_approval_status(project_code, module_code, record, user_id):
    approval_code = get_approval_module(module_code)
    user_paths = (ApprovalPath.query
                  .filter_by(project_code=project_code,
                             module_code=approval_code,
                             user_id=user_id,
                             path_type="APPROVER")
                  .order_by(ApprovalPath.level_no.asc())
                  .all())
    if not user_paths:
        return {
            "isPendingForMe": False,
            "myLevel":        None,
            "workflowStatus": record.workflow_status,
            "currentLevel":   record.current_level,
        }
    my_levels = [p.level_no for p in user_paths]
    active_level = next(
        (lvl for lvl in my_levels
         if record.workflow_status == f"Pending_L{lvl}"),
        my_levels[0]
    )
    is_pending = record.workflow_status == f"Pending_L{active_level}"
    return {
        "isPendingForMe": is_pending,
        "myLevel":        active_level,
        "workflowStatus": record.workflow_status,
        "currentLevel":   record.current_level,
    }