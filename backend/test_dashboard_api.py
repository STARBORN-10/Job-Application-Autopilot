"""
Offline tests for the dashboard-facing API added in V2.5:
- top matches are ordered by score (ties: newest) over ALL jobs, skipped / rejected excluded, and the
  newest-first limit no longer hides an older 9+ job; /api/jobs?sort=score orders before the limit,
- the source list is the union of registered sources and the sources found in stored data, with counts
  (merged jobs counted under every source that found them); analytics can be filtered by source,
- exports: CSV / Excel / PDF with the right content types and file names, filters, and no formula
  injection (CSV prefix, Excel text cells),
- Approve shows exactly what it will do (preview), and returns a plain-language outcome; skip explains
  itself; the job timeline; the deprecated Make.com ingestion path still works with MAKE_API_KEY;
  CORS accepts any localhost dev port and FRONTEND_URL.
"""
import datetime
import io
import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent))

from testing_utils import Checker, use_temp_database

use_temp_database()
os.environ["MAKE_API_KEY"] = "legacy-key-123"

from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

import crud, models, schemas
import db_migrations
from database import engine
from main import app, cors_settings
from services import export as export_service

db_migrations.upgrade_database(engine)
Session = sessionmaker(bind=engine)


def add(db, title, score, source="adzuna", names=None, status="To Apply", approval="pending", company="Acme",
        description="", url=None):
    job = crud.create_job(db, schemas.JobCreate(title=title, company=company, score=score, source=source,
                                                source_names=names or [source], status=status,
                                                description=description, url=url or f"https://x.example/{title}"))
    job.approval_status = approval
    db.commit()
    return job


