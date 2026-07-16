from app.extensions import db
from datetime import datetime


class Supplier(db.Model):
    __tablename__ = "suppliers"

    id = db.Column(db.Integer, primary_key=True)

    supplier_code = db.Column(db.String(50), unique=True, nullable=False)

    # =====================================
    # SUPPLIER DETAILS (own copy, synced from vendor on vendor update)
    # =====================================

    supplier_name = db.Column(db.String(200), nullable=False)
    registered_address = db.Column(db.Text, nullable=True)
    corporate_address = db.Column(db.Text, nullable=True)

    # =====================================
    # CONTACT DETAILS
    # =====================================

    contact_person = db.Column(db.String(150), nullable=True)
    designation = db.Column(db.String(100), nullable=True)
    mobile_number = db.Column(db.String(20), nullable=True)
    whatsapp_number = db.Column(db.String(20), nullable=True)
    email = db.Column(db.String(150), nullable=True)

    # =====================================
    # SUPPLIER SPECIFIC
    # =====================================

    supplier_types = db.Column(db.JSON, nullable=True)
    nature_of_service = db.Column(db.JSON, nullable=True)
    service_description = db.Column(db.Text, nullable=True)

    # =====================================
    # STATUS + AUDIT
    # =====================================

    status = db.Column(db.String(30), default="Active")

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    created_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)

    created_by_user = db.relationship("User", backref="created_suppliers", lazy=True)

    # =====================================
    # RELATIONSHIPS
    # =====================================

    ledger_mappings = db.relationship("SupplierLedgerMap", backref="supplier", lazy=True, cascade="all, delete-orphan")
    project_mappings = db.relationship("SupplierProjectMap", backref="supplier", lazy=True, cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Supplier {self.supplier_code} - {self.supplier_name}>"


class SupplierLedgerMap(db.Model):
    __tablename__ = "supplier_ledger_map"

    id = db.Column(db.Integer, primary_key=True)
    supplier_id = db.Column(db.Integer, db.ForeignKey("suppliers.id", ondelete="CASCADE"), nullable=False)
    ledger_id = db.Column(db.Integer, db.ForeignKey("vendors.id", ondelete="CASCADE"), nullable=False)

    vendor = db.relationship("Vendor", backref="supplier_mappings", lazy=True)

    __table_args__ = (
        db.UniqueConstraint("supplier_id", "ledger_id", name="uq_supplier_ledger"),
    )

    def __repr__(self):
        return f"<SupplierLedgerMap supplier={self.supplier_id} ledger={self.ledger_id}>"


class SupplierProjectMap(db.Model):
    __tablename__ = "supplier_project_map"

    id = db.Column(db.Integer, primary_key=True)
    supplier_id = db.Column(db.Integer, db.ForeignKey("suppliers.id", ondelete="CASCADE"), nullable=False)
    project_id = db.Column(db.Integer, db.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    project_code = db.Column(db.String(50), nullable=True)
    assigned_at = db.Column(db.DateTime, default=datetime.utcnow)

    project = db.relationship("Project", lazy=True)

    __table_args__ = (
        db.UniqueConstraint("supplier_id", "project_id", name="uq_supplier_project"),
    )

    def __repr__(self):
        return f"<SupplierProjectMap supplier={self.supplier_id} project={self.project_id}>"
