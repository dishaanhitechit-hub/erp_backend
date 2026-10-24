from app.extensions import db
from app.response import res
from app.models.employee import Employee


def get_all_employees(data):
    q = Employee.query
    search = data.get("search", "").strip()
    dept = data.get("department", "").strip()
    status = data.get("status", "").strip()

    if search:
        q = q.filter(
            db.or_(
                Employee.full_name.ilike(f"%{search}%"),
                Employee.emp_code.ilike(f"%{search}%"),
                Employee.designation.ilike(f"%{search}%"),
            )
        )
    if dept:
        q = q.filter(Employee.department == dept)
    if status:
        q = q.filter(Employee.employee_status == status)

    employees = q.order_by(Employee.full_name).all()
    return res("ok", [e.to_dict() for e in employees])


def get_employee(emp_id):
    emp = Employee.query.get(emp_id)
    if not emp:
        return res("Employee not found", {}, 404)
    return res("ok", emp.to_detail_dict())


def create_employee(data):
    if not data.get("emp_code") or not data.get("full_name"):
        return res("emp_code and full_name are required", {}, 400)

    if Employee.query.filter_by(emp_code=data["emp_code"]).first():
        return res("Employee code already exists", {}, 400)

    emp = Employee(
        emp_code=data["emp_code"],
        full_name=data["full_name"],
        date_of_birth=data.get("date_of_birth"),
        gender=data.get("gender"),
        blood_group=data.get("blood_group"),
        nationality=data.get("nationality"),
        mother_tongue=data.get("mother_tongue"),
        marital_status=data.get("marital_status"),
        personal_mobile=data.get("personal_mobile"),
        personal_email=data.get("personal_email"),
        current_address=data.get("current_address"),
        permanent_address=data.get("permanent_address"),
        aadhaar_masked=data.get("aadhaar_masked"),
        pan_number=data.get("pan_number"),
        passport_number=data.get("passport_number"),
        passport_expiry=data.get("passport_expiry"),
        emergency_contact_name=data.get("emergency_contact_name"),
        emergency_contact_relation=data.get("emergency_contact_relation"),
        emergency_contact_mobile=data.get("emergency_contact_mobile"),
        designation=data.get("designation"),
        department=data.get("department"),
        date_of_joining=data.get("date_of_joining"),
        employment_type=data.get("employment_type"),
        employee_status=data.get("employee_status", "Active"),
        grade_band=data.get("grade_band"),
        reporting_manager_id=data.get("reporting_manager_id"),
        work_location=data.get("work_location"),
        cost_centre=data.get("cost_centre"),
        probation_end_date=data.get("probation_end_date"),
        confirmation_date=data.get("confirmation_date"),
        work_email=data.get("work_email"),
        desk_seat_number=data.get("desk_seat_number"),
        ctc_annual=data.get("ctc_annual", 0),
        basic_monthly=data.get("basic_monthly", 0),
        hra_monthly=data.get("hra_monthly", 0),
        special_allowance=data.get("special_allowance", 0),
        other_allowances=data.get("other_allowances", 0),
        pf_applicable=data.get("pf_applicable", True),
        pf_uan=data.get("pf_uan"),
        esi_applicable=data.get("esi_applicable", False),
        gratuity_eligible=data.get("gratuity_eligible", True),
        bank_name=data.get("bank_name"),
        bank_account_masked=data.get("bank_account_masked"),
        ifsc_code=data.get("ifsc_code"),
        payment_mode=data.get("payment_mode"),
        degree=data.get("degree"),
        specialization=data.get("specialization"),
        university=data.get("university"),
        year_of_passing=data.get("year_of_passing"),
        percentage_cgpa=data.get("percentage_cgpa"),
        total_experience=data.get("total_experience"),
        relevant_experience=data.get("relevant_experience"),
        primary_skills=data.get("primary_skills"),
        secondary_skills=data.get("secondary_skills"),
        cv_url=data.get("cv_url"),
    )
    db.session.add(emp)
    db.session.commit()
    return res("Employee created", emp.to_detail_dict(), 201)


def update_employee(emp_id, data):
    emp = Employee.query.get(emp_id)
    if not emp:
        return res("Employee not found", {}, 404)

    fields = [
        "full_name", "date_of_birth", "gender", "blood_group", "nationality",
        "mother_tongue", "marital_status", "personal_mobile", "personal_email",
        "current_address", "permanent_address", "aadhaar_masked", "pan_number",
        "passport_number", "passport_expiry", "emergency_contact_name",
        "emergency_contact_relation", "emergency_contact_mobile", "designation",
        "department", "date_of_joining", "employment_type", "employee_status",
        "grade_band", "reporting_manager_id", "work_location", "cost_centre",
        "probation_end_date", "confirmation_date", "work_email", "desk_seat_number",
        "ctc_annual", "basic_monthly", "hra_monthly", "special_allowance",
        "other_allowances", "pf_applicable", "pf_uan", "esi_applicable",
        "gratuity_eligible", "bank_name", "bank_account_masked", "ifsc_code",
        "payment_mode", "degree", "specialization", "university", "year_of_passing",
        "percentage_cgpa", "total_experience", "relevant_experience",
        "primary_skills", "secondary_skills", "cv_url",
    ]
    for f in fields:
        if f in data:
            setattr(emp, f, data[f])

    db.session.commit()
    return res("Employee updated", emp.to_detail_dict())


def get_departments():
    rows = db.session.query(Employee.department).filter(
        Employee.department.isnot(None)
    ).distinct().all()
    depts = sorted([r[0] for r in rows if r[0]])
    return res("ok", depts)
