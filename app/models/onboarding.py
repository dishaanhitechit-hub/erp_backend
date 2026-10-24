from app.extensions import db

DEFAULT_TASKS = [
    ("Documentation", "Collect offer letter acceptance"),
    ("Documentation", "Collect educational certificates"),
    ("Documentation", "Collect ID proof (Aadhaar/Passport)"),
    ("Documentation", "Collect PAN card copy"),
    ("Documentation", "Collect bank details form"),
    ("Documentation", "Collect passport-size photographs"),
    ("IT Setup", "Create work email account"),
    ("IT Setup", "Issue laptop / desktop"),
    ("IT Setup", "Grant ERP system access"),
    ("IT Setup", "Setup VPN credentials"),
    ("HR Formalities", "Complete joining form"),
    ("HR Formalities", "Add to payroll system"),
    ("HR Formalities", "Explain leave & attendance policy"),
    ("HR Formalities", "Issue employee ID card"),
    ("Induction", "Company overview session"),
    ("Induction", "Introduce to team"),
    ("Induction", "Office tour / facility walkthrough"),
    ("Training", "Role-specific training schedule"),
    ("Training", "Compliance & safety training"),
]


class OnboardingTask(db.Model):
    __tablename__ = "onboarding_tasks"

    id = db.Column(db.Integer, primary_key=True)
    employee_id = db.Column(db.Integer, db.ForeignKey("employees.id"), nullable=False)
    category = db.Column(db.String(50))
    task_name = db.Column(db.String(200), nullable=False)
    status = db.Column(db.String(20), default="Pending")  # Pending | Done | NA
    due_date = db.Column(db.Date)
    completed_at = db.Column(db.DateTime)
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, server_default=db.func.now())

    employee = db.relationship("Employee", backref="onboarding_tasks")

    def to_dict(self):
        return {
            "id": self.id,
            "employee_id": self.employee_id,
            "category": self.category,
            "task_name": self.task_name,
            "status": self.status,
            "due_date": str(self.due_date) if self.due_date else None,
            "completed_at": str(self.completed_at) if self.completed_at else None,
            "notes": self.notes,
        }
