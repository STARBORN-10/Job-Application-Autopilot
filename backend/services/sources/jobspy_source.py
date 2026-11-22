"""
Indeed India + LinkedIn via the optional `python-jobspy` package (experimental, OFF by default).

python-jobspy is not in requirements.txt (it pulls pandas and a TLS client); install it from
requirements-optional.txt to use this source. Without it, the source reports "not configured".
Naukri and Google are deliberately not used: in testing Naukri returned irrelevant results without
descriptions and Google returned nothing.
"""
import importlib.util
import math

from schemas import JobCreate
from services.sources.base import FetchContext, JobSource, SourceError, SourceQuery, SourceTransientError
from services.sources.common import experience_from_text, normalize_job_type, parse_datetime

SITES = ("indeed", "linkedin")


def _scrape(**kwargs):
    from jobspy import scrape_jobs  # imported lazily: optional dependency
    return scrape_jobs(**kwargs)


def _clean(value):
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    text = str(value).strip()
    return text if text and text.lower() not in ("nan", "none", "nat") else None


class JobSpySource(JobSource):
    name = "jobspy"
    label = "Indeed + LinkedIn (experimental, via python-jobspy)"
    description = ("Scrapes public Indeed India and LinkedIn search results (with descriptions). Slow, "
                   "may be rate limited or blocked, especially from cloud servers. Needs python-jobspy.")
    experimental = True
    default_enabled = False
    max_requests_per_run = 2
    results_wanted = 15

    def missing_config(self):
        return [] if importlib.util.find_spec("jobspy") else ["python-jobspy package"]

    def fetch(self, query: SourceQuery, ctx: FetchContext):
        ctx.request()
        try:
            frame = _scrape(
                site_name=list(SITES),
                search_term=query.search_terms,
                location=query.city or "India",
                country_indeed="India",
                results_wanted=self.results_wanted,
                hours_old=query.max_age_days * 24,
                linkedin_fetch_description=True,
                description_format="markdown",
            )
        except ImportError:
            raise SourceError("python-jobspy is not installed")
        except Exception as exc:  # the library raises many different exception types
            raise SourceTransientError(f"JobSpy scrape failed ({type(exc).__name__})")
        rows = frame.to_dict("records") if hasattr(frame, "to_dict") else list(frame or [])
        return [job for job in (self._normalize(r) for r in rows) if job]

    def _normalize(self, row: dict):
        title, company = _clean(row.get("title")), _clean(row.get("company"))
        if not title:
            return None
        description = _clean(row.get("description")) or ""
        location = _clean(row.get("location")) or ""
        if row.get("is_remote") is True:
            location = f"{location} (Remote)".strip()
        site = _clean(row.get("site")) or "jobspy"
        return JobCreate(
            title=title,
            company=company or "",
            url=_clean(row.get("job_url")) or _clean(row.get("job_url_direct")),
            location=location,
            description=description,
            job_type=normalize_job_type(_clean(row.get("job_type"))),
            experience=experience_from_text(title, description),
            source=self.name,
            source_names=[f"{self.name}:{site}"],
            external_id=_clean(row.get("id")),
            posted_date=parse_datetime(_clean(row.get("date_posted"))),
            description_quality="full" if len(description) > 600 else "snippet",
        )
