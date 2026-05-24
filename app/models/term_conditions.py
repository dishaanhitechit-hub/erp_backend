from app.extensions import db

class TermConditions(db.Model):
    __tablename__ = 'term_conditions'
    id = db.Column(db.Integer, primary_key=True)
    category = db.Column(db.String,nullable=False)
    header=db.Column(db.String,nullable=False)
    sub_header=db.Column(db.String)
    term_description=db.Column(db.String,nullable=False)

    created_by=db.Column(db.Integer,db.ForeignKey('users.id'),nullable=False)


    creator = db.relationship( "User", foreign_keys=[created_by],lazy=True)
