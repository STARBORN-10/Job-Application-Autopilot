"""
Offline tests for the Telegram approve/skip flow: callback handling, chat-id authorisation, the
webhook secret, set-webhook, polling, and the dashboard approve/skip endpoints with ADMIN_API_KEY.
All Telegram HTTP is mocked; no message is ever sent.
"""
import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent))

from testing_utils import Checker, mock_client, use_temp_database

use_temp_database()
os.environ["TELEGRAM_BOT_TOKEN"] = "123:test-token"
os.environ["TELEGRAM_CHAT_ID"] = "555"
os.environ["TELEGRAM_WEBHOOK_SECRET"] = "hook-secret-xyz"
os.environ.pop("ADMIN_API_KEY", None)

import httpx
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

import crud, models, schemas
import db_migrations
from database import engine, get_db
from main import app
from services import llm, telegram_bot

db_migrations.upgrade_database(engine)
Session = sessionmaker(bind=engine)


class FakeTelegram:
    """Records Bot API calls made through a mocked httpx client."""

    def __init__(self, updates=None):
        self.calls = []
        self.updates = list(updates or [])

    def handler(self, request: httpx.Request) -> httpx.Response:
        method = request.url.path.rsplit("/", 1)[-1]
        body = json.loads(request.read() or b"{}")
        self.calls.append((method, body))
        if method == "getUpdates":
            out, self.updates = self.updates, []
            return httpx.Response(200, json={"ok": True, "result": out})
        return httpx.Response(200, json={"ok": True, "result": True if method != "sendMessage" else {"message_id": 9}})

    def client(self):
        return mock_client({"api.telegram.org": self.handler})

    def methods(self):
        return [m for m, _ in self.calls]


def tap(job_id, action, chat_id=555, message_id=77, cq_id="cq1"):
    return {"update_id": 1000 + job_id, "callback_query": {
        "id": cq_id, "from": {"id": chat_id}, "data": f"{action}:{job_id}",
        "message": {"message_id": message_id, "chat": {"id": chat_id}, "text": "New Job"}}}


