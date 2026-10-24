from app.extensions import db
from app.response import res
from app.models.recruitment import JobOpening, Candidate
from app.models.employee import Employee


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

    for f in ["stage", "notes", "current_ctc", "expected_ctc", "notice_period"]:
        if f in data:
            setattr(candidate, f, data[f])

    db.session.commit()
    return res("Candidate updated", candidate.to_dict())


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
