"""
Comprehensive end-to-end test suite for Job Application Autopilot.
Covers:
1. Make.com Authentication & Context Endpoint (GET /api/make/context)
2. Experience Filter Enforcement on Job Creation (POST /api/jobs)
3. Duplicate Job Detection (URL primary, Title+Company fallback)
4. Resume Management (Magic byte validation, Upload, Active Selection, Text Extraction, Replacement, Deletion)
5. General Settings Management (GET & PUT /api/settings)
6. Automation Webhook Trigger (POST /api/automation/trigger)
7. Existing Job CRUD Operations (GET, PUT, DELETE)
"""

import os
import sys
import tempfile
import io
from pathlib import Path
from unittest.mock import patch

# Set test environment key BEFORE importing main
TEST_API_KEY = "test_end_to_end_secret_key"
os.environ["MAKE_API_KEY"] = TEST_API_KEY

# Use an isolated temporary SQLite database for tests
temp_db_file = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
temp_db_file.close()
os.environ["DATABASE_URL"] = f"sqlite:///{temp_db_file.name}"

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from fastapi.testclient import TestClient
import PyPDF2
import httpx

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


def create_valid_pdf_bytes():
    """Generates valid PDF binary data starting with %PDF- header."""
    writer = PyPDF2.PdfWriter()
    writer.add_blank_page(width=72, height=72)
    pdf_bytes = io.BytesIO()
    writer.write(pdf_bytes)
    pdf_bytes.seek(0)
    return pdf_bytes.getvalue()


