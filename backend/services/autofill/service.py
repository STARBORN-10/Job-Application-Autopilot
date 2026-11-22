"""
Start a career-page form fill for a job in the background and log it in `applications` (method "autofill").

Statuses: in_progress -> prefilled (all known fields filled, stopped before submit) | needs_input (required
questions left for you, or a CAPTCHA) | submitted (only when policy allows) | failed (with the reason).
"""
import datetime
import json
import logging
import os
from pathlib import Path
from typing import Optional

import crud
import models
import tenancy
from database import SessionLocal
from services.apply import detect
from services.autofill import policy, runner
from services.autofill.profile import get_profile
from services.redact import redact
from services.tasks import tasks

logger = logging.getLogger("autofill.service")
SUPPORTED = ("greenhouse", "lever", "ashby")
BACKEND_DIR = Path(__file__).resolve().parent.parent.parent


def screenshot_dir() -> Path:
    return Path(os.getenv("GENERATED_DIR") or (BACKEND_DIR / "generated")) / "screenshots"


def supported_ats(url: Optional[str]) -> Optional[str]:
    ats = detect.ats_provider(url)
    return ats if ats in SUPPORTED else None


class AutofillUnavailable(Exception):
    pass


def resume_for(db, job) -> tuple[Optional[Path], str]:
    """The tailored resume PDF when one exists for this job, else the active original resume."""
    from services import resume_tailor
    settings = crud.get_general_settings(db)
    resume = crud.get_active_resume_for_role(db, settings.active_role)
    row = resume_tailor.latest(db, job.id, resume) if resume is not None else None
    if row is not None and row.status == "tailored":
        try:
            path = resume_tailor.file_for(row, "pdf")
            db.commit()
            if path:
                return path, "tailored"
        except Exception:
            logger.exception("Tailored resume file unavailable; using the original")
    if resume is not None and resume.file_path and Path(resume.file_path).is_file():
        return Path(resume.file_path), "original"
    return None, "none"


def check_ready(job, url_override: Optional[str] = None) -> str:
    """Raise AutofillUnavailable with a plain reason when filling cannot start; return the ATS name."""
    ats = supported_ats(url_override or job.url)
    if not ats and not url_override:
        raise AutofillUnavailable("Automatic form filling supports Greenhouse, Lever and Ashby career pages only. "
                                  "Open the posting and apply by hand.")
    if not runner.playwright_available():
        raise AutofillUnavailable(runner.INSTALL_HINT)
    return ats


def start_prefill(job_id: int, session_factory=SessionLocal, url_override: Optional[str] = None,
                  inline: bool = False) -> dict:
    """Start (or return the running) prefill task for a job. `url_override` + `inline` are for tests."""
    running = tasks.active_for("autofill", job_id)
    if running:
        return running
    # Every session this task opens (now and in its background thread) belongs to the user who started it.
    session_factory = tenancy.scoped_factory(session_factory, tenancy.current_user_id())
    db = session_factory()
    try:
        job = crud.get_job(db, job_id)
        if job is None:
            raise AutofillUnavailable("Job not found.")
        ats = check_ready(job, url_override)
        app_row = models.Application(job_id=job.id, method="autofill", status="in_progress",
                                     dry_run=policy.dry_run(), payload_summary=json.dumps({"ats": ats, "url": job.url}))
        db.add(app_row)
        db.commit()
        app_id = app_row.id
    finally:
        db.close()

    def work(task):
        db2 = session_factory()
        try:
            job2 = crud.get_job(db2, job_id)
            task.step("Preparing your resume and cover letter...")
            from services.scoring.writer import ensure_cover_letter
            letter = ensure_cover_letter(db2, job2)
            resume_path, resume_kind = resume_for(db2, job2)
            profile = get_profile(db2)
            report = runner.run_prefill(url_override or job2.url, ats, profile, resume_path, letter,
                                        job2.approval_status, screenshot_dir(), on_step=task.step)
            report["resume_kind"] = resume_kind
            report["profile_missing"] = profile.missing_basics()
            row = db2.get(models.Application, app_id)
            row.status = report["status"]
            row.payload_summary = json.dumps(report, default=str)
            row.error = redact(report["error"]) if report.get("error") else None
            row.updated_at = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
            if report.get("submitted"):
                job2.status = "Applied"
            db2.commit()
            return {"application_id": app_id, **summarize(report)}
        except Exception as exc:
            logger.exception("Autofill task failed")
            try:
                row = db2.get(models.Application, app_id)
                row.status = "failed"
                row.error = redact(f"{type(exc).__name__}: {exc}")[:500]
                db2.commit()
            except Exception:
                db2.rollback()
            raise
        finally:
            db2.close()

    if inline:
        return tasks.run_inline("autofill", job_id, work)
    return tasks.start("autofill", job_id, work, first_step="Queued: opening a browser...")


def summarize(report: dict) -> dict:
    """Plain-language outcome for the UI."""
    status = report.get("status")
    filled = len(report.get("filled") or [])
    unfilled = report.get("unfilled_required") or []
    if status == "submitted":
        text = f"Submitted the form ({filled} fields filled)."
    elif status in ("prefilled", "needs_input"):
        text = f"Form pre-filled: {filled} field(s) filled."
        if unfilled:
            text += f" {len(unfilled)} required field(s) need your answer."
        if report.get("captcha"):
            text += " A CAPTCHA is on the page: you must solve it yourself."
        text += " " + (report.get("submit_reason") or "Not submitted.")
    else:
        text = report.get("error") or "Form filling failed."
    return {"status": status, "message": text, "filled": filled, "unfilled_required": len(unfilled),
            "captcha": bool(report.get("captcha")), "submitted": bool(report.get("submitted"))}
