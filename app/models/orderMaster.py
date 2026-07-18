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
        nullable=False
    )
    cost_head = db.Column(
        db.String(50),
        nullable=True,
        default="test"
    )
    vendor_id=db.Column(
        db.Integer,
        db.ForeignKey(
            "vendors.id"
        ),
        nullable=True
    )

    transfer_project_site = db.Column(
        db.String(50),
        db.ForeignKey("projects.project_code"),
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
    quotation_no=db.Column(db.String(60),
                             nullable=False,
                                default="1")
    quotation_date=db.Column(
        db.Date,
    )
    validity_date=db.Column(
        db.Date
    )

    billing_address=db.Column(
        db.Text
    )

    shipping_address=db.Column(
        db.Text
    )

    contact_person=db.Column(
        db.String(50),nullable=True
    )

    contact_number=db.Column(db.String(50),nullable=True)

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

    pdf_url = db.Column(db.Text, nullable=True)
    pdf_token = db.Column(db.Text, nullable=True)
    pdf_generated_at = db.Column(db.DateTime, nullable=True)


    project=db.relationship(
        "Project",
        foreign_keys="[OrderMaster.project_code]",
        backref="orders"
    )

    items=db.relationship(
        "OrderItem",
        backref="order",
        cascade="all,delete-orphan"
    )

    creator = db.relationship(
        "User",
        foreign_keys=[created_by]
    )

    approver = db.relationship(
        "User",
        foreign_keys=[approved_by]
    )

    submitter = db.relationship(
        "User",
        foreign_keys=[submitted_by]
    )

    rejector = db.relationship(
        "User",
        foreign_keys=[rejected_by]
    )

    updater = db.relationship(
        "User",
        foreign_keys=[updated_by]
    )
    vendor = db.relationship(
        "Vendor",
        backref="orders"
    )

    transfer_site_project = db.relationship(
        "Project",
        foreign_keys="[OrderMaster.transfer_project_site]",
        lazy=True
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
        nullable=True
    )

    item_code=db.Column(
        db.String(50),
        db.ForeignKey(
            "items.item_code"
        )
    )

    custom_note=db.Column(
        db.Text
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

    # FK to master terms table — for referential integrity only
    source_term_id=db.Column(
        db.Integer,
        db.ForeignKey("terms.term_id"),
        nullable=True
    )

    # JSON array of customised termGroups
    custom_groups=db.Column(
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


    creator=db.relationship(
        "User",
        foreign_keys=[created_by]
    )
