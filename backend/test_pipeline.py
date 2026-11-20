"""
Comprehensive Offline Unit Test Suite for Pipeline Orchestrator.
Tests deduplication, experience filtering, Gemini scoring, post-commit notifications,
session lifecycle, concurrency protection, and fault tolerance.
Zero live external API calls are made.
"""

import sys
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

# Ensure backend directory is in path
sys.path.insert(0, str(Path(__file__).parent))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import models
import schemas
import crud
from services import pipeline
from services.ai_service import AIEvaluationResult


def create_in_memory_db():
    """Sets up an isolated, in-memory SQLite database for test execution."""
    test_engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )
    TestingSession = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)
    models.Base.metadata.create_all(bind=test_engine)
    return TestingSession


def run_all_pipeline_tests():
    print("=" * 70)
    print("RUNNING OFFLINE PIPELINE ORCHESTRATOR TESTS")
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
    # Setup Test Database & Resume Context
    # -----------------------------------------------------------------------
    TestingSession = create_in_memory_db()
    db = TestingSession()

    # Seed general settings (active_role="AI/ML Engineer", max_years_experience=1, min_match_score=7.0)
    settings = schemas.GeneralSettings(
        active_role="AI/ML Engineer",
        max_years_experience=1,
        filter_enabled=True,
        min_match_score=7.0,
        preferred_locations="Remote, India",
    )
    crud.update_general_settings(db, settings)

    # Seed active resume
    crud.create_resume(
        db=db,
        filename="test_ai_resume.pdf",
        target_role="AI/ML Engineer",
        extracted_text="Experienced Python developer with skills in PyTorch, scikit-learn, and NLP systems.",
        file_path="/tmp/test_ai_resume.pdf",
        file_size=2048,
    )

    # Pre-seed an existing job to test duplicate skipping
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
    # 1. Test: Pre-Gemini Duplicate Detection
    # -----------------------------------------------------------------------
    print("\n--- 1. Testing Pre-Gemini Duplicate Detection ---")
    mock_duplicate_job = schemas.JobCreate(
        title="Existing NLP Specialist",
        company="PreExisting Corp",
        url="https://example.com/job/already-exists/", # trailing slash variation
        location="Bengaluru",
        description="Duplicate posting",
        experience="0-1 years",
        source="JSearch",
    )

    with patch("services.jsearch_service.fetch_jobs") as mock_fetch, \
         patch("services.ai_service.evaluate_job") as mock_eval:

        mock_fetch.return_value = [mock_duplicate_job]

        summary = pipeline.run_automation_pipeline(db_session=db)

        assert_test(summary["status"] == "success", "Pipeline executes successfully")
        assert_test(summary["total_fetched"] == 1, "Total fetched count is 1")
        assert_test(summary["duplicates_skipped"] == 1, "Duplicate count is 1")
        assert_test(mock_eval.call_count == 0, "Gemini was NOT called for duplicate job (zero token cost)")
        assert_test(summary["saved"] == 0, "Duplicate job was not re-saved")

    # -----------------------------------------------------------------------
    # 2. Test: Pre-Gemini Experience Filter
    # -----------------------------------------------------------------------
    print("\n--- 2. Testing Pre-Gemini Experience Filter ---")
    mock_senior_job = schemas.JobCreate(
        title="Principal AI Researcher",
        company="BigLab AI",
        url="https://example.com/job/senior-ai",
        location="Bengaluru",
        description="Requires deep research experience.",
        experience="5+ years required",
        source="JSearch",
    )

    with patch("services.jsearch_service.fetch_jobs") as mock_fetch, \
         patch("services.ai_service.evaluate_job") as mock_eval:

        mock_fetch.return_value = [mock_senior_job]

        summary = pipeline.run_automation_pipeline(db_session=db)

        assert_test(summary["experience_filtered"] == 1, "Experience filter skipped 5+ years job")
        assert_test(mock_eval.call_count == 0, "Gemini was NOT called for experience-ineligible job")
        assert_test(summary["saved"] == 0, "Senior job was not saved")

    # -----------------------------------------------------------------------
    # 3. Test: Score Threshold Filtering (< min_match_score)
    # -----------------------------------------------------------------------
    print("\n--- 3. Testing Score Threshold Filter ---")
    mock_low_score_job = schemas.JobCreate(
        title="Junior Frontend Intern",
        company="WebDesign Studio",
        url="https://example.com/job/frontend-intern",
        location="Remote",
        description="Only HTML/CSS design tasks.",
        experience="Fresher",
        source="JSearch",
    )

    with patch("services.jsearch_service.fetch_jobs") as mock_fetch, \
         patch("services.ai_service.evaluate_job") as mock_eval, \
         patch("services.notification_service.send_job_alert") as mock_notify:

        mock_fetch.return_value = [mock_low_score_job]
        mock_eval.return_value = AIEvaluationResult(
            score=5.5, # Below 7.0 threshold
            match_reason="Role is frontend-only, poor fit for AI/ML Engineer profile.",
            cover_letter="Cover letter...",
        )

        summary = pipeline.run_automation_pipeline(db_session=db)

        assert_test(summary["ai_evaluated"] == 1, "Gemini evaluated the eligible job")
        assert_test(mock_eval.call_count == 1, "AI evaluation called once")
        assert_test(summary["saved"] == 0, "Low-scoring job (5.5 < 7.0) was NOT saved to database")
        assert_test(mock_notify.call_count == 0, "Telegram was NOT called for low-scoring job")

    # -----------------------------------------------------------------------
    # 4. Test: Qualifying Job Saved & Post-Commit Telegram Notification
    # -----------------------------------------------------------------------
    print("\n--- 4. Testing Qualifying Job Persistence & Notification ---")
    mock_qualifying_job = schemas.JobCreate(
        title="Junior ML Engineer",
        company="Cognitive Systems",
        url="https://example.com/job/ml-junior-99",
        location="Remote",
        description="Develop ML training pipelines in Python.",
        experience="0-1 years",
        source="JSearch",
    )

    with patch("services.jsearch_service.fetch_jobs") as mock_fetch, \
         patch("services.ai_service.evaluate_job") as mock_eval, \
         patch("services.notification_service.send_job_alert") as mock_notify:

        mock_fetch.return_value = [mock_qualifying_job]
        mock_eval.return_value = AIEvaluationResult(
            score=8.8, # Qualifies (> 7.0)
            match_reason="Strong Python and ML pipeline match.",
            cover_letter="Dear Cognitive Systems Hiring Team...",
        )
        mock_notify.return_value = {"ok": True, "result": {"message_id": 123}}

        summary = pipeline.run_automation_pipeline(db_session=db)

        assert_test(summary["saved"] == 1, "Qualifying job successfully saved to DB")
        assert_test(summary["notified"] == 1, "Telegram alert sent for saved job")
        assert_test(mock_notify.call_count == 1, "send_job_alert invoked once")

        # Verify job is persisted in database
        saved_db_record = db.query(models.Job).filter(models.Job.url == "https://example.com/job/ml-junior-99").first()
        assert_test(saved_db_record is not None, "Job record exists in database table")
        assert_test(saved_db_record.score == 8.8, "Stored score matches evaluation")
        assert_test(saved_db_record.status == "To Apply", "Stored status defaults to 'To Apply'")

    # -----------------------------------------------------------------------
    # 5. Test: Concurrency Protection (threading.Lock)
    # -----------------------------------------------------------------------
    print("\n--- 5. Testing Concurrency Protection ---")
    # Simulate an active pipeline run holding the lock
    acquired = pipeline._pipeline_lock.acquire(blocking=False)
    assert_test(acquired is True, "Test acquired pipeline lock directly")

    try:
        # A second run should be rejected immediately
        busy_summary = pipeline.run_automation_pipeline(db_session=db)
        assert_test(busy_summary["status"] == "already_running", "Concurrent run blocked with status 'already_running'")
        assert_test(busy_summary["total_fetched"] == 0, "No duplicate actions executed when busy")
    finally:
        pipeline._pipeline_lock.release()

    # Verify lock is released and pipeline runs normally again
    assert_test(pipeline._pipeline_lock.locked() is False, "Pipeline lock is clean and unlocked")

    # -----------------------------------------------------------------------
    # 6. Test: Fault Tolerance (Single Job Failure Doesn't Halt Batch)
    # -----------------------------------------------------------------------
    print("\n--- 6. Testing Fault Tolerance Across Batch ---")
    job_bad = schemas.JobCreate(
        title="Failing Job Posting",
        company="Buggy Corp",
        url="https://example.com/job/fails",
        location="Remote",
        description="Fails during AI evaluation",
        experience="Fresher",
        source="JSearch",
    )
    job_good = schemas.JobCreate(
        title="AI Automation Developer",
        company="Stable AI Inc",
        url="https://example.com/job/succeeds",
        location="Remote",
        description="Good job",
        experience="Fresher",
        source="JSearch",
    )

    with patch("services.jsearch_service.fetch_jobs") as mock_fetch, \
         patch("services.ai_service.evaluate_job") as mock_eval, \
         patch("services.notification_service.send_job_alert") as mock_notify:

        mock_fetch.return_value = [job_bad, job_good]

        # Job 1 raises an unexpected exception; Job 2 succeeds
        mock_eval.side_effect = [
            RuntimeError("Simulated LLM network glitch"),
            AIEvaluationResult(score=9.1, match_reason="Great fit", cover_letter="Letter..."),
        ]

        summary = pipeline.run_automation_pipeline(db_session=db)

        assert_test(summary["total_fetched"] == 2, "Both jobs fetched in batch")
        assert_test(summary["failed"] == 1, "Single failing job recorded as failed")
        assert_test(summary["saved"] == 1, "Subsequent valid job processed and saved successfully")
        assert_test(summary["notified"] == 1, "Subsequent valid job notified successfully")

    # -----------------------------------------------------------------------
    # 7. Test: Database Session is Always Closed
    # -----------------------------------------------------------------------
    print("\n--- 7. Testing Database Session Cleanup ---")
    mock_session = MagicMock()
    mock_session_factory = MagicMock(return_value=mock_session)

    # Mock settings and resume query on the mock session
    mock_settings = schemas.GeneralSettings(active_role="AI/ML Engineer")
    mock_resume = MagicMock()
    mock_resume.extracted_text = "Resume text"

    with patch("crud.get_general_settings", return_value=mock_settings), \
         patch("crud.get_active_resume_for_role", return_value=mock_resume), \
         patch("services.jsearch_service.fetch_jobs", side_effect=Exception("Trigger cleanup")):

        summary = pipeline.run_automation_pipeline(session_factory=mock_session_factory)
        assert_test(mock_session.close.call_count == 1, "Session close() called exactly once even after exception")

   
    # -----------------------------------------------------------------------
    # 8. Test: Database commit failure – Telegram must NOT be called
    # -----------------------------------------------------------------------
    print("\n--- 8. Testing DB commit failure (Telegram should NOT be called)---")

    mock_fail_job = schemas.JobCreate(
        title="Failing DB Job",
        company="DBError Corp",
        url="https://example.com/job/db-fail",
        location="Remote",
        description="Job that triggers DB commit error.",
        experience="Fresher",
        source="JSearch",
    )

    with patch("services.jsearch_service.fetch_jobs") as mock_fetch, \
         patch("services.ai_service.evaluate_job") as mock_eval, \
         patch("crud.create_job", side_effect=Exception("DB commit error")) as mock_create, \
         patch("services.notification_service.send_job_alert") as mock_notify:

        mock_fetch.return_value = [mock_fail_job]
        mock_eval.return_value = AIEvaluationResult(
            score=8.5,
            match_reason="Perfect fit for role.",
            cover_letter="Dear Hiring Manager...",
        )

        summary = pipeline.run_automation_pipeline(db_session=db)

        assert_test(mock_eval.called is True, "Gemini evaluation was performed")
        assert_test(mock_create.called is True, "Database save was attempted")
        assert_test(summary["failed"] == 1, "Job counted as failed due to DB error")
        assert_test(mock_notify.called is False, "Telegram not invoked when DB commit fails")

    # -----------------------------------------------------------------------
    # 9. Test: Telegram notification failure – job persists, not counted as notified
    # -----------------------------------------------------------------------
    print("\n--- 9. Testing Telegram failure (job should persist, notified count unchanged)---")

    mock_notify_fail_job = schemas.JobCreate(
        title="Notify Fail Job",
        company="NotifyError Inc",
        url="https://example.com/job/notify-fail",
        location="Remote",
        description="Job that triggers Telegram error.",
        experience="Fresher",
        source="JSearch",
    )

    with patch("services.jsearch_service.fetch_jobs") as mock_fetch, \
         patch("services.ai_service.evaluate_job") as mock_eval, \
         patch("services.notification_service.send_job_alert", side_effect=Exception("Telegram error")) as mock_notify:

        mock_fetch.return_value = [mock_notify_fail_job]
        mock_eval.return_value = AIEvaluationResult(
            score=8.5,
            match_reason="Perfect fit for role.",
            cover_letter="Dear Hiring Manager...",
        )

        summary = pipeline.run_automation_pipeline(db_session=db)

        assert_test(summary["saved"] == 1, "Job saved even when Telegram fails")
        assert_test(summary["notified"] == 0, "Notified count stays zero after Telegram error")
        assert_test(mock_notify.called is True, "Telegram notification was attempted")

        saved_record = db.query(models.Job).filter(
            models.Job.url == "https://example.com/job/notify-fail"
        ).first()

        assert_test(saved_record is not None, "Job remains in DB after Telegram failure")

    print("\n" + "=" * 70)
    print(f"ALL {total_tests} PIPELINE ORCHESTRATOR TESTS PASSED! ({passed_tests}/{total_tests})")
    print("=" * 70)

    db.close()


if __name__ == "__main__":
    run_all_pipeline_tests()
