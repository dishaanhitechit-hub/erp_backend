from app.extensions import db


class ProjectTeam(db.Model):
    __tablename__ = "project_teams"

    id = db.Column(db.Integer, primary_key=True)

    project_id = db.Column(db.Integer, db.ForeignKey("projects.id"))
    designation_id = db.Column(db.Integer, db.ForeignKey("designations.id"))

    team_type = db.Column(db.String(20))  # "SITE", "HO"

    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)

    # relationships
    project = db.relationship("Project", backref="teams")
    designation = db.relationship("Designation")
    user = db.relationship("User")