# app/models/user.py
from sqlalchemy import event

from app.extensions import db, bcrypt
# from app.models import Role


class User(db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), unique=False, nullable=False)
    login_username = db.Column(db.String(100), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.Text, nullable=False)
    mobile = db.Column(db.String(20), unique=False, nullable=False)
    wp_mobile = db.Column(db.String(20), unique=False, nullable=False)
    emp_code = db.Column(db.String(20), unique=False, nullable=False)
    signature = db.Column(db.String(255))

    #  set password
    def set_password(self, password):
        self.password_hash = bcrypt.generate_password_hash(password).decode('utf-8')

    #  check password
    def check_password(self, password):
        return bcrypt.check_password_hash(self.password_hash, password)



    is_active = db.Column(db.Boolean, default=True)

    global_role_id = db.Column(db.Integer, db.ForeignKey("roles.id"))

    created_at = db.Column(db.DateTime, server_default=db.func.now())


    # relationships
    global_role = db.relationship("Role", backref="users")

@event.listens_for(User, "before_insert")
def gen_login_username(mapper, connection, target):
    cl_user = target.username.replace(" ", "").lower()
    target.login_username = f"{cl_user}_{target.emp_code}"
        # Update in DB
    # connection.execute(
    # User.__table__.update()
    # .where(User.id == target.id)
    # .values(login_username=login_username)
    #     )


