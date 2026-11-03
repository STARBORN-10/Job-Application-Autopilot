"""
Integration test suite for Job Application Autopilot - Phase 1.
Tests:
1. Make.com Authentication & Context Endpoint (GET /api/make/context)
2. Experience Filter Enforcement on Job Creation (POST /api/jobs)
3. Duplicate Job Detection (URL primary, Title+Company fallback)
4. Existing Job CRUD Operations (GET, PUT, DELETE)
5. Resume & Experience Filter Settings Endpoints
"""

import os
import sys
import tempfile
from pathlib import Path

# Set test environment key BEFORE importing main
TEST_API_KEY = "test_phase1_secret_key"
os.environ["MAKE_API_KEY"] = TEST_API_KEY

# Use an isolated temporary SQLite database for tests
temp_db_file = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
temp_db_file.close()
os.environ["DATABASE_URL"] = f"sqlite:///{temp_db_file.name}"

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from fastapi.testclient import TestClient

import models
import database
from main import app
from database import Base, get_db

# Create isolated test engine and session
test_engine = create_engine(
    f"sqlite:///{temp_db_file.name}",
    connect_args={"check_same_thread": False},
)
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

AUTH_HEADER = {"X-API-Key": TEST_API_KEY}


def run_tests():
    print("=" * 70)
    print("RUNNING JOB APPLICATION AUTOPILOT - PHASE 1 TEST SUITE")
    print("=" * 70)

    total_tests = 0
    passed_tests = 0

    def assert_test(condition, test_name):
        nonlocal total_tests, passed_tests
        total_tests += 1
        if condition:
            passed_tests += 1
            print(f"  [PASS] {test_name}")
        else:
            print(f"  [FAIL] {test_name}")
            raise AssertionError(f"Test failed: {test_name}")

    # -----------------------------------------------------------------------
    # 1. Make.com Authentication & Context Endpoint
    # -----------------------------------------------------------------------
    print("\n--- 1. Testing GET /api/make/context & Auth ---")

    # 1.1 Without API Key
    r = client.get("/api/make/context")
    assert_test(r.status_code == 401, "GET /api/make/context without API key returns 401")

    # 1.2 With invalid API Key
    r = client.get("/api/make/context", headers={"X-API-Key": "wrong_key"})
    assert_test(r.status_code == 401, "GET /api/make/context with invalid API key returns 401")

    # 1.3 With valid API Key (initial state, no resume uploaded yet)
    r = client.get("/api/make/context", headers=AUTH_HEADER)
    assert_test(r.status_code == 200, "GET /api/make/context with valid key returns 200")
    data = r.json()
    assert_test("active_role" in data, "Response contains active_role")
    assert_test("experience_filter" in data, "Response contains experience_filter")
    assert_test(data["active_role"] == "AI/ML Engineer", "Default active_role is AI/ML Engineer")
    assert_test(data["experience_filter"]["max_years_experience"] == 1, "Default max_years_experience is 1")
    assert_test(data["experience_filter"]["filter_enabled"] is True, "Default filter_enabled is True")

    # -----------------------------------------------------------------------
    # 2. Testing Resume association with Make Context
    # -----------------------------------------------------------------------
    print("\n--- 2. Testing Resume association with Make Context ---")

    # Create dummy PDF bytes
    import io
    import PyPDF2
    writer = PyPDF2.PdfWriter()
    writer.add_blank_page(width=72, height=72)
    pdf_bytes = io.BytesIO()
    writer.write(pdf_bytes)
    pdf_bytes.seek(0)

    # Upload resume for AI/ML Engineer
    upload_resp = client.post(
        "/api/resumes",
        data={"target_role": "AI/ML Engineer"},
        files={"file": ("test_ml_resume.pdf", pdf_bytes, "application/pdf")},
    )
    assert_test(upload_resp.status_code == 200, "Upload resume for AI/ML Engineer returns 200")
    uploaded_resume_id = upload_resp.json()["id"]

    # Verify context now includes resume info
    r = client.get("/api/make/context", headers=AUTH_HEADER)
    data = r.json()
    assert_test(data["resume_id"] == uploaded_resume_id, "Context returns matched resume_id")
    assert_test(data["filename"] == "test_ml_resume.pdf", "Context returns matched filename")
    assert_test("extracted_text" in data, "Context returns extracted_text field")

    # -----------------------------------------------------------------------
    # 3. Experience Filter Enforcement
    # -----------------------------------------------------------------------
    print("\n--- 3. Testing Experience Filter on POST /api/jobs ---")

    # Ensure filter is set to max 1 year
    client.put(
        "/api/settings/experience-filter",
        json={"active_role": "AI/ML Engineer", "max_years_experience": 1, "filter_enabled": True},
    )

    # 3.1 Job requiring 5+ years -> REJECT (422)
    job_senior = {
        "title": "Senior AI Architect",
        "company": "GiantCorp",
        "url": "https://example.com/job/senior-ai",
        "experience": "5+ years",
        "score": 9.0,
        "match_reason": "High tech score but senior role",
    }
    r = client.post("/api/jobs", json=job_senior, headers=AUTH_HEADER)
    assert_test(r.status_code == 422, "Job with '5+ years' rejected when max is 1 (HTTP 422)")

    # 3.2 Job requiring 3-5 years -> REJECT (422)
    job_mid = {
        "title": "Mid Machine Learning Engineer",
        "company": "MidTech",
        "url": "https://example.com/job/mid-ml",
        "experience": "3-5 years",
        "score": 8.0,
    }
    r = client.post("/api/jobs", json=job_mid, headers=AUTH_HEADER)
    assert_test(r.status_code == 422, "Job with '3-5 years' rejected when max is 1 (HTTP 422)")

    # 3.3 Job requiring 2+ years -> REJECT (422)
    job_2plus = {
        "title": "Python Developer II",
        "company": "ScaleUp",
        "url": "https://example.com/job/py-2plus",
        "experience": "2+ years",
        "score": 8.2,
    }
    r = client.post("/api/jobs", json=job_2plus, headers=AUTH_HEADER)
    assert_test(r.status_code == 422, "Job with '2+ years' rejected when max is 1 (HTTP 422)")

    # 3.4 Job for Fresher -> ACCEPT (200)
    job_fresher = {
        "title": "Junior AI/ML Engineer",
        "company": "StartAI",
        "url": "https://example.com/job/junior-ai",
        "experience": "Fresher",
        "score": 8.8,
    }
    r = client.post("/api/jobs", json=job_fresher, headers=AUTH_HEADER)
    assert_test(r.status_code == 200, "Job with 'Fresher' experience accepted (HTTP 200)")

    # 3.5 Job with 0-1 years -> ACCEPT (200)
    job_0_1 = {
        "title": "Associate Data Analyst",
        "company": "DataHub",
        "url": "https://example.com/job/assoc-data",
        "experience": "0-1 years",
        "score": 8.4,
    }
    r = client.post("/api/jobs", json=job_0_1, headers=AUTH_HEADER)
    assert_test(r.status_code == 200, "Job with '0-1 years' experience accepted (HTTP 200)")

    # 3.6 Job with 1 year / 1+ years (min 1 <= max 1) -> ACCEPT (200)
    job_1yr = {
        "title": "Python Developer Entry",
        "company": "WebCorp",
        "url": "https://example.com/job/py-entry",
        "experience": "1 year",
        "score": 8.1,
    }
    r = client.post("/api/jobs", json=job_1yr, headers=AUTH_HEADER)
    assert_test(r.status_code == 200, "Job with '1 year' experience accepted (HTTP 200)")

    # 3.7 Job with missing / unclear experience -> ACCEPT (not inventing a value)
    job_unclear = {
        "title": "AI Engineer (Open Range)",
        "company": "OpenLabs",
        "url": "https://example.com/job/open-ai",
        "experience": "Not Specified",
        "score": 8.5,
    }
    r = client.post("/api/jobs", json=job_unclear, headers=AUTH_HEADER)
    assert_test(r.status_code == 200, "Job with unclear 'Not Specified' experience accepted without inventing value")

    job_none_exp = {
        "title": "Machine Learning Intern",
        "company": "DeepTech",
        "url": "https://example.com/job/ml-intern",
        "experience": None,
        "score": 8.7,
    }
    r = client.post("/api/jobs", json=job_none_exp, headers=AUTH_HEADER)
    assert_test(r.status_code == 200, "Job with None experience accepted")

    # 3.8 When filter_enabled is False -> 5+ years should be ACCEPTED
    client.put(
        "/api/settings/experience-filter",
        json={"active_role": "AI/ML Engineer", "max_years_experience": 1, "filter_enabled": False},
    )
    job_disabled_filter = {
        "title": "Principal Architect",
        "company": "BigFirm",
        "url": "https://example.com/job/principal",
        "experience": "8+ years",
        "score": 9.5,
    }
    r = client.post("/api/jobs", json=job_disabled_filter, headers=AUTH_HEADER)
    assert_test(r.status_code == 200, "When filter_enabled=False, 8+ years job is accepted")

    # Re-enable filter for further tests
    client.put(
        "/api/settings/experience-filter",
        json={"active_role": "AI/ML Engineer", "max_years_experience": 1, "filter_enabled": True},
    )

    # -----------------------------------------------------------------------
    # 4. Duplicate Job Detection
    # -----------------------------------------------------------------------
    print("\n--- 4. Testing Duplicate Job Detection ---")

    # 4.1 Duplicate by exact URL
    dup_url_job = {
        "title": "Junior AI/ML Engineer (New Posting)",
        "company": "StartAI Different Name",
        "url": "https://example.com/job/junior-ai",  # same url as created in 3.4
        "experience": "Fresher",
    }
    r = client.post("/api/jobs", json=dup_url_job, headers=AUTH_HEADER)
    assert_test(r.status_code == 409, "Duplicate job by exact URL rejected (HTTP 409)")

    # 4.2 Duplicate by normalized URL (trailing slash)
    dup_slash_job = {
        "title": "Junior AI/ML Engineer (Slash Posting)",
        "company": "StartAI",
        "url": "https://example.com/job/junior-ai/",
        "experience": "Fresher",
    }
    r = client.post("/api/jobs", json=dup_slash_job, headers=AUTH_HEADER)
    assert_test(r.status_code == 409, "Duplicate job with trailing slash URL rejected (HTTP 409)")

    # 4.3 Fallback duplicate detection by Title + Company (no URL provided)
    job_no_url_1 = {
        "title": "Automation Test Trainee",
        "company": "QualityFirst Labs",
        "url": None,
        "experience": "Fresher",
        "score": 8.0,
    }
    r1 = client.post("/api/jobs", json=job_no_url_1, headers=AUTH_HEADER)
    assert_test(r1.status_code == 200, "First job without URL created successfully")

    # Same title and company (different case & whitespace)
    job_no_url_dup = {
        "title": "  automation test trainee  ",
        "company": "qualityfirst labs",
        "url": "",
        "experience": "Fresher",
        "score": 8.0,
    }
    r2 = client.post("/api/jobs", json=job_no_url_dup, headers=AUTH_HEADER)
    assert_test(r2.status_code == 409, "Duplicate job by Title + Company fallback rejected (HTTP 409)")

    # Different title or company without URL -> accepted
    job_no_url_diff = {
        "title": "Automation Test Engineer II",
        "company": "QualityFirst Labs",
        "url": None,
        "experience": "1 year",
        "score": 8.0,
    }
    r3 = client.post("/api/jobs", json=job_no_url_diff, headers=AUTH_HEADER)
    assert_test(r3.status_code == 200, "Different job without URL accepted (HTTP 200)")

    # -----------------------------------------------------------------------
    # 5. Existing Job CRUD Operations
    # -----------------------------------------------------------------------
    print("\n--- 5. Testing Existing Job CRUD Operations ---")

    # 5.1 GET /api/jobs
    r = client.get("/api/jobs")
    assert_test(r.status_code == 200, "GET /api/jobs returns 200")
    jobs_list = r.json()
    assert_test(len(jobs_list) > 0, f"GET /api/jobs returned {len(jobs_list)} jobs")

    # 5.2 GET /api/jobs/{id}
    first_job_id = jobs_list[0]["id"]
    r = client.get(f"/api/jobs/{first_job_id}")
    assert_test(r.status_code == 200, f"GET /api/jobs/{first_job_id} returns 200")
    assert_test(r.json()["id"] == first_job_id, "Fetched correct job ID")

    # 5.3 PUT /api/jobs/{id} (Status change from Tracker or Job Details)
    r = client.put(f"/api/jobs/{first_job_id}", json={"status": "Applied"})
    assert_test(r.status_code == 200, "PUT /api/jobs/{id} returns 200")
    assert_test(r.json()["status"] == "Applied", "Job status updated to 'Applied'")

    # 5.4 DELETE /api/jobs/{id}
    r = client.delete(f"/api/jobs/{first_job_id}")
    assert_test(r.status_code == 200, "DELETE /api/jobs/{id} returns 200")

    # 5.5 Verify deleted
    r = client.get(f"/api/jobs/{first_job_id}")
    assert_test(r.status_code == 404, "GET deleted job returns 404")

    # -----------------------------------------------------------------------
    # 6. Resume & Settings Endpoints
    # -----------------------------------------------------------------------
    print("\n--- 6. Testing Resume & Settings Endpoints ---")

    # 6.1 List resumes
    r = client.get("/api/resumes")
    assert_test(r.status_code == 200, "GET /api/resumes returns 200")

    # 6.2 Update resume role
    r = client.put(f"/api/resumes/{uploaded_resume_id}/role", json={"target_role": "Python Developer"})
    assert_test(r.status_code == 200, "PUT /api/resumes/{id}/role returns 200")

    # 6.3 Clean up uploaded test resume
    r = client.delete(f"/api/resumes/{uploaded_resume_id}")
    assert_test(r.status_code == 200, "DELETE /api/resumes/{id} returns 200")

    # Summary
    print("\n" + "=" * 70)
    print(f"ALL TESTS COMPLETED: {passed_tests}/{total_tests} PASSED (100%)")
    print("=" * 70)

    # Cleanup temp db
    try:
        os.remove(temp_db_file.name)
    except Exception:
        pass


if __name__ == "__main__":
    run_tests()
