"""
JSearch Service Module
Fetches and normalizes job opportunities from JSearch API via RapidAPI.
"""

import os
import re
import logging
from typing import Optional, List, Dict, Any
import httpx

try:
    from schemas import JobCreate
except ImportError:
    from backend.schemas import JobCreate

logger = logging.getLogger("jsearch_service")
logger.setLevel(logging.INFO)

# Default RapidAPI configuration for JSearch
DEFAULT_API_HOST = "jsearch.p.rapidapi.com"
DEFAULT_API_URL = "https://jsearch.p.rapidapi.com/search"
DEFAULT_TIMEOUT_SECONDS = 15.0


# ---------------------------------------------------------------------------
# Custom Exceptions
# ---------------------------------------------------------------------------
class JSearchError(Exception):
    """Base exception for JSearch API operations."""
    pass


class JSearchConfigError(JSearchError):
    """Raised when required API credentials or configurations are missing."""
    pass


class JSearchAuthError(JSearchError):
    """Raised when RapidAPI rejects authentication (HTTP 401 / 403)."""
    pass


class JSearchRateLimitError(JSearchError):
    """Raised when RapidAPI rate limit is reached (HTTP 429)."""
    pass


class JSearchNetworkError(JSearchError):
    """Raised when an HTTP connection or timeout error occurs."""
    pass


# ---------------------------------------------------------------------------
# Helper Functions
# ---------------------------------------------------------------------------
def get_api_key() -> str:
    """
    Retrieves the RapidAPI key from environment variables.
    Checks RAPIDAPI_KEY first, falling back to JSEARCH_API_KEY.
    Does not expose or log the key.
    """
    key = os.getenv("RAPIDAPI_KEY") or os.getenv("JSEARCH_API_KEY")
    if not key or not key.strip():
        raise JSearchConfigError(
            "RAPIDAPI_KEY is not configured in environment variables. Please add it to your .env file."
        )
    return key.strip()


def build_search_query(active_role: str, preferred_locations: Optional[str] = None) -> str:
    """
    Constructs an optimized JSearch search query string.
    Combines active role and preferred locations safely.
    Example: 'AI/ML Engineer in India' or 'Python Developer in Remote'
    """
    role = active_role.strip() if active_role else "Software Developer"
    if not preferred_locations or not preferred_locations.strip():
        return role

    # Clean and split locations
    locations = [loc.strip() for loc in preferred_locations.split(",") if loc.strip()]
    if not locations:
        return role

    # Check for remote preference
    has_remote = any("remote" in loc.lower() for loc in locations)
    non_remote_locations = [loc for loc in locations if "remote" not in loc.lower() and "hybrid" not in loc.lower()]

    if non_remote_locations:
        primary_loc = non_remote_locations[0]
        if has_remote:
            return f"{role} in {primary_loc} remote"
        return f"{role} in {primary_loc}"

    if has_remote:
        return f"{role} remote"

    return f"{role} in {locations[0]}"


def extract_location(raw_job: Dict[str, Any]) -> str:
    """
    Assembles a coherent location string from JSearch geographic fields.
    """
    city = raw_job.get("job_city")
    state = raw_job.get("job_state")
    country = raw_job.get("job_country")
    is_remote = bool(raw_job.get("job_is_remote"))

    parts = [p.strip() for p in [city, state, country] if p and isinstance(p, str) and p.strip()]
    location_str = ", ".join(parts) if parts else ""

    if is_remote:
        return f"{location_str} (Remote)".strip() if location_str else "Remote"

    return location_str or "Not Specified"


def extract_experience_text(raw_job: Dict[str, Any]) -> Optional[str]:
    """
    Extracts experience requirements from structured JSearch fields or highlights.
    Returns a human-readable experience string (e.g. '0-1 years', '2 years', 'Fresher').
    """
    req_exp = raw_job.get("job_required_experience")
    if isinstance(req_exp, dict):
        if req_exp.get("no_experience_required") is True:
            return "Fresher"

        months = req_exp.get("required_experience_in_months")
        if months is not None and isinstance(months, (int, float)) and months > 0:
            if months < 12:
                return f"{int(months)} months"
            years = months / 12.0
            return f"{int(years)} year{'s' if years > 1 else ''}" if years.is_integer() else f"{years:g} years"

    # Fallback: scan qualifications highlights if available
    highlights = raw_job.get("job_highlights")
    if isinstance(highlights, dict):
        quals = highlights.get("Qualifications")
        if isinstance(quals, list):
            for qual in quals:
                if isinstance(qual, str):
                    match = re.search(r'(\d+\+?\s*(?:to|-)?\s*\d*\s*(?:years?|yrs?|months?))', qual, re.IGNORECASE)
                    if match:
                        return match.group(1).strip()

    return None


