# app/models/project.py

from app.extensions import db

class Project(db.Model):
    __tablename__ = "projects"

    id = db.Column(db.Integer, primary_key=True)
    project_code = db.Column(db.String(50), unique=True)
    project_name = db.Column(db.String(200))
    client_name = db.Column(db.String(200))
    project_details = db.Column(db.Text)
    registered_address = db.Column(db.String(400))
    proj_mgmt_contact_number = db.Column(db.String(200))
    proj_mgmt_email_id = db.Column(db.String(200))
    commercial_manager = db.Column(db.String(200))
    comm_mgmt_email_id = db.Column(db.String(200))
    comm_mgmt_contact_number = db.Column(db.String(200))

    gstn = db.Column(db.String(200))

    billing_address = db.Column(db.String(400))
    shipping_address = db.Column(db.String(400))
    shipping_address_2= db.Column(db.String(400))
    shipping_address_3 = db.Column(db.String(400))
    project_manager = db.Column(db.String(200))

    initial_order_value = db.Column(db.String(200))
    schedule_date = db.Column(db.Date)
    schedule_completion_date = db.Column(db.Date)
    revised_order_value = db.Column(db.String(200))
    original_start_date = db.Column(db.Date)
    extended_complete_date = db.Column(db.Date)

    status = db.Column(db.String(50))  # ongoing / hold / completed

    created_at = db.Column(db.DateTime, server_default=db.func.now())

    # needed update