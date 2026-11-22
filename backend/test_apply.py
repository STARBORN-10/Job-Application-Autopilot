"""
Offline tests for safe applying (services/apply): recruiter e-mail detection, method choice, dry-run
by default, daily cap, duplicate guard, approval guard, SMTP sending (smtplib mocked, nothing is ever
sent), assisted applying with a (mocked) Telegram message, and the applications API.
"""
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent))

from testing_utils import Checker, use_temp_database

use_temp_database()

from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

import crud, models, schemas
import db_migrations
from database import engine, get_db
from main import app
from services.apply import detect, service as apply_service

db_migrations.upgrade_database(engine)
Session = sessionmaker(bind=engine)

LETTER = "Dear Hiring Team,\n\nI build backend services in Python and FastAPI. " * 3


def make_job(db, n, description="", url=None, approved=True, letter=LETTER):
    job = crud.create_job(db, schemas.JobCreate(title=f"Backend Developer {n}", company=f"Company {n}",
                                                url=url or f"https://jobs.example.in/{n}", description=description,
                                                cover_letter=letter, score=8.0))
    if approved:
        job.approval_status = "approved"
        db.commit()
    return job


def run():
    check = Checker("RUNNING OFFLINE SAFE-APPLY TESTS")

    check.section("1. Recruiter e-mail detection")
    f = detect.find_recruiter_email
    check(f("Interested candidates can send their resume to hr@acme.in today.") == "hr@acme.in", "Plain address found")
    check(f("Contact noreply@acme.in or careers@acme.in to apply") == "careers@acme.in", "no-reply skipped")
    check(f("logo icon@2x.png and banner@3x.jpg") is None, "Image file names are not e-mails")
    check(f("e.g. name@example.com") is None and f("Apply via jobs@linkedin.com") is None,
          "Placeholder and job-board domains ignored")
    check(f("Questions: privacy@acme.in. Send CV: talent.team@acme.in") == "talent.team@acme.in",
          "Address near hiring words preferred; privacy@ ignored")
    check(f(None) is None and f("No address here") is None, "No address -> None")
    check(detect.ats_provider("https://boards.greenhouse.io/acme/jobs/1") == "greenhouse"
          and detect.ats_provider("https://jobs.lever.co/cred/abc") == "lever"
          and detect.ats_provider("https://jobs.ashbyhq.com/notion/x") == "ashby"
          and detect.ats_provider("https://acme.in/careers") is None, "ATS career pages recognised")

    check.section("2. Approval guard and method choice")
    db = Session()
    tmp = Path(tempfile.mkdtemp())
    pdf = tmp / "resume.pdf"
    pdf.write_bytes(b"%PDF-1.4 test resume")
    crud.create_resume(db, filename="resume.pdf", target_role="AI/ML Engineer", extracted_text="Python, FastAPI",
                       file_path=str(pdf), file_size=pdf.stat().st_size)
    pending = make_job(db, 1, "Send CV to hr@one.in", approved=False)
    try:
        apply_service.apply_for_job(db, pending)
        guarded = False
    except apply_service.NotApprovedError:
        guarded = True
    check(guarded and db.query(models.Application).count() == 0, "Unapproved jobs are never applied for")
    check(apply_service.choose_method(make_job(db, 2, "mail resume to jobs@two.in", approved=False))[0] == "email",
          "E-mail in the description -> email method")
    method, info = apply_service.choose_method(make_job(db, 3, "Apply on our page",
                                                        url="https://boards.greenhouse.io/three/jobs/9", approved=False))
    check(method == "assisted" and info["ats"] == "greenhouse" and "pre-filled" in info["note"],
          "Greenhouse URL -> assisted, with the form pre-fill offered")

    check.section("3. Dry run is the default")
    smtp = MagicMock()
    with patch.dict(os.environ, {"APPLY_DRY_RUN": ""}), patch("smtplib.SMTP_SSL", smtp), patch("smtplib.SMTP", smtp):
        check(apply_service.dry_run_enabled(), "APPLY_DRY_RUN unset/empty -> dry run")
        job = make_job(db, 4, "Send resume to hr@four.in")
        a = apply_service.apply_for_job(db, job)
    payload = json.loads(a.payload_summary)
    check(a.method == "email" and a.status == "dry_run" and a.dry_run is True, "Logged as dry_run")
    check(payload["to"] == "hr@four.in" and payload["attachment"] == "resume.pdf" and payload["body_chars"] == len(LETTER),
          "Payload summary: recipient, attachment, body size")
    check(smtp.call_count == 0, "Nothing sent in dry run (smtplib untouched)")
    again = apply_service.apply_for_job(db, job)
    check(again.id == a.id and db.query(models.Application).filter_by(job_id=job.id).count() == 1,
          "Duplicate guard: the same job is not applied for twice")

    check.section("4. Daily cap")
    with patch.dict(os.environ, {"APPLY_DAILY_CAP": "2"}):
        b = apply_service.apply_for_job(db, make_job(db, 5, "Send resume to hr@five.in"))
        c = apply_service.apply_for_job(db, make_job(db, 6, "Send resume to hr@six.in"))
    check(b.status == "dry_run" and c.status == "skipped" and "Daily cap" in c.error, "Third e-mail of the day is skipped")

    check.section("5. Real sending path (smtplib mocked)")
    env = {"APPLY_DRY_RUN": "false", "SMTP_HOST": "smtp.gmail.com", "SMTP_PORT": "465", "SMTP_USER": "me@gmail.com",
           "SMTP_PASSWORD": "app-pass-secret-123", "SMTP_FROM": "me@gmail.com", "APPLY_DAILY_CAP": "50"}
    server = MagicMock()
    smtp_ssl = MagicMock()
    smtp_ssl.return_value.__enter__.return_value = server
    with patch.dict(os.environ, env), patch("smtplib.SMTP_SSL", smtp_ssl):
        job = make_job(db, 7, "Send resume to hr@seven.in")
        a = apply_service.apply_for_job(db, job)
    msg = server.send_message.call_args[0][0]
    attachments = [p.get_filename() for p in msg.iter_attachments()]
    check(a.status == "sent" and a.dry_run is False, "Status 'sent' when dry run is off and SMTP works")
    check(server.login.call_args[0] == ("me@gmail.com", "app-pass-secret-123") and msg["To"] == "hr@seven.in",
          "Logged in and addressed to the recruiter")
    check(attachments == ["resume.pdf"] and "Python and FastAPI" in msg.get_body().get_content(),
          "Resume PDF attached, cover letter as body")
    db.refresh(job)
    check(job.status == "Applied", "Job marked Applied after a real send")

    failing = MagicMock()
    failing.return_value.__enter__.return_value.login.side_effect = Exception("535 auth failed for app-pass-secret-123")
    with patch.dict(os.environ, env), patch("smtplib.SMTP_SSL", failing):
        f8 = apply_service.apply_for_job(db, make_job(db, 8, "Send resume to hr@eight.in"))
    check(f8.status == "failed" and "app-pass-secret-123" not in f8.error and "***" in f8.error,
          "SMTP failure logged as failed, password redacted")
    with patch.dict(os.environ, {**env, "SMTP_HOST": ""}):
        f9 = apply_service.apply_for_job(db, make_job(db, 9, "Send resume to hr@nine.in"))
    check(f9.status == "failed" and "SMTP is not configured" in f9.error, "Missing SMTP settings -> failed, clear error")
    with patch.dict(os.environ, env), patch("smtplib.SMTP_SSL", smtp_ssl), \
         patch("services.apply.service.ensure_cover_letter", return_value=None):
        f10 = apply_service.apply_for_job(db, make_job(db, 10, "Send resume to hr@ten.in", letter=None))
    check(f10.status == "failed" and "cover letter" in f10.error.lower(), "No cover letter -> not sent")
    retry = apply_service.apply_for_job(db, crud.get_job(db, f9.job_id))
    check(retry.id != f9.id and retry.status == "dry_run", "A failed attempt can be retried (now dry run)")

    check.section("6. Assisted applying")
    sent = []
    with patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "1:t", "TELEGRAM_CHAT_ID": "555"}), \
         patch("services.notification_service.send_telegram_notification",
               side_effect=lambda text, **k: sent.append(text) or {"ok": True}):
        a = apply_service.apply_for_job(db, make_job(db, 11, "Apply online", url="https://jobs.lever.co/x/11"))
    p = json.loads(a.payload_summary)
    check(a.method == "assisted" and a.status == "ready_to_submit", "No e-mail -> assisted, ready_to_submit")
    check(p["telegram_sent"] and "https://jobs.lever.co/x/11" in sent[0] and "Cover letter:" in sent[0],
          "Link and cover letter sent to Telegram")
    a2 = apply_service.apply_for_job(db, make_job(db, 12, "Apply online"))
    check(a2.status == "ready_to_submit" and json.loads(a2.payload_summary)["telegram_sent"] is False,
          "Without Telegram configured it is still logged (shown in the dashboard)")

    check.section("7. API")

    def override():
        s = Session()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_db] = override
    api = TestClient(app)
    r = api.get("/api/applications")
    rows = r.json()
    check(r.status_code == 200 and len(rows) == db.query(models.Application).count(), "GET /api/applications lists all")
    assisted = next(x for x in rows if x["method"] == "assisted")
    check(assisted["job_title"].startswith("Backend Developer") and assisted["cover_letter"] == LETTER,
          "Assisted rows include job info and the cover letter (copy button)")
    check({"id", "method", "status", "dry_run", "payload_summary", "error", "created_at"} <= set(rows[0]),
          "Rows carry method, status, dry-run flag, payload, error, timestamps")
    cfg = api.get("/api/applications/config").json()
    check(cfg["dry_run"] is True and cfg["daily_cap"] == 10 and cfg["smtp_configured"] is False, "Config for the banner")
    unapproved = make_job(db, 13, "x", approved=False)
    check(api.post(f"/api/jobs/{unapproved.id}/apply").status_code == 409, "Apply endpoint refuses unapproved jobs")
    approve_me = make_job(db, 14, "Send resume to hr@fourteen.in", approved=False)
    r = api.post(f"/api/jobs/{approve_me.id}/approve")
    check(r.status_code == 200 and r.json()["application"]["status"] == "dry_run", "Approving applies (dry run)")
    r = api.post(f"/api/jobs/{approve_me.id}/apply")
    check(r.status_code == 200 and r.json()["id"] == api.get("/api/applications").json()[0]["id"],
          "Apply again returns the existing application (no duplicate)")

    app.dependency_overrides.clear()
    db.close()
    check.done("SAFE-APPLY")


if __name__ == "__main__":
    run()
