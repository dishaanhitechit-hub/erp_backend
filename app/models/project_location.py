from sqlalchemy import ForeignKey

from app.extensions import db


class ProjectLocation(db.Model):
    __tablename__ = 'Projectlocation'
    id = db.Column(db.Integer, primary_key=True)
    store_location = db.Column(db.String,unique=True)
    use_location = db.Column(db.String,unique=True)
    project_code=db.Column(db.String,db.ForeignKey('projects.project_code'))

    pLocation=db.relationship('Project',backref="projects")