from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import Optional, Any
import datetime
import json
import models, schemas
from services.dedupe import canonical_url as make_canonical_url


def _utcnow() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)


# ---------------------------------------------------------------------------
# Job CRUD
# ---------------------------------------------------------------------------

def get_job(db: Session, job_id: int):
    return db.query(models.Job).filter(models.Job.id == job_id).first()

def get_jobs(db: Session, skip: int = 0, limit: int = 100, approval_status: Optional[str] = None,
             sort: str = "newest"):
    # Ordering happens in SQL before offset/limit, so a limit never hides the newest (or best) jobs.
    q = db.query(models.Job)
    if approval_status:
        q = q.filter(func.coalesce(models.Job.approval_status, "pending") == approval_status)
    if sort == "score":
        q = q.order_by(func.coalesce(models.Job.score, -1).desc(), models.Job.id.desc())
    else:
        q = q.order_by(models.Job.id.desc())
    return q.offset(skip).limit(limit).all()


def get_top_jobs(db: Session, limit: int = 5, min_score: Optional[float] = None):
    """Highest score first (ties: newest first). Skipped and Rejected jobs are left out."""
    q = db.query(models.Job).filter(
        models.Job.score.isnot(None),
        func.coalesce(models.Job.approval_status, "pending") != "skipped",
        func.coalesce(models.Job.status, "To Apply") != "Rejected",
    )
    if min_score is not None:
        q = q.filter(models.Job.score >= min_score)
    return q.order_by(models.Job.score.desc(), models.Job.id.desc()).limit(limit).all()


def source_counts(db: Session) -> dict:
    """{source (lower case): {"primary": n, "seen": n}}: primary = the job's own source; seen = in source_names."""
    out: dict = {}
    for source, names in db.query(models.Job.source, models.Job.source_names).all():
        key = (source or "unknown").strip().lower()
        out.setdefault(key, {"primary": 0, "seen": 0})["primary"] += 1
        try:
            listed = json.loads(names) if names else []
        except ValueError:
            listed = []
        for name in {(n or "").strip().lower() for n in (listed if isinstance(listed, list) else [])} | {key}:
            if name:
                out.setdefault(name, {"primary": 0, "seen": 0})["seen"] += 1
    return out

def create_job(db: Session, job: schemas.JobCreate):
    data = job.model_dump()
    # JSON-valued fields are stored as text.
    names = data.pop("source_names", None) or ([job.source] if job.source else [])
    data["source_names"] = json.dumps(names)
    breakdown = data.pop("score_breakdown", None)
    data["score_breakdown"] = json.dumps(breakdown) if breakdown is not None else None
    if data.get("posted_date") is None:
        data.pop("posted_date", None)  # let the column default (now) apply, as in V1
    if not data.get("canonical_url") and job.url:
        data["canonical_url"] = make_canonical_url(job.url)
    data.setdefault("approval_status", "pending")
    data["last_seen"] = _utcnow()
    db_job = models.Job(**data)
    db.add(db_job)
    db.commit()
    db.refresh(db_job)
    return db_job


def touch_existing_job(db: Session, existing: models.Job, seen_sources: list[str]) -> models.Job:
    """A known job was returned again: record when, and by which sources."""
    try:
        names = json.loads(existing.source_names) if existing.source_names else []
    except ValueError:
        names = []
    if not names and existing.source:
        names = [existing.source]
    for name in seen_sources:
        if name and name not in names:
            names.append(name)
    existing.source_names = json.dumps(names)
    existing.last_seen = _utcnow()
    db.commit()
    return existing

def update_job(db: Session, job_id: int, job: schemas.JobUpdate):
    db_job = db.query(models.Job).filter(models.Job.id == job_id).first()
    if not db_job:
        return None
    for key, value in job.model_dump(exclude_unset=True).items():
        setattr(db_job, key, value)
    db.commit()
    db.refresh(db_job)
    return db_job

def delete_job(db: Session, job_id: int):
    db_job = db.query(models.Job).filter(models.Job.id == job_id).first()
    if not db_job:
        return None
    db.delete(db_job)
    db.commit()
    return db_job

