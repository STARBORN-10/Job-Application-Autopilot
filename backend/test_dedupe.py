"""Offline tests for cross-source de-duplication (services/dedupe.py) and location helpers (services/geo.py)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from testing_utils import Checker

from schemas import JobCreate
from services import dedupe, geo


def job(title, company, location, source, url=None, description="", quality="full", **kw):
    return JobCreate(title=title, company=company, location=location, source=source, source_names=[source],
                     url=url, description=description, description_quality=quality, **kw)


def run():
    check = Checker("RUNNING OFFLINE DE-DUPLICATION TESTS")

    check.section("1. Canonical URLs")
    c = dedupe.canonical_url
    check(c("https://www.Example.com/jobs/123/?utm_source=x&utm_medium=api#apply") == "https://example.com/jobs/123",
          "Strips utm params, fragment, www, trailing slash; lower-cases host")
    check(c("http://example.com/job?id=7&gh_src=abc&ref=linkedin") == "https://example.com/job?id=7",
          "Keeps meaningful params (id), drops tracking (gh_src, ref)")
    check(c("https://example.com/job?b=2&a=1") == c("https://example.com/job?a=1&b=2"), "Query order does not matter")
    check(c("") is None and c(None) is None and c("not a url") is None, "Empty/invalid URLs give None")
    check(c("https://jobs.lever.co/cred/abc") != c("https://jobs.lever.co/cred/abd"), "Different paths stay different")

    check.section("2. Same job on JSearch + Adzuna + Jooble merges")
    full_desc = "We are hiring a Python Developer. " * 40
    js = job("Python Developer", "Blumetra Solutions Pvt Ltd", "Hyderabad, Telangana, India", "jsearch",
             url="https://careers.blumetra.com/jobs/42?utm_source=google", description=full_desc,
             experience="2-4 years", job_type="Full-time")
    az = job("Python Developer", "Blumetra", "Hyderabad, Telangana", "adzuna",
             url="https://www.adzuna.in/details/5966478742?utm_medium=api&utm_source=x",
             description="Python Developer ... snippet", quality="snippet")
    jb = job("Python Developer - 4-5 Years", "BLUMETRA SOLUTIONS PRIVATE LIMITED", "Hyderabad", "jooble",
             url="https://in.jooble.org/jdp/111", description="<b>Python</b> snippet", quality="snippet")
    unique, merged = dedupe.dedupe_jobs([az, jb, js])
    check(len(unique) == 1 and merged == 2, "Three listings of one job collapse into one")
    m = unique[0]
    check(set(m.source_names) == {"jsearch", "adzuna", "jooble"}, "Every source is recorded in source_names")
    check(m.description == full_desc and m.description_quality == "full", "The richest (full) description is kept")
    check(m.url.startswith("https://careers.blumetra.com"), "URL of the full-description listing is kept")
    check(m.experience == "2-4 years" and m.job_type == "Full-time", "Missing fields are filled from duplicates")

    same_url_a = job("Data Analyst", "Foo", "Pune", "jsearch", url="https://boards.greenhouse.io/foo/jobs/9?gh_src=1")
    same_url_b = job("Analyst, Data", "Foo Inc", "Remote", "ats", url="https://boards.greenhouse.io/foo/jobs/9")
    unique, merged = dedupe.dedupe_jobs([same_url_a, same_url_b])
    check(len(unique) == 1, "Same canonical URL merges even when titles differ")

    remote = job("Backend Developer (Remote)", "Zeta", "Remote", "adzuna")
    city = job("Backend Developer", "Zeta Suite", "Bengaluru, India", "jooble")
    check(len(dedupe.dedupe_jobs([remote, city])[0]) == 1, "Remote/unknown location is compatible with a city")

    check.section("3. Look-alikes that must NOT merge")
    base = job("Python Developer", "Acme Technologies", "Bengaluru", "jsearch")
    cases = [
        (job("Senior Python Developer", "Acme Technologies", "Bengaluru", "adzuna"), "Senior vs non-senior title"),
        (job("Python Developer Intern", "Acme Technologies", "Bengaluru", "adzuna"), "Intern vs regular role"),
        (job("Python Developer", "Apex Systems", "Bengaluru", "adzuna"), "Different company"),
        (job("Python Developer", "Acme Technologies", "Pune", "adzuna"), "Same company, different city"),
        (job("Java Developer", "Acme Technologies", "Bengaluru", "adzuna"), "Different technology"),
        (job("Python Developer", "", "Bengaluru", "adzuna"), "Missing company never fuzzy-merges"),
    ]
    for other, label in cases:
        unique, merged = dedupe.dedupe_jobs([base.model_copy(deep=True), other])
        check(len(unique) == 2 and merged == 0, f"Not merged: {label}")

    check.section("4. Normalisation helpers")
    check(dedupe.normalize_title("Python Backend Developer - 6-8 Years") == "python backend developer",
          "Trailing experience tag removed from titles")
    check(dedupe.normalize_company("Blumetra Solutions Pvt. Ltd.") == "blumetra", "Legal suffixes removed from company")
    check(dedupe.same_title("Data Scientist", "Data Scientist (Remote)"), "Bracketed notes are ignored in titles")
    check(dedupe.same_company("Zeta", "Zeta Suite") and not dedupe.same_company("Zeta", "Zepto"),
          "Company prefix match, but not merely similar names")

    check.section("5. Location matching (hard filter input)")
    prefs = ["Remote", "India"]
    check(geo.location_match("Bengaluru, Karnataka", prefs) == "match", "Indian city matches 'India'")
    check(geo.location_match("Remote", prefs) == "match", "Remote matches when Remote is preferred")
    check(geo.location_match("San Francisco, United States (Remote)", prefs) == "mismatch",
          "US-only remote does not match an India search")
    check(geo.location_match("London, UK", prefs) == "mismatch", "Foreign city is a mismatch")
    check(geo.location_match("Not Specified", prefs) == "unknown", "Unclear location is unknown (never filtered)")
    check(geo.location_match("Pune", ["Bengaluru"]) == "mismatch", "Different Indian city when only a city is preferred")
    check(geo.location_match("Bangalore", ["Bengaluru", "Remote"]) == "match", "City aliases (Bangalore = Bengaluru)")
    check(geo.location_match("Gurgaon, Haryana", ["Hybrid", "India"]) == "match", "Gurgaon matches India")
    check(geo.location_match("Anywhere", []) == "match", "No preferences means everything matches")

    check.done("DE-DUPLICATION")


if __name__ == "__main__":
    run()
