

from app.extensions import db

class WorkflowModuleAlias(db.Model):

    __tablename__ = "workflow_module_alias"

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    module_code = db.Column(
        db.String(100),
        unique=True,
        nullable=False
    )

    approval_module_code = db.Column(
        db.String(100),
        nullable=False
    )