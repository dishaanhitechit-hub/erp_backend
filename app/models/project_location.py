from app.extensions import db


class ProjectLocation(db.Model):
    __tablename__ = 'Projectlocation'

    id            = db.Column(db.Integer, primary_key=True)
    location_name = db.Column(db.String, nullable=True)
    location_type = db.Column(db.String, nullable=True)  # e.g. Store / Use
    project_code  = db.Column(db.String, db.ForeignKey('projects.project_code'))

    __table_args__ = (
        db.UniqueConstraint(
            'project_code', 'location_name', 'location_type',
            name='uq_project_location_name_type'
        ),
    )

    pLocation = db.relationship('Project', backref="projects")

