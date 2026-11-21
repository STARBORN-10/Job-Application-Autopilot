import os
import datetime
import hmac
import json
import re
import shutil
import uuid
import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from dotenv import load_dotenv

import httpx
from fastapi import FastAPI, Depends, HTTPException, Header, UploadFile, File, Form, Query, BackgroundTasks, Response, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
from typing import List, Optional

import PyPDF2

load_dotenv(dotenv_path=Path(__file__).resolve().parent / ".env")

import models, schemas, crud
import db_migrations
from database import SessionLocal, engine, get_db
from security import require_admin, trigger_cooldown
from services.pipeline import run_automation_pipeline, get_pipeline_status
from services import ai_service, analytics as analytics_service, llm, telegram_bot
from services import notification_service
from services import export as export_service, resume_tailor
from services.autofill import policy as autofill_policy, runner as autofill_runner, service as autofill_service
from services.autofill.profile import ApplicantProfile, get_profile as get_applicant_profile, save_profile as save_applicant_profile
from services.progress import progress as pipeline_progress
from services.tasks import tasks as task_registry
from services.decisions import record_decision
from services.apply import emailer as apply_emailer, service as apply_service
from services.retry import retry_call
from services.scoring import tuning as scoring_tuning, weights as scoring_weights
from services.sources import registry as source_registry

logger = logging.getLogger("job_autopilot")

# ---------------------------------------------------------------------------
# Database schema
# ---------------------------------------------------------------------------
# Alembic migrations run in the lifespan handler below (with retries), so the app can still
# start and report a clear health status when the database is temporarily unreachable.

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

async def _scheduler_loop(interval_minutes: float):
    """Run the automation pipeline every `interval_minutes` (first run after one interval)."""
    while True:
        await asyncio.sleep(interval_minutes * 60)
        try:
            await asyncio.to_thread(run_automation_pipeline)
        except Exception:
            logger.exception("Scheduled pipeline run failed")


_db_state = {"ready": False, "error": None}


async def _init_db_with_retry(retry_seconds: float = 30.0):
    """Run migrations (upgrade head); if the database is unreachable (e.g. a paused hosted DB), keep retrying."""
    while True:
        try:
            await asyncio.to_thread(db_migrations.upgrade_database, engine)
            _db_state["ready"], _db_state["error"] = True, None
            logger.info("Database ready.")
            return
        except Exception as exc:
            _db_state["ready"], _db_state["error"] = False, type(exc).__name__
            logger.error(f"Database not reachable ({type(exc).__name__}); retrying in {retry_seconds:g}s")
            await asyncio.sleep(retry_seconds)


