"""
Safe applying, only ever after a job is approved.

Method:
- "email" when the posting contains a recruiter address: the cover letter is the body and the
  active resume PDF is attached. APPLY_DRY_RUN (default true) logs what would be sent and sends
  nothing. A daily cap (APPLY_DAILY_CAP, default 10) limits e-mails (dry runs count too).
- "assisted" otherwise: status ready_to_submit; the link and cover letter are sent to Telegram (if
  configured) and shown in the dashboard so the user submits by hand. Greenhouse / Lever / Ashby
  career pages are also "assisted"; in addition their form can be pre-filled automatically
  (services/autofill, logged as method "autofill"; it stops before submitting unless allowed).

The resume used is the tailored PDF for this job when one exists (services/resume_tailor.py), else
the active original resume. describe() turns an application row into a plain-language outcome and
preview() explains what Approve will do for a job before the user clicks it.

Every attempt is logged in `applications`; a job already applied for (dry run, sent or ready) is not
applied for again.
"""
import datetime
import json
import logging
import os
from pathlib import Path
from typing import Optional

import crud
import models
from services import notification_service as tg
from services.apply import detect, emailer
from services.redact import redact
from services.scoring.writer import ensure_cover_letter

logger = logging.getLogger("apply")

DONE_STATUSES = ("dry_run", "sent", "ready_to_submit")


class NotApprovedError(Exception):
    pass


def dry_run_enabled() -> bool:
    return (os.getenv("APPLY_DRY_RUN") or "true").strip().lower() not in ("false", "0", "no", "off")


def daily_cap() -> int:
    try:
        return max(0, int(os.getenv("APPLY_DAILY_CAP", "10")))
    except ValueError:
        return 10


def _today_start() -> datetime.datetime:
    now = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


def emails_today(db) -> int:
    return (
        db.query(models.Application)
        .filter(models.Application.method == "email",
                models.Application.status.in_(("sent", "dry_run")),
                models.Application.created_at >= _today_start())
        .count()
    )


def existing_application(db, job_id: int) -> Optional[models.Application]:
    return (
        db.query(models.Application)
        .filter(models.Application.job_id == job_id, models.Application.status.in_(DONE_STATUSES))
        .order_by(models.Application.id.desc())
        .first()
    )


AUTOFILL_ATS = ("greenhouse", "lever", "ashby")


def choose_method(job) -> tuple[str, dict]:
    email = detect.find_recruiter_email(job.description)
    if email:
        return "email", {"to": email}
    ats = detect.ats_provider(job.url)
    if ats in AUTOFILL_ATS:
        note = (f"{ats.title()} career page: the form can be pre-filled for you ('Pre-fill application form'); "
                "it stops before submitting so you can review it and click Submit yourself.")
    elif ats:
        note = f"{ats.title()} career page: open the link and submit it yourself with the prepared cover letter."
    else:
        note = "No recruiter e-mail in the posting: open the link and submit with the prepared cover letter."
    return "assisted", {"url": job.url, "ats": ats, "note": note}


def resume_file(db, job) -> tuple[Optional[Path], str]:
    """(path, "tailored" | "original" | "none"): the tailored PDF for this job when it exists."""
    settings = crud.get_general_settings(db)
    resume = crud.get_active_resume_for_role(db, settings.active_role)
    try:
        from services import resume_tailor
        row = resume_tailor.latest(db, job.id, resume) if resume is not None else None
        if row is not None and row.status == "tailored":
            path = resume_tailor.file_for(row, "pdf")
            db.commit()
            if path:
                return path, "tailored"
    except Exception:
        logger.exception("Tailored resume unavailable; using the original")
        db.rollback()
    if resume is not None and resume.file_path and Path(resume.file_path).is_file():
        return Path(resume.file_path), "original"
    return None, "none"


def _log(db, job, method: str, status: str, payload: dict, error: Optional[str] = None) -> models.Application:
    app = models.Application(job_id=job.id, method=method, status=status, dry_run=dry_run_enabled(),
                             payload_summary=json.dumps(payload, default=str), error=redact(error) if error else None)
    db.add(app)
    db.commit()
    db.refresh(app)
    logger.info(f"Application for job {job.id}: method={method} status={status}")
    return app


