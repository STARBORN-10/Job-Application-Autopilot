import json
from pydantic import BaseModel, Field, field_validator
from typing import Optional, List, Any
from datetime import datetime

# ---------------------------------------------------------------------------
# Job Schemas
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
    # V2 fields (optional, so V1 clients such as Make.com keep working unchanged)
    external_id: Optional[str] = None
    canonical_url: Optional[str] = None
    description_quality: Optional[str] = None   # "full" or "snippet"


def _parse_json_field(value: Any) -> Any:
    """Columns that hold JSON text are exposed as real lists/objects in the API."""
    if isinstance(value, str):
        try:
            return json.loads(value) if value.strip() else None
        except ValueError:
            return None
    return value


class JobCreate(JobBase):
    posted_date: Optional[datetime] = None
    source_names: List[str] = Field(default_factory=list)
    score_breakdown: Optional[dict] = None

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
    source_names: List[str] = Field(default_factory=list)
    score_breakdown: Optional[dict] = None
    approval_status: Optional[str] = "pending"
    last_seen: Optional[datetime] = None

    @field_validator("source_names", mode="before")
    @classmethod
    def _source_names(cls, value):
        parsed = _parse_json_field(value)
        return parsed if isinstance(parsed, list) else []

    @field_validator("score_breakdown", mode="before")
    @classmethod
    def _breakdown(cls, value):
        parsed = _parse_json_field(value)
        return parsed if isinstance(parsed, dict) else None

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
    # V2 hard filters (empty = no restriction)
    preferred_job_types: str = ""          # e.g. "Full-time, Internship"
    blocked_companies: str = ""            # comma-separated, case-insensitive
    blocked_keywords: str = ""             # comma-separated; matched against title + description
    max_job_age_days: int = Field(default=30, ge=1, le=365)


class AutomationTriggerResponse(BaseModel):
    """Response returned when triggering the automation pipeline."""
    status: str
    message: str
    details: Optional[dict] = None


# ---------------------------------------------------------------------------
# V2: sources
# ---------------------------------------------------------------------------

class SourceToggle(BaseModel):
    enabled: bool


class AtsCompany(BaseModel):
    provider: str                    # greenhouse / lever / ashby
    token: str                       # board name in the provider's URL, e.g. "groww"
    name: Optional[str] = None       # display name (defaults to the token)

    @field_validator("provider")
    @classmethod
    def _provider(cls, value: str) -> str:
        value = value.strip().lower()
        if value not in ("greenhouse", "lever", "ashby"):
            raise ValueError("provider must be greenhouse, lever or ashby")
        return value

    @field_validator("token")
    @classmethod
    def _token(cls, value: str) -> str:
        value = value.strip()
        if not value or not all(ch.isalnum() or ch in "-_." for ch in value):
            raise ValueError("token must be the board name from the careers URL (letters, digits, - _ .)")
        return value


class AtsCompanyList(BaseModel):
    companies: List[AtsCompany]
