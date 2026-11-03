from sqlalchemy import Column, Integer, String, Float, Text, DateTime, Boolean
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
