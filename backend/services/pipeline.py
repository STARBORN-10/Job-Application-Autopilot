"""
Pipeline Orchestrator Service Module

One run:
1. Concurrency protection (one run at a time)
2. Settings, the active resume and its cached candidate profile
3. Every enabled source, each isolated (services/sources/runner.py)
4. Cross-source de-duplication (services/dedupe.py)
5. Database duplicate check (known jobs only get last_seen / source_names updated)
6. Hard filters (experience, location, job type, blocked company/keyword) - no AI cost
7. Cheap keyword pre-score for every job; only the top LLM_MAX_JOBS_PER_RUN (default 15) get
   AI fact extraction, a re-score and (if they pass the minimum score) an AI cover letter
8. Save with the score breakdown, then (strictly after the commit) a Telegram alert
9. The run summary is kept in memory and persisted to app_settings, so it survives restarts
"""

import os
import re
import logging
import threading
import datetime
from collections import Counter
from typing import Optional, Dict, Any

import crud
import schemas
from database import SessionLocal
from services import dedupe, geo, jsearch_service, llm, notification_service
from services.retry import retry_call
from services.scoring import facts as facts_mod, profile as profile_mod, weights as weights_mod
from services.scoring.engine import score_job
from services.scoring.filters import first_failure, run_hard_filters
from services.scoring.writer import write_cover_letter
from services.sources import registry
from services.sources.base import SourceQuery
from services.sources.runner import run_sources

logger = logging.getLogger("pipeline_orchestrator")
logger.setLevel(logging.INFO)

_TELEGRAM_TRANSIENT = (notification_service.TelegramNetworkError, notification_service.TelegramRateLimitError)

STATUS_SETTINGS_KEY = "pipeline_status"
MAX_DETAILS = 300
MAX_MERGE_RECORDS = 60

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
    range_match = re.search(r'(\d+(?:\.\d+)?)\s*(?:-|to|–)\s*(\d+(?:\.\d+)?)\s*(?:years?|yrs?|yr)?\b', cleaned)
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


def _new_summary() -> Dict[str, Any]:
    return {
        "status": "started",
        "message": "",
        "active_role": "",
        "total_fetched": 0,
        "unique_jobs": 0,
        "merged_duplicates": 0,
        "merges": [],              # which listings were merged and why (first MAX_MERGE_RECORDS)
        "duplicates_skipped": 0,
        "experience_filtered": 0,
        "filtered": {},            # other hard filters: {"location": n, "job_type": n, ...}
        "ai_evaluated": 0,         # jobs whose facts were extracted by AI
        "ai_errors": 0,
        "cover_letters": 0,
        "profile_source": None,
        "saved": 0,
        "notified": 0,
        "failed": 0,
        "sources": {},
        "details": [],
    }


def llm_jobs_per_run() -> int:
    try:
        return max(0, int(os.getenv("LLM_MAX_JOBS_PER_RUN", "15")))
    except ValueError:
        return 15


def build_query(settings: schemas.GeneralSettings) -> SourceQuery:
    return SourceQuery(
        role=settings.active_role or "AI/ML Engineer",
        locations=geo.split_preferences(settings.preferred_locations),
        max_age_days=getattr(settings, "max_job_age_days", 30) or 30,
        country_code=jsearch_service.infer_country_code(settings.preferred_locations) or "in",
    )


