"""
Offline tests for the AI provider layer (services/llm): provider order, fall-through on rate limits /
server errors / invalid JSON, Groq token throttling, schema validation, task -> model selection.
"""
import json
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent))

from testing_utils import Checker, mock_client

import httpx
from pydantic import BaseModel
from google.genai import errors as genai_errors

from services import llm
from services.llm import openai_compat, router

for name in ("LLM_PROVIDER_ORDER", "GROQ_MODEL", "GROQ_MODEL_EXTRACT", "GROQ_MODEL_WRITE", "OPENROUTER_API_KEY",
             "GEMINI_MODEL_EXTRACT", "GEMINI_MODEL_WRITE"):
    os.environ.pop(name, None)
os.environ["GEMINI_API_KEY"] = "test-gemini"
os.environ["GROQ_API_KEY"] = "test-groq"
os.environ["GEMINI_MODEL"] = "gemini-test-model"


class Facts(BaseModel):
    skills: list[str]
    min_years: float | None = None


def reset():
    for p in router.PROVIDERS.values():
        p._cooldown_until = 0.0
        if hasattr(p, "_remaining_tokens"):
            p._remaining_tokens, p._reset_at = None, 0.0


def gemini_client(text=None, error=None):
    client = MagicMock()
    if error is not None:
        client.models.generate_content.side_effect = error
    else:
        resp = MagicMock()
        resp.text = text
        client.models.generate_content.return_value = resp
    return client


def groq_reply(content, status=200, headers=None):
    body = {"choices": [{"message": {"content": content}}]} if status == 200 else {"error": {"message": "x"}}
    return httpx.Response(status, json=body, headers=headers or {})


