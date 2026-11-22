"""
Alembic environment.

Two ways in:
- From the app (db_migrations.upgrade_database): a live connection is passed in
  config.attributes["connection"], and logging is left alone so the app's loggers keep working.
- From the CLI (`alembic upgrade head` in backend/): the URL comes from DATABASE_URL
  (python-dotenv loads backend/.env, exactly like the app).
"""
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import create_engine, pool

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

config = context.config


def _run(connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=None,          # migrations are written by hand and are idempotent
        render_as_batch=connection.dialect.name == "sqlite",
        compare_type=False,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connection = config.attributes.get("connection")
    if connection is not None:
        _run(connection)
        return

    if config.config_file_name is not None:
        fileConfig(config.config_file_name, disable_existing_loggers=False)
    from database import DATABASE_URL  # loads backend/.env

    engine = create_engine(DATABASE_URL, poolclass=pool.NullPool)
    with engine.connect() as conn:
        _run(conn)
        conn.commit()


if context.is_offline_mode():
    raise SystemExit("Offline (--sql) mode is not supported: migrations inspect the live schema.")
run_migrations_online()
