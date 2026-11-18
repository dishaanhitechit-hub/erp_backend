# app/models/transitRequest.py
# Transit Request — pre-authorization document for material movement

from app.extensions import db
from datetime import datetime


class TransitRequest(db.Model):

    __tablename__ = "transit_requests"

    id = db.Column(db.Integer, primary_key=True)

    tr_no = db.Column(db.String(50), unique=True, nullable=False)
    tr_uuid = db.Column(db.String(36), unique=True, nullable=True, index=True)

    request_date = db.Column(db.Date, nullable=False)

    project_code = db.Column(
        db.String(50),
        db.ForeignKey("projects.project_code"),
        nullable=False
    )

    # Purchase_Order | Site_Transfer_Order
    order_type = db.Column(db.String(50), nullable=True)

    order_id = db.Column(
        db.Integer,
        db.ForeignKey("order_master.id"),
        nullable=True
    )

    # Sale_Dispatch | Internal_Transfer | Vendor_Return | Inter_Project
    transfer_type = db.Column(db.String(30), nullable=True)

    # Road | Rail | Air | Courier
    mode_of_transport = db.Column(db.String(30), nullable=True)

    preferred_carrier_id = db.Column(
        db.Integer,
        db.ForeignKey("vendors.id"),
        nullable=True
    )

    estimated_freight = db.Column(db.Numeric(17, 2), nullable=True)

    # Source / Destination (free text, supplemented by order FK)
    source_location = db.Column(db.String(300), nullable=True)
    destination_location = db.Column(db.String(300), nullable=True)

    priority = db.Column(db.String(20), default="Medium")  # High | Medium | Low
    required_delivery_date = db.Column(db.Date, nullable=True)

    purpose = db.Column(db.String(300), nullable=True)
    remarks = db.Column(db.Text, nullable=True)
    attached_doc = db.Column(db.Text, nullable=True)

    # ── workflow ──────────────────────────────────────────────────
    workflow_status = db.Column(db.String(30), default="Draft")
    # Operational transit status — set after TR is Approved
    # Values: Pending_Dispatch | In_Transit | Partially_Delivered | Delivered
    transit_status = db.Column(db.String(30), default="Pending_Dispatch", nullable=True)
    # Fulfillment against linked DCs: Open | Partial | Fulfilled | Cancelled
    fulfillment_status = db.Column(db.String(30), default="Open", nullable=True)
    status = db.Column(db.String(30), default="Active")
    current_level = db.Column(db.Integer, default=0)
    locked = db.Column(db.Boolean, default=False)

    # ── audit ─────────────────────────────────────────────────────
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    submitted_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    submitted_at = db.Column(db.DateTime, nullable=True)
    approved_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    final_approved_at = db.Column(db.DateTime, nullable=True)
    rejected_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    rejected_at = db.Column(db.DateTime, nullable=True)
    correction_sent_at = db.Column(db.DateTime, nullable=True)

    # ── relationships ─────────────────────────────────────────────
    project = db.relationship("Project", foreign_keys=[project_code], backref="transit_requests")
    order = db.relationship("OrderMaster", backref="transit_requests")
    preferred_carrier = db.relationship("Vendor", foreign_keys=[preferred_carrier_id])

    items = db.relationship(
        "TransitRequestItem",
        backref="transit_request",
        cascade="all,delete-orphan",
        order_by="TransitRequestItem.id",
    )

    creator = db.relationship("User", foreign_keys=[created_by])
    updater = db.relationship("User", foreign_keys=[updated_by])
    submitter = db.relationship("User", foreign_keys=[submitted_by])
    approver = db.relationship("User", foreign_keys=[approved_by])
    rejector = db.relationship("User", foreign_keys=[rejected_by])


class TransitRequestItem(db.Model):

    __tablename__ = "transit_request_items"

    id = db.Column(db.Integer, primary_key=True)

    tr_id = db.Column(
        db.Integer,
        db.ForeignKey("transit_requests.id"),
        nullable=False
    )

    order_item_id = db.Column(
        db.Integer,
        db.ForeignKey("order_items.id"),
        nullable=True
    )

    item_code = db.Column(
        db.String(50),
        db.ForeignKey("items.item_code"),
        nullable=True
    )

    is_asset = db.Column(db.Boolean, default=False, nullable=False)

    asset_code = db.Column(
        db.String(50),
        db.ForeignKey("assets.asset_code"),
        nullable=True
    )

    requested_qty = db.Column(db.Numeric(17, 4), nullable=False, default=0)
    remarks = db.Column(db.String(300), nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # ── relationships ─────────────────────────────────────────────
    order_item = db.relationship("OrderItem")
    item = db.relationship("Item")
    asset = db.relationship(
        "Asset",
        foreign_keys=[asset_code],
        primaryjoin="TransitRequestItem.asset_code == Asset.asset_code"
    )
