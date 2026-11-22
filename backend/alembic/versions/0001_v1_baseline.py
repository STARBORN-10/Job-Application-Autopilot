"""V1 baseline: the three tables V1 created with Base.metadata.create_all.

Safe on both a fresh, empty database and an existing V1 database (where create_all already made
these tables): each table and index is created only if it is missing, so existing rows are untouched.

Revision ID: 0001_v1_baseline
Revises:
Create Date: 2026-11-21
"""
from alembic import op
import sqlalchemy as sa

revision = "0001_v1_baseline"
down_revision = None
branch_labels = None
depends_on = None


def _existing_tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _create_index_if_missing(name: str, table: str, columns: list[str], unique: bool = False) -> None:
    existing = {ix["name"] for ix in sa.inspect(op.get_bind()).get_indexes(table)}
    if name not in existing:
        op.create_index(name, table, columns, unique=unique)


def upgrade() -> None:
    tables = _existing_tables()

    if "jobs" not in tables:
        op.create_table(
            "jobs",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("title", sa.String()),
            sa.Column("company", sa.String()),
            sa.Column("url", sa.String()),
            sa.Column("location", sa.String()),
            sa.Column("description", sa.Text()),
            sa.Column("job_type", sa.String()),
            sa.Column("experience", sa.String()),
            sa.Column("source", sa.String()),
            sa.Column("posted_date", sa.DateTime()),
            sa.Column("date_found", sa.DateTime()),
            sa.Column("score", sa.Float()),
            sa.Column("match_reason", sa.Text()),
            sa.Column("cover_letter", sa.Text()),
            sa.Column("status", sa.String()),
        )
    _create_index_if_missing("ix_jobs_id", "jobs", ["id"])
    _create_index_if_missing("ix_jobs_title", "jobs", ["title"])
    _create_index_if_missing("ix_jobs_company", "jobs", ["company"])

    if "resumes" not in tables:
        op.create_table(
            "resumes",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("filename", sa.String(), nullable=False),
            sa.Column("target_role", sa.String(), nullable=False),
            sa.Column("extracted_text", sa.Text()),
            sa.Column("file_path", sa.String(), nullable=False),
            sa.Column("file_size", sa.Integer()),
            sa.Column("is_active", sa.Boolean()),
            sa.Column("uploaded_at", sa.DateTime()),
            sa.Column("updated_at", sa.DateTime()),
        )
    _create_index_if_missing("ix_resumes_id", "resumes", ["id"])
    _create_index_if_missing("ix_resumes_target_role", "resumes", ["target_role"])

    if "app_settings" not in tables:
        op.create_table(
            "app_settings",
            sa.Column("key", sa.String(), primary_key=True),
            sa.Column("value", sa.Text(), nullable=False),
        )
    _create_index_if_missing("ix_app_settings_key", "app_settings", ["key"])


def downgrade() -> None:
    # Dropping the V1 tables would delete user data; refuse instead.
    raise RuntimeError("Downgrading below the V1 baseline is not supported.")
