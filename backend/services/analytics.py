"""
Analytics aggregation over stored jobs. Pure functions (no DB access) so they are easy to test.
All figures are computed on demand from the existing `jobs` table - no schema changes.
"""

import csv
import datetime
import io
from collections import Counter
from typing import Any, Dict, Iterable, List

STATUS_ORDER = ["To Apply", "Applied", "Interview", "Offer", "Rejected"]
SCORE_BUCKETS = [("0-4", 0.0, 5.0), ("5-6", 5.0, 7.0), ("7-8", 7.0, 9.0), ("9-10", 9.0, 10.01)]

CSV_COLUMNS = [
    "id", "title", "company", "location", "job_type", "experience", "source",
    "score", "status", "date_found", "url", "match_reason",
]


def _as_date(value: Any) -> datetime.date | None:
    if isinstance(value, datetime.datetime):
        return value.date()
    if isinstance(value, datetime.date):
        return value
    return None


def build_analytics(jobs: Iterable[Any], days: int = 30, today: datetime.date | None = None) -> Dict[str, Any]:
    """Aggregate job records into dashboard-ready statistics."""
    jobs = list(jobs)
    today = today or datetime.date.today()

    scores = [j.score for j in jobs if isinstance(j.score, (int, float))]
    status_counts = Counter((j.status or "To Apply") for j in jobs)

    # Funnel: every known status first (in pipeline order), then any custom ones.
    funnel = [{"status": s, "count": status_counts.get(s, 0)} for s in STATUS_ORDER]
    funnel += [{"status": s, "count": c} for s, c in status_counts.items() if s not in STATUS_ORDER]

    score_distribution = [
        {"range": label, "count": sum(1 for s in scores if lo <= s < hi)}
        for label, lo, hi in SCORE_BUCKETS
    ]

    start = today - datetime.timedelta(days=days - 1)
    per_day = Counter()
    for j in jobs:
        d = _as_date(j.date_found)
        if d and start <= d <= today:
            per_day[d] += 1
    jobs_over_time = [
        {"date": (start + datetime.timedelta(days=i)).isoformat(),
         "count": per_day.get(start + datetime.timedelta(days=i), 0)}
        for i in range(days)
    ]

    top_companies = Counter(j.company for j in jobs if j.company).most_common(5)
    # V1 stored "JSearch"; V2 sources use lower-case ids ("jsearch", "adzuna", ...): group case-insensitively.
    sources = Counter((j.source or "unknown").strip().lower() for j in jobs)

    applied_or_later = sum(c for s, c in status_counts.items() if s not in ("To Apply",))
    interviews = status_counts.get("Interview", 0) + status_counts.get("Offer", 0)

    return {
        "total_jobs": len(jobs),
        "average_score": round(sum(scores) / len(scores), 1) if scores else 0.0,
        "applied_count": applied_or_later,
        "application_rate": round(100 * applied_or_later / len(jobs), 1) if jobs else 0.0,
        "interview_rate": round(100 * interviews / applied_or_later, 1) if applied_or_later else 0.0,
        "funnel": funnel,
        "score_distribution": score_distribution,
        "jobs_over_time": jobs_over_time,
        "top_companies": [{"company": c, "count": n} for c, n in top_companies],
        "sources": [{"source": s, "count": n} for s, n in sources.most_common()],
    }


def jobs_to_csv(jobs: Iterable[Any]) -> str:
    """Render jobs as CSV text (replaces the old Make.com -> Google Sheets log)."""
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(CSV_COLUMNS)
    for j in jobs:
        row: List[Any] = []
        for col in CSV_COLUMNS:
            value = getattr(j, col, "")
            if isinstance(value, datetime.datetime):
                value = value.isoformat(timespec="seconds")
            value = "" if value is None else str(value)
            # Neutralise spreadsheet formula injection (cells starting with = + - @)
            if value and value[0] in ("=", "+", "-", "@") and col not in ("id", "score"):
                value = "'" + value
            row.append(value)
        writer.writerow(row)
    return buf.getvalue()
