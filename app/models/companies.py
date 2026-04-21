from app.extensions import db

class Company(db.Model):
    __tablename__ = "companies"

    id = db.Column(db.Integer, primary_key=True)

    company_name = db.Column(db.String(255), nullable=False)

    registered_address = db.Column(db.Text, nullable=True)
    corporate_address = db.Column(db.Text, nullable=True)

    pan = db.Column(db.String(20), nullable=True)
    gstn = db.Column(db.String(20), nullable=True)
    gstn_type = db.Column(db.String(50), nullable=True)

    state = db.Column(db.String(100), nullable=True,)
    state_code = db.Column(db.String(10), nullable=True)

    contact_person = db.Column(db.String(100), nullable=True)
    contact_number = db.Column(db.String(15), nullable=True)
    whatsapp_number = db.Column(db.String(15), nullable=True)

    email = db.Column(db.String(120), nullable=True)

    pan_file = db.Column(db.String(255), nullable=True)
    gstn_file = db.Column(db.String(255), nullable=True)

    created_at = db.Column(db.DateTime, server_default=db.func.now())
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)

    # relationship
    creator = db.relationship("User", backref="companies", lazy=True)