"""
Telegram approve / skip flow.

Job alerts carry three buttons (Approve, Skip, Cover letter). A tap arrives as a `callback_query`
update, either through the webhook (POST /api/telegram/webhook, verified with the
X-Telegram-Bot-Api-Secret-Token header) or, for local development without a public URL, through a
long-polling loop (TELEGRAM_MODE=polling). Only updates from TELEGRAM_CHAT_ID are obeyed.
Everything degrades to a logged no-op when the bot is not configured.
"""
import logging
import os
import threading
from typing import Any, Callable, Optional

import httpx

import crud
from services import notification_service as tg
from services.decisions import record_decision
from services.scoring.writer import ensure_cover_letter

logger = logging.getLogger("telegram_bot")

ACTIONS = {"approve": "approved", "skip": "skipped"}


def configured_chat_id() -> Optional[str]:
    return (os.getenv("TELEGRAM_CHAT_ID") or "").strip() or None


def webhook_secret() -> Optional[str]:
    return (os.getenv("TELEGRAM_WEBHOOK_SECRET") or "").strip() or None


def _chat_id_of(update: dict) -> Optional[str]:
    if "callback_query" in update:
        cq = update["callback_query"]
        chat = ((cq.get("message") or {}).get("chat") or {}).get("id")
        return str(chat if chat is not None else (cq.get("from") or {}).get("id"))
    if "message" in update:
        return str(((update["message"].get("chat") or {}).get("id")))
    return None


def _outcome_keyboard(label: str, job_id: int) -> dict:
    return {"inline_keyboard": [[{"text": label, "callback_data": "noop"}],
                                [{"text": "Cover letter", "callback_data": f"cover:{job_id}"}]]}


def _safe(call: Callable[[], Any], what: str) -> Any:
    try:
        return call()
    except tg.TelegramNotificationError as exc:
        logger.warning(f"Telegram {what} failed: {exc}")
        return None


def handle_update(db, update: dict, client: Optional[httpx.Client] = None,
                  on_approved: Optional[Callable] = None) -> dict:
    """Process one Telegram update. Returns a small dict describing what happened (for logs and tests)."""
    allowed = configured_chat_id()
    chat_id = _chat_id_of(update)
    if not allowed:
        logger.warning(f"Telegram update from chat {chat_id} ignored: TELEGRAM_CHAT_ID is not set. "
                       "Set it to this chat id to authorise it.")
        return {"handled": False, "reason": "chat_not_configured", "chat_id": chat_id}
    if chat_id != allowed:
        logger.warning(f"Telegram update from unauthorised chat {chat_id} ignored")
        return {"handled": False, "reason": "unauthorised_chat"}

    cq = update.get("callback_query")
    if not cq:
        return {"handled": False, "reason": "not_a_button_tap"}
    data = cq.get("data") or ""
    action, _, raw_id = data.partition(":")

    def answer(text: str) -> None:
        _safe(lambda: tg.call_telegram("answerCallbackQuery", {"callback_query_id": cq.get("id"), "text": text},
                                       client), "answerCallbackQuery")

    if action == "noop":
        answer("Already decided")
        return {"handled": True, "action": "noop"}
    if not raw_id.isdigit() or action not in (*ACTIONS, "cover"):
        answer("Unknown action")
        return {"handled": False, "reason": "bad_callback_data"}

    job = crud.get_job(db, int(raw_id))
    if job is None:
        answer("This job no longer exists")
        return {"handled": False, "reason": "job_not_found"}

    if action == "cover":
        letter = ensure_cover_letter(db, job)
        answer("Sending the cover letter" if letter else "No cover letter available")
        if letter:
            text = f"Cover letter for {job.title} at {job.company}:\n\n{letter}"
            _safe(lambda: tg.send_telegram_notification(text, client=client, parse_mode=None), "sendMessage")
        return {"handled": True, "action": "cover", "job_id": job.id, "sent": bool(letter)}

    outcome = record_decision(db, job, ACTIONS[action], channel="telegram")
    result = {"handled": True, "action": action, "job_id": job.id, "changed": outcome.changed}
    label = "Approved" if action == "approve" else "Skipped"
    if outcome.changed and action == "approve" and on_approved is not None:
        application = on_approved(db, job)
        if application is not None:
            result["application_status"] = application.status
            label = f"Approved - {application.status.replace('_', ' ')}"
    answer(label if outcome.changed else f"Already {ACTIONS[action]}")
    message = cq.get("message") or {}
    if message.get("message_id") is not None:
        _safe(lambda: tg.call_telegram("editMessageReplyMarkup", {
            "chat_id": message["chat"]["id"], "message_id": message["message_id"],
            "reply_markup": _outcome_keyboard(label, job.id)}, client), "editMessageReplyMarkup")
    return result


def set_webhook(base_url: str, client: Optional[httpx.Client] = None) -> dict:
    """Register <base_url>/api/telegram/webhook with Telegram, including the secret token."""
    secret = webhook_secret()
    if not secret:
        raise tg.TelegramConfigError("TELEGRAM_WEBHOOK_SECRET is not set.")
    url = base_url.rstrip("/") + "/api/telegram/webhook"
    if not url.startswith("https://"):
        raise tg.TelegramConfigError("Telegram only delivers webhooks to https:// URLs.")
    tg.call_telegram("setWebhook", {"url": url, "secret_token": secret,
                                    "allowed_updates": ["callback_query", "message"]}, client)
    return {"webhook_url": url}


class Poller:
    """Long-polling loop for local development (TELEGRAM_MODE=polling). Runs in a daemon thread."""

    def __init__(self, session_factory, on_approved: Optional[Callable] = None, client: Optional[httpx.Client] = None):
        self.session_factory = session_factory
        self.on_approved = on_approved
        self.client = client
        self.offset: Optional[int] = None
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def poll_once(self, timeout: int = 25) -> int:
        payload = {"timeout": timeout, "allowed_updates": ["callback_query", "message"]}
        if self.offset is not None:
            payload["offset"] = self.offset
        updates = tg.call_telegram("getUpdates", payload, self.client, timeout=timeout + 10) or []
        for update in updates:
            self.offset = int(update["update_id"]) + 1
            db = self.session_factory()
            try:
                handle_update(db, update, self.client, self.on_approved)
            except Exception:
                logger.exception("Failed to handle a Telegram update")
            finally:
                db.close()
        return len(updates)

    def _loop(self) -> None:
        _safe(lambda: tg.call_telegram("deleteWebhook", {}, self.client), "deleteWebhook")
        while not self._stop.is_set():
            try:
                self.poll_once()
            except tg.TelegramNotificationError as exc:
                logger.warning(f"Telegram polling error: {exc}; retrying in 10s")
                self._stop.wait(10)

    def start(self) -> None:
        self._thread = threading.Thread(target=self._loop, name="telegram-poller", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()


def polling_enabled() -> bool:
    return (os.getenv("TELEGRAM_MODE") or "").strip().lower() == "polling"
