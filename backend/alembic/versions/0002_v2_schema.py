"""V2 schema: new job columns and the source_health, job_decisions, applications,
candidate_profiles and api_usage tables.

Every step checks the live schema first, so the migration is safe to re-run and works on databases
where some of these objects already exist. Columns are added with batch_alter_table so SQLite works.

Revision ID: 0002_v2_schema
Revises: 0001_v1_baseline
Create Date: 2026-11-21
"""
from alembic import op
import sqlalchemy as sa

revision = "0002_v2_schema"
down_revision = "0001_v1_baseline"
branch_labels = None
depends_on = None

NEW_JOB_COLUMNS = [
    sa.Column("external_id", sa.String()),
    sa.Column("canonical_url", sa.String()),
    sa.Column("source_names", sa.Text()),
    sa.Column("score_breakdown", sa.Text()),
    sa.Column("description_quality", sa.String()),
    sa.Column("approval_status", sa.String(), server_default="pending"),
    sa.Column("last_seen", sa.DateTime()),
]


def _inspector():
    return sa.inspect(op.get_bind())


def upgrade() -> None:
    existing_cols = {c["name"] for c in _inspector().get_columns("jobs")}
    missing = [col for col in NEW_JOB_COLUMNS if col.name not in existing_cols]
    if missing:
        with op.batch_alter_table("jobs") as batch:
            for col in missing:
                batch.add_column(col.copy())

    if "ix_jobs_canonical_url" not in {ix["name"] for ix in _inspector().get_indexes("jobs")}:
        op.create_index("ix_jobs_canonical_url", "jobs", ["canonical_url"])

    tables = set(_inspector().get_table_names())

    if "source_health" not in tables:
        op.create_table(
            "source_health",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("source_name", sa.String(), nullable=False, unique=True),
            sa.Column("last_success_at", sa.DateTime()),
            sa.Column("last_error_at", sa.DateTime()),
            sa.Column("last_error", sa.Text()),
            sa.Column("last_count", sa.Integer()),
            sa.Column("total_runs", sa.Integer()),
        )

    if "job_decisions" not in tables:
        op.create_table(
            "job_decisions",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("job_id", sa.Integer(), sa.ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False),
            sa.Column("decision", sa.String(), nullable=False),
            sa.Column("decided_at", sa.DateTime()),
            sa.Column("channel", sa.String()),
            sa.Column("score_snapshot", sa.Float()),
            sa.Column("breakdown_snapshot", sa.Text()),
        )
        op.create_index("ix_job_decisions_job_id", "job_decisions", ["job_id"])

    if "applications" not in tables:
        op.create_table(
            "applications",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("job_id", sa.Integer(), sa.ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False),
            sa.Column("method", sa.String(), nullable=False),
            sa.Column("status", sa.String(), nullable=False),
            sa.Column("dry_run", sa.Boolean()),
            sa.Column("payload_summary", sa.Text()),
            sa.Column("error", sa.Text()),
            sa.Column("created_at", sa.DateTime()),
            sa.Column("updated_at", sa.DateTime()),
        )
        op.create_index("ix_applications_job_id", "applications", ["job_id"])

    if "candidate_profiles" not in tables:
        op.create_table(
            "candidate_profiles",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("resume_id", sa.Integer(), nullable=False),
            sa.Column("resume_hash", sa.String(), nullable=False),
            sa.Column("profile_json", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime()),
        )
        op.create_index("ix_candidate_profiles_resume_id", "candidate_profiles", ["resume_id"])

    if "api_usage" not in tables:
        op.create_table(
            "api_usage",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("provider", sa.String(), nullable=False),
            sa.Column("period", sa.String(), nullable=False),
            sa.Column("count", sa.Integer(), nullable=False),
            sa.UniqueConstraint("provider", "period", name="uq_api_usage_provider_period"),
        )


def downgrade() -> None:
    for table in ("api_usage", "candidate_profiles", "applications", "job_decisions", "source_health"):
        op.drop_table(table)
    op.drop_index("ix_jobs_canonical_url", table_name="jobs")
    with op.batch_alter_table("jobs") as batch:
        for col in reversed(NEW_JOB_COLUMNS):
            batch.drop_column(col.name)
