"""
Offline Unit Test Suite for Telegram Notification Service.
Tests message formatting, credential safety, character limits, HTML escaping,
and mocked Telegram API interactions using httpx.MockTransport.
Zero live network calls are made.
"""

import os
import sys
import json
from pathlib import Path
import httpx

# Ensure backend directory is in path
sys.path.insert(0, str(Path(__file__).parent))

from services.notification_service import (
    format_job_alert,
    get_telegram_credentials,
    get_dashboard_url,
    send_telegram_notification,
    send_job_alert,
    TelegramNotificationError,
    TelegramConfigError,
    TelegramAuthError,
    TelegramRateLimitError,
    TelegramNetworkError,
    MAX_TELEGRAM_MESSAGE_LENGTH,
)


def run_all_notification_tests():
    print("=" * 70)
    print("RUNNING OFFLINE TELEGRAM NOTIFICATION SERVICE UNIT TESTS (MOCKED)")
    print("=" * 70)

    total_tests = 0
    passed_tests = 0

    def assert_test(condition: bool, test_name: str):
        nonlocal total_tests, passed_tests
        total_tests += 1
        if condition:
            passed_tests += 1
            print(f"  [PASS] {test_name}")
        else:
            print(f"  [FAIL] {test_name}")
            raise AssertionError(f"Test failed: {test_name}")

    # -----------------------------------------------------------------------
    # 1. Message Formatting Tests
    # -----------------------------------------------------------------------
    print("\n--- 1. Testing format_job_alert ---")
    msg1 = format_job_alert(
        title="AI Engineer",
        company="NeuroTech Inc",
        score=9.2,
        match_reason="Matches your Python and NLP background.",
        url="https://example.com/apply/1",
        experience="1-2 years",
        location="Bengaluru (Remote)",
    )
    assert_test("<b>Role:</b> AI Engineer" in msg1, "Role formatted with HTML bold")
    assert_test("<b>Company:</b> NeuroTech Inc" in msg1, "Company formatted with HTML bold")
    assert_test("<b>Match Score:</b> 9.2/10" in msg1, "Match score formatted properly")
    assert_test("<b>Location:</b> Bengaluru (Remote)" in msg1, "Location included")
    assert_test("<b>Experience:</b> 1-2 years" in msg1, "Experience included")
    assert_test("https://example.com/apply/1" in msg1, "Apply link included")
    assert_test("View on Dashboard" in msg1, "Dashboard link included")

    # Minimal fields
    msg_min = format_job_alert(
        title="Backend Dev",
        company="Startup Co",
        score=7.0,
        match_reason="Basic match",
    )
    assert_test("<b>Role:</b> Backend Dev" in msg_min, "Minimal job formatted")
    assert_test("Location" not in msg_min, "Missing location omitted cleanly")
    assert_test("Experience" not in msg_min, "Missing experience omitted cleanly")
    assert_test("Apply Here" not in msg_min, "Missing URL omitted cleanly")

    # HTML escaping safety
    msg_escape = format_job_alert(
        title="C++ <Developer> & Architect",
        company="AT&T > Bell Labs",
        score=8.0,
        match_reason="Skills in <C++> & multi-threading",
    )
    assert_test("&lt;Developer&gt;" in msg_escape, "HTML < > tags escaped in title")
    assert_test("AT&amp;T &gt; Bell Labs" in msg_escape, "HTML & and > escaped in company")
    assert_test("&lt;C++&gt; &amp; multi-threading" in msg_escape, "HTML entities escaped in match reason")

    # Plain text mode
    msg_plain = format_job_alert(
        title="Data Analyst",
        company="Analytics Corp",
        score=8.5,
        match_reason="Good SQL skills",
        use_html=False,
    )
    assert_test("Role: Data Analyst" in msg_plain, "Plain text role formatted without tags")
    assert_test("<b>" not in msg_plain, "Plain text has zero HTML tags")

    # Enforcing Telegram 4096 character limit
    huge_reason = "Detailed skill analysis: " + ("Very long explanation sentence. " * 300)
    msg_huge = format_job_alert(
        title="Lead Architect",
        company="Global Enterprise",
        score=9.5,
        match_reason=huge_reason,
        url="https://example.com/long-url",
    )
    assert_test(len(msg_huge) <= MAX_TELEGRAM_MESSAGE_LENGTH, "Massive message truncated to <= 4096 chars")
    assert_test("[truncated]" in msg_huge or "..." in msg_huge, "Truncation indicator present in oversized message")

    # -----------------------------------------------------------------------
    # 2. Credential Handling Tests
    # -----------------------------------------------------------------------
    print("\n--- 2. Testing get_telegram_credentials ---")
    os.environ["TELEGRAM_BOT_TOKEN"] = "123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11"
    os.environ["TELEGRAM_CHAT_ID"] = "987654321"

    token, chat_id = get_telegram_credentials()
    assert_test(token == "123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11", "Token retrieved cleanly")
    assert_test(chat_id == "987654321", "Chat ID retrieved cleanly")

    # Missing token
    del os.environ["TELEGRAM_BOT_TOKEN"]
    try:
        get_telegram_credentials()
        assert_test(False, "Missing token should raise TelegramConfigError")
    except TelegramConfigError as exc:
        assert_test("TELEGRAM_BOT_TOKEN" in str(exc), "Missing token error identifies variable name")
        assert_test("123456" not in str(exc), "Error does not leak secret values")

    # Missing chat ID
    os.environ["TELEGRAM_BOT_TOKEN"] = "valid_token"
    del os.environ["TELEGRAM_CHAT_ID"]
    try:
        get_telegram_credentials()
        assert_test(False, "Missing chat ID should raise TelegramConfigError")
    except TelegramConfigError as exc:
        assert_test("TELEGRAM_CHAT_ID" in str(exc), "Missing chat ID error identifies variable name")

    # -----------------------------------------------------------------------
    # 3. Mocked Telegram API Network & Error Tests
    # -----------------------------------------------------------------------
    print("\n--- 3. Testing send_telegram_notification with MockTransport ---")
    os.environ["TELEGRAM_BOT_TOKEN"] = "test_bot_token"
    os.environ["TELEGRAM_CHAT_ID"] = "test_chat_id"

    # 3.1 Successful send
    def mock_handler_200(request: httpx.Request) -> httpx.Response:
        assert "bottest_bot_token/sendMessage" in str(request.url)
        body = json.loads(request.read())
        assert body.get("chat_id") == "test_chat_id"
        assert "New Job" in body.get("text")
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 999}})

    mock_client_200 = httpx.Client(transport=httpx.MockTransport(mock_handler_200))
    res = send_telegram_notification("🎯 New Job Opportunity Discovered!", client=mock_client_200)
    assert_test(res.get("ok") is True, "HTTP 200 returns valid Telegram response")
    assert_test(res.get("result", {}).get("message_id") == 999, "Returned message_id verified")

    # 3.2 Authentication failure (HTTP 401)
    def mock_handler_401(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"ok": False, "error_code": 401, "description": "Unauthorized"})

    mock_client_401 = httpx.Client(transport=httpx.MockTransport(mock_handler_401))
    try:
        send_telegram_notification("Test message", client=mock_client_401)
        assert_test(False, "HTTP 401 should raise TelegramAuthError")
    except TelegramAuthError:
        assert_test(True, "HTTP 401 raises TelegramAuthError cleanly")

    # 3.3 Rate limit (HTTP 429)
    def mock_handler_429(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"ok": False, "error_code": 429, "description": "Too Many Requests: retry after 5"})

    mock_client_429 = httpx.Client(transport=httpx.MockTransport(mock_handler_429))
    try:
        send_telegram_notification("Test message", client=mock_client_429)
        assert_test(False, "HTTP 429 should raise TelegramRateLimitError")
    except TelegramRateLimitError:
        assert_test(True, "HTTP 429 raises TelegramRateLimitError cleanly")

    # 3.4 Invalid Chat ID / Bad Request (HTTP 400)
    def mock_handler_400(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"ok": False, "error_code": 400, "description": "Bad Request: chat not found"})

    mock_client_400 = httpx.Client(transport=httpx.MockTransport(mock_handler_400))
    try:
        send_telegram_notification("Test message", client=mock_client_400)
        assert_test(False, "HTTP 400 Chat Not Found should raise TelegramNotificationError")
    except TelegramNotificationError:
        assert_test(True, "HTTP 400 Chat Not Found raises TelegramNotificationError cleanly")

    # 3.5 HTML Parse error fallback to plain text
    call_count = 0
    def mock_handler_html_fallback(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        body = json.loads(request.read())
        if call_count == 1:
            # First attempt with parse_mode='HTML' fails with entity parse error
            assert body.get("parse_mode") == "HTML"
            return httpx.Response(400, json={"ok": False, "description": "Bad Request: can't parse entities in message"})
        else:
            # Second attempt without parse_mode succeeds
            assert "parse_mode" not in body
            return httpx.Response(200, json={"ok": True, "result": {"message_id": 1000}})

    mock_client_fallback = httpx.Client(transport=httpx.MockTransport(mock_handler_html_fallback))
    fallback_res = send_telegram_notification("<b>Broken <Tag</b>", client=mock_client_fallback, parse_mode="HTML")
    assert_test(fallback_res.get("ok") is True, "HTML entity error gracefully retries and delivers as plain text")
    assert_test(call_count == 2, "Fallback executed exactly 2 requests (HTML then plain text)")

    # 3.6 Network Timeout
    def mock_handler_timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("Connection timed out after 10s")

    mock_client_timeout = httpx.Client(transport=httpx.MockTransport(mock_handler_timeout))
    try:
        send_telegram_notification("Test message", client=mock_client_timeout)
        assert_test(False, "Timeout should raise TelegramNetworkError")
    except TelegramNetworkError:
        assert_test(True, "Timeout raises TelegramNetworkError cleanly")

    # -----------------------------------------------------------------------
    # 4. send_job_alert Integration Test
    # -----------------------------------------------------------------------
    print("\n--- 4. Testing send_job_alert ---")
    mock_client_alert = httpx.Client(transport=httpx.MockTransport(mock_handler_200))
    alert_res = send_job_alert(
        title="Staff ML Engineer",
        company="HyperScale AI",
        score=9.8,
        match_reason="World-class fit for LLM inference optimization.",
        url="https://example.com/jobs/99",
        client=mock_client_alert,
    )
    assert_test(alert_res.get("ok") is True, "send_job_alert formats and dispatches successfully")

    # -----------------------------------------------------------------------
    # 5. V2: inline Approve / Skip / Cover letter buttons and generic Bot API calls
    # -----------------------------------------------------------------------
    print("\n--- 5. Testing inline keyboard and call_telegram ---")
    from services.notification_service import job_keyboard, call_telegram
    sent = {}

    def capture(request: httpx.Request) -> httpx.Response:
        sent["body"] = json.loads(request.read())
        sent["path"] = request.url.path
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 5}})

    send_job_alert(title="ML Engineer", company="Acme", score=8.1, match_reason="Fits", job_id=42,
                   client=httpx.Client(transport=httpx.MockTransport(capture)))
    buttons = [b["callback_data"] for row in sent["body"]["reply_markup"]["inline_keyboard"] for b in row]
    assert_test(buttons == ["approve:42", "skip:42", "cover:42"], "Alert with job_id carries Approve/Skip/Cover letter")
    send_job_alert(title="ML Engineer", company="Acme", score=8.1, match_reason="Fits",
                   client=httpx.Client(transport=httpx.MockTransport(capture)))
    assert_test("reply_markup" not in sent["body"], "Alert without job_id has no buttons (V1 behaviour)")
    assert_test(job_keyboard(7)["inline_keyboard"][0][0]["text"] == "Approve", "Keyboard labels")

    result = call_telegram("answerCallbackQuery", {"callback_query_id": "1", "text": "ok"},
                           client=httpx.Client(transport=httpx.MockTransport(capture)))
    assert_test(sent["path"].endswith("/answerCallbackQuery") and result == {"message_id": 5}, "call_telegram returns result")
    bad = httpx.Client(transport=httpx.MockTransport(
        lambda r: httpx.Response(400, json={"ok": False, "description": "message is not modified"})))
    try:
        call_telegram("editMessageReplyMarkup", {}, client=bad)
        raised = False
    except TelegramNotificationError as exc:
        raised = "not modified" in str(exc)
    assert_test(raised, "call_telegram maps API errors to TelegramNotificationError")

    print("\n" + "=" * 70)
    print(f"ALL {total_tests} TELEGRAM NOTIFICATION TESTS PASSED! ({passed_tests}/{total_tests})")
    print("=" * 70)


if __name__ == "__main__":
    run_all_notification_tests()
