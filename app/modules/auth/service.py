# app/modules/auth/service.py

from app.models.user import User
from app.extensions import db
from app.response import res
from flask_jwt_extended import create_access_token

def login_user(loginUserName, password):
    user = User.query.filter_by(login_username =  loginUserName).first()

    if not user or not user.check_password(password):
        return res ("Invalid Credential", code = 401)

    #  info in token

    token = create_access_token(
        identity = str(user.id),
        additional_claims={
            "username": user.login_username,
            "role": user.global_role.name if user.global_role else None
        }
    )

    data = [ {"token" : token ,"id": user.id,
            "username": user.username,
            "role": user.global_role.name if user.global_role else None
        }
    ]


    return res("Succesfully Loggin", data)


#