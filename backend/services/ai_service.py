"""
Gemini AI Service Module
Evaluates job postings against candidate resumes using the Google GenAI SDK.
Produces structured match scores (0-10), fit rationale, and tailored cover letters.
"""

import os
import re
import json
import math
import logging
from typing import Optional, Dict, Any
from pydantic import BaseModel, Field

from google import genai
from google.genai import types
from google.genai import errors as genai_errors

logger = logging.getLogger("ai_service")
logger.setLevel(logging.INFO)

# Default model configuration
DEFAULT_GEMINI_MODEL = "gemini-2.5-flash"
DEFAULT_TEMPERATURE = 0.2


# ---------------------------------------------------------------------------
# Pydantic Output Model
# ---------------------------------------------------------------------------
class AIEvaluationResult(BaseModel):
    """Structured evaluation result for a job opportunity."""
    score: float = Field(..., ge=0.0, le=10.0, description="Match score from 0.0 to 10.0")
    match_reason: str = Field(..., min_length=1, description="1-2 sentences explaining why the job matches or doesn't")
    cover_letter: str = Field(..., min_length=1, description="Professional personalized cover letter")


# ---------------------------------------------------------------------------
# Custom Exceptions
# ---------------------------------------------------------------------------
class AIError(Exception):
    """Base exception for AI evaluation errors."""
    pass


class AIConfigError(AIError):
    """Raised when GEMINI_API_KEY or required configuration is missing."""
    pass


class AIAuthError(AIError):
    """Raised when Gemini API rejects credentials (HTTP 401/403)."""
    pass


class AIRateLimitError(AIError):
    """Raised when Gemini API quota or rate limit is reached (HTTP 429)."""
    pass


class AITimeoutError(AIError):
    """Raised when the Gemini API call times out."""
    pass


class AIValidationError(AIError):
    """Raised when inputs (e.g. resume or job description) are invalid/empty."""
    pass


class AIResponseFormatError(AIError):
    """Raised when the model output cannot be parsed into the required schema."""
    pass


# ---------------------------------------------------------------------------
# Credential & Configuration Helpers
# ---------------------------------------------------------------------------
def get_gemini_api_key() -> str:
    """
    Retrieves the Gemini API key from environment variables.
    Checks GEMINI_API_KEY. Never prints or logs the key.
    """
    key = os.getenv("GEMINI_API_KEY")
    if not key or not key.strip():
        raise AIConfigError(
            "GEMINI_API_KEY is not configured in environment variables. Please add it to your .env file."
        )
    return key.strip()


def get_gemini_model_name() -> str:
    """Retrieves the configured Gemini model name."""
    return os.getenv("GEMINI_MODEL", DEFAULT_GEMINI_MODEL)


# ---------------------------------------------------------------------------
# Prompt Construction
# ---------------------------------------------------------------------------
SYSTEM_INSTRUCTION = (
    "You are an expert technical recruiter and career coach. "
    "Evaluate the fit between the candidate's resume and the job posting. "
    "Strictly output a valid JSON object matching the requested schema with no extraneous markdown wrappers."
)


def build_evaluation_prompt(
    job_title: str,
    company: str,
    job_description: str,
    resume_text: str,
    active_role: str = "AI/ML Engineer",
    max_years_experience: int = 1,
) -> str:
    """
    Builds the structured evaluation prompt matching project guidelines.
    """
    return f"""Candidate Active Target Role: {active_role}
Max Allowed Experience: {max_years_experience} year(s)

Candidate Resume:
{resume_text}

Job Opportunity:
Title: {job_title}
Company: {company}
Job Description:
{job_description}

Return ONLY a raw JSON object with this exact structure:
{{
  "score": <float between 0.0 and 10.0 based on skill and domain overlap>,
  "match_reason": "<1-2 sentence explanation of why this job matches or doesn't match>",
  "cover_letter": "<Professional, concise 3-paragraph personalized cover letter tailored to this role and company using candidate's projects>"
}}"""


