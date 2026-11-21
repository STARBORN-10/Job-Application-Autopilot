"""
Safe applying, only ever after a job is approved.

Method:
- "email" when the posting contains a recruiter address: the cover letter is the body and the
  active resume PDF is attached. APPLY_DRY_RUN (default true) logs what would be sent and sends
  nothing. A daily cap (APPLY_DAILY_CAP, default 10) limits e-mails (dry runs count too).
- "assisted" otherwise: status ready_to_submit; the link and cover letter are sent to Telegram (if
  configured) and shown in the dashboard so the user submits by hand. Greenhouse / Lever / Ashby
  career pages are detected and also routed here: automatic form filling is deferred.

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


def choose_method(job) -> tuple[str, dict]:
    email = detect.find_recruiter_email(job.description)
    if email:
        return "email", {"to": email}
    ats = detect.ats_provider(job.url)
    note = (f"{ats.title()} career page: automatic form filling is not available yet, submit it yourself."
            if ats else "No recruiter e-mail in the posting: open the link and submit with the cover letter.")
    return "assisted", {"url": job.url, "ats": ats, "note": note}


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
    settings = crud.get_general_settings(db)
    resume = crud.get_active_resume_for_role(db, settings.active_role)
    subject = f"Application for {job.title}" + (f" at {job.company}" if job.company else "")
    payload = {"to": to, "subject": subject, "from": emailer.smtp_settings()["sender"] or None,
               "body_chars": len(letter or ""), "attachment": Path(resume.file_path).name if resume else None}
    if not letter:
        return _log(db, job, "email", "failed", payload, "No cover letter available (AI providers unavailable).")
    if resume is None or not Path(resume.file_path).is_file():
        return _log(db, job, "email", "failed", payload, "Active resume PDF not found on disk.")
    if emails_today(db) >= daily_cap():
        return _log(db, job, "email", "skipped", payload, f"Daily cap of {daily_cap()} e-mail applications reached.")
    if dry_run_enabled():
        payload["body_preview"] = letter[:300]
        return _log(db, job, "email", "dry_run", payload)
    try:
        emailer.send_email(to, subject, letter, Path(resume.file_path))
    except emailer.EmailConfigError as exc:
        return _log(db, job, "email", "failed", payload, str(exc))
    except Exception as exc:  # smtplib / network errors
        return _log(db, job, "email", "failed", payload, f"{type(exc).__name__}: {exc}")
    job.status = "Applied"
    db.commit()
    return _log(db, job, "email", "sent", payload)


def _apply_assisted(db, job, info: dict, letter: Optional[str], telegram_client) -> models.Application:
    payload = {**info, "cover_letter_chars": len(letter or ""), "telegram_sent": False}
    if (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip() and (os.getenv("TELEGRAM_CHAT_ID") or "").strip():
        text = (f"Ready to submit: {job.title} at {job.company}\n{job.url or '(no link)'}\n\n{info['note']}"
                + (f"\n\nCover letter:\n{letter}" if letter else ""))
        try:
            tg.send_telegram_notification(text, client=telegram_client, parse_mode=None)
            payload["telegram_sent"] = True
        except tg.TelegramNotificationError as exc:
            payload["telegram_error"] = redact(str(exc))[:200]
    return _log(db, job, "assisted", "ready_to_submit", payload)