def find_duplicate_job(db: Session, job: schemas.JobCreate) -> Optional[models.Job]:
    """
    Check if a job already exists in the database.
    1. Primary check: Exact or normalized URL match (including the V2 canonical URL).
    2. Fallback check: Case-insensitive Title + Company match when URL is missing/empty.
    """
    canonical = job.canonical_url or (make_canonical_url(job.url) if job.url else None)
    if canonical:
        existing = db.query(models.Job).filter(models.Job.canonical_url == canonical).first()
        if existing:
            return existing

    if job.url and job.url.strip():
        clean_url = job.url.strip()
        url_variants = [clean_url, clean_url.rstrip("/"), clean_url.rstrip("/") + "/"]
        existing = db.query(models.Job).filter(models.Job.url.in_(url_variants)).first()
        if existing:
            return existing

    # Fallback: match by title and company (case-insensitive & trimmed)
    if job.title and job.company:
        clean_title = job.title.strip().lower()
        clean_company = job.company.strip().lower()
        existing = db.query(models.Job).filter(
            func.lower(func.trim(models.Job.title)) == clean_title,
            func.lower(func.trim(models.Job.company)) == clean_company
        ).first()
        if existing:
            return existing

    return None

# ---------------------------------------------------------------------------
# Resume CRUD
# ---------------------------------------------------------------------------
# Resume CRUD
# ---------------------------------------------------------------------------

def get_resumes(db: Session, include_inactive: bool = True):
    """Return all resumes ordered by upload date so the UI can display and toggle them."""
    q = db.query(models.Resume)
    if not include_inactive:
        q = q.filter(models.Resume.is_active == True)
    return q.order_by(models.Resume.uploaded_at.desc()).all()

def get_resume(db: Session, resume_id: int) -> Optional[models.Resume]:
    return db.query(models.Resume).filter(models.Resume.id == resume_id).first()

def get_active_resume_for_role(db: Session, target_role: str) -> Optional[models.Resume]:
    return (
        db.query(models.Resume)
        .filter(models.Resume.target_role == target_role, models.Resume.is_active == True)
        .order_by(models.Resume.uploaded_at.desc())
        .first()
    )

def create_resume(
    db: Session,
    filename: str,
    target_role: str,
    extracted_text: str,
    file_path: str,
    file_size: int,
) -> models.Resume:
    # Deactivate any previous resumes for this target_role so this new one becomes active
    db.query(models.Resume).filter(models.Resume.target_role == target_role).update({"is_active": False})
    db_resume = models.Resume(
        filename=filename,
        target_role=target_role,
        extracted_text=extracted_text,
        file_path=file_path,
        file_size=file_size,
        is_active=True,
    )
    db.add(db_resume)
    db.commit()
    db.refresh(db_resume)
    return db_resume

def activate_resume(db: Session, resume_id: int) -> Optional[models.Resume]:
    """Select this resume as the active resume for its target role."""
    resume = db.query(models.Resume).filter(models.Resume.id == resume_id).first()
    if not resume:
        return None
    # Deactivate all other resumes for the same role
    db.query(models.Resume).filter(
        models.Resume.target_role == resume.target_role,
        models.Resume.id != resume_id,
    ).update({"is_active": False})
    resume.is_active = True
    db.commit()
    db.refresh(resume)
    return resume

def update_resume_role(db: Session, resume_id: int, target_role: str) -> Optional[models.Resume]:
    db_resume = db.query(models.Resume).filter(models.Resume.id == resume_id).first()
    if not db_resume:
        return None
    # Check if there is an active resume for the new target role
    existing_active = get_active_resume_for_role(db, target_role)
    db_resume.target_role = target_role
    if not existing_active:
        db_resume.is_active = True
    db.commit()
    db.refresh(db_resume)
    return db_resume

def replace_resume_file(
    db: Session,
    resume_id: int,
    filename: str,
    extracted_text: str,
    file_path: str,
    file_size: int,
) -> Optional[models.Resume]:
    """Replace the uploaded file for an existing resume record."""
    db_resume = db.query(models.Resume).filter(models.Resume.id == resume_id).first()
    if not db_resume:
        return None
    db_resume.filename = filename
    db_resume.extracted_text = extracted_text
    db_resume.file_path = file_path
    db_resume.file_size = file_size
    db.commit()
    db.refresh(db_resume)
    return db_resume

def soft_delete_resume(db: Session, resume_id: int) -> Optional[models.Resume]:
    db_resume = db.query(models.Resume).filter(models.Resume.id == resume_id).first()
    if not db_resume:
        return None
    db_resume.is_active = False
    db.commit()
    db.refresh(db_resume)
    return db_resume

