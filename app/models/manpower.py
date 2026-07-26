from app.extensions import db
from datetime import datetime


class ManpowerWorker(db.Model):
    __tablename__ = "manpower_workers"

    id = db.Column(db.Integer, primary_key=True)

    man_id = db.Column(db.String(20), unique=True, nullable=False)  # Auto: MAN0001

    # ── Vendor link ──────────────────────────────────────────────
    vendor_id = db.Column(
        db.Integer,
        db.ForeignKey("vendors.id", ondelete="SET NULL"),
        nullable=True,
    )
    vendor = db.relationship("Vendor", backref="manpower_workers", lazy=True)

    # ── Personal info ─────────────────────────────────────────────
    full_name = db.Column(db.String(200), nullable=False)
    father_name = db.Column(db.String(200), nullable=True)
    nominee = db.Column(db.String(200), nullable=True)
    address = db.Column(db.Text, nullable=True)

    # ── Work info ─────────────────────────────────────────────────
    # stored as underscore key from LABOUR_CATEGORY_LIST (e.g. "Bar_Bender")
    category = db.Column(db.String(100), nullable=True)
    rate_per_manday = db.Column(db.Numeric(10, 2), nullable=True)
    date_of_joining = db.Column(db.Date, nullable=True)

    # ── Identity / compliance numbers ─────────────────────────────
    aadhar_number = db.Column(db.String(20), nullable=True)
    pan = db.Column(db.String(20), nullable=True)
    uan = db.Column(db.String(30), nullable=True)
    esic = db.Column(db.String(30), nullable=True)

    # ── Bank details ──────────────────────────────────────────────
    bank_account_number = db.Column(db.String(100), nullable=True)
    bank_name = db.Column(db.String(150), nullable=True)
    branch_name = db.Column(db.String(150), nullable=True)
    ifsc_code = db.Column(db.String(50), nullable=True)

    # ── Document files (BunnyCDN URLs) ────────────────────────────
    aadhar_file = db.Column(db.String(300), nullable=True)
    pan_file = db.Column(db.String(300), nullable=True)
    uan_file = db.Column(db.String(300), nullable=True)
    esic_file = db.Column(db.String(300), nullable=True)
    bank_details_file = db.Column(db.String(300), nullable=True)

    # ── Audit ─────────────────────────────────────────────────────
    status = db.Column(db.String(30), default="Active")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    created_by = db.Column(
        db.Integer,
        db.ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_by_user = db.relationship("User", backref="created_manpower_workers", lazy=True)

    def __repr__(self):
        return f"<ManpowerWorker {self.man_id} - {self.full_name}>"
