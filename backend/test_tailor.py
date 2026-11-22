"""
Offline tests for the tailored resume (services/resume_tailor.py):
- the honesty verifier removes invented employers, titles, degrees, certifications, skills, tools,
  numbers and contact details, and keeps everything that is traceable to the original resume,
- jobs at or above the threshold keep the original (no AI call),
- re-scoring uses the same engine, before/after are computed (never hard-coded), invented skills can
  never raise the score, and missing skills are reported as gaps instead of being added,
- PDF / DOCX rendering, caching, regenerate, the API endpoints, the no-AI path, and Approve using the
  tailored resume. The AI layer is mocked; nothing goes online.
"""
import datetime
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent))

from testing_utils import Checker, use_temp_database

use_temp_database()

from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

import crud, models, schemas
import db_migrations
from database import engine
from main import app
from services import llm, resume_tailor
from services.llm import LLMResult
from services.scoring import facts as facts_mod
from services.scoring.engine import score_job
from services.scoring.profile import heuristic_profile

db_migrations.upgrade_database(engine)
Session = sessionmaker(bind=engine)

ORIGINAL = """Asha Verma
asha.verma@example.in | +91 98765 43210 | linkedin.com/in/asha-verma | Bengaluru
SUMMARY
Computer science student building machine learning and backend projects in Python.
SKILLS
Python, SQL, FastAPI, Docker, Pandas, scikit-learn, Git
EXPERIENCE
Data Science Intern, Acme Analytics (Jun 2025 - Aug 2025)
- Built a churn model with scikit-learn reaching 87% accuracy on 12,000 customer records
- Automated weekly SQL reports for the sales team
PROJECTS
Resume Matcher (2025) | Python, FastAPI
- REST API that scores resumes against job posts
EDUCATION
B.Tech Computer Science, Example Institute of Technology, 2022 - 2026, CGPA 8.4
CERTIFICATIONS
AWS Cloud Practitioner
"""

DRAFT = {
    "name": "Asha Verma",
    "contact": ["asha.verma@example.in | +91 98765 43210 | github.com/asha-fake"],
    "summary": ("Computer science student who builds machine learning and backend projects in Python. "
                "Led a team of 10 engineers at Microsoft."),
    "skills": ["scikit-learn", "Python", "SQL", "Kubernetes", "FastAPI", "TensorFlow", "Docker", "Python"],
    "experience": [
        {"title": "Data Science Intern", "organization": "Acme Analytics", "dates": "Jun 2025 - Aug 2025",
         "bullets": ["Built a customer churn model in scikit-learn with 87% accuracy on 12,000 records",
                     "Improved model latency by 40%",
                     "Deployed models on Kubernetes clusters",
                     "Automated weekly SQL reports for the sales team"]},
        {"title": "Machine Learning Engineer", "organization": "Google", "dates": "2024",
         "bullets": ["Trained large models"]},
    ],
    "projects": [{"name": "Resume Matcher", "dates": "2025", "technologies": ["Python", "FastAPI", "React"],
                  "bullets": ["REST API in FastAPI that scores resumes against job posts"]}],
    "education": [{"degree": "B.Tech Computer Science", "institution": "Example Institute of Technology",
                   "dates": "2022 - 2026", "details": "CGPA 8.4"},
                  {"degree": "M.Tech", "institution": "IIT Bombay", "dates": "2027", "details": ""}],
    "certifications": ["AWS Cloud Practitioner", "Google Professional ML Engineer"],
    "achievements": [],
}

DESCRIPTION = ("We need a Machine Learning Engineer with Python, scikit-learn, SQL, Docker, Kubernetes and TensorFlow. "
               "Build models and FastAPI services. Fresher friendly, 0-1 years.")

CALLS = []


def fake_generate(task, prompt, schema=None, system="", max_tokens=700, clients=None):
    if system != resume_tailor.TAILOR_SYSTEM:
        raise llm.LLMUnavailableError("only the tailor prompt is mocked")
    CALLS.append(task)
    data = schema.model_validate(DRAFT).model_dump() if schema else DRAFT
    return LLMResult(data=data, provider="fake", model="fake-model")


