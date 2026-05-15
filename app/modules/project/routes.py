from flask_jwt_extended import (
    jwt_required,
    get_jwt_identity
)
from flask import Blueprint, request ,jsonify
from .service import *
project_bp = Blueprint("project", __name__)

@project_bp.route(
    "/enter/<projectCode>",
    methods=["POST"]
)

@jwt_required()
def enter_project_route(
        projectCode
):

    user_id = int(
        get_jwt_identity()
    )

    return enter_project(
        projectCode,
        user_id
    )