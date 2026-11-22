"""Adzuna India source (official API). Descriptions are ~500-character snippets."""
import os

from schemas import JobCreate
from services.sources.base import FetchContext, JobSource, SourceError, SourceQuery, http_get
from services.sources.common import clean_company, experience_from_text, normalize_job_type, parse_datetime, strip_html

API_URL = "https://api.adzuna.com/v1/api/jobs/{country}/search/{page}"


class AdzunaSource(JobSource):
    name = "adzuna"
    label = "Adzuna India"
    description = "Official Adzuna job search API for India. Descriptions are short snippets."
    required_env = ("ADZUNA_APP_ID", "ADZUNA_APP_KEY")
    description_quality = "snippet"
    max_requests_per_run = 3

    def fetch(self, query: SourceQuery, ctx: FetchContext):
        params = {
            "app_id": os.getenv("ADZUNA_APP_ID", "").strip(),
            "app_key": os.getenv("ADZUNA_APP_KEY", "").strip(),
            "what": query.search_terms,
            "results_per_page": 50,
            "max_days_old": query.max_age_days,
            "content-type": "application/json",
        }
        if query.city:
            params["where"] = query.city
        url = API_URL.format(country=(query.country_code or "in"), page=1)
        response = http_get(ctx, url, "Adzuna", params=params)
        try:
            data = response.json()
        except ValueError:
            raise SourceError("Adzuna returned a non-JSON response")
        return [job for job in (self._normalize(item) for item in data.get("results") or []) if job]

    def _normalize(self, item: dict):
        if not isinstance(item, dict):
            return None
        title = strip_html(item.get("title"))
        if not title:
            return None
        company = clean_company((item.get("company") or {}).get("display_name"))
        location = (item.get("location") or {}).get("display_name") or ""
        description = strip_html(item.get("description"))
        job_type = normalize_job_type(item.get("contract_time")) or normalize_job_type(item.get("contract_type"))
        return JobCreate(
            title=title,
            company=company,
            url=item.get("redirect_url"),
            location=location,
            description=description,
            job_type=job_type,
            experience=experience_from_text(title, description),
            source=self.name,
            source_names=[self.name],
            external_id=str(item.get("id")) if item.get("id") else None,
            posted_date=parse_datetime(item.get("created")),
            description_quality="snippet",
        )
