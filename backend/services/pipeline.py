"""
Pipeline Orchestrator Service Module
Orchestrates end-to-end automated job discovery:
1. Concurrency protection via threading.Lock
2. Context and active resume retrieval from database
3. JSearch job fetching
4. Pre-Gemini duplicate detection and experience filtering
5. Gemini AI evaluation and match scoring
6. Minimum match score threshold filtering
7. Database persistence via crud.create_job
8. Post-commit Telegram notifications
9. Isolated session lifecycle and fault-tolerant per-job processing
"""

import re
import logging
import threading
from typing import Optional, Dict, Any, List

try:
    import crud
    import schemas
    from database import SessionLocal
    from services import jsearch_service
    from services import ai_service
    from services import notification_service
except ImportError:
    from backend import crud
    from backend import schemas
    from backend.database import SessionLocal
    from backend.services import jsearch_service
    from backend.services import ai_service
    from backend.services import notification_service

logger = logging.getLogger("pipeline_orchestrator")
logger.setLevel(logging.INFO)

# Global execution lock to prevent overlapping runs
_pipeline_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Experience Extraction Helper (Preserving logic from main.py)
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

    return None


# ---------------------------------------------------------------------------
# Pipeline Orchestrator Core
# ---------------------------------------------------------------------------
def run_automation_pipeline(
    db_session: Optional[Any] = None,
    session_factory=SessionLocal,
    jsearch_client: Optional[Any] = None,
    ai_client: Optional[Any] = None,
    telegram_client: Optional[Any] = None,
    num_pages: int = 1,
) -> Dict[str, Any]:
    """
    Executes the automated job application discovery pipeline.
    Guarantees thread-safe single-run execution, isolated DB session cleanup,
    early pre-filtering, and post-commit notifications.

    Parameters:
        db_session: Optional pre-configured SQLAlchemy Session (used in tests).
        session_factory: Callable returning a new Session (defaults to SessionLocal).
        jsearch_client: Optional httpx.Client for mocked JSearch operations.
        ai_client: Optional client for mocked Gemini AI operations.
        telegram_client: Optional httpx.Client for mocked Telegram operations.
        num_pages: Number of JSearch result pages to fetch (default 1).

    Returns:
        Dict summarizing pipeline execution metrics.
    """
    # 1. Thread-safe concurrency check
    acquired = _pipeline_lock.acquire(blocking=False)
    if not acquired:
        logger.warning("Pipeline run rejected: another automation run is already in progress.")
        return {
            "status": "already_running",
            "message": "Automation pipeline is already currently running.",
            "total_fetched": 0,
            "duplicates_skipped": 0,
            "experience_filtered": 0,
            "ai_evaluated": 0,
            "saved": 0,
            "notified": 0,
            "failed": 0,
            "details": [],
        }

    summary: Dict[str, Any] = {
        "status": "started",
        "message": "",
        "active_role": "",
        "total_fetched": 0,
        "duplicates_skipped": 0,
        "experience_filtered": 0,
        "ai_evaluated": 0,
        "saved": 0,
        "notified": 0,
        "failed": 0,
        "details": [],
    }

    # 2. Database session lifecycle management
    db = db_session
    managed_session = False

    try:
    if db is None:
        db = session_factory()
        managed_session = True
        # 3. Retrieve settings and active profile
        settings = crud.get_general_settings(db)
        active_role = settings.active_role or "AI/ML Engineer"
        min_match_score = getattr(settings, "min_match_score", None)
        if min_match_score is None:
            min_match_score = 7.0
        preferred_locations = getattr(settings, "preferred_locations", "Remote, India, Hybrid")
        max_years_experience = getattr(settings, "max_years_experience", 1)
        filter_enabled = getattr(settings, "filter_enabled", True)

        summary["active_role"] = active_role

        # 4. Retrieve active resume
        active_resume = crud.get_active_resume_for_role(db, active_role)
        if not active_resume or not active_resume.extracted_text or not active_resume.extracted_text.strip():
            msg = f"No active resume with extracted text found for role '{active_role}'. Please upload a resume first."
            logger.warning(msg)
            summary["status"] = "error"
            summary["message"] = msg
            return summary

        resume_text = active_resume.extracted_text.strip()

        # 5. Fetch jobs from JSearch
        try:
            fetched_jobs = jsearch_service.fetch_jobs(
                active_role=active_role,
                preferred_locations=preferred_locations,
                num_pages=num_pages,
                client=jsearch_client,
            )
        except Exception as j_exc:
            msg = f"Job discovery failed: {j_exc}"
            logger.error(msg)
            summary["status"] = "error"
            summary["message"] = msg
            return summary

        summary["total_fetched"] = len(fetched_jobs)
        logger.info(f"Pipeline fetched {len(fetched_jobs)} candidate jobs for role '{active_role}'.")

        # 6. Process each job with fault-tolerant isolation
        for job in fetched_jobs:
            job_title = job.title or "Unknown Role"
            job_company = job.company or "Unknown Company"

            try:
                # -----------------------------------------------------------
                # Step A: Pre-Gemini Duplicate Detection (Zero AI Token Cost)
                # -----------------------------------------------------------
                duplicate = crud.find_duplicate_job(db, job)
                if duplicate:
                    summary["duplicates_skipped"] += 1
                    logger.info(f"Duplicate job skipped before AI evaluation: '{job_title}' at '{job_company}'")
                    summary["details"].append({
                        "title": job_title,
                        "company": job_company,
                        "status": "duplicate_skipped",
                        "reason": f"Already exists in database (ID: {duplicate.id})",
                    })
                    continue

                # -----------------------------------------------------------
                # Step B: Pre-Gemini Experience Filter (Zero AI Token Cost)
                # -----------------------------------------------------------
                if filter_enabled:
                    min_years = extract_minimum_experience_years(job.experience)
                    if min_years is not None and min_years > max_years_experience:
                        summary["experience_filtered"] += 1
                        logger.info(
                            f"Experience filter skipped job: '{job_title}' at '{job_company}' "
                            f"(requires {job.experience}, min {min_years:g}y > max {max_years_experience}y)"
                        )
                        summary["details"].append({
                            "title": job_title,
                            "company": job_company,
                            "status": "experience_filtered",
                            "reason": f"Requires {min_years:g}y, exceeding max {max_years_experience}y",
                        })
                        continue

                # -----------------------------------------------------------
                # Step C: Gemini AI Match Evaluation & Cover Letter Generation
                # -----------------------------------------------------------
                logger.info(f"Calling Gemini to evaluate: '{job_title}' at '{job_company}'")
                eval_result = ai_service.evaluate_job(
                    job_title=job_title,
                    company=job_company,
                    job_description=job.description or "",
                    resume_text=resume_text,
                    active_role=active_role,
                    max_years_experience=max_years_experience,
                    client=ai_client,
                )
                summary["ai_evaluated"] += 1

                job.score = eval_result.score
                job.match_reason = eval_result.match_reason
                job.cover_letter = eval_result.cover_letter

                # -----------------------------------------------------------
                # Step D: Match Score Threshold Filter
                # -----------------------------------------------------------
                if job.score < min_match_score:
                    logger.info(
                        f"Job below minimum score: '{job_title}' at '{job_company}' "
                        f"(Score: {job.score:.1f} < Threshold: {min_match_score:.1f})"
                    )
                    summary["details"].append({
                        "title": job_title,
                        "company": job_company,
                        "status": "score_below_threshold",
                        "score": job.score,
                        "reason": f"Score {job.score:.1f} below minimum threshold {min_match_score:.1f}",
                    })
                    continue

                # -----------------------------------------------------------
                # Step E: Database Persistence
                # -----------------------------------------------------------
                saved_job = crud.create_job(db=db, job=job)
                summary["saved"] += 1
                logger.info(f"Persisted qualifying job to database (ID: {saved_job.id}, Score: {saved_job.score})")

                # -----------------------------------------------------------
                # Step F: Telegram Notification (STRICTLY POST-COMMIT)
                # -----------------------------------------------------------
                notified = False
                try:
                    notification_service.send_job_alert(
                        title=saved_job.title,
                        company=saved_job.company,
                        score=saved_job.score,
                        match_reason=saved_job.match_reason,
                        url=saved_job.url,
                        experience=saved_job.experience,
                        location=saved_job.location,
                        client=telegram_client,
                    )
                    summary["notified"] += 1
                    notified = True
                    logger.info(f"Telegram notification sent for job ID {saved_job.id}")
                except Exception as notify_exc:
                    logger.warning(f"Telegram notification failed for job ID {saved_job.id}: {notify_exc}")

                summary["details"].append({
                    "title": saved_job.title,
                    "company": saved_job.company,
                    "status": "saved",
                    "job_id": saved_job.id,
                    "score": saved_job.score,
                    "notified": notified,
                })

            except Exception as item_exc:
                summary["failed"] += 1
                logger.error(f"Error processing job '{job_title}' at '{job_company}': {item_exc}")
                summary["details"].append({
                    "title": job_title,
                    "company": job_company,
                    "status": "failed",
                    "error": str(item_exc),
                })
                # Continue processing remaining jobs in the batch

        summary["status"] = "success"
        summary["message"] = (
            f"Job automation complete: {summary['saved']} new qualifying jobs saved, "
            f"{summary['notified']} alerts sent, {summary['duplicates_skipped']} duplicates skipped, "
            f"{summary['experience_filtered']} filtered by experience."
        )
        return summary


    finally:
        try:
            if managed_session and db is not None:
                try:
                    db.close()
                    logger.info("Pipeline database session closed.")
                except Exception:
                    logger.exception("Failed to close pipeline database session.")
        finally:
            _pipeline_lock.release()
