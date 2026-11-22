from app.extensions import db
from datetime import datetime


class OgSaleOrderMaster(db.Model):

    __tablename__ = "og_sale_order_master"

    id = db.Column(db.Integer, primary_key=True)

    erp_no   = db.Column(db.String(50), unique=True, nullable=False)
    og_sale_order_uuid = db.Column(db.String(36), unique=True, nullable=True, index=True)
    og_sale_order_date = db.Column(db.Date, nullable=False)

    order_no       = db.Column(db.String(50),  nullable=True)
    order_validity = db.Column(db.Date,        nullable=True)
    order_title    = db.Column(db.String(200), nullable=False)

    project_code = db.Column(
        db.String(50),
        db.ForeignKey("projects.project_code"),
        nullable=False
    )

    debtor_id = db.Column(
        db.Integer,
        db.ForeignKey("vendors.id"),
        nullable=True
    )

    # Financials — computed from items + boq_items
    basic_amount = db.Column(db.Numeric(14, 2), default=0)
    gst_amount   = db.Column(db.Numeric(14, 2), default=0)
    total_amount = db.Column(db.Numeric(14, 2), default=0)

    # Three attachment slots
    attachment_1 = db.Column(db.Text, nullable=True)
    attachment_2 = db.Column(db.Text, nullable=True)
    attachment_3 = db.Column(db.Text, nullable=True)

    # Workflow
    workflow_status = db.Column(db.String(30), default="Draft")
    status          = db.Column(db.String(30), default="Active")
    current_level   = db.Column(db.Integer,   default=0)
    locked          = db.Column(db.Boolean,   default=False)

    # Audit
    created_by         = db.Column(db.Integer, db.ForeignKey("users.id"))
    created_at         = db.Column(db.DateTime, default=datetime.utcnow)
    updated_by         = db.Column(db.Integer, db.ForeignKey("users.id"))
    updated_at         = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    submitted_by       = db.Column(db.Integer, db.ForeignKey("users.id"))
    submitted_at       = db.Column(db.DateTime)
    approved_by        = db.Column(db.Integer, db.ForeignKey("users.id"))
    final_approved_at  = db.Column(db.DateTime)
    rejected_by        = db.Column(db.Integer, db.ForeignKey("users.id"))
    rejected_at        = db.Column(db.DateTime)
    correction_sent_at = db.Column(db.DateTime)

    # Relationships
    project   = db.relationship("Project", backref="og_sale_orders")
    debtor    = db.relationship("Vendor", foreign_keys=[debtor_id], lazy=True)
    items     = db.relationship(
        "OgSaleOrderItem",
        backref="og_sale_order",
        cascade="all,delete-orphan",
        order_by="OgSaleOrderItem.sl_no",
    )
    boq_items = db.relationship(
        "OgSaleOrderBoqItem",
        backref="og_sale_order",
        cascade="all,delete-orphan",
        order_by="OgSaleOrderBoqItem.sl_no",
    )
    creator   = db.relationship("User", foreign_keys=[created_by])
    updater   = db.relationship("User", foreign_keys=[updated_by])
    submitter = db.relationship("User", foreign_keys=[submitted_by])
    approver  = db.relationship("User", foreign_keys=[approved_by])
    rejector  = db.relationship("User", foreign_keys=[rejected_by])


