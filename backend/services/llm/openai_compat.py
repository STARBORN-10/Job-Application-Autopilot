"""
OpenAI-compatible chat providers: Groq (primary fallback) and OpenRouter (optional).

Groq's free tier is generous on requests but small on tokens per minute (about 8000 TPM), so the
Groq provider reads the x-ratelimit-* headers of each response and, before the next call, waits for
the token window to reset when the remaining budget is too small (never longer than
GROQ_MAX_WAIT_SECONDS; otherwise it hands over to the next provider).
"""
import os
import re
import time
from typing import Optional

import httpx

from services.llm.base import Provider, ProviderError

_sleep = time.sleep  # patched in tests


def parse_duration(value: Optional[str]) -> Optional[float]:
    """'7.66s' / '2m59.5s' / '120ms' / '1h2m' / '30' -> seconds."""
    if not value:
        return None
    value = value.strip()
    try:
        return float(value)
    except ValueError:
        pass
    total, matched = 0.0, False
    for number, unit in re.findall(r"([\d.]+)\s*(ms|h|m|s)", value):
        matched = True
        total += float(number) * {"ms": 0.001, "s": 1, "m": 60, "h": 3600}[unit]
    return total if matched else None


class OpenAICompatibleProvider(Provider):
    url = ""
    max_tokens_field = "max_completion_tokens"
    throttle = False

    def __init__(self):
        super().__init__()
        self._remaining_tokens: Optional[int] = None
        self._reset_at = 0.0

    def _max_wait(self) -> float:
        try:
            return float(os.getenv(f"{self.name.upper()}_MAX_WAIT_SECONDS", "20"))
        except ValueError:
            return 20.0

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {os.getenv(self.key_env, '').strip()}", "Content-Type": "application/json"}

    def _body(self, task, prompt, system, max_tokens) -> dict:
        model = self.model_for(task)
        body = {
            "model": model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
            "response_format": {"type": "json_object"},
            "temperature": 0.2 if task == "extract" else 0.5,
            self.max_tokens_field: max_tokens,
        }
        if model.startswith("openai/gpt-oss"):
            body["reasoning_effort"] = "low"   # reasoning tokens count against the TPM budget
        return body

    def _wait_for_tokens(self, estimate: int) -> None:
        if not self.throttle or self._remaining_tokens is None:
            return
        now = time.monotonic()
        if self._remaining_tokens >= estimate or now >= self._reset_at:
            return
        wait = self._reset_at - now
        if wait > self._max_wait():
            raise ProviderError(f"{self.name} token budget exhausted for {wait:.0f}s", cooldown_seconds=wait)
        _sleep(wait)

    def _update_limits(self, response: httpx.Response) -> None:
        remaining = response.headers.get("x-ratelimit-remaining-tokens")
        reset = parse_duration(response.headers.get("x-ratelimit-reset-tokens"))
        if remaining is not None:
            try:
                self._remaining_tokens = int(float(remaining))
            except ValueError:
                self._remaining_tokens = None
        if reset is not None:
            self._reset_at = time.monotonic() + reset

    def _post(self, body: dict, client: Optional[httpx.Client]) -> httpx.Response:
        try:
            if client is not None:
                return client.post(self.url, json=body, headers=self._headers(), timeout=60.0)
            with httpx.Client() as c:
                return c.post(self.url, json=body, headers=self._headers(), timeout=60.0)
        except httpx.TimeoutException:
            raise ProviderError(f"{self.name} request timed out", cooldown_seconds=10)
        except httpx.RequestError as exc:
            raise ProviderError(f"{self.name} connection failed ({type(exc).__name__})", cooldown_seconds=10)

    def complete_json(self, task, prompt, system, max_tokens, client=None) -> str:
        body = self._body(task, prompt, system, max_tokens)
        estimate = (len(system) + len(prompt)) // 3 + max_tokens
        self._wait_for_tokens(estimate)

        for attempt in (1, 2):
            response = self._post(body, client)
            self._update_limits(response)
            if response.status_code == 429:
                retry_after = parse_duration(response.headers.get("retry-after")) or 30.0
                if attempt == 1 and retry_after <= self._max_wait():
                    _sleep(retry_after)
                    continue
                raise ProviderError(f"{self.name} rate limited (retry after {retry_after:.0f}s)",
                                    cooldown_seconds=retry_after)
            break

        code = response.status_code
        if code in (401, 403):
            raise ProviderError(f"{self.name} rejected the API key (HTTP {code})", cooldown_seconds=3600)
        if code >= 500:
            raise ProviderError(f"{self.name} server error (HTTP {code})", cooldown_seconds=15)
        if code >= 400:
            detail = ""
            try:
                detail = (response.json().get("error") or {}).get("message", "")[:160]
            except (ValueError, AttributeError):
                pass
            raise ProviderError(f"{self.name} HTTP {code}: {detail}")
        try:
            content = response.json()["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError):
            raise ProviderError(f"{self.name} returned an unexpected response shape")
        return content or ""


class GroqProvider(OpenAICompatibleProvider):
    name = "groq"
    key_env = "GROQ_API_KEY"
    url = "https://api.groq.com/openai/v1/chat/completions"
    throttle = True
    default_models = {"extract": "openai/gpt-oss-20b", "write": "openai/gpt-oss-120b"}


class OpenRouterProvider(OpenAICompatibleProvider):
    name = "openrouter"
    key_env = "OPENROUTER_API_KEY"
    url = "https://openrouter.ai/api/v1/chat/completions"
    max_tokens_field = "max_tokens"
    default_models = {"extract": "meta-llama/llama-3.3-70b-instruct:free",
                      "write": "meta-llama/llama-3.3-70b-instruct:free"}
