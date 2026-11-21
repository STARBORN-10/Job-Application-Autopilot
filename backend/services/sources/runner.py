"""
Runs every enabled + configured source independently.

Each source gets its own try/except and retry (services/retry.py), its own request cap per run and,
where set, a monthly budget tracked in api_usage. One failing source never stops the others. The
outcome of each source is written to source_health and returned in a per-source report.
"""
import datetime
import logging
import time
from dataclasses import dataclass, field
from typing import Optional

import httpx

import models
from services import usage
from services.redact import redact
from services.retry import retry_call
from services.sources import registry
from services.sources.base import FetchContext, JobSource, SourceBudgetExceeded, SourceQuery

logger = logging.getLogger("sources")


@dataclass
class SourcesResult:
    jobs: list = field(default_factory=list)
    report: dict = field(default_factory=dict)

    @property
    def ran(self) -> list[str]:
        return [n for n, r in self.report.items() if r["status"] in ("ok", "error")]

    @property
    def all_failed(self) -> bool:
        ran = self.ran
        return bool(ran) and all(self.report[n]["status"] == "error" for n in ran)


def _now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)


def _record_health(db, name: str, count: Optional[int], error: Optional[str]) -> None:
    try:
        row = db.query(models.SourceHealth).filter(models.SourceHealth.source_name == name).first()
        if row is None:
            row = models.SourceHealth(source_name=name, total_runs=0, last_count=0)
            db.add(row)
        row.total_runs = int(row.total_runs or 0) + 1
        if error is None:
            row.last_success_at = _now()
            row.last_count = count or 0
        else:
            row.last_error_at = _now()
            row.last_error = error[:500]
        db.commit()
    except Exception:
        logger.exception(f"Could not record health for source '{name}'")
        try:
            db.rollback()
        except Exception:
            pass


def _make_request_guard(db, source: JobSource, counter: dict):
    budget = source.monthly_budget()

    def request() -> None:
        if counter["requests"] >= source.max_requests_per_run:
            raise SourceBudgetExceeded(f"per-run cap of {source.max_requests_per_run} request(s) reached")
        if budget is not None and usage.get_count(db, source.name) >= budget:
            raise SourceBudgetExceeded(f"monthly budget of {budget} request(s) used up")
        counter["requests"] += 1
        usage.increment(db, source.name)

    return request


def _too_old(job, max_age_days: int) -> bool:
    posted = getattr(job, "posted_date", None)
    if not posted:
        return False
    if posted.tzinfo:
        posted = posted.astimezone(datetime.timezone.utc).replace(tzinfo=None)
    return (_now() - posted).days > max_age_days


def run_sources(
    db,
    query: SourceQuery,
    http_client: Optional[httpx.Client] = None,
    only: Optional[list[str]] = None,
) -> SourcesResult:
    """Fetch from every enabled source. `only` restricts the run to the named sources (tests / manual runs)."""
    result = SourcesResult()
    enabled = registry.enabled_map(db)
    settings = {"ats_companies": registry.get_ats_companies(db)}
    own_client = http_client is None
    client = http_client or httpx.Client(follow_redirects=True, headers={"User-Agent": "JobApplicationAutopilot/2.0"})

    try:
        for source in registry.ALL_SOURCES:
            entry = {"status": "", "count": 0, "fetched": 0, "stale_dropped": 0, "requests": 0,
                     "seconds": 0.0, "error": None, "warnings": []}
            result.report[source.name] = entry
            is_on = source.name in only if only is not None else enabled.get(source.name, False)
            if not is_on:
                entry["status"] = "disabled"
                continue
            if not source.is_configured():
                entry["status"] = "not_configured"
                entry["error"] = "Missing: " + ", ".join(source.missing_config())
                continue
            budget = source.monthly_budget()
            if budget is not None and usage.get_count(db, source.name) >= budget:
                entry["status"] = "skipped"
                entry["error"] = f"Monthly budget of {budget} request(s) used up"
                continue

            counter = {"requests": 0}
            ctx = FetchContext(client=client, request=_make_request_guard(db, source, counter), settings=settings)
            started = time.monotonic()
            try:
                jobs = retry_call(
                    lambda: source.fetch(query, ctx),
                    retry_on=source.transient_errors,
                    label=f"{source.label} fetch",
                )
                fresh = jobs if source.live_listings else [j for j in jobs if not _too_old(j, query.max_age_days)]
                entry.update(status="ok", fetched=len(jobs), count=len(fresh), stale_dropped=len(jobs) - len(fresh))
                result.jobs.extend(fresh)
                _record_health(db, source.name, len(fresh), None)
            except Exception as exc:
                message = redact(f"{type(exc).__name__}: {exc}")
                entry.update(status="error", error=message)
                logger.warning(f"Source '{source.name}' failed: {message}")
                _record_health(db, source.name, None, message)
            finally:
                entry["requests"] = counter["requests"]
                entry["seconds"] = round(time.monotonic() - started, 2)
                entry["warnings"] = [redact(w) for w in ctx.warnings][:10]
    finally:
        if own_client:
            client.close()
    return result
