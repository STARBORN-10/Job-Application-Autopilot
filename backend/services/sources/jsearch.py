"""JSearch (RapidAPI) source: wraps the V1 jsearch_service. Free plan = 200 requests/month."""
from services import jsearch_service
from services.sources.base import FetchContext, JobSource, SourceError, SourceQuery


class JSearchSource(JobSource):
    name = "jsearch"
    label = "JSearch (Google Jobs via RapidAPI)"
    description = "Aggregated listings from Google for Jobs. Full descriptions. Free plan: 200 requests per month."
    required_env = ("RAPIDAPI_KEY",)
    max_requests_per_run = 2            # one search, plus one retry at most
    default_monthly_budget = 150        # keep a margin under the 200/month free plan
    transient_errors = (jsearch_service.JSearchNetworkError, jsearch_service.JSearchRateLimitError)

    def missing_config(self):
        import os
        return [] if (os.getenv("RAPIDAPI_KEY") or os.getenv("JSEARCH_API_KEY") or "").strip() else ["RAPIDAPI_KEY"]

    def fetch(self, query: SourceQuery, ctx: FetchContext):
        ctx.request()
        try:
            jobs = jsearch_service.fetch_jobs(
                active_role=query.role,
                preferred_locations=query.preferred_locations_text,
                num_pages=1,
                client=ctx.client,
            )
        except (jsearch_service.JSearchConfigError, jsearch_service.JSearchAuthError) as exc:
            raise SourceError(str(exc))
        for job in jobs:
            job.source = self.name
            job.source_names = [self.name]
            job.description_quality = "full"
        return jobs
