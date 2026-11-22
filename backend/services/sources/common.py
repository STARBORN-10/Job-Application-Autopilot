"""Normalisation helpers shared by the job sources."""
import datetime
import html
import re
from typing import Optional

_TAG_RE = re.compile(r"<[^>]+>")
_BLOCK_TAG_RE = re.compile(r"</?(?:p|div|br|li|ul|ol|h[1-6]|tr)[^>]*>", re.IGNORECASE)

_EXPERIENCE_RE = re.compile(
    r"(\d+(?:\.\d+)?\s*\+?\s*(?:(?:to|-|–)\s*\d+(?:\.\d+)?\s*)?(?:years?|yrs?))"
    r"(?:\s*(?:of\s+)?(?:[\w-]+\s+){0,2}?(?:experience|exp)\b)?",
    re.IGNORECASE,
)


def strip_html(text: Optional[str]) -> str:
    """HTML (possibly entity-escaped, as Greenhouse returns it) -> readable plain text."""
    if not text:
        return ""
    t = html.unescape(html.unescape(text)) if "&lt;" in text else html.unescape(text)
    t = _BLOCK_TAG_RE.sub("\n", t)
    t = _TAG_RE.sub(" ", t)
    t = t.replace("\xa0", " ")
    t = re.sub(r"[ \t\r\f\v]+", " ", t)
    t = re.sub(r"\n\s*\n+", "\n\n", t)
    return t.strip()


def parse_datetime(value) -> Optional[datetime.datetime]:
    """ISO-8601 string or epoch (seconds or milliseconds) -> naive UTC datetime."""
    if value in (None, ""):
        return None
    try:
        if isinstance(value, (int, float)) or (isinstance(value, str) and value.isdigit()):
            ts = float(value)
            if ts > 1e11:  # milliseconds
                ts /= 1000.0
            return datetime.datetime.fromtimestamp(ts, datetime.timezone.utc).replace(tzinfo=None)
        text = str(value).strip().replace("Z", "+00:00")
        # Trim fractional seconds beyond microseconds (Jooble sends 7 digits).
        text = re.sub(r"(\.\d{6})\d+", r"\1", text)
        parsed = datetime.datetime.fromisoformat(text)
        if parsed.tzinfo:
            parsed = parsed.astimezone(datetime.timezone.utc).replace(tzinfo=None)
        return parsed
    except (ValueError, OSError, OverflowError):
        return None


def experience_from_text(*texts: Optional[str]) -> Optional[str]:
    """First experience phrase such as '3-4 Years' or '2+ years' found in the given texts."""
    for text in texts:
        if not text:
            continue
        lowered = text.lower()
        if re.search(r"\b(fresher|freshers|no experience required|entry[- ]level)\b", lowered):
            return "Fresher"
        match = _EXPERIENCE_RE.search(text)
        if match:
            return re.sub(r"\s+", " ", match.group(1)).strip()
    return None


_JOB_TYPES = [
    (re.compile(r"intern", re.I), "Internship"),
    (re.compile(r"part[\s_-]?time", re.I), "Part-time"),
    (re.compile(r"contract|freelance|consult", re.I), "Contract"),
    (re.compile(r"temp", re.I), "Temporary"),
    (re.compile(r"full[\s_-]?time|permanent|regular", re.I), "Full-time"),
]


def normalize_job_type(value: Optional[str]) -> Optional[str]:
    """Map the many spellings ('FULLTIME', 'full_time', 'FullTime', 'Intern') onto one vocabulary."""
    if not value:
        return None
    for pattern, label in _JOB_TYPES:
        if pattern.search(str(value)):
            return label
    return str(value).strip() or None


_JUNK_COMPANY = re.compile(r"checking your browser|just a moment|captcha|access denied|attention required", re.I)


def clean_company(name: Optional[str]) -> str:
    """Company name, or "" when a source returned a bot-check page title instead (seen on Adzuna)."""
    name = strip_html(name)
    return "" if not name or _JUNK_COMPANY.search(name) else name