def apply_for_job(db, job, telegram_client=None) -> models.Application:
    """Apply for an approved job with the safest available method. Never raises for expected failures."""
    if (job.approval_status or "pending") != "approved":
        raise NotApprovedError("Only approved jobs can be applied for.")
    previous = existing_application(db, job.id)
    if previous is not None:
        return previous

    method, info = choose_method(job)
    letter = ensure_cover_letter(db, job)
    if method == "email":
        return _apply_by_email(db, job, info["to"], letter)
    return _apply_assisted(db, job, info, letter, telegram_client)


def _apply_by_email(db, job, to: str, letter: Optional[str]) -> models.Application:
    path, kind = resume_file(db, job)
    subject = f"Application for {job.title}" + (f" at {job.company}" if job.company else "")
    payload = {"to": to, "subject": subject, "from": emailer.smtp_settings()["sender"] or None,
               "body_chars": len(letter or ""), "attachment": path.name if path else None, "resume_kind": kind}
    if not letter:
        return _log(db, job, "email", "failed", payload, "No cover letter available (AI providers unavailable).")
    if path is None:
        return _log(db, job, "email", "failed", payload, "Active resume PDF not found on disk.")
    if emails_today(db) >= daily_cap():
        return _log(db, job, "email", "skipped", payload, f"Daily cap of {daily_cap()} e-mail applications reached.")
    if dry_run_enabled():
        payload["body_preview"] = letter[:300]
        return _log(db, job, "email", "dry_run", payload)
    try:
        emailer.send_email(to, subject, letter, path)
    except emailer.EmailConfigError as exc:
        return _log(db, job, "email", "failed", payload, str(exc))
    except Exception as exc:  # smtplib / network errors
        return _log(db, job, "email", "failed", payload, f"{type(exc).__name__}: {exc}")
    job.status = "Applied"
    db.commit()
    return _log(db, job, "email", "sent", payload)


