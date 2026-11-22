"""
Public ATS job boards (no key): Greenhouse, Lever and Ashby.

Boards list every opening of a company, worldwide and in every department, so results are filtered
to the user's preferred locations (by location text; Lever's country field is used when present)
and to the active role (title / description relevance).
"""
import os
import time

from schemas import JobCreate
from services import geo, matching
from services.sources.base import FetchContext, JobSource, SourceError, SourceQuery, SourceTransientError, http_get
from services.sources.common import normalize_job_type, parse_datetime, strip_html, experience_from_text

DEFAULT_ATS_COMPANIES = [
    {"provider": "greenhouse", "token": "groww", "name": "Groww"},
    {"provider": "greenhouse", "token": "databricks", "name": "Databricks"},
    {"provider": "greenhouse", "token": "stripe", "name": "Stripe"},
    # Verified in November 2026: each board lists many India openings.
    {"provider": "greenhouse", "token": "razorpaysoftwareprivatelimited", "name": "Razorpay"},
    {"provider": "greenhouse", "token": "zscaler", "name": "Zscaler"},
    {"provider": "greenhouse", "token": "okta", "name": "Okta"},
    {"provider": "greenhouse", "token": "mongodb", "name": "MongoDB"},
    {"provider": "ashby", "token": "sarvam", "name": "Sarvam AI"},
    {"provider": "lever", "token": "cred", "name": "CRED"},
    {"provider": "lever", "token": "meesho", "name": "Meesho"},
    {"provider": "lever", "token": "paytm", "name": "Paytm"},
    {"provider": "lever", "token": "zeta", "name": "Zeta"},
    {"provider": "ashby", "token": "notion", "name": "Notion"},
    {"provider": "ashby", "token": "openai", "name": "OpenAI"},
]

URLS = {
    "greenhouse": "https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true",
    "lever": "https://api.lever.co/v0/postings/{token}?mode=json",
    "ashby": "https://api.ashbyhq.com/posting-api/job-board/{token}",
}


def _delay() -> float:
    try:
        return max(0.0, float(os.getenv("ATS_REQUEST_DELAY_SECONDS", "0.5")))
    except ValueError:
        return 0.5


class AtsBoardsSource(JobSource):
    name = "ats"
    label = "Company career boards (Greenhouse / Lever / Ashby)"
    description = ("Public job boards of the companies in your list. No key needed. Full descriptions. "
                   "Filtered to your preferred locations and active role.")
    live_listings = True
    max_requests_per_run = 25

    def fetch(self, query: SourceQuery, ctx: FetchContext):
        companies = ctx.settings.get("ats_companies") or DEFAULT_ATS_COMPANIES
        jobs: list[JobCreate] = []
        failures: list[str] = []
        for i, company in enumerate(companies[: self.max_requests_per_run]):
            if i:
                time.sleep(_delay())
            provider, token = company.get("provider"), company.get("token")
            if provider not in URLS or not token:
                continue
            label = f"{provider}:{token}"
            try:
                response = http_get(ctx, URLS[provider].format(token=token), label, timeout=30.0)
                data = response.json()
            except (SourceError, ValueError) as exc:
                # One broken board (renamed, removed) must not hide the others.
                failures.append(f"{label} ({exc})" if isinstance(exc, SourceError) else f"{label} (bad JSON)")
                continue
            name = company.get("name") or token
            raw = {"greenhouse": self._greenhouse, "lever": self._lever, "ashby": self._ashby}[provider](data, name)
            jobs.extend(j for j in raw if self._keep(j, query))
        if failures and not jobs and len(failures) == len(companies[: self.max_requests_per_run]):
            raise SourceTransientError("All ATS boards failed: " + "; ".join(failures[:5]))
        ctx.warnings.extend(failures)
        return jobs

    @staticmethod
    def _keep(job: JobCreate, query: SourceQuery) -> bool:
        if geo.location_match(job.location, query.locations) != "match":
            return False
        return matching.is_relevant(job.title, query.role, job.description)

    def _job(self, **kw) -> JobCreate:
        description = kw.pop("description", "") or ""
        return JobCreate(
            source=self.name,
            source_names=[self.name],
            description=description,
            description_quality="full",
            experience=experience_from_text(kw.get("title"), description),
            **kw,
        )

    def _greenhouse(self, data: dict, company: str) -> list[JobCreate]:
        out = []
        for item in (data or {}).get("jobs") or []:
            title = (item.get("title") or "").strip()
            if not title:
                continue
            location = (item.get("location") or {}).get("name") or ""
            offices = ", ".join(o.get("location") or o.get("name") or "" for o in item.get("offices") or [])
            out.append(self._job(
                title=title,
                company=item.get("company_name") or company,
                url=item.get("absolute_url"),
                location=location if location else offices,
                description=strip_html(item.get("content")),
                external_id=str(item.get("id")) if item.get("id") else None,
                posted_date=parse_datetime(item.get("first_published") or item.get("updated_at")),
            ))
        return out

    def _lever(self, data: list, company: str) -> list[JobCreate]:
        out = []
        for item in data if isinstance(data, list) else []:
            title = (item.get("text") or "").strip()
            if not title:
                continue
            cats = item.get("categories") or {}
            locations = cats.get("allLocations") or [cats.get("location") or ""]
            location = ", ".join(l for l in locations if l)
            if (item.get("country") or "").upper() == "IN" and "india" not in location.lower():
                location = f"{location}, India".strip(", ")
            if (item.get("workplaceType") or "").lower() == "remote":
                location = f"{location} (Remote)".strip()
            parts = [item.get("descriptionPlain") or strip_html(item.get("description"))]
            for lst in item.get("lists") or []:
                parts.append(f"{lst.get('text') or ''}\n{strip_html(lst.get('content'))}")
            parts.append(item.get("additionalPlain") or "")
            out.append(self._job(
                title=title,
                company=company,
                url=item.get("hostedUrl"),
                location=location,
                description="\n\n".join(p.strip() for p in parts if p and p.strip()),
                job_type=normalize_job_type(cats.get("commitment")),
                external_id=item.get("id"),
                posted_date=parse_datetime(item.get("createdAt")),
            ))
        return out

    def _ashby(self, data: dict, company: str) -> list[JobCreate]:
        out = []
        for item in (data or {}).get("jobs") or []:
            title = (item.get("title") or "").strip()
            if not title or item.get("isListed") is False:
                continue
            places = [item.get("location") or ""] + [s.get("location") or "" for s in item.get("secondaryLocations") or []]
            country = (((item.get("address") or {}).get("postalAddress") or {}).get("addressCountry")) or ""
            location = ", ".join(p for p in places if p)
            if country and country.lower() not in location.lower():
                location = f"{location}, {country}".strip(", ")
            if item.get("isRemote") or (item.get("workplaceType") or "").lower() == "remote":
                location = f"{location} (Remote)".strip()
            out.append(self._job(
                title=title,
                company=company,
                url=item.get("jobUrl"),
                location=location,
                description=item.get("descriptionPlain") or strip_html(item.get("descriptionHtml")),
                job_type=normalize_job_type(item.get("employmentType")),
                external_id=item.get("id"),
                posted_date=parse_datetime(item.get("publishedAt")),
            ))
        return out
