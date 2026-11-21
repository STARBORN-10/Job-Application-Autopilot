"""The list of job sources, and their per-source settings (stored in app_settings)."""
from typing import Optional

from sqlalchemy.orm import Session

import crud, models
from services.sources.adzuna import AdzunaSource
from services.sources.ats import DEFAULT_ATS_COMPANIES, AtsBoardsSource
from services.sources.base import JobSource
from services.sources.internshala import InternshalaSource
from services.sources.jobspy_source import JobSpySource
from services.sources.jooble import JoobleSource
from services.sources.jsearch import JSearchSource

SOURCES_SETTINGS_KEY = "sources"          # {"<name>": {"enabled": bool}}
ATS_COMPANIES_KEY = "ats_companies"       # [{"provider", "token", "name"}]

ALL_SOURCES: list[JobSource] = [
    JSearchSource(),
    AdzunaSource(),
    JoobleSource(),
    AtsBoardsSource(),
    InternshalaSource(),
    JobSpySource(),
]


def get_source(name: str) -> Optional[JobSource]:
    return next((s for s in ALL_SOURCES if s.name == name), None)


def enabled_map(db: Session) -> dict[str, bool]:
    stored = crud.get_json_setting(db, SOURCES_SETTINGS_KEY, {}) or {}
    if not isinstance(stored, dict):
        stored = {}
    result = {}
    for source in ALL_SOURCES:
        entry = stored.get(source.name)
        result[source.name] = bool(entry.get("enabled")) if isinstance(entry, dict) and "enabled" in entry \
            else source.default_enabled
    return result


def set_enabled(db: Session, name: str, enabled: bool) -> None:
    stored = crud.get_json_setting(db, SOURCES_SETTINGS_KEY, {}) or {}
    if not isinstance(stored, dict):
        stored = {}
    stored[name] = {"enabled": bool(enabled)}
    crud.set_json_setting(db, SOURCES_SETTINGS_KEY, stored)


def get_ats_companies(db: Session) -> list[dict]:
    stored = crud.get_json_setting(db, ATS_COMPANIES_KEY, None)
    return stored if isinstance(stored, list) else list(DEFAULT_ATS_COMPANIES)


def set_ats_companies(db: Session, companies: list[dict]) -> None:
    crud.set_json_setting(db, ATS_COMPANIES_KEY, companies)


def health_rows(db: Session) -> dict[str, models.SourceHealth]:
    try:
        return {row.source_name: row for row in db.query(models.SourceHealth).all()}
    except Exception:
        return {}


def describe_sources(db: Session) -> list[dict]:
    """Everything the Settings page shows per source."""
    enabled = enabled_map(db)
    health = health_rows(db)
    out = []
    for source in ALL_SOURCES:
        row = health.get(source.name)
        out.append({
            "name": source.name,
            "label": source.label,
            "description": source.description,
            "enabled": enabled[source.name],
            "configured": source.is_configured(),
            "missing_config": source.missing_config(),
            "experimental": source.experimental,
            "default_enabled": source.default_enabled,
            "description_quality": source.description_quality,
            "monthly_budget": source.monthly_budget(),
            "health": {
                "last_success_at": row.last_success_at.isoformat() if row and row.last_success_at else None,
                "last_error_at": row.last_error_at.isoformat() if row and row.last_error_at else None,
                "last_error": row.last_error if row else None,
                "last_count": row.last_count if row else None,
                "total_runs": row.total_runs if row else 0,
            },
        })
    return out
