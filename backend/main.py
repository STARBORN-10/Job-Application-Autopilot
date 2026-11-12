import os
import json
import re
import shutil
import uuid
from pathlib import Path
from dotenv import load_dotenv

import httpx
from fastapi import FastAPI, Depends, HTTPException, Header, UploadFile, File, Form, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
from typing import List, Optional

import PyPDF2

import models, schemas, crud
from database import SessionLocal, engine, get_db

load_dotenv(dotenv_path=Path(__file__).resolve().parent / ".env")

# ---------------------------------------------------------------------------
# DB table creation
# ---------------------------------------------------------------------------
models.Base.metadata.create_all(bind=engine)

# ---------------------------------------------------------------------------
# Upload directory – store resume PDFs here
# ---------------------------------------------------------------------------
UPLOAD_DIR = Path(__file__).parent / "uploads" / "resumes"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

MAX_PDF_SIZE_MB = 10
ALLOWED_ROLES = [
    "AI/ML Engineer",
    "Data Analyst",
    "Backend Developer",
    "Python Developer",
    "Automation Engineer",
]

app = FastAPI(title="Job Application Autopilot API")

# ---------------------------------------------------------------------------
# CORS
# ---------------------------------------------------------------------------
cors_env = os.getenv("CORS_ORIGINS", "").strip()
allowed_origins = [o.strip() for o in cors_env.split(",") if o.strip()] if cors_env else ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve uploaded PDFs (for preview / download)
app.mount("/uploads", StaticFiles(directory=str(Path(__file__).parent / "uploads")), name="uploads")

# ---------------------------------------------------------------------------
# Auth helper (used by Make.com endpoints)
# ---------------------------------------------------------------------------
def verify_api_key(x_api_key: str | None = Header(default=None)):
    expected_key = os.getenv("MAKE_API_KEY")
    if not expected_key or x_api_key != expected_key:
        raise HTTPException(status_code=401, detail="Invalid API key")
    return True


# ---------------------------------------------------------------------------
# PDF text extraction helper
# ---------------------------------------------------------------------------
def extract_pdf_text(file_path: Path) -> str:
    """Extract plain text from a PDF using PyPDF2."""
    text_parts: list[str] = []
    try:
        with open(file_path, "rb") as f:
            reader = PyPDF2.PdfReader(f)
            for page in reader.pages:
                text = page.extract_text()
                if text:
                    text_parts.append(text)
    except Exception as exc:
        # Return partial text rather than crashing
        text_parts.append(f"[Extraction error: {exc}]")
    return "\n".join(text_parts).strip()


# ---------------------------------------------------------------------------
# Experience extraction helper
# ---------------------------------------------------------------------------
def extract_minimum_experience_years(exp_str: Optional[str]) -> Optional[float]:
    """
    Extracts the minimum required years of experience from an experience string.
    Returns:
        float: minimum required years (e.g. 0.0 for Fresher, 2.0 for '2-4 years' or '2+ yrs').
        None: if experience is missing, unspecified, or unclear (does not invent a value).
    """
    if not exp_str or not isinstance(exp_str, str):
        return None

    cleaned = exp_str.strip().lower()
    if not cleaned:
        return None

    # Fresher / entry-level / intern keywords
    fresher_keywords = [
        "fresher",
        "freshers",
        "intern",
        "internship",
        "trainee",
        "entry level",
        "entry-level",
        "graduate",
    ]
    if any(kw in cleaned for kw in fresher_keywords):
        return 0.0

    # Range pattern: e.g. "0-1 years", "0 to 2 yrs", "2-5 years", "3 - 5 Yrs", "1-2 Years"
    range_match = re.search(r'(\d+(?:\.\d+)?)\s*(?:-|to)\s*(\d+(?:\.\d+)?)\s*(?:years?|yrs?|yr)?\b', cleaned)
    if range_match:
        try:
            return float(range_match.group(1))
        except ValueError:
            pass

    # Single number with years or plus: e.g. "2+ years", "3+ Yrs", "1 year", "5 yrs", "2+ yrs"
    single_year_match = re.search(r'(\d+(?:\.\d+)?)\s*\+?\s*(?:years?|yrs?|yr)\b', cleaned)
    if single_year_match:
        try:
            return float(single_year_match.group(1))
        except ValueError:
            pass

    # Prefixed phrases: e.g. "min 2 years", "at least 3 yrs", "minimum 1 year"
    prefix_match = re.search(r'(?:min|minimum|at least)\s*(\d+(?:\.\d+)?)\s*(?:years?|yrs?|yr)?\b', cleaned)
    if prefix_match:
        try:
            return float(prefix_match.group(1))
        except ValueError:
            pass

    # Month-based experience: e.g. "6 months", "6+ mos"
    month_match = re.search(r'(\d+(?:\.\d+)?)\s*\+?\s*(?:months?|mos?|mo)\b', cleaned)
    if month_match:
        try:
            return float(month_match.group(1)) / 12.0
        except ValueError:
            pass

    # Plain digit: e.g. "0", "1", "2"
    if cleaned.isdigit():
        return float(cleaned)

    # Missing, unclear, or vague phrases ("not specified", "competitive", "any", "negotiable", "experienced", etc.)
    return None


