"""
Offline Unit Test Suite for Gemini AI Service.
Tests structured output parsing, error handling, score validation, and mocked client execution.
Zero live API requests are made.
"""

import os
import sys
import json
from pathlib import Path
from unittest.mock import MagicMock

# Ensure backend directory is in path
sys.path.insert(0, str(Path(__file__).parent))

from services.ai_service import (
    AIEvaluationResult,
    AIError,
    AIConfigError,
    AIAuthError,
    AIRateLimitError,
    AITimeoutError,
    AIValidationError,
    AIResponseFormatError,
    build_evaluation_prompt,
    parse_and_validate_ai_response,
    evaluate_job,
)
from google.genai import errors as genai_errors


MOCK_VALID_RAW_JSON = json.dumps({
    "score": 8.7,
    "match_reason": "Strong alignment with candidate's Python and ML background. Excellent match for computer vision skills.",
    "cover_letter": "Dear Acme Hiring Team,\n\nI am thrilled to apply for the Machine Learning Engineer position. My background in PyTorch and NLP aligns closely with your needs.\n\nSincerely,\nCandidate"
})

MOCK_MARKDOWN_WRAPPED_JSON = f"""```json
{MOCK_VALID_RAW_JSON}
```"""


def run_all_ai_service_tests():
    print("=" * 70)
    print("RUNNING OFFLINE GEMINI AI SERVICE UNIT TESTS (MOCKED)")
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
    # 1. Prompt Builder Tests
    # -----------------------------------------------------------------------
    print("\n--- 1. Testing build_evaluation_prompt ---")
    prompt = build_evaluation_prompt(
        job_title="ML Engineer",
        company="Acme Corp",
        job_description="Build ML models in PyTorch.",
        resume_text="Experienced in Python, PyTorch, and NLP.",
        active_role="AI/ML Engineer",
        max_years_experience=1,
    )
    assert_test("Candidate Active Target Role: AI/ML Engineer" in prompt, "Prompt includes active role")
    assert_test("Max Allowed Experience: 1 year(s)" in prompt, "Prompt includes max experience")
    assert_test("Title: ML Engineer" in prompt, "Prompt includes job title")
    assert_test("Company: Acme Corp" in prompt, "Prompt includes company")

    # -----------------------------------------------------------------------
    # 2. Response Parsing & Schema Validation Tests
    # -----------------------------------------------------------------------
    print("\n--- 2. Testing parse_and_validate_ai_response ---")
    # 2.1 Clean JSON
    res1 = parse_and_validate_ai_response(MOCK_VALID_RAW_JSON)
    assert_test(isinstance(res1, AIEvaluationResult), "Valid raw JSON returns AIEvaluationResult")
    assert_test(res1.score == 8.7, "Score parsed correctly")
    assert_test("PyTorch" in res1.cover_letter, "Cover letter parsed correctly")

    # 2.2 Markdown fenced JSON
    res2 = parse_and_validate_ai_response(MOCK_MARKDOWN_WRAPPED_JSON)
    assert_test(isinstance(res2, AIEvaluationResult), "Markdown ```json fenced output handled cleanly")
    assert_test(res2.score == 8.7, "Score matches from fenced block")

    # 2.3 Empty or non-dict outputs
    try:
        parse_and_validate_ai_response("")
        assert_test(False, "Empty response should fail")
    except AIResponseFormatError:
        assert_test(True, "Empty response raises AIResponseFormatError")

    try:
        parse_and_validate_ai_response("[1, 2, 3]")
        assert_test(False, "JSON array should fail")
    except AIResponseFormatError:
        assert_test(True, "JSON array raises AIResponseFormatError")

    try:
        parse_and_validate_ai_response("{broken_json: true")
        assert_test(False, "Malformed JSON syntax should fail")
    except AIResponseFormatError:
        assert_test(True, "Malformed JSON syntax raises AIResponseFormatError")

    # 2.4 Missing required fields
    no_score_json = json.dumps({"match_reason": "Good", "cover_letter": "Letter"})
    try:
        parse_and_validate_ai_response(no_score_json)
        assert_test(False, "Missing score should fail")
    except AIResponseFormatError:
        assert_test(True, "Missing score raises AIResponseFormatError")

    no_reason_json = json.dumps({"score": 8.0, "cover_letter": "Letter"})
    try:
        parse_and_validate_ai_response(no_reason_json)
        assert_test(False, "Missing match_reason should fail")
    except AIResponseFormatError:
        assert_test(True, "Missing match_reason raises AIResponseFormatError")

    no_cover_json = json.dumps({"score": 8.0, "match_reason": "Reason"})
    try:
        parse_and_validate_ai_response(no_cover_json)
        assert_test(False, "Missing cover_letter should fail")
    except AIResponseFormatError:
        assert_test(True, "Missing cover_letter raises AIResponseFormatError")

    # -----------------------------------------------------------------------
    # 3. Score Bounds & Type Validation Tests
    # -----------------------------------------------------------------------
    print("\n--- 3. Testing Score Validation ---")
    # Score > 10.0
    high_score_json = json.dumps({"score": 11.5, "match_reason": "Reason", "cover_letter": "Letter"})
    try:
        parse_and_validate_ai_response(high_score_json)
        assert_test(False, "Score > 10.0 should fail")
    except AIResponseFormatError:
        assert_test(True, "Score > 10.0 raises AIResponseFormatError")

    # Score < 0.0
    low_score_json = json.dumps({"score": -1.0, "match_reason": "Reason", "cover_letter": "Letter"})
    try:
        parse_and_validate_ai_response(low_score_json)
        assert_test(False, "Score < 0.0 should fail")
    except AIResponseFormatError:
        assert_test(True, "Score < 0.0 raises AIResponseFormatError")

    # Non-numeric score
    str_score_json = json.dumps({"score": "excellent", "match_reason": "Reason", "cover_letter": "Letter"})
    try:
        parse_and_validate_ai_response(str_score_json)
        assert_test(False, "Non-numeric score string should fail")
    except AIResponseFormatError:
        assert_test(True, "Non-numeric score string raises AIResponseFormatError")

    # Valid edge boundary scores (0.0 and 10.0)
    boundary_min = parse_and_validate_ai_response(json.dumps({"score": 0.0, "match_reason": "Zero match", "cover_letter": "Letter"}))
    assert_test(boundary_min.score == 0.0, "Score 0.0 is accepted")

    boundary_max = parse_and_validate_ai_response(json.dumps({"score": 10.0, "match_reason": "Perfect match", "cover_letter": "Letter"}))
    assert_test(boundary_max.score == 10.0, "Score 10.0 is accepted")

    # -----------------------------------------------------------------------
    # 4. Input Validation Tests (Empty Resume or Job Description)
    # -----------------------------------------------------------------------
    print("\n--- 4. Testing evaluate_job Input Validation ---")
    mock_client = MagicMock()

    try:
        evaluate_job("ML Eng", "Corp", "Valid description", "", client=mock_client)
        assert_test(False, "Empty resume should fail")
    except AIValidationError:
        assert_test(True, "Empty resume string raises AIValidationError")

    try:
        evaluate_job("ML Eng", "Corp", "Valid description", "   \n\t   ", client=mock_client)
        assert_test(False, "Whitespace-only resume should fail")
    except AIValidationError:
        assert_test(True, "Whitespace-only resume raises AIValidationError")

    try:
        evaluate_job("ML Eng", "Corp", "", "Valid resume text", client=mock_client)
        assert_test(False, "Empty job description should fail")
    except AIValidationError:
        assert_test(True, "Empty job description raises AIValidationError")

    try:
        evaluate_job("ML Eng", "Corp", "   ", "Valid resume text", client=mock_client)
        assert_test(False, "Whitespace-only job description should fail")
    except AIValidationError:
        assert_test(True, "Whitespace-only job description raises AIValidationError")

    # -----------------------------------------------------------------------
    # 5. Mock Client Execution & Error Handling Tests
    # -----------------------------------------------------------------------
    print("\n--- 5. Testing Mock Client Invocation & API Errors ---")
    # 5.1 Successful evaluation
    mock_resp = MagicMock()
    mock_resp.text = MOCK_VALID_RAW_JSON
    mock_client.models.generate_content.return_value = mock_resp

    eval_result = evaluate_job(
        job_title="ML Engineer",
        company="Acme Corp",
        job_description="Deep learning specialist needed.",
        resume_text="Senior ML practitioner with PyTorch experience.",
        client=mock_client,
    )
    assert_test(isinstance(eval_result, AIEvaluationResult), "evaluate_job returns AIEvaluationResult from mocked client")
    assert_test(eval_result.score == 8.7, "Match score matches mock")

    # 5.2 Rate limit error (HTTP 429)
    rate_limit_err = genai_errors.APIError(429, {"error": {"message": "RESOURCE_EXHAUSTED: Rate limit exceeded", "status": "RESOURCE_EXHAUSTED"}})
    mock_client.models.generate_content.side_effect = rate_limit_err
    try:
        evaluate_job("ML Eng", "Corp", "Job desc", "Resume text", client=mock_client)
        assert_test(False, "API 429 should raise AIRateLimitError")
    except AIRateLimitError:
        assert_test(True, "API 429 maps to AIRateLimitError")

    # 5.2b Temporary overload (HTTP 503) must be retryable (AITimeoutError)
    overload_err = genai_errors.APIError(503, {"error": {"message": "high demand", "status": "UNAVAILABLE"}})
    mock_client.models.generate_content.side_effect = overload_err
    try:
        evaluate_job("ML Eng", "Corp", "Job desc", "Resume text", client=mock_client)
        assert_test(False, "API 503 should raise a retryable error")
    except AITimeoutError:
        assert_test(True, "API 503 maps to retryable AITimeoutError")

    # 5.3 Authentication error (HTTP 401)
    auth_err = genai_errors.APIError(401, {"error": {"message": "API_KEY_INVALID", "status": "UNAUTHENTICATED"}})
    mock_client.models.generate_content.side_effect = auth_err
    try:
        evaluate_job("ML Eng", "Corp", "Job desc", "Resume text", client=mock_client)
        assert_test(False, "API 401 should raise AIAuthError")
    except AIAuthError:
        assert_test(True, "API 401 maps to AIAuthError")

    # 5.4 Timeout error
    mock_client.models.generate_content.side_effect = TimeoutError("Connection timed out after 30s")
    try:
        evaluate_job("ML Eng", "Corp", "Job desc", "Resume text", client=mock_client)
        assert_test(False, "TimeoutError should raise AITimeoutError")
    except AITimeoutError:
        assert_test(True, "TimeoutError maps to AITimeoutError")

    # 5.5 Missing GEMINI_API_KEY when no client provided
    if "GEMINI_API_KEY" in os.environ:
        del os.environ["GEMINI_API_KEY"]

    try:
        evaluate_job("ML Eng", "Corp", "Job desc", "Resume text")
        assert_test(False, "Missing GEMINI_API_KEY should raise AIConfigError")
    except AIConfigError:
        assert_test(True, "Missing GEMINI_API_KEY raises AIConfigError without leaking credentials")

    print("\n" + "=" * 70)
    print(f"ALL {total_tests} GEMINI AI SERVICE OFFLINE TESTS PASSED! ({passed_tests}/{total_tests})")
    print("=" * 70)


if __name__ == "__main__":
    run_all_ai_service_tests()
