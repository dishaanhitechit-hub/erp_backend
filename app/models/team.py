from app.extensions import db


class ProjectTeam(db.Model):
    __tablename__ = "project_teams"

    id = db.Column(db.Integer, primary_key=True)

    project_id = db.Column(db.Integer, db.ForeignKey("projects.id"))
    name = db.Column(db.String(50))  # "SITE", "HO"

    project = db.relationship("Project", backref="teams")