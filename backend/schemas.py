from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime

# ---------------------------------------------------------------------------
# Job Schemas (unchanged)
# ---------------------------------------------------------------------------

class JobBase(BaseModel):
    title: str
    company: str
    url: Optional[str] = None
    location: Optional[str] = None
    description: Optional[str] = None
    job_type: Optional[str] = None
    experience: Optional[str] = None
    source: Optional[str] = None
    score: Optional[float] = None
    match_reason: Optional[str] = None
    cover_letter: Optional[str] = None
    status: str = "To Apply"

class JobCreate(JobBase):
    pass

class JobUpdate(BaseModel):
    title: Optional[str] = None
    company: Optional[str] = None
    url: Optional[str] = None
    location: Optional[str] = None
    description: Optional[str] = None
    job_type: Optional[str] = None
    experience: Optional[str] = None
    source: Optional[str] = None
    score: Optional[float] = None
    match_reason: Optional[str] = None
    cover_letter: Optional[str] = None
    status: Optional[str] = None

class JobResponse(JobBase):
    id: int
    posted_date: Optional[datetime]
    date_found: Optional[datetime]

    class Config:
        from_attributes = True

# ---------------------------------------------------------------------------
# Resume Schemas
# ---------------------------------------------------------------------------

class ResumeResponse(BaseModel):
    id: int
    filename: str
    target_role: str
    file_size: Optional[int]
    is_active: bool
    uploaded_at: Optional[datetime]
    updated_at: Optional[datetime]
    # NOTE: extracted_text is intentionally omitted from list responses
    # to keep payloads small. Use the dedicated /api/resumes/{id}/text endpoint.

    class Config:
        from_attributes = True


class ResumeDetailResponse(ResumeResponse):
    """Full response that includes extracted_text — used by Make.com endpoint."""
    extracted_text: Optional[str]


class ResumeRoleUpdate(BaseModel):
    target_role: str


# ---------------------------------------------------------------------------
# Settings Schemas
# ---------------------------------------------------------------------------

class SettingItem(BaseModel):
    key: str
    value: str


class ExperienceFilterSettings(BaseModel):
    """Structured settings for the experience / role filter."""
    active_role: Optional[str] = "AI/ML Engineer"
    max_years_experience: int = 1      # reject jobs requiring more than this
    filter_enabled: bool = True


class MakeContextResponse(BaseModel):
    """Unified context returned to Make.com for AI evaluation & cover letters."""
    active_role: str
    resume_id: Optional[int] = None
    filename: Optional[str] = None
    extracted_text: Optional[str] = None
    experience_filter: ExperienceFilterSettings


class GeneralSettings(BaseModel):
    """User-configurable settings across job search, matching, and automations."""
    target_roles: str = "AI/ML Engineer, Data Analyst, Backend Developer, Python Developer, Automation Engineer"
    preferred_locations: str = "Remote, India, Hybrid"
    min_match_score: float = 7.0
    make_webhook_url: Optional[str] = ""
    active_role: str = "AI/ML Engineer"
    max_years_experience: int = 1
    filter_enabled: bool = True


class AutomationTriggerResponse(BaseModel):
    """Response returned when triggering Make.com automation."""
    status: str
    message: str
    details: Optional[dict] = None