def _apply_assisted(db, job, info: dict, letter: Optional[str], telegram_client) -> models.Application:
    path, kind = resume_file(db, job)
    payload = {**info, "cover_letter_chars": len(letter or ""), "telegram_sent": False,
               "resume_file": path.name if path else None, "resume_kind": kind}
    if (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip() and (os.getenv("TELEGRAM_CHAT_ID") or "").strip():
        text = (f"Ready to submit: {job.title} at {job.company}\n{job.url or '(no link)'}\n\n{info['note']}"
                + (f"\n\nCover letter:\n{letter}" if letter else ""))
        try:
            tg.send_telegram_notification(text, client=telegram_client, parse_mode=None)
            payload["telegram_sent"] = True
        except tg.TelegramNotificationError as exc:
            payload["telegram_error"] = redact(str(exc))[:200]
    return _log(db, job, "assisted", "ready_to_submit", payload)


# ---------------------------------------------------------------------------
# Plain-language outcome and preview (what the UI shows around Approve)
# ---------------------------------------------------------------------------
def describe(app_row: models.Application, payload: Optional[dict] = None) -> str:
    """One or two sentences saying exactly what happened for this application attempt."""
    if payload is None:
        try:
            payload = json.loads(app_row.payload_summary) if app_row.payload_summary else {}
        except ValueError:
            payload = {}
    status, method = app_row.status, app_row.method
    resume_note = {"tailored": " Your tailored resume was used.", "original": " Your original resume was used."}.get(
        payload.get("resume_kind"), "")
    if method == "email":
        to = payload.get("to") or "the recruiter"
        if status == "dry_run":
            return (f"Dry run: an e-mail to {to} with your cover letter and resume was prepared but NOT sent "
                    f"(dry run is on).{resume_note}")
        if status == "sent":
            return f"E-mail sent to {to} with your cover letter and resume attached.{resume_note}"
        if status == "skipped":
            return f"Not sent: {app_row.error or 'skipped'}"
        return f"Could not e-mail {to}: {app_row.error or 'unknown error'}"
    if method == "assisted":
        if status == "ready_to_submit":
            base = ("Assisted apply: open the job link and submit it yourself; your cover letter and resume are "
                    "ready below.")
            if payload.get("ats") in AUTOFILL_ATS:
                base += " You can also let the app pre-fill the form."
            if payload.get("telegram_sent"):
                base += " The link and letter were also sent to Telegram."
            return base + resume_note
        return f"Assisted apply could not be prepared: {app_row.error or status}"
    if method == "autofill":
        from services.autofill.service import summarize
        if status == "in_progress":
            return "Filling the application form..."
        return summarize({**payload, "status": status, "error": payload.get("error") or app_row.error})["message"]
    return f"{method}: {status}"


def preview(db, job) -> dict:
    """What Approve will do for this job with the current configuration (nothing is changed)."""
    from services import llm, resume_tailor
    from services.autofill import policy as autofill_policy, runner as autofill_runner
    method, info = choose_method(job)
    dry = dry_run_enabled()
    previous = existing_application(db, job.id)
    ats = info.get("ats") if method == "assisted" else detect.ats_provider(job.url)
    autofill_possible = ats in AUTOFILL_ATS
    limit = resume_tailor.threshold()
    settings = crud.get_general_settings(db)
    resume = crud.get_active_resume_for_role(db, settings.active_role)
    steps = []
    if previous is not None:
        steps.append(f"An application was already logged ({previous.method}, {previous.status.replace('_', ' ')}); "
                     "it will not be repeated.")
    if resume is None:
        steps.append("No active resume: upload one on the Resumes page first.")
    tailor = "off"
    if resume_tailor.auto_tailor_on_approve():
        if job.score is not None and job.score >= limit:
            tailor = "not_needed"
            steps.append(f"Resume: the score {job.score:.1f} is already at or above {limit:g}, so your original resume "
                         "is used unchanged.")
        elif llm.available_providers():
            tailor = "will_tailor"
            steps.append("Resume: a tailored version for this job is generated first (only facts from your resume, "
                         "re-ordered and re-worded); you see the score before and after.")
        else:
            tailor = "unavailable"
            steps.append("Resume: tailoring is on but no AI provider is configured, so the original is used.")
    else:
        steps.append("Resume: automatic tailoring is off (AUTO_TAILOR_ON_APPROVE=false); the original resume is used.")
    steps.append("Cover letter: the saved one is used." if (job.cover_letter or "").strip()
                 else "Cover letter: one is written now by the AI (if a provider is available).")
    if method == "email":
        if dry:
            steps.append(f"E-mail: an application to {info['to']} is prepared and logged but NOT sent (dry run is on).")
        elif not emailer.smtp_configured():
            steps.append(f"E-mail to {info['to']}: SMTP is not configured, so it will fail and be logged.")
        else:
            steps.append(f"E-mail: your cover letter and resume are SENT to {info['to']} (dry run is off). "
                         f"Daily cap {daily_cap()}, used today {emails_today(db)}.")
    else:
        telegram = bool((os.getenv("TELEGRAM_BOT_TOKEN") or "").strip() and (os.getenv("TELEGRAM_CHAT_ID") or "").strip())
        steps.append("Assisted apply: the link and cover letter are prepared for you to submit yourself"
                     + (" (and sent to Telegram)." if telegram else "."))
        if autofill_possible:
            if not autofill_runner.playwright_available():
                steps.append(f"{ats.title()} form filling: not available. {autofill_runner.INSTALL_HINT}")
            elif autofill_policy.on_approve():
                allowed = autofill_policy.submit_enabled() and not autofill_policy.dry_run()
                steps.append(f"{ats.title()} form: a browser fills your details, uploads the resume and pastes the "
                             "cover letter, then " + ("submits ONLY if every required field is filled and there is "
                                                      "no CAPTCHA." if allowed else "STOPS before submitting."))
            else:
                steps.append(f"{ats.title()} form: use 'Pre-fill application form' on the job page to fill it.")
    return {"method": method, "recruiter_email": info.get("to"), "ats": ats, "autofill_possible": autofill_possible,
            "dry_run": dry, "smtp_configured": emailer.smtp_configured(), "tailor": tailor, "tailor_threshold": limit,
            "already_applied": previous is not None, "steps": steps}