def run():
    check = Checker("RUNNING OFFLINE AI PROVIDER LAYER TESTS")

    check.section("1. Provider order and models")
    check([p.name for p in llm.provider_order()] == ["gemini", "groq", "openrouter"], "Default order gemini, groq, openrouter")
    check(llm.available_providers() == ["gemini", "groq"], "OpenRouter skipped without a key")
    with patch.dict(os.environ, {"LLM_PROVIDER_ORDER": "groq, gemini"}):
        check([p.name for p in llm.provider_order()] == ["groq", "gemini"], "LLM_PROVIDER_ORDER respected")
    groq = router.PROVIDERS["groq"]
    check(groq.model_for("extract") == "openai/gpt-oss-20b" and groq.model_for("write") == "openai/gpt-oss-120b",
          "Groq: small model for extract, bigger for write")
    with patch.dict(os.environ, {"GROQ_MODEL_WRITE": "qwen/qwen3.8-27b"}):
        check(groq.model_for("write") == "qwen/qwen3.8-27b" and groq.model_for("extract") == "openai/gpt-oss-20b",
              "Per-task env override")
    check(router.PROVIDERS["gemini"].model_for("extract") == "gemini-test-model", "Gemini uses GEMINI_MODEL")

    check.section("2. Happy path and schema validation")
    reset()
    r = llm.generate_json("extract", "Extract JSON", schema=Facts,
                          clients={"gemini": gemini_client('{"skills": ["Python"], "min_years": 1}')})
    check(r.provider == "gemini" and r.data == {"skills": ["Python"], "min_years": 1.0}, "Gemini answer validated")
    r = llm.generate_json("extract", "x", clients={"gemini": gemini_client('```json\n{"a": 1}\n```')})
    check(r.data == {"a": 1}, "Markdown-fenced JSON accepted")

    check.section("3. Fall-through to the next provider")
    seen = []
    groq_client = mock_client({"api.groq.com": lambda req: groq_reply('{"skills": ["SQL"]}')}, seen)
    reset()
    rate_limited = genai_errors.APIError(429, {"error": {"message": "RESOURCE_EXHAUSTED", "status": "RESOURCE_EXHAUSTED"}})
    r = llm.generate_json("extract", "x", schema=Facts,
                          clients={"gemini": gemini_client(error=rate_limited), "groq": groq_client})
    check(r.provider == "groq" and r.data["skills"] == ["SQL"], "Gemini 429 -> Groq answers")
    body = json.loads(seen[0].read())
    check(body["response_format"] == {"type": "json_object"} and body["model"] == "openai/gpt-oss-20b",
          "Groq called in JSON mode with the extract model")
    check(seen[0].headers["authorization"] == "Bearer test-groq", "Bearer auth header")
    check(router.PROVIDERS["gemini"].cooling_down(), "Rate-limited Gemini is put on cooldown")
    seen.clear()
    r = llm.generate_json("extract", "x", clients={"gemini": gemini_client('{"never": 1}'), "groq": groq_client})
    check(r.provider == "groq", "While cooling down, Gemini is skipped without a call")

    reset()
    r = llm.generate_json("extract", "x", schema=Facts,
                          clients={"gemini": gemini_client('{"skills": "not-a-list"}'), "groq": groq_client})
    check(r.provider == "groq", "Schema-invalid JSON falls through")
    reset()
    r = llm.generate_json("extract", "x", clients={"gemini": gemini_client("I think the answer is..."), "groq": groq_client})
    check(r.provider == "groq", "Non-JSON text falls through")
    reset()
    overloaded = genai_errors.APIError(503, {"error": {"message": "overloaded", "status": "UNAVAILABLE"}})
    r = llm.generate_json("write", "x", clients={"gemini": gemini_client(error=overloaded), "groq": groq_client})
    check(r.provider == "groq" and r.model == "openai/gpt-oss-120b", "Gemini 503 -> Groq write model")

    reset()
    bad_groq = mock_client({"api.groq.com": lambda req: groq_reply("", status=500)})
    try:
        llm.generate_json("extract", "x", clients={"gemini": gemini_client(error=overloaded), "groq": bad_groq})
        raised = False
    except llm.LLMUnavailableError as exc:
        raised = "test-groq" not in str(exc) and "gemini" in str(exc) and "groq" in str(exc)
    check(raised, "All providers failing -> LLMUnavailableError listing each (no key in message)")

    with patch.dict(os.environ, {"GEMINI_API_KEY": "", "GROQ_API_KEY": ""}):
        try:
            llm.generate_json("extract", "x")
            none = False
        except llm.LLMUnavailableError as exc:
            none = "No AI provider" in str(exc)
    check(none, "No configured provider -> clear LLMUnavailableError")

    check.section("4. Groq throttling (tokens per minute)")
    reset()
    os.environ["LLM_PROVIDER_ORDER"] = "groq"
    low = mock_client({"api.groq.com": lambda req: groq_reply('{"ok": 1}', headers={
        "x-ratelimit-remaining-tokens": "100", "x-ratelimit-reset-tokens": "7.5s"})})
    with patch("services.llm.openai_compat._sleep") as fake_sleep:
        llm.generate_json("extract", "x" * 300, clients={"groq": low})
        llm.generate_json("extract", "x" * 300, clients={"groq": low})
    check(fake_sleep.call_count == 1 and 7.0 <= fake_sleep.call_args[0][0] <= 7.5,
          "Second call waits for the token window to reset (headers read)")

    reset()
    calls = {"n": 0}

    def limited(req):
        calls["n"] += 1
        if calls["n"] == 1:
            return groq_reply("", status=429, headers={"retry-after": "3"})
        return groq_reply('{"ok": 2}')

    with patch("services.llm.openai_compat._sleep") as fake_sleep:
        r = llm.generate_json("extract", "x", clients={"groq": mock_client({"api.groq.com": limited})})
    check(r.data == {"ok": 2} and fake_sleep.call_args[0][0] == 3.0, "429 with short retry-after: wait, retry once")

    reset()
    long_wait = mock_client({"api.groq.com": lambda req: groq_reply("", status=429, headers={"retry-after": "120"})})
    with patch("services.llm.openai_compat._sleep") as fake_sleep:
        try:
            llm.generate_json("extract", "x", clients={"groq": long_wait})
            ok = False
        except llm.LLMUnavailableError:
            ok = fake_sleep.call_count == 0 and router.PROVIDERS["groq"].cooling_down()
    check(ok, "429 with a long retry-after: no sleep, provider cools down, next provider used")
    os.environ.pop("LLM_PROVIDER_ORDER")

    check(openai_compat.parse_duration("2m59.5s") == 179.5 and openai_compat.parse_duration("120ms") == 0.12
          and openai_compat.parse_duration("30") == 30.0, "Rate-limit durations parsed")

    check.done("AI PROVIDER LAYER")


if __name__ == "__main__":
    run()
