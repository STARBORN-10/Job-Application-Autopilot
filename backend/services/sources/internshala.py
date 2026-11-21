"""
Internshala (experimental scraper, OFF by default).

Policy: only clean public listing pages (no query strings, no /api/ paths: robots.txt disallows
those), one page of jobs and one of internships per run, at most one request per second, results
cached in memory, no login. Card text is a short snippet.
"""
import datetime
import html
import os
import re
import time

from schemas import JobCreate
from services.sources.base import FetchContext, JobSource, SourceError, SourceQuery, http_get
from services.sources.common import experience_from_text, normalize_job_type, strip_html

BASE = "https://internshala.com"
USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/130.0 Safari/537.36")

# Role -> (jobs slug, internships slug). Unknown roles fall back to the role words.
ROLE_SLUGS = {
    "ai/ml engineer": ("machine-learning", "machine-learning"),
    "data analyst": ("data-analytics", "data-analytics"),
    "backend developer": ("backend-development", "backend-development"),
    "python developer": ("python-developer", "python"),
}

_CARD_START = re.compile(r'<div class="container-fluid individual_internship\b')
_cache: dict[str, tuple[float, str]] = {}
_last_request = [0.0]


def _slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def listing_urls(role: str) -> list[str]:
    jobs_slug, intern_slug = ROLE_SLUGS.get(role.strip().lower(), (_slugify(role), _slugify(role)))
    return [f"{BASE}/jobs/{jobs_slug}-jobs", f"{BASE}/internships/{intern_slug}-internship"]


def _text(fragment: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", fragment))).strip()


def _first(pattern: str, chunk: str) -> str:
    m = re.search(pattern, chunk, re.S)
    return _text(m.group(1)) if m else ""


def _posted(label: str, now: datetime.datetime) -> datetime.datetime | None:
    label = label.lower()
    if not label:
        return None
    if any(w in label for w in ("today", "just now", "hour", "minute", "few")):
        return now
    m = re.search(r"(\d+)\s*(day|week|month)", label)
    if not m:
        return None
    n = int(m.group(1))
    days = {"day": 1, "week": 7, "month": 30}[m.group(2)] * n
    return now - datetime.timedelta(days=days)


def parse_listing(page_html: str, now: datetime.datetime | None = None) -> list[dict]:
    """Parse the job/internship cards of one listing page (stops at the 'no more results' banner)."""
    now = now or datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
    banner = page_html.find("no_opening_banner")
    if banner != -1:
        page_html = page_html[:banner]
    starts = [m.start() for m in _CARD_START.finditer(page_html)]
    cards = []
    for i, start in enumerate(starts):
        chunk = page_html[start: starts[i + 1] if i + 1 < len(starts) else len(page_html)]
        link = re.search(r'<a[^>]*class="job-title-href"[^>]*href="([^"?]+)"[^>]*>(.*?)</a>', chunk, re.S)
        if not link:
            continue
        kind = (re.search(r'employment_type="(\w+)"', chunk) or [None, "job"])[1]
        locations = [_text(x) for x in re.findall(r"<a[^>]*>(.*?)</a>", _first_block(chunk, "locations"))]
        experience = _first(r'ic-16-briefcase"></i>\s*<span>(.*?)</span>', chunk)
        labels = [_text(x) for x in re.findall(r'<div class="status-li[^"]*">.*?<span>(.*?)</span>', chunk, re.S)]
        cards.append({
            "kind": kind,
            "title": _text(link.group(2)),
            "url": BASE + link.group(1),
            "company": _first(r'<p class="company-name">(.*?)</p>', chunk),
            "locations": [l for l in locations if l],
            "experience": experience,
            "about": _first(r'<div class="about_job">.*?<div class="text">(.*?)</div>', chunk),
            "skills": [_text(x) for x in re.findall(r"<div class='job_skill'>(.*?)</div>", chunk)],
            "posted": _posted(_first(r'ic-16-reschedule"></i>\s*<span>(.*?)</span>', chunk), now),
            "labels": labels,
            "id": (re.search(r'internshipId="(\d+)"', chunk) or [None, None])[1],
        })
    return cards


def _first_block(chunk: str, css_class: str) -> str:
    m = re.search(rf'class="row-1-item\s+{css_class}\s*">(.*?)</(?:p|div)>', chunk, re.S)
    return m.group(1) if m else ""


class InternshalaSource(JobSource):
    name = "internshala"
    label = "Internshala (experimental scraper)"
    description = ("Public Internshala listing pages for your role: one jobs page and one internships page "
                   "per run, max 1 request/second, cached. Snippets only. May break if the site changes.")
    experimental = True
    default_enabled = False
    description_quality = "snippet"
    max_requests_per_run = 2

    def fetch(self, query: SourceQuery, ctx: FetchContext):
        jobs: list[JobCreate] = []
        for url in listing_urls(query.role)[: self.max_requests_per_run]:
            jobs.extend(self._to_jobs(parse_listing(self._get(url, ctx))))
        return jobs

    def _get(self, url: str, ctx: FetchContext) -> str:
        if "?" in url or "," in url or "%" in url or "/api/" in url:
            raise SourceError("Refusing a URL that Internshala's robots.txt disallows")
        ttl = float(os.getenv("INTERNSHALA_CACHE_HOURS", "6") or 6) * 3600
        cached = _cache.get(url)
        if cached and time.time() - cached[0] < ttl:
            return cached[1]
        wait = 1.1 - (time.monotonic() - _last_request[0])
        if wait > 0:
            time.sleep(wait)
        _last_request[0] = time.monotonic()
        response = http_get(ctx, url, "Internshala", headers={"User-Agent": USER_AGENT}, follow_redirects=False)
        _cache[url] = (time.time(), response.text)
        return response.text

    def _to_jobs(self, cards: list[dict]) -> list[JobCreate]:
        out = []
        for card in cards:
            internship = card["kind"] == "internship"
            remote = any("work from home" in l.lower() for l in card["locations"])
            places = [l for l in card["locations"] if "work from home" not in l.lower()]
            location = ", ".join(places) + (", India" if places else "")
            if remote:
                location = f"{location} (Remote)".strip() if location else "Remote, India"
            label_type = next((normalize_job_type(l) for l in card["labels"] if normalize_job_type(l) != l), None)
            description = card["about"]
            if card["skills"]:
                description = f"{description}\nSkills: {', '.join(card['skills'])}".strip()
            out.append(JobCreate(
                title=card["title"],
                company=card["company"],
                url=card["url"],
                location=location or "India",
                description=strip_html(description),
                job_type="Internship" if internship else (label_type or "Full-time"),
                experience="Fresher" if internship else (experience_from_text(card["experience"]) or card["experience"] or None),
                source=self.name,
                source_names=[self.name],
                external_id=card["id"],
                posted_date=card["posted"],
                description_quality="snippet",
            ))
        return out
