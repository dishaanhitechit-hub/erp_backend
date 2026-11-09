from flask_sqlalchemy import SQLAlchemy
from flask_jwt_extended import JWTManager
from flask_bcrypt import Bcrypt
from flask_migrate import Migrate

db = SQLAlchemy()
jwt = JWTManager()
bcrypt = Bcrypt()
migrate = Migrate()


@jwt.token_in_blocklist_loader
def check_if_token_revoked(jwt_header, jwt_payload):
    from app.models.tokenBlocklist import TokenBlocklist
    jti = jwt_payload.get("jti")
    return TokenBlocklist.query.filter_by(jti=jti).scalar() is not None

# Every document needs a print id (…_uuid) for its print page / PDF link.
# If a save path forgets to set one, fill it in here.
import uuid as _uuid
from sqlalchemy import event as _event


@_event.listens_for(db.Model, "before_insert", propagate=True)
def _fill_print_uuid(mapper, connection, target):
    for col in mapper.columns:
        if col.key.endswith("_uuid") and col.type.python_type is str and not getattr(target, col.key, None):
            setattr(target, col.key, str(_uuid.uuid4()))
