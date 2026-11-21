"""
Offline tests for the V2 job sources: Adzuna, Jooble, ATS boards, Internshala, JobSpy and JSearch
normalisation; the runner (isolation, retry, health, budgets, age filter); the sources API;
the trigger cooldown and the persisted run status. All HTTP is mocked.
"""
import datetime
import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent))

from testing_utils import Checker, fixture_json, fixture_text, mock_client, use_temp_database

use_temp_database()
os.environ["ADZUNA_APP_ID"] = "test-app-id"
os.environ["ADZUNA_APP_KEY"] = "test-app-key-123"
os.environ["JOOBLE_API_KEY"] = "test-jooble-key"
os.environ["RAPIDAPI_KEY"] = "test-rapid-key"
os.environ["ATS_REQUEST_DELAY_SECONDS"] = "0"
os.environ.pop("JSEARCH_MONTHLY_BUDGET", None)

import httpx
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

import crud, models, schemas
from database import engine, get_db
import db_migrations
from main import app
from security import trigger_cooldown
from services import pipeline, usage
from services.sources import internshala, registry, runner
from services.sources.base import SourceQuery
from services.sources.jobspy_source import JobSpySource

db_migrations.upgrade_database(engine)
Session = sessionmaker(bind=engine)

QUERY = SourceQuery(role="Python Developer", locations=["Remote", "India"], max_age_days=30)


def ok_json(data):
    return lambda request: httpx.Response(200, json=data)


