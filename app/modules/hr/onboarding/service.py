from app.extensions import db
from app.response import res
from app.models.onboarding import OnboardingTask, DEFAULT_TASKS
from app.models.employee import Employee
from datetime import datetime


def get_onboarding_list(data):
    search = data.get("search", "").strip()
    q = Employee.query

    if search:
        q = q.filter(
            db.or_(
                Employee.full_name.ilike(f"%{search}%"),
                Employee.emp_code.ilike(f"%{search}%"),
            )
        )

    employees = q.order_by(Employee.date_of_joining.desc()).all()
    result = []
    for emp in employees:
        tasks = OnboardingTask.query.filter_by(employee_id=emp.id).all()
        if not tasks:
            continue
        total = len(tasks)
        done = sum(1 for t in tasks if t.status == "Done")
        result.append({
            "id": emp.id,
            "emp_code": emp.emp_code,
            "full_name": emp.full_name,
            "designation": emp.designation,
            "department": emp.department,
            "date_of_joining": str(emp.date_of_joining) if emp.date_of_joining else None,
            "employee_status": emp.employee_status,
            "total_tasks": total,
            "done_tasks": done,
            "progress_pct": round((done / total) * 100) if total else 0,
            "onboarding_status": "Completed" if done == total else ("In Progress" if done > 0 else "Pending"),
        })
    return res("ok", result)


def get_employee_tasks(emp_id):
    emp = Employee.query.get(emp_id)
    if not emp:
        return res("Employee not found", {}, 404)

    tasks = OnboardingTask.query.filter_by(employee_id=emp_id).order_by(
        OnboardingTask.category, OnboardingTask.id
    ).all()

    categories = {}
    for t in tasks:
        cat = t.category or "General"
        categories.setdefault(cat, []).append(t.to_dict())

    total = len(tasks)
    done = sum(1 for t in tasks if t.status == "Done")

    return res("ok", {
        "employee": {
            "id": emp.id,
            "emp_code": emp.emp_code,
            "full_name": emp.full_name,
            "designation": emp.designation,
            "department": emp.department,
            "date_of_joining": str(emp.date_of_joining) if emp.date_of_joining else None,
        },
        "categories": categories,
        "summary": {
            "total": total,
            "done": done,
            "progress_pct": round((done / total) * 100) if total else 0,
        },
    })


def init_onboarding(emp_id, data):
    emp = Employee.query.get(emp_id)
    if not emp:
        return res("Employee not found", {}, 404)

    existing = OnboardingTask.query.filter_by(employee_id=emp_id).first()
    if existing:
        return res("Onboarding already initialised for this employee", {}, 400)

    custom_tasks = data.get("tasks", [])
    task_list = custom_tasks if custom_tasks else DEFAULT_TASKS

    for item in task_list:
        if isinstance(item, (list, tuple)):
            cat, name = item[0], item[1]
        else:
            cat = item.get("category", "General")
            name = item.get("task_name", "")

        task = OnboardingTask(
            employee_id=emp_id,
            category=cat,
            task_name=name,
            status="Pending",
        )
        db.session.add(task)

    db.session.commit()
    return get_employee_tasks(emp_id)


def update_task(task_id, data):
    task = OnboardingTask.query.get(task_id)
    if not task:
        return res("Task not found", {}, 404)

    if "status" in data:
        task.status = data["status"]
        if data["status"] == "Done" and not task.completed_at:
            task.completed_at = datetime.utcnow()
        elif data["status"] != "Done":
            task.completed_at = None

    if "notes" in data:
        task.notes = data["notes"]
    if "due_date" in data:
        task.due_date = data["due_date"]

    db.session.commit()
    return res("Task updated", task.to_dict())


def add_task(emp_id, data):
    emp = Employee.query.get(emp_id)
    if not emp:
        return res("Employee not found", {}, 404)

    task = OnboardingTask(
        employee_id=emp_id,
        category=data.get("category", "General"),
        task_name=data.get("task_name", ""),
        status=data.get("status", "Pending"),
        due_date=data.get("due_date"),
        notes=data.get("notes"),
    )
    db.session.add(task)
    db.session.commit()
    return res("Task added", task.to_dict(), 201)


def get_onboarding_stats():
    from sqlalchemy import func

    total_employees = Employee.query.count()

    emp_ids_with_onboarding = db.session.query(
        OnboardingTask.employee_id
    ).distinct().all()
    emp_ids = [r[0] for r in emp_ids_with_onboarding]

    completed = 0
    in_progress = 0
    pending = 0

    for eid in emp_ids:
        tasks = OnboardingTask.query.filter_by(employee_id=eid).all()
        total = len(tasks)
        done = sum(1 for t in tasks if t.status == "Done")
        if done == total:
            completed += 1
        elif done > 0:
            in_progress += 1
        else:
            pending += 1

    return res("ok", {
        "total_onboarding": len(emp_ids),
        "completed": completed,
        "in_progress": in_progress,
        "pending": pending,
    })
