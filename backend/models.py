"""
SQLAlchemy models.

The schema is managed by Alembic (backend/alembic). Every change here needs a matching migration;
test_migrations.py checks that a migrated database matches these models.

Ownership: Job, Resume, AppSettings, JobDecision, Application, CandidateProfile and TailoredResume carry a
user_id. tenancy.py filters every query on them to the signed-in user and stamps new rows, so no endpoint can
forget to scope its data. SourceHealth and ApiUsage are shared on purpose (one provider key and quota).
"""
from sqlalchemy import Column, Integer, String, Float, Text, DateTime, Boolean, ForeignKey, UniqueConstraint
from database import Base
import datetime


class User(Base):
    """An account. Every job, resume, setting, decision and application belongs to exactly one user (user_id)."""
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    email = Column(String, nullable=False, unique=True, index=True)   # always stored lower-case
    password_hash = Column(String, nullable=False)                     # scrypt, never the password itself
    name = Column(String)
    is_active = Column(Boolean, default=True, nullable=False)
    token_version = Column(Integer, default=0, nullable=False)         # bump to sign the user out everywhere
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    last_login_at = Column(DateTime)
    telegram_chat_id = Column(String, index=True)                      # the chat that receives this user's alerts
    telegram_link_code = Column(String)                                # one-time code for "/start <code>" linking
    telegram_link_expires = Column(DateTime)


class Job(Base):
    __tablename__ = "jobs"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, index=True)
    company = Column(String, index=True)
    url = Column(String)
    location = Column(String)
    description = Column(Text)
    job_type = Column(String)
    experience = Column(String)
    source = Column(String)
    posted_date = Column(DateTime, default=datetime.datetime.utcnow)
    date_found = Column(DateTime, default=datetime.datetime.utcnow)
    score = Column(Float)
    match_reason = Column(Text)
    cover_letter = Column(Text)
    status = Column(String, default="To Apply")

    # --- V2 (all nullable / defaulted so V1 rows stay valid) ---
    external_id = Column(String)                 # id of the posting at its source
    canonical_url = Column(String, index=True)   # tracking-free URL used for de-duplication
    source_names = Column(Text)                  # JSON list: every source that returned this job
    score_breakdown = Column(Text)               # JSON: explainable score parts
    description_quality = Column(String)         # "full" or "snippet"
    approval_status = Column(String, default="pending", server_default="pending")  # pending/approved/skipped
    last_seen = Column(DateTime)                 # last time any source returned this job
    user_id = Column(Integer, index=True)        # owner (users.id); NULL = single-user / legacy data


class Resume(Base):
    __tablename__ = "resumes"

    id = Column(Integer, primary_key=True, index=True)
    filename = Column(String, nullable=False)          # original upload filename
    target_role = Column(String, nullable=False, index=True)  # e.g. "AI/ML Engineer"
    extracted_text = Column(Text)                      # full text extracted from PDF
    file_path = Column(String, nullable=False)         # path on disk
    file_size = Column(Integer)                        # bytes
    is_active = Column(Boolean, default=True)          # soft-delete flag
    uploaded_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)
    user_id = Column(Integer, index=True)        # owner (users.id); NULL = single-user / legacy data


class AppSettings(Base):
    """Key-value settings store. One row per (user, setting); user_id NULL = single-user / legacy."""
    __tablename__ = "app_settings"
    __table_args__ = (UniqueConstraint("user_id", "key", name="uq_app_settings_user_key"),)

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, index=True)
    key = Column(String, nullable=False, index=True)
    value = Column(Text, nullable=False)


class SourceHealth(Base):
    """Last outcome of each job source (one row per source)."""
    __tablename__ = "source_health"

    id = Column(Integer, primary_key=True)
    source_name = Column(String, nullable=False, unique=True)
    last_success_at = Column(DateTime)
    last_error_at = Column(DateTime)
    last_error = Column(Text)
    last_count = Column(Integer, default=0)
    total_runs = Column(Integer, default=0)


class JobDecision(Base):
    """An approve/skip decision on a job, with the score at decision time (training data for tuning)."""
    __tablename__ = "job_decisions"

    id = Column(Integer, primary_key=True)
    job_id = Column(Integer, ForeignKey("jobs.id", ondelete="CASCADE"), index=True, nullable=False)
    decision = Column(String, nullable=False)            # approved / skipped
    decided_at = Column(DateTime, default=datetime.datetime.utcnow)
    channel = Column(String)                             # telegram / dashboard
    score_snapshot = Column(Float)
    breakdown_snapshot = Column(Text)                    # JSON copy of jobs.score_breakdown
    user_id = Column(Integer, index=True)        # owner (users.id); NULL = single-user / legacy data


class Application(Base):
    """One application attempt for a job (email, assisted, ...)."""
    __tablename__ = "applications"

    id = Column(Integer, primary_key=True)
    job_id = Column(Integer, ForeignKey("jobs.id", ondelete="CASCADE"), index=True, nullable=False)
    method = Column(String, nullable=False)              # email / assisted
    status = Column(String, nullable=False)              # dry_run / sent / ready_to_submit / failed / skipped
    dry_run = Column(Boolean, default=True)
    payload_summary = Column(Text)                       # JSON: what was (or would have been) sent
    error = Column(Text)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)
    user_id = Column(Integer, index=True)        # owner (users.id); NULL = single-user / legacy data


class CandidateProfile(Base):
    """Structured profile extracted from a resume, cached by resume id + content hash."""
    __tablename__ = "candidate_profiles"

    id = Column(Integer, primary_key=True)
    resume_id = Column(Integer, index=True, nullable=False)
    resume_hash = Column(String, nullable=False)
    profile_json = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    user_id = Column(Integer, index=True)        # owner (users.id); NULL = single-user / legacy data


class ApiUsage(Base):
    """Monthly request counter per external provider (quota tracking)."""
    __tablename__ = "api_usage"
    __table_args__ = (UniqueConstraint("provider", "period", name="uq_api_usage_provider_period"),)

    id = Column(Integer, primary_key=True)
    provider = Column(String, nullable=False)
    period = Column(String, nullable=False)              # e.g. "2026-11"
    count = Column(Integer, default=0, nullable=False)


class TailoredResume(Base):
    """A resume rewritten for one job (only reordered / reworded facts from the original), with scores."""
    __tablename__ = "tailored_resumes"

    id = Column(Integer, primary_key=True)
    job_id = Column(Integer, ForeignKey("jobs.id", ondelete="CASCADE"), index=True, nullable=False)
    resume_id = Column(Integer, index=True, nullable=False)
    resume_hash = Column(String, nullable=False)         # version of the original resume text
    status = Column(String, nullable=False)              # tailored / not_needed / failed
    structured_json = Column(Text)                       # JSON: summary, skills, experience, projects, ...
    tailored_text = Column(Text)                         # plain-text rendering (preview, re-scoring)
    pdf_path = Column(String)                            # rendered files (regenerable from structured_json)
    docx_path = Column(String)
    score_before = Column(Float)
    score_after = Column(Float)
    breakdown_after = Column(Text)                       # JSON score breakdown with the tailored resume
    metrics = Column(Text)                               # JSON: keyword coverage before/after, stored score
    removed_unverified = Column(Text)                    # JSON list of items dropped by the verifier
    gaps = Column(Text)                                  # JSON list of skills the job wants that the resume lacks
    provider = Column(String)
    error = Column(Text)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    user_id = Column(Integer, index=True)        # owner (users.id); NULL = single-user / legacy data
