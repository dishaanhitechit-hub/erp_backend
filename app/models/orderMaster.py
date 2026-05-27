# app/models/order_master.py

from app.extensions import db
from datetime import datetime


class OrderMaster(db.Model):

    __tablename__="order_master"

    id=db.Column(
        db.Integer,
        primary_key=True
    )

    order_no=db.Column(
        db.String(50),
        unique=True,
        nullable=False
    )

    project_code=db.Column(
        db.String(50),
        db.ForeignKey(
            "projects.project_code"
        ),
        nullable=False
    )

    sub_code=db.Column(
        db.String(50),
        db.ForeignKey(
            "category_master.fixed_code"
        ),
        nullable=False
    )

    category_code=db.Column(
        db.String(50),
        nullable=True
    )

    vendor_id=db.Column(
        db.Integer,
        db.ForeignKey(
            "vendors.id"
        ),
        nullable=True
    )
    booked_amount=db.Column(
        db.Numeric(14,4),
        nullable=False,
        default=0
    )
    order_date=db.Column(
        db.Date,
        nullable=False
    )
    quotation_no_date=db.Column(db.String(60),
                             nullable=False,
                                default="1")
    validity_date=db.Column(
        db.Date
    )

    billing_address=db.Column(
        db.Text
    )

    shipping_address=db.Column(
        db.Text
    )

    order_message=db.Column(
        db.Text
    )

    supporting_file=db.Column(
        db.Text
    )

    basic_amount=db.Column(
        db.Numeric(14,2),
        default=0
    )

    gst_amount=db.Column(
        db.Numeric(14,2),
        default=0
    )

    total_amount=db.Column(
        db.Numeric(14,2),
        default=0
    )

    workflow_status=db.Column(
        db.String(30),
        default="Draft"
    )

    status=db.Column(
        db.String(30),
        default="Active"
    )
    supporting_file = db.Column(
        db.Text
    )
    created_by=db.Column(
        db.Integer,
        db.ForeignKey(
            "users.id"
        )
    )

    created_at=db.Column(
        db.DateTime,
        default=datetime.utcnow
    )

    updated_at=db.Column(
        db.DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow
    )

    approved_by = db.Column(
        db.Integer,
        db.ForeignKey("users.id")
    )

    submitted_by = db.Column(
        db.Integer,
        db.ForeignKey("users.id")
    )

    rejected_by = db.Column(
        db.Integer,
        db.ForeignKey("users.id")
    )

    submitted_at = db.Column(
        db.DateTime
    )

    final_approved_at = db.Column(
        db.DateTime
    )

    rejected_at = db.Column(
        db.DateTime
    )

    correction_sent_at = db.Column(
        db.DateTime
    )

    updated_by = db.Column(
        db.Integer,
        db.ForeignKey("users.id")
    )

    current_level = db.Column(
        db.Integer,
        default=0
    )

    locked = db.Column(
        db.Boolean,
        default=False
    )

    project=db.relationship(
        "Project",
        backref="orders"
    )

    items=db.relationship(
        "OrderItem",
        backref="order",
        cascade="all,delete-orphan"
    )

    creator=db.relationship(
        "User"
    )
    vendor = db.relationship(
        "Vendor",
        backref="orders"
    )
# app/models/order_item.py

from app.extensions import db
from datetime import datetime


class OrderItem(db.Model):

    __tablename__="order_items"

    id=db.Column(
        db.Integer,
        primary_key=True
    )

    order_id=db.Column(
        db.Integer,
        db.ForeignKey(
            "order_master.id"
        ),
        nullable=False
    )

    indent_item_id=db.Column(
        db.Integer,
        db.ForeignKey(
            "indent_items.id"
        ),
        nullable=False
    )

    item_code=db.Column(
        db.String(50),
        db.ForeignKey(
            "items.item_code"
        )
    )

    note=db.Column(
        db.Text
    )

    unit=db.Column(
        db.String(50)
    )

    qty=db.Column(
        db.Numeric(12,2)
    )

    amend_qty=db.Column(
        db.Numeric(12,2),
        default=0
    )

    used_qty=db.Column(
        db.Numeric(12,2),
        default=0
    )

    balance_qty=db.Column(
        db.Numeric(12,2),
        default=0
    )

    rate=db.Column(
        db.Numeric(12,2)
    )

    amount=db.Column(
        db.Numeric(14,2)
    )

    gst_percent=db.Column(
        db.Numeric(5,2)
    )

    gst_amount=db.Column(
        db.Numeric(14,2)
    )

    location=db.Column(
        db.String(150)
    )

    item_status=db.Column(
        db.String(30),
        default="Pending"
    )

    created_at=db.Column(
        db.DateTime,
        default=datetime.utcnow
    )


    item=db.relationship(
        "Item"
    )

    indent_item=db.relationship(
        "IndentItem"
    )

# app/models/order_terms_condition.py

from app.extensions import db
from datetime import datetime


class OrderTermsCondition(db.Model):

    __tablename__="order_terms_conditions"

    id=db.Column(
        db.Integer,
        primary_key=True
    )

    order_id=db.Column(
        db.Integer,
        db.ForeignKey(
            "order_master.id"
        ),
        nullable=False
    )

    term_id=db.Column(
        db.Integer,
        db.ForeignKey(
            "term_conditions.id"
        ),
        nullable=False
    )

    # optional if user edits after selecting
    custom_description=db.Column(
        db.Text
    )

    sequence_no=db.Column(
        db.Integer,
        default=1
    )

    status=db.Column(
        db.String(30),
        default="Active"
    )

    created_by=db.Column(
        db.Integer,
        db.ForeignKey(
            "users.id"
        )
    )

    created_at=db.Column(
        db.DateTime,
        default=datetime.utcnow
    )


    order=db.relationship(
        "OrderMaster",
        backref=db.backref(
            "terms_conditions",
            cascade="all,delete-orphan"
        )
    )


    term=db.relationship(
        "TermConditions",
        lazy=True
    )


    creator=db.relationship(
        "User",
        foreign_keys=[created_by]
    )