# ---------------------------------------------------------------------------
# Pipeline Orchestrator Core
# ---------------------------------------------------------------------------
def _run(db, summary: Dict[str, Any], http_client, telegram_client, only_sources) -> None:
    settings = crud.get_general_settings(db)
    active_role = settings.active_role or "AI/ML Engineer"
    min_match_score = settings.min_match_score if settings.min_match_score is not None else 7.0
    summary["active_role"] = active_role

    active_resume = crud.get_active_resume_for_role(db, active_role)
    if not active_resume or not active_resume.extracted_text or not active_resume.extracted_text.strip():
        summary["status"] = "error"
        summary["message"] = f"No active resume with extracted text found for role '{active_role}'. Please upload a resume first."
        logger.warning(summary["message"])
        return
    resume_text = active_resume.extracted_text.strip()

    # --- Discovery: every enabled source, isolated from the others
    fetched = run_sources(db, build_query(settings), http_client=http_client, only=only_sources)
    summary["sources"] = fetched.report
    if not fetched.ran:
        summary["status"] = "error"
        summary["message"] = "No job source is enabled and configured. Check Settings > Job sources."
        return
    if fetched.all_failed:
        errors = "; ".join(f"{n}: {fetched.report[n]['error']}" for n in fetched.ran)
        summary["status"] = "error"
        summary["message"] = f"Job discovery failed: {errors}"
        logger.error(summary["message"])
        return

    merges: list = []
    jobs, merged = dedupe.dedupe_jobs(fetched.jobs, merges)
    summary["merges"] = merges[:MAX_MERGE_RECORDS]
    summary["total_fetched"] = len(fetched.jobs)
    summary["unique_jobs"] = len(jobs)
    summary["merged_duplicates"] = merged
    logger.info(f"Pipeline fetched {len(fetched.jobs)} jobs ({len(jobs)} unique) for role '{active_role}'.")

    profile = profile_mod.get_profile(db, active_resume, active_role, settings.target_roles)
    summary["profile_source"] = profile.source
    weights = weights_mod.get_weights(db)
    filtered = Counter()

    # --- Pass 1 (no AI): database duplicates, hard filters, keyword pre-score
    candidates = []
    for job in jobs:
        try:
            duplicate = crud.find_duplicate_job(db, job)
            if duplicate:
                crud.touch_existing_job(db, duplicate, job.source_names or [job.source])
                summary["duplicates_skipped"] += 1
                _detail(summary, job, "duplicate_skipped", reason=f"Already exists in database (ID: {duplicate.id})")
                continue
            facts = facts_mod.heuristic_facts(job)
            filters = run_hard_filters(job, settings, _min_years(job, facts))
            if _filtered_out(summary, filtered, job, filters):
                continue
            candidates.append((job, facts, filters, score_job(job, facts, profile, settings, weights, filters)))
        except Exception as item_exc:
            _failed(summary, db, job, item_exc)

    # --- Pass 2: AI facts + cover letters for the most promising jobs only (cost control)
    candidates.sort(key=lambda c: c[3].score, reverse=True)
    ai_budget = llm_jobs_per_run() if llm.available_providers() else 0
    for rank, (job, facts, filters, result) in enumerate(candidates):
        try:
            use_ai = rank < ai_budget
            if use_ai:
                try:
                    facts = facts_mod.llm_facts(job, fallback=facts)
                    summary["ai_evaluated"] += 1
                    filters = run_hard_filters(job, settings, _min_years(job, facts))
                    if _filtered_out(summary, filtered, job, filters):
                        continue
                    result = score_job(job, facts, profile, settings, weights, filters)
                except llm.LLMError as exc:
                    summary["ai_errors"] += 1
                    use_ai = False
                    logger.warning(f"AI facts unavailable for '{job.title}', keeping the keyword score: {exc}")

            job.score = result.score
            job.score_breakdown = result.breakdown
            job.match_reason = result.match_reason
            if job.score < min_match_score:
                _detail(summary, job, "score_below_threshold", score=job.score,
                        reason=f"Score {job.score:.1f} below minimum threshold {min_match_score:.1f}")
                continue

            if use_ai:
                try:
                    job.cover_letter, _provider = write_cover_letter(job, resume_text, profile)
                    summary["cover_letters"] += 1
                except llm.LLMError as exc:
                    logger.warning(f"Cover letter not generated for '{job.title}': {exc}")

            saved_job = crud.create_job(db=db, job=job)
            summary["saved"] += 1
            notified = _notify(saved_job, telegram_client)
            summary["notified"] += int(notified)
            _detail(summary, saved_job, "saved", job_id=saved_job.id, score=saved_job.score, notified=notified)
        except Exception as item_exc:
            _failed(summary, db, job, item_exc)

    summary["filtered"] = dict(filtered)

    summary["status"] = "success"
    summary["message"] = (
        f"Job automation complete: {summary['saved']} new qualifying jobs saved, "
        f"{summary['notified']} alerts sent, {summary['duplicates_skipped']} duplicates skipped, "
        f"{summary['merged_duplicates']} cross-source duplicates merged, "
        f"{summary['experience_filtered']} filtered by experience, "
        f"{sum(summary['filtered'].values())} by other filters, {summary['ai_evaluated']} scored with AI facts."
    )


def _min_years(job, facts) -> Optional[float]:
    """Explicit experience field first (V1 rule); otherwise the (verified) facts."""
    explicit = extract_minimum_experience_years(job.experience)
    return explicit if explicit is not None else facts.min_years


def _detail(summary: Dict[str, Any], job, status: str, **extra) -> None:
    summary["details"].append({"title": job.title or "Unknown Role", "company": job.company or "Unknown Company",
                               "status": status, **extra})


def _filtered_out(summary: Dict[str, Any], counter: Counter, job, filters) -> bool:
    failure = first_failure(filters)
    if failure is None:
        return False
    if failure.name == "experience":
        summary["experience_filtered"] += 1
        _detail(summary, job, "experience_filtered", reason=failure.detail)
    else:
        counter[failure.name] += 1
        _detail(summary, job, f"filtered_{failure.name}", reason=failure.detail)
    return True


def _failed(summary: Dict[str, Any], db, job, exc: Exception) -> None:
    summary["failed"] += 1
    logger.error(f"Error processing job '{job.title}' at '{job.company}': {exc}")
    _detail(summary, job, "failed", error=str(exc))
    try:
        db.rollback()
    except Exception:
        pass


