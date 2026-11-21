"""
Settings and the submit gate for career-page form filling.

Default behaviour: fill the form and STOP (never submit). A form is only submitted when ALL of these hold:
- AUTOFILL_SUBMIT=true            (default false)
- APPLY_DRY_RUN=false             (default true)
- the job was explicitly approved (approval_status == "approved")
- no required field is left unfilled
- no CAPTCHA was detected on the page
AUTOFILL_MODE=prefill (the only mode; kept as a setting for clarity), AUTOFILL_HEADLESS (default true;
false leaves a visible browser window open locally so you can review and click Submit yourself).
"""
import os
from typing import Optional


def _flag(name: str, default: bool) -> bool:
    raw = (os.getenv(name) or "").strip().lower()
    if not raw:
        return default
    return raw not in ("false", "0", "no", "off")


def mode() -> str:
    return (os.getenv("AUTOFILL_MODE") or "prefill").strip().lower() or "prefill"


def submit_enabled() -> bool:
    return _flag("AUTOFILL_SUBMIT", False)


def headless() -> bool:
    return _flag("AUTOFILL_HEADLESS", True)


def on_approve() -> bool:
    return _flag("AUTOFILL_ON_APPROVE", True)


def timeout_seconds() -> float:
    try:
        return max(5.0, float(os.getenv("AUTOFILL_TIMEOUT_SECONDS", "45")))
    except ValueError:
        return 45.0


def keep_open_minutes() -> float:
    try:
        return max(0.0, float(os.getenv("AUTOFILL_KEEP_OPEN_MINUTES", "20")))
    except ValueError:
        return 20.0


def dry_run() -> bool:
    return _flag("APPLY_DRY_RUN", True)


def submit_decision(approval_status: Optional[str], unfilled_required: list, captcha: bool) -> tuple[bool, str]:
    """(allowed, reason). The reason is shown to the user either way."""
    if not submit_enabled():
        return False, "Not submitted: automatic submission is off (AUTOFILL_SUBMIT=false). Review the form and submit it yourself."
    if dry_run():
        return False, "Not submitted: dry run is on (APPLY_DRY_RUN=true)."
    if (approval_status or "pending") != "approved":
        return False, "Not submitted: the job is not approved."
    if unfilled_required:
        return False, f"Not submitted: {len(unfilled_required)} required field(s) need your answer."
    if captcha:
        return False, "Not submitted: the page has a CAPTCHA, which must be solved by you."
    return True, "All checks passed: submitting."


def describe() -> dict:
    return {"mode": mode(), "submit_enabled": submit_enabled(), "headless": headless(), "on_approve": on_approve(),
            "dry_run": dry_run(), "timeout_seconds": timeout_seconds()}
