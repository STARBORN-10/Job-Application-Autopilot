"""
Offline tests for accounts and per-user data isolation (AUTH_ENABLED=true).

Covers: registration and login rules, tokens, the legacy-data claim, that one user can never read, change or delete
another user's data through any kind of endpoint, per-user run state (lock, progress, cooldown, tasks), the
scheduler, Telegram linking and routing, owner-only real e-mail, password change / sign-out-everywhere, account
deletion, sign-up controls, the removed public /uploads mount, and a sweep that fails if any route is open
without a sign-in. No real service is contacted.
"""
import datetime
import io
import json
import os
import sys
import time
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent))

from testing_utils import Checker, mock_client, use_temp_database

use_temp_database()
os.environ.update(
    AUTH_ENABLED="true", AUTH_SECRET="test-secret-for-the-auth-suite-0123456789", MAKE_API_KEY="legacy-key",
    TELEGRAM_BOT_TOKEN="123:TEST", TELEGRAM_BOT_USERNAME="autopilot_test_bot", TELEGRAM_WEBHOOK_SECRET="wh-secret",
    TRIGGER_COOLDOWN_SECONDS="120",
)
for name in ("ALLOW_SIGNUP", "SIGNUP_CODE", "OWNER_EMAIL", "AUTH_TOKEN_DAYS"):
    os.environ.pop(name, None)

import httpx
import jwt
from fastapi.testclient import TestClient

import auth
import crud
import db_migrations
import main
import models
import schemas
import tenancy
from database import SessionLocal, engine
from security import trigger_cooldown
from services import notification_service as tg, pipeline, telegram_bot
from services.apply import service as apply_service
from services.progress import progress
from services.tasks import tasks

db_migrations.upgrade_database(engine)
client = TestClient(main.app)
PASSWORD = "correct horse battery"


def session(user_id):
    # expire_on_commit=False: the test keeps reading ids and fields of rows after committing and closing.
    return tenancy.set_tenant(SessionLocal(expire_on_commit=False), user_id)


def system():
    return tenancy.system_session(SessionLocal())


def bearer(token):
    return {"Authorization": f"Bearer {token}"}


def register(email, password=PASSWORD, name="", **extra):
    return client.post("/api/auth/register", json={"email": email, "password": password, "name": name, **extra})


def tiny_pdf(text="Python developer with FastAPI") -> bytes:
    from reportlab.pdfgen import canvas
    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    c.drawString(72, 720, text)
    c.save()
    return buf.getvalue()


def fake_telegram(seen=None):
    def handler(request):
        if seen is not None:
            seen.append(request)
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 1}})
    return mock_client({"api.telegram.org": handler}, None)


