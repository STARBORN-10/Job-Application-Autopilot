"""
Amazon Jobs India (public careers search JSON, no key).

This is the same JSON feed that amazon.jobs itself uses, read at low volume (one request per run).
It is not an official, documented API, so the source is health-tracked like the others and can be
switched off in Settings if Amazon changes it. Postings carry full descriptions plus basic and
preferred qualifications. India only: other country codes return nothing.
"""
import datetime
from typing import Optional

from schemas import JobCreate
from services import matching
from services.sources.base import FetchContext, JobSource, SourceError, SourceQuery, http_get
from services.sources.common import experience_from_text, normalize_job_type, strip_html

SEARCH_URL = "https://www.amazon.jobs/en/search.json"
SITE = "https://www.amazon.jobs"


def _posted(value: Optional[str]) -> Optional[datetime.datetime]:
    """Amazon writes dates like 'November 20, 2026'."""
    if not value:
        return None
    for fmt in ("%B %d, %Y", "%b %d, %Y"):
        try:
            return datetime.datetime.strptime(value.strip(), fmt)
        except ValueError:
            continue
    return None


class AmazonJobsSource(JobSource):
    name = "amazon"
    label = "Amazon Jobs India"
    description = ("Amazon's public careers search for India. No key needed. Full descriptions with qualifications. "
                   "Unofficial feed: switch it off if it ever stops working.")
    live_listings = True            # open positions, not dated ads: skip the age filter
    max_requests_per_run = 1

    def fetch(self, query: SourceQuery, ctx: FetchContext):
        if (query.country_code or "in").lower() != "in":
            return []
        params = {"base_query": query.search_terms, "country": "IND", "result_limit": 50, "sort": "recent"}
        response = http_get(ctx, SEARCH_URL, "Amazon Jobs", params=params, timeout=30.0)
        try:
            data = response.json()
        except ValueError:
            raise SourceError("Amazon Jobs returned a non-JSON response")
        jobs = [self._normalize(item) for item in data.get("jobs") or []]
        return [j for j in jobs if j and matching.is_relevant(j.title, query.role, j.description)]

    def _normalize(self, item: dict) -> Optional[JobCreate]:
        if not isinstance(item, dict):
            return None
        title = strip_html(item.get("title"))
        path = item.get("job_path")
        if not title or not path:
            return None
        parts = [strip_html(item.get("description"))]
        if item.get("basic_qualifications"):
            parts.append("Basic qualifications\n" + strip_html(item["basic_qualifications"]))
        if item.get("preferred_qualifications"):
            parts.append("Preferred qualifications\n" + strip_html(item["preferred_qualifications"]))
        description = "\n\n".join(p for p in parts if p)
        job_type = "Internship" if item.get("is_intern") else normalize_job_type(item.get("job_schedule_type"))
        location = item.get("normalized_location") or item.get("location") or ""
        return JobCreate(
            title=title,
            company="Amazon",
            url=SITE + path,
            location=location.replace(", IND", ", India"),
            description=description,
            job_type=job_type,
            experience=experience_from_text(title, description),
            source=self.name,
            source_names=[self.name],
            external_id=str(item.get("id_icims") or item.get("id") or "") or None,
            posted_date=_posted(item.get("posted_date")),
            description_quality="full",
        )
