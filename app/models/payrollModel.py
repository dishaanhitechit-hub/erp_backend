from app.extensions import db


class PayrollRun(db.Model):
    __tablename__ = "payroll_runs"

    id = db.Column(db.Integer, primary_key=True)
    month = db.Column(db.Integer, nullable=False)   # 1-12
    year = db.Column(db.Integer, nullable=False)
    status = db.Column(db.String(20), default="Draft")  # Draft | Processed | Paid
    run_date = db.Column(db.Date)
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    created_at = db.Column(db.DateTime, server_default=db.func.now())

    entries = db.relationship("PayrollEntry", backref="payroll_run", lazy=True)
    creator = db.relationship("User", backref="payroll_runs")

    def to_dict(self):
        return {
            "id": self.id,
            "month": self.month,
            "year": self.year,
            "status": self.status,
            "run_date": str(self.run_date) if self.run_date else None,
            "employee_count": len(self.entries),
            "created_at": str(self.created_at) if self.created_at else None,
        }


class PayrollEntry(db.Model):
    __tablename__ = "payroll_entries"

    id = db.Column(db.Integer, primary_key=True)
    payroll_run_id = db.Column(db.Integer, db.ForeignKey("payroll_runs.id"))
    employee_id = db.Column(db.Integer, db.ForeignKey("employees.id"))

    days_worked = db.Column(db.Integer, default=0)
    working_days = db.Column(db.Integer, default=26)

    basic = db.Column(db.Numeric(12, 2), default=0)
    hra = db.Column(db.Numeric(12, 2), default=0)
    special_allowance = db.Column(db.Numeric(12, 2), default=0)
    other_allowances = db.Column(db.Numeric(12, 2), default=0)
    bonus = db.Column(db.Numeric(12, 2), default=0)
    lop = db.Column(db.Numeric(12, 2), default=0)   # Loss of Pay

    pf = db.Column(db.Numeric(12, 2), default=0)
    esi = db.Column(db.Numeric(12, 2), default=0)
    pt = db.Column(db.Numeric(12, 2), default=0)    # Professional Tax
    tds = db.Column(db.Numeric(12, 2), default=0)

    gross = db.Column(db.Numeric(12, 2), default=0)
    total_deductions = db.Column(db.Numeric(12, 2), default=0)
    net_pay = db.Column(db.Numeric(12, 2), default=0)

    status = db.Column(db.String(20), default="Pending")  # Paid | Pending | On Hold

    employee = db.relationship("Employee", backref="payroll_entries")

    def to_dict(self):
        emp = self.employee
        return {
            "id": self.id,
            "payroll_run_id": self.payroll_run_id,
            "employee_id": self.employee_id,
            "emp_code": emp.emp_code if emp else None,
            "name": emp.full_name if emp else None,
            "dept": emp.department if emp else None,
            "designation": emp.designation if emp else None,
            "days_worked": self.days_worked,
            "working_days": self.working_days,
            "basic": float(self.basic or 0),
            "hra": float(self.hra or 0),
            "special_allowance": float(self.special_allowance or 0),
            "other_allowances": float(self.other_allowances or 0),
            "bonus": float(self.bonus or 0),
            "lop": float(self.lop or 0),
            "pf": float(self.pf or 0),
            "esi": float(self.esi or 0),
            "pt": float(self.pt or 0),
            "tds": float(self.tds or 0),
            "gross": float(self.gross or 0),
            "total_deductions": float(self.total_deductions or 0),
            "net_pay": float(self.net_pay or 0),
            "status": self.status,
        }
