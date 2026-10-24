from app.extensions import db
from app.response import res
from app.models.recruitment import JobOpening, Candidate, Interview
from app.models.employee import Employee
import random
import string


def get_job_openings(data):
    q = JobOpening.query
    search = data.get("search", "").strip()
    status = data.get("status", "").strip()
    dept = data.get("department", "").strip()

    if search:
        q = q.filter(
            db.or_(
                JobOpening.title.ilike(f"%{search}%"),
                JobOpening.department.ilike(f"%{search}%"),
            )
        )
    if status:
        q = q.filter(JobOpening.status == status)
    if dept:
        q = q.filter(JobOpening.department == dept)

    jobs = q.order_by(JobOpening.created_at.desc()).all()
    return res("ok", [j.to_dict() for j in jobs])


def create_job_opening(data):
    if not data.get("title"):
        return res("title is required", {}, 400)

    job = JobOpening(
        title=data["title"],
        department=data.get("department"),
        location=data.get("location"),
        openings_count=data.get("openings_count", 1),
        experience_required=data.get("experience_required"),
        job_type=data.get("job_type"),
        status=data.get("status", "Open"),
        description=data.get("description"),
        salary_band=data.get("salary_band"),
        deadline=data.get("deadline"),
    )
    db.session.add(job)
    db.session.commit()
    return res("Job opening created", job.to_dict(), 201)


def update_job_opening(job_id, data):
    job = JobOpening.query.get(job_id)
    if not job:
        return res("Job opening not found", {}, 404)

    for f in ["title", "department", "location", "openings_count",
              "experience_required", "job_type", "status", "description",
              "salary_band", "deadline"]:
        if f in data:
            setattr(job, f, data[f])

    db.session.commit()
    return res("Job opening updated", job.to_dict())


def get_candidates(data):
    q = Candidate.query
    job_id = data.get("jobId")
    stage = data.get("stage", "").strip()
    search = data.get("search", "").strip()

    if job_id:
        q = q.filter(Candidate.job_opening_id == job_id)
    if stage:
        q = q.filter(Candidate.stage == stage)
    if search:
        q = q.filter(
            db.or_(
                Candidate.name.ilike(f"%{search}%"),
                Candidate.email.ilike(f"%{search}%"),
            )
        )

    candidates = q.order_by(Candidate.created_at.desc()).all()
    return res("ok", [c.to_dict() for c in candidates])


def create_candidate(data):
    if not data.get("name") or not data.get("job_opening_id"):
        return res("name and job_opening_id are required", {}, 400)

    candidate = Candidate(
        job_opening_id=data["job_opening_id"],
        name=data["name"],
        email=data.get("email"),
        mobile=data.get("mobile"),
        resume_url=data.get("resume_url"),
        stage=data.get("stage", "Applied"),
        applied_date=data.get("applied_date"),
        notes=data.get("notes"),
        current_ctc=data.get("current_ctc"),
        expected_ctc=data.get("expected_ctc"),
        notice_period=data.get("notice_period"),
        source=data.get("source"),
    )
    db.session.add(candidate)
    db.session.commit()
    return res("Candidate created", candidate.to_dict(), 201)


def update_candidate_stage(candidate_id, data):
    candidate = Candidate.query.get(candidate_id)
    if not candidate:
        return res("Candidate not found", {}, 404)

    new_stage = data.get("stage")

    # Lock: cannot move to Joined without both letters generated
    if new_stage == "Joined":
        if not candidate.offer_letter_generated:
            return res("Cannot mark as Joined — Offer Letter has not been generated yet.", {}, 400)
        if not candidate.appointment_letter_generated:
            return res("Cannot mark as Joined — Appointment Letter has not been generated yet.", {}, 400)

    for f in ["stage", "notes", "current_ctc", "expected_ctc", "notice_period"]:
        if f in data:
            setattr(candidate, f, data[f])

    db.session.commit()

    # Auto-init onboarding when candidate joins
    if new_stage == "Joined":
        _auto_init_onboarding(candidate)

    return res("Candidate updated", candidate.to_dict())


