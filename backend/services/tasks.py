"""
Tiny in-memory registry for slow background actions (e.g. filling a career-page form), so the UI can
poll GET /api/tasks/{id} and show "Opening page... Filling fields... Done".

Thread-safe; finished tasks are kept (most recent MAX_TASKS) so a page reload still shows the result.
The durable record of what happened is always written elsewhere (e.g. the applications table).

Every task remembers which user started it (`owner`): other users cannot see it, and its thread runs as that user.
"""
import copy
import datetime
import logging
import threading
import uuid
from typing import Any, Callable, Optional

import tenancy

logger = logging.getLogger("tasks")
MAX_TASKS = 100


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


class Task:
    def __init__(self, registry: "TaskRegistry", task_id: str):
        self._registry = registry
        self.id = task_id

    def step(self, message: str) -> None:
        self._registry._update(self.id, step=message)

    def update(self, **fields) -> None:
        self._registry._update(self.id, **fields)


class TaskRegistry:
    def __init__(self):
        self._lock = threading.Lock()
        self._tasks: dict[str, dict[str, Any]] = {}

    def active_for(self, kind: str, job_id: int) -> Optional[dict]:
        owner = tenancy.current_key()
        with self._lock:
            for t in self._tasks.values():
                if t["kind"] == kind and t["job_id"] == job_id and t["status"] == "running" and t["owner"] == owner:
                    return copy.deepcopy(t)
        return None

    def start(self, kind: str, job_id: Optional[int], target: Callable[[Task], Any], first_step: str = "Starting...") -> dict:
        """Run target(task) in a daemon thread; its return value becomes task["result"]."""
        task_id = uuid.uuid4().hex[:12]
        owner, owner_id = tenancy.current_key(), tenancy.current_user_id()
        with self._lock:
            self._tasks[task_id] = {"id": task_id, "kind": kind, "job_id": job_id, "status": "running",
                                    "step": first_step, "steps": [{"at": _now(), "message": first_step}],
                                    "result": None, "error": None, "started_at": _now(), "finished_at": None,
                                    "owner": owner}
            self._trim()
        task = Task(self, task_id)

        def run():
            try:
                with tenancy.tenant_scope(owner_id):
                    result = target(task)
                self._update(task_id, status="done", result=result, step="Done")
            except Exception as exc:
                logger.exception(f"Task {kind} failed")
                self._update(task_id, status="failed", error=str(exc) or type(exc).__name__, step="Failed")
            finally:
                self._update(task_id, finished_at=_now())

        threading.Thread(target=run, name=f"task-{kind}-{task_id}", daemon=True).start()
        return self.get(task_id)

    def run_inline(self, kind: str, job_id: Optional[int], target: Callable[[Task], Any]) -> dict:
        """Same bookkeeping, but in the calling thread (tests)."""
        task_id = uuid.uuid4().hex[:12]
        with self._lock:
            self._tasks[task_id] = {"id": task_id, "kind": kind, "job_id": job_id, "status": "running", "step": "",
                                    "steps": [], "result": None, "error": None, "started_at": _now(), "finished_at": None,
                                    "owner": tenancy.current_key()}
        task = Task(self, task_id)
        try:
            self._update(task_id, status="done", result=target(task), step="Done")
        except Exception as exc:
            self._update(task_id, status="failed", error=str(exc), step="Failed")
        self._update(task_id, finished_at=_now())
        return self.get(task_id)

    def get(self, task_id: str, only_mine: bool = False) -> Optional[dict]:
        """The task, or None. With only_mine, also None when it belongs to another user."""
        with self._lock:
            t = self._tasks.get(task_id)
            if t is None or (only_mine and t["owner"] != tenancy.current_key()):
                return None
            return copy.deepcopy(t)

    def for_job(self, job_id: int) -> list[dict]:
        owner = tenancy.current_key()
        with self._lock:
            return [copy.deepcopy(t) for t in self._tasks.values() if t["job_id"] == job_id and t["owner"] == owner]

    def _update(self, task_id: str, step: Optional[str] = None, **fields) -> None:
        with self._lock:
            t = self._tasks.get(task_id)
            if t is None:
                return
            if step is not None and step != t["step"]:
                t["step"] = step
                t["steps"].append({"at": _now(), "message": step})
                t["steps"] = t["steps"][-30:]
            t.update(fields)

    def _trim(self) -> None:
        if len(self._tasks) <= MAX_TASKS:
            return
        finished = sorted((t for t in self._tasks.values() if t["status"] != "running"), key=lambda t: t["started_at"])
        for t in finished[: len(self._tasks) - MAX_TASKS]:
            self._tasks.pop(t["id"], None)


tasks = TaskRegistry()