def normalize_jsearch_job(raw_job: Dict[str, Any]) -> Optional[JobCreate]:
    """
    Transforms a single raw JSearch result dictionary into a standard JobCreate schema.
    Returns None if essential fields (title, company) are missing or invalid.
    """
    if not isinstance(raw_job, dict):
        return None

    title = raw_job.get("job_title")
    company = raw_job.get("employer_name")

    if not title or not isinstance(title, str) or not title.strip():
        logger.warning("Skipping JSearch job with missing job_title.")
        return None

    if not company or not isinstance(company, str) or not company.strip():
        logger.warning(f"Skipping JSearch job '{title}' with missing employer_name.")
        return None

    # URL prioritization: apply_link > google_link
    url = raw_job.get("job_apply_link") or raw_job.get("job_google_link")
    if url and not isinstance(url, str):
        url = str(url)

    # Job type formatting
    job_type = raw_job.get("job_employment_type")
    if job_type and isinstance(job_type, str):
        job_type = job_type.replace("_", " ").title()

    description = raw_job.get("job_description")
    if description and not isinstance(description, str):
        description = str(description)

    location = extract_location(raw_job)
    experience = extract_experience_text(raw_job)

    try:
        return JobCreate(
            title=title.strip(),
            company=company.strip(),
            url=url.strip() if url else None,
            location=location,
            description=description.strip() if description else "",
            job_type=job_type,
            experience=experience,
            source="JSearch",
            score=None,
            match_reason=None,
            cover_letter=None,
            status="To Apply",
        )
    except Exception as exc:
        logger.warning(f"Validation error normalizing JSearch job '{title}' at '{company}': {exc}")
        return None


# ---------------------------------------------------------------------------
# Main Fetch Operation
# ---------------------------------------------------------------------------
def fetch_jobs(
    active_role: str,
    preferred_locations: Optional[str] = None,
    num_pages: int = 1,
    date_posted: str = "all",
    client: Optional[httpx.Client] = None,
) -> List[JobCreate]:
    """
    Queries JSearch API for job postings matching active_role and preferred_locations.
    Returns a list of validated JobCreate objects.
    Accepts an optional httpx.Client for offline testing or dependency injection.
    """
    api_key = get_api_key()
    api_url = os.getenv("JSEARCH_API_URL", DEFAULT_API_URL)
    api_host = os.getenv("JSEARCH_API_HOST", DEFAULT_API_HOST)

    query = build_search_query(active_role=active_role, preferred_locations=preferred_locations)
    headers = {
        "X-RapidAPI-Key": api_key,
        "X-RapidAPI-Host": api_host,
    }
    params = {
        "query": query,
        "page": "1",
        "num_pages": str(max(1, num_pages)),
        "date_posted": date_posted,
    }

    logger.info(f"Initiating JSearch query: '{query}' (pages: {num_pages})")

    # Helper to execute request with given client
    def _do_request(c: httpx.Client) -> httpx.Response:
        try:
            return c.get(api_url, headers=headers, params=params, timeout=DEFAULT_TIMEOUT_SECONDS)
        except httpx.TimeoutException as exc:
            raise JSearchNetworkError(f"JSearch API request timed out after {DEFAULT_TIMEOUT_SECONDS}s: {exc}")
        except httpx.RequestError as exc:
            raise JSearchNetworkError(f"Failed to connect to JSearch API: {exc}")

    if client is not None:
        response = _do_request(client)
    else:
        with httpx.Client() as default_client:
            response = _do_request(default_client)

    # Status validation
    if response.status_code in (401, 403):
        raise JSearchAuthError("RapidAPI authentication failed. Verify that RAPIDAPI_KEY is valid.")
    if response.status_code == 429:
        raise JSearchRateLimitError("RapidAPI rate limit exceeded. Try again later or upgrade your plan.")
    if response.status_code >= 400:
        raise JSearchError(
            f"JSearch API returned HTTP {response.status_code}: {response.text[:200]}"
        )

    # Response parsing
    try:
        data = response.json()
    except Exception as exc:
        raise JSearchError(f"Failed to parse JSearch response as JSON: {exc}")

    if not isinstance(data, dict):
        raise JSearchError("JSearch API response is not a valid JSON dictionary.")

    raw_jobs = data.get("data")
    if not raw_jobs or not isinstance(raw_jobs, list):
        logger.info("JSearch returned zero job items for this query.")
        return []

    normalized_jobs: List[JobCreate] = []
    for item in raw_jobs:
        job = normalize_jsearch_job(item)
        if job is not None:
            normalized_jobs.append(job)

    logger.info(f"Successfully normalized {len(normalized_jobs)} / {len(raw_jobs)} JSearch jobs.")
    return normalized_jobs

