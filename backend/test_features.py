"""
Offline tests for: analytics aggregation, CSV export, and AI resume-to-job compatibility analysis.
Zero live external API calls are made (Gemini is mocked).
"""

import csv
import datetime
import io
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent))

TEST_API_KEY = "test_features_key"
os.environ["MAKE_API_KEY"] = TEST_API_KEY
temp_db_file = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
temp_db_file.close()
os.environ["DATABASE_URL"] = f"sqlite:///{temp_db_file.name}"

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from fastapi.testclient import TestClient

import crud
import schemas
from main import app
from database import Base, get_db
from services import ai_service, analytics

test_engine = create_engine(f"sqlite:///{temp_db_file.name}", connect_args={"check_same_thread": False})
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)
Base.metadata.create_all(bind=test_engine)


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db
client = TestClient(app)

AUTH = {"X-API-Key": TEST_API_KEY}


def run():
    total = passed = 0

    def check(cond, name):
        nonlocal total, passed
        total += 1
        if cond:
            passed += 1
            print(f"  [PASS] {name}")
        else:
            print(f"  [FAIL] {name}")
            raise AssertionError(f"Test failed: {name}")

    today = datetime.date(2026, 11, 20)

    def job(score, status, company, days_ago, source="JSearch"):
        return SimpleNamespace(
            score=score, status=status, company=company, source=source,
            date_found=datetime.datetime.combine(today - datetime.timedelta(days=days_ago), datetime.time(9)),
        )

    # ------------------------------------------------------------------
    print("\n--- 1. Analytics aggregation ---")
    empty = analytics.build_analytics([], today=today)
    check(empty["total_jobs"] == 0 and empty["average_score"] == 0.0, "Empty dataset yields zeros (no crash)")
    check(len(empty["jobs_over_time"]) == 30, "Timeline covers 30 days even when empty")

    jobs = [
        job(9.5, "Interview", "Acme", 0), job(8.0, "Applied", "Acme", 1),
        job(7.0, "To Apply", "Beta", 1), job(4.0, "Rejected", "Gamma", 40, source="Manual"),
        job(6.0, "Offer", "Beta", 2), job(None, None, "Delta", 3),
    ]
    a = analytics.build_analytics(jobs, today=today)
    check(a["total_jobs"] == 6, "Total jobs counted")
    check(a["average_score"] == round((9.5 + 8 + 7 + 4 + 6) / 5, 1), "Average ignores jobs without a score")
    funnel = {f["status"]: f["count"] for f in a["funnel"]}
    check(funnel == {"To Apply": 2, "Applied": 1, "Interview": 1, "Offer": 1, "Rejected": 1},
          "Funnel counts statuses (missing status = To Apply)")
    dist = {d["range"]: d["count"] for d in a["score_distribution"]}
    check(dist == {"0-4": 1, "5-6": 1, "7-8": 2, "9-10": 1}, "Score distribution buckets are correct")
    check(sum(p["count"] for p in a["jobs_over_time"]) == 5, "Timeline excludes jobs older than the window")
    check(a["jobs_over_time"][-1] == {"date": "2026-11-20", "count": 1}, "Timeline ends today")
    check(a["top_companies"][0] == {"company": "Acme", "count": 2}, "Top company ranked first")
    check(a["applied_count"] == 4 and a["application_rate"] == round(100 * 4 / 6, 1), "Application rate computed")
    check(a["interview_rate"] == 50.0, "Interview rate = (interview+offer) / applied-or-later")

    # ------------------------------------------------------------------
    print("\n--- 2. CSV export ---")
    rows = list(csv.reader(io.StringIO(analytics.jobs_to_csv([
        SimpleNamespace(id=1, title="=HYPERLINK(\"http://evil\")", company="A, Inc", location="Remote",
                        job_type=None, experience="Fresher", source="JSearch", score=8.5, status="To Apply",
                        date_found=datetime.datetime(2026, 11, 20, 9, 0), url="https://x.io", match_reason="ok\nline2"),
    ]))))
    check(rows[0][:3] == ["id", "title", "company"], "CSV has header row")
    check(rows[1][1].startswith("'="), "Formula-injection prefix neutralised")
    check(rows[1][2] == "A, Inc", "Commas are quoted correctly")
    check(rows[1][4] == "" and rows[1][7] == "8.5", "None -> empty cell; score preserved")

    # ------------------------------------------------------------------
    print("\n--- 3. Analytics + export endpoints ---")
    db = TestingSessionLocal()
    created = crud.create_job(db, schemas.JobCreate(
        title="ML Engineer", company="Acme", url="https://acme.io/1", location="Remote",
        description="Python, PyTorch, MLOps", experience="Fresher", source="JSearch", score=8.2,
        match_reason="Strong fit", cover_letter="Dear team", status="To Apply"))
    job_id = created.id
    r = client.get("/api/analytics")
    check(r.status_code == 200 and r.json()["total_jobs"] == 1, "GET /api/analytics returns aggregated data")
    check(client.get("/api/analytics?days=3").status_code == 422, "days below minimum is rejected")
    r = client.get("/api/export/jobs.csv")
    check(r.status_code == 200 and r.headers["content-type"].startswith("text/csv"), "CSV export returns text/csv")
    check("ML Engineer" in r.text and "attachment" in r.headers["content-disposition"], "CSV contains jobs + download header")

    # ------------------------------------------------------------------
    print("\n--- 4. AI compatibility analysis ---")
    good = '{"summary":"Good fit.","matched_skills":["Python"],"missing_skills":["MLOps"],"resume_suggestions":["Add deployment project"]}'
    parsed = ai_service.parse_compatibility_response(f"```json\n{good}\n```")
    check(parsed.matched_skills == ["Python"] and parsed.missing_skills == ["MLOps"], "Parses fenced JSON analysis")
    for bad in ("", "not json", "[1,2]", '{"summary":"  "}'):
        try:
            ai_service.parse_compatibility_response(bad)
            ok = False
        except ai_service.AIResponseFormatError:
            ok = True
        check(ok, f"Rejects invalid analysis output: {bad[:15]!r}")

    mock_client = MagicMock()
    mock_client.models.generate_content.return_value = SimpleNamespace(text=good)
    res = ai_service.analyze_compatibility("ML Eng", "Acme", "Needs Python", "Resume text", client=mock_client)
    check(res.summary == "Good fit." and mock_client.models.generate_content.call_count == 1,
          "analyze_compatibility calls Gemini once and returns structured result")
    try:
        ai_service.analyze_compatibility("T", "C", "desc", "   ", client=mock_client)
        ok = False
    except ai_service.AIValidationError:
        ok = True
    check(ok, "Empty resume raises AIValidationError")

    # Endpoint: no resume yet
    r = client.post(f"/api/jobs/{job_id}/analyze")
    check(r.status_code == 422 and "resume" in r.json()["detail"].lower(), "Analyze without resume -> 422")
    check(client.post("/api/jobs/9999/analyze").status_code == 404, "Analyze unknown job -> 404")

    crud.create_resume(db=db, filename="r.pdf", target_role="AI/ML Engineer",
                       extracted_text="Python developer, PyTorch projects.", file_path="/tmp/r.pdf", file_size=10)

    with patch("services.ai_service.analyze_compatibility",
               return_value=ai_service.CompatibilityAnalysis(
                   summary="ok", matched_skills=["Python"], missing_skills=["MLOps"], resume_suggestions=[])):
        r = client.post(f"/api/jobs/{job_id}/analyze")
    check(r.status_code == 200 and r.json()["missing_skills"] == ["MLOps"], "Analyze endpoint returns skill gaps")

    for exc, code in [(ai_service.AIConfigError("no key"), 503), (ai_service.AIRateLimitError("429"), 429),
                      (ai_service.AITimeoutError("t"), 504), (ai_service.AIAuthError("bad"), 502)]:
        with patch("services.retry.time.sleep"), patch("services.ai_service.analyze_compatibility", side_effect=exc):
            r = client.post(f"/api/jobs/{job_id}/analyze")
        check(r.status_code == code, f"{type(exc).__name__} maps to HTTP {code}")

    db.close()
    print("\n" + "=" * 70)
    print(f"ALL FEATURE TESTS PASSED! ({passed}/{total})")
    print("=" * 70)
    try:
        os.remove(temp_db_file.name)
    except Exception:
        pass


if __name__ == "__main__":
    run()
