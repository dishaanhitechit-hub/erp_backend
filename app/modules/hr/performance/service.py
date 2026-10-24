from app.extensions import db
from app.response import res
from app.models.performanceModel import PerformanceReview, DisciplineCase
from app.models.employee import Employee
import uuid
from datetime import date


def get_reviews(data):
    q = PerformanceReview.query
    search = data.get("search", "").strip()
    status = data.get("status", "").strip()
    dept = data.get("department", "").strip()

    if search or dept:
        q = q.join(Employee, PerformanceReview.employee_id == Employee.id)
        if search:
            q = q.filter(
                db.or_(
                    Employee.full_name.ilike(f"%{search}%"),
                    Employee.emp_code.ilike(f"%{search}%"),
                )
            )
        if dept:
            q = q.filter(Employee.department == dept)
    if status:
        q = q.filter(PerformanceReview.status == status)

    reviews = q.order_by(PerformanceReview.created_at.desc()).all()
    return res("ok", [r.to_dict() for r in reviews])


def get_review(review_id):
    review = PerformanceReview.query.get(review_id)
    if not review:
        return res("Review not found", {}, 404)
    return res("ok", review.to_dict())


def create_review(data):
    if not data.get("employee_id"):
        return res("employee_id is required", {}, 400)

    review = PerformanceReview(
        employee_id=data["employee_id"],
        cycle_name=data.get("cycle_name"),
        rating=data.get("rating"),
        goals_completion_pct=data.get("goals_completion_pct"),
        status=data.get("status", "Pending"),
        reviewer_id=data.get("reviewer_id"),
        next_review_date=data.get("next_review_date"),
        pip_active=data.get("pip_active", False),
        notes=data.get("notes"),
    )
    db.session.add(review)
    db.session.commit()
    return res("Review created", review.to_dict(), 201)


def update_review(review_id, data):
    review = PerformanceReview.query.get(review_id)
    if not review:
        return res("Review not found", {}, 404)

    for f in ["cycle_name", "rating", "goals_completion_pct", "status",
              "reviewer_id", "next_review_date", "pip_active", "notes"]:
        if f in data:
            setattr(review, f, data[f])

    db.session.commit()
    return res("Review updated", review.to_dict())


def get_review_stats():
    total = PerformanceReview.query.count()
    completed = PerformanceReview.query.filter_by(status="Completed").count()
    pending = PerformanceReview.query.filter_by(status="Pending").count()
    overdue = PerformanceReview.query.filter_by(status="Overdue").count()
    pip = PerformanceReview.query.filter_by(pip_active=True).count()

    rating_dist = {str(i): PerformanceReview.query.filter(
        db.cast(PerformanceReview.rating, db.Integer) == i
    ).count() for i in range(1, 6)}

    return res("ok", {
        "total": total,
        "completed": completed,
        "pending": pending,
        "overdue": overdue,
        "pip_active": pip,
        "rating_distribution": rating_dist,
    })


def get_discipline_cases(data):
    q = DisciplineCase.query
    search = data.get("search", "").strip()
    severity = data.get("severity", "").strip()
    status = data.get("status", "").strip()

    if search:
        q = q.join(Employee, DisciplineCase.employee_id == Employee.id).filter(
            db.or_(
                Employee.full_name.ilike(f"%{search}%"),
                DisciplineCase.case_code.ilike(f"%{search}%"),
            )
        )
    if severity:
        q = q.filter(DisciplineCase.severity == severity)
    if status:
        q = q.filter(DisciplineCase.status == status)

    cases = q.order_by(DisciplineCase.created_at.desc()).all()
    return res("ok", [c.to_dict() for c in cases])


def create_discipline_case(data):
    if not data.get("employee_id"):
        return res("employee_id is required", {}, 400)

    case_code = f"DC-{date.today().year}-{str(uuid.uuid4())[:6].upper()}"
    case = DisciplineCase(
        case_code=case_code,
        employee_id=data["employee_id"],
        incident_type=data.get("incident_type"),
        severity=data.get("severity", "Low"),
        incident_date=data.get("incident_date"),
        action_taken=data.get("action_taken"),
        status=data.get("status", "Active"),
        description=data.get("description"),
    )
    db.session.add(case)
    db.session.commit()
    return res("Discipline case created", case.to_dict(), 201)


def update_discipline_case(case_id, data):
    case = DisciplineCase.query.get(case_id)
    if not case:
        return res("Case not found", {}, 404)

    for f in ["incident_type", "severity", "incident_date",
              "action_taken", "status", "description"]:
        if f in data:
            setattr(case, f, data[f])

    db.session.commit()
    return res("Case updated", case.to_dict())


def get_discipline_stats():
    total = DisciplineCase.query.count()
    active = DisciplineCase.query.filter_by(status="Active").count()
    resolved = DisciplineCase.query.filter_by(status="Resolved").count()
    pip = DisciplineCase.query.filter_by(status="PIP Active").count()
    critical = DisciplineCase.query.filter_by(severity="Critical").count()
    return res("ok", {
        "total": total,
        "active": active,
        "resolved": resolved,
        "pip_active": pip,
        "critical": critical,
    })
