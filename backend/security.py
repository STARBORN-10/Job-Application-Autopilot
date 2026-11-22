"""
Protection for expensive or dangerous endpoints.

- ADMIN_API_KEY (optional): when set, endpoints that act on the user's behalf (approve / skip /
  apply, Telegram webhook registration, weight tuning) require the header `X-Admin-Key`.
  The trigger endpoint is NOT protected this way because the browser UI calls it.
  Note: a key placed in the frontend build (VITE_ADMIN_API_KEY) is visible to anyone who can load
  the site, so it only keeps out casual callers; keep the dashboard URL private.
- Trigger cooldown: at most one manual pipeline start per user per TRIGGER_COOLDOWN_SECONDS (default 120).
"""
import hmac
import os
import threading
import time

from fastapi import Header, HTTPException

import tenancy


def admin_key_configured() -> bool:
    return bool((os.getenv("ADMIN_API_KEY") or "").strip())


def require_admin(x_admin_key: str | None = Header(default=None)) -> bool:
    expected = (os.getenv("ADMIN_API_KEY") or "").strip()
    if not expected:
        return True
    if not x_admin_key or not hmac.compare_digest(x_admin_key.strip(), expected):
        raise HTTPException(status_code=401, detail="Missing or invalid X-Admin-Key header.")
    return True


class Cooldown:
    """Allows one action per window for each user; thread-safe."""

    def __init__(self, env_name: str, default_seconds: float):
        self.env_name = env_name
        self.default_seconds = default_seconds
        self._last_by_user: dict[str, float] = {}
        self._lock = threading.Lock()

    def seconds(self) -> float:
        try:
            return max(0.0, float(os.getenv(self.env_name, self.default_seconds)))
        except (TypeError, ValueError):
            return self.default_seconds

    def try_acquire(self) -> float:
        """Return 0 and start a new window if allowed, else the seconds left to wait."""
        key = tenancy.current_key()
        with self._lock:
            now = time.monotonic()
            window = self.seconds()
            last = self._last_by_user.get(key)
            if last is not None and now - last < window:
                return window - (now - last)
            self._last_by_user[key] = now
            return 0.0

    def remaining(self) -> float:
        """Seconds until the next action is allowed (0 when allowed now). Does not start a window."""
        key = tenancy.current_key()
        with self._lock:
            last = self._last_by_user.get(key)
            if last is None:
                return 0.0
            return max(0.0, self.seconds() - (time.monotonic() - last))

    def reset(self) -> None:
        with self._lock:
            self._last_by_user.clear()


trigger_cooldown = Cooldown("TRIGGER_COOLDOWN_SECONDS", 120.0)
