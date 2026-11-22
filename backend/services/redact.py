"""Remove secret values from text before it is logged, stored or returned by the API."""
import os

SECRET_ENV_VARS = (
    "RAPIDAPI_KEY", "JSEARCH_API_KEY", "GEMINI_API_KEY", "GROQ_API_KEY", "OPENROUTER_API_KEY",
    "ADZUNA_APP_ID", "ADZUNA_APP_KEY", "JOOBLE_API_KEY", "TELEGRAM_BOT_TOKEN", "TELEGRAM_WEBHOOK_SECRET",
    "SMTP_PASSWORD", "ADMIN_API_KEY", "MAKE_API_KEY",
)


def redact(text) -> str:
    text = str(text) if text is not None else ""
    for name in SECRET_ENV_VARS:
        value = (os.getenv(name) or "").strip()
        if len(value) >= 4 and value in text:
            text = text.replace(value, "***")
    return text