def hard_delete_resume(db: Session, resume_id: int) -> Optional[models.Resume]:
    db_resume = db.query(models.Resume).filter(models.Resume.id == resume_id).first()
    if not db_resume:
        return None
    role = db_resume.target_role
    was_active = db_resume.is_active
    db.delete(db_resume)
    db.commit()
    # If the active resume was deleted, promote the next available resume for that role
    if was_active:
        next_resume = (
            db.query(models.Resume)
            .filter(models.Resume.target_role == role)
            .order_by(models.Resume.uploaded_at.desc())
            .first()
        )
        if next_resume:
            next_resume.is_active = True
            db.commit()
    return db_resume

# ---------------------------------------------------------------------------
# AppSettings CRUD
# ---------------------------------------------------------------------------

GENERAL_SETTINGS_KEY = "general_settings"

def get_setting(db: Session, key: str, default: str = "") -> str:
    row = db.query(models.AppSettings).filter(models.AppSettings.key == key).first()
    return row.value if row else default

def set_setting(db: Session, key: str, value: str) -> models.AppSettings:
    row = db.query(models.AppSettings).filter(models.AppSettings.key == key).first()
    if row:
        row.value = value
    else:
        row = models.AppSettings(key=key, value=value)
        db.add(row)
    db.commit()
    db.refresh(row)
    return row

def get_json_setting(db: Session, key: str, default: Any = None) -> Any:
    """Read a JSON-valued setting; returns `default` when missing or unreadable."""
    raw = get_setting(db, key, "")
    if not raw:
        return default
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return default

def set_json_setting(db: Session, key: str, value: Any) -> None:
    set_setting(db, key, json.dumps(value, default=str))

def get_experience_filter_settings(db: Session) -> schemas.ExperienceFilterSettings:
    """Retrieve structured experience filter settings from DB with fallback defaults."""
    raw = get_setting(db, "experience_filter", "{}")
    try:
        data = json.loads(raw)
    except Exception:
        data = {}
    defaults = schemas.ExperienceFilterSettings()
    return schemas.ExperienceFilterSettings(
        active_role=data.get("active_role", defaults.active_role),
        max_years_experience=data.get("max_years_experience", defaults.max_years_experience),
        filter_enabled=data.get("filter_enabled", defaults.filter_enabled),
    )

def get_general_settings(db: Session) -> schemas.GeneralSettings:
    """Retrieve all unified general settings from DB."""
    raw = get_setting(db, GENERAL_SETTINGS_KEY, "{}")
    try:
        data = json.loads(raw)
    except Exception:
        data = {}
    exp_settings = get_experience_filter_settings(db)
    defaults = schemas.GeneralSettings()
    return schemas.GeneralSettings(
        target_roles=data.get("target_roles", defaults.target_roles),
        preferred_locations=data.get("preferred_locations", defaults.preferred_locations),
        min_match_score=float(data.get("min_match_score", defaults.min_match_score)),
        make_webhook_url=data.get("make_webhook_url", defaults.make_webhook_url),
        active_role=data.get("active_role", exp_settings.active_role or defaults.active_role),
        max_years_experience=int(data.get("max_years_experience", exp_settings.max_years_experience)),
        filter_enabled=bool(data.get("filter_enabled", exp_settings.filter_enabled)),
        preferred_job_types=data.get("preferred_job_types", defaults.preferred_job_types),
        blocked_companies=data.get("blocked_companies", defaults.blocked_companies),
        blocked_keywords=data.get("blocked_keywords", defaults.blocked_keywords),
        max_job_age_days=int(data.get("max_job_age_days", defaults.max_job_age_days)),
    )

def update_general_settings(db: Session, settings: schemas.GeneralSettings) -> schemas.GeneralSettings:
    """Save general settings and sync experience_filter key."""
    set_setting(db, GENERAL_SETTINGS_KEY, settings.model_dump_json())
    # Keep experience_filter synced for backward compatibility
    exp_filter = schemas.ExperienceFilterSettings(
        active_role=settings.active_role,
        max_years_experience=settings.max_years_experience,
        filter_enabled=settings.filter_enabled,
    )
    set_setting(db, "experience_filter", exp_filter.model_dump_json())
    return settings