def run():
    check = Checker("RUNNING OFFLINE TELEGRAM APPROVAL TESTS")
    db = Session()
    job = crud.create_job(db, schemas.JobCreate(title="ML Engineer", company="Acme", url="https://x/1", score=8.4,
                                                score_breakdown={"total": 8.4, "parts": {}}))
    other = crud.create_job(db, schemas.JobCreate(title="Data Analyst", company="Beta", url="https://x/2", score=7.2,
                                                  cover_letter="Dear Beta team, ..."))

    check.section("1. Authorisation")
    tg = FakeTelegram()
    r = telegram_bot.handle_update(db, tap(job.id, "approve", chat_id=999), tg.client())
    check(r["handled"] is False and r["reason"] == "unauthorised_chat" and tg.calls == [],
          "Taps from another chat are ignored (no reply, no decision)")
    with patch.dict(os.environ, {"TELEGRAM_CHAT_ID": ""}):
        r = telegram_bot.handle_update(db, tap(job.id, "approve"), tg.client())
    check(r["reason"] == "chat_not_configured" and r["chat_id"] == "555", "Without TELEGRAM_CHAT_ID nothing is obeyed")
    db.refresh(job)
    check(job.approval_status == "pending", "Job still pending after ignored taps")

    check.section("2. Approve / Skip buttons")
    tg = FakeTelegram()
    r = telegram_bot.handle_update(db, tap(job.id, "approve"), tg.client())
    db.refresh(job)
    decisions = db.query(models.JobDecision).filter(models.JobDecision.job_id == job.id).all()
    check(r["handled"] and r["changed"] and job.approval_status == "approved", "Approve sets approval_status")
    check(len(decisions) == 1 and decisions[0].channel == "telegram" and decisions[0].score_snapshot == 8.4
          and json.loads(decisions[0].breakdown_snapshot)["total"] == 8.4, "Decision stored with score snapshot")
    check(tg.methods() == ["answerCallbackQuery", "editMessageReplyMarkup"], "Tap answered and buttons replaced")
    edited = dict(tg.calls)["editMessageReplyMarkup"]
    check(edited["message_id"] == 77 and edited["reply_markup"]["inline_keyboard"][0][0]["text"].startswith("Approved"),
          "Message now shows the outcome")
    tg = FakeTelegram()
    r = telegram_bot.handle_update(db, tap(job.id, "approve"), tg.client())
    check(r["changed"] is False and db.query(models.JobDecision).count() == 1, "Double tap does not duplicate the decision")
    r = telegram_bot.handle_update(db, tap(job.id, "skip"), tg.client())
    db.refresh(job)
    check(job.approval_status == "skipped" and db.query(models.JobDecision).count() == 2, "Changing the decision is recorded")

    check.section("3. Cover letter button and bad input")
    tg = FakeTelegram()
    r = telegram_bot.handle_update(db, tap(other.id, "cover"), tg.client())
    sent = [b for m, b in tg.calls if m == "sendMessage"]
    check(r["sent"] and sent and "Dear Beta team" in sent[0]["text"] and sent[0]["chat_id"] == "555",
          "Existing cover letter sent to the chat")
    tg = FakeTelegram()
    with patch("services.llm.available_providers", return_value=[]):
        crud.create_resume(db, filename="r.pdf", target_role="AI/ML Engineer", extracted_text="Python",
                           file_path="/tmp/r.pdf", file_size=1)
        with patch("services.scoring.writer.write_cover_letter", side_effect=llm.LLMUnavailableError("down")):
            r = telegram_bot.handle_update(db, tap(job.id, "cover"), tg.client())
    check(r["sent"] is False and tg.methods() == ["answerCallbackQuery"]
          and dict(tg.calls)["answerCallbackQuery"]["text"] == "No cover letter available",
          "No letter and no AI -> polite answer, nothing sent")
    with patch("services.scoring.writer.write_cover_letter", return_value=("Dear Acme, I build ML systems." * 3, "fake")):
        tg = FakeTelegram()
        r = telegram_bot.handle_update(db, tap(job.id, "cover"), tg.client())
    db.refresh(job)
    check(r["sent"] and job.cover_letter.startswith("Dear Acme"), "Missing letter written on demand and saved")
    for data, reason in [("approve:abc", "bad_callback_data"), ("delete:1", "bad_callback_data")]:
        u = tap(job.id, "approve")
        u["callback_query"]["data"] = data
        check(telegram_bot.handle_update(db, u, FakeTelegram().client())["reason"] == reason, f"'{data}' rejected")
    check(telegram_bot.handle_update(db, tap(99999, "approve"), FakeTelegram().client())["reason"] == "job_not_found",
          "Unknown job id handled")
    check(telegram_bot.handle_update(db, {"update_id": 1, "message": {"chat": {"id": 555}, "text": "hi"}},
                                     FakeTelegram().client())["reason"] == "not_a_button_tap", "Plain messages ignored")

    check.section("4. Polling mode")
    tg = FakeTelegram(updates=[tap(other.id, "approve")])
    poller = telegram_bot.Poller(Session, client=tg.client())
    n = poller.poll_once(timeout=0)
    db.expire_all()
    check(n == 1 and poller.offset == 1000 + other.id + 1, "getUpdates processed and offset advanced")
    check(crud.get_job(db, other.id).approval_status == "approved", "Polled tap recorded the decision")
    with patch.dict(os.environ, {"TELEGRAM_MODE": "polling"}):
        check(telegram_bot.polling_enabled(), "TELEGRAM_MODE=polling enables polling")
    check(not telegram_bot.polling_enabled(), "Polling is off by default")

    check.section("5. Webhook endpoint")

    def override():
        s = Session()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_db] = override
    api = TestClient(app)
    third = crud.create_job(db, schemas.JobCreate(title="Backend Dev", company="Gamma", url="https://x/3", score=7.5))
    with patch("services.notification_service.call_telegram") as fake_call:
        r = api.post("/api/telegram/webhook", json=tap(third.id, "skip"))
        check(r.status_code == 401, "Missing secret header -> 401")
        r = api.post("/api/telegram/webhook", json=tap(third.id, "skip"),
                     headers={"X-Telegram-Bot-Api-Secret-Token": "wrong"})
        check(r.status_code == 401, "Wrong secret -> 401")
        r = api.post("/api/telegram/webhook", json=tap(third.id, "skip"),
                     headers={"X-Telegram-Bot-Api-Secret-Token": "hook-secret-xyz"})
        db.expire_all()
        check(r.status_code == 200 and crud.get_job(db, third.id).approval_status == "skipped",
              "Valid webhook call processed (decision recorded)")
        check(fake_call.called, "Bot API answered through the (mocked) client")
        with patch.dict(os.environ, {"TELEGRAM_WEBHOOK_SECRET": ""}):
            r = api.post("/api/telegram/webhook", json={}, headers={"X-Telegram-Bot-Api-Secret-Token": "x"})
        check(r.status_code == 503, "Webhook refused when no secret is configured")

    check.section("6. set-webhook and ADMIN_API_KEY")
    with patch("services.notification_service.call_telegram", return_value=True) as fake_call:
        r = api.post("/api/telegram/set-webhook", json={"base_url": "https://autopilot.example.com/"})
        check(r.status_code == 200 and r.json()["webhook_url"] == "https://autopilot.example.com/api/telegram/webhook",
              "set-webhook registers <base>/api/telegram/webhook")
        args = fake_call.call_args[0]
        check(args[0] == "setWebhook" and args[1]["secret_token"] == "hook-secret-xyz", "Secret token sent to Telegram")
        check(api.post("/api/telegram/set-webhook", json={"base_url": "http://insecure"}).status_code == 422,
              "Non-https URL rejected")
        with patch.dict(os.environ, {"ADMIN_API_KEY": "admin-123"}):
            check(api.post("/api/telegram/set-webhook", json={"base_url": "https://a.b"}).status_code == 401,
                  "With ADMIN_API_KEY set, set-webhook needs X-Admin-Key")
            check(api.post("/api/jobs/1/approve").status_code == 401, "Approve needs X-Admin-Key")
            check(api.post("/api/jobs/1/skip", headers={"X-Admin-Key": "nope"}).status_code == 401, "Wrong key -> 401")
            r = api.post(f"/api/jobs/{third.id}/approve", headers={"X-Admin-Key": "admin-123"})
            check(r.status_code == 200 and r.json()["job"]["approval_status"] == "approved" and r.json()["changed"],
                  "Correct key -> approved")
            with patch("main.run_automation_pipeline"):
                from security import trigger_cooldown
                trigger_cooldown.reset()
                check(api.post("/api/automation/trigger").status_code == 200, "Trigger stays open (the browser calls it)")
                trigger_cooldown.reset()

    check.section("7. Dashboard endpoints without ADMIN_API_KEY")
    r = api.post(f"/api/jobs/{third.id}/skip")
    check(r.status_code == 200 and r.json()["job"]["approval_status"] == "skipped", "Skip from the dashboard")
    check(api.post("/api/jobs/99999/approve").status_code == 404, "Unknown job -> 404")
    dec = db.query(models.JobDecision).filter(models.JobDecision.job_id == third.id).all()
    check([d.channel for d in dec] == ["telegram", "dashboard", "dashboard"], "Channel recorded per decision")
    r = api.get("/api/jobs", params={"approval_status": "approved"})
    check(r.status_code == 200 and {j["id"] for j in r.json()} == {other.id}, "GET /api/jobs?approval_status filter")
    check(api.get("/api/jobs", params={"approval_status": "bogus"}).status_code == 422, "Invalid filter value -> 422")

    app.dependency_overrides.clear()
    db.close()
    check.done("TELEGRAM APPROVAL")


if __name__ == "__main__":
    run()
