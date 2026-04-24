from app.extensions import db

class Team(db.Model):
    __tablename__ = "teams"

    id = db.Column(db.Integer, primary_key=True)
    team_type = db.Column(db.String(20), unique=True, nullable=False)

    def __repr__(self):
        return f"<Team {self.team_type}>"