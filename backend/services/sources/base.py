"""
Job source plugin interface.

A source turns a SourceQuery into a list of JobCreate objects. Sources never touch the database or
the network budget directly: every outgoing request goes through FetchContext.request(), which
enforces the per-run cap and the monthly budget, and records usage.
"""
import os
from dataclasses import dataclass, field
from typing import Callable, Optional

import httpx

from schemas import JobCreate


class SourceError(Exception):
    """A source failed in a way that a retry will not fix (bad key, unexpected response, ...)."""


class SourceTransientError(SourceError):
    """Timeout, connection problem, rate limit or server error: worth retrying."""


class SourceBudgetExceeded(SourceError):
    """The per-run cap or the monthly request budget for this source is used up."""


@dataclass
class SourceQuery:
    role: str
    locations: list[str] = field(default_factory=list)   # e.g. ["Remote", "India", "Bengaluru"]
    max_age_days: int = 30
    country_code: Optional[str] = "in"

    @property
    def preferred_locations_text(self) -> str:
        return ", ".join(self.locations)

    @property
    def search_terms(self) -> str:
        """Role as plain search words ("AI/ML Engineer" -> "AI ML Engineer")."""
        return " ".join(self.role.replace("/", " ").split()) or "Software Developer"

    @property
    def city(self) -> Optional[str]:
        """First preferred location that is a place (not Remote/Hybrid/the country itself)."""
        for loc in self.locations:
            if loc.strip().lower() not in ("remote", "hybrid", "india", "in", "anywhere", "work from home"):
                return loc.strip()
        return None


@dataclass
class FetchContext:
    """Per-source, per-run helpers handed to JobSource.fetch()."""
    client: httpx.Client
    request: Callable[[], None]          # call before every outgoing HTTP request
    settings: dict = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)   # partial failures worth showing (e.g. one board down)


class JobSource:
    name: str = ""                 # stable id used in settings, health and source_names
    label: str = ""                # human readable
    description: str = ""
    experimental: bool = False     # scraped / may break
    default_enabled: bool = True
    required_env: tuple[str, ...] = ()
    description_quality: str = "full"
    live_listings: bool = False    # postings are live openings (ATS boards): skip the age filter
    max_requests_per_run: int = 5
    default_monthly_budget: Optional[int] = None
    transient_errors: tuple[type[BaseException], ...] = (SourceTransientError,)

    def missing_config(self) -> list[str]:
        return [name for name in self.required_env if not (os.getenv(name) or "").strip()]

    def is_configured(self) -> bool:
        return not self.missing_config()

    def monthly_budget(self) -> Optional[int]:
        raw = os.getenv(f"{self.name.upper()}_MONTHLY_BUDGET")
        if raw:
            try:
                return max(0, int(raw))
            except ValueError:
                pass
        return self.default_monthly_budget

    def fetch(self, query: SourceQuery, ctx: FetchContext) -> list[JobCreate]:
        raise NotImplementedError


def check_response(response: httpx.Response, source_label: str) -> None:
    """Map HTTP status codes onto the source error hierarchy (never includes the URL: it may hold keys)."""
    code = response.status_code
    if code == 429 or code >= 500:
        raise SourceTransientError(f"{source_label} returned HTTP {code}")
    if code in (401, 403):
        raise SourceError(f"{source_label} rejected the credentials (HTTP {code})")
    if code >= 400:
        raise SourceError(f"{source_label} returned HTTP {code}")


def http_get(ctx: FetchContext, url: str, label: str, **kwargs) -> httpx.Response:
    ctx.request()
    try:
        response = ctx.client.get(url, timeout=kwargs.pop("timeout", 20.0), **kwargs)
    except httpx.TimeoutException:
        raise SourceTransientError(f"{label} timed out")
    except httpx.RequestError as exc:
        raise SourceTransientError(f"{label} connection failed ({type(exc).__name__})")
    check_response(response, label)
    return response


def http_post(ctx: FetchContext, url: str, label: str, **kwargs) -> httpx.Response:
    ctx.request()
    try:
        response = ctx.client.post(url, timeout=kwargs.pop("timeout", 20.0), **kwargs)
    except httpx.TimeoutException:
        raise SourceTransientError(f"{label} timed out")
    except httpx.RequestError as exc:
        raise SourceTransientError(f"{label} connection failed ({type(exc).__name__})")
    check_response(response, label)
    return response