# ===========================================================================
# Health
# ===========================================================================
@app.get("/")
def read_root():
    return {"message": "Job Application Autopilot API is running"}


# ===========================================================================
# Jobs (unchanged)
# ===========================================================================

@app.get("/api/jobs", response_model=List[schemas.JobResponse])
def read_jobs(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    jobs = crud.get_jobs(db, skip=skip, limit=limit)
    return jobs

@app.get("/api/jobs/{job_id}", response_model=schemas.JobResponse)
def read_job(job_id: int, db: Session = Depends(get_db)):
    db_job = crud.get_job(db, job_id=job_id)
    if db_job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return db_job

@app.post("/api/jobs", response_model=schemas.JobResponse, dependencies=[Depends(verify_api_key)])
def create_job(job: schemas.JobCreate, db: Session = Depends(get_db)):
    # 1. Duplicate job detection (URL primary match, Title+Company fallback)
    duplicate = crud.find_duplicate_job(db, job)
    if duplicate:
        return duplicate

    # 2. Experience filter enforcement
    filter_settings = crud.get_experience_filter_settings(db)
    if filter_settings.filter_enabled:
        min_years = extract_minimum_experience_years(job.experience)
        if min_years is not None and min_years > filter_settings.max_years_experience:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"Job rejected by experience filter: explicitly requires '{job.experience}' "
                    f"(min {min_years:g} years), which exceeds the configured maximum of "
                    f"{filter_settings.max_years_experience} year(s)."
                ),
            )

    return crud.create_job(db=db, job=job)

@app.put("/api/jobs/{job_id}", response_model=schemas.JobResponse)
def update_job(job_id: int, job: schemas.JobUpdate, db: Session = Depends(get_db)):
    db_job = crud.update_job(db, job_id=job_id, job=job)
    if db_job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return db_job

@app.delete("/api/jobs/{job_id}", response_model=schemas.JobResponse)
def delete_job(job_id: int, db: Session = Depends(get_db)):
    db_job = crud.delete_job(db, job_id=job_id)
    if db_job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return db_job


# ===========================================================================
# Resumes
# ===========================================================================

@app.get("/api/resumes", response_model=List[schemas.ResumeResponse])
def list_resumes(db: Session = Depends(get_db)):
    """Return all active resumes (no extracted_text to keep payload small)."""
    return crud.get_resumes(db)


@app.post("/api/resumes", response_model=schemas.ResumeResponse)
def upload_resume(
    target_role: str = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """Upload a new PDF resume and associate it with a target role."""
    # Validate role
    if target_role not in ALLOWED_ROLES:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid target_role. Allowed: {ALLOWED_ROLES}",
        )

    # Validate file type extension
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=422, detail="Only PDF files are accepted.")

    # Read content
    content = file.file.read()

    # Validate file size
    max_bytes = MAX_PDF_SIZE_MB * 1024 * 1024
    if len(content) > max_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"PDF exceeds maximum allowed size of {MAX_PDF_SIZE_MB} MB.",
        )

    # Validate PDF magic header bytes
    if not content.startswith(b"%PDF-"):
        raise HTTPException(
            status_code=422,
            detail="Invalid PDF file format. File does not start with standard PDF header.",
        )

    # Save to disk with unique prefix to avoid overwrite/collisions
    safe_basename = Path(file.filename).name.replace(" ", "_")
    unique_prefix = uuid.uuid4().hex[:8]
    safe_name = f"{unique_prefix}_{target_role.replace('/', '_').replace(' ', '_')}_{safe_basename}"
    dest_path = UPLOAD_DIR / safe_name
    with open(dest_path, "wb") as f_out:
        f_out.write(content)

    # Extract text
    extracted_text = extract_pdf_text(dest_path)

    # Persist to DB
    db_resume = crud.create_resume(
        db=db,
        filename=file.filename,
        target_role=target_role,
        extracted_text=extracted_text,
        file_path=str(dest_path),
        file_size=len(content),
    )
    return db_resume


