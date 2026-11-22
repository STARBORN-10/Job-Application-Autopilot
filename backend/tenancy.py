"""
Per-user data isolation.

Every row of the "tenant" models (Job, Resume, AppSettings, JobDecision, Application, CandidateProfile,
TailoredResume) belongs to one user (user_id). Instead of remembering to filter in each of the ~60 endpoints,
the filter is applied centrally:

* A database session carries its tenant in `session.info`. Every ORM query on a tenant model (select, update,
  delete, count, get) gets `WHERE user_id = <tenant>` added automatically (`do_orm_execute`).
* New rows are stamped with the session's tenant (`before_flush`), and a row can never be saved for another
  tenant than the session's.
* tenant `None` is the single-user / legacy tenant: rows with `user_id IS NULL`. This is what local mode
  (AUTH_ENABLED=false), the existing tests and pre-account data use. When accounts are on, the first
  registered user takes over those legacy rows (see auth.claim_legacy_data).
* With accounts on, a session whose tenant was never set refuses to touch tenant data (TenantError), so a
  forgotten scope fails loudly instead of leaking. Code that really needs every user (the scheduler, account
  deletion) opts in with `system_session()`.

The same user id also keys the in-memory per-user state (run lock, progress, cooldown, background tasks) through
a context variable: see `tenant_scope()`.
"""
import contextlib
import contextvars
import os
import threading
from typing import Any, Callable, Optional

from sqlalchemy import event
from sqlalchemy.orm import Session, with_loader_criteria

import models

TENANT_MODELS = (models.Job, models.Resume, models.AppSettings, models.JobDecision, models.Application,
                 models.CandidateProfile, models.TailoredResume)

_ALL = object()       # session opted out of scoping (system work)
_UNSET = object()


class TenantError(RuntimeError):
    """A session touched tenant data without a user context while accounts are enabled."""


def auth_enabled() -> bool:
    """Accounts are on unless AUTH_ENABLED is explicitly false (single-user local mode)."""
    return (os.getenv("AUTH_ENABLED") or "true").strip().lower() not in ("0", "false", "no", "off")


# ---------------------------------------------------------------------------
# Session tenant
# ---------------------------------------------------------------------------
def set_tenant(db: Session, user_id: Optional[int]) -> Session:
    db.info["tenant"] = user_id
    db.info.pop("tenant_all", None)
    return db


def system_session(db: Session) -> Session:
    """Opt this session out of per-user filtering (account management, scheduler). Use sparingly."""
    db.info["tenant_all"] = True
    return db


def get_tenant(db: Session) -> Optional[int]:
    t = _resolve(db)
    if t is _ALL:
        raise TenantError("This session is not scoped to one user.")
    return t


def tenant_of(db: Session) -> Optional[int]:
    """The user id of a scoped session, or None (single-user mode, or an unscoped system session)."""
    t = _resolve(db, strict=False)
    return None if t is _ALL else t


def _resolve(db: Session, strict: bool = True) -> Any:
    info = db.info
    if info.get("tenant_all"):
        return _ALL
    if "tenant" in info:
        return info["tenant"]
    if strict and auth_enabled():
        raise TenantError("No user context for this database session (accounts are enabled).")
    return None


def scoped_factory(factory: Callable[[], Session], user_id: Optional[int]) -> Callable[[], Session]:
    """A session factory whose sessions are already scoped to `user_id` (for background threads)."""
    def make() -> Session:
        return set_tenant(factory(), user_id)
    return make


_NO_ONE = -1   # an id no user has: a filter that matches nothing


@event.listens_for(Session, "do_orm_execute")
def _scope_queries(state) -> None:
    if state.is_column_load or state.is_relationship_load:
        return
    info = state.session.info
    if info.get("tenant_all"):
        return
    if "tenant" in info:
        tenant = info["tenant"]
    elif auth_enabled():
        # Accounts are on but nobody told this session whose data it may see.
        if any(m.class_ in TENANT_MODELS for m in state.all_mappers):
            raise TenantError("No user context for this database session (accounts are enabled).")
        # A wrapped statement (e.g. Query.count() selects FROM a subquery) hides its tables: fail closed.
        tenant = _NO_ONE
    else:
        tenant = None
    # The filter is ALWAYS added (it only affects per-user tables): the statement may be wrapped, so we cannot rely
    # on spotting a per-user table in it. Plain SQL expressions, not lambdas: compiled statements are cached.
    uid = None if tenant is None else int(tenant)
    state.statement = state.statement.options(*[
        with_loader_criteria(m, m.user_id.is_(None) if uid is None else m.user_id == uid, include_aliases=True)
        for m in TENANT_MODELS])


@event.listens_for(Session, "before_flush")
def _stamp_rows(session, flush_context, instances) -> None:
    owned = [obj for obj in session.new if isinstance(obj, TENANT_MODELS)]
    if not owned:
        return
    tenant = _resolve(session)
    if tenant is _ALL:
        return
    for obj in owned:
        if obj.user_id is None:
            obj.user_id = tenant
        elif obj.user_id != tenant:
            raise TenantError("Refusing to save a row that belongs to another user.")


# ---------------------------------------------------------------------------
# Current user for in-memory per-user state (context variable)
# ---------------------------------------------------------------------------
_current: contextvars.ContextVar = contextvars.ContextVar("current_user_id", default=_UNSET)


def set_current_user(user_id: Optional[int]):
    return _current.set(user_id)


def current_user_id() -> Optional[int]:
    v = _current.get()
    return None if v is _UNSET else v


def current_key() -> str:
    """Key of the current user for per-user dictionaries ("local" in single-user mode)."""
    uid = current_user_id()
    return "local" if uid is None else f"u{uid}"


@contextlib.contextmanager
def tenant_scope(user_id: Optional[int]):
    token = _current.set(user_id)
    try:
        yield
    finally:
        _current.reset(token)


class TenantLock:
    """threading.Lock look-alike with one independent lock per user (acquire / release / locked)."""

    def __init__(self):
        self._guard = threading.Lock()
        self._locks: dict[str, threading.Lock] = {}

    def _lock(self) -> threading.Lock:
        key = current_key()
        with self._guard:
            return self._locks.setdefault(key, threading.Lock())

    def acquire(self, blocking: bool = True, timeout: float = -1) -> bool:
        return self._lock().acquire(blocking, timeout)

    def release(self) -> None:
        self._lock().release()

    def locked(self) -> bool:
        return self._lock().locked()


class TenantDict:
    """A dict with one independent copy per user, exposing the small dict API the code uses."""

    def __init__(self, factory: Callable[[], dict]):
        self._factory = factory
        self._guard = threading.Lock()
        self._data: dict[str, dict] = {}

    def _d(self) -> dict:
        key = current_key()
        with self._guard:
            if key not in self._data:
                self._data[key] = self._factory()
            return self._data[key]

    def __getitem__(self, k):
        return self._d()[k]

    def __setitem__(self, k, v):
        self._d()[k] = v

    def get(self, k, default=None):
        return self._d().get(k, default)

    def update(self, *args, **kwargs):
        self._d().update(*args, **kwargs)

    def keys(self):
        return self._d().keys()

    def items(self):
        return self._d().items()

    def __iter__(self):
        return iter(self._d())

    def copy(self) -> dict:
        return dict(self._d())
