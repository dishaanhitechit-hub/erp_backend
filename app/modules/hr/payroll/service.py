from app.extensions import db
from app.response import res
from app.models.payrollModel import PayrollRun, PayrollEntry
from app.models.employee import Employee
from datetime import date


def get_payroll_list(data):
    q = PayrollEntry.query.join(PayrollRun)
    month = data.get("month")
    year = data.get("year")
    status = data.get("status", "").strip()
    search = data.get("search", "").strip()

    if month:
        q = q.filter(PayrollRun.month == month)
    if year:
        q = q.filter(PayrollRun.year == year)
    if status:
        q = q.filter(PayrollEntry.status == status)
    if search:
        q = q.join(Employee, PayrollEntry.employee_id == Employee.id).filter(
            db.or_(
                Employee.full_name.ilike(f"%{search}%"),
                Employee.emp_code.ilike(f"%{search}%"),
            )
        )

    entries = q.all()
    data_list = [e.to_dict() for e in entries]

    gross_total = sum(e.get("gross", 0) for e in data_list)
    net_total = sum(e.get("net_pay", 0) for e in data_list)
    deductions_total = sum(e.get("total_deductions", 0) for e in data_list)
    pending_count = sum(1 for e in data_list if e.get("status") == "Pending")

    return res("ok", {
        "entries": data_list,
        "summary": {
            "gross_total": round(gross_total, 2),
            "net_total": round(net_total, 2),
            "deductions_total": round(deductions_total, 2),
            "pending_count": pending_count,
            "employee_count": len(data_list),
        }
    })


def get_payslip(entry_id):
    entry = PayrollEntry.query.get(entry_id)
    if not entry:
        return res("Payroll entry not found", {}, 404)
    d = entry.to_dict()
    run = entry.payroll_run
    if run:
        d["month"] = run.month
        d["year"] = run.year
        d["run_status"] = run.status
    return res("ok", d)


def run_payroll(data):
    month = data.get("month")
    year = data.get("year")
    if not month or not year:
        return res("month and year are required", {}, 400)

    existing = PayrollRun.query.filter_by(month=month, year=year).first()
    if existing:
        return res("Payroll run already exists for this month", {}, 400)

    payroll_run = PayrollRun(
        month=month,
        year=year,
        status="Draft",
        run_date=date.today(),
        created_by=data.get("created_by"),
    )
    db.session.add(payroll_run)
    db.session.flush()

    employees = Employee.query.filter_by(employee_status="Active").all()
    for emp in employees:
        basic = float(emp.basic_monthly or 0)
        hra = float(emp.hra_monthly or 0)
        special = float(emp.special_allowance or 0)
        others = float(emp.other_allowances or 0)
        gross = basic + hra + special + others

        pf = round(basic * 0.12, 2) if emp.pf_applicable else 0
        esi = round(gross * 0.0075, 2) if emp.esi_applicable else 0
        pt = 200.0

        total_deductions = pf + esi + pt
        net_pay = gross - total_deductions

        entry = PayrollEntry(
            payroll_run_id=payroll_run.id,
            employee_id=emp.id,
            days_worked=26,
            working_days=26,
            basic=basic,
            hra=hra,
            special_allowance=special,
            other_allowances=others,
            gross=round(gross, 2),
            pf=pf,
            esi=esi,
            pt=pt,
            total_deductions=round(total_deductions, 2),
            net_pay=round(net_pay, 2),
            status="Pending",
        )
        db.session.add(entry)

    db.session.commit()
    return res("Payroll run created", payroll_run.to_dict(), 201)


def update_payroll_status(entry_id, data):
    entry = PayrollEntry.query.get(entry_id)
    if not entry:
        return res("Payroll entry not found", {}, 404)
    if "status" in data:
        entry.status = data["status"]
    db.session.commit()
    return res("Status updated", entry.to_dict())


def get_department_summary(data):
    month = data.get("month")
    year = data.get("year")

    q = db.session.query(
        Employee.department,
        db.func.sum(PayrollEntry.gross).label("gross"),
        db.func.sum(PayrollEntry.net_pay).label("net"),
        db.func.count(PayrollEntry.id).label("count"),
    ).join(PayrollEntry, PayrollEntry.employee_id == Employee.id)\
     .join(PayrollRun, PayrollEntry.payroll_run_id == PayrollRun.id)

    if month:
        q = q.filter(PayrollRun.month == month)
    if year:
        q = q.filter(PayrollRun.year == year)

    rows = q.group_by(Employee.department).all()
    result = [
        {
            "department": r[0] or "Unknown",
            "gross": float(r[1] or 0),
            "net": float(r[2] or 0),
            "count": r[3],
        }
        for r in rows
    ]
    return res("ok", result)
