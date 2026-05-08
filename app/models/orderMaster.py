# OrderMaster
from app.extensions import db
from datetime import datetime



class OrderMaster(db.Model):
    __tablename__ = 'order_master'

    id = db.Column(db.Integer, primary_key=True)
    order_no = db.Column(db.String(50), unique=True, nullable=False)
    order_date = db.Column(db.DateTime)
    order_validity = db.Column(db.Date)

    indent_id = db.Column(db.Integer, db.ForeignKey('indent_master.id'))
    project_code = db.Column(db.String(50))
    category_code = db.Column(db.String(50))
    sub_category_code = db.Column(db.String(50))

    party_name = db.Column(db.String(200))
    party_address = db.Column(db.Text)
    party_gstn = db.Column(db.String(50))
    site = db.Column(db.String(200))
    billing_address = db.Column(db.Text)
    shipping_address = db.Column(db.Text)
    order_message = db.Column(db.Text)
    quotation_file = db.Column(db.String(500))

    basic_amount = db.Column(db.Numeric(15, 2))
    gst_amount = db.Column(db.Numeric(15, 2))
    total_amount = db.Column(db.Numeric(15, 2))

    igst_selected = db.Column(db.Boolean, default=False)
    cgst_selected = db.Column(db.Boolean, default=False)
    sgst_selected = db.Column(db.Boolean, default=False)
    igst_amount = db.Column(db.Numeric(15, 2))
    cgst_amount = db.Column(db.Numeric(15, 2))
    sgst_amount = db.Column(db.Numeric(15, 2))

    order_status = db.Column(db.String(50))  # Draft, Submitted, Verified, Approved
    booked_status = db.Column(db.String(50))  # Pending, Booked

    created_by = db.Column(db.Integer)
    updated_by = db.Column(db.Integer)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime)

    # Relationships
    order_items = db.relationship('OrderItem', backref='order', lazy=True)
    order_cost_centers = db.relationship('OrderCostCenter', backref='order', lazy=True)
    order_terms = db.relationship('OrderTerm', backref='order', lazy=True)
    order_approvals = db.relationship('OrderApproval', backref='order', lazy=True)


# OrderItem
class OrderItem(db.Model):
    __tablename__ = 'order_item'

    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey('order_master.id'))
    indent_item_id = db.Column(db.Integer, db.ForeignKey('indent_item.id'))
    item_code = db.Column(db.String(50))

    indent_qty = db.Column(db.Numeric(15, 3))
    order_qty = db.Column(db.Numeric(15, 3))
    rate = db.Column(db.Numeric(15, 2))
    amount = db.Column(db.Numeric(15, 2))
    gst_percentage = db.Column(db.Numeric(5, 2))
    gst_amount = db.Column(db.Numeric(15, 2))

    location = db.Column(db.String(200))
    note = db.Column(db.Text)

    created_by = db.Column(db.Integer)

    # Relationships
    item = db.relationship('Item', foreign_keys=[item_code],
                           primaryjoin="OrderItem.item_code==Item.item_code")


# OrderCostCenter
class OrderCostCenter(db.Model):
    __tablename__ = 'order_cost_center'

    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey('order_master.id'))
    cc_code = db.Column(db.String(50))
    cc_name = db.Column(db.String(200))
    basic_amount = db.Column(db.Numeric(15, 2))
    created_by = db.Column(db.Integer)


# OrderTerm
class OrderTerm(db.Model):
    __tablename__ = 'order_term'

    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey('order_master.id'))
    header = db.Column(db.String(200))
    sub_header = db.Column(db.String(200))
    description = db.Column(db.Text)
    created_by = db.Column(db.Integer)


# OrderApproval
class OrderApproval(db.Model):
    __tablename__ = 'order_approval'

    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey('order_master.id'))
    action = db.Column(db.String(50))  # Created, Verified, Approved
    user_name = db.Column(db.String(200))
    status = db.Column(db.String(50))  # Submit, Pending, Rejected
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


# TermsMaster (for pre-defined T&C)
class TermsMaster(db.Model):
    __tablename__ = 'terms_master'

    id = db.Column(db.Integer, primary_key=True)
    mark_id = db.Column(db.String(50))  # GST-1, Payment-1, etc.
    header = db.Column(db.String(200))
    sub_header = db.Column(db.String(200))
    description = db.Column(db.Text)
    status = db.Column(db.String(50))  # Active, Inactive