@app.put("/api/resumes/{resume_id}/role", response_model=schemas.ResumeResponse)
def update_resume_role(
    resume_id: int,
    payload: schemas.ResumeRoleUpdate,
    db: Session = Depends(get_db),
):
    """Change the target role for an existing resume."""
    if payload.target_role not in ALLOWED_ROLES:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid target_role. Allowed: {ALLOWED_ROLES}",
        )
    db_resume = crud.update_resume_role(db, resume_id=resume_id, target_role=payload.target_role)
    if not db_resume:
        raise HTTPException(status_code=404, detail="Resume not found")
    return db_resume


@app.put("/api/resumes/{resume_id}/replace", response_model=schemas.ResumeResponse)
def replace_resume_file(
    resume_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """Replace the PDF file for an existing resume record."""
    db_resume = crud.get_resume(db, resume_id)
    if not db_resume:
        raise HTTPException(status_code=404, detail="Resume not found")

    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=422, detail="Only PDF files are accepted.")

    content = file.file.read()
    max_bytes = MAX_PDF_SIZE_MB * 1024 * 1024
    if len(content) > max_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"PDF exceeds maximum allowed size of {MAX_PDF_SIZE_MB} MB.",
        )

    if not content.startswith(b"%PDF-"):
        raise HTTPException(
            status_code=422,
            detail="Invalid PDF file format. File does not start with standard PDF header.",
        )

    # Remove old file if it exists
    old_path = Path(db_resume.file_path)
    if old_path.exists():
        try:
            old_path.unlink()
        except Exception:
            pass

    safe_basename = Path(file.filename).name.replace(" ", "_")
    unique_prefix = uuid.uuid4().hex[:8]
    safe_name = f"{unique_prefix}_{db_resume.target_role.replace('/', '_').replace(' ', '_')}_{safe_basename}"
    dest_path = UPLOAD_DIR / safe_name
    with open(dest_path, "wb") as f_out:
        f_out.write(content)

    extracted_text = extract_pdf_text(dest_path)

    db_resume = crud.replace_resume_file(
        db=db,
        resume_id=resume_id,
        filename=file.filename,
        extracted_text=extracted_text,
        file_path=str(dest_path),
        file_size=len(content),
    )
    return db_resume


@app.delete("/api/resumes/{resume_id}", response_model=schemas.ResumeResponse)
def delete_resume(resume_id: int, db: Session = Depends(get_db)):
    """Hard-delete a resume and its file from disk."""
    db_resume = crud.get_resume(db, resume_id)
    if not db_resume:
        raise HTTPException(status_code=404, detail="Resume not found")

    # Remove file from disk
    file_path = Path(db_resume.file_path)
    if file_path.exists():
        file_path.unlink()

    deleted = crud.hard_delete_resume(db, resume_id)
    return deleted


@app.get("/api/resumes/{resume_id}/text")
def get_resume_text(resume_id: int, db: Session = Depends(get_db)):
    """Return only the extracted text for a resume (used internally)."""
    db_resume = crud.get_resume(db, resume_id)
    if not db_resume:
        raise HTTPException(status_code=404, detail="Resume not found")
    return {"id": db_resume.id, "target_role": db_resume.target_role, "extracted_text": db_resume.extracted_text}


# ===========================================================================
# Make.com secure endpoints
# ===========================================================================

@app.get(
    "/api/make/context",
    response_model=schemas.MakeContextResponse,
    dependencies=[Depends(verify_api_key)],
)
def make_get_context(db: Session = Depends(get_db)):
    """
    Secure endpoint for Make.com.
    Returns:
    - Currently selected target role
    - That role's active resume details & extracted text (if uploaded)
    - Full experience-filter settings (max_years_experience, filter_enabled)
    Required header: X-API-Key: <MAKE_API_KEY env var>
    """
    settings = crud.get_experience_filter_settings(db)
    active_role = settings.active_role or "AI/ML Engineer"
    db_resume = crud.get_active_resume_for_role(db, active_role)

    return schemas.MakeContextResponse(
        active_role=active_role,
        resume_id=db_resume.id if db_resume else None,
        filename=db_resume.filename if db_resume else None,
        extracted_text=db_resume.extracted_text if db_resume else None,
        experience_filter=settings,
    )