def _auto_init_onboarding(candidate):
    from app.models.onboarding import OnboardingTask, DEFAULT_TASKS

    # Try to find existing employee by email
    emp = None
    if candidate.email:
        emp = Employee.query.filter_by(work_email=candidate.email).first()
        if not emp:
            emp = Employee.query.filter_by(personal_email=candidate.email).first()

    # Auto-create employee record if not found
    if not emp:
        suffix = ''.join(random.choices(string.digits, k=4))
        emp_code = f"EMP-{suffix}"
        while Employee.query.filter_by(emp_code=emp_code).first():
            suffix = ''.join(random.choices(string.digits, k=4))
            emp_code = f"EMP-{suffix}"

        job = candidate.job_opening
        emp = Employee(
            emp_code=emp_code,
            full_name=candidate.name,
            work_email=candidate.email,
            designation=job.title if job else None,
            department=job.department if job else None,
            employee_status="Active",
        )
        db.session.add(emp)
        db.session.flush()

    # Init onboarding tasks if not already done
    existing = OnboardingTask.query.filter_by(employee_id=emp.id).first()
    if not existing:
        for item in DEFAULT_TASKS:
            cat, name = item[0], item[1]
            task = OnboardingTask(
                employee_id=emp.id,
                category=cat,
                task_name=name,
                status="Pending",
            )
            db.session.add(task)
        db.session.commit()


def mark_offer_letter(candidate_id):
    candidate = Candidate.query.get(candidate_id)
    if not candidate:
        return res("Candidate not found", {}, 404)
    candidate.offer_letter_generated = True
    db.session.commit()
    return res("Offer letter marked as generated", candidate.to_dict())


def mark_appointment_letter(candidate_id):
    candidate = Candidate.query.get(candidate_id)
    if not candidate:
        return res("Candidate not found", {}, 404)
    candidate.appointment_letter_generated = True
    db.session.commit()
    return res("Appointment letter marked as generated", candidate.to_dict())


def get_offer_letter_data(candidate_id):
    candidate = Candidate.query.get(candidate_id)
    if not candidate:
        return res("Candidate not found", {}, 404)

    job = candidate.job_opening
    data = candidate.to_dict()
    data["job_title"] = job.title if job else None
    data["department"] = job.department if job else None
    data["job_type"] = job.job_type if job else None
    data["location"] = job.location if job else None
    return res("ok", data)


def get_pipeline_stats():
    stages = ["Applied", "Screening", "Interview", "Offer", "Joined", "Rejected"]
    stats = {}
    for stage in stages:
        stats[stage] = Candidate.query.filter_by(stage=stage).count()
    total_open = JobOpening.query.filter_by(status="Open").count()
    return res("ok", {"pipeline": stats, "open_positions": total_open})


# ─── Interviews ────────────────────────────────────────────────

def get_interviews(data):
    q = Interview.query
    candidate_id = data.get("candidate_id")
    status = data.get("status", "").strip()

    if candidate_id:
        q = q.filter(Interview.candidate_id == candidate_id)
    if status:
        q = q.filter(Interview.status == status)

    interviews = q.order_by(Interview.scheduled_date.asc(), Interview.scheduled_time.asc()).all()
    return res("ok", [i.to_dict() for i in interviews])


def create_interview(data):
    if not data.get("candidate_id"):
        return res("candidate_id is required", {}, 400)

    iv = Interview(
        candidate_id=data["candidate_id"],
        scheduled_date=data.get("scheduled_date"),
        scheduled_time=data.get("scheduled_time"),
        round_name=data.get("round_name"),
        mode=data.get("mode", "Video Call"),
        interviewer=data.get("interviewer"),
        status=data.get("status", "Scheduled"),
        feedback=data.get("feedback"),
        score=data.get("score"),
        decision=data.get("decision"),
    )
    db.session.add(iv)

    # Move candidate to Interview stage if still in Screening/Applied
    candidate = Candidate.query.get(data["candidate_id"])
    if candidate and candidate.stage in ("Applied", "Screening"):
        candidate.stage = "Interview"

    db.session.commit()
    return res("Interview scheduled", iv.to_dict(), 201)


def update_interview(iv_id, data):
    iv = Interview.query.get(iv_id)
    if not iv:
        return res("Interview not found", {}, 404)

    for f in ["scheduled_date", "scheduled_time", "round_name", "mode",
              "interviewer", "status", "feedback", "score", "decision"]:
        if f in data:
            setattr(iv, f, data[f])

    db.session.commit()
    return res("Interview updated", iv.to_dict())