def run():
    check = Checker("RUNNING OFFLINE DASHBOARD API TESTS")
    db = Session()
    api = TestClient(app)

    check.section("1. Top matches by score")
    nine = add(db, "Old but great", 9.3, source="jsearch")
    for i in range(120):  # newer, weaker jobs push the 9.3 job out of a newest-first page of 100
        add(db, f"Filler {i}", 7.0 + (i % 10) / 10, source="adzuna")
    add(db, "Skipped high", 9.8, approval="skipped")
    add(db, "Rejected high", 9.7, status="Rejected")
    tie_old = add(db, "Tie old", 8.95, source="jooble")
    tie_new = add(db, "Tie new", 8.95, source="jooble")
    add(db, "No score", None)
    newest_page = api.get("/api/jobs", params={"limit": 100}).json()
    check(nine.id not in {j["id"] for j in newest_page}, "Reproduces the bug: newest-first page of 100 misses the 9.3 job")
    top = api.get("/api/jobs/top", params={"limit": 5}).json()
    check(top[0]["id"] == nine.id and top[0]["score"] == 9.3, "Top list starts with the highest score (9.3)")
    check([j["score"] for j in top] == sorted([j["score"] for j in top], reverse=True), "Sorted by score, descending")
    check(all(j["title"] not in ("Skipped high", "Rejected high") for j in top), "Skipped and Rejected jobs excluded")
    ids = [j["id"] for j in top]
    check(ids.index(tie_new.id) < ids.index(tie_old.id), "Ties: newest first")
    check(all(j["score"] is not None for j in api.get("/api/jobs/top", params={"limit": 100}).json()), "Unscored jobs excluded")
    check(all(j["score"] >= 9 for j in api.get("/api/jobs/top", params={"min_score": 9}).json()), "min_score filter")
    by_score = api.get("/api/jobs", params={"limit": 3, "sort": "score"}).json()
    check([j["score"] for j in by_score] == [9.8, 9.7, 9.3], "/api/jobs?sort=score orders before the limit")
    check(api.get("/api/jobs", params={"sort": "random"}).status_code == 422, "Unknown sort rejected")

    check.section("2. Sources: registered + found in data, with counts")
    add(db, "Merged job", 8.0, source="adzuna", names=["adzuna", "jooble", "ats"])
    add(db, "V1 job", 7.5, source="JSearch")
    add(db, "Legacy ingest", 7.2, source="make")
    summary = {s["name"]: s for s in api.get("/api/sources/summary").json()}
    check({"jsearch", "adzuna", "jooble", "ats", "internshala", "jobspy"} <= set(summary), "All registered sources listed")
    check(summary["make"]["registered"] is False and summary["make"]["jobs"] == 1, "Source found only in data is listed")
    check(summary["jsearch"]["jobs"] == 2, "V1 'JSearch' and V2 'jsearch' counted together")
    check(summary["ats"]["jobs"] == 0 and summary["ats"]["seen"] == 1, "Merged job counted as 'seen' on every source")
    check(summary["internshala"]["jobs"] == 0 and summary["internshala"]["enabled"] is False, "Zero-count sources included")
    merged = next(j for j in api.get("/api/jobs", params={"limit": 500}).json() if j["title"] == "Merged job")
    check(merged["source_names"] == ["adzuna", "jooble", "ats"], "source_names exposed for 'Also found on'")
    a_all = api.get("/api/analytics").json()
    a_jooble = api.get("/api/analytics", params={"source": "jooble"}).json()
    check(a_jooble["total_jobs"] == 3 and a_all["total_jobs"] > a_jooble["total_jobs"],
          "Analytics source filter (primary or merged source)")
    check({s["source"] for s in a_all["sources"]} >= {"adzuna", "jooble", "jsearch", "make"},
          "Analytics sources reflect the stored data")

    check.section("3. Exports")
    add(db, "=HYPERLINK(\"http://evil\")", 8.1, company="+SUM(A1)", source="jooble")
    r = api.get("/api/export/jobs.csv")
    check(r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
          and 'filename="jobs-' in r.headers["content-disposition"], "CSV: content type and file name")
    check("'=HYPERLINK" in r.text and "'+SUM" in r.text, "CSV: formula injection neutralised")
    r = api.get("/api/export/jobs.xlsx", params={"source": "jooble"})
    check(r.status_code == 200 and r.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet") and r.content[:2] == b"PK",
        "Excel: content type, real .xlsx")
    from openpyxl import load_workbook
    ws = load_workbook(io.BytesIO(r.content)).active
    header = [c.value for c in ws[1]]
    check(header[:3] == ["ID", "Title", "Company"] and ws["A1"].font.bold and ws.freeze_panes == "A2",
          "Excel: bold header, frozen first row")
    titles = [ws.cell(row=i, column=2).value for i in range(2, ws.max_row + 1)]
    evil_row = titles.index('=HYPERLINK("http://evil")') + 2
    check(ws.cell(row=evil_row, column=2).data_type == "s" and ws.cell(row=evil_row, column=3).data_type == "s",
          "Excel: '=...' and '+...' stored as text, never as formulas")
    check(all(ws.cell(row=i, column=7).value == "jooble" or "jooble" in (ws.cell(row=i, column=8).value or "")
              for i in range(2, ws.max_row + 1)), "Excel: source filter applied")
    check(ws.column_dimensions["B"].width >= 30, "Excel: sensible column widths")
    r = api.get("/api/export/jobs.pdf", params={"min_score": 9})
    check(r.status_code == 200 and r.headers["content-type"] == "application/pdf" and r.content[:5] == b"%PDF-",
          "PDF: content type, real PDF")
    check(api.get("/api/export/jobs.pdf", params={"source": "nothing-here"}).status_code == 200,
          "PDF with no matching jobs still renders")
    check(api.get("/api/export/jobs.docx").status_code == 404, "Unknown format -> 404")
    filtered = export_service.filter_jobs(db.query(models.Job).all(), status="Rejected")
    check(len(filtered) == 1 and filtered[0].title == "Rejected high", "Status filter")

    check.section("4. Approve: preview, outcome, timeline; skip")
    import tempfile
    pdf = Path(tempfile.mkdtemp()) / "cv.pdf"
    pdf.write_bytes(b"%PDF-1.4 cv")
    crud.create_resume(db, filename="cv.pdf", target_role="AI/ML Engineer", extracted_text="Python developer, SQL.",
                       file_path=str(pdf), file_size=10)
    job = add(db, "Recruiter mail job", 8.4, description="Please send your resume to hr@acme.in",
              url="https://acme.example/jobs/9")
    job.cover_letter = "Dear Hiring Team, " * 10
    db.commit()
    prev = api.get(f"/api/jobs/{job.id}/approve-preview").json()
    check(prev["method"] == "email" and prev["recruiter_email"] == "hr@acme.in" and prev["dry_run"] is True,
          "Preview: e-mail method, recruiter address, dry run")
    check(any("NOT sent" in s for s in prev["steps"]) and any("Resume" in s for s in prev["steps"]),
          "Preview steps explain the dry run and the resume")
    r = api.post(f"/api/jobs/{job.id}/approve").json()
    check(r["changed"] and r["application"]["status"] == "dry_run" and r["message"].startswith("Dry run"),
          f"Outcome in plain language: {r['message'][:70]}")
    check(r["application"]["outcome"] == r["message"] and r["application"]["cover_letter"], "Outcome + letter in the record")
    again = api.post(f"/api/jobs/{job.id}/approve").json()
    check(again["changed"] is False and "already approved" in again["message"], "Approving twice repeats nothing")
    tl = api.get(f"/api/jobs/{job.id}/timeline").json()
    kinds = [e["kind"] for e in tl["events"]]
    check(kinds[0] == "found" and "decision_approved" in kinds and "application_email" in kinds,
          f"Timeline: found -> approved -> application ({kinds})")
    gh = add(db, "Greenhouse job", 8.0, url="https://boards.greenhouse.io/acme/jobs/77")
    prev = api.get(f"/api/jobs/{gh.id}/approve-preview").json()
    check(prev["method"] == "assisted" and prev["ats"] == "greenhouse" and prev["autofill_possible"], "Preview: Greenhouse")
    r = api.post(f"/api/jobs/{gh.id}/approve").json()
    check(r["application"]["method"] == "assisted" and "submit it yourself" in r["message"]
          and r["autofill_note"], "Assisted outcome + why the pre-fill did not start (off in tests)")
    s = api.post(f"/api/jobs/{gh.id}/skip").json()
    check(s["job"]["approval_status"] == "skipped" and "Nothing was sent" in s["message"], "Skip explains itself")
    check(api.get("/api/jobs/99999/approve-preview").status_code == 404, "Unknown job -> 404")
    apps = api.get("/api/applications").json()
    check(all("outcome" in a and "resume_kind" in a for a in apps), "Applications list carries outcome + resume used")

    check.section("5. Deprecated Make.com ingestion still works")
    r = api.post("/api/jobs", json={"title": "Ingested", "company": "Legacy"})
    check(r.status_code == 401, "Without X-API-Key -> 401")
    r = api.post("/api/jobs", json={"title": "Ingested", "company": "Legacy", "experience": "Fresher"},
                 headers={"X-API-Key": "legacy-key-123"})
    check(r.status_code == 200 and r.json()["title"] == "Ingested", "With MAKE_API_KEY -> job saved")
    r = api.get("/api/make/context", headers={"X-API-Key": "legacy-key-123"})
    check(r.status_code == 200 and "active_role" in r.json(), "GET /api/make/context still answers")
    spec = api.get("/openapi.json").json()
    check(spec["paths"]["/api/make/context"]["get"].get("deprecated") is True
          and spec["paths"]["/api/jobs"]["post"].get("deprecated") is True, "Legacy endpoints marked deprecated")

    check.section("6. CORS for local dev ports and FRONTEND_URL")
    for origin in ("http://localhost:5173", "http://localhost:5180", "http://127.0.0.1:4173"):
        r = api.options("/api/jobs", headers={"Origin": origin, "Access-Control-Request-Method": "GET"})
        check(r.status_code == 200 and r.headers.get("access-control-allow-origin") in (origin, "*"),
              f"Preflight allowed for {origin}")
    with patch.dict(os.environ, {"CORS_ORIGINS": "https://a.example", "FRONTEND_URL": "https://dash.example/"}):
        cfg = cors_settings()
    check(cfg["allow_origins"] == ["https://a.example", "https://dash.example"], "FRONTEND_URL added to CORS_ORIGINS")
    import re
    check(re.match(cfg["allow_origin_regex"], "http://localhost:5180") and not re.match(cfg["allow_origin_regex"], "https://evil.example"),
          "Localhost regex accepts dev ports only")

    db.close()
    check.done("DASHBOARD API")


if __name__ == "__main__":
    run()
