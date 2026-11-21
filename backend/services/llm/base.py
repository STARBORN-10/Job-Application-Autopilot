"""Provider interface and errors for the LLM layer."""
import os
import time
from typing import Optional


class LLMError(Exception):
    """Base error of the LLM layer."""


class ProviderError(LLMError):
    """One provider failed. `fallthrough` errors (rate limit, 5xx, timeout, invalid JSON) move on to the next provider."""

    def __init__(self, message: str, fallthrough: bool = True, cooldown_seconds: float = 0.0):
        super().__init__(message)
        self.fallthrough = fallthrough
        self.cooldown_seconds = cooldown_seconds


class LLMUnavailableError(LLMError):
    """No provider is configured, or every configured provider failed."""


TASKS = ("extract", "write")


class Provider:
    name = ""
    key_env = ""
    default_models: dict[str, str] = {}

    def __init__(self):
        self._cooldown_until = 0.0

    def is_configured(self) -> bool:
        return bool((os.getenv(self.key_env) or "").strip())

    def model_for(self, task: str) -> str:
        """Per-task override (e.g. GROQ_MODEL_EXTRACT), then a provider-wide one (GROQ_MODEL), then the default."""
        prefix = self.name.upper()
        return (
            (os.getenv(f"{prefix}_MODEL_{task.upper()}") or "").strip()
            or (os.getenv(f"{prefix}_MODEL") or "").strip()
            or self.default_models.get(task)
            or self.default_models["extract"]
        )

    # --- cooldown after a rate limit, so later calls in the same run skip straight to the next provider
    def cooling_down(self) -> bool:
        return time.monotonic() < self._cooldown_until

    def cool_down(self, seconds: float) -> None:
        if seconds > 0:
            self._cooldown_until = max(self._cooldown_until, time.monotonic() + seconds)

    def complete_json(self, task: str, prompt: str, system: str, max_tokens: int, client: Optional[object] = None) -> str:
        """Return the raw JSON text produced by the model, or raise ProviderError."""
        raise NotImplementedError
