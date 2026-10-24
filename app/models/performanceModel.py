from app.extensions import db


class PerformanceReview(db.Model):
    __tablename__ = "performance_reviews"

    id = db.Column(db.Integer, primary_key=True)
    employee_id = db.Column(db.Integer, db.ForeignKey("employees.id"))
    cycle_name = db.Column(db.String(80))          # e.g. "Annual 2026"
    rating = db.Column(db.Numeric(3, 1))           # 0.0–5.0
    goals_completion_pct = db.Column(db.Integer)   # 0–100+
    status = db.Column(db.String(20), default="Pending")
    # Pending | In Review | Completed | Overdue
    reviewer_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    next_review_date = db.Column(db.Date)
    pip_active = db.Column(db.Boolean, default=False)
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, server_default=db.func.now())

    employee = db.relationship("Employee", backref="performance_reviews")
    reviewer = db.relationship("User", backref="reviews_given")

    def to_dict(self):
        emp = self.employee
        return {
            "id": self.id,
            "employee_id": self.employee_id,
            "emp_code": emp.emp_code if emp else None,
            "name": emp.full_name if emp else None,
            "dept": emp.department if emp else None,
            "designation": emp.designation if emp else None,
            "cycle_name": self.cycle_name,
            "rating": float(self.rating) if self.rating else None,
            "goals_completion_pct": self.goals_completion_pct,
            "status": self.status,
            "pip_active": self.pip_active,
            "next_review_date": str(self.next_review_date) if self.next_review_date else None,
            "notes": self.notes,
            "created_at": str(self.created_at) if self.created_at else None,
        }


class DisciplineCase(db.Model):
    __tablename__ = "discipline_cases"

    id = db.Column(db.Integer, primary_key=True)
    case_code = db.Column(db.String(30), unique=True, nullable=False)
    employee_id = db.Column(db.Integer, db.ForeignKey("employees.id"))
    incident_type = db.Column(db.String(60))
    # Attendance | Insubordination | Policy Violation | Performance Issue | Misconduct
    severity = db.Column(db.String(20))   # Low | Medium | High | Critical
    incident_date = db.Column(db.Date)
    action_taken = db.Column(db.String(100))
    status = db.Column(db.String(30), default="Active")
    # Active | Pending SCN | Under Investigation | PIP Active | Resolved
    description = db.Column(db.Text)
    created_at = db.Column(db.DateTime, server_default=db.func.now())

    employee = db.relationship("Employee", backref="discipline_cases")

    def to_dict(self):
        emp = self.employee
        return {
            "id": self.id,
            "case_code": self.case_code,
            "employee_id": self.employee_id,
            "emp_code": emp.emp_code if emp else None,
            "name": emp.full_name if emp else None,
            "dept": emp.department if emp else None,
            "incident_type": self.incident_type,
            "severity": self.severity,
            "incident_date": str(self.incident_date) if self.incident_date else None,
            "action_taken": self.action_taken,
            "status": self.status,
            "description": self.description,
            "created_at": str(self.created_at) if self.created_at else None,
        }