# ---------------------------------------------------------------------------
# Response Parsing & Schema Validation
# ---------------------------------------------------------------------------
def parse_and_validate_ai_response(raw_text: str) -> AIEvaluationResult:
    """
    Parses and strictly validates raw LLM output into AIEvaluationResult.
    Handles raw JSON or JSON wrapped in markdown code blocks.
    Enforces score bounds [0.0, 10.0] and non-empty string fields.
    """
    if not raw_text or not isinstance(raw_text, str) or not raw_text.strip():
        raise AIResponseFormatError("Received empty response from AI model.")

    cleaned_text = raw_text.strip()

    # Strip markdown code fences if present (e.g. ```json ... ```)
    if "```" in cleaned_text:
        match = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', cleaned_text)
        if match:
            cleaned_text = match.group(1).strip()

    try:
        data = json.loads(cleaned_text)
    except json.JSONDecodeError as exc:
        raise AIResponseFormatError(f"Failed to parse AI output as JSON: {exc}. Raw snippet: {cleaned_text[:120]}")

    if not isinstance(data, dict):
        raise AIResponseFormatError(f"AI output is not a JSON object: {type(data).__name__}")

    # Validate score field
    if "score" not in data:
        raise AIResponseFormatError("Missing required 'score' field in AI response.")

    raw_score = data.get("score")
    try:
        score = float(raw_score)
    except (ValueError, TypeError):
        raise AIResponseFormatError(f"Score '{raw_score}' is not a valid numeric float.")

    if math.isnan(score) or math.isinf(score) or score < 0.0 or score > 10.0:
        raise AIResponseFormatError(f"Score {score} is out of valid [0.0, 10.0] range.")

    # Validate match_reason field
    reason = data.get("match_reason")
    if not reason or not isinstance(reason, str) or not reason.strip():
        raise AIResponseFormatError("Missing or empty 'match_reason' field in AI response.")

    # Validate cover_letter field
    cover = data.get("cover_letter")
    if not cover or not isinstance(cover, str) or not cover.strip():
        raise AIResponseFormatError("Missing or empty 'cover_letter' field in AI response.")

    return AIEvaluationResult(
        score=round(score, 1),
        match_reason=reason.strip(),
        cover_letter=cover.strip(),
    )


# ---------------------------------------------------------------------------
# Core Evaluation Function
# ---------------------------------------------------------------------------
def evaluate_job(
    job_title: str,
    company: str,
    job_description: str,
    resume_text: str,
    active_role: str = "AI/ML Engineer",
    max_years_experience: int = 1,
    client: Optional[Any] = None,
) -> AIEvaluationResult:
    """
    Evaluates a single job opportunity against candidate resume text.
    Validates inputs, contacts Google Gemini, and returns a verified AIEvaluationResult.
    Accepts an optional client for offline testing and mock injection.
    """
    # 1. Input Validation
    if not resume_text or not isinstance(resume_text, str) or not resume_text.strip():
        raise AIValidationError("Candidate resume text is empty. Upload a resume before running AI evaluation.")

    if not job_description or not isinstance(job_description, str) or not job_description.strip():
        raise AIValidationError("Job description is empty. Cannot evaluate an empty job description.")

    clean_title = (job_title or "Position").strip()
    clean_company = (company or "Company").strip()

    logger.info(f"Evaluating job '{clean_title}' at '{clean_company}' for role '{active_role}'")

    # 2. Client & Prompt Preparation
    model_name = get_gemini_model_name()
    prompt = build_evaluation_prompt(
        job_title=clean_title,
        company=clean_company,
        job_description=job_description.strip(),
        resume_text=resume_text.strip(),
        active_role=active_role,
        max_years_experience=max_years_experience,
    )

    # 3. Model Invocation
    try:
        active_client = client if client is not None else genai.Client(api_key=get_gemini_api_key())

        config = types.GenerateContentConfig(
            system_instruction=SYSTEM_INSTRUCTION,
            response_mime_type="application/json",
            response_schema=AIEvaluationResult,
            temperature=DEFAULT_TEMPERATURE,
        )

        response = active_client.models.generate_content(
            model=model_name,
            contents=prompt,
            config=config,
        )

    except AIConfigError:
        raise

    except genai_errors.APIError as exc:
        err_msg = str(exc)
        code = getattr(exc, "code", None)
        if code == 429 or "RESOURCE_EXHAUSTED" in err_msg or "rate limit" in err_msg.lower():
            raise AIRateLimitError(f"Gemini API rate limit exceeded: {err_msg}")
        if code in (401, 403) or "API_KEY_INVALID" in err_msg or "unauthorized" in err_msg.lower():
            raise AIAuthError("Gemini authentication failed. Verify GEMINI_API_KEY is valid.")
        raise AIError(f"Gemini API error ({code}): {err_msg}")

    except TimeoutError as exc:
        raise AITimeoutError(f"Gemini API request timed out: {exc}")

    except Exception as exc:
        err_str = str(exc)
        if "timeout" in err_str.lower():
            raise AITimeoutError(f"Gemini request timed out: {exc}")
        if "rate limit" in err_str.lower() or "quota" in err_str.lower():
            raise AIRateLimitError(f"Gemini quota/rate limit error: {exc}")
        raise AIError(f"Unexpected error calling Gemini API: {exc}")

    # 4. Extract and validate output
    raw_response_text = getattr(response, "text", None)
    if not raw_response_text and hasattr(response, "candidates") and response.candidates:
        # Fallback extraction from candidate content parts
        parts = getattr(response.candidates[0].content, "parts", [])
        if parts:
            raw_response_text = getattr(parts[0], "text", None)

    return parse_and_validate_ai_response(raw_response_text or "")
