from app.extensions import db
from datetime import datetime

VALID_MODULES = ["Order", "Enquiry", "Despatch", "Delivery", "Rent"]

MODULE_SUBMODULE_MAP = {
    "Order": [
        "Purchase_Order", "Service_Order", "Work_Order",
        "Customer_Supply_Order", "Site_Transfer_Order"
    ],
    "Enquiry": ["Material_Enquiry", "Service_Enquiry"],
    "Despatch": ["Delivery_Challan", "General_Delivery"],
    "Delivery": ["Delivery_Challan", "General_Delivery"],
    "Rent": ["Machinery_Rent", "Equipment_Rent"],
}

VALID_TERM_TYPES = ["General_Terms", "Special_Terms"]
VALID_POINT_STYLES = ["bullet", "numbered", "alpha", "roman"]


class Term(db.Model):
    __tablename__ = "terms"

    term_id = db.Column(db.Integer, primary_key=True)
    module = db.Column(db.String, nullable=False)
    sub_module = db.Column(db.String, nullable=False)
    term_type = db.Column(db.String, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    term_groups = db.relationship(
        "TermGroup",
        backref="term",
        cascade="all, delete-orphan",
        order_by="TermGroup.sort_order"
    )


class TermGroup(db.Model):
    __tablename__ = "term_groups"

    group_id = db.Column(db.Integer, primary_key=True)
    term_id = db.Column(db.Integer, db.ForeignKey("terms.term_id", ondelete="CASCADE"), nullable=False)
    sort_order = db.Column(db.Integer, nullable=False, default=0)
    title = db.Column(db.String, nullable=False)
    description = db.Column(db.String, nullable=False)
    point_style = db.Column(db.String, nullable=False)

    points = db.relationship(
        "TermPoint",
        backref="group",
        cascade="all, delete-orphan",
        order_by="TermPoint.sort_order"
    )


class TermPoint(db.Model):
    __tablename__ = "term_points"

    point_id = db.Column(db.Integer, primary_key=True)
    group_id = db.Column(db.Integer, db.ForeignKey("term_groups.group_id", ondelete="CASCADE"), nullable=False)
    sort_order = db.Column(db.Integer, nullable=False, default=0)
    text = db.Column(db.String, nullable=False)
