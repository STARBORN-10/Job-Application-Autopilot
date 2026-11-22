"""Monthly request counters per external provider (api_usage table)."""
import datetime

from sqlalchemy.orm import Session

import models


def current_period(now: datetime.datetime | None = None) -> str:
    now = now or datetime.datetime.now(datetime.timezone.utc)
    return now.strftime("%Y-%m")


def get_count(db: Session, provider: str, period: str | None = None) -> int:
    row = (
        db.query(models.ApiUsage)
        .filter(models.ApiUsage.provider == provider, models.ApiUsage.period == (period or current_period()))
        .first()
    )
    return int(row.count or 0) if row else 0


def increment(db: Session, provider: str, amount: int = 1) -> int:
    period = current_period()
    row = (
        db.query(models.ApiUsage)
        .filter(models.ApiUsage.provider == provider, models.ApiUsage.period == period)
        .first()
    )
    if row is None:
        row = models.ApiUsage(provider=provider, period=period, count=0)
        db.add(row)
    row.count = int(row.count or 0) + amount
    db.commit()
    return row.count


def usage_for_period(db: Session, period: str | None = None) -> dict[str, int]:
    rows = db.query(models.ApiUsage).filter(models.ApiUsage.period == (period or current_period())).all()
    return {row.provider: int(row.count or 0) for row in rows}