def make_job(db, title, score=None, url="https://jobs.example.in/1"):
    j = schemas.JobCreate(title=title, company="Beta AI", url=url, location="Bengaluru, India",
                          description=DESCRIPTION, experience="0-1 years", source="adzuna", description_quality="full",
                          posted_date=datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None))
    settings = crud.get_general_settings(db)
    facts = facts_mod.heuristic_facts(j)
    result = score_job(j, facts, heuristic_profile(ORIGINAL, settings.active_role, settings.target_roles), settings)
    j.score = score if score is not None else result.score
    j.score_breakdown = result.breakdown
    j.cover_letter = "Dear Hiring Team, I build machine learning projects in Python. " * 3
    return crud.create_job(db, j)


def run():
    check = Checker("RUNNING OFFLINE TAILORED-RESUME TESTS")
    db = Session()
    resume_dir = Path(tempfile.mkdtemp())
    pdf = resume_dir / "asha.pdf"
    pdf.write_bytes(b"%PDF-1.4 original resume")
    crud.create_resume(db, filename="asha.pdf", target_role="AI/ML Engineer", extracted_text=ORIGINAL,
                       file_path=str(pdf), file_size=pdf.stat().st_size)

    check.section("1. Honesty verifier")
    draft = resume_tailor.StructuredResume.model_validate(DRAFT)
    clean, removed = resume_tailor.verify(draft, ORIGINAL)
    reasons = {r["text"]: r["reason"] for r in removed}
    lowered = [s.lower() for s in clean.skills]
    check("kubernetes" not in lowered and "tensorflow" not in lowered, "Skills not in the resume are removed")
    check(lowered == ["scikit-learn", "python", "sql", "fastapi", "docker"], f"Real skills kept, in the new order, deduplicated ({clean.skills})")
    check([e.organization for e in clean.experience] == ["Acme Analytics"], "Invented employer entry (Google) removed")
    bullets = clean.experience[0].bullets
    check("Improved model latency by 40%" not in bullets, "Bullet with an invented number (40%) removed")
    check(not any("Kubernetes" in b for b in bullets), "Bullet naming an invented tool removed")
    check("Built a customer churn model in scikit-learn with 87% accuracy on 12,000 records" in bullets,
          "Reworded bullet with real numbers (87%, 12,000) kept")
    check(clean.experience[0].dates == "Jun 2025 - Aug 2025", "Real dates kept")
    check([ed.institution for ed in clean.education] == ["Example Institute of Technology"], "Invented degree removed")
    check(clean.certifications == ["AWS Cloud Practitioner"], "Invented certification removed")
    check(clean.projects[0].technologies == ["Python", "FastAPI"], "Invented project technology (React) removed")
    check("Microsoft" not in clean.summary and clean.summary.startswith("Computer science student"),
          "Invented summary sentence removed, real one kept")
    check(clean.contact == ["asha.verma@example.in | +91 98765 43210"], "Invented contact link removed")
    check(len(removed) >= 10 and all(r["reason"] for r in removed), f"Every removal is logged with a reason ({len(removed)})")
    check(any("40" in r["reason"] for r in removed), "Removal reason names the invented number")
    text = resume_tailor.render_text(clean)
    for invented in ("Kubernetes", "TensorFlow", "Google", "IIT Bombay", "Microsoft", "React", "40%"):
        check(invented not in text, f"'{invented}' does not appear in the tailored text")
    v = resume_tailor.Verifier(ORIGINAL)
    check(v.numbers_supported("CGPA 8.4, 87%")[0] and not v.numbers_supported("CGPA 9.1")[0], "Number check")
    check(v.dates_supported("2022 - 2026") and not v.dates_supported("2019"), "Date check")
    broken = "Jan 2025 â€“ Mar 2025 â€™s â€¢ ok café"
    check(resume_tailor.fix_mojibake(broken) == "Jan 2025 – Mar 2025 ’s • ok café",
          "Broken PDF dashes/quotes/bullets are repaired; real accented text is untouched")
    iv = resume_tailor.Verifier("AWS AI/ML Virtual Internship - AICTE. Built models in Python.")
    check(iv.phrase_supported("AWS AI/ML Virtual Intern") and iv.phrase_supported("Python Developer") is False,
          "Title 'Intern' matches the resume's 'Internship' (stem), an unrelated word does not")
    check(not iv.phrase_supported("Senior Machine Learning Manager"), "Invented seniority/title still rejected")

    check.section("2. Score already at or above the threshold: original kept, no AI call")
    high = make_job(db, "Machine Learning Engineer", score=9.3, url="https://jobs.example.in/high")
    CALLS.clear()
    with patch("services.resume_tailor.llm.generate_json", side_effect=fake_generate):
        row = resume_tailor.tailor_for_job(db, high)
    check(row.status == "not_needed" and not CALLS, "Score 9.3 >= 9.0 -> not_needed, AI not called")
    info = resume_tailor.to_dict(row)
    check(info["score_before"] == info["score_after"] == 9.3 and "unchanged" in info["message"],
          "Original score shown, message says the resume is unchanged")
    with patch.dict(os.environ, {"TAILOR_SCORE_THRESHOLD": "9.5"}):
        check(resume_tailor.threshold() == 9.5, "Threshold is configurable (TAILOR_SCORE_THRESHOLD)")

    check.section("3. Tailoring below the threshold: verified rewrite + honest re-score")
    job = make_job(db, "Machine Learning Engineer")
    stored = job.score
    CALLS.clear()
    with patch("services.resume_tailor.llm.generate_json", side_effect=fake_generate):
        row = resume_tailor.tailor_for_job(db, job)
    info = resume_tailor.to_dict(row)
    check(row.status == "tailored" and CALLS == ["write"], "Tailored with one AI call (task 'write')")
    check(info["removed_unverified"] and len(info["removed_unverified"]) == len(removed), "Removed items persisted")
    check({"kubernetes", "tensorflow"} <= set(info["gaps"]), f"Missing skills listed as gaps, not added ({info['gaps']})")
    check(info["score_before"] is not None and info["score_after"] is not None, "Before and after scores computed")
    check(abs(info["score_before"] - stored) < 0.11, f"'Before' re-score matches the stored score ({info['score_before']} vs {stored})")
    check(info["score_after"] >= info["score_before"], f"Tailoring never lowers the score ({info['score_before']} -> {info['score_after']})")
    check(info["score_after"] < 9.0, "The score stays honest: it does not reach 9 when real skills are missing")
    # A job saved by the old V1 pipeline has a single AI-opinion score and no breakdown: the page must say why
    # the before/after numbers differ from the saved score.
    legacy = make_job(db, "Machine Learning Engineer", score=8.9, url="https://jobs.example.in/legacy")
    legacy.score_breakdown = None
    db.commit()
    with patch("services.resume_tailor.llm.generate_json", side_effect=fake_generate):
        lrow = resume_tailor.tailor_for_job(db, legacy, regenerate=True)
    check(lrow.status == "tailored" and "older AI-opinion score" in resume_tailor.to_dict(lrow)["message"],
          "Legacy (V1) score is explained next to the before/after numbers")
    # What would the score have been if the invented skills had been accepted? It must be higher than what we report.
    settings = crud.get_general_settings(db)
    cheat_profile = heuristic_profile(ORIGINAL, settings.active_role, settings.target_roles)
    cheat_profile = cheat_profile.model_copy(update={"skills": cheat_profile.skills + ["kubernetes", "tensorflow"]})
    cheat = score_job(job, resume_tailor.facts_from_job(job), cheat_profile, settings)
    check(cheat.score > info["score_after"], f"Invented skills would have raised it ({cheat.score}); the verifier kept them out")
    check(info["breakdown_after"]["parts"]["skills"]["value"] <= cheat.breakdown["parts"]["skills"]["value"],
          "After-breakdown comes from the same scoring engine")
    kb, ka = info["keyword_coverage_before"], info["keyword_coverage_after"]
    check(kb["total"] == ka["total"] and ka["found"] >= kb["found"] and "kubernetes" not in ka["found_skills"],
          f"Keyword coverage before/after ({kb['found']}/{kb['total']} -> {ka['found']}/{ka['total']})")
    check("Kubernetes" not in row.tailored_text and "Asha Verma" in row.tailored_text, "Tailored text has no invented facts")

    check.section("4. Files, cache and regenerate")
    check(row.pdf_path and Path(row.pdf_path).read_bytes()[:5] == b"%PDF-", "PDF rendered")
    check(row.docx_path and Path(row.docx_path).read_bytes()[:2] == b"PK", "DOCX rendered")
    check(str(Path(os.environ["GENERATED_DIR"])) in row.pdf_path, "Files go to GENERATED_DIR (outside the repo in tests)")
    Path(row.pdf_path).unlink()
    check(resume_tailor.file_for(row, "pdf") is not None, "A missing file is re-rendered from the stored JSON")
    CALLS.clear()
    with patch("services.resume_tailor.llm.generate_json", side_effect=fake_generate):
        again = resume_tailor.tailor_for_job(db, job)
        check(again.id == row.id and not CALLS, "Cached: same job + resume version -> no new AI call")
        fresh = resume_tailor.tailor_for_job(db, job, regenerate=True)
    check(fresh.id != row.id and CALLS == ["write"], "regenerate=True makes a new version")

    check.section("5. No AI provider")
    nojob = make_job(db, "Python Developer", url="https://jobs.example.in/noai")
    with patch("services.resume_tailor.llm.generate_json", side_effect=llm.LLMUnavailableError("All AI providers failed")):
        failed = resume_tailor.tailor_for_job(db, nojob)
    check(failed.status == "failed" and "unchanged" in resume_tailor.to_dict(failed)["message"]
          and "AI providers" in failed.error, "Honest failure: original kept, reason recorded")

    check.section("6. API")
    api = TestClient(app)
    with patch("services.resume_tailor.llm.generate_json", side_effect=fake_generate):
        r = api.post(f"/api/jobs/{nojob.id}/tailor-resume?regenerate=true")
    check(r.status_code == 200 and r.json()["status"] == "tailored", "POST /api/jobs/{id}/tailor-resume")
    r = api.get(f"/api/jobs/{nojob.id}/tailored-resume")
    check(r.status_code == 200 and r.json()["structured"]["skills"] and r.json()["outdated"] is False,
          "GET /api/jobs/{id}/tailored-resume returns the structured resume")
    r = api.get(f"/api/jobs/{nojob.id}/tailored-resume.pdf")
    check(r.status_code == 200 and r.headers["content-type"] == "application/pdf" and r.content[:5] == b"%PDF-"
          and "attachment" in r.headers["content-disposition"], "PDF download")
    r = api.get(f"/api/jobs/{nojob.id}/tailored-resume.docx")
    check(r.status_code == 200 and "wordprocessingml" in r.headers["content-type"] and r.content[:2] == b"PK",
          "DOCX download")
    check(api.get(f"/api/jobs/{high.id}/tailored-resume.pdf").status_code == 404,
          "No file when the original is used (not_needed)")
    check(api.get("/api/jobs/99999/tailored-resume").status_code == 404, "Unknown job -> 404")
    with patch("services.resume_tailor.latest", return_value=None):
        r = api.get(f"/api/jobs/{nojob.id}/tailored-resume")
    check(r.status_code == 200 and r.json() is None, "No tailored resume yet -> 200 null (not a 404 error)")
    check(api.get(f"/api/jobs/{nojob.id}/tailored-resume.txt").status_code == 404, "Unknown file type -> 404")

    check.section("7. Approve uses the tailored resume")
    target = make_job(db, "Machine Learning Engineer", url="https://jobs.example.in/approve")
    target.description += " Send your resume to hr@beta-ai.in"
    db.commit()
    with patch("services.resume_tailor.llm.generate_json", side_effect=fake_generate):
        r = api.post(f"/api/jobs/{target.id}/approve")
    body = r.json()
    check(r.status_code == 200 and body["tailored_resume"]["status"] == "tailored", "Approve tailors the resume first")
    app_out = body["application"]
    check(app_out["status"] == "dry_run" and app_out["resume_kind"] == "tailored"
          and app_out["resume_file"].endswith(".pdf"), "The e-mail (dry run) attaches the tailored PDF")
    check("NOT sent" in body["message"] and "hr@beta-ai.in" in body["message"], f"Plain outcome: {body['message'][:90]}")
    with patch.dict(os.environ, {"AUTO_TAILOR_ON_APPROVE": "false"}):
        off = make_job(db, "Data Scientist", url="https://jobs.example.in/off")
        r = api.post(f"/api/jobs/{off.id}/approve")
    check(r.json()["tailored_resume"] is None and r.json()["application"]["resume_kind"] == "original",
          "AUTO_TAILOR_ON_APPROVE=false keeps the original resume")

    db.close()
    check.done("TAILORED-RESUME")


if __name__ == "__main__":
    run()
