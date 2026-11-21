"""
Cross-source de-duplication (stdlib only).

The same opening is often returned by several sources (JSearch, Adzuna, Jooble, ...), each with its
own redirect URL. Two jobs are treated as the same posting when:
1. their canonical URLs are equal (tracking parameters, fragments, "www." and trailing slashes removed), or
2. the normalised company names agree, the normalised titles are near-identical (difflib ratio at or
   above TITLE_THRESHOLD, with no seniority word on only one side) and the locations are compatible.

Merging keeps every source name and the richest description.
"""
import difflib
import re
from typing import Iterable, Optional
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from services import geo

TITLE_THRESHOLD = 0.9
COMPANY_THRESHOLD = 0.9

TRACKING_PARAMS = {
    "gclid", "fbclid", "msclkid", "mc_cid", "mc_eid", "ref", "ref_src", "referrer", "refid", "trk",
    "trkinfo", "trackingid", "src", "source", "from", "gh_src", "lever-origin", "lever-source",
    "utm", "_hsenc", "_hsmi", "igshid", "si", "spm", "campaign", "jobsource", "ss", "ga",
}

SENIORITY_WORDS = {
    "intern", "internship", "trainee", "junior", "jr", "senior", "sr", "lead", "principal", "staff",
    "head", "manager", "director", "associate", "ii", "iii", "iv", "2", "3", "chief", "vp", "fresher",
}

COMPANY_SUFFIXES = {
    "pvt", "private", "ltd", "limited", "inc", "llc", "llp", "plc", "corp", "corporation", "co",
    "company", "gmbh", "india", "technologies", "technology", "tech", "solutions", "services",
    "software", "labs", "group", "the",
}


def canonical_url(url: Optional[str]) -> Optional[str]:
    """Tracking-free, comparable form of a URL (None for empty/invalid input)."""
    if not url or not isinstance(url, str) or not url.strip():
        return None
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return None
    if not parts.netloc:
        return None
    host = parts.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    host = host.removesuffix(":443").removesuffix(":80")
    query = [
        (k, v) for k, v in parse_qsl(parts.query, keep_blank_values=False)
        if not k.lower().startswith("utm_") and k.lower() not in TRACKING_PARAMS
    ]
    query.sort()
    path = parts.path.rstrip("/") or ""
    return urlunsplit(("https", host, path, urlencode(query), ""))


def _words(text: Optional[str]) -> list[str]:
    text = (text or "").lower().replace("&", " and ")
    return re.findall(r"[a-z0-9+#]+", text)


def normalize_title(title: Optional[str]) -> str:
    """Lower-case words only; drops bracketed notes and trailing experience tags like '- 6-8 Years'."""
    t = (title or "").lower()
    t = re.sub(r"\([^)]*\)|\[[^\]]*\]", " ", t)
    t = re.sub(r"[-|,:]\s*\d+\s*(?:-|to|–)?\s*\d*\s*\+?\s*(?:years?|yrs?)\b.*$", " ", t)
    t = re.sub(r"\b(?:remote|hybrid|wfh|work from home|full[- ]?time|immediate joiner[s]?)\b", " ", t)
    return " ".join(_words(t))


def normalize_company(company: Optional[str]) -> str:
    words = [w for w in _words(company) if w not in COMPANY_SUFFIXES]
    return " ".join(words)


def _seniority(title_norm: str) -> set[str]:
    return set(title_norm.split()) & SENIORITY_WORDS


def same_company(a: Optional[str], b: Optional[str]) -> bool:
    na, nb = normalize_company(a), normalize_company(b)
    if not na or not nb:
        return False
    if na == nb or difflib.SequenceMatcher(None, na, nb).ratio() >= COMPANY_THRESHOLD:
        return True
    # "Zeta" vs "Zeta Suite": the shorter name is the leading word(s) of the longer one.
    short, long_ = sorted((na.split(), nb.split()), key=len)
    return len(" ".join(short)) >= 4 and long_[: len(short)] == short


def same_title(a: Optional[str], b: Optional[str]) -> bool:
    na, nb = normalize_title(a), normalize_title(b)
    if not na or not nb:
        return False
    if _seniority(na) != _seniority(nb):
        return False
    return na == nb or difflib.SequenceMatcher(None, na, nb).ratio() >= TITLE_THRESHOLD


def compatible_locations(a: Optional[str], b: Optional[str]) -> bool:
    """Unknown or remote locations are compatible with anything; otherwise the cities must overlap."""
    ca, cb = geo.cities_in(a), geo.cities_in(b)
    if not ca or not cb:
        return True
    return bool(ca & cb)


def is_same_job(a, b) -> bool:
    """`a` and `b` are JobCreate-like objects (title, company, location, url / canonical_url)."""
    ua = getattr(a, "canonical_url", None) or canonical_url(getattr(a, "url", None))
    ub = getattr(b, "canonical_url", None) or canonical_url(getattr(b, "url", None))
    if ua and ub and ua == ub:
        return True
    return (
        same_company(a.company, b.company)
        and same_title(a.title, b.title)
        and compatible_locations(a.location, b.location)
    )


def _richness(job) -> tuple[int, int]:
    full = 1 if (getattr(job, "description_quality", None) or "full") == "full" else 0
    return full, len(job.description or "")


def merge_into(primary, other) -> None:
    """Fold `other` into `primary` (in place): union of sources, richest description, missing fields filled."""
    names = list(primary.source_names or ([primary.source] if primary.source else []))
    for name in (other.source_names or ([other.source] if other.source else [])):
        if name and name not in names:
            names.append(name)
    primary.source_names = names

    if _richness(other) > _richness(primary):
        primary.description = other.description
        primary.description_quality = other.description_quality
        if other.url:
            primary.url = other.url
            primary.canonical_url = other.canonical_url or canonical_url(other.url)
    for field in ("experience", "job_type", "location", "posted_date", "external_id"):
        if not getattr(primary, field, None) and getattr(other, field, None):
            setattr(primary, field, getattr(other, field))
    if not primary.company and other.company:
        primary.company = other.company


def dedupe_jobs(jobs: Iterable) -> tuple[list, int]:
    """
    Merge duplicates within one batch. Returns (unique jobs, number of jobs merged away).
    Order is preserved (first occurrence wins as the representative).
    """
    unique: list = []
    merged = 0
    for job in jobs:
        if not job.canonical_url and job.url:
            job.canonical_url = canonical_url(job.url)
        if not job.source_names and job.source:
            job.source_names = [job.source]
        match = next((u for u in unique if is_same_job(u, job)), None)
        if match is None:
            unique.append(job)
        else:
            merge_into(match, job)
            merged += 1
    return unique, merged
