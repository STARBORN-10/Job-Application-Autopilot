"""
SQLAlchemy models.

The schema is managed by Alembic (backend/alembic). Every change here needs a matching migration;
test_migrations.py checks that a migrated database matches these models.
"""
from sqlalchemy import Column, Integer, String, Float, Text, DateTime, Boolean, ForeignKey, UniqueConstraint
from database import Base
import datetime


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


class AppSettings(Base):
    """Key-value settings store. One row per setting."""
    __tablename__ = "app_settings"

    key = Column(String, primary_key=True, index=True)
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


class CandidateProfile(Base):
    """Structured profile extracted from a resume, cached by resume id + content hash."""
    __tablename__ = "candidate_profiles"

    id = Column(Integer, primary_key=True)
    resume_id = Column(Integer, index=True, nullable=False)
    resume_hash = Column(String, nullable=False)
    profile_json = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)


class ApiUsage(Base):
    """Monthly request counter per external provider (quota tracking)."""
    __tablename__ = "api_usage"
    __table_args__ = (UniqueConstraint("provider", "period", name="uq_api_usage_provider_period"),)

    id = Column(Integer, primary_key=True)
    provider = Column(String, nullable=False)
    period = Column(String, nullable=False)              # e.g. "2026-11"
    count = Column(Integer, default=0, nullable=False)
