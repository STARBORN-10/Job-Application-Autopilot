"""
Hard filters (no AI): a job that fails one is not scored or saved.

- experience: the posting explicitly requires more years than the configured maximum (V1 behaviour)
- location: clearly outside the preferred locations (unclear locations pass; remote handled)
- job type: a known type that is not in the preferred types (when any are set)
- blocked company / blocked keyword (settings, case-insensitive whole-word match)
"""
import re
from dataclasses import dataclass
from typing import Optional

from services import geo
from services.sources.common import normalize_job_type


@dataclass
class FilterResult:
    name: str
    passed: bool
    detail: str

    def as_dict(self) -> dict:
        return {"name": self.name, "result": "pass" if self.passed else "fail", "detail": self.detail}


def _csv(value: Optional[str]) -> list[str]:
    return [v.strip() for v in (value or "").split(",") if v.strip()]


def _contains_word(haystack: str, needle: str) -> bool:
    return bool(re.search(rf"(?<![a-z0-9]){re.escape(needle.lower())}(?![a-z0-9])", haystack.lower()))


def experience_filter(min_years: Optional[float], settings) -> FilterResult:
    if not settings.filter_enabled or min_years is None:
        return FilterResult("experience", True, "no explicit minimum" if min_years is None else "filter disabled")
    if min_years > settings.max_years_experience:
        return FilterResult("experience", False,
                            f"requires {min_years:g}y, more than your maximum of {settings.max_years_experience}y")
    return FilterResult("experience", True, f"requires {min_years:g}y")


def run_hard_filters(job, settings, min_years: Optional[float]) -> list[FilterResult]:
    results = [experience_filter(min_years, settings)]

    verdict = geo.location_match(job.location, geo.split_preferences(settings.preferred_locations))
    results.append(FilterResult("location", verdict != "mismatch",
                                f"'{job.location or 'not specified'}' is {verdict} for '{settings.preferred_locations}'"))

    wanted_types = [normalize_job_type(t) for t in _csv(getattr(settings, "preferred_job_types", ""))]
    job_type = normalize_job_type(job.job_type)
    if wanted_types and job_type and job_type not in wanted_types:
        results.append(FilterResult("job_type", False, f"{job_type} is not in {', '.join(wanted_types)}"))
    else:
        results.append(FilterResult("job_type", True, job_type or "type not stated"))

    blocked = [c for c in _csv(getattr(settings, "blocked_companies", "")) if _contains_word(job.company or "", c)]
    results.append(FilterResult("blocked_company", not blocked,
                                f"company matches '{blocked[0]}'" if blocked else "not blocked"))

    text = f"{job.title or ''}\n{job.description or ''}"
    hits = [k for k in _csv(getattr(settings, "blocked_keywords", "")) if _contains_word(text, k)]
    results.append(FilterResult("blocked_keyword", not hits, f"mentions '{hits[0]}'" if hits else "none found"))
    return results


def first_failure(results: list[FilterResult]) -> Optional[FilterResult]:
    return next((r for r in results if not r.passed), None)