def run():
    check = Checker("RUNNING OFFLINE ACCOUNT AND ISOLATION TESTS")

    # ------------------------------------------------------------------
    check.section("1. Public and protected endpoints")
    check(client.get("/api/health").status_code == 200, "Health is public")
    cfg = client.get("/api/auth/config").json()
    check(cfg["auth_enabled"] is True and cfg["signup_open"] is True and cfg["first_account"] is True,
          "Config: accounts on, sign-up open, the first account is announced")
    check(client.get("/api/jobs").status_code == 401, "Job list needs a sign-in")
    check(client.get("/api/jobs", headers=bearer("not-a-token")).status_code == 401, "Garbage token rejected")
    check(client.post("/api/automation/trigger").status_code == 401, "Trigger needs a sign-in")

    # ------------------------------------------------------------------
    check.section("2. Data that existed before accounts is kept for the first account")
    legacy = session(None)
    legacy_job = crud.create_job(legacy, schemas.JobCreate(title="Legacy ML Engineer", company="OldCo", url="https://old/1", score=8.1))
    crud.set_setting(legacy, "general_settings", json.dumps({"min_match_score": 6.5, "target_roles": "AI/ML Engineer"}))
    legacy_resume = crud.create_resume(legacy, "old.pdf", "AI/ML Engineer", "Python PyTorch", "x", 1)
    legacy.close()
    check(legacy_job.user_id is None, "Pre-account rows have no owner")

    r = register("owner@example.com", name="Olivia Owner")
    check(r.status_code == 200 and r.json()["user"]["is_owner"] is True and r.json()["token"], "First account created and is the owner")
    token_a = r.json()["token"]
    A = bearer(token_a)
    jobs_a = client.get("/api/jobs", headers=A).json()
    check([j["title"] for j in jobs_a] == ["Legacy ML Engineer"], "The first account inherited the existing jobs")
    check(client.get("/api/resumes", headers=A).json()[0]["filename"] == "old.pdf", "...and the existing resume")
    check(client.get("/api/settings", headers=A).json()["min_match_score"] == 6.5, "...and the existing settings")
    check(client.get("/api/auth/config").json()["first_account"] is False, "Config no longer announces a first account")

    # ------------------------------------------------------------------
    check.section("3. Registration and login rules")
    auth.login_limiter.reset()
    check(register("bad-email").status_code == 422, "Invalid e-mail rejected")
    check(register("short@example.com", password="short").status_code == 422, "Short password rejected")
    check(register("x@example.com", password="p" * 200).status_code == 422, "Over-long password rejected")
    check(register("OWNER@Example.com").status_code == 409, "Duplicate e-mail rejected (case-insensitive)")
    r = register("  Bea@Example.COM ", name="Bea Builder")
    check(r.status_code == 200 and r.json()["user"]["email"] == "bea@example.com", "E-mail is trimmed and lower-cased")
    check(r.json()["user"]["is_owner"] is False, "Later accounts are not the owner")
    token_b = r.json()["token"]
    B = bearer(token_b)
    with SessionLocal() as s:
        row = s.query(models.User).filter(models.User.email == "bea@example.com").one()
        check(row.password_hash.startswith("scrypt$") and PASSWORD not in row.password_hash, "Passwords are stored as salted scrypt hashes")
        check(auth.verify_password(PASSWORD, row.password_hash) and not auth.verify_password("wrong password", row.password_hash),
              "Password check accepts the right password only")
        h2 = auth.hash_password(PASSWORD)
        check(h2 != row.password_hash, "Same password, different salt, different hash")
    check(client.post("/api/auth/login", json={"email": "bea@example.com", "password": PASSWORD}).status_code == 200, "Login works")
    check(client.post("/api/auth/login", json={"email": "BEA@example.com", "password": PASSWORD}).status_code == 200, "Login ignores e-mail case")
    check(client.post("/api/auth/login", json={"email": "bea@example.com", "password": "nope-nope"}).status_code == 401, "Wrong password -> 401")
    check(client.post("/api/auth/login", json={"email": "ghost@example.com", "password": PASSWORD}).status_code == 401, "Unknown e-mail -> same 401")
    bad = client.post("/api/auth/login", json={"email": "bea@example.com", "password": "nope-nope"}).json()["detail"]
    ghost = client.post("/api/auth/login", json={"email": "ghost@example.com", "password": "nope-nope"}).json()["detail"]
    check(bad == ghost, "Wrong password and unknown e-mail give the identical message")
    auth.login_limiter.reset()
    codes = [client.post("/api/auth/login", json={"email": "victim@example.com", "password": f"guess-{i}-xxxxx"}).status_code for i in range(10)]
    check(codes[:8] == [401] * 8 and codes[8] == 429 and codes[9] == 429, "Login is rate limited after 8 failures")
    auth.login_limiter.reset()
    me = client.get("/api/auth/me", headers=B).json()
    check(me["user"]["email"] == "bea@example.com" and me["auth_enabled"] is True, "GET /api/auth/me returns the account")
    check(client.put("/api/auth/me", json={"name": "Bea B."}, headers=B).json()["user"]["name"] == "Bea B.", "Profile name can be changed")

    # ------------------------------------------------------------------
    check.section("4. Tokens")
    claims = jwt.decode(token_a, os.environ["AUTH_SECRET"], algorithms=["HS256"])
    check(claims["sub"] == "1" and claims["exp"] > time.time() + 6 * 86400, "Token carries the user id and lasts about 7 days")
    expired = jwt.encode({"sub": "1", "ver": 0, "iat": int(time.time()) - 100, "exp": int(time.time()) - 10}, os.environ["AUTH_SECRET"], algorithm="HS256")
    check(client.get("/api/jobs", headers=bearer(expired)).status_code == 401, "Expired token rejected")
    forged = jwt.encode({"sub": "1", "ver": 0, "iat": int(time.time()), "exp": int(time.time()) + 999}, "attacker-secret", algorithm="HS256")
    check(client.get("/api/jobs", headers=bearer(forged)).status_code == 401, "Token signed with another secret rejected")
    none_alg = jwt.encode({"sub": "1", "ver": 0, "iat": int(time.time()), "exp": int(time.time()) + 999}, None, algorithm="none")
    check(client.get("/api/jobs", headers=bearer(none_alg)).status_code == 401, "Unsigned ('alg: none') token rejected")
    check(client.get("/api/jobs", headers={"Authorization": token_a}).status_code == 401, "Token without the 'Bearer' word rejected")
    ghost_token = jwt.encode({"sub": "999", "ver": 0, "iat": int(time.time()), "exp": int(time.time()) + 999}, os.environ["AUTH_SECRET"], algorithm="HS256")
    check(client.get("/api/jobs", headers=bearer(ghost_token)).status_code == 401, "Valid token of a user that does not exist rejected")

    # ------------------------------------------------------------------
    check.section("5. One user cannot see or change another user's data")
    db_a = session(1)
    job_a = crud.create_job(db_a, schemas.JobCreate(title="Secret Job of A", company="A Corp", url="https://a/secret", score=9.4,
                                                    description="Python", cover_letter="Dear A"))
    app_a = models.Application(job_id=job_a.id, method="assisted", status="ready_to_submit", dry_run=True, payload_summary="{}")
    db_a.add(app_a)
    db_a.commit()
    resume_a_path = Path(main.UPLOAD_DIR) / "test_user_a_resume.pdf"
    resume_a_path.write_bytes(tiny_pdf("A private resume"))
    resume_a = crud.create_resume(db_a, "a_private.pdf", "AI/ML Engineer", "A private resume text", str(resume_a_path), 10)
    db_a.close()
    db_b = session(2)
    job_b = crud.create_job(db_b, schemas.JobCreate(title="Job of B", company="B Corp", url="https://b/1", score=7.2))
    db_b.close()
    check(job_a.user_id == 1 and job_b.user_id == 2, "Rows are stamped with their owner")

    titles_b = [j["title"] for j in client.get("/api/jobs?limit=2000", headers=B).json()]
    check(titles_b == ["Job of B"], "B's job list contains only B's job")
    check(client.get(f"/api/jobs/{job_a.id}", headers=B).status_code == 404, "B cannot open A's job by id")
    check(client.put(f"/api/jobs/{job_a.id}", json={"status": "Applied"}, headers=B).status_code == 404, "B cannot edit A's job")
    check(client.delete(f"/api/jobs/{job_a.id}", headers=B).status_code == 404, "B cannot delete A's job")
    check(session(1).get(models.Job, job_a.id) is not None, "A's job is still there after B's delete attempt")
    check([j["title"] for j in client.get("/api/jobs/top?limit=50", headers=B).json()] == ["Job of B"], "Top jobs are per user")
    check(client.get("/api/analytics", headers=B).json()["total_jobs"] == 1, "Analytics count only B's jobs")
    csv_b = client.get("/api/export/jobs.csv", headers=B).text
    check("Secret Job of A" not in csv_b and "Job of B" in csv_b, "CSV export contains only B's jobs")
    for fmt in ("xlsx", "pdf"):
        check(client.get(f"/api/export/jobs.{fmt}", headers=B).status_code == 200, f"{fmt} export works for B")
    check(client.post(f"/api/jobs/{job_a.id}/analyze", headers=B).status_code == 404, "B cannot analyze A's job")
    for path in ("approve-preview", "timeline", "tailored-resume"):
        check(client.get(f"/api/jobs/{job_a.id}/{path}", headers=B).status_code == 404, f"B cannot read A's job /{path}")
    for path in ("approve", "skip", "apply", "tailor-resume", "prefill"):
        check(client.post(f"/api/jobs/{job_a.id}/{path}", headers=B).status_code == 404, f"B cannot POST /{path} on A's job")
    check(session(1).get(models.Job, job_a.id).approval_status == "pending", "A's job was not approved by B's attempts")
    check(client.get(f"/api/applications/{app_a.id}/screenshot", headers=B).status_code == 404, "B cannot open A's application screenshot")
    check(client.get("/api/applications", headers=B).json() == [] or all(a["job_id"] != job_a.id for a in client.get("/api/applications", headers=B).json()),
          "B's applications list does not include A's")

    check(client.get("/api/resumes", headers=B).json() == [], "B has no resumes of A's")
    check(client.get(f"/api/resumes/{resume_a.id}/text", headers=B).status_code == 404, "B cannot read A's resume text")
    check(client.get(f"/api/resumes/{resume_a.id}/file", headers=B).status_code == 404, "B cannot download A's resume PDF")
    check(client.delete(f"/api/resumes/{resume_a.id}", headers=B).status_code == 404, "B cannot delete A's resume")
    check(client.put(f"/api/resumes/{resume_a.id}/activate", headers=B).status_code == 404, "B cannot activate A's resume")
    check(client.put(f"/api/resumes/{resume_a.id}/role", json={"target_role": "Data Analyst"}, headers=B).status_code == 404, "B cannot change A's resume role")
    r = client.get(f"/api/resumes/{resume_a.id}/file", headers=A)
    check(r.status_code == 200 and r.content.startswith(b"%PDF-"), "A can download A's own PDF")
    check(client.get("/uploads/test_user_a_resume.pdf").status_code == 404 and client.get("/uploads/resumes/test_user_a_resume.pdf").status_code == 404,
          "Resume PDFs are no longer served publicly under /uploads")
    outside = session(1)
    stray = crud.create_resume(outside, "stray.pdf", "Data Analyst", "t", str(Path(main.BACKEND_DIR if hasattr(main, "BACKEND_DIR") else Path(main.__file__).parent) / "main.py"), 1)
    outside.close()
    check(client.get(f"/api/resumes/{stray.id}/file", headers=A).status_code == 404, "A resume record cannot be used to download files outside the upload folder")

    # per-user settings
    s_a = client.get("/api/settings", headers=A).json()
    s_a["min_match_score"] = 8.8
    s_a["preferred_locations"] = "Pune"
    check(client.put("/api/settings", json=s_a, headers=A).status_code == 200, "A saves settings")
    s_b = client.get("/api/settings", headers=B).json()
    check(s_b["min_match_score"] != 8.8 and s_b["preferred_locations"] != "Pune", "B does not see A's settings")
    client.put("/api/sources/internshala", json={"enabled": True}, headers=A)
    enabled = lambda h: {s["name"]: s["enabled"] for s in client.get("/api/sources", headers=h).json()}
    check(enabled(A)["internshala"] is True and enabled(B)["internshala"] is False, "Source toggles are per user")
    client.put("/api/settings/ats-companies", json={"companies": [{"provider": "greenhouse", "token": "acmecorp", "name": "Acme"}]}, headers=A)
    check([c["token"] for c in client.get("/api/settings/ats-companies", headers=A).json()["companies"]] == ["acmecorp"]
          and len(client.get("/api/settings/ats-companies", headers=B).json()["companies"]) > 1, "Company lists are per user")
    client.put("/api/settings/applicant-profile", json={"first_name": "Olivia", "last_name": "Owner", "email": "o@example.com"}, headers=A)
    check(client.get("/api/settings/applicant-profile", headers=B).json()["first_name"] == "", "Applicant profile is per user")
    w_b = client.get("/api/scoring/weights", headers=B).json()
    check(client.get("/api/scoring/weights", headers=A).status_code == 200 and w_b is not None, "Scoring weights are served per user")

    # ------------------------------------------------------------------
    check.section("6. A user can only decide on their own jobs; decisions stay separate")
    r = client.post(f"/api/jobs/{job_b.id}/approve", headers=B)
    check(r.status_code == 200 and r.json()["changed"] is True, "B approves B's own job")
    counts = (session(1).query(models.JobDecision).count(), session(2).query(models.JobDecision).count())
    if counts != (0, 1):
        with system() as dbg:
            print("DEBUG decisions:", [(d.id, d.job_id, d.user_id, d.decision, d.channel) for d in dbg.query(models.JobDecision).all()],
                  "| jobs:", [(j.id, j.title, j.user_id) for j in dbg.query(models.Job).all()])
    check(counts == (0, 1), f"The decision is recorded for B only (A, B = {counts})")
    check(session(2).query(models.Application).count() >= 1 and all(a.job_id != job_a.id for a in session(2).query(models.Application).all()),
          "B's application record is B's own")
    check(client.get("/api/applications", headers=A).status_code == 200
          and all(a["job_id"] != job_b.id for a in client.get("/api/applications", headers=A).json()), "A does not see B's application")
    approve_pre = client.get(f"/api/jobs/{job_b.id}/approve-preview", headers=B).json()
    check(approve_pre.get("method") in ("assisted", "email"), "B can preview B's job")

    # ------------------------------------------------------------------
    check.section("7. Per-user run state: lock, progress, cooldown, tasks")
    with tenancy.tenant_scope(1):
        got_a = pipeline._pipeline_lock.acquire(blocking=False)
    with tenancy.tenant_scope(2):
        locked_b = pipeline._pipeline_lock.locked()
        got_b = pipeline._pipeline_lock.acquire(blocking=False)
        pipeline._pipeline_lock.release()
    with tenancy.tenant_scope(1):
        locked_a = pipeline._pipeline_lock.locked()
        pipeline._pipeline_lock.release()
    check(got_a and locked_a and not locked_b and got_b, "A's running search does not lock B out")
    with tenancy.tenant_scope(1):
        progress.begin("A is searching")
    with tenancy.tenant_scope(2):
        snap_b = progress.snapshot()
    with tenancy.tenant_scope(1):
        snap_a = progress.snapshot()
        progress.finish(True, "done")
    check(snap_a["active"] is True and snap_a["message"] == "A is searching" and snap_b["active"] is False, "Progress is tracked per user")
    with tenancy.tenant_scope(1):
        pipeline._run_state.update(last_run={"headline": "A ran"})
    with tenancy.tenant_scope(2):
        check(pipeline._run_state["last_run"] is None, "Last run summary is per user")
    trigger_cooldown.reset()
    started = []
    with patch.object(main, "_run_pipeline_from_trigger", lambda uid=None: started.append(uid)):
        ra = client.post("/api/automation/trigger", headers=A)
        ra2 = client.post("/api/automation/trigger", headers=A)
        rb = client.post("/api/automation/trigger", headers=B)
    check(ra.json()["status"] == "started" and rb.json()["status"] == "started", "A and B can both start a search")
    check(ra2.json()["status"] == "already_running", "A cannot start a second run on top of A's own")
    check(started == [1, 2], "Each run is started for its own user")
    status_a = client.get("/api/automation/status", headers=A).json()
    status_b = client.get("/api/automation/status", headers=B).json()
    check(status_a["progress"]["run_id"] != status_b["progress"]["run_id"], "Each user polls their own run")
    for uid in (1, 2):
        with tenancy.tenant_scope(uid):
            progress.finish(True, "reset")
    trigger_cooldown.reset()
    with tenancy.tenant_scope(1):
        t_a = tasks.run_inline("autofill", job_a.id, lambda t: {"ok": True})
    check(client.get(f"/api/tasks/{t_a['id']}", headers=A).status_code == 200, "A reads A's task")
    check(client.get(f"/api/tasks/{t_a['id']}", headers=B).status_code == 404, "B cannot read A's task")
    check("owner" not in client.get(f"/api/tasks/{t_a['id']}", headers=A).json(), "Internal task owner is not exposed")

    # scheduler: one run per user that has an active resume, never for users without one
    with SessionLocal() as s:
        s.add(models.User(email="noresume@example.com", password_hash="x"))
        s.commit()
    session(2).add(models.Resume(filename="b.pdf", target_role="AI/ML Engineer", extracted_text="x", file_path="x", is_active=True))
    db_b2 = session(2)
    db_b2.add(models.Resume(filename="b.pdf", target_role="AI/ML Engineer", extracted_text="x", file_path="x", is_active=True))
    db_b2.commit()
    db_b2.close()
    calls = []
    with patch.object(main, "run_automation_pipeline", lambda **kw: calls.append(kw.get("user_id"))):
        main._run_scheduled_pipelines()
    check(sorted(calls) == [1, 2], "The scheduler runs once for each user with an active resume")

    # ------------------------------------------------------------------
    check.section("8. Telegram: each user links their own chat")
    r = client.post("/api/auth/telegram/link", headers=A)
    check(r.status_code == 200 and r.json()["deep_link"].startswith("https://t.me/autopilot_test_bot?start="), "A gets a link code and a deep link")
    code_a = r.json()["code"]
    code_b = client.post("/api/auth/telegram/link", headers=B).json()["code"]
    seen = []
    tgc = mock_client({"api.telegram.org": lambda req: (seen.append(req), httpx.Response(200, json={"ok": True, "result": {}}))[1]})
    start = lambda chat, text: {"update_id": 1, "message": {"chat": {"id": chat}, "text": text}}
    res = telegram_bot.route_update(start(777, "/start wrong-code"), SessionLocal, tgc)
    check(res["handled"] is False and res["reason"] == "bad_link_code", "A wrong code does not link a chat")
    res = telegram_bot.route_update(start(777, f"/start {code_a}"), SessionLocal, tgc)
    check(res["handled"] and res["action"] == "linked", "A links chat 777")
    res = telegram_bot.route_update(start(888, f"/start {code_b}"), SessionLocal, tgc)
    check(res["handled"] and res["action"] == "linked", "B links chat 888")
    res = telegram_bot.route_update(start(999, f"/start {code_a}"), SessionLocal, tgc)
    check(res["handled"] is False, "A used code cannot be used again")
    with SessionLocal() as s:
        chats = {u.email: u.telegram_chat_id for u in s.query(models.User).all()}
    check(chats["owner@example.com"] == "777" and chats["bea@example.com"] == "888", "Each account has its own chat")
    res = telegram_bot.route_update(start(555, "hello"), SessionLocal, tgc)
    check(res["handled"] is False and res["reason"] == "unauthorised_chat", "An unknown chat is ignored")
    tap = lambda chat, job_id, action="approve": {"update_id": 2, "callback_query": {"id": "c1", "data": f"{action}:{job_id}", "from": {"id": chat},
                                                  "message": {"chat": {"id": chat}, "message_id": 5}}}
    res = telegram_bot.route_update(tap(777, job_b.id, "skip"), SessionLocal, tgc)
    check(res["handled"] is False and res["reason"] == "job_not_found", "A's chat cannot act on B's job")
    check(session(2).get(models.Job, job_b.id).approval_status == "approved", "B's job was not changed by A's tap")
    res = telegram_bot.route_update(tap(888, job_a.id, "approve"), SessionLocal, tgc)
    check(res["handled"] is False and res["reason"] == "job_not_found", "B's chat cannot act on A's job")
    res = telegram_bot.route_update(tap(777, job_a.id, "skip"), SessionLocal, tgc)
    check(res["handled"] and res["action"] == "skip" and session(1).get(models.Job, job_a.id).approval_status == "skipped",
          "A's chat can act on A's own job")
    check(client.post("/api/telegram/webhook", json={}).status_code == 401, "The webhook needs its secret header")
    check(client.post("/api/telegram/webhook", json={}, headers={"X-Telegram-Bot-Api-Secret-Token": "wh-secret"}).status_code == 200,
          "...and accepts it")
    sent = []
    send_client = mock_client({"api.telegram.org": lambda req: (sent.append(json.loads(req.content)), httpx.Response(200, json={"ok": True}))[1]})
    pipeline._notify(job_b, send_client, chat_id="888", scoped=True)
    check(sent and sent[-1]["chat_id"] == "888", "A job alert goes to the owning user's chat")
    check(pipeline._notify(job_b, send_client, chat_id=None, scoped=True) is False and len(sent) == 1,
          "A user without a linked chat gets no alert (and nobody else's chat is used)")
    check(client.delete("/api/auth/telegram", headers=B).json()["user"]["telegram_linked"] is False, "A user can unlink Telegram")
    db_x = session(2)
    check(auth.telegram_chat_for(db_x) is None, "After unlinking, no chat is used for B")
    db_x.close()
    os.environ["TELEGRAM_CHAT_ID"] = "4242"
    db_o, db_b3 = session(1), session(2)
    check(auth.telegram_chat_for(db_o) == "777" and auth.telegram_chat_for(db_b3) is None, "TELEGRAM_CHAT_ID serves only the owner, and only without a linked chat")
    db_o.close()
    db_b3.close()
    os.environ["TELEGRAM_CHAT_ID"] = ""

    # ------------------------------------------------------------------
    check.section("9. Real e-mail only for the owner (it uses the server's SMTP account)")
    with patch.dict(os.environ, {"APPLY_DRY_RUN": "false"}):
        db_o, db_u = session(1), session(2)
        check(apply_service.dry_run_enabled(db_o) is False, "Owner: real sending allowed when dry run is off")
        check(apply_service.dry_run_enabled(db_u) is True, "Other user: still a dry run")
        db_o.close()
        db_u.close()
    check(apply_service.dry_run_enabled(None) is True, "Dry run stays on by default")

    # ------------------------------------------------------------------
    check.section("10. Legacy ingestion endpoints act on the owner account only")
    r = client.post("/api/jobs", json={"title": "Via legacy key", "company": "L", "url": "https://l/1", "experience": "Fresher"},
                    headers={"X-API-Key": "legacy-key"})
    check(r.status_code == 200, "Legacy POST /api/jobs works with the API key")
    check(client.post("/api/jobs", json={"title": "x", "company": "y", "url": "https://l/2"}).status_code == 401, "...and not without it")
    check("Via legacy key" in [j["title"] for j in client.get("/api/jobs?limit=2000", headers=A).json()]
          and "Via legacy key" not in [j["title"] for j in client.get("/api/jobs?limit=2000", headers=B).json()], "The job lands in the owner's list only")
    check(client.get("/api/make/context", headers={"X-API-Key": "legacy-key"}).status_code == 200, "Legacy context endpoint works with the key")

    # ------------------------------------------------------------------
    check.section("11. Password change, sign out everywhere")
    r = client.post("/api/auth/change-password", json={"current_password": "wrong", "new_password": "a brand new password"}, headers=B)
    check(r.status_code == 401, "Wrong current password rejected")
    r = client.post("/api/auth/change-password", json={"current_password": PASSWORD, "new_password": "short"}, headers=B)
    check(r.status_code == 422, "Weak new password rejected")
    r = client.post("/api/auth/change-password", json={"current_password": PASSWORD, "new_password": "a brand new password"}, headers=B)
    new_b = r.json()["token"]
    check(r.status_code == 200 and client.get("/api/jobs", headers=B).status_code == 401, "The old token stops working after a password change")
    check(client.get("/api/jobs", headers=bearer(new_b)).status_code == 200, "The new token works")
    check(client.post("/api/auth/login", json={"email": "bea@example.com", "password": "a brand new password"}).status_code == 200
          and client.post("/api/auth/login", json={"email": "bea@example.com", "password": PASSWORD}).status_code == 401, "Only the new password logs in")
    B = bearer(new_b)
    r = client.post("/api/auth/logout-all", headers=B)
    check(client.get("/api/jobs", headers=B).status_code == 401 and client.get("/api/jobs", headers=bearer(r.json()["token"])).status_code == 200,
          "Sign out everywhere ends other sessions and returns a fresh token")
    B = bearer(r.json()["token"])

    # ------------------------------------------------------------------
    check.section("12. Account deletion removes only that account's data")
    carol = register("carol@example.com", name="Carol").json()
    C = bearer(carol["token"])
    db_c = session(carol["user"]["id"])
    crud.create_job(db_c, schemas.JobCreate(title="Carol job", company="C", url="https://c/1"))
    carol_file = Path(main.UPLOAD_DIR) / "test_carol_resume.pdf"
    carol_file.write_bytes(tiny_pdf("carol"))
    crud.create_resume(db_c, "carol.pdf", "AI/ML Engineer", "carol text", str(carol_file), 5)
    db_c.close()
    check(client.request("DELETE", "/api/auth/account", json={"password": "wrong-password"}, headers=C).status_code == 401, "Deleting needs the right password")
    r = client.request("DELETE", "/api/auth/account", json={"password": PASSWORD}, headers=C)
    check(r.status_code == 200 and r.json()["deleted"]["jobs"] == 1 and r.json()["deleted"]["resumes"] == 1, "Account deleted with its rows")
    check(not carol_file.exists(), "...and the uploaded PDF was removed from disk")
    check(client.get("/api/jobs", headers=C).status_code == 401, "The deleted account's token stops working")
    with system() as s:
        check(s.query(models.Job).filter(models.Job.title == "Carol job").count() == 0, "No rows of the deleted account remain")
        check(s.query(models.Job).filter(models.Job.title == "Job of B").count() == 1, "Other accounts' data is untouched")

    # ------------------------------------------------------------------
    check.section("13. Sign-up controls")
    with patch.dict(os.environ, {"ALLOW_SIGNUP": "false"}):
        check(register("late@example.com").status_code == 403 and client.get("/api/auth/config").json()["signup_open"] is False,
              "ALLOW_SIGNUP=false closes registration")
    with patch.dict(os.environ, {"SIGNUP_CODE": "invite-123"}):
        check(client.get("/api/auth/config").json()["signup_code_required"] is True, "Config tells the page an invite code is needed")
        check(register("code1@example.com").status_code == 403, "Registration without the invite code is refused")
        check(register("code2@example.com", signup_code="wrong").status_code == 403, "A wrong invite code is refused")
        check(register("code3@example.com", signup_code="invite-123").status_code == 200, "The right invite code is accepted")
    auth.login_limiter.reset()

    # OWNER_EMAIL decides who inherits data that existed before accounts
    with system() as s:
        pass
    legacy2 = session(None)
    crud.create_job(legacy2, schemas.JobCreate(title="Second legacy job", company="Z", url="https://z/1"))
    legacy2.close()
    with patch.dict(os.environ, {"OWNER_EMAIL": "boss@example.com"}):
        register("nobody@example.com")
        with system() as s:
            check(s.query(models.Job).filter(models.Job.title == "Second legacy job").one().user_id is None, "A non-owner e-mail does not take the old data")
        r = register("boss@example.com")
        with system() as s:
            check(s.query(models.Job).filter(models.Job.title == "Second legacy job").one().user_id == r.json()["user"]["id"]
                  and r.json()["user"]["is_owner"] is True, "OWNER_EMAIL takes over the old data when it registers")

    # ------------------------------------------------------------------
    check.section("13b. Owner command-line tool (no e-mail password reset exists)")
    import manage_users
    out = io.StringIO()
    with patch("sys.stdout", out), SessionLocal() as s:
        manage_users.list_users(s)
    listing = out.getvalue()
    owner_line = next((l for l in listing.splitlines() if "owner@example.com" in l), "")
    check(bool(owner_line) and "owner" in owner_line.split("last sign-in:")[1].split(), "list shows the accounts and marks the owner")
    with SessionLocal() as s:
        manage_users.reset_password(s, "owner@example.com", "reset by the owner 123")
    check(client.get("/api/jobs", headers=A).status_code == 401, "Resetting a password ends that user's old sessions")
    check(client.post("/api/auth/login", json={"email": "owner@example.com", "password": "reset by the owner 123"}).status_code == 200,
          "...and the new password works")
    try:
        with SessionLocal() as s:
            manage_users.reset_password(s, "owner@example.com", "short")
        weak_refused = False
    except SystemExit:
        weak_refused = True
    check(weak_refused, "A weak password is refused by the tool too")
    with SessionLocal() as s:
        manage_users.set_active(s, "owner@example.com", False)
    check(client.post("/api/auth/login", json={"email": "owner@example.com", "password": "reset by the owner 123"}).status_code == 403,
          "A disabled account cannot sign in")
    with SessionLocal() as s:
        manage_users.set_active(s, "owner@example.com", True)
    check(client.post("/api/auth/login", json={"email": "owner@example.com", "password": "reset by the owner 123"}).status_code == 200,
          "...and can again once enabled")
    try:
        with SessionLocal() as s:
            manage_users.reset_password(s, "nobody-here@example.com", "whatever 12345")
        unknown_refused = False
    except SystemExit:
        unknown_refused = True
    check(unknown_refused, "An unknown e-mail is reported, not ignored")
    auth.login_limiter.reset()

    check.section("14. Every query style is filtered on every per-user table (regression: Query.count() once leaked)")
    from sqlalchemy import func, select
    with SessionLocal() as s:
        empty_user = models.User(email="empty@example.com", password_hash="x")
        s.add(empty_user)
        s.commit()
        empty_id = empty_user.id
    with system() as s:
        everything = {m.__tablename__: s.query(m).count() for m in tenancy.TENANT_MODELS}
    check(all(n > 0 for t, n in everything.items() if t in ("jobs", "resumes", "app_settings", "job_decisions", "applications")),
          f"The database really holds rows for other users to leak ({everything})")
    for model in tenancy.TENANT_MODELS:
        name = model.__tablename__
        e = session(empty_id)
        shapes = {
            "query().count()": e.query(model).count(),
            "query().all()": len(e.query(model).all()),
            "func.count()": e.query(func.count(model.id)).scalar(),
            "select()": len(list(e.execute(select(model)).scalars())),
            "query().first()": 0 if e.query(model).first() is None else 1,
            "exists()": 1 if e.query(e.query(model).exists()).scalar() else 0,
        }
        e.close()
        check(all(v == 0 for v in shapes.values()), f"A user with no data sees nothing in {name} ({shapes})")

    check.section("14b. The session itself refuses to work without a user (defence in depth)")
    try:
        SessionLocal().query(models.Job).all()
        refused = False
    except tenancy.TenantError:
        refused = True
    check(refused, "A database session without a user cannot read user data")
    try:
        s = session(1)
        s.add(models.Job(title="forged", user_id=2))
        s.commit()
        refused = False
    except tenancy.TenantError:
        refused = True
    check(refused, "A session cannot save a row that belongs to another user")

    # ------------------------------------------------------------------
    check.section("15. Sweep: every route needs a sign-in unless it is deliberately public")
    open_routes = []
    skip = {"/openapi.json", "/docs", "/redoc", "/docs/oauth2-redirect"}
    n = 0
    for route in main.app.routes:
        path = getattr(route, "path", None)
        if not path or path in skip or not hasattr(route, "methods"):
            continue
        concrete = path.replace("{job_id}", "1").replace("{resume_id}", "1").replace("{task_id}", "x").replace("{application_id}", "1") \
                       .replace("{name}", "x").replace("{fmt}", "csv").replace("{kind}", "pdf")
        for method in route.methods - {"HEAD", "OPTIONS"}:
            n += 1
            resp = client.request(method, concrete, json={} if method in ("POST", "PUT", "PATCH", "DELETE") else None)
            if (method, path) in auth.PUBLIC:
                continue
            if resp.status_code != 401:
                open_routes.append((method, path, resp.status_code))
    check(n > 60, f"The sweep covered {n} method/route pairs")
    check(not open_routes, f"No route answers without a sign-in (open: {open_routes})")
    check(len(auth.PUBLIC) <= 9, "The public list is short and explicit")

    for path in (resume_a_path,):
        try:
            path.unlink()
        except OSError:
            pass
    check.done("ACCOUNT AND ISOLATION")


if __name__ == "__main__":
    run()
