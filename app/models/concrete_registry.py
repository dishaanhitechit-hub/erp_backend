from app.extensions import db


class ConcreteRegistry(db.Model):
    __tablename__ = 'concrete_registry'

    id = db.Column(db.Integer, primary_key=True)

    projectcode = db.Column(
        db.String(50),
        db.ForeignKey("projects.project_code"),
        nullable=False
    )

    reference_order_no = db.Column(db.String(50), nullable=False)
    project_sub_location = db.Column(db.String(50), nullable=False)
    segment = db.Column(db.String(50), nullable=False)

    pouring_date = db.Column(db.Date, nullable=False)
    pouring_start_date = db.Column(db.Time, nullable=False)
    pouring_end_date = db.Column(db.Time, nullable=False)

    grade_concrete = db.Column(db.String(50), nullable=False)
    concrete_volume = db.Column(db.String(50), nullable=False)

    requisition_no = db.Column(db.String(50), nullable=False)
    requisition_by = db.Column(db.String(50), nullable=False)

    vehicle_number = db.Column(db.String(50), nullable=False)
    batch_no = db.Column(db.String(50), nullable=False)

    attach_batch_file = db.Column(db.String(255), nullable=True)

    project = db.relationship(
        "Project",
        backref="concrete_registry"
    )
