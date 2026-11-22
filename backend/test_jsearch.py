"""
Offline Unit Test Suite for JSearch Service.
Tests normalization, query building, error handling, and mock API execution.
No live API calls are made.
"""

import os
os.environ["AUTH_ENABLED"] = "false"   # this suite tests the single-user mode (see test_auth.py for accounts)
import sys
import json
from pathlib import Path
import httpx

# Ensure backend directory is in path
sys.path.insert(0, str(Path(__file__).parent))

from services.jsearch_service import (
    build_search_query,
    extract_location,
    extract_experience_text,
    normalize_jsearch_job,
    fetch_jobs,
    JSearchError,
    JSearchConfigError,
    JSearchAuthError,
    JSearchRateLimitError,
    JSearchNetworkError,
)
from schemas import JobCreate


MOCK_JSEARCH_RESPONSE = {
    "status": "OK",
    "request_id": "test-req-123",
    "parameters": {"query": "AI/ML Engineer in India", "page": 1, "num_pages": 1},
    "data": [
        {
            "job_id": "job-1",
            "job_title": "Junior Machine Learning Engineer",
            "employer_name": "Acme AI Corp",
            "job_apply_link": "https://example.com/apply/1",
            "job_description": "We are seeking a junior ML engineer proficient in Python and PyTorch.",
            "job_city": "Bengaluru",
            "job_state": "Karnataka",
            "job_country": "India",
            "job_is_remote": False,
            "job_employment_type": "FULLTIME",
            "job_required_experience": {
                "no_experience_required": False,
                "required_experience_in_months": 12,
            },
        },
        {
            "job_id": "job-2",
            "job_title": "AI Research Intern",
            "employer_name": "DeepTech Labs",
            "job_google_link": "https://example.com/google/2",
            "job_description": "Internship opportunity for aspiring AI practitioners.",
            "job_city": None,
            "job_state": None,
            "job_country": None,
            "job_is_remote": True,
            "job_employment_type": "INTERN",
            "job_required_experience": {
                "no_experience_required": True,
            },
        },
        {
            # Invalid item: missing title
            "job_id": "job-3-invalid",
            "job_title": None,
            "employer_name": "NoTitle Inc",
            "job_description": "Missing title posting",
        },
        {
            # Invalid item: missing company
            "job_id": "job-4-invalid",
            "job_title": "Data Scientist",
            "employer_name": "",
            "job_description": "Missing employer",
        },
        {
            "job_id": "job-5",
            "job_title": "Python Developer",
            "employer_name": "FinTech Systems",
            "job_apply_link": "https://example.com/apply/5",
            "job_description": "Backend services developer.",
            "job_city": "Mumbai",
            "job_state": "MH",
            "job_country": "IN",
            "job_is_remote": True,
            "job_employment_type": "CONTRACTOR",
            "job_highlights": {
                "Qualifications": ["Must have 2+ years experience in FastAPI and SQL"]
            },
        },
    ],
}