@app.get(
    "/api/make/resume",
    response_model=schemas.ResumeDetailResponse,
    dependencies=[Depends(verify_api_key)],
)
def make_get_resume(
    role: str = Query(..., description="Target role to look up, e.g. 'AI/ML Engineer'"),
    db: Session = Depends(get_db),
):
    """
    Secure endpoint for Make.com.
    Returns the most recently uploaded active resume for the given role,
    including the extracted_text field for AI matching / cover letter generation.

    Required header: X-API-Key: <MAKE_API_KEY env var>
    """
    db_resume = crud.get_active_resume_for_role(db, role)
    if not db_resume:
        raise HTTPException(
            status_code=404,
            detail=f"No active resume found for role '{role}'.",
        )
    return db_resume


# ===========================================================================
# Settings
# ===========================================================================

@app.put("/api/resumes/{resume_id}/activate", response_model=schemas.ResumeResponse)
def activate_resume(resume_id: int, db: Session = Depends(get_db)):
    """Set this resume as the active resume for its target role."""
    db_resume = crud.activate_resume(db, resume_id=resume_id)
    if not db_resume:
        raise HTTPException(status_code=404, detail="Resume not found")
    return db_resume


# ===========================================================================
# Settings & Automations
# ===========================================================================

EXPERIENCE_SETTINGS_KEY = "experience_filter"

@app.get("/api/settings", response_model=schemas.GeneralSettings)
def get_settings(db: Session = Depends(get_db)):
    """Retrieve full unified general settings for job search and Make.com automation."""
    return crud.get_general_settings(db)


@app.put("/api/settings", response_model=schemas.GeneralSettings)
def update_settings(payload: schemas.GeneralSettings, db: Session = Depends(get_db)):
    """Update unified general settings."""
    return crud.update_general_settings(db, payload)


@app.get("/api/settings/experience-filter", response_model=schemas.ExperienceFilterSettings)
def get_experience_filter(db: Session = Depends(get_db)):
    return crud.get_experience_filter_settings(db)


@app.put("/api/settings/experience-filter", response_model=schemas.ExperienceFilterSettings)
def update_experience_filter(payload: schemas.ExperienceFilterSettings, db: Session = Depends(get_db)):
    crud.set_setting(db, EXPERIENCE_SETTINGS_KEY, payload.model_dump_json())
    return payload


@app.post("/api/automation/trigger", response_model=schemas.AutomationTriggerResponse)
def trigger_automation(db: Session = Depends(get_db)):
    """
    Trigger the configured Make.com webhook to find new jobs.
    Passes the current active role and matching preferences in the payload.
    """
    settings = crud.get_general_settings(db)
    webhook_url = settings.make_webhook_url or os.getenv("MAKE_WEBHOOK_URL", "")

    if not webhook_url or not webhook_url.strip():
        raise HTTPException(
            status_code=400,
            detail="Make.com Webhook URL is not configured. Please add your webhook URL in Settings.",
        )

    context_payload = {
        "active_role": settings.active_role,
        "max_years_experience": settings.max_years_experience,
        "filter_enabled": settings.filter_enabled,
        "min_match_score": settings.min_match_score,
        "trigger_source": "dashboard",
    }

    try:
        resp = httpx.post(webhook_url.strip(), json=context_payload, timeout=10.0)
        if resp.status_code >= 400:
            raise HTTPException(
                status_code=502,
                detail=f"Make.com webhook returned HTTP status {resp.status_code}: {resp.text[:200]}",
            )
        return schemas.AutomationTriggerResponse(
            status="success",
            message=f"Job search triggered successfully for '{settings.active_role}'! New matching opportunities will appear on your dashboard.",
            details={"active_role": settings.active_role, "status_code": resp.status_code},
        )
    except httpx.RequestError as exc:
        raise HTTPException(
            status_code=504,
            detail=f"Failed to connect to Make.com webhook: {str(exc)}",
        )
