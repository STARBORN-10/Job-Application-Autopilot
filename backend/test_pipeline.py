"""
Comprehensive Offline Unit Test Suite for Pipeline Orchestrator (V2).
Tests deduplication, experience and hard filters, explainable scoring with AI facts (mocked),
the AI cost budget, cover letters, post-commit notifications, session lifecycle, concurrency
protection, fault tolerance and retries. Zero live external API calls are made: only the JSearch
source is enabled (its fetch is mocked) and the AI provider layer is replaced by a fake.
"""

import datetime
import os
import re
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

# Ensure backend directory is in path
sys.path.insert(0, str(Path(__file__).parent))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import models
import schemas
import crud
from services import pipeline, llm
from services.llm import LLMResult
from services.scoring.facts import FACTS_SYSTEM
from services.scoring.profile import PROFILE_SYSTEM
from services.scoring.writer import WRITER_SYSTEM


def create_in_memory_db():
    """Sets up an isolated, in-memory SQLite database for test execution."""
    test_engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )
    TestingSession = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)
    models.Base.metadata.create_all(bind=test_engine)
    return TestingSession


# ---------------------------------------------------------------------------
# Fake AI provider layer: answers by prompt type, records every call
# ---------------------------------------------------------------------------
AI_CALLS = []
PROFILE = {"skills": ["Python", "PyTorch", "scikit-learn", "NLP", "Machine Learning", "SQL", "Docker"],
           "years_experience": 0, "education_level": "bachelor", "roles": [], "project_keywords": [],
           "preferred_roles": ["AI/ML Engineer"]}
FACTS = {
    "Junior Frontend Intern": {"required_skills": ["HTML", "CSS", "Figma"], "level": "intern"},
    "Junior ML Engineer": {"required_skills": ["Python", "PyTorch", "SQL", "machine learning"], "min_years": 0,
                           "level": "junior", "work_mode": "remote"},
}
FAIL_TITLES = set()
AI_DOWN_TITLES = set()


def fake_generate_json(task, prompt, schema=None, system="", max_tokens=700, clients=None):
    if system == PROFILE_SYSTEM:
        AI_CALLS.append("profile")
        data = PROFILE
    elif system == FACTS_SYSTEM:
        title = re.search(r"Title: (.*)", prompt).group(1).strip()
        AI_CALLS.append(f"facts:{title}")
        if title in FAIL_TITLES:
            raise RuntimeError("Simulated unexpected glitch")
        if title in AI_DOWN_TITLES:
            raise llm.LLMUnavailableError("All AI providers failed: gemini: 429; groq: 429")
        data = FACTS.get(title, {"required_skills": ["Python", "machine learning"]})
    elif system == WRITER_SYSTEM:
        AI_CALLS.append("letter")
        data = {"cover_letter": "Dear Hiring Team, I build ML pipelines in Python and PyTorch. " * 3}
    else:
        raise AssertionError("unexpected AI prompt")
    if schema is not None:
        data = schema.model_validate(data).model_dump()
    return LLMResult(data=data, provider="fake", model="fake-model")


def calls(prefix):
    return [c for c in AI_CALLS if c.startswith(prefix)]


def now():
    return datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)


def make_job(title, company, url, location="Remote", description="Python ML role", experience="Fresher", **kw):
    return schemas.JobCreate(title=title, company=company, url=url, location=location, description=description,
                             experience=experience, source="JSearch", posted_date=kw.pop("posted_date", now()), **kw)