class OgSaleOrderItem(db.Model):
    """Regular items table — all fields manual, no FK to item master."""

    __tablename__ = "og_sale_order_items"

    id = db.Column(db.Integer, primary_key=True)

    og_sale_order_id = db.Column(
        db.Integer,
        db.ForeignKey("og_sale_order_master.id"),
        nullable=False
    )

    sl_no            = db.Column(db.Integer,      nullable=False)
    item_code        = db.Column(db.String(50),   nullable=True)
    item_name        = db.Column(db.String(2000), nullable=True)
    item_description = db.Column(db.Text,         nullable=True)
    item_name_desc   = db.Column(db.Text,         nullable=True)
    unit             = db.Column(db.String(30),   nullable=True)

    order_qty   = db.Column(db.Numeric(17, 4), default=0)
    rate        = db.Column(db.Numeric(17, 4), default=0)
    amount      = db.Column(db.Numeric(14, 2), default=0)
    gst_percent = db.Column(db.Numeric(5,  2), default=0)
    gst_amount  = db.Column(db.Numeric(14, 2), default=0)

    # set when the line was added by an approved amendment (NULL = original line)
    amendment_id = db.Column(
        db.Integer, db.ForeignKey("og_sale_order_amendment.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    amendment = db.relationship("OgSaleOrderAmendment", foreign_keys=[amendment_id])

    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class OgSaleOrderBoqItem(db.Model):
    """BOQ items table — same structure as OgSaleOrderItem, all manual."""

    __tablename__ = "og_sale_order_boq_items"

    id = db.Column(db.Integer, primary_key=True)

    og_sale_order_id = db.Column(
        db.Integer,
        db.ForeignKey("og_sale_order_master.id"),
        nullable=False
    )

    sl_no            = db.Column(db.Integer,      nullable=False)
    item_code        = db.Column(db.String(50),   nullable=True)
    item_name        = db.Column(db.String(2000), nullable=True)
    item_description = db.Column(db.Text,         nullable=True)
    item_name_desc   = db.Column(db.Text,         nullable=True)
    unit             = db.Column(db.String(30),   nullable=True)

    order_qty   = db.Column(db.Numeric(17, 4), default=0)
    rate        = db.Column(db.Numeric(17, 4), default=0)
    amount      = db.Column(db.Numeric(14, 2), default=0)
    gst_percent = db.Column(db.Numeric(5,  2), default=0)
    gst_amount  = db.Column(db.Numeric(14, 2), default=0)

    # set when the line was added by an approved amendment (NULL = original line)
    amendment_id = db.Column(
        db.Integer, db.ForeignKey("og_sale_order_amendment.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    amendment = db.relationship("OgSaleOrderAmendment", foreign_keys=[amendment_id])

    created_at = db.Column(db.DateTime, default=datetime.utcnow)


# ══════════════════════════════════════════════════════════════════
# AMENDMENTS — extra items added to an Approved Sale Order
# ══════════════════════════════════════════════════════════════════

class OgSaleOrderAmendment(db.Model):
    """One amendment (AMD-1, AMD-2 …) of an Approved Sale Order.

    The proposed lines live in og_sale_order_amendment_items until final
    approval; then they are copied to the end of the order's item tables
    (tagged with amendment_id) and the order totals go up. Nothing else on the
    order changes, so bills already raised are untouched.
    """

    __tablename__ = "og_sale_order_amendment"
    __table_args__ = (
        db.UniqueConstraint("og_sale_order_id", "amendment_seq", name="uq_og_so_amendment_seq"),
    )

    id = db.Column(db.Integer, primary_key=True)
    og_sale_order_id = db.Column(
        db.Integer, db.ForeignKey("og_sale_order_master.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    amendment_seq  = db.Column(db.Integer, nullable=False)          # 1, 2, 3 … per order
    amendment_no   = db.Column(db.String(60), nullable=False)       # e.g. OSO001/AMD-1
    amendment_date = db.Column(db.Date, nullable=False)
    reason         = db.Column(db.Text, nullable=False)
    customer_ref   = db.Column(db.String(100), nullable=True)       # client's amendment letter / PO rev no
    attachment     = db.Column(db.Text, nullable=True)
    project_code   = db.Column(db.String(50), db.ForeignKey("projects.project_code"), nullable=False)

    # amounts this amendment adds
    basic_amount = db.Column(db.Numeric(14, 2), default=0)
    gst_amount   = db.Column(db.Numeric(14, 2), default=0)
    total_amount = db.Column(db.Numeric(14, 2), default=0)
    # order total before / after (filled on final approval, for the history)
    order_total_before = db.Column(db.Numeric(14, 2), nullable=True)
    order_total_after  = db.Column(db.Numeric(14, 2), nullable=True)

    workflow_status = db.Column(db.String(30), default="Draft")
    current_level   = db.Column(db.Integer, default=0)
    locked          = db.Column(db.Boolean, default=False)

    created_by         = db.Column(db.Integer, db.ForeignKey("users.id"))
    created_at         = db.Column(db.DateTime, default=datetime.utcnow)
    updated_by         = db.Column(db.Integer, db.ForeignKey("users.id"))
    updated_at         = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    submitted_by       = db.Column(db.Integer, db.ForeignKey("users.id"))
    submitted_at       = db.Column(db.DateTime)
    approved_by        = db.Column(db.Integer, db.ForeignKey("users.id"))
    final_approved_at  = db.Column(db.DateTime)
    rejected_by        = db.Column(db.Integer, db.ForeignKey("users.id"))
    rejected_at        = db.Column(db.DateTime)
    correction_sent_at = db.Column(db.DateTime)

    og_sale_order = db.relationship(
        "OgSaleOrderMaster",
        backref=db.backref("amendments", cascade="all,delete-orphan", passive_deletes=True,
                           order_by="OgSaleOrderAmendment.amendment_seq"),
    )
    items = db.relationship(
        "OgSaleOrderAmendmentItem", backref="amendment",
        cascade="all,delete-orphan", order_by="OgSaleOrderAmendmentItem.sl_no",
    )
    creator   = db.relationship("User", foreign_keys=[created_by])
    submitter = db.relationship("User", foreign_keys=[submitted_by])
    approver  = db.relationship("User", foreign_keys=[approved_by])
    rejector  = db.relationship("User", foreign_keys=[rejected_by])


class OgSaleOrderAmendmentItem(db.Model):
    """A proposed line of an amendment (BOQ or Non-BOQ). Copied into the order on approval."""

    __tablename__ = "og_sale_order_amendment_items"

    id = db.Column(db.Integer, primary_key=True)
    amendment_id = db.Column(
        db.Integer, db.ForeignKey("og_sale_order_amendment.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    sl_no            = db.Column(db.Integer, nullable=False)
    item_type        = db.Column(db.String(10), nullable=False, default="non-boq")   # boq | non-boq
    item_code        = db.Column(db.String(50), nullable=True)
    item_name        = db.Column(db.String(2000), nullable=True)
    item_description = db.Column(db.Text, nullable=True)
    unit             = db.Column(db.String(30), nullable=True)
    order_qty   = db.Column(db.Numeric(17, 4), default=0)
    rate        = db.Column(db.Numeric(17, 4), default=0)
    amount      = db.Column(db.Numeric(14, 2), default=0)
    gst_percent = db.Column(db.Numeric(5, 2), default=0)
    gst_amount  = db.Column(db.Numeric(14, 2), default=0)
    # the order line it became (set on final approval)
    so_item_id     = db.Column(db.Integer, nullable=True)
    so_item_sl_no  = db.Column(db.Integer, nullable=True)