def _start_telegram_poller():
    """Local-development alternative to the webhook (TELEGRAM_MODE=polling); off by default."""
    if not telegram_bot.polling_enabled():
        return None
    if not (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip():
        logger.warning("TELEGRAM_MODE=polling but TELEGRAM_BOT_TOKEN is not set; Telegram polling disabled.")
        return None
    poller = telegram_bot.Poller(SessionLocal, on_approved=_on_approved)
    poller.start()
    logger.info("Telegram polling started (TELEGRAM_MODE=polling).")
    return poller


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Initialise the database (with retries) and start the optional scheduler and Telegram poller."""
    db_task = asyncio.create_task(_init_db_with_retry())
    poller = _start_telegram_poller()
    task = None
    try:
        interval = float(os.getenv("AUTO_RUN_INTERVAL_MINUTES", "0") or 0)
    except ValueError:
        logger.warning("Invalid AUTO_RUN_INTERVAL_MINUTES; scheduler disabled.")
        interval = 0
    if interval > 0:
        logger.info(f"Automation scheduler enabled: every {interval:g} minute(s).")
        task = asyncio.create_task(_scheduler_loop(interval))
    yield
    db_task.cancel()
    if task:
        task.cancel()
    if poller:
        poller.stop()


app = FastAPI(title="Job Application Autopilot API", lifespan=lifespan)

# ---------------------------------------------------------------------------
# CORS
# ---------------------------------------------------------------------------
# CORS_ORIGINS: comma-separated list (unset = allow every origin). FRONTEND_URL (the deployed dashboard)
# is always added. Local development origins (http://localhost:<any port>, http://127.0.0.1:<any port>)
# are always allowed, so a Vite dev server on 5173 or any other port works against a restricted backend.
def cors_settings() -> dict:
    cors_env = os.getenv("CORS_ORIGINS", "").strip()
    origins = [o.strip().rstrip("/") for o in cors_env.split(",") if o.strip()] if cors_env else ["*"]
    frontend = (os.getenv("FRONTEND_URL") or "").strip().rstrip("/")
    if frontend and "*" not in origins and frontend not in origins:
        origins.append(frontend)
    return {"allow_origins": origins, "allow_origin_regex": r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$"}


app.add_middleware(
    CORSMiddleware,
    **cors_settings(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition", "Retry-After"],
)

# Serve uploaded PDFs (for preview / download)
app.mount("/uploads", StaticFiles(directory=str(Path(__file__).parent / "uploads")), name="uploads")

# ---------------------------------------------------------------------------
# Auth helper for the legacy ingestion endpoints (POST /api/jobs, /api/make/*).
# DEPRECATED: these served the old Make.com scenario, which the native pipeline replaced. They are kept
# (with MAKE_API_KEY) only so existing external integrations and tests keep working.
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


@app.get("/api/health")
def health():
    """Liveness + database check. Returns 503 with a short reason when the database is unreachable."""
    try:
        with engine.connect() as conn:
            conn.exec_driver_sql("SELECT 1")
    except Exception as exc:
        # Only the error type is returned, never the connection string or credentials.
        raise HTTPException(status_code=503, detail=f"Database unreachable ({type(exc).__name__})")
    return {"status": "ok", "database": "ok", "tables_ready": _db_state["ready"]}


# ===========================================================================
# Jobs (unchanged)
# ===========================================================================

@app.get("/api/jobs", response_model=List[schemas.JobResponse])
def read_jobs(
    skip: int = 0,
    limit: int = 100,
    approval_status: Optional[str] = Query(None, pattern="^(pending|approved|skipped)$"),
    sort: str = Query("newest", pattern="^(newest|score)$"),
    db: Session = Depends(get_db),
):
    """Jobs, newest first (default) or best score first (`sort=score`; ties: newest first). The ordering is
    done by the database before the limit, so a limit never hides a higher-scoring older job."""
    return crud.get_jobs(db, skip=skip, limit=limit, approval_status=approval_status, sort=sort)


@app.get("/api/jobs/top", response_model=List[schemas.JobResponse])
def top_jobs(limit: int = Query(5, ge=1, le=100), min_score: Optional[float] = Query(None, ge=0, le=10),
             db: Session = Depends(get_db)):
    """Best matches: highest score first (ties: newest first), excluding skipped and rejected jobs."""
    return crud.get_top_jobs(db, limit=limit, min_score=min_score)

@app.get("/api/jobs/{job_id}", response_model=schemas.JobResponse)
def read_job(job_id: int, db: Session = Depends(get_db)):
    db_job = crud.get_job(db, job_id=job_id)
    if db_job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return db_job

@app.post("/api/jobs", response_model=schemas.JobResponse, dependencies=[Depends(verify_api_key)], deprecated=True)
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
# Analytics, export & AI compatibility analysis
# ===========================================================================

@app.get("/api/analytics")
def get_analytics(days: int = Query(30, ge=7, le=365), source: Optional[str] = Query(None, max_length=40),
                  db: Session = Depends(get_db)):
    """Aggregated statistics for the analytics dashboard (computed on demand). `source` limits it to jobs
    found on that source (primary or merged)."""
    jobs = crud.get_jobs(db, skip=0, limit=100000)
    if source:
        jobs = export_service.filter_jobs(jobs, source=source)
    data = analytics_service.build_analytics(jobs, days=days)
    data["source_filter"] = source
    return data


@app.get("/api/export/jobs.{fmt}")
def export_jobs(
    fmt: str,
    status: Optional[str] = Query(None, max_length=40),
    min_score: Optional[float] = Query(None, ge=0, le=10),
    source: Optional[str] = Query(None, max_length=40),
    approval_status: Optional[str] = Query(None, pattern="^(pending|approved|skipped)$"),
    db: Session = Depends(get_db),
):
    """Download jobs as CSV, Excel (.xlsx) or PDF, optionally filtered like the Job Listings page."""
    if fmt not in export_service.FORMATS:
        raise HTTPException(status_code=404, detail="Unknown export format. Use jobs.csv, jobs.xlsx or jobs.pdf.")
    jobs = export_service.filter_jobs(crud.get_jobs(db, skip=0, limit=100000), status=status, min_score=min_score,
                                      source=source, approval_status=approval_status)
    filters = ", ".join(f"{k}={v}" for k, v in (("status", status), ("min score", min_score), ("source", source),
                                                ("decision", approval_status)) if v not in (None, ""))
    try:
        content = export_service.render(fmt, jobs, filters)
    except ImportError as exc:
        raise HTTPException(status_code=501, detail=f"Export to {fmt} needs a missing package ({exc.name}). "
                                                    "Run: pip install -r requirements.txt")
    media_type, ext = export_service.FORMATS[fmt]
    stamp = datetime.date.today().isoformat()
    return Response(content=content, media_type=media_type,
                    headers={"Content-Disposition": f'attachment; filename="jobs-{stamp}.{ext}"'})


@app.post("/api/jobs/{job_id}/analyze")
def analyze_job_compatibility(job_id: int, db: Session = Depends(get_db)):
    """Skill-gap analysis of the active resume against one job (Gemini; generated on demand)."""
    job = crud.get_job(db, job_id=job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")

    active_role = crud.get_general_settings(db).active_role or "AI/ML Engineer"
    resume = crud.get_active_resume_for_role(db, active_role)
    if not resume or not (resume.extracted_text or "").strip():
        raise HTTPException(
            status_code=422,
            detail=f"No active resume with extracted text found for role '{active_role}'. Upload a resume first.",
        )

    try:
        return retry_call(
            lambda: ai_service.analyze_compatibility(
                job_title=job.title,
                company=job.company,
                job_description=job.description or "",
                resume_text=resume.extracted_text,
            ),
            retry_on=(ai_service.AITimeoutError, ai_service.AIRateLimitError, ai_service.AIResponseFormatError),
            label="Gemini compatibility analysis",
        )
    except ai_service.AIValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except ai_service.AIConfigError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except ai_service.AIRateLimitError as exc:
        raise HTTPException(status_code=429, detail=str(exc))
    except ai_service.AITimeoutError as exc:
        raise HTTPException(status_code=504, detail=str(exc))
    except ai_service.AIError as exc:
        raise HTTPException(status_code=502, detail=str(exc))


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
# Legacy ingestion endpoints (DEPRECATED)
# ---------------------------------------------------------------------------
# These served the old Make.com scenario, which the built-in Python pipeline replaced. They are kept,
# protected by MAKE_API_KEY (X-API-Key header), so existing deployments, external scripts and the test
# suites keep working. The dashboard no longer uses them. Do not build new features on them.
# ===========================================================================

@app.get(
    "/api/make/context",
    response_model=schemas.MakeContextResponse,
    dependencies=[Depends(verify_api_key)],
    deprecated=True,
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
    deprecated=True,
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
def trigger_automation(background_tasks: BackgroundTasks):
    """
    Trigger the native Python automation pipeline in the background.
    Rate limited: one manual start per TRIGGER_COOLDOWN_SECONDS (default 120 s), because each run
    spends API quota (JSearch: 200 requests/month on the free plan).
    """
    if get_pipeline_status()["running"]:
        return schemas.AutomationTriggerResponse(
            status="already_running",
            message="Automation pipeline is already running. Check /api/automation/status for progress.",
            details={},
        )
    wait = trigger_cooldown.try_acquire()
    if wait > 0:
        seconds = int(wait) + 1
        raise HTTPException(
            status_code=429,
            detail=f"A run was started recently. Please wait {seconds} more second(s) before starting another.",
            headers={"Retry-After": str(seconds)},
        )
    # Mark the run as starting right away, so a status poll made immediately after this response already
    # shows it (the background task may take a moment to begin).
    run_id = pipeline_progress.begin()
    background_tasks.add_task(_run_pipeline_from_trigger)
    return schemas.AutomationTriggerResponse(
        status="started",
        message="Automation pipeline started.",
        details={"run_id": run_id, "cooldown_seconds": int(trigger_cooldown.seconds())},
    )


def _run_pipeline_from_trigger() -> None:
    try:
        run_automation_pipeline(progress_begun=True)
    finally:
        # Never leave the progress panel spinning if the run did not report its end.
        from services import pipeline as _pipeline
        if pipeline_progress.is_active() and not _pipeline._pipeline_lock.locked():
            pipeline_progress.finish(False, "The run ended unexpectedly.", error="The run ended unexpectedly.")


@app.get("/api/automation/status")
def automation_status(db: Session = Depends(get_db)):
    """
    Whether the pipeline is running, live progress of the current run (stage, per-source state,
    counters, ids of jobs saved so far), the last finished run (survives restarts), per-source health
    and the seconds left before another manual start is allowed.
    """
    try:
        status = get_pipeline_status(db)
    except Exception as exc:
        logger.warning(f"Status with database details failed ({type(exc).__name__}); returning in-memory status")
        status = get_pipeline_status()
    status["cooldown_remaining"] = round(trigger_cooldown.remaining(), 1)
    status["cooldown_seconds"] = trigger_cooldown.seconds()
    return status


# ===========================================================================
# V2: job sources & AI providers
# ===========================================================================

@app.get("/api/sources")
def list_sources(db: Session = Depends(get_db)):
    """Every job source with enabled/configured/experimental flags and its last health record."""
    return source_registry.describe_sources(db)


@app.get("/api/sources/summary")
def sources_summary(db: Session = Depends(get_db)):
    """
    Every source the user can filter by: the registered sources plus any other source name found in the
    stored jobs (e.g. V1's "JSearch" or the legacy ingestion API), with job counts. `jobs` counts jobs whose
    own source is this one; `seen` also counts jobs merged from several sources that list it.
    """
    counts = crud.source_counts(db)
    out = []
    registered = {s["name"]: s for s in source_registry.describe_sources(db)}
    for name, s in registered.items():
        c = counts.pop(name, {"primary": 0, "seen": 0})
        out.append({"name": name, "label": s["label"], "registered": True, "enabled": s["enabled"],
                    "configured": s["configured"], "jobs": c["primary"], "seen": c["seen"]})
    for name, c in sorted(counts.items()):
        out.append({"name": name, "label": name, "registered": False, "enabled": None, "configured": None,
                    "jobs": c["primary"], "seen": c["seen"]})
    return out


@app.put("/api/sources/{name}")
def toggle_source(name: str, payload: schemas.SourceToggle, db: Session = Depends(get_db)):
    if source_registry.get_source(name) is None:
        raise HTTPException(status_code=404, detail=f"Unknown source '{name}'")
    source_registry.set_enabled(db, name, payload.enabled)
    return next(s for s in source_registry.describe_sources(db) if s["name"] == name)


@app.get("/api/settings/ats-companies", response_model=schemas.AtsCompanyList)
def get_ats_companies(db: Session = Depends(get_db)):
    return {"companies": source_registry.get_ats_companies(db)}


@app.put("/api/settings/ats-companies", response_model=schemas.AtsCompanyList)
def update_ats_companies(payload: schemas.AtsCompanyList, db: Session = Depends(get_db)):
    if len(payload.companies) > 25:
        raise HTTPException(status_code=422, detail="At most 25 companies (each one is a request per run).")
    companies = [c.model_dump() for c in payload.companies]
    for c in companies:
        c["name"] = c.get("name") or c["token"]
    source_registry.set_ats_companies(db, companies)
    return {"companies": companies}


@app.get("/api/scoring/weights")
def get_scoring_weights(db: Session = Depends(get_db)):
    """Current score weights (percent per part, sum 100) and the defaults."""
    return {"weights": scoring_weights.get_weights(db), "defaults": scoring_weights.DEFAULT_WEIGHTS,
            "parts": list(scoring_weights.PARTS)}


@app.put("/api/scoring/weights")
def update_scoring_weights(payload: dict, db: Session = Depends(get_db)):
    """Set the weights; they must be whole numbers 0-100 that add up to 100. Applies to future scores."""
    try:
        weights = scoring_weights.set_weights(db, payload.get("weights", payload))
    except scoring_weights.WeightsError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return {"weights": weights, "defaults": scoring_weights.DEFAULT_WEIGHTS, "parts": list(scoring_weights.PARTS)}


@app.post("/api/scoring/tune", dependencies=[Depends(require_admin)])
def tune_scoring_weights(apply: bool = Query(False), db: Session = Depends(get_db)):
    """
    Suggest weights learned from approve/skip decisions (needs 30+ decisions). Shows old vs new and
    only saves them with ?apply=true. Needs X-Admin-Key when ADMIN_API_KEY is set.
    """
    return scoring_tuning.tune(db, apply=apply)


def _after_approval(db: Session, job: models.Job) -> dict:
    """
    Everything that follows an approval, in order, never breaking the approval itself:
    1. tailored resume (AUTO_TAILOR_ON_APPROVE, default on; skipped when the score is already >= the threshold),
    2. apply with the safest method (e-mail, dry run by default, or assisted),
    3. for Greenhouse / Lever / Ashby pages, start pre-filling the form in the background (AUTOFILL_ON_APPROVE,
       needs Playwright; never submits unless explicitly allowed).
    """
    result = {"application": None, "tailored_resume": None, "tailor_error": None, "autofill_task": None,
              "autofill_note": None}
    if resume_tailor.auto_tailor_on_approve():
        try:
            result["tailored_resume"] = resume_tailor.to_dict(resume_tailor.tailor_for_job(db, job))
        except resume_tailor.TailorError as exc:
            result["tailor_error"] = str(exc)
        except Exception as exc:
            logger.exception(f"Tailoring the resume for job {job.id} failed")
            db.rollback()
            result["tailor_error"] = f"Tailoring failed ({type(exc).__name__}); the original resume is used."
    try:
        result["application"] = apply_service.apply_for_job(db, job)
    except Exception:
        logger.exception(f"Applying for job {job.id} failed")
        db.rollback()
    app_row = result["application"]
    if app_row is not None and app_row.method == "assisted" and autofill_service.supported_ats(job.url):
        if not autofill_policy.on_approve():
            result["autofill_note"] = "Form pre-fill on approve is off; use 'Pre-fill application form'."
        elif not autofill_runner.playwright_available():
            result["autofill_note"] = autofill_runner.INSTALL_HINT
        else:
            try:
                result["autofill_task"] = autofill_service.start_prefill(job.id)
            except autofill_service.AutofillUnavailable as exc:
                result["autofill_note"] = str(exc)
            except Exception:
                logger.exception(f"Starting the form pre-fill for job {job.id} failed")
                result["autofill_note"] = "Could not start the form pre-fill."
    return result


def _on_approved(db: Session, job: models.Job) -> Optional[models.Application]:
    """After an approval from Telegram: same steps as the dashboard. Returns the application row."""
    return _after_approval(db, job)["application"]


def _screenshot_url(app_row: models.Application, payload: dict) -> Optional[str]:
    return f"/api/applications/{app_row.id}/screenshot" if payload.get("screenshot") else None


def _application_out(app_row: Optional[models.Application], job: Optional[models.Job] = None) -> Optional[dict]:
    if app_row is None:
        return None
    try:
        payload = json.loads(app_row.payload_summary) if app_row.payload_summary else {}
    except ValueError:
        payload = {}
    # Never expose server file-system paths; the screenshot is served by its own endpoint.
    public = {k: v for k, v in payload.items() if k not in ("screenshot", "screenshot_after_submit")}
    out = {
        "id": app_row.id, "job_id": app_row.job_id, "method": app_row.method, "status": app_row.status,
        "dry_run": bool(app_row.dry_run), "payload_summary": public, "error": app_row.error,
        "outcome": apply_service.describe(app_row, payload),
        "resume_kind": payload.get("resume_kind"),
        "resume_file": payload.get("resume_file") or payload.get("attachment"),
        "screenshot_url": _screenshot_url(app_row, payload),
        "created_at": app_row.created_at.isoformat() if app_row.created_at else None,
        "updated_at": app_row.updated_at.isoformat() if app_row.updated_at else None,
    }
    if job is not None:
        out.update(job_title=job.title, job_company=job.company, job_url=job.url, job_source=job.source,
                   cover_letter=job.cover_letter if app_row.method in ("assisted", "autofill", "email") else None)
    return out


def _decide(job_id: int, decision: str, db: Session) -> dict:
    job = crud.get_job(db, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    outcome = record_decision(db, job, decision, channel="dashboard")
    extra = _after_approval(db, job) if outcome.changed and decision == "approved" else {}
    application = extra.get("application")
    db.refresh(job)
    app_out = _application_out(application, job)
    if decision == "approved":
        if not outcome.changed:
            message = "This job was already approved; nothing was repeated."
        elif app_out:
            message = app_out["outcome"]
        else:
            message = "Approved, but the apply step could not run (see the server log)."
    else:
        message = ("Skipped: the job is hidden from your top matches and counted as 'not interested' for score "
                   "tuning. Nothing was sent." if outcome.changed else "This job was already skipped.")
    return {"job": schemas.JobResponse.model_validate(job).model_dump(mode="json"), "changed": outcome.changed,
            "application": app_out, "message": message,
            "tailored_resume": extra.get("tailored_resume"), "tailor_error": extra.get("tailor_error"),
            "autofill_task": extra.get("autofill_task"), "autofill_note": extra.get("autofill_note")}


def _job_or_404(db: Session, job_id: int) -> models.Job:
    job = crud.get_job(db, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@app.get("/api/jobs/{job_id}/approve-preview")
def approve_preview(job_id: int, db: Session = Depends(get_db)):
    """Exactly what Approve will do for this job with the current configuration. Changes nothing."""
    return apply_service.preview(db, _job_or_404(db, job_id))


@app.get("/api/jobs/{job_id}/timeline")
def job_timeline(job_id: int, db: Session = Depends(get_db)):
    """Decisions, application attempts, tailored resumes and running tasks for one job, oldest first."""
    job = _job_or_404(db, job_id)
    events = []
    events.append({"at": job.date_found.isoformat() if job.date_found else None, "kind": "found",
                   "text": f"Found on {job.source or 'unknown source'}"})
    for d in db.query(models.JobDecision).filter(models.JobDecision.job_id == job_id).all():
        events.append({"at": d.decided_at.isoformat() if d.decided_at else None, "kind": f"decision_{d.decision}",
                       "text": f"{d.decision.capitalize()} ({d.channel or 'dashboard'})"})
    tailored = db.query(models.TailoredResume).filter(models.TailoredResume.job_id == job_id).all()
    for t in tailored:
        info = resume_tailor.to_dict(t)
        events.append({"at": info["created_at"], "kind": f"tailor_{t.status}", "text": info.get("message") or t.status})
    apps = db.query(models.Application).filter(models.Application.job_id == job_id).order_by(models.Application.id).all()
    for a in apps:
        events.append({"at": a.created_at.isoformat() if a.created_at else None, "kind": f"application_{a.method}",
                       "status": a.status, "text": apply_service.describe(a)})
    events.sort(key=lambda e: e["at"] or "")
    return {"events": events, "applications": [_application_out(a, job) for a in reversed(apps)],
            "tasks": task_registry.for_job(job_id)}


@app.post("/api/jobs/{job_id}/tailor-resume", dependencies=[Depends(require_admin)])
def tailor_resume(job_id: int, regenerate: bool = Query(False), db: Session = Depends(get_db)):
    """
    Create (or return the cached) tailored resume for this job. If the score is already at or above
    TAILOR_SCORE_THRESHOLD (default 9.0) the original resume is kept. `regenerate=true` forces a new version.
    """
    job = _job_or_404(db, job_id)
    try:
        row = resume_tailor.tailor_for_job(db, job, regenerate=regenerate)
    except resume_tailor.TailorError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return resume_tailor.to_dict(row, job)


@app.get("/api/jobs/{job_id}/tailored-resume")
def get_tailored_resume(job_id: int, db: Session = Depends(get_db)):
    """The latest tailored resume for this job and the active resume (404 when none was made yet)."""
    job = _job_or_404(db, job_id)
    resume = crud.get_active_resume_for_role(db, crud.get_general_settings(db).active_role)
    row = resume_tailor.latest(db, job.id, resume) if resume is not None else None
    if row is None:
        row = resume_tailor.latest(db, job.id)
        if row is None:
            raise HTTPException(status_code=404, detail="No tailored resume for this job yet.")
    data = resume_tailor.to_dict(row, job)
    data["outdated"] = resume is None or row.resume_id != resume.id
    return data


@app.get("/api/jobs/{job_id}/tailored-resume.{kind}")
def download_tailored_resume(job_id: int, kind: str, db: Session = Depends(get_db)):
    if kind not in ("pdf", "docx"):
        raise HTTPException(status_code=404, detail="Use .pdf or .docx")
    job = _job_or_404(db, job_id)
    row = resume_tailor.latest(db, job.id)
    if row is None or row.status != "tailored":
        raise HTTPException(status_code=404, detail="No tailored resume file for this job (the original is used).")
    try:
        path = resume_tailor.file_for(row, kind)
        db.commit()
    except ImportError as exc:
        raise HTTPException(status_code=501, detail=f"Rendering needs a missing package ({exc.name}).")
    if path is None:
        raise HTTPException(status_code=500, detail="The file could not be rendered.")
    safe_company = re.sub(r"[^A-Za-z0-9]+", "_", job.company or "company").strip("_")[:40] or "company"
    media = ("application/pdf" if kind == "pdf"
             else "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
    return FileResponse(str(path), media_type=media, filename=f"resume_{safe_company}_{job.id}.{kind}")


@app.post("/api/jobs/{job_id}/prefill", dependencies=[Depends(require_admin)])
def prefill_application(job_id: int, db: Session = Depends(get_db)):
    """Fill the Greenhouse / Lever / Ashby application form in the background (stops before submit by default)."""
    _job_or_404(db, job_id)
    try:
        return autofill_service.start_prefill(job_id)
    except autofill_service.AutofillUnavailable as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@app.get("/api/tasks/{task_id}")
def get_task(task_id: str):
    task = task_registry.get(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found (the server may have restarted).")
    return task


@app.get("/api/applications/{application_id}/screenshot")
def application_screenshot(application_id: int, after_submit: bool = False, db: Session = Depends(get_db)):
    row = db.get(models.Application, application_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Application not found")
    try:
        payload = json.loads(row.payload_summary or "{}")
    except ValueError:
        payload = {}
    raw = payload.get("screenshot_after_submit" if after_submit else "screenshot")
    base = autofill_service.screenshot_dir().resolve()
    path = Path(raw).resolve() if raw else None
    if path is None or not path.is_file() or base not in path.parents:
        raise HTTPException(status_code=404, detail="Screenshot not available.")
    return FileResponse(str(path), media_type="image/png")


@app.get("/api/settings/applicant-profile", response_model=ApplicantProfile)
def read_applicant_profile(db: Session = Depends(get_db)):
    """Contact details used to fill application forms (never visa, salary or EEO answers)."""
    return get_applicant_profile(db)


@app.put("/api/settings/applicant-profile", response_model=ApplicantProfile)
def update_applicant_profile(payload: ApplicantProfile, db: Session = Depends(get_db)):
    return save_applicant_profile(db, payload)


@app.get("/api/autofill/config")
def autofill_config(db: Session = Depends(get_db)):
    """Form-filling settings and whether Playwright is installed (for the Settings page)."""
    return {**autofill_policy.describe(), "playwright_installed": autofill_runner.playwright_available(),
            "install_hint": autofill_runner.INSTALL_HINT, "profile_missing": get_applicant_profile(db).missing_basics(),
            "tailor_threshold": resume_tailor.threshold(), "auto_tailor_on_approve": resume_tailor.auto_tailor_on_approve()}


@app.post("/api/jobs/{job_id}/apply", dependencies=[Depends(require_admin)])
def apply_job(job_id: int, db: Session = Depends(get_db)):
    """Retry applying for an approved job (e.g. after a failed or capped attempt). Never applies to unapproved jobs."""
    job = crud.get_job(db, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    try:
        application = apply_service.apply_for_job(db, job)
    except apply_service.NotApprovedError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return _application_out(application, job)


@app.get("/api/applications")
def list_applications(limit: int = Query(200, ge=1, le=1000), db: Session = Depends(get_db)):
    """Application log, newest first, with the job's title/company/link."""
    rows = db.query(models.Application).order_by(models.Application.id.desc()).limit(limit).all()
    jobs = {j.id: j for j in db.query(models.Job).filter(models.Job.id.in_({r.job_id for r in rows})).all()} if rows else {}
    return [_application_out(r, jobs.get(r.job_id)) for r in rows]


@app.get("/api/applications/config")
def applications_config(db: Session = Depends(get_db)):
    """What the apply step will do: dry-run flag (banner), daily cap and whether SMTP is set up."""
    return {"dry_run": apply_service.dry_run_enabled(), "daily_cap": apply_service.daily_cap(),
            "emails_today": apply_service.emails_today(db), "smtp_configured": apply_emailer.smtp_configured()}


@app.post("/api/jobs/{job_id}/approve", dependencies=[Depends(require_admin)])
def approve_job(job_id: int, db: Session = Depends(get_db)):
    """Approve a job (same as the Telegram Approve button). Needs X-Admin-Key when ADMIN_API_KEY is set."""
    return _decide(job_id, "approved", db)


@app.post("/api/jobs/{job_id}/skip", dependencies=[Depends(require_admin)])
def skip_job(job_id: int, db: Session = Depends(get_db)):
    """Skip a job (same as the Telegram Skip button). Needs X-Admin-Key when ADMIN_API_KEY is set."""
    return _decide(job_id, "skipped", db)


# ===========================================================================
# V2: Telegram approve / skip
# ===========================================================================

@app.post("/api/telegram/webhook")
async def telegram_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    x_telegram_bot_api_secret_token: Optional[str] = Header(default=None),
):
    """Receives button taps from Telegram. Only requests carrying TELEGRAM_WEBHOOK_SECRET are accepted."""
    secret = telegram_bot.webhook_secret()
    if not secret:
        logger.warning("Telegram webhook called but TELEGRAM_WEBHOOK_SECRET is not set; ignoring.")
        raise HTTPException(status_code=503, detail="Telegram webhook is not configured.")
    if not x_telegram_bot_api_secret_token or not hmac.compare_digest(x_telegram_bot_api_secret_token, secret):
        raise HTTPException(status_code=401, detail="Invalid webhook secret.")
    try:
        update = await request.json()
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid JSON")
    background_tasks.add_task(_process_telegram_update, update)
    return {"ok": True}


def _process_telegram_update(update: dict) -> None:
    db = SessionLocal()
    try:
        telegram_bot.handle_update(db, update, on_approved=_on_approved)
    except Exception:
        logger.exception("Failed to process a Telegram update")
    finally:
        db.close()


@app.post("/api/telegram/set-webhook", dependencies=[Depends(require_admin)])
def telegram_set_webhook(payload: Optional[dict] = None):
    """
    Register this backend's webhook with Telegram. Body: {"base_url": "https://your-backend"} or set
    PUBLIC_BACKEND_URL. Needs TELEGRAM_BOT_TOKEN and TELEGRAM_WEBHOOK_SECRET (and X-Admin-Key if configured).
    """
    base_url = ((payload or {}).get("base_url") or os.getenv("PUBLIC_BACKEND_URL") or "").strip()
    if not base_url:
        raise HTTPException(status_code=422, detail="Provide base_url or set PUBLIC_BACKEND_URL.")
    try:
        return telegram_bot.set_webhook(base_url)
    except notification_service.TelegramConfigError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except notification_service.TelegramNotificationError as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@app.get("/api/ai/providers")
def ai_providers():
    """Configured AI providers in fallback order (never returns keys)."""
    return [
        {"name": p.name, "configured": p.is_configured(), "extract_model": p.model_for("extract"),
         "write_model": p.model_for("write")}
        for p in llm.provider_order()
    ]
