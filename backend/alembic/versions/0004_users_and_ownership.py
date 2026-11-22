"""Accounts: a users table, an owner (user_id) on every per-user table, and per-user settings.

Existing rows keep user_id NULL. That is the single-user / legacy tenant: when accounts are enabled, the first
registered user takes over those rows (auth.claim_legacy_data), so nobody loses data.

app_settings used to have `key` as its primary key; with several users the same key exists once per user, so the
table is rebuilt with a surrogate id and a unique (user_id, key). Every step checks the live schema first, so it is
safe on an existing database and safe to re-run (SQLite and PostgreSQL).

Revision ID: 0004_users_and_ownership
Revises: 0003_tailored_resumes
Create Date: 2026-11-22
"""
from alembic import op
import sqlalchemy as sa

revision = "0004_users_and_ownership"
down_revision = "0003_tailored_resumes"
branch_labels = None
depends_on = None

OWNED_TABLES = ("jobs", "resumes", "job_decisions", "applications", "candidate_profiles", "tailored_resumes")


def _columns(inspector, table):
    return {c["name"] for c in inspector.get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "users" not in tables:
        op.create_table(
            "users",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("email", sa.String(), nullable=False),
            sa.Column("password_hash", sa.String(), nullable=False),
            sa.Column("name", sa.String()),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("token_version", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("created_at", sa.DateTime()),
            sa.Column("last_login_at", sa.DateTime()),
            sa.Column("telegram_chat_id", sa.String()),
            sa.Column("telegram_link_code", sa.String()),
            sa.Column("telegram_link_expires", sa.DateTime()),
        )
        op.create_index("ix_users_email", "users", ["email"], unique=True)
        op.create_index("ix_users_telegram_chat_id", "users", ["telegram_chat_id"])

    for table in OWNED_TABLES:
        if table in tables and "user_id" not in _columns(inspector, table):
            op.add_column(table, sa.Column("user_id", sa.Integer()))
            op.create_index(f"ix_{table}_user_id", table, ["user_id"])

    if "app_settings" in tables and "user_id" not in _columns(inspector, "app_settings"):
        # Rebuild: rename, drop the old index (its name is reused), create the new shape, copy, drop the old table.
        old_indexes = [i["name"] for i in inspector.get_indexes("app_settings")]
        op.rename_table("app_settings", "app_settings_old")
        for name in old_indexes:
            op.drop_index(name, table_name="app_settings_old")
        op.create_table(
            "app_settings",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("user_id", sa.Integer()),
            sa.Column("key", sa.String(), nullable=False),
            sa.Column("value", sa.Text(), nullable=False),
            sa.UniqueConstraint("user_id", "key", name="uq_app_settings_user_key"),
        )
        op.create_index("ix_app_settings_user_id", "app_settings", ["user_id"])
        op.create_index("ix_app_settings_key", "app_settings", ["key"])
        op.execute(sa.text('INSERT INTO app_settings ("key", value) SELECT "key", value FROM app_settings_old'))
        op.drop_table("app_settings_old")


def downgrade() -> None:
    # Per-user data cannot be merged back into single-user tables without losing information, so the downgrade only
    # removes the structure and keeps the rows of the first owner (user_id NULL) and of user 1.
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "app_settings" in tables and "user_id" in _columns(inspector, "app_settings"):
        new_indexes = [i["name"] for i in inspector.get_indexes("app_settings")]
        op.rename_table("app_settings", "app_settings_new")
        for name in new_indexes:
            op.drop_index(name, table_name="app_settings_new")
        op.create_table(
            "app_settings",
            sa.Column("key", sa.String(), primary_key=True),
            sa.Column("value", sa.Text(), nullable=False),
        )
        op.create_index("ix_app_settings_key", "app_settings", ["key"])
        op.execute(sa.text('INSERT INTO app_settings ("key", value) SELECT "key", value FROM app_settings_new '
                           "WHERE user_id IS NULL OR user_id = (SELECT MIN(id) FROM users)"))
        op.drop_table("app_settings_new")
    for table in OWNED_TABLES:
        if table in tables and "user_id" in _columns(inspector, table):
            op.drop_index(f"ix_{table}_user_id", table_name=table)
            with op.batch_alter_table(table) as batch:
                batch.drop_column("user_id")
    if "users" in tables:
        op.drop_index("ix_users_telegram_chat_id", table_name="users")
        op.drop_index("ix_users_email", table_name="users")
        op.drop_table("users")
