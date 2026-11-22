"""
Approve / skip decisions (from Telegram or the dashboard).

Each decision sets jobs.approval_status and is stored in job_decisions together with a snapshot of
the score and its breakdown: that history is the training data for weight tuning (V2.4).
Repeating the current decision is a no-op, so double taps do not create duplicate training rows.
"""
import datetime
from dataclasses import dataclass
from typing import Optional

import models

DECISIONS = ("approved", "skipped")


@dataclass
class DecisionOutcome:
    job: models.Job
    decision: str
    changed: bool
    record: Optional[models.JobDecision]


def record_decision(db, job: models.Job, decision: str, channel: str) -> DecisionOutcome:
    if decision not in DECISIONS:
        raise ValueError(f"decision must be one of {DECISIONS}")
    if (job.approval_status or "pending") == decision:
        return DecisionOutcome(job=job, decision=decision, changed=False, record=None)
    record = models.JobDecision(
        job_id=job.id,
        decision=decision,
        decided_at=datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None),
        channel=channel,
        score_snapshot=job.score,
        breakdown_snapshot=job.score_breakdown,
    )
    job.approval_status = decision
    db.add(record)
    db.commit()
    db.refresh(job)
    return DecisionOutcome(job=job, decision=decision, changed=True, record=record)


def count_decisions(db) -> int:
    return db.query(models.JobDecision).count()
