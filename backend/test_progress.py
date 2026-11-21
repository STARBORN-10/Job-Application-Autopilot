"""
Offline tests for live pipeline progress (services/progress.py) and the "Find New Jobs" API:
- the progress tracker (stages, per-source states, counters, saved-job ids) is thread-safe,
- the runner reports waiting -> running -> done / failed / skipped per source with plain reasons,
- a pipeline run reports every stage, commits each saved job immediately (visible to another session
  while the run continues), and ends with a per-source summary and a one-line headline,
- the trigger marks the run as started at once, never leaves it spinning, and a second click gets 429
  with Retry-After; GET /api/automation/status keeps its old fields and adds progress + cooldown.
All HTTP and AI calls are mocked; nothing goes online.
"""
import datetime
import os
import sys
import threading
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent))

from testing_utils import Checker, mock_client, use_temp_database

use_temp_database()
os.environ["ADZUNA_APP_ID"] = "test-app-id"
os.environ["ADZUNA_APP_KEY"] = "test-app-key-123"
os.environ["JOOBLE_API_KEY"] = "test-jooble-key"
os.environ["ATS_REQUEST_DELAY_SECONDS"] = "0"

import httpx
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

import crud, models, schemas
import db_migrations
from database import engine
from main import app
from security import trigger_cooldown
from services import pipeline
from services.progress import RunProgress, plain_source_error, progress
from services.sources import runner
from services.sources.base import SourceQuery

db_migrations.upgrade_database(engine)
Session = sessionmaker(bind=engine)


def job(title, company, source, url):
    return schemas.JobCreate(title=title, company=company, url=url, source=source, source_names=[source],
                             location="Remote, India", description="Python, FastAPI, SQL, Docker and machine learning.",
                             posted_date=datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None),
                             experience="0-1 years", description_quality="full")


