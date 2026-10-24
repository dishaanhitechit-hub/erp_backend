from app.extensions import db


class Employee(db.Model):
    __tablename__ = "employees"

    id = db.Column(db.Integer, primary_key=True)
    emp_code = db.Column(db.String(30), unique=True, nullable=False)

    # Personal
    full_name = db.Column(db.String(150), nullable=False)
    date_of_birth = db.Column(db.Date)
    gender = db.Column(db.String(20))
    blood_group = db.Column(db.String(10))
    nationality = db.Column(db.String(50))
    mother_tongue = db.Column(db.String(50))
    marital_status = db.Column(db.String(20))
    personal_mobile = db.Column(db.String(20))
    personal_email = db.Column(db.String(120))

    # Address
    current_address = db.Column(db.Text)
    permanent_address = db.Column(db.Text)

    # Identity
    aadhaar_masked = db.Column(db.String(20))
    pan_number = db.Column(db.String(15))
    passport_number = db.Column(db.String(20))
    passport_expiry = db.Column(db.Date)

    # Emergency
    emergency_contact_name = db.Column(db.String(100))
    emergency_contact_relation = db.Column(db.String(30))
    emergency_contact_mobile = db.Column(db.String(20))

    # Employment
    designation = db.Column(db.String(100))
    department = db.Column(db.String(100))
    date_of_joining = db.Column(db.Date)
    employment_type = db.Column(db.String(30))        # Full-time, Contract, Intern, Part-time
    employee_status = db.Column(db.String(20), default="Active")  # Active, Inactive, On Notice
    grade_band = db.Column(db.String(30))
    reporting_manager_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    work_location = db.Column(db.String(100))
    cost_centre = db.Column(db.String(30))
    probation_end_date = db.Column(db.Date)
    confirmation_date = db.Column(db.Date)
    work_email = db.Column(db.String(120))
    desk_seat_number = db.Column(db.String(30))

    # Payroll
    ctc_annual = db.Column(db.Numeric(14, 2), default=0)
    basic_monthly = db.Column(db.Numeric(12, 2), default=0)
    hra_monthly = db.Column(db.Numeric(12, 2), default=0)
    special_allowance = db.Column(db.Numeric(12, 2), default=0)
    other_allowances = db.Column(db.Numeric(12, 2), default=0)
    pf_applicable = db.Column(db.Boolean, default=True)
    pf_uan = db.Column(db.String(30))
    esi_applicable = db.Column(db.Boolean, default=False)
    gratuity_eligible = db.Column(db.Boolean, default=True)
    bank_name = db.Column(db.String(80))
    bank_account_masked = db.Column(db.String(30))
    ifsc_code = db.Column(db.String(20))
    payment_mode = db.Column(db.String(20))

    # Qualifications
    degree = db.Column(db.String(50))
    specialization = db.Column(db.String(100))
    university = db.Column(db.String(150))
    year_of_passing = db.Column(db.Integer)
    percentage_cgpa = db.Column(db.String(20))
    total_experience = db.Column(db.Integer)
    relevant_experience = db.Column(db.Integer)
    primary_skills = db.Column(db.Text)
    secondary_skills = db.Column(db.Text)

    cv_url = db.Column(db.String(500))

    created_at = db.Column(db.DateTime, server_default=db.func.now())
    updated_at = db.Column(db.DateTime, server_default=db.func.now(), onupdate=db.func.now())

    # Relationships
    reporting_manager = db.relationship("User", backref="direct_reports")

    def to_dict(self):
        return {
            "id": self.id,
            "emp_code": self.emp_code,
            "full_name": self.full_name,
            "designation": self.designation,
            "department": self.department,
            "date_of_joining": str(self.date_of_joining) if self.date_of_joining else None,
            "employment_type": self.employment_type,
            "employee_status": self.employee_status,
            "grade_band": self.grade_band,
            "work_location": self.work_location,
            "work_email": self.work_email,
            "ctc_annual": float(self.ctc_annual or 0),
            "reporting_manager": self.reporting_manager.username if self.reporting_manager else None,
            "reporting_manager_id": self.reporting_manager_id,
        }

    def to_detail_dict(self):
        d = self.to_dict()
        d.update({
            "date_of_birth": str(self.date_of_birth) if self.date_of_birth else None,
            "gender": self.gender,
            "blood_group": self.blood_group,
            "nationality": self.nationality,
            "mother_tongue": self.mother_tongue,
            "marital_status": self.marital_status,
            "personal_mobile": self.personal_mobile,
            "personal_email": self.personal_email,
            "current_address": self.current_address,
            "permanent_address": self.permanent_address,
            "aadhaar_masked": self.aadhaar_masked,
            "pan_number": self.pan_number,
            "passport_number": self.passport_number,
            "passport_expiry": str(self.passport_expiry) if self.passport_expiry else None,
            "emergency_contact_name": self.emergency_contact_name,
            "emergency_contact_relation": self.emergency_contact_relation,
            "emergency_contact_mobile": self.emergency_contact_mobile,
            "cost_centre": self.cost_centre,
            "desk_seat_number": self.desk_seat_number,
            "probation_end_date": str(self.probation_end_date) if self.probation_end_date else None,
            "confirmation_date": str(self.confirmation_date) if self.confirmation_date else None,
            "basic_monthly": float(self.basic_monthly or 0),
            "hra_monthly": float(self.hra_monthly or 0),
            "special_allowance": float(self.special_allowance or 0),
            "other_allowances": float(self.other_allowances or 0),
            "pf_applicable": self.pf_applicable,
            "pf_uan": self.pf_uan,
            "esi_applicable": self.esi_applicable,
            "gratuity_eligible": self.gratuity_eligible,
            "bank_name": self.bank_name,
            "bank_account_masked": self.bank_account_masked,
            "ifsc_code": self.ifsc_code,
            "payment_mode": self.payment_mode,
            "degree": self.degree,
            "specialization": self.specialization,
            "university": self.university,
            "year_of_passing": self.year_of_passing,
            "percentage_cgpa": self.percentage_cgpa,
            "total_experience": self.total_experience,
            "relevant_experience": self.relevant_experience,
            "primary_skills": self.primary_skills,
            "secondary_skills": self.secondary_skills,
            "cv_url": self.cv_url,
            "reporting_manager_id": self.reporting_manager_id,
            "created_at": str(self.created_at) if self.created_at else None,
            "updated_at": str(self.updated_at) if self.updated_at else None,
        })
        return d
