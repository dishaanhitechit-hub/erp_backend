from app.extensions import db

class ModuleMaster(db.Model):

    __tablename__="module_master"

    id=db.Column(
        db.Integer,
        primary_key=True
    )

    module_code=db.Column(
        db.String(50),
        unique=True,
        nullable=False
    )

    module_name=db.Column(
        db.String(100),
        nullable=False
    )

    status=db.Column(
        db.String(20),
        default="Active"
    )

class ApprovalPath(db.Model):

    __tablename__="approval_path"

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    project_code = db.Column(
        db.String(50),
        db.ForeignKey(
            "projects.project_code"
        ),
        nullable=False
    )

    module_code = db.Column(
        db.String(50),
        db.ForeignKey(
            "module_master.module_code"
        ),
        nullable=False
    )

    level_no = db.Column(
        db.Integer,
        nullable=False
    )

    user_id = db.Column(
        db.Integer,
        db.ForeignKey(
            "users.id"
        ),
        nullable=False
    )

    path_type = db.Column(
        db.String(20),
        nullable=False
    )
    # CREATOR
    # APPROVER

    created_at=db.Column(
        db.DateTime,
        server_default=db.func.now()
    )

    project = db.relationship(
        "Project"
    )

    module = db.relationship(
        "ModuleMaster"
    )

    user = db.relationship(
        "User"
    )
    __table_args__=(

        db.UniqueConstraint(
            "project_code",
            "module_code",
            "user_id",
            "level_no",
            "path_type",
            name="uq_approval_path"
        ),

    )


class ApprovalHistory(db.Model):

    __tablename__="approval_history"

    id=db.Column(
        db.Integer,
        primary_key=True
    )

    project_code=db.Column(
        db.String(50),
        db.ForeignKey(
            "projects.project_code"
        ),
        nullable=False
    )

    module_code=db.Column(
        db.String(50),
        db.ForeignKey(
            "module_master.module_code"
        ),
        nullable=False
    )

    record_id=db.Column(
        db.Integer,
        nullable=False
    )

    level_no=db.Column(
        db.Integer
    )

    action=db.Column(
        db.String(30),
        nullable=False
    )
    # SUBMIT
    # APPROVE
    # REBACK
    # REJECT

    comments=db.Column(
        db.Text
    )

    action_by=db.Column(
        db.Integer,
        db.ForeignKey(
            "users.id"
        )
    )

    created_at=db.Column(
        db.DateTime,
        server_default=db.func.now()
    )

    # -------------------
    # relationships
    # -------------------

    project=db.relationship(
        "Project"
    )

    module=db.relationship(
        "ModuleMaster"
    )

    user=db.relationship(
        "User"
    )

