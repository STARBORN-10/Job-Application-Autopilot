"""
Offline tests for career-page form filling (services/autofill):
- field mapping (classify_field), sensitive questions never answered, application URLs,
- the submit gate (all five conditions), the applicant profile validation and API,
- the "Playwright not installed" path (clear message, no crash),
- real Playwright (if installed) against LOCAL fixture pages imitating Greenhouse, Lever and Ashby, served
  from a localhost test server: fields filled, resume uploaded, cover letter pasted, custom / EEO / visa
  questions left for the user, CAPTCHA detected, screenshot taken, and never submitted by default.
  Submission is only exercised against the local test server, never a real company form.
"""
import datetime
import json
import os
import sys
import tempfile
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent))

from testing_utils import TESTS_DATA, Checker, use_temp_database

use_temp_database()

from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

import crud, models, schemas
import db_migrations
from database import engine
from main import app
from services.autofill import fields, policy, runner, service
from services.autofill.profile import ApplicantProfile, save_profile

db_migrations.upgrade_database(engine)
Session = sessionmaker(bind=engine)
FIXTURES = TESTS_DATA / "autofill"
SUBMISSIONS = []


class FixtureHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(FIXTURES), **kwargs)

    def do_POST(self):  # the only "submit" target in these tests
        length = int(self.headers.get("Content-Length") or 0)
        SUBMISSIONS.append({"path": self.path, "bytes": len(self.rfile.read(length))})
        body = b"<html><body><h1>Thank you for applying!</h1></body></html>"
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


PROFILE = ApplicantProfile(first_name="Asha", last_name="Verma", email="asha.verma@example.in", phone="+91 98765 43210",
                           location="Bengaluru, India", linkedin="linkedin.com/in/asha-verma",
                           github="https://github.com/asha-verma", portfolio="asha.dev")
LETTER = "Dear Hiring Team,\nI build machine learning projects in Python and FastAPI.\nRegards, Asha"


