from pydantic import BaseModel
from typing import Optional
from datetime import datetime

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