def recent(days=1):
    return (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")


def run():
    check = Checker("RUNNING OFFLINE JOB SOURCE TESTS")
    db = Session()

    # ------------------------------------------------------------------
    check.section("1. Adzuna")
    adzuna_data = fixture_json("adzuna_in.json")
    for item in adzuna_data["results"]:  # keep the test independent of today's date
        if not item["created"].startswith("2024"):
            item["created"] = recent(3)
    seen = []
    client = mock_client({"api.adzuna.com": ok_json(adzuna_data)}, seen)
    res = runner.run_sources(db, QUERY, http_client=client, only=["adzuna"])
    rep = res.report["adzuna"]
    req = seen[0]
    check(rep["status"] == "ok" and rep["fetched"] == 6, "Adzuna fixture parsed (6 results)")
    check(rep["stale_dropped"] == 2 and rep["count"] == 4, "Two 2024 postings dropped by the 30-day age filter")
    check(req.url.path == "/v1/api/jobs/in/search/1", "India endpoint, page 1")
    check(req.url.params["what"] == "Python Developer" and req.url.params["max_days_old"] == "30", "what + max_days_old sent")
    check(all(j.description_quality == "snippet" and j.source == "adzuna" for j in res.jobs), "Marked as snippet, source adzuna")
    hyd = next(j for j in res.jobs if j.company == "Blumetra")
    check(hyd.experience == "4–5 Years" and hyd.job_type == "Full-time", "Experience and job type extracted")
    check(hyd.posted_date is not None, "Posted date parsed")
    from services.sources.common import clean_company
    check(clean_company("Checking your browser before redirecting") == "" and clean_company("<b>Acme</b>") == "Acme",
          "Bot-check page titles are not used as company names")

    # ------------------------------------------------------------------
    check.section("2. Jooble")
    jooble_data = fixture_json("jooble_in.json")
    for item in jooble_data["jobs"]:
        item["updated"] = recent(2)
    seen = []
    client = mock_client({"in.jooble.org": ok_json(jooble_data)}, seen)
    res = runner.run_sources(db, QUERY, http_client=client, only=["jooble"])
    body = json.loads(seen[0].read())
    check(res.report["jooble"]["count"] == 6, "Jooble fixture parsed (6 jobs)")
    check(seen[0].method == "POST" and body["keywords"] == "Python Developer", "POST with keywords")
    check(all("<b>" not in j.description and "&nbsp;" not in j.description for j in res.jobs), "HTML stripped from snippets")
    check(res.jobs[0].experience == "3 - 4 Years", "Experience read from the title/snippet")

    # ------------------------------------------------------------------
    check.section("3. ATS boards (Greenhouse / Lever / Ashby)")
    gh = {"jobs": [
        {"id": 1, "title": "Backend Engineer - Python", "absolute_url": "https://boards.greenhouse.io/acme/jobs/1",
         "location": {"name": "Bengaluru, India"}, "updated_at": recent(3),
         "content": "&lt;p&gt;Build APIs in &lt;b&gt;Python&lt;/b&gt; and Django.&lt;/p&gt;", "company_name": "Acme"},
        {"id": 2, "title": "Python Developer", "absolute_url": "https://boards.greenhouse.io/acme/jobs/2",
         "location": {"name": "Berlin, Germany"}, "updated_at": recent(3), "content": "Python"},
        {"id": 3, "title": "Accounts Manager", "absolute_url": "https://boards.greenhouse.io/acme/jobs/3",
         "location": {"name": "Mumbai, India"}, "updated_at": recent(3), "content": "Finance"},
    ]}
    lever = [
        {"id": "a1", "text": "Software Engineer, Backend", "hostedUrl": "https://jobs.lever.co/beta/a1", "country": "IN",
         "categories": {"location": "Pune", "commitment": "Full time"}, "createdAt": 1790573982021,
         "descriptionPlain": "We use Python and PostgreSQL.", "lists": [{"text": "Requirements", "content": "<li>Python</li>"}]},
        {"id": "a2", "text": "Python Developer", "hostedUrl": "https://jobs.lever.co/beta/a2", "country": "US",
         "categories": {"location": "New York"}, "createdAt": 1790573982021, "descriptionPlain": "Python"},
    ]
    ashby = fixture_json("ashby_notion.json")
    ashby["jobs"].append({"id": "x9", "title": "Python Developer Intern", "jobUrl": "https://jobs.ashbyhq.com/n/x9",
                          "location": "Remote", "isRemote": True, "employmentType": "Intern",
                          "publishedAt": recent(1), "descriptionPlain": "Python"})
    calls = {"n": 0}

    def gh_handler(request):
        calls["n"] += 1
        return httpx.Response(200, json=gh) if "acme" in request.url.path else httpx.Response(404, json={})

    client = mock_client({"boards-api.greenhouse.io": gh_handler, "api.lever.co": ok_json(lever),
                          "api.ashbyhq.com": ok_json(ashby)})
    registry.set_ats_companies(db, [{"provider": "greenhouse", "token": "acme", "name": "Acme"},
                                    {"provider": "greenhouse", "token": "gone", "name": "Gone"},
                                    {"provider": "lever", "token": "beta", "name": "Beta"},
                                    {"provider": "ashby", "token": "notion", "name": "Notion"}])
    res = runner.run_sources(db, QUERY, http_client=client, only=["ats"])
    titles = sorted(j.title for j in res.jobs)
    check(res.report["ats"]["status"] == "ok", "ATS run succeeds even though one board returns 404")
    check(any("greenhouse:gone" in w for w in res.report["ats"]["warnings"]), "The broken board is reported as a warning")
    check(titles == ["Backend Engineer - Python", "Python Developer Intern", "Software Engineer, Backend"],
          f"Only India/remote AND role-relevant postings kept ({titles})")
    gj = next(j for j in res.jobs if j.title == "Backend Engineer - Python")
    check(gj.description == "Build APIs in Python and Django." and gj.description_quality == "full",
          "Greenhouse escaped HTML content decoded to plain text")
    lj = next(j for j in res.jobs if j.title == "Software Engineer, Backend")
    check("India" in lj.location and lj.job_type == "Full-time" and "Requirements" in lj.description,
          "Lever: country IN -> India, commitment -> job type, lists included in description")
    aj = next(j for j in res.jobs if j.title == "Python Developer Intern")
    check(aj.job_type == "Internship" and "Remote" in aj.location, "Ashby: employment type and remote flag")
    check(res.report["ats"]["requests"] == 4, "One request per configured company")

    # ------------------------------------------------------------------
    check.section("4. Internshala parser (fixture pages)")
    jobs_cards = internshala.parse_listing(fixture_text("internshala_jobs.html"))
    intern_cards = internshala.parse_listing(fixture_text("internshala_internships.html"))
    check(len(jobs_cards) == 2, "Parsing stops at the 'no more results' banner (2 matching job cards)")
    check(len(intern_cards) == 4, "4 internship cards parsed")
    src = internshala.InternshalaSource()
    ij = src._to_jobs(jobs_cards)[0]
    check(ij.title == "Python Developer" and ij.company == "Simpli Intern", "Title and company parsed")
    check(ij.location == "Remote, India" and ij.experience == "Fresher", "Work from home -> Remote; no experience -> Fresher")
    check(ij.url.startswith("https://internshala.com/job/detail/") and "?" not in ij.url, "Clean detail URL")
    ii = src._to_jobs(intern_cards)
    check(all(j.job_type == "Internship" for j in ii) and ii[1].location == "Pune, India", "Internships typed, city parsed")
    check(internshala.listing_urls("Python Developer") == ["https://internshala.com/jobs/python-developer-jobs",
                                                           "https://internshala.com/internships/python-internship"],
          "Clean listing URLs for the role (no query strings)")
    try:
        src._get("https://internshala.com/jobs?page=2", None)
        blocked = False
    except Exception as exc:
        blocked = "robots" in str(exc)
    check(blocked, "URLs with query strings are refused (robots.txt policy)")
    check(registry.enabled_map(db)["internshala"] is False and src.experimental, "Internshala is experimental and OFF by default")

    pages = {"/jobs/python-developer-jobs": fixture_text("internshala_jobs.html"),
             "/internships/python-internship": fixture_text("internshala_internships.html")}
    seen = []
    client = mock_client({"internshala.com": lambda r: httpx.Response(200, text=pages[r.url.path])}, seen)
    with patch("services.sources.internshala.time.sleep") as fake_sleep:
        internshala._cache.clear()
        res = runner.run_sources(db, QUERY, http_client=client, only=["internshala"])
        runner.run_sources(db, QUERY, http_client=client, only=["internshala"])  # served from cache
    check(res.report["internshala"]["count"] == 6, "Runner returns 2 jobs + 4 internships")
    check(len(seen) == 2, "Second run is served from the cache (no new requests)")
    check("Mozilla" in seen[0].headers["user-agent"], "Browser User-Agent sent")

    # ------------------------------------------------------------------
    check.section("5. JobSpy (optional dependency)")
    js = JobSpySource()
    check(js.default_enabled is False and js.experimental, "JobSpy is experimental and OFF by default")
    rows = [{"title": "Python Developer", "company": "Acme", "location": "Pune, MH, IN", "site": "indeed",
             "job_url": "https://in.indeed.com/viewjob?jk=1", "description": "Python " * 200, "job_type": "fulltime",
             "date_posted": "2026-11-18", "id": "in-1", "is_remote": False},
            {"title": float("nan"), "company": "x"}]

    class FakeFrame:
        def to_dict(self, orient):
            return rows

    with patch("services.sources.jobspy_source._scrape", return_value=FakeFrame()), \
         patch.object(JobSpySource, "missing_config", return_value=[]):
        res = runner.run_sources(db, QUERY, http_client=mock_client({}), only=["jobspy"])
    j = res.jobs[0] if res.jobs else None
    check(res.report["jobspy"]["count"] == 1 and j.source_names == ["jobspy:indeed"], "Rows normalised; NaN titles skipped")
    check(j.job_type == "Full-time" and j.description_quality == "full", "Job type normalised, long description = full")
    with patch("importlib.util.find_spec", return_value=None):
        check(js.is_configured() is False, "Without python-jobspy installed the source is 'not configured'")

    # ------------------------------------------------------------------
    check.section("6. Runner: isolation, retry, health, budgets")
    with patch("services.retry.time.sleep"):
        flaky = {"n": 0}

        def jooble_flaky(request):
            flaky["n"] += 1
            return httpx.Response(503) if flaky["n"] == 1 else httpx.Response(200, json=jooble_data)

        client = mock_client({
            "api.adzuna.com": lambda r: httpx.Response(401, json={"exception": "AUTH_FAIL"}),
            "in.jooble.org": jooble_flaky,
            "jsearch.p.rapidapi.com": lambda r: (_ for _ in ()).throw(httpx.ConnectError("down")),
        })
        res = runner.run_sources(db, QUERY, http_client=client, only=["adzuna", "jooble", "jsearch"])
    check(res.report["adzuna"]["status"] == "error" and "credentials" in res.report["adzuna"]["error"],
          "Adzuna auth failure reported, not raised")
    check(res.report["jooble"]["status"] == "ok" and flaky["n"] == 2, "Jooble 503 retried, then succeeded")
    check(res.report["jsearch"]["status"] == "error", "JSearch connection failure reported")
    check(len(res.jobs) == 6 and not res.all_failed, "One healthy source still delivers its jobs")
    check(all("test-app-key-123" not in (r["error"] or "") for r in res.report.values()), "No key in error text")
    health = registry.health_rows(db)
    check(health["adzuna"].last_error_at is not None and health["jooble"].last_count == 6, "source_health updated")
    check(res.report["jsearch"]["requests"] == 2, "JSearch per-run cap (2) limits retries")

    with patch.dict(os.environ, {"JSEARCH_MONTHLY_BUDGET": "3"}):
        before = usage.get_count(db, "jsearch")
        check(before == 2, "api_usage counted each JSearch request")
        usage.increment(db, "jsearch")
        res = runner.run_sources(db, QUERY, http_client=mock_client({}), only=["jsearch"])
        check(res.report["jsearch"]["status"] == "skipped" and "budget" in res.report["jsearch"]["error"],
              "Monthly budget used up -> source skipped without any request")

    res = runner.run_sources(db, QUERY, http_client=mock_client({}), only=[])
    check(res.report["adzuna"]["status"] == "disabled" and res.ran == [], "Sources not selected are 'disabled'")
    with patch.dict(os.environ, {"JOOBLE_API_KEY": ""}):
        res = runner.run_sources(db, QUERY, http_client=mock_client({}), only=["jooble"])
    check(res.report["jooble"]["status"] == "not_configured" and "JOOBLE_API_KEY" in res.report["jooble"]["error"],
          "Missing key -> 'not_configured' naming the variable")

    # ------------------------------------------------------------------
    check.section("7. Sources API and settings")

    def override_get_db():
        s = Session()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_db] = override_get_db
    api = TestClient(app)
    r = api.get("/api/sources")
    names = [s["name"] for s in r.json()]
    check(r.status_code == 200 and names == ["jsearch", "adzuna", "jooble", "ats", "internshala", "jobspy"],
          "GET /api/sources lists all sources")
    ad = next(s for s in r.json() if s["name"] == "adzuna")
    check(ad["configured"] is True and ad["health"]["last_error"] and ad["description_quality"] == "snippet",
          "Source entry has configured flag, health and description quality")
    r = api.put("/api/sources/internshala", json={"enabled": True})
    check(r.status_code == 200 and r.json()["enabled"] is True, "PUT /api/sources/{name} enables a source")
    check(api.put("/api/sources/nope", json={"enabled": True}).status_code == 404, "Unknown source -> 404")
    r = api.get("/api/settings/ats-companies")
    check(r.status_code == 200 and len(r.json()["companies"]) == 4, "GET ATS company list")
    r = api.put("/api/settings/ats-companies", json={"companies": [{"provider": "lever", "token": "cred"}]})
    check(r.status_code == 200 and r.json()["companies"][0]["name"] == "cred", "PUT ATS list (name defaults to token)")
    bad = api.put("/api/settings/ats-companies", json={"companies": [{"provider": "workday", "token": "x"}]})
    check(bad.status_code == 422, "Unknown ATS provider rejected")
    bad = api.put("/api/settings/ats-companies", json={"companies": [{"provider": "lever", "token": "a/b?c"}]})
    check(bad.status_code == 422, "Board tokens with URL characters rejected")
    r = api.get("/api/ai/providers")
    check(r.status_code == 200 and [p["name"] for p in r.json()][:2] == ["gemini", "groq"]
          and "key" not in json.dumps(r.json()).lower().replace("api_key", ""), "GET /api/ai/providers (no keys)")

    check.section("8. Trigger cooldown and persisted status")
    trigger_cooldown.reset()
    with patch("main.run_automation_pipeline") as fake_run, patch.dict(os.environ, {"TRIGGER_COOLDOWN_SECONDS": "120"}):
        first = api.post("/api/automation/trigger")
        second = api.post("/api/automation/trigger")
    check(first.status_code == 200 and fake_run.call_count == 1, "First trigger starts a run")
    check(second.status_code == 429 and "wait" in second.json()["detail"].lower(), "Second trigger within 120 s -> 429")
    trigger_cooldown.reset()

    crud.create_resume(db, filename="r.pdf", target_role="AI/ML Engineer", extracted_text="Python developer",
                       file_path="/tmp/r.pdf", file_size=1)
    with patch("services.sources.registry.enabled_map", return_value={"jooble": True}):
        summary = pipeline.run_automation_pipeline(db_session=db, http_client=mock_client({
            "in.jooble.org": lambda r: httpx.Response(500)}))
    check(summary["status"] == "error" and "jooble" in summary["message"], "All sources failing -> run status 'error'")
    pipeline._run_state.update(started_at=None, finished_at=None, last_run=None)  # simulate a restart
    status = api.get("/api/automation/status").json()
    check(status["last_run"] and status["last_run"]["status"] == "error", "Last run is read back from the database after a restart")
    check(status["running"] is False and len(status["sources"]) == 6, "Status keeps old fields and adds 'sources'")
    check("jooble" in status["last_run"]["sources"], "Run summary has per-source results")

    app.dependency_overrides.clear()
    db.close()
    check.done("JOB SOURCE")


if __name__ == "__main__":
    run()
