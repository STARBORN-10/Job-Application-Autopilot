"""
Small retry-with-exponential-backoff helper for transient external API failures.

Only exceptions listed in `retry_on` are retried; everything else (auth errors,
config errors, validation errors) propagates immediately so we never hammer an
API with a request that cannot succeed.
"""

import logging
import os
import random
import time
from typing import Callable, Tuple, Type, TypeVar

logger = logging.getLogger("retry")

T = TypeVar("T")


def _env_int(name: str, default: int) -> int:
    try:
        return max(1, int(os.getenv(name, default)))
    except (TypeError, ValueError):
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return max(0.0, float(os.getenv(name, default)))
    except (TypeError, ValueError):
        return default


def retry_call(
    fn: Callable[[], T],
    retry_on: Tuple[Type[BaseException], ...],
    label: str = "operation",
    attempts: int | None = None,
    base_delay: float | None = None,
    max_delay: float = 30.0,
) -> T:
    """
    Call `fn()` and retry on any exception in `retry_on`, with exponential backoff
    plus a little jitter. Re-raises the last error once attempts are exhausted.

    Defaults come from env vars RETRY_MAX_ATTEMPTS (3) and RETRY_BASE_DELAY_SECONDS (1.5).
    """
    attempts = attempts if attempts is not None else _env_int("RETRY_MAX_ATTEMPTS", 3)
    base_delay = base_delay if base_delay is not None else _env_float("RETRY_BASE_DELAY_SECONDS", 1.5)

    for attempt in range(1, attempts + 1):
        try:
            return fn()
        except retry_on as exc:
            if attempt >= attempts:
                logger.error(f"{label} failed after {attempts} attempt(s): {exc}")
                raise
            delay = min(max_delay, base_delay * (2 ** (attempt - 1)))
            delay += random.uniform(0, delay * 0.1)
            logger.warning(f"{label} attempt {attempt}/{attempts} failed ({exc}); retrying in {delay:.1f}s")
            time.sleep(delay)
    raise RuntimeError("unreachable")  # pragma: no cover