def run_all_tests():
    print("=" * 70)
    print("RUNNING COMPREHENSIVE END-TO-END TEST SUITE")
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
    print("\n--- 1. Testing GET /api/make/context & Authentication ---")
    r = client.get("/api/make/context")
    assert_test(r.status_code == 401, "GET /api/make/context without API key returns 401 Unauthorized")

    r = client.get("/api/make/context", headers={"X-API-Key": "wrong_key"})
    assert_test(r.status_code == 401, "GET /api/make/context with invalid API key returns 401 Unauthorized")

    r = client.get("/api/make/context", headers=AUTH_HEADER)
    assert_test(r.status_code == 200, "GET /api/make/context with valid key returns 200 OK")
    data = r.json()
    assert_test("active_role" in data, "Context response includes active_role")
    assert_test("experience_filter" in data, "Context response includes experience_filter")
    assert_test(data["experience_filter"]["max_years_experience"] == 1, "Default max_years_experience is 1")
    assert_test(data["experience_filter"]["filter_enabled"] is True, "Default filter_enabled is True")

    # -----------------------------------------------------------------------
    # 2. Resume Management: Upload, Validation, Active Selection
    # -----------------------------------------------------------------------
    print("\n--- 2. Testing Resume Management & Security Validation ---")

    # 2.1 File header magic byte validation
    fake_pdf = io.BytesIO(b"This is just plain text, not a real PDF file!")
    r = client.post(
        "/api/resumes",
        data={"target_role": "AI/ML Engineer"},
        files={"file": ("fake.pdf", fake_pdf, "application/pdf")},
    )
    assert_test(r.status_code == 422, "Upload non-PDF text masquerading as .pdf rejected with 422")

    # 2.2 Upload valid first resume for AI/ML Engineer
    valid_pdf_1 = create_valid_pdf_bytes()
    r = client.post(
        "/api/resumes",
        data={"target_role": "AI/ML Engineer"},
        files={"file": ("soham_ai_resume_v1.pdf", io.BytesIO(valid_pdf_1), "application/pdf")},
    )
    assert_test(r.status_code == 200, "Upload valid PDF resume v1 returns 200 OK")
    resume_1 = r.json()
    assert_test(resume_1["is_active"] is True, "First uploaded resume is set to active")

    # 2.3 Upload second resume for same role (AI/ML Engineer)
    valid_pdf_2 = create_valid_pdf_bytes()
    r = client.post(
        "/api/resumes",
        data={"target_role": "AI/ML Engineer"},
        files={"file": ("soham_ai_resume_v2.pdf", io.BytesIO(valid_pdf_2), "application/pdf")},
    )
    assert_test(r.status_code == 200, "Upload second PDF resume v2 returns 200 OK")
    resume_2 = r.json()
    assert_test(resume_2["is_active"] is True, "Newly uploaded resume v2 is now active")

    # Verify resume 1 is now inactive
    r = client.get("/api/resumes")
    all_resumes = r.json()
    r1_found = next(r for r in all_resumes if r["id"] == resume_1["id"])
    assert_test(r1_found["is_active"] is False, "Older resume v1 is now marked inactive")

    # 2.4 Test selecting active resume via PUT /api/resumes/{id}/activate
    r = client.put(f"/api/resumes/{resume_1['id']}/activate")
    assert_test(r.status_code == 200, "Activate resume v1 returns 200 OK")
    activated = r.json()
    assert_test(activated["is_active"] is True, "Resume v1 is now active")

    # Verify context endpoint returns resume 1
    r = client.get("/api/make/context", headers=AUTH_HEADER)
    assert_test(r.json()["resume_id"] == resume_1["id"], "Make context reflects newly activated resume")

    # 2.5 Text extraction retrieval endpoint
    r = client.get(f"/api/resumes/{resume_1['id']}/text")
    assert_test(r.status_code == 200, "GET /api/resumes/{id}/text returns 200 OK")
    assert_test("extracted_text" in r.json(), "Extracted text payload returned")

    # 2.6 Replace resume file with validation
    valid_pdf_replace = create_valid_pdf_bytes()
    r = client.put(
        f"/api/resumes/{resume_2['id']}/replace",
        files={"file": ("soham_ai_resume_v2_updated.pdf", io.BytesIO(valid_pdf_replace), "application/pdf")},
    )
    assert_test(r.status_code == 200, "Replace resume file returns 200 OK")

    # -----------------------------------------------------------------------
    # 3. Experience Filter Enforcement on POST /api/jobs
    # -----------------------------------------------------------------------
    print("\n--- 3. Testing Experience Filter on POST /api/jobs ---")

    # Ensure max 1 year experience filter
    client.put(
        "/api/settings/experience-filter",
        json={"active_role": "AI/ML Engineer", "max_years_experience": 1, "filter_enabled": True},
    )

    # 3.1 5+ years -> REJECT (422)
    r = client.post("/api/jobs", json={
        "title": "Senior AI Architect",
        "company": "EnterpriseAI",
        "url": "https://example.com/job/senior-ai-1",
        "experience": "5+ years",
        "score": 9.2,
    }, headers=AUTH_HEADER)
    assert_test(r.status_code == 422, "5+ years job rejected by experience filter (HTTP 422)")

    # 3.2 2-4 years -> REJECT (422)
    r = client.post("/api/jobs", json={
        "title": "ML Engineer",
        "company": "MidCorp",
        "url": "https://example.com/job/ml-2-4",
        "experience": "2-4 years",
        "score": 8.5,
    }, headers=AUTH_HEADER)
    assert_test(r.status_code == 422, "2-4 years job rejected by experience filter (HTTP 422)")

    # 3.3 Fresher -> ACCEPT (200)
    r = client.post("/api/jobs", json={
        "title": "Junior AI/ML Engineer",
        "company": "InnovateLabs",
        "url": "https://example.com/job/fresher-ai-1",
        "experience": "Fresher",
        "score": 8.7,
        "match_reason": "Excellent match for Python and ML basics",
    }, headers=AUTH_HEADER)
    assert_test(r.status_code == 200, "Fresher job accepted (HTTP 200)")

    # 3.4 0-1 years -> ACCEPT (200)
    r = client.post("/api/jobs", json={
        "title": "Data Analyst Intern",
        "company": "AnalyticsCorp",
        "url": "https://example.com/job/da-intern-1",
        "experience": "0-1 years",
        "score": 8.2,
    }, headers=AUTH_HEADER)
    assert_test(r.status_code == 200, "0-1 years job accepted (HTTP 200)")

    # 3.5 Missing / Unclear experience ("Not Specified") -> ACCEPT (not invented)
    r = client.post("/api/jobs", json={
        "title": "Junior Python Developer",
        "company": "CloudWave",
        "url": "https://example.com/job/py-unclear",
        "experience": "Not Specified",
        "score": 8.0,
    }, headers=AUTH_HEADER)
    assert_test(r.status_code == 200, "Unclear experience job accepted without inventing value (HTTP 200)")

    # 3.6 When filter_enabled=False -> 5+ years is accepted
    client.put(
        "/api/settings/experience-filter",
        json={"active_role": "AI/ML Engineer", "max_years_experience": 1, "filter_enabled": False},
    )
    r = client.post("/api/jobs", json={
        "title": "Lead Research Engineer",
        "company": "GlobalAI",
        "url": "https://example.com/job/lead-ai",
        "experience": "6+ years",
        "score": 9.5,
    }, headers=AUTH_HEADER)
    assert_test(r.status_code == 200, "When filter is disabled, 6+ years job accepted (HTTP 200)")

    # Re-enable filter
    client.put(
        "/api/settings/experience-filter",
        json={"active_role": "AI/ML Engineer", "max_years_experience": 1, "filter_enabled": True},
    )

    # -----------------------------------------------------------------------
    # 4. Duplicate Job Detection
    # -----------------------------------------------------------------------
    print("\n--- 4. Testing Duplicate Job Detection ---")

    # 4.1 Exact URL duplicate
    r = client.post("/api/jobs", json={
        "title": "Junior AI/ML Engineer (Duplicate)",
        "company": "InnovateLabs",
        "url": "https://example.com/job/fresher-ai-1",
        "experience": "Fresher",
    }, headers=AUTH_HEADER)
    assert_test(r.status_code == 409, "Exact URL duplicate rejected (HTTP 409)")

    # 4.2 Trailing slash URL duplicate
    r = client.post("/api/jobs", json={
        "title": "Junior AI/ML Engineer (Slash)",
        "company": "InnovateLabs",
        "url": "https://example.com/job/fresher-ai-1/",
        "experience": "Fresher",
    }, headers=AUTH_HEADER)
    assert_test(r.status_code == 409, "Trailing slash URL duplicate rejected (HTTP 409)")

    # 4.3 Fallback match by Title + Company (no URL provided)
    r1 = client.post("/api/jobs", json={
        "title": "Backend Intern",
        "company": "PySystems",
        "url": None,
        "experience": "Fresher",
    }, headers=AUTH_HEADER)
    assert_test(r1.status_code == 200, "First job without URL created (HTTP 200)")

    # Duplicate without URL (case-insensitive & whitespace trimmed)
    r2 = client.post("/api/jobs", json={
        "title": "  backend intern  ",
        "company": "pysystems",
        "url": "",
        "experience": "Fresher",
    }, headers=AUTH_HEADER)
    assert_test(r2.status_code == 409, "Title + Company fallback duplicate rejected (HTTP 409)")

    # -----------------------------------------------------------------------
    # 5. General Settings Management
    # -----------------------------------------------------------------------
    print("\n--- 5. Testing General Settings Endpoints ---")
    r = client.get("/api/settings")
    assert_test(r.status_code == 200, "GET /api/settings returns 200 OK")
    curr_settings = r.json()
    assert_test("target_roles" in curr_settings, "Settings include target_roles")
    assert_test("make_webhook_url" in curr_settings, "Settings include make_webhook_url")

    # Update general settings
    new_settings = {
        "target_roles": "AI/ML Engineer, Data Analyst, Backend Developer",
        "preferred_locations": "Remote, India",
        "min_match_score": 7.5,
        "make_webhook_url": "https://hook.eu2.make.com/mock-webhook-token",
        "active_role": "Data Analyst",
        "max_years_experience": 2,
        "filter_enabled": True,
    }
    r = client.put("/api/settings", json=new_settings)
    assert_test(r.status_code == 200, "PUT /api/settings returns 200 OK")
    updated_data = r.json()
    assert_test(updated_data["active_role"] == "Data Analyst", "Updated active_role persisted")
    assert_test(updated_data["min_match_score"] == 7.5, "Updated min_match_score persisted")

    # Verify experience filter synced
    r = client.get("/api/settings/experience-filter")
    assert_test(r.json()["active_role"] == "Data Analyst", "Experience filter synced with general settings")

    # -----------------------------------------------------------------------
    # 6. Automation Webhook Trigger Endpoint
    # -----------------------------------------------------------------------
    print("\n--- 6. Testing Automation Webhook Trigger ---")

    # 6.1 Without webhook URL configured
    client.put("/api/settings", json={**new_settings, "make_webhook_url": ""})
    r = client.post("/api/automation/trigger")
    assert_test(r.status_code == 400, "Trigger without webhook URL returns 400 Bad Request")

    # 6.2 With webhook URL configured (mocked external HTTP call)
    client.put("/api/settings", json={**new_settings, "make_webhook_url": "https://hook.eu2.make.com/mock-test"})
    with patch("httpx.post") as mock_post:
        mock_response = httpx.Response(status_code=200, text="Accepted")
        mock_post.return_value = mock_response

        r = client.post("/api/automation/trigger")
        assert_test(r.status_code == 200, "Trigger with configured webhook returns 200 OK")
        assert_test(r.json()["status"] == "success", "Response status is 'success'")
        mock_post.assert_called_once()

    # -----------------------------------------------------------------------
    # 7. Job CRUD & Lifecycle Operations
    # -----------------------------------------------------------------------
    print("\n--- 7. Testing Job CRUD & Lifecycle Operations ---")

    # 7.1 GET /api/jobs
    r = client.get("/api/jobs")
    assert_test(r.status_code == 200, "GET /api/jobs returns 200 OK")
    jobs = r.json()
    assert_test(len(jobs) >= 2, f"Returned {len(jobs)} stored jobs")

    # 7.2 GET /api/jobs/{id}
    job_id = jobs[0]["id"]
    r = client.get(f"/api/jobs/{job_id}")
    assert_test(r.status_code == 200, f"GET /api/jobs/{job_id} returns 200 OK")

    # 7.3 PUT /api/jobs/{id}
    r = client.put(f"/api/jobs/{job_id}", json={"status": "Interview"})
    assert_test(r.status_code == 200, "PUT /api/jobs/{id} status updated to 'Interview'")
    assert_test(r.json()["status"] == "Interview", "Updated status verified")

    # 7.4 DELETE /api/jobs/{id}
    r = client.delete(f"/api/jobs/{job_id}")
    assert_test(r.status_code == 200, "DELETE /api/jobs/{id} returns 200 OK")
    r = client.get(f"/api/jobs/{job_id}")
    assert_test(r.status_code == 404, "Deleted job returns 404 Not Found")

    # Clean up uploaded test resumes
    client.delete(f"/api/resumes/{resume_1['id']}")
    client.delete(f"/api/resumes/{resume_2['id']}")

    print("\n" + "=" * 70)
    print(f"ALL TESTS COMPLETED: {passed_tests}/{total_tests} PASSED (100%)")
    print("=" * 70)

    # Clean up temp database
    try:
        os.remove(temp_db_file.name)
    except Exception:
        pass


if __name__ == "__main__":
    run_all_tests()
