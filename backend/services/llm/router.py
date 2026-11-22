"""
Provider fallback chain.

generate_json(task, prompt, schema) tries each configured provider in LLM_PROVIDER_ORDER
(default "gemini,groq,openrouter"). A rate limit, 5xx, timeout, auth problem or invalid JSON moves
on to the next provider; a provider that was rate limited is skipped for a short cooldown so the
rest of the run does not keep hitting it.
"""
import json
import logging
import os
import re
import threading
from dataclasses import dataclass
from typing import Optional, Type

from pydantic import BaseModel, ValidationError

from services.llm.base import TASKS, LLMUnavailableError, Provider, ProviderError
from services.llm.gemini import GeminiProvider
from services.llm.openai_compat import GroqProvider, OpenRouterProvider
from services.redact import redact

logger = logging.getLogger("llm")

PROVIDERS: dict[str, Provider] = {p.name: p for p in (GeminiProvider(), GroqProvider(), OpenRouterProvider())}
DEFAULT_ORDER = "gemini,groq,openrouter"
DEFAULT_SYSTEM = "You are a precise assistant. Reply with a single valid JSON object only, no markdown."

_lock = threading.Lock()  # one LLM call at a time keeps us inside free-tier rate limits


@dataclass
class LLMResult:
    data: dict
    provider: str
    model: str


def provider_order() -> list[Provider]:
    names = [n.strip().lower() for n in (os.getenv("LLM_PROVIDER_ORDER") or DEFAULT_ORDER).split(",") if n.strip()]
    return [PROVIDERS[n] for n in names if n in PROVIDERS]


def available_providers() -> list[str]:
    return [p.name for p in provider_order() if p.is_configured()]


def _parse(raw: str) -> dict:
    text = (raw or "").strip()
    if "```" in text:
        m = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
        if m:
            text = m.group(1).strip()
    if not text.startswith("{"):
        m = re.search(r"\{[\s\S]*\}", text)
        if m:
            text = m.group(0)
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("not a JSON object")
    return data


def generate_json(
    task: str,
    prompt: str,
    schema: Optional[Type[BaseModel]] = None,
    system: str = DEFAULT_SYSTEM,
    max_tokens: int = 700,
    clients: Optional[dict] = None,
) -> LLMResult:
    """Ask the first working provider for a JSON object (validated against `schema` when given)."""
    if task not in TASKS:
        raise ValueError(f"unknown task '{task}'")
    errors = []
    candidates = [p for p in provider_order() if p.is_configured()]
    if not candidates:
        raise LLMUnavailableError("No AI provider is configured (set GEMINI_API_KEY or GROQ_API_KEY).")

    for provider in candidates:
        if provider.cooling_down():
            errors.append(f"{provider.name}: cooling down")
            continue
        try:
            with _lock:
                raw = provider.complete_json(task, prompt, system, max_tokens, (clients or {}).get(provider.name))
            data = _parse(raw)
            if schema is not None:
                data = schema.model_validate(data).model_dump()
            return LLMResult(data=data, provider=provider.name, model=provider.model_for(task))
        except ProviderError as exc:
            provider.cool_down(exc.cooldown_seconds)
            errors.append(f"{provider.name}: {exc}")
        except (ValueError, ValidationError) as exc:
            errors.append(f"{provider.name}: invalid JSON ({type(exc).__name__})")
        logger.warning(f"LLM provider failed, trying next: {redact(errors[-1])}")

    raise LLMUnavailableError(redact("All AI providers failed: " + "; ".join(errors)))
