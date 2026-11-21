"""
AI provider layer: Gemini, Groq and OpenRouter behind one call.

    from services import llm
    result = llm.generate_json("extract", prompt, schema=MyModel)   # -> LLMResult(data, provider, model)

Tasks: "extract" (small, fast model) and "write" (better model). See router.py for the fallback rules.
"""
from services.llm.base import LLMError, LLMUnavailableError, ProviderError
from services.llm.router import LLMResult, PROVIDERS, available_providers, generate_json, provider_order

__all__ = [
    "LLMError", "LLMUnavailableError", "ProviderError", "LLMResult", "PROVIDERS",
    "available_providers", "generate_json", "provider_order",
]
