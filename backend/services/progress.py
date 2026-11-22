"""
Live progress of a pipeline run, shared between the worker thread and the status endpoint.

The pipeline calls the update methods as it works; GET /api/automation/status returns snapshot().
Everything is guarded by one lock and snapshot() returns plain copies, so polling once a second is
cheap and never sees a half-written state.

Stages, in order: starting -> fetching -> deduplicating -> filtering -> scoring -> saving -> done | failed.
Per-source states: waiting -> running -> done | failed | skipped (with a plain-language reason).
"""
import copy
import datetime
import re
import threading
import time
import uuid
from typing import Any, Optional

import tenancy

STAGES = ["starting", "fetching", "deduplicating", "filtering", "scoring", "saving", "done"]
STAGE_LABELS = {
    "starting": "Starting",
    "fetching": "Fetching jobs from sources",
    "deduplicating": "Merging duplicates",
    "filtering": "Applying your filters",
    "scoring": "Scoring jobs",
    "saving": "Saving matches",
    "done": "Finished",
    "failed": "Failed",
}
MAX_NEW_IDS = 300


def _now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def plain_source_error(message: Optional[str]) -> Optional[str]:
    """Turn a technical source error into a sentence a user understands."""
    if not message:
        return message
    text = str(message)
    low = text.lower()
    if low.startswith("missing:"):
        return "Not set up: missing " + text.split(":", 1)[1].strip()
    if "monthly budget" in low:
        return "Skipped: this month's request budget is used up"
    if "per-run cap" in low:
        return "Stopped early: per-run request limit reached"
    if "rejected the credentials" in low or "http 401" in low or "http 403" in low:
        return "The API key was rejected (check it in backend/.env)"
    if "http 429" in low or "rate limit" in low:
        return "Rate limited by the provider; try again later"
    if "timed out" in low or "timeout" in low:
        return "The source did not answer in time"
    if "connection failed" in low or "connecterror" in low:
        return "Could not connect (network problem or the site is down)"
    m = re.search(r"http (5\d\d)", low)
    if m:
        return f"The source is having problems (HTTP {m.group(1)})"
    return re.sub(r"^\w+Error:\s*", "", text)[:240]


class RunProgress:
    """Progress of the current (or last) pipeline run."""

    def __init__(self):
        self._lock = threading.Lock()
        self._state: dict[str, Any] = self._blank()
        self._t0: Optional[float] = None

    @staticmethod
    def _blank() -> dict:
        return {
            "run_id": None, "active": False, "stage": "idle", "stage_label": "Idle", "stages": STAGES,
            "started_at": None, "finished_at": None, "elapsed_seconds": 0.0,
            "message": "", "sources": {}, "source_order": [],
            "fetched": 0, "unique": 0, "processed": 0, "total": 0,
            "saved": 0, "new_job_ids": [], "saved_by_source": {},
            "summary": None, "error": None,
        }

    # --- lifecycle -------------------------------------------------------------------------
    def begin(self, message: str = "Starting the job search...") -> str:
        with self._lock:
            self._state = self._blank()
            self._t0 = time.monotonic()
            self._state.update(run_id=uuid.uuid4().hex[:12], active=True, stage="starting",
                               stage_label=STAGE_LABELS["starting"], started_at=_now_iso(), message=message)
            return self._state["run_id"]

    def is_active(self) -> bool:
        with self._lock:
            return bool(self._state["active"])

    def finish(self, ok: bool, message: str, summary: Optional[dict] = None, error: Optional[str] = None) -> None:
        with self._lock:
            stage = "done" if ok else "failed"
            self._state.update(active=False, stage=stage, stage_label=STAGE_LABELS[stage], message=message,
                               finished_at=_now_iso(), summary=summary, error=error)
            if self._t0 is not None:
                self._state["elapsed_seconds"] = round(time.monotonic() - self._t0, 1)
            # Sources that never started (e.g. the run failed early) are not left "waiting".
            for entry in self._state["sources"].values():
                if entry["state"] in ("waiting", "running"):
                    entry["state"] = "skipped" if entry["state"] == "waiting" else "failed"
                    entry["reason"] = entry.get("reason") or ("Run stopped" if ok else "Run failed")

    # --- updates ---------------------------------------------------------------------------
    def stage(self, name: str, message: Optional[str] = None) -> None:
        with self._lock:
            self._state["stage"] = name
            self._state["stage_label"] = STAGE_LABELS.get(name, name)
            if message is not None:
                self._state["message"] = message

    def message(self, text: str) -> None:
        with self._lock:
            self._state["message"] = text

    def source(self, name: str, state: str, label: Optional[str] = None, count: Optional[int] = None,
               reason: Optional[str] = None) -> None:
        with self._lock:
            entry = self._state["sources"].get(name)
            if entry is None:
                entry = {"name": name, "label": label or name, "state": state, "count": 0, "reason": None,
                         "started_at": None, "seconds": None}
                self._state["sources"][name] = entry
                self._state["source_order"].append(name)
            if label:
                entry["label"] = label
            if state == "running":
                entry["started_at"] = time.monotonic()
            elif state in ("done", "failed") and entry.get("started_at"):
                entry["seconds"] = round(time.monotonic() - entry["started_at"], 1)
            entry["state"] = state
            if count is not None:
                entry["count"] = count
            if reason is not None:
                entry["reason"] = plain_source_error(reason)
            if state == "running":
                self._state["message"] = f"Fetching from {entry['label']}..."

    def counts(self, **values) -> None:
        with self._lock:
            for key, value in values.items():
                self._state[key] = value

    def saved_job(self, job_id: int, source: Optional[str]) -> None:
        with self._lock:
            self._state["saved"] += 1
            if len(self._state["new_job_ids"]) < MAX_NEW_IDS:
                self._state["new_job_ids"].append(job_id)
            key = (source or "unknown").lower()
            self._state["saved_by_source"][key] = self._state["saved_by_source"].get(key, 0) + 1

    def processed(self, n: int = 1) -> None:
        with self._lock:
            self._state["processed"] += n

    # --- read ------------------------------------------------------------------------------
    def snapshot(self) -> dict:
        with self._lock:
            state = copy.deepcopy(self._state)
            if state["active"] and self._t0 is not None:
                state["elapsed_seconds"] = round(time.monotonic() - self._t0, 1)
        state["sources"] = [_public_source(state["sources"][n]) for n in state.pop("source_order")]
        return state


def _public_source(entry: dict) -> dict:
    out = {k: v for k, v in entry.items() if k != "started_at"}
    return out


class _ProgressPerUser:
    """`progress` as the pipeline and the status endpoint use it, but one independent RunProgress per user.

    Whichever user the current thread works for (tenancy.tenant_scope / the sign-in check) decides which tracker
    every call goes to, so one person's search never shows up on, or overwrites, another person's dashboard.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._by_user: dict[str, RunProgress] = {}

    def _current(self) -> RunProgress:
        key = tenancy.current_key()
        with self._lock:
            if key not in self._by_user:
                self._by_user[key] = RunProgress()
            return self._by_user[key]

    def __getattr__(self, name: str):
        return getattr(self._current(), name)


progress = _ProgressPerUser()
