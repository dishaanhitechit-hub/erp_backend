from app.extensions import db
from datetime import datetime


class PMMaster(db.Model):
    __tablename__ = "pm_master"

    id = db.Column(db.Integer, primary_key=True)
    pm_uid = db.Column(db.String(20), unique=True, nullable=False)

    machine_name   = db.Column(db.String(200), nullable=True)
    machinery_type = db.Column(db.String(100), nullable=True)

    registration_number = db.Column(db.String(100), nullable=True)
    registration_date   = db.Column(db.Date, nullable=True)
    registration_file   = db.Column(db.String(300), nullable=True)

    insurance_number = db.Column(db.String(100), nullable=True)
    insurance_date   = db.Column(db.Date, nullable=True)
    insurance_file   = db.Column(db.String(300), nullable=True)

    puc_cert_number = db.Column(db.String(100), nullable=True)
    puc_date        = db.Column(db.Date, nullable=True)
    puc_file        = db.Column(db.String(300), nullable=True)

    road_tax_number = db.Column(db.String(100), nullable=True)
    road_tax_date   = db.Column(db.Date, nullable=True)
    road_tax_file   = db.Column(db.String(300), nullable=True)

    fuel_consumption_unit = db.Column(db.String(100), nullable=True)

    purchased_bill_amount = db.Column(db.Numeric(17, 4), nullable=True)
    purchased_bill_date   = db.Column(db.Date, nullable=True)
    purchased_bill_file   = db.Column(db.String(300), nullable=True)

    status     = db.Column(db.String(30), default="Active")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    created_by = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    updated_by = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    creator = db.relationship("User", foreign_keys=[created_by])
    updater = db.relationship("User", foreign_keys=[updated_by])

    service_histories = db.relationship("PMServiceHistory", backref="pm", cascade="all,delete-orphan")
    service_schedules = db.relationship("PMServiceSchedule", backref="pm", cascade="all,delete-orphan")


class PMServiceHistory(db.Model):
    __tablename__ = "pm_service_history"

    id = db.Column(db.Integer, primary_key=True)

    pm_id = db.Column(db.Integer, db.ForeignKey("pm_master.id", ondelete="CASCADE"), nullable=False)

    service_type    = db.Column(db.String(100), nullable=True)
    service_date    = db.Column(db.Date, nullable=True)
    bill_amount     = db.Column(db.Numeric(17, 4), nullable=True)
    party_bill_no   = db.Column(db.String(100), nullable=True)
    party_bill_file = db.Column(db.String(300), nullable=True)
    service_location  = db.Column(db.String(200), nullable=True)
    job_monitoring_by = db.Column(db.String(200), nullable=True)
    operator_name     = db.Column(db.String(200), nullable=True)

    status     = db.Column(db.String(30), default="Active")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    created_by = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    updated_by = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    creator = db.relationship("User", foreign_keys=[created_by])
    updater = db.relationship("User", foreign_keys=[updated_by])


class PMServiceSchedule(db.Model):
    __tablename__ = "pm_service_schedule"

    id = db.Column(db.Integer, primary_key=True)

    pm_id = db.Column(db.Integer, db.ForeignKey("pm_master.id", ondelete="CASCADE"), nullable=False)

    service_type      = db.Column(db.String(100), nullable=True)
    service_date      = db.Column(db.Date, nullable=True)
    reading_under     = db.Column(db.String(100), nullable=True)
    expected_expenses = db.Column(db.Numeric(17, 4), nullable=True)
    responsible_person = db.Column(db.String(200), nullable=True)

    status     = db.Column(db.String(30), default="Active")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    created_by = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    updated_by = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    creator = db.relationship("User", foreign_keys=[created_by])
    updater = db.relationship("User", foreign_keys=[updated_by])
