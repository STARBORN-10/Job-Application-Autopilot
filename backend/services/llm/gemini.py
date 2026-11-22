"""Gemini provider: reuses the V1 Gemini call (services/ai_service.py) and its error mapping."""
import os

from services import ai_service
from services.llm.base import Provider, ProviderError


class GeminiProvider(Provider):
    name = "gemini"
    key_env = "GEMINI_API_KEY"

    def model_for(self, task: str) -> str:
        return (
            (os.getenv(f"GEMINI_MODEL_{task.upper()}") or "").strip()
            or ai_service.get_gemini_model_name()
        )

    def complete_json(self, task, prompt, system, max_tokens, client=None) -> str:
        try:
            return ai_service._generate_json_text(
                prompt,
                None,
                self.model_for(task),
                client,
                system_instruction=system,
                temperature=0.2 if task == "extract" else 0.5,
            )
        except ai_service.AIRateLimitError as exc:
            raise ProviderError(f"Gemini rate limited: {str(exc)[:160]}", cooldown_seconds=60)
        except ai_service.AITimeoutError as exc:
            raise ProviderError(f"Gemini unavailable/timeout: {str(exc)[:160]}", cooldown_seconds=20)
        except ai_service.AIError as exc:
            # Auth/config/unknown errors: this provider will not work this run, but others may.
            raise ProviderError(f"Gemini error: {str(exc)[:160]}", cooldown_seconds=300)
