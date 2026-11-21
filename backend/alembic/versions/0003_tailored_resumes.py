"""Tailored resumes: one row per (job, resume version) with the structured rewrite and scores.

Additive only (a new table), and it checks the live schema first, so it is safe on an existing V2
database and safe to re-run.

Revision ID: 0003_tailored_resumes
Revises: 0002_v2_schema
Create Date: 2026-11-22
"""
from alembic import op
import sqlalchemy as sa

revision = "0003_tailored_resumes"
down_revision = "0002_v2_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "tailored_resumes" in set(inspector.get_table_names()):
        return
    op.create_table(
        "tailored_resumes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("job_id", sa.Integer(), sa.ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("resume_id", sa.Integer(), nullable=False),
        sa.Column("resume_hash", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("structured_json", sa.Text()),
        sa.Column("tailored_text", sa.Text()),
        sa.Column("pdf_path", sa.String()),
        sa.Column("docx_path", sa.String()),
        sa.Column("score_before", sa.Float()),
        sa.Column("score_after", sa.Float()),
        sa.Column("breakdown_after", sa.Text()),
        sa.Column("metrics", sa.Text()),
        sa.Column("removed_unverified", sa.Text()),
        sa.Column("gaps", sa.Text()),
        sa.Column("provider", sa.String()),
        sa.Column("error", sa.Text()),
        sa.Column("created_at", sa.DateTime()),
    )
    op.create_index("ix_tailored_resumes_job_id", "tailored_resumes", ["job_id"])
    op.create_index("ix_tailored_resumes_resume_id", "tailored_resumes", ["resume_id"])


def downgrade() -> None:
    op.drop_index("ix_tailored_resumes_resume_id", table_name="tailored_resumes")
    op.drop_index("ix_tailored_resumes_job_id", table_name="tailored_resumes")
    op.drop_table("tailored_resumes")