def run():
    check = Checker("RUNNING OFFLINE FORM-FILLING TESTS")
    db = Session()
    c = fields.classify_field

    check.section("1. Field mapping")
    cases = [
        (dict(label="First Name"), "first_name"), (dict(label="Last Name"), "last_name"),
        (dict(label="", name="first_name"), "first_name"), (dict(label="Full name"), "full_name"),
        (dict(label="Name", name="_systemfield_name"), "full_name"), (dict(label="Email"), "email"),
        (dict(label="Phone"), "phone"), (dict(label="Mobile number"), "phone"),
        (dict(label="Location (City)"), "location"), (dict(label="LinkedIn Profile"), "linkedin"),
        (dict(label="", name="urls[GitHub]"), "github"), (dict(label="Website"), "portfolio"),
        (dict(label="Current company", name="org"), "current_company"),
        (dict(label="Notice period"), "notice_period"),
        (dict(label="Resume/CV", input_type="file"), "resume"),
        (dict(label="Cover Letter", input_type="file"), "cover_letter"),
        (dict(label="Cover Letter", tag="textarea", input_type="textarea"), "cover_letter"),
        (dict(label="", name="email", autocomplete="email"), "email"),
        (dict(label="", autocomplete="given-name"), "first_name"),
    ]
    for kwargs, expected in cases:
        check(c(**kwargs) == expected, f"{kwargs} -> {expected}")
    sensitive = ["Gender", "Race / Ethnicity", "Veteran status", "Disability status",
                 "Will you now or in the future require sponsorship for employment visa status?",
                 "Are you legally authorized to work in India?", "What is your expected CTC?",
                 "Expected salary", "Date of birth", "I consent to the privacy policy", "How did you hear about us?"]
    for label in sensitive:
        check(c(label=label) == "sensitive", f"Never answered: '{label}'")
    check(c(label="Why do you want to work here?", tag="textarea", input_type="textarea") is None,
          "Custom question -> unknown (left for the user)")
    check(c(label="Do you agree?", input_type="checkbox") is None and c(label="Country", tag="select") is None,
          "Checkboxes and dropdowns are never guessed")
    check(c(label="Upload any file", input_type="file") is None, "Unknown file inputs are left alone")
    check(c(label="Current company name") == "current_company", "'Company name' is not taken as the person's name")

    check.section("2. Application URLs")
    check(runner.application_url("https://jobs.lever.co/cred/abc-123", "lever") == "https://jobs.lever.co/cred/abc-123/apply",
          "Lever -> /apply")
    check(runner.application_url("https://jobs.lever.co/cred/abc-123/apply", "lever").count("/apply") == 1,
          "Lever /apply not doubled")
    check(runner.application_url("https://jobs.ashbyhq.com/notion/xyz", "ashby") == "https://jobs.ashbyhq.com/notion/xyz/application",
          "Ashby -> /application")
    gh = "https://job-boards.greenhouse.io/groww/jobs/123"
    check(runner.application_url(gh, "greenhouse") == gh, "Greenhouse form is on the job page")
    check(service.supported_ats("https://boards.greenhouse.io/x/jobs/1") == "greenhouse"
          and service.supported_ats("https://acme.myworkdayjobs.com/x") is None, "Only Greenhouse/Lever/Ashby supported")

    check.section("3. Submit gate")
    d = policy.submit_decision
    with patch.dict(os.environ, {"AUTOFILL_SUBMIT": "", "APPLY_DRY_RUN": ""}):
        check(d("approved", [], False) == (False, d("approved", [], False)[1]) and "AUTOFILL_SUBMIT" in d("approved", [], False)[1],
              "Default: never submits (AUTOFILL_SUBMIT is off)")
    with patch.dict(os.environ, {"AUTOFILL_SUBMIT": "true", "APPLY_DRY_RUN": "true"}):
        check(d("approved", [], False)[0] is False and "dry run" in d("approved", [], False)[1], "Dry run blocks submit")
    with patch.dict(os.environ, {"AUTOFILL_SUBMIT": "true", "APPLY_DRY_RUN": "false"}):
        check(d("pending", [], False)[0] is False, "Unapproved job blocks submit")
        check(d("approved", [{"field": "Why us?"}], False)[0] is False, "Unfilled required field blocks submit")
        check(d("approved", [], True)[0] is False, "CAPTCHA blocks submit")
        check(d("approved", [], False)[0] is True, "Only all five conditions together allow submit")
    check(policy.headless() is True and policy.mode() == "prefill", "Defaults: headless, prefill mode")

    check.section("4. Applicant profile")
    check(PROFILE.linkedin == "https://linkedin.com/in/asha-verma" and PROFILE.portfolio == "https://asha.dev",
          "URLs normalised to https://")
    for bad in ({"email": "not-an-email"}, {"phone": "call me"}, {"linkedin": "https://twitter.com/x"},
                {"github": "gitlab.com/x"}, {"first_name": "x" * 200}):
        try:
            ApplicantProfile(**bad)
            ok = False
        except ValueError:
            ok = True
        check(ok, f"Rejected: {bad if len(str(bad)) < 60 else 'over-long name'}")
    api = TestClient(app)
    r = api.put("/api/settings/applicant-profile", json={"email": "bad"})
    check(r.status_code == 422, "API rejects an invalid profile (422)")
    r = api.put("/api/settings/applicant-profile", json=PROFILE.model_dump())
    check(r.status_code == 200 and api.get("/api/settings/applicant-profile").json()["first_name"] == "Asha",
          "Profile saved and read back")
    cfg = api.get("/api/autofill/config").json()
    check(cfg["submit_enabled"] is False and cfg["profile_missing"] == [] and "playwright_installed" in cfg,
          "GET /api/autofill/config")

    check.section("5. Playwright not installed")
    shot_dir = Path(tempfile.mkdtemp())
    with patch("services.autofill.runner.playwright_available", return_value=False):
        rep = runner.run_prefill("http://127.0.0.1:9/x", "greenhouse", PROFILE, None, LETTER, "approved", shot_dir)
        check(rep["status"] == "failed" and "playwright install chromium" in rep["error"], "Report says how to install it")
        job = crud.create_job(db, schemas.JobCreate(title="ML Engineer", company="Fixture Co", source="ats",
                                                    url="https://boards.greenhouse.io/fixture/jobs/1"))
        r = api.post(f"/api/jobs/{job.id}/prefill")
        check(r.status_code == 422 and "pip install" in r.json()["detail"], "API answers 422 with the install hint")
        prev = api.get(f"/api/jobs/{job.id}/approve-preview").json()
        check(prev["autofill_possible"] and any("not available" in s for s in prev["steps"]),
              "Approve preview explains that form filling is unavailable")
    plain = crud.create_job(db, schemas.JobCreate(title="Analyst", company="Plain Co", url="https://plain.example/1"))
    r = api.post(f"/api/jobs/{plain.id}/prefill")
    check(r.status_code == 422 and "Greenhouse, Lever and Ashby" in r.json()["detail"], "Unsupported site -> clear 422")

    if not runner.playwright_available():
        print("  (skipped browser tests: Playwright is not installed)")
        db.close()
        check.done("FORM-FILLING")
        return

    check.section("6. Real browser against local fixture pages")
    server = ThreadingHTTPServer(("127.0.0.1", 0), FixtureHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    resume = Path(tempfile.mkdtemp()) / "asha_resume.pdf"
    resume.write_bytes(b"%PDF-1.4 test resume")
    try:
        with patch.dict(os.environ, {"AUTOFILL_TIMEOUT_SECONDS": "20"}):
            steps = []
            gh_rep = runner.run_prefill(f"{base}/greenhouse.html", None, PROFILE, resume, LETTER, "approved", shot_dir,
                                        on_step=steps.append)
        filled = {f["field"]: f["value"] for f in gh_rep["filled"]}
        check(gh_rep["error"] is None, f"Greenhouse fixture: no error ({gh_rep['error']})")
        check(filled.get("First Name") == "Asha" and filled.get("Last Name") == "Verma"
              and filled.get("Email") == "asha.verma@example.in", "Greenhouse: name and e-mail filled")
        check(filled.get("Location (City)") == "Bengaluru, India" and filled.get("LinkedIn Profile", "").startswith("https://linkedin.com")
              and filled.get("Website") == "https://asha.dev", "Greenhouse: location, LinkedIn, website filled")
        check(gh_rep["resume_uploaded"] and gh_rep["cover_letter"] == "pasted",
              "Greenhouse: resume uploaded, cover letter pasted via 'Enter manually'")
        unfilled = {u["field"] for u in gh_rep["unfilled_required"]}
        check(any("Why do you want" in u for u in unfilled), "Custom required question reported, not answered")
        check(any("sponsorship" in u for u in unfilled), "Visa question reported as needing your answer")
        check(any("Gender" in n["field"] for n in gh_rep["needs_your_answer"]), "EEO question listed, never answered")
        check(gh_rep["status"] == "needs_input" and gh_rep["submitted"] is False and not SUBMISSIONS,
              "Greenhouse: stopped before submit")
        check(gh_rep["screenshot"] and Path(gh_rep["screenshot"]).read_bytes()[:4] == b"\x89PNG", "Screenshot taken")
        check(steps[:2] == ["Starting the browser...", "Opening the application page..."] and len(steps) >= 5,
              "Progress steps reported")

        lv_rep = runner.run_prefill(f"{base}/lever.html", None, PROFILE, resume, LETTER, "approved", shot_dir)
        lv = {f["field"]: f["value"] for f in lv_rep["filled"]}
        check(lv.get("Full name") == "Asha Verma" and lv.get("Current company") is None,
              "Lever: full name filled; empty profile value (current company) left empty")
        check(lv.get("GitHub URL") == "https://github.com/asha-verma" and lv.get("Portfolio URL") == "https://asha.dev",
              "Lever: link fields filled")
        check(lv_rep["cover_letter"] == "pasted" and lv_rep["resume_uploaded"], "Lever: letter pasted, resume uploaded")
        check(lv_rep["captcha"] is True and lv_rep["status"] == "needs_input", "Lever: hCaptcha detected -> hand over")
        check(any("CTC" in u["field"] for u in lv_rep["unfilled_required"]), "Lever: salary question never answered")

        ab_rep = runner.run_prefill(f"{base}/ashby.html", None, PROFILE, resume, LETTER, "approved", shot_dir)
        ab = {f["field"]: f["value"] for f in ab_rep["filled"]}
        check(ab.get("Name") == "Asha Verma" and ab.get("Email") == "asha.verma@example.in" and ab_rep["resume_uploaded"],
              "Ashby (rendered by script): name, e-mail, resume")
        check(any("authorized to work" in u["field"] for u in ab_rep["unfilled_required"]),
              "Ashby: work-authorisation radio question left for the user")
        check(ab_rep["cover_letter"] == "not provided" and ab_rep["submitted"] is False, "Ashby: no cover field, not submitted")

        check.section("7. Submit gate with a real browser (local server only)")
        simple = f"{base}/simple.html"
        rep = runner.run_prefill(simple, None, PROFILE, resume, LETTER, "approved", shot_dir)
        check(rep["status"] == "prefilled" and not SUBMISSIONS and "AUTOFILL_SUBMIT" in rep["submit_reason"],
              "Complete form, default settings -> prefilled, NOT submitted")
        with patch.dict(os.environ, {"AUTOFILL_SUBMIT": "true", "APPLY_DRY_RUN": "false"}):
            rep = runner.run_prefill(simple, None, PROFILE, resume, LETTER, "pending", shot_dir)
            check(not rep["submitted"] and not SUBMISSIONS, "Submit allowed by config but job not approved -> not submitted")
            rep = runner.run_prefill(simple, None, PROFILE, resume, LETTER, "approved", shot_dir)
        check(rep["submitted"] and rep["status"] == "submitted" and len(SUBMISSIONS) == 1
              and SUBMISSIONS[0]["path"] == "/submit/simple", "All conditions met -> submitted to the LOCAL server")
        check(rep.get("submit_confirmed") is True, "Confirmation page detected after submit")
        bad = runner.run_prefill(f"{base}/missing.html", None, PROFILE, resume, LETTER, "approved", shot_dir)
        check(bad["status"] == "failed" and bad["error"], f"Missing page -> clear error ({(bad['error'] or '')[:60]})")

        check.section("8. Service: background record in applications")
        save_profile(db, PROFILE)
        job = crud.create_job(db, schemas.JobCreate(title="Backend Developer", company="Fixture Co", source="ats",
                                                    url="https://jobs.lever.co/fixture/1",
                                                    cover_letter=LETTER))
        task = service.start_prefill(job.id, session_factory=Session, url_override=f"{base}/greenhouse.html", inline=True)
        check(task["status"] == "done" and task["result"]["status"] == "needs_input", "Task finished: needs your input")
        check("Form pre-filled" in task["result"]["message"] and "Not submitted" in task["result"]["message"],
              f"Plain outcome: {task['result']['message'][:80]}")
        db.expire_all()
        row = db.query(models.Application).filter_by(job_id=job.id, method="autofill").one()
        payload = json.loads(row.payload_summary)
        check(row.status == "needs_input" and payload["filled"] and payload["screenshot"], "Application row records the report")
        apps = api.get("/api/applications").json()
        mine = next(a for a in apps if a["id"] == row.id)
        check(mine["screenshot_url"] and "screenshot" not in mine["payload_summary"], "API hides the file path, gives a URL")
        shot = api.get(mine["screenshot_url"])
        check(shot.status_code == 200 and shot.headers["content-type"] == "image/png", "Screenshot served as PNG")
        check("pre-filled" in mine["outcome"].lower(), "Outcome text in the applications list")
        tl = api.get(f"/api/jobs/{job.id}/timeline").json()
        check(any(e["kind"] == "application_autofill" for e in tl["events"]) and tl["tasks"], "Timeline shows the pre-fill")
    finally:
        server.shutdown()

    db.close()
    check.done("FORM-FILLING")


if __name__ == "__main__":
    run()
