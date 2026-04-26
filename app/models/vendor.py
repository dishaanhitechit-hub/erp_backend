# models/vendor.py
# Updated ORM:
# vendor_category will be fetched from CategoryMaster table

from app.extensions import db
from datetime import datetime

class Vendor(db.Model):
    __tablename__ = "vendors"

    # =====================================
    # PRIMARY INFO
    # =====================================

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    ledger_code = db.Column(
        db.String(50),
        unique=True,
        nullable=False
    )  # Auto Generated

    ledger_name = db.Column(
        db.String(200),
        nullable=False
    )

    registered_address = db.Column(
        db.Text,
        nullable=True
    )

    corporate_address = db.Column(
        db.Text,
        nullable=True
    )

    # =====================================
    # VENDOR CATEGORY FROM CATEGORY MASTER
    # =====================================

    category_id = db.Column(
        db.Integer,
        db.ForeignKey("category_master.id"),
        nullable=False
    )

    # =====================================
    # TAX DETAILS
    # =====================================

    pan = db.Column(
        db.String(20),
        nullable=True
    )

    gstin = db.Column(
        db.String(30),
        nullable=True
    )

    state_code = db.Column(
        db.String(20),
        nullable=True
    )

    state_name = db.Column(
        db.String(100),
        nullable=True
    )

    # =====================================
    # CONTACT DETAILS
    # =====================================

    primary_contact_person = db.Column(
        db.String(150),
        nullable=True
    )

    primary_contact_number = db.Column(
        db.String(20),
        nullable=True
    )

    designation = db.Column(
        db.String(100),
        nullable=True
    )

    whatsapp_number = db.Column(
        db.String(20),
        nullable=True
    )

    # =====================================
    # BANK DETAILS
    # =====================================

    bank_account_number = db.Column(
        db.String(100),
        nullable=True
    )

    bank_name = db.Column(
        db.String(150),
        nullable=True
    )

    branch_name = db.Column(
        db.String(150),
        nullable=True
    )

    ifsc_code = db.Column(
        db.String(50),
        nullable=True
    )


    # =====================================
    # RELATIONSHIP
    # =====================================

    vendor_category = db.relationship(
        "CategoryMaster",
        backref="vendors",
        lazy=True
    )

    # =====================================
    # FILE STORAGE
    # Store only filename
    # Example:
    # pan_xxx.pdf
    # trade_xxx.jpg
    # =====================================

    trade_licence_file = db.Column(
        db.String(300),
        nullable=True
    )

    pan_file = db.Column(
        db.String(300),
        nullable=True
    )

    gstn_file = db.Column(
        db.String(300),
        nullable=True
    )

    bank_details_file = db.Column(
        db.String(300),
        nullable=True
    )




    # =====================================
    # STATUS + AUDIT
    # =====================================

    status = db.Column(
        db.String(30),
        default="Active"
    )

    created_at = db.Column(
        db.DateTime,
        default=datetime.utcnow
    )

    updated_at = db.Column(
        db.DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow
    )

    created_by = db.Column(
        db.Integer,
        db.ForeignKey("users.id"),
        nullable=True
    )

    created_by_user = db.relationship(
        "User",
        backref="created_vendors",
        lazy=True
    )
    # =====================================
    # STRING REPRESENTATION
    # =====================================

    def __repr__(self):
        return f"<Vendor {self.ledger_code} - {self.ledger_name}>"