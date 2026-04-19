# app/models/project_role.py

from app.extensions import db

class ProjectUserRole(db.Model):
    __tablename__ = "project_user_roles"

    id = db.Column(db.Integer, primary_key=True)

    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    project_id = db.Column(db.Integer, db.ForeignKey("projects.id"))
    designation_id = db.Column(db.Integer, db.ForeignKey("designations.id"))
    team_id = db.Column(db.Integer, db.ForeignKey("project_teams.id"))

    # relationships
    user = db.relationship("User", backref="project_roles")
    project = db.relationship("Project", backref="user_roles")
    designation = db.relationship("Designation")
    team = db.relationship("ProjectTeam")

    __table_args__ = (
        db.UniqueConstraint(
            'user_id', 'project_id', 'designation_id', 'team_id',
            name='unique_user_project_team_role'
        ),
    )