def run_all_jsearch_tests():
    print("=" * 70)
    print("RUNNING OFFLINE JSEARCH SERVICE UNIT TESTS (MOCKED)")
    print("=" * 70)

    total_tests = 0
    passed_tests = 0

    def assert_test(condition: bool, test_name: str):
        nonlocal total_tests, passed_tests
        total_tests += 1
        if condition:
            passed_tests += 1
            print(f"  [PASS] {test_name}")
        else:
            print(f"  [FAIL] {test_name}")
            raise AssertionError(f"Test failed: {test_name}")

    # -----------------------------------------------------------------------
    # 1. Query Builder Tests
    # -----------------------------------------------------------------------
    print("\n--- 1. Testing build_search_query ---")
    q1 = build_search_query("AI/ML Engineer")
    assert_test(q1 == "AI/ML Engineer", "Role only produces clean query")

    q2 = build_search_query("AI/ML Engineer", "India")
    assert_test(q2 == "AI/ML Engineer in India", "Role with single location")

    q3 = build_search_query("Python Developer", "Remote, India, Hybrid")
    assert_test(q3 == "Python Developer in India remote", "Role with Remote + India combines correctly")

    q4 = build_search_query("Data Analyst", "Remote")
    assert_test(q4 == "Data Analyst remote", "Role with Remote only")

    # -----------------------------------------------------------------------
    # 2. Extract Location Tests
    # -----------------------------------------------------------------------
    print("\n--- 2. Testing extract_location ---")
    loc1 = extract_location({"job_city": "Bengaluru", "job_state": "Karnataka", "job_country": "IN"})
    assert_test(loc1 == "Bengaluru, Karnataka, IN", "Standard city/state/country location")

    loc2 = extract_location({"job_city": "Pune", "job_country": "IN", "job_is_remote": True})
    assert_test(loc2 == "Pune, IN (Remote)", "Remote flag appends to location")

    loc3 = extract_location({"job_is_remote": True})
    assert_test(loc3 == "Remote", "Pure remote defaults to 'Remote'")

    loc4 = extract_location({})
    assert_test(loc4 == "Not Specified", "Empty location defaults to 'Not Specified'")

    # -----------------------------------------------------------------------
    # 3. Extract Experience Tests
    # -----------------------------------------------------------------------
    print("\n--- 3. Testing extract_experience_text ---")
    exp1 = extract_experience_text({"job_required_experience": {"no_experience_required": True}})
    assert_test(exp1 == "Fresher", "no_experience_required resolves to 'Fresher'")

    exp2 = extract_experience_text({"job_required_experience": {"required_experience_in_months": 24}})
    assert_test(exp2 == "2 years", "24 months resolves to '2 years'")

    exp3 = extract_experience_text({"job_required_experience": {"required_experience_in_months": 6}})
    assert_test(exp3 == "6 months", "6 months resolves to '6 months'")

    exp4 = extract_experience_text({
        "job_highlights": {"Qualifications": ["Requires at least 3 years experience with Python"]}
    })
    assert_test(exp4 == "3 years", "Regex fallback extracts experience from qualifications")

    exp5 = extract_experience_text({})
    assert_test(exp5 is None, "Missing experience returns None without inventing values")

    # -----------------------------------------------------------------------
    # 4. Normalization Tests
    # -----------------------------------------------------------------------
    print("\n--- 4. Testing normalize_jsearch_job ---")
    job1 = normalize_jsearch_job(MOCK_JSEARCH_RESPONSE["data"][0])
    assert_test(isinstance(job1, JobCreate), "Valid job normalizes to JobCreate instance")
    assert_test(job1.title == "Junior Machine Learning Engineer", "Title correctly mapped")
    assert_test(job1.company == "Acme AI Corp", "Company correctly mapped")
    assert_test(job1.url == "https://example.com/apply/1", "Apply link correctly mapped")
    assert_test(job1.location == "Bengaluru, Karnataka, India", "Location correctly mapped")
    assert_test(job1.experience == "1 year", "Experience correctly mapped from 12 months")
    assert_test(job1.source == "JSearch", "Source set to 'JSearch'")
    assert_test(job1.status == "To Apply", "Status defaults to 'To Apply'")
    assert_test(job1.score is None, "Score is None (deferred to AI evaluation)")

    # Malformed / invalid items
    job_invalid_title = normalize_jsearch_job(MOCK_JSEARCH_RESPONSE["data"][2])
    assert_test(job_invalid_title is None, "Item with missing job_title returns None")

    job_invalid_company = normalize_jsearch_job(MOCK_JSEARCH_RESPONSE["data"][3])
    assert_test(job_invalid_company is None, "Item with empty employer_name returns None")

    job_invalid_type = normalize_jsearch_job("not a dict")
    assert_test(job_invalid_type is None, "Non-dict item returns None safely")

    # -----------------------------------------------------------------------
    # 5. Offline Mock Transport Fetch Tests
    # -----------------------------------------------------------------------
    print("\n--- 5. Testing fetch_jobs with MockTransport ---")
    os.environ["RAPIDAPI_KEY"] = "mock_test_key"

    # 5.1 Success mock response
    def mock_handler_200(request: httpx.Request) -> httpx.Response:
        assert request.headers.get("X-RapidAPI-Key") == "mock_test_key"
        assert request.headers.get("X-RapidAPI-Host") == "jsearch.p.rapidapi.com"
        return httpx.Response(200, json=MOCK_JSEARCH_RESPONSE)

    mock_client_200 = httpx.Client(transport=httpx.MockTransport(mock_handler_200))
    jobs = fetch_jobs("AI/ML Engineer", "India", client=mock_client_200)
    assert_test(len(jobs) == 3, "fetch_jobs filters 2 invalid items and returns 3 valid JobCreate objects")

    # 5.2 HTTP 401 Unauthorized
    def mock_handler_401(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text="Unauthorized: Invalid RapidAPI key")

    mock_client_401 = httpx.Client(transport=httpx.MockTransport(mock_handler_401))
    try:
        fetch_jobs("AI/ML Engineer", client=mock_client_401)
        assert_test(False, "HTTP 401 should raise JSearchAuthError")
    except JSearchAuthError:
        assert_test(True, "HTTP 401 raises JSearchAuthError cleanly")

    # 5.3 HTTP 429 Rate Limit
    def mock_handler_429(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, text="Rate limit exceeded")

    mock_client_429 = httpx.Client(transport=httpx.MockTransport(mock_handler_429))
    try:
        fetch_jobs("AI/ML Engineer", client=mock_client_429)
        assert_test(False, "HTTP 429 should raise JSearchRateLimitError")
    except JSearchRateLimitError:
        assert_test(True, "HTTP 429 raises JSearchRateLimitError cleanly")

    # 5.4 Network Timeout
    def mock_handler_timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("Read timeout")

    mock_client_timeout = httpx.Client(transport=httpx.MockTransport(mock_handler_timeout))
    try:
        fetch_jobs("AI/ML Engineer", client=mock_client_timeout)
        assert_test(False, "Timeout should raise JSearchNetworkError")
    except JSearchNetworkError:
        assert_test(True, "Timeout raises JSearchNetworkError cleanly")

    # 5.5 Missing RAPIDAPI_KEY check
    del os.environ["RAPIDAPI_KEY"]
    if "JSEARCH_API_KEY" in os.environ:
        del os.environ["JSEARCH_API_KEY"]

    try:
        fetch_jobs("AI/ML Engineer")
        assert_test(False, "Missing API key should raise JSearchConfigError")
    except JSearchConfigError:
        assert_test(True, "Missing API key raises JSearchConfigError without leaking credentials")

    # -----------------------------------------------------------------------
    # 6. /search-v2 API format, country targeting, experience fallback
    # -----------------------------------------------------------------------
    print("\n--- 6. Testing /search-v2 response format ---")
    from services import jsearch_service as _js
    os.environ["RAPIDAPI_KEY"] = "mock_test_key"  # an earlier test removes it on purpose
    seen = {}

    def v2_handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = request.url
        return httpx.Response(200, json={
            "status": "OK",
            "data": {"jobs": [
                {"job_title": "Python Developer", "employer_name": "Acme", "job_city": "Pune", "job_country": "IN",
                 "job_apply_link": "https://acme.io/apply/1",
                 "job_description": "We need 3+ years of experience in Python and SQL."},
                {"job_title": "Intern", "employer_name": "Beta", "job_description": "Great learning opportunity."},
            ], "cursor": "abc"},
        })

    v2_jobs = fetch_jobs("Python Developer", "India, Remote", client=httpx.Client(transport=httpx.MockTransport(v2_handler)))
    assert_test(_js.DEFAULT_API_URL.endswith("/search-v2"), "Default endpoint is /search-v2")
    assert_test(seen["url"].path == "/search-v2", "Request is sent to /search-v2")
    assert_test(len(v2_jobs) == 2, "Parses jobs nested under data.jobs")
    assert_test(seen["url"].params.get("country") == "in", "Sends country=in for an India search")
    assert_test(v2_jobs[0].experience == "3+ years", "Experience extracted from description when API omits it")
    assert_test(v2_jobs[1].experience is None, "No experience phrase -> None (not invented)")
    assert_test(_js.infer_country_code("Remote, Bangalore") is None, "Unknown location -> no country override")
    assert_test(_js.infer_country_code("Remote, UK") == "gb", "UK maps to gb")

    print("\n" + "=" * 70)
    print(f"ALL {total_tests} JSEARCH OFFLINE TESTS PASSED SUCCESSFULLY! ({passed_tests}/{total_tests})")
    print("=" * 70)


if __name__ == "__main__":
    run_all_jsearch_tests()

