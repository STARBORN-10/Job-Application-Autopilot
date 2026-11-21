"""Jooble India source (official API, key in the URL path). Snippets only."""
import os

from schemas import JobCreate
from services.sources.base import FetchContext, JobSource, SourceError, SourceQuery, http_post
from services.sources.common import clean_company, experience_from_text, normalize_job_type, parse_datetime, strip_html

API_URL = "https://in.jooble.org/api/{key}"


class JoobleSource(JobSource):
    name = "jooble"
    label = "Jooble India"
    description = "Official Jooble API (aggregates Indian job boards). Descriptions are short snippets."
    required_env = ("JOOBLE_API_KEY",)
    description_quality = "snippet"
    max_requests_per_run = 3

    def fetch(self, query: SourceQuery, ctx: FetchContext):
        body = {"keywords": query.search_terms, "location": query.city or "", "page": "1"}
        url = API_URL.format(key=os.getenv("JOOBLE_API_KEY", "").strip())
        response = http_post(ctx, url, "Jooble", json=body)
        try:
            data = response.json()
        except ValueError:
            raise SourceError("Jooble returned a non-JSON response")
        return [job for job in (self._normalize(item) for item in data.get("jobs") or []) if job]

    def _normalize(self, item: dict):
        if not isinstance(item, dict):
            return None
        title = strip_html(item.get("title"))
        if not title:
            return None
        snippet = strip_html(item.get("snippet")).strip(" .…")
        return JobCreate(
            title=title,
            company=clean_company(item.get("company")),
            url=item.get("link"),
            location=strip_html(item.get("location")),
            description=snippet,
            job_type=normalize_job_type(item.get("type")),
            experience=experience_from_text(title, snippet),
            source=self.name,
            source_names=[self.name],
            external_id=str(item.get("id")) if item.get("id") is not None else None,
            posted_date=parse_datetime(item.get("updated")),
            description_quality="snippet",
        )
