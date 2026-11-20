"""
Telegram Notification Service Module
Dispatches formatted job opportunity alerts to Telegram via the Telegram Bot API.
"""

import os
import html
import logging
from typing import Optional, Dict, Any
import httpx

logger = logging.getLogger("notification_service")
logger.setLevel(logging.INFO)

TELEGRAM_API_BASE = "https://api.telegram.org"
MAX_TELEGRAM_MESSAGE_LENGTH = 4096
DEFAULT_TIMEOUT_SECONDS = 10.0


# ---------------------------------------------------------------------------
# Custom Exceptions
# ---------------------------------------------------------------------------
class TelegramNotificationError(Exception):
    """Base exception for Telegram notification failures."""
    pass


class TelegramConfigError(TelegramNotificationError):
    """Raised when TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID is missing or invalid."""
    pass


class TelegramAuthError(TelegramNotificationError):
    """Raised when Telegram rejects the bot token (HTTP 401 / 404)."""
    pass


class TelegramRateLimitError(TelegramNotificationError):
    """Raised when Telegram API rate limit is reached (HTTP 429)."""
    pass


class TelegramNetworkError(TelegramNotificationError):
    """Raised when an HTTP connection or timeout error occurs."""
    pass


# ---------------------------------------------------------------------------
# Credential & Configuration Helpers
# ---------------------------------------------------------------------------
def get_telegram_credentials() -> tuple[str, str]:
    """
    Safely retrieves the Telegram bot token and chat ID from environment variables.
    Raises TelegramConfigError if either is missing or empty.
    Never prints or logs the credentials.
    """
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")

    if not token or not token.strip():
        raise TelegramConfigError(
            "TELEGRAM_BOT_TOKEN is not configured in environment variables. Please add it to your .env file."
        )

    if not chat_id or not chat_id.strip():
        raise TelegramConfigError(
            "TELEGRAM_CHAT_ID is not configured in environment variables. Please add it to your .env file."
        )

    return token.strip(), chat_id.strip()


def get_dashboard_url() -> str:
    """Returns the configured frontend dashboard URL."""
    base_url = os.getenv("FRONTEND_URL", "http://localhost:5173").rstrip("/")
    return f"{base_url}/jobs"


# ---------------------------------------------------------------------------
# Message Formatter
# ---------------------------------------------------------------------------
def format_job_alert(
    title: str,
    company: str,
    score: float,
    match_reason: str,
    url: Optional[str] = None,
    experience: Optional[str] = None,
    location: Optional[str] = None,
    dashboard_url: Optional[str] = None,
    use_html: bool = True,
) -> str:
    """
    Formats a clean, structured job notification message.
    Escapes HTML entities safely if use_html is True.
    Guarantees output stays within Telegram's 4096-character limit.
    """
    dash_url = dashboard_url or get_dashboard_url()
    clean_score = f"{score:.1f}".rstrip("0").rstrip(".") if isinstance(score, (int, float)) else str(score)

    if use_html:
        safe_title = html.escape((title or "Unknown Role").strip())
        safe_company = html.escape((company or "Unknown Company").strip())
        safe_location = html.escape((location or "").strip())
        safe_experience = html.escape((experience or "").strip())
        safe_reason = html.escape((match_reason or "").strip())

        lines = [
            "🎯 <b>New Job Opportunity Discovered!</b>",
            "",
            f"<b>Role:</b> {safe_title}",
            f"<b>Company:</b> {safe_company}",
            f"<b>Match Score:</b> {clean_score}/10",
        ]

        if safe_location and safe_location.lower() != "not specified":
            lines.append(f"<b>Location:</b> {safe_location}")

        if safe_experience:
            lines.append(f"<b>Experience:</b> {safe_experience}")

        lines.append("")
        lines.append(f"<b>Reason:</b> {safe_reason}")

        if url and url.strip():
            safe_url = html.escape(url.strip())
            lines.append("")
            lines.append(f'👉 <a href="{safe_url}"><b>Apply Here</b></a>')

        lines.append(f'📊 <a href="{html.escape(dash_url)}"><b>View on Dashboard</b></a>')
        message = "\n".join(lines)

    else:
        # Plain text formatting
        raw_title = (title or "Unknown Role").strip()
        raw_company = (company or "Unknown Company").strip()
        lines = [
            "🎯 New Job Opportunity Discovered!",
            "",
            f"Role: {raw_title}",
            f"Company: {raw_company}",
            f"Match Score: {clean_score}/10",
        ]

        if location and location.strip() and location.strip().lower() != "not specified":
            lines.append(f"Location: {location.strip()}")

        if experience and experience.strip():
            lines.append(f"Experience: {experience.strip()}")

        lines.append("")
        lines.append(f"Reason: {(match_reason or '').strip()}")

        if url and url.strip():
            lines.append("")
            lines.append(f"Apply Link: {url.strip()}")

        lines.append(f"Dashboard: {dash_url}")
        message = "\n".join(lines)

    # Enforce Telegram 4096 character limit
    if len(message) > MAX_TELEGRAM_MESSAGE_LENGTH:
        overflow = len(message) - MAX_TELEGRAM_MESSAGE_LENGTH + 20
        # Truncate match reason if oversized
        if len(match_reason) > overflow + 50:
            truncated_reason = match_reason[:-overflow].strip() + "... [truncated]"
            return format_job_alert(
                title=title,
                company=company,
                score=score,
                match_reason=truncated_reason,
                url=url,
                experience=experience,
                location=location,
                dashboard_url=dashboard_url,
                use_html=use_html,
            )
        # Hard truncate as ultimate safeguard
        return message[:MAX_TELEGRAM_MESSAGE_LENGTH - 4] + "..."

    return message


