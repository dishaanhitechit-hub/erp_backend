# app/models/advanceAdjustment.py
# Advance Adjustment — settles part of a vendor's outstanding advance (paid
# through Account › Payment › Advance against an ADVANCE Payment Request)
# against ONE bill: a Purchase Bill (of a BRR) or a Journal Entry (the
# vendor's Cr lines). One advance can be adjusted against many bills, in
# parts; one bill can take many advances. All bills of one advance are of one
# type (BRR or JOURNAL).
#
# Lines say how the amount sits on the bill's rows (product / CC wise):
#   line_type "item"    → pb_item_id   (purchase bill basic row)
#   line_type "gst"     → gst_type     (purchase bill GST row, plain e.g. "IGST")
#   line_type "journal" → je_line_id   (journal Dr CC line)
#
# Posting (source_type "advance_adjustment"):
#   Dr Vendor  per line, tagged with the line's CC (cost_centre_code)
#   Cr Vendor  total, untagged (the advance)
# Cancelling reverses the posting (-REV); nothing is deleted.

from app.extensions import db
from datetime import datetime
import uuid as _uuid_lib


class AdvanceAdjustmentMaster(db.Model):

    __tablename__ = "advance_adjustment_master"
    __table_args__ = (
        db.CheckConstraint(
            "workflow_status = 'Cancelled' OR "   # a deleted bill clears a cancelled adjustment's link
            "(link_type = 'BRR' AND purchase_bill_id IS NOT NULL AND journal_id IS NULL) OR "
            "(link_type = 'JOURNAL' AND journal_id IS NOT NULL AND purchase_bill_id IS NULL)",
            name="ck_advance_adjustment_link",
        ),
    )

    id             = db.Column(db.Integer, primary_key=True)
    adjustment_no  = db.Column(db.String(50), unique=True, nullable=False)
    adjustment_uuid = db.Column(db.String(36), unique=True, nullable=True,
                                default=lambda: str(_uuid_lib.uuid4()))
    adjustment_date = db.Column(db.Date, nullable=False)

    project_code = db.Column(db.String(50), db.ForeignKey("projects.project_code"), nullable=False, index=True)
    vendor_id    = db.Column(db.Integer, db.ForeignKey("vendors.id"), nullable=False, index=True)

    # the ADVANCE Payment Request whose paid money is adjusted
    payment_request_id = db.Column(db.Integer, db.ForeignKey("payment_request_master.id"),
                                   nullable=False, index=True)

    link_type        = db.Column(db.String(20), nullable=False)          # BRR | JOURNAL
    purchase_bill_id = db.Column(db.Integer, db.ForeignKey("purchase_bill_master.id"), nullable=True, index=True)
    brr_id           = db.Column(db.Integer, db.ForeignKey("brr_master.id"), nullable=True, index=True)
    journal_id       = db.Column(db.Integer, db.ForeignKey("journal_entry_master.id"), nullable=True, index=True)
    bill_no          = db.Column(db.String(100), nullable=True)           # snapshot: PB no / voucher no

    amount  = db.Column(db.Numeric(14, 2), nullable=False, default=0)
    remarks = db.Column(db.Text, nullable=True)

    # Approved = posted and counting ; Cancelled = reversed, kept for audit
    workflow_status = db.Column(db.String(30), nullable=False, default="Approved")

    created_by   = db.Column(db.Integer, db.ForeignKey("users.id"))
    created_at   = db.Column(db.DateTime, default=datetime.utcnow)
    cancelled_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    cancelled_at = db.Column(db.DateTime)
    cancel_reason = db.Column(db.Text)

    lines = db.relationship("AdvanceAdjustmentLine", backref="adjustment",
                            cascade="all, delete-orphan", order_by="AdvanceAdjustmentLine.sl_no")
    payment_request = db.relationship("PaymentRequestMaster", foreign_keys=[payment_request_id],
                                      backref=db.backref("adjustments", lazy="dynamic"))
    purchase_bill = db.relationship("PurchaseBillMaster", foreign_keys=[purchase_bill_id])
    journal       = db.relationship("JournalEntryMaster", foreign_keys=[journal_id])
    vendor        = db.relationship("Vendor", foreign_keys=[vendor_id])
    creator       = db.relationship("User", foreign_keys=[created_by])
    canceller     = db.relationship("User", foreign_keys=[cancelled_by])


class AdvanceAdjustmentLine(db.Model):

    __tablename__ = "advance_adjustment_line"

    id            = db.Column(db.Integer, primary_key=True)
    adjustment_id = db.Column(db.Integer, db.ForeignKey("advance_adjustment_master.id", ondelete="CASCADE"),
                              nullable=False, index=True)
    sl_no         = db.Column(db.Integer, nullable=False, default=1)

    line_type  = db.Column(db.String(10), nullable=False)       # item | gst | journal
    pb_item_id = db.Column(db.Integer, db.ForeignKey("purchase_bill_items.id"), nullable=True, index=True)
    gst_type   = db.Column(db.String(30), nullable=True)        # plain, e.g. "IGST"
    je_line_id = db.Column(db.Integer, db.ForeignKey("journal_entry_lines.id"), nullable=True, index=True)

    cc_code     = db.Column(db.String(50),  nullable=True)
    cc_name     = db.Column(db.String(255), nullable=True)
    description = db.Column(db.Text,        nullable=True)

    booked_amount = db.Column(db.Numeric(14, 2), default=0)
    amount        = db.Column(db.Numeric(14, 2), nullable=False, default=0)