def run_all_pipeline_tests():
    print("=" * 70)
    print("RUNNING OFFLINE PIPELINE ORCHESTRATOR TESTS")
    print("=" * 70)

    # V2: the pipeline runs every enabled source. Keep this suite offline and focused on the
    # orchestration logic by enabling only JSearch (whose fetch_jobs is mocked below), and replace
    # the AI provider layer with the fake above.
    patches = [
        patch("services.sources.registry.enabled_map", return_value={"jsearch": True}),
        patch("services.llm.generate_json", side_effect=fake_generate_json),
        patch("services.llm.available_providers", return_value=["fake"]),
    ]
    for p in patches:
        p.start()
    os.environ.setdefault("RAPIDAPI_KEY", "offline-test-key")
    os.environ.pop("LLM_MAX_JOBS_PER_RUN", None)

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
    # Setup Test Database & Resume Context
    # -----------------------------------------------------------------------
    TestingSession = create_in_memory_db()
    db = TestingSession()

    settings = schemas.GeneralSettings(
        active_role="AI/ML Engineer",
        max_years_experience=1,
        filter_enabled=True,
        min_match_score=7.0,
        preferred_locations="Remote, India",
    )
    crud.update_general_settings(db, settings)

    crud.create_resume(
        db=db,
        filename="test_ai_resume.pdf",
        target_role="AI/ML Engineer",
        extracted_text="Python developer with skills in PyTorch, scikit-learn, NLP, SQL and Docker.",
        file_path="/tmp/test_ai_resume.pdf",
        file_size=2048,
    )

    existing_job = schemas.JobCreate(
        title="Existing NLP Specialist",
        company="PreExisting Corp",
        url="https://example.com/job/already-exists",
        location="Bengaluru",
        description="Old listing",
        experience="0-1 years",
        source="JSearch",
    )
    crud.create_job(db, existing_job)

    # -----------------------------------------------------------------------
    # 1. Test: Duplicate Detection before any AI facts
    # -----------------------------------------------------------------------
    print("\n--- 1. Testing Pre-AI Duplicate Detection ---")
    dup = make_job("Existing NLP Specialist", "PreExisting Corp", "https://example.com/job/already-exists/",
                   location="Bengaluru")
    with patch("services.jsearch_service.fetch_jobs", return_value=[dup]):
        AI_CALLS.clear()
        summary = pipeline.run_automation_pipeline(db_session=db)
    assert_test(summary["status"] == "success", "Pipeline executes successfully")
    assert_test(summary["total_fetched"] == 1, "Total fetched count is 1")
    assert_test(summary["duplicates_skipped"] == 1, "Duplicate count is 1")
    assert_test(calls("facts") == [] and calls("letter") == [], "No AI facts or letters for a duplicate (zero token cost)")
    assert_test(summary["saved"] == 0, "Duplicate job was not re-saved")
    known = db.query(models.Job).filter(models.Job.title == "Existing NLP Specialist").first()
    assert_test(known.last_seen is not None and "jsearch" in known.source_names, "Known job gets last_seen + source")
    assert_test(calls("profile") == ["profile"], "Candidate profile extracted once (first run)")

    # -----------------------------------------------------------------------
    # 2. Test: Experience Filter before AI
    # -----------------------------------------------------------------------
    print("\n--- 2. Testing Pre-AI Experience Filter ---")
    senior = make_job("Principal AI Researcher", "BigLab AI", "https://example.com/job/senior-ai",
                      location="Bengaluru", description="Requires deep research experience.", experience="5+ years required")
    with patch("services.jsearch_service.fetch_jobs", return_value=[senior]):
        AI_CALLS.clear()
        summary = pipeline.run_automation_pipeline(db_session=db)
    assert_test(summary["experience_filtered"] == 1, "Experience filter skipped 5+ years job")
    assert_test(calls("facts") == [], "No AI call for an experience-ineligible job")
    assert_test(calls("profile") == [], "Profile served from the cache (resume unchanged)")
    assert_test(summary["saved"] == 0, "Senior job was not saved")

    # -----------------------------------------------------------------------
    # 3. Test: Score Threshold Filtering (< min_match_score)
    # -----------------------------------------------------------------------
    print("\n--- 3. Testing Score Threshold Filter ---")
    low = make_job("Junior Frontend Intern", "WebDesign Studio", "https://example.com/job/frontend-intern",
                   description="Only HTML/CSS design tasks.")
    with patch("services.jsearch_service.fetch_jobs", return_value=[low]), \
         patch("services.notification_service.send_job_alert") as mock_notify:
        AI_CALLS.clear()
        summary = pipeline.run_automation_pipeline(db_session=db)
    detail = summary["details"][0]
    assert_test(summary["ai_evaluated"] == 1 and len(calls("facts")) == 1, "AI facts extracted for the eligible job")
    assert_test(detail["status"] == "score_below_threshold" and detail["score"] < 7.0,
                f"Low-scoring job ({detail['score']}) is below the 7.0 threshold")
    assert_test(summary["saved"] == 0, "Low-scoring job was NOT saved to database")
    assert_test(mock_notify.call_count == 0 and calls("letter") == [], "No alert and no cover letter for it")

    # -----------------------------------------------------------------------
    # 4. Test: Qualifying Job Saved with breakdown, cover letter & Post-Commit Notification
    # -----------------------------------------------------------------------
    print("\n--- 4. Testing Qualifying Job Persistence & Notification ---")
    good = make_job("Junior ML Engineer", "Cognitive Systems", "https://example.com/job/ml-junior-99",
                    description="Develop ML training pipelines in Python with PyTorch and SQL. Machine learning focus.",
                    experience="0-1 years")
    with patch("services.jsearch_service.fetch_jobs", return_value=[good]), \
         patch("services.notification_service.send_job_alert") as mock_notify:
        mock_notify.return_value = {"ok": True, "result": {"message_id": 123}}
        AI_CALLS.clear()
        summary = pipeline.run_automation_pipeline(db_session=db)
    assert_test(summary["saved"] == 1, "Qualifying job successfully saved to DB")
    assert_test(summary["notified"] == 1 and mock_notify.call_count == 1, "Telegram alert sent for saved job")
    assert_test(summary["cover_letters"] == 1, "Cover letter written for the qualifying job")
    rec = db.query(models.Job).filter(models.Job.url == "https://example.com/job/ml-junior-99").first()
    resp = schemas.JobResponse.model_validate(rec)
    assert_test(rec is not None and rec.score == 10.0, f"Stored score is the computed score ({rec.score})")
    assert_test(rec.status == "To Apply" and rec.approval_status == "pending", "Defaults: 'To Apply', approval 'pending'")
    bd = resp.score_breakdown
    assert_test(bd["total"] == rec.score and set(bd["parts"]) == {"skills", "role", "experience", "preferences", "freshness"},
                "Breakdown stored with all five parts and the same total")
    assert_test(bd["matched_skills"] == ["python", "pytorch", "sql", "machine learning"] and bd["missing_skills"] == [],
                "Matched and missing skills recorded")
    assert_test(bd["facts_source"] == "llm" and bd["description_quality"] == "full", "Facts source and quality recorded")
    assert_test("4/4 required skills" in rec.match_reason, "match_reason is generated from the breakdown")
    assert_test(rec.cover_letter.startswith("Dear Hiring Team"), "Cover letter stored")

    # -----------------------------------------------------------------------
    # 5. Test: Concurrency Protection (threading.Lock)
    # -----------------------------------------------------------------------
    print("\n--- 5. Testing Concurrency Protection ---")
    acquired = pipeline._pipeline_lock.acquire(blocking=False)
    assert_test(acquired is True, "Test acquired pipeline lock directly")
    try:
        busy_summary = pipeline.run_automation_pipeline(db_session=db)
        assert_test(busy_summary["status"] == "already_running", "Concurrent run blocked with status 'already_running'")
        assert_test(busy_summary["total_fetched"] == 0, "No duplicate actions executed when busy")
    finally:
        pipeline._pipeline_lock.release()
    assert_test(pipeline._pipeline_lock.locked() is False, "Pipeline lock is clean and unlocked")

    # -----------------------------------------------------------------------
    # 6. Test: Fault Tolerance (Single Job Failure Doesn't Halt Batch)
    # -----------------------------------------------------------------------
    print("\n--- 6. Testing Fault Tolerance Across Batch ---")
    job_bad = make_job("Failing Job Posting", "Buggy Corp", "https://example.com/job/fails")
    job_good = make_job("ML Engineer", "Stable AI Inc", "https://example.com/job/succeeds",
                        description="Machine learning in Python.")
    FAIL_TITLES.add("Failing Job Posting")
    with patch("services.jsearch_service.fetch_jobs", return_value=[job_bad, job_good]), \
         patch("services.notification_service.send_job_alert"):
        summary = pipeline.run_automation_pipeline(db_session=db)
    FAIL_TITLES.clear()
    assert_test(summary["total_fetched"] == 2, "Both jobs fetched in batch")
    assert_test(summary["failed"] == 1, "Single failing job recorded as failed")
    assert_test(summary["saved"] == 1 and summary["notified"] == 1, "The other job is still saved and notified")

    # -----------------------------------------------------------------------
    # 7. Test: Database Session is Always Closed
    # -----------------------------------------------------------------------
    print("\n--- 7. Testing Database Session Cleanup ---")
    mock_session = MagicMock()
    mock_session_factory = MagicMock(return_value=mock_session)
    mock_settings = schemas.GeneralSettings(active_role="AI/ML Engineer")
    mock_resume = MagicMock()
    mock_resume.extracted_text = "Resume text"
    with patch("crud.get_general_settings", return_value=mock_settings), \
         patch("crud.get_active_resume_for_role", return_value=mock_resume), \
         patch("services.jsearch_service.fetch_jobs", side_effect=Exception("Trigger cleanup")):
        pipeline.run_automation_pipeline(session_factory=mock_session_factory)
    assert_test(mock_session.close.call_count == 1, "Session close() called exactly once even after exception")

    # -----------------------------------------------------------------------
    # 8. Test: Database commit failure – Telegram must NOT be called
    # -----------------------------------------------------------------------
    print("\n--- 8. Testing DB commit failure (Telegram should NOT be called)---")
    fail_db = make_job("Failing DB Job", "DBError Corp", "https://example.com/job/db-fail")
    with patch("services.jsearch_service.fetch_jobs", return_value=[fail_db]), \
         patch("crud.create_job", side_effect=Exception("DB commit error")) as mock_create, \
         patch("services.notification_service.send_job_alert") as mock_notify:
        summary = pipeline.run_automation_pipeline(db_session=db)
    assert_test(mock_create.called is True, "Database save was attempted")
    assert_test(summary["failed"] == 1, "Job counted as failed due to DB error")
    assert_test(mock_notify.called is False, "Telegram not invoked when DB commit fails")

    # -----------------------------------------------------------------------
    # 9. Test: Telegram notification failure – job persists, not counted as notified
    # -----------------------------------------------------------------------
    print("\n--- 9. Testing Telegram failure (job should persist, notified count unchanged)---")
    notify_fail = make_job("Notify Fail Job", "NotifyError Inc", "https://example.com/job/notify-fail",
                           description="Machine learning and Python.")
    FACTS["Notify Fail Job"] = {"required_skills": ["Python", "machine learning"]}
    with patch("services.jsearch_service.fetch_jobs", return_value=[notify_fail]), \
         patch("services.notification_service.send_job_alert", side_effect=Exception("Telegram error")) as mock_notify:
        summary = pipeline.run_automation_pipeline(db_session=db)
    assert_test(summary["saved"] == 1, "Job saved even when Telegram fails")
    assert_test(summary["notified"] == 0, "Notified count stays zero after Telegram error")
    assert_test(mock_notify.called is True, "Telegram notification was attempted")
    assert_test(db.query(models.Job).filter(models.Job.url == "https://example.com/job/notify-fail").first() is not None,
                "Job remains in DB after Telegram failure")

    # -----------------------------------------------------------------------
    # 10. Test: Run status tracking (feeds GET /api/automation/status)
    # -----------------------------------------------------------------------
    print("\n--- 10. Testing Run Status Tracking ---")
    status = pipeline.get_pipeline_status()
    assert_test(status["running"] is False, "Status reports not running when idle")
    assert_test(status["last_run"] is not None and status["last_run"]["status"] == "success",
                "Status records the last finished run summary")
    assert_test(status["started_at"] is not None and status["finished_at"] is not None,
                "Status records start and finish timestamps")
    finished_before = status["finished_at"]
    pipeline._pipeline_lock.acquire(blocking=False)
    try:
        assert_test(pipeline.get_pipeline_status()["running"] is True, "Status reports running while lock is held")
        pipeline.run_automation_pipeline(db_session=db)
    finally:
        pipeline._pipeline_lock.release()
    assert_test(pipeline.get_pipeline_status()["finished_at"] == finished_before,
                "Rejected overlapping run does not overwrite the last-run record")
    with patch("services.jsearch_service.fetch_jobs", side_effect=Exception("boom")):
        crashed = pipeline.run_automation_pipeline(db_session=db)
    assert_test(crashed["status"] == "error", "Discovery failure is reported as status 'error'")
    assert_test(pipeline.get_pipeline_status()["last_run"]["status"] == "error", "Failed run is recorded in status")
    stored = crud.get_json_setting(db, pipeline.STATUS_SETTINGS_KEY)
    assert_test(stored["last_run"]["status"] == "error", "Run summary persisted to the database")

    # -----------------------------------------------------------------------
    # 11. Test: Retry with exponential backoff, and AI outage fallback
    # -----------------------------------------------------------------------
    print("\n--- 11. Testing Retry / Backoff / AI fallback ---")
    from services.retry import retry_call
    from services import ai_service, jsearch_service

    counter = {"n": 0}

    def flaky():
        counter["n"] += 1
        if counter["n"] < 3:
            raise ai_service.AIRateLimitError("429")
        return "ok"

    with patch("services.retry.time.sleep") as mock_sleep:
        result = retry_call(flaky, retry_on=(ai_service.AIRateLimitError,), attempts=3, base_delay=1.0)
    assert_test(result == "ok" and counter["n"] == 3, "Transient error retried until success")
    assert_test(mock_sleep.call_count == 2, "Slept between attempts only")
    delays = [c.args[0] for c in mock_sleep.call_args_list]
    assert_test(1.0 <= delays[0] < 1.2 and 2.0 <= delays[1] < 2.4, "Backoff doubles each attempt (with jitter)")
    with patch("services.retry.time.sleep"):
        try:
            retry_call(lambda: (_ for _ in ()).throw(ai_service.AITimeoutError("t")),
                       retry_on=(ai_service.AITimeoutError,), attempts=2, base_delay=0.1)
            raised = False
        except ai_service.AITimeoutError:
            raised = True
    assert_test(raised, "Error re-raised once attempts are exhausted")
    auth_calls = {"n": 0}

    def bad_auth():
        auth_calls["n"] += 1
        raise ai_service.AIAuthError("bad key")

    with patch("services.retry.time.sleep") as mock_sleep:
        try:
            retry_call(bad_auth, retry_on=(ai_service.AITimeoutError,), attempts=3)
        except ai_service.AIAuthError:
            pass
    assert_test(auth_calls["n"] == 1 and mock_sleep.call_count == 0, "Non-transient (auth) error is NOT retried")

    outage = make_job("Retry Eng", "Flaky Corp", "https://example.com/job/retry-1",
                      description="Machine learning engineer: Python, PyTorch, SQL, NLP.")
    AI_DOWN_TITLES.add("Retry Eng")
    with patch("services.jsearch_service.fetch_jobs", return_value=[outage]), \
         patch("services.notification_service.send_job_alert"):
        AI_CALLS.clear()
        summary = pipeline.run_automation_pipeline(db_session=db)
    AI_DOWN_TITLES.clear()
    rec = db.query(models.Job).filter(models.Job.url == "https://example.com/job/retry-1").first()
    assert_test(summary["ai_errors"] == 1 and summary["failed"] == 0, "AI outage is not a job failure")
    assert_test(rec is not None and '"facts_source": "heuristic"' in rec.score_breakdown,
                "Job kept with the keyword (heuristic) score when every AI provider is down")
    assert_test(calls("letter") == [], "No cover letter attempted for a job scored without AI")

    fetch_calls = {"n": 0}

    def flaky_fetch(**kwargs):
        fetch_calls["n"] += 1
        if fetch_calls["n"] == 1:
            raise jsearch_service.JSearchNetworkError("timeout")
        return []

    with patch("services.retry.time.sleep"), \
         patch("services.jsearch_service.fetch_jobs", side_effect=flaky_fetch):
        summary = pipeline.run_automation_pipeline(db_session=db)
    assert_test(fetch_calls["n"] == 2 and summary["status"] == "success", "JSearch fetch retried after network error")

    # -----------------------------------------------------------------------
    # 12. Test: AI cost budget (only the top N by keyword pre-score use AI)
    # -----------------------------------------------------------------------
    print("\n--- 12. Testing AI budget (LLM_MAX_JOBS_PER_RUN) ---")
    batch = [
        make_job("Data Entry Operator", "Clerks Co", "https://example.com/job/b1", description="Typing and filing."),
        make_job("Machine Learning Engineer", "Top AI", "https://example.com/job/b2",
                 description="Python, PyTorch, scikit-learn, NLP, SQL, Docker. Machine learning models."),
        make_job("ML Engineer Intern", "Mid AI", "https://example.com/job/b3", description="Python and NLP."),
    ]
    with patch.dict(os.environ, {"LLM_MAX_JOBS_PER_RUN": "1"}), \
         patch("services.jsearch_service.fetch_jobs", return_value=batch), \
         patch("services.notification_service.send_job_alert"):
        AI_CALLS.clear()
        summary = pipeline.run_automation_pipeline(db_session=db)
    assert_test(calls("facts") == ["facts:Machine Learning Engineer"],
                "Only the best pre-scored job got AI facts")
    assert_test(len(calls("letter")) <= 1 and summary["ai_evaluated"] == 1, "At most one cover letter (AI budget)")
    b3 = db.query(models.Job).filter(models.Job.url == "https://example.com/job/b3").first()
    if b3 is not None:
        assert_test(b3.cover_letter is None and '"facts_source": "heuristic"' in b3.score_breakdown,
                    "Jobs outside the budget keep the keyword score and get no letter")

    with patch("services.llm.available_providers", return_value=[]), \
         patch("services.jsearch_service.fetch_jobs", return_value=[
             make_job("NLP Engineer", "No AI Corp", "https://example.com/job/noai",
                      description="Python, NLP, PyTorch, machine learning, SQL.")]), \
         patch("services.notification_service.send_job_alert"):
        AI_CALLS.clear()
        summary = pipeline.run_automation_pipeline(db_session=db)
    assert_test(AI_CALLS == [] and summary["status"] == "success", "No AI provider: no AI calls, run still succeeds")

    # -----------------------------------------------------------------------
    # 13. Test: Other hard filters (location, blocked company/keyword, job type)
    # -----------------------------------------------------------------------
    print("\n--- 13. Testing hard filters ---")
    crud.update_general_settings(db, settings.model_copy(update={
        "blocked_companies": "Spammy Staffing", "blocked_keywords": "unpaid", "preferred_job_types": "Full-time, Internship"}))
    batch = [
        make_job("ML Engineer", "London AI", "https://example.com/job/f1", location="London, UK"),
        make_job("ML Engineer", "Spammy Staffing Pvt Ltd", "https://example.com/job/f2"),
        make_job("ML Engineer", "Honest AI", "https://example.com/job/f3", description="Unpaid ML role in Python."),
        make_job("ML Engineer", "Contract AI", "https://example.com/job/f4", job_type="Contractor"),
    ]
    with patch("services.jsearch_service.fetch_jobs", return_value=batch):
        AI_CALLS.clear()
        summary = pipeline.run_automation_pipeline(db_session=db)
    assert_test(summary["filtered"] == {"location": 1, "blocked_company": 1, "blocked_keyword": 1, "job_type": 1},
                f"Each hard filter removed its job ({summary['filtered']})")
    assert_test(calls("facts") == [] and summary["saved"] == 0, "Filtered jobs cost no AI calls and are not saved")

    print("\n" + "=" * 70)
    print(f"ALL {total_tests} PIPELINE ORCHESTRATOR TESTS PASSED! ({passed_tests}/{total_tests})")
    print("=" * 70)

    for p in patches:
        p.stop()
    db.close()


if __name__ == "__main__":
    run_all_pipeline_tests()