# ---------------------------------------------------------------------------
# Notification Dispatcher
# ---------------------------------------------------------------------------
def send_telegram_notification(
    message: str,
    client: Optional[httpx.Client] = None,
    parse_mode: Optional[str] = "HTML",
) -> Dict[str, Any]:
    """
    Sends a message via the Telegram Bot API.
    Supports mocked httpx.Client injection for offline tests.
    If an HTML parse error occurs, gracefully falls back to plain text.
    """
    token, chat_id = get_telegram_credentials()
    api_url = f"{TELEGRAM_API_BASE}/bot{token}/sendMessage"

    payload = {
        "chat_id": chat_id,
        "text": message[:MAX_TELEGRAM_MESSAGE_LENGTH],
    }
    if parse_mode:
        payload["parse_mode"] = parse_mode

    logger.info(f"Dispatching Telegram notification to chat_id '{chat_id}'")

    def _post(c: httpx.Client, body: dict) -> httpx.Response:
        try:
            return c.post(api_url, json=body, timeout=DEFAULT_TIMEOUT_SECONDS)
        except httpx.TimeoutException as exc:
            raise TelegramNetworkError(f"Telegram API request timed out after {DEFAULT_TIMEOUT_SECONDS}s: {exc}")
        except httpx.RequestError as exc:
            raise TelegramNetworkError(f"Failed to connect to Telegram API: {exc}")

    def _execute(body: dict) -> httpx.Response:
        if client is not None:
            return _post(client, body)
        with httpx.Client() as default_client:
            return _post(default_client, body)

    response = _execute(payload)

    # Graceful fallback: If Telegram fails because of HTML entity parse error, retry without parse_mode
    if response.status_code == 400 and parse_mode:
        err_text = response.text.lower()
        if "can't parse entities" in err_text or "tag" in err_text or "parse" in err_text:
            logger.warning("HTML parse error from Telegram; falling back to plain text delivery.")
            payload_fallback = dict(payload)
            payload_fallback.pop("parse_mode", None)
            response = _execute(payload_fallback)

    # Status Code Validation
    if response.status_code in (401, 404):
        raise TelegramAuthError("Telegram authentication failed. Verify TELEGRAM_BOT_TOKEN is valid.")
    if response.status_code == 429:
        raise TelegramRateLimitError(f"Telegram rate limit reached: {response.text[:200]}")
    if response.status_code >= 400:
        raise TelegramNotificationError(f"Telegram API error HTTP {response.status_code}: {response.text[:200]}")

    try:
        data = response.json()
    except Exception as exc:
        raise TelegramNotificationError(f"Failed to parse Telegram response as JSON: {exc}")

    if not isinstance(data, dict) or not data.get("ok"):
        desc = data.get("description", "Unknown Telegram error") if isinstance(data, dict) else str(data)
        raise TelegramNotificationError(f"Telegram delivery rejected: {desc}")

    logger.info("Telegram notification delivered successfully.")
    return data


def send_job_alert(
    title: str,
    company: str,
    score: float,
    match_reason: str,
    url: Optional[str] = None,
    experience: Optional[str] = None,
    location: Optional[str] = None,
    client: Optional[httpx.Client] = None,
) -> Dict[str, Any]:
    """
    High-level convenience function to format and dispatch a job alert.
    """
    formatted_msg = format_job_alert(
        title=title,
        company=company,
        score=score,
        match_reason=match_reason,
        url=url,
        experience=experience,
        location=location,
        use_html=True,
    )
    return send_telegram_notification(formatted_msg, client=client, parse_mode="HTML")