def _notify(saved_job, telegram_client) -> bool:
    """Telegram alert, strictly after the job is committed. Failures never undo the save."""
    try:
        retry_call(
            lambda: notification_service.send_job_alert(
                title=saved_job.title, company=saved_job.company, score=saved_job.score,
                match_reason=saved_job.match_reason, url=saved_job.url, experience=saved_job.experience,
                location=saved_job.location, client=telegram_client, job_id=saved_job.id,
            ),
            retry_on=_TELEGRAM_TRANSIENT,
            label="Telegram alert",
        )
        return True
    except Exception as notify_exc:
        logger.warning(f"Telegram notification failed for job ID {saved_job.id}: {notify_exc}")
        return False


def _execute_pipeline(
    db_session: Optional[Any] = None,
    session_factory=SessionLocal,
    telegram_client: Optional[Any] = None,
    http_client: Optional[Any] = None,
    only_sources: Optional[list] = None,
    started_at: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Executes one pipeline run with single-run locking and isolated DB session cleanup.
    `http_client` (optional, e.g. a mocked httpx.Client) is shared by all sources;
    `only_sources` restricts the run to the named sources.
    """
    if not _pipeline_lock.acquire(blocking=False):
        logger.warning("Pipeline run rejected: another automation run is already in progress.")
        busy = _new_summary()
        busy.update(status="already_running", message="Automation pipeline is already currently running.")
        return busy

    summary = _new_summary()
    db = db_session
    managed_session = False
    try:
        if db is None:
            db = session_factory()
            managed_session = True
        try:
            _run(db, summary, http_client, telegram_client, only_sources)
        except Exception as exc:
            logger.exception("Pipeline run failed")
            summary["status"] = "error"
            summary["message"] = f"Pipeline crashed: {exc}"
        summary["details"] = summary["details"][:MAX_DETAILS]
        _persist_status(db, started_at or _now_iso(), summary)
        return summary
    finally:
        try:
            if managed_session and db is not None:
                try:
                    db.close()
                except Exception:
                    logger.exception("Failed to close pipeline database session.")
        finally:
            _pipeline_lock.release()


# ---------------------------------------------------------------------------
# Run status tracking (exposed via GET /api/automation/status)
# ---------------------------------------------------------------------------
_status_lock = threading.Lock()
_run_state: Dict[str, Any] = {"started_at": None, "finished_at": None, "last_run": None}


def _now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _persist_status(db, started_at: str, summary: Dict[str, Any]) -> None:
    """Save the finished run to app_settings so the dashboard still shows it after a restart."""
    try:
        crud.set_json_setting(db, STATUS_SETTINGS_KEY,
                              {"started_at": started_at, "finished_at": _now_iso(), "last_run": summary})
    except Exception:
        logger.exception("Could not persist the pipeline run summary")
        try:
            db.rollback()
        except Exception:
            pass


def get_pipeline_status(db: Optional[Any] = None) -> Dict[str, Any]:
    """Whether the pipeline is running, the last finished run (memory, else the database) and source health."""
    with _status_lock:
        state = dict(_run_state)
    if state["last_run"] is None and db is not None:
        stored = crud.get_json_setting(db, STATUS_SETTINGS_KEY, None)
        if isinstance(stored, dict):
            state.update({k: stored.get(k) for k in ("started_at", "finished_at", "last_run")})
    result = {
        "running": _pipeline_lock.locked(),
        "started_at": state["started_at"],
        "finished_at": state["finished_at"],
        "last_run": state["last_run"],
    }
    if db is not None:
        result["sources"] = registry.describe_sources(db)
    return result


def run_automation_pipeline(
    db_session: Optional[Any] = None,
    session_factory=SessionLocal,
    telegram_client: Optional[Any] = None,
    http_client: Optional[Any] = None,
    only_sources: Optional[list] = None,
) -> Dict[str, Any]:
    """
    Public entry point: runs the pipeline and records start/finish time and summary
    so the API/UI can report progress. See _execute_pipeline for the actual logic.
    """
    started = _now_iso()
    try:
        summary = _execute_pipeline(
            db_session=db_session,
            session_factory=session_factory,
            telegram_client=telegram_client,
            http_client=http_client,
            only_sources=only_sources,
            started_at=started,
        )
    except Exception as exc:
        logger.exception("Pipeline crashed unexpectedly")
        summary = {"status": "error", "message": f"Pipeline crashed: {exc}", "details": []}

    # A rejected overlapping run must not overwrite the in-progress run's record.
    if summary.get("status") != "already_running":
        with _status_lock:
            _run_state["started_at"] = started
            _run_state["finished_at"] = _now_iso()
            _run_state["last_run"] = summary
    return summary