def run():
    check = Checker("RUNNING OFFLINE LIVE-PROGRESS TESTS")
    db = Session()

    check.section("1. Progress tracker")
    p = RunProgress()
    snap = p.snapshot()
    check(snap["active"] is False and snap["stage"] == "idle" and snap["sources"] == [], "Idle tracker is empty")
    run_id = p.begin()
    p.source("adzuna", "waiting", label="Adzuna India")
    p.source("jooble", "waiting", label="Jooble")
    p.source("adzuna", "running")
    snap = p.snapshot()
    check(snap["active"] and snap["run_id"] == run_id and snap["stage"] == "starting", "begin() starts a run")
    check([s["state"] for s in snap["sources"]] == ["running", "waiting"], "Per-source states kept in order")
    check(snap["message"].startswith("Fetching from Adzuna"), "Message follows the running source")
    p.source("adzuna", "done", count=12)
    p.source("jooble", "failed", reason="SourceTransientError: Jooble returned HTTP 503")
    snap = p.snapshot()
    check(snap["sources"][0]["count"] == 12 and snap["sources"][0]["seconds"] is not None, "Done source has count + time")
    check(snap["sources"][1]["reason"] == "The source is having problems (HTTP 503)", "Failure reason in plain language")

    # Thread safety: many writers + a reader polling snapshots never crash or lose updates.
    p.stage("scoring")
    p.counts(processed=0, total=4000)
    errors = []

    def writer(n):
        try:
            for i in range(500):
                p.processed()
                if i % 50 == 0:
                    p.saved_job(n * 1000 + i, "adzuna")
        except Exception as exc:  # pragma: no cover
            errors.append(exc)

    def reader():
        try:
            for _ in range(300):
                s = p.snapshot()
                assert 0 <= s["processed"] <= 4000
        except Exception as exc:  # pragma: no cover
            errors.append(exc)

    threads = [threading.Thread(target=writer, args=(n,)) for n in range(8)] + [threading.Thread(target=reader)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    snap = p.snapshot()
    check(not errors and snap["processed"] == 4000, "8 writer threads + a polling reader: no lost updates (4000)")
    check(snap["saved"] == 80 and len(snap["new_job_ids"]) == 80 and snap["saved_by_source"]["adzuna"] == 80,
          "Saved-job counter, ids and per-source counts are consistent")
    p.finish(True, "Found 80 new jobs: Adzuna 80.", summary={"saved": 80})
    snap = p.snapshot()
    check(snap["active"] is False and snap["stage"] == "done" and snap["summary"]["saved"] == 80,
          "finish() records the final summary")
    check(isinstance(snap["elapsed_seconds"], float), "Elapsed time recorded")

    p2 = RunProgress()
    p2.begin()
    p2.source("jsearch", "waiting", label="JSearch")
    p2.finish(False, "boom", error="boom")
    check(p2.snapshot()["sources"][0]["state"] == "skipped", "A source still waiting when the run fails becomes 'skipped'")

    check.section("2. Plain-language source errors")
    check(plain_source_error("Missing: ADZUNA_APP_ID, ADZUNA_APP_KEY") == "Not set up: missing ADZUNA_APP_ID, ADZUNA_APP_KEY",
          "Missing key")
    check("budget" in plain_source_error("Monthly budget of 150 request(s) used up"), "Budget reached")
    check("API key was rejected" in plain_source_error("SourceError: Adzuna rejected the credentials (HTTP 401)"), "Bad key")
    check("Rate limited" in plain_source_error("SourceTransientError: Jooble returned HTTP 429"), "Rate limit")
    check("did not answer in time" in plain_source_error("SourceTransientError: JSearch timed out"), "Timeout")
    check("Could not connect" in plain_source_error("SourceTransientError: Adzuna connection failed (ConnectError)"),
          "Connection problem")

    check.section("3. Runner reports per-source states")
    events = []
    adzuna = {"results": [{"title": "Python Developer", "company": {"display_name": "Acme"},
                           "location": {"display_name": "Bengaluru, Karnataka"},
                           "redirect_url": "https://www.adzuna.in/details/1", "description": "Python and SQL",
                           "created": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                           "id": "1"}]}
    client = mock_client({"api.adzuna.com": lambda r: httpx.Response(200, json=adzuna),
                          "in.jooble.org": lambda r: httpx.Response(503)})
    with patch("services.retry.time.sleep"):
        result = runner.run_sources(db, SourceQuery(role="Python Developer", locations=["India"]), http_client=client,
                                    only=["adzuna", "jooble", "jsearch"],
                                    on_progress=lambda name, state, **kw: events.append((name, state, kw)))
    states = {}
    for name, state, _kw in events:
        states.setdefault(name, []).append(state)
    check(states["adzuna"] == ["waiting", "running", "done"], f"Adzuna: waiting -> running -> done ({states['adzuna']})")
    check(states["jooble"] == ["waiting", "running", "failed"], "Jooble (HTTP 503): waiting -> running -> failed")
    check(states["jsearch"] == ["waiting", "skipped"], "JSearch without a key: waiting -> skipped")
    check(result.report["adzuna"]["count"] == 1, "Runner result unchanged (Adzuna 1 job)")
    check("internshala" not in states, "Disabled sources are not reported")
    boom = runner.run_sources(db, SourceQuery(role="x"), http_client=client, only=["adzuna"],
                              on_progress=lambda *a, **k: (_ for _ in ()).throw(RuntimeError("ui bug")))
    check(boom.report["adzuna"]["status"] == "ok", "A failing progress callback never breaks a source")

    check.section("4. Pipeline run: stages, immediate commits, summary, headline")
    crud.create_resume(db, filename="r.pdf", target_role="AI/ML Engineer",
                       extracted_text="Python developer. FastAPI, SQL, Docker, machine learning projects.",
                       file_path="/tmp/none.pdf", file_size=1)
    crud.create_job(db, job("Old Duplicate Role", "Dup Co", "adzuna", "https://dup.example/1"))
    fetched = [job("ML Engineer", "Alpha", "adzuna", "https://a.example/1"),
               job("Python Developer", "Beta", "adzuna", "https://b.example/1"),
               job("Backend Developer", "Gamma", "jooble", "https://c.example/1"),
               job("Old Duplicate Role", "Dup Co", "jooble", "https://dup.example/1")]
    stages_seen, visible_elsewhere = [], []
    real_stage, real_create = progress.stage, crud.create_job

    def spy_stage(name, message=None):
        stages_seen.append(name)
        return real_stage(name, message)

    def spy_create(db, job):
        saved = real_create(db=db, job=job)
        other = Session()  # a second connection, like the dashboard's next poll
        visible_elsewhere.append(other.get(models.Job, saved.id) is not None)
        other.close()
        return saved

    def fake_sources(db_, query, http_client=None, only=None, on_progress=None):
        res = runner.SourcesResult()
        for name in ("adzuna", "jooble"):
            on_progress(name, "waiting", label=name.title())
        for name in ("adzuna", "jooble"):
            on_progress(name, "running")
            mine = [j for j in fetched if j.source == name]
            res.jobs.extend(mine)
            res.report[name] = {"status": "ok", "count": len(mine), "error": None}
            on_progress(name, "done", count=len(mine))
        return res

    with patch("services.pipeline.run_sources", side_effect=fake_sources), \
         patch.object(progress, "stage", side_effect=spy_stage), \
         patch("crud.create_job", side_effect=spy_create), \
         patch("services.notification_service.send_job_alert"):
        summary = pipeline.run_automation_pipeline(db_session=db)
    check(summary["status"] == "success", f"Run succeeded ({summary['message'][:80]})")
    check(stages_seen[:5] == ["fetching", "deduplicating", "filtering", "scoring", "saving"],
          f"Stages reported in order ({stages_seen})")
    check(summary["saved"] >= 1 and visible_elsewhere and all(visible_elsewhere),
          f"Each saved job is committed at once and visible to another session ({len(visible_elsewhere)})")
    snap = progress.snapshot()
    check(snap["active"] is False and snap["stage"] == "done", "Progress ends in 'done'")
    check(len(snap["new_job_ids"]) == summary["saved"], "Progress lists the ids of the jobs saved in this run")
    per = summary["per_source"]
    check(per["adzuna"]["fetched"] == 2 and per["jooble"]["fetched"] == 2, "Per-source fetched counts")
    check(per["jooble"]["duplicates"] == 1, "Database duplicate attributed to its source")
    check(sum(v["saved"] for v in per.values()) == summary["saved"], "Per-source saved adds up to the total")
    check(summary["headline"].startswith(f"Found {summary['saved']} new job"), f"Headline: {summary['headline']}")
    check(snap["summary"]["headline"] == summary["headline"] and "details" not in snap["summary"],
          "Compact summary (no per-job details) in the progress snapshot")
    status = pipeline.get_pipeline_status(db)
    check({"running", "started_at", "finished_at", "last_run", "sources", "progress"} <= set(status),
          "Status keeps the old fields and adds 'progress'")

    check.section("5. Headline when nothing new is saved, and failures")
    check(pipeline.build_headline({"saved": 0, "duplicates_skipped": 52, "total_fetched": 60, "per_source": {}})
          == "No new jobs; 52 duplicates skipped (already in your list).", "No new jobs, duplicates explained")
    check("sources returned no jobs" in pipeline.build_headline({"saved": 0, "total_fetched": 0, "per_source": {}}),
          "Empty fetch explained")
    from sqlalchemy.exc import OperationalError
    check("database problem" in pipeline.describe_crash(OperationalError("SELECT", {}, Exception("locked"))),
          "Database failures described in plain language")
    with patch("services.pipeline.run_sources", side_effect=RuntimeError("Source exploded")):
        crashed = pipeline.run_automation_pipeline(db_session=db)
    snap = progress.snapshot()
    check(crashed["status"] == "error" and snap["stage"] == "failed" and "Source exploded" in snap["error"],
          "A crash ends the progress in 'failed' with the reason")
    db.query(models.Resume).delete()
    db.commit()
    no_resume = pipeline.run_automation_pipeline(db_session=db)
    check(no_resume["status"] == "error" and "upload a resume" in progress.snapshot()["message"].lower(),
          "Missing resume is reported in plain language")

    check.section("6. Trigger + status API")
    api = TestClient(app)
    trigger_cooldown.reset()
    seen_active = []
    with patch("main.run_automation_pipeline", side_effect=lambda **kw: seen_active.append(progress.is_active())), \
         patch.dict(os.environ, {"TRIGGER_COOLDOWN_SECONDS": "120"}):
        first = api.post("/api/automation/trigger")
        second = api.post("/api/automation/trigger")
    check(first.status_code == 200 and first.json()["details"]["run_id"], "Trigger returns the run id")
    check(seen_active == [True], "The run is marked active before the background task starts")
    check(progress.is_active() is False and progress.snapshot()["stage"] == "failed",
          "A run that never reports its end is closed ('ended unexpectedly'), not left spinning")
    check(second.status_code == 429 and second.headers.get("retry-after", "").isdigit()
          and int(second.headers["retry-after"]) > 100, "Second click within the cooldown -> 429 with Retry-After")
    with patch.dict(os.environ, {"TRIGGER_COOLDOWN_SECONDS": "120"}):
        status = api.get("/api/automation/status").json()
    check(status["running"] is False and status["cooldown_remaining"] > 100 and "progress" in status,
          "Status reports the cooldown left and the progress")
    trigger_cooldown.reset()
    pipeline._pipeline_lock.acquire()
    try:
        r = api.post("/api/automation/trigger")
        check(r.json()["status"] == "already_running", "Trigger while a run holds the lock -> already_running")
    finally:
        pipeline._pipeline_lock.release()
    trigger_cooldown.reset()

    db.close()
    check.done("LIVE-PROGRESS")


if __name__ == "__main__":
    run()
