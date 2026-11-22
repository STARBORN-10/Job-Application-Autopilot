"""
Offline tests for the Alembic migrations:
- a fresh, empty database migrates to the latest schema,
- a V1 database (tables created by V1's create_all, with rows) upgrades without losing data,
- migrations are idempotent and the migrated schema matches models.py,
- (if present) a copy of a real pre-V2 backup database upgrades cleanly.
"""
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from testing_utils import Checker, use_temp_database

use_temp_database()

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker

import db_migrations
import models

V1_DDL = [
    """CREATE TABLE jobs (id INTEGER NOT NULL PRIMARY KEY, title VARCHAR, company VARCHAR, url VARCHAR,
       location VARCHAR, description TEXT, job_type VARCHAR, experience VARCHAR, source VARCHAR,
       posted_date DATETIME, date_found DATETIME, score FLOAT, match_reason TEXT, cover_letter TEXT, status VARCHAR)""",
    "CREATE INDEX ix_jobs_id ON jobs (id)",
    "CREATE INDEX ix_jobs_title ON jobs (title)",
    "CREATE INDEX ix_jobs_company ON jobs (company)",
    """CREATE TABLE resumes (id INTEGER NOT NULL PRIMARY KEY, filename VARCHAR NOT NULL, target_role VARCHAR NOT NULL,
       extracted_text TEXT, file_path VARCHAR NOT NULL, file_size INTEGER, is_active BOOLEAN,
       uploaded_at DATETIME, updated_at DATETIME)""",
    "CREATE INDEX ix_resumes_id ON resumes (id)",
    "CREATE INDEX ix_resumes_target_role ON resumes (target_role)",
    "CREATE TABLE app_settings (key VARCHAR NOT NULL PRIMARY KEY, value TEXT NOT NULL)",
    "CREATE INDEX ix_app_settings_key ON app_settings (key)",
]

HEAD = "0004_users_and_ownership"
BACKUP = Path(os.getenv("V1_BACKUP_DB", r"C:\WINDOWS\TEMP\v2_samples\jobs.db.pre-v2.bak"))


def _columns(engine, table):
    return {c["name"] for c in inspect(engine).get_columns(table)}


def run():
    check = Checker("RUNNING OFFLINE MIGRATION TESTS")
    tmp = Path(tempfile.mkdtemp())

    check.section("1. Fresh database")
    fresh = create_engine(f"sqlite:///{tmp / 'fresh.db'}")
    db_migrations.upgrade_database(fresh)
    tables = set(inspect(fresh).get_table_names())
    check(set(models.Base.metadata.tables) <= tables, "All model tables exist after upgrade head")
    check(db_migrations.current_revision(fresh) == HEAD, f"Revision is head ({HEAD})")
    for name, table in models.Base.metadata.tables.items():
        check(_columns(fresh, name) == {c.name for c in table.columns}, f"Migrated '{name}' columns match models.py")

    check.section("2. Existing V1 database (create_all era) with data")
    v1 = create_engine(f"sqlite:///{tmp / 'v1.db'}")
    with v1.begin() as conn:
        for ddl in V1_DDL:
            conn.exec_driver_sql(ddl)
        conn.exec_driver_sql("INSERT INTO jobs (title, company, url, score, status) VALUES "
                             "('ML Engineer', 'Acme', 'https://x/1', 8.5, 'To Apply'), "
                             "('Data Analyst', 'Beta', 'https://x/2', 7.1, 'Applied')")
        conn.exec_driver_sql("INSERT INTO resumes (filename, target_role, extracted_text, file_path, is_active) "
                             "VALUES ('r.pdf', 'AI/ML Engineer', 'Python', '/tmp/r.pdf', 1)")
        conn.exec_driver_sql("INSERT INTO app_settings (key, value) VALUES ('general_settings', '{}')")
    db_migrations.upgrade_database(v1)
    with v1.connect() as conn:
        rows = conn.execute(text("SELECT title, score, status, approval_status FROM jobs ORDER BY id")).fetchall()
        resumes = conn.execute(text("SELECT count(*) FROM resumes")).scalar()
        settings = conn.execute(text("SELECT value FROM app_settings WHERE key='general_settings'")).scalar()
    check(len(rows) == 2 and rows[0][0] == "ML Engineer" and rows[1][2] == "Applied", "Existing job rows survive")
    check(rows[0][1] == 8.5, "Existing scores survive")
    check(all(r[3] == "pending" for r in rows), "New approval_status column is 'pending' for old rows")
    check(resumes == 1 and settings == "{}", "Resumes and settings survive")
    check({"external_id", "canonical_url", "source_names", "score_breakdown", "description_quality",
           "approval_status", "last_seen"} <= _columns(v1, "jobs"), "All new job columns were added")
    check({"source_health", "job_decisions", "applications", "candidate_profiles", "api_usage"}
          <= set(inspect(v1).get_table_names()), "All new tables were created")

    check.section("3. Idempotency")
    db_migrations.upgrade_database(v1)
    db_migrations.upgrade_database(fresh)
    with v1.connect() as conn:
        check(conn.execute(text("SELECT count(*) FROM jobs")).scalar() == 2, "Re-running upgrade changes nothing")

    check.section("4. ORM works on the migrated V1 database")
    from sqlalchemy.orm import sessionmaker
    import crud, schemas
    session = sessionmaker(bind=v1)()
    job = crud.create_job(session, schemas.JobCreate(title="New", company="Gamma", url="https://x/3?utm_source=a",
                                                     source="adzuna", score_breakdown={"total": 7.0}))
    check(job.canonical_url == "https://x/3" and job.approval_status == "pending", "New V2 row saved with V2 fields")
    session.close()

    check.section("5. Copy of a real pre-V2 database (optional)")
    if BACKUP.exists():
        copy = tmp / "backup_copy.db"
        shutil.copyfile(BACKUP, copy)
        eng = create_engine(f"sqlite:///{copy}")
        with eng.connect() as conn:
            before = {t: conn.execute(text(f"SELECT count(*) FROM {t}")).scalar() for t in ("jobs", "resumes", "app_settings")}
        db_migrations.upgrade_database(eng)
        with eng.connect() as conn:
            after = {t: conn.execute(text(f"SELECT count(*) FROM {t}")).scalar() for t in ("jobs", "resumes", "app_settings")}
        check(before == after, f"Row counts unchanged on the backup copy ({after})")
        eng.dispose()
    else:
        print("  (skipped: no backup database found)")

    check.section("6. Existing V2 database (0002) with data -> tailored_resumes added, rows kept")
    from alembic import command
    v2 = create_engine(f"sqlite:///{tmp / 'v2.db'}")
    cfg = db_migrations._config()
    with v2.begin() as conn:
        cfg.attributes["connection"] = conn
        command.upgrade(cfg, "0002_v2_schema")
    with v2.begin() as conn:
        conn.exec_driver_sql("INSERT INTO jobs (title, company, url, score, status, approval_status, source_names) VALUES "
                             "('ML Engineer', 'Acme', 'https://x/1', 8.2, 'To Apply', 'approved', '[\"adzuna\", \"jooble\"]')")
        conn.exec_driver_sql("INSERT INTO applications (job_id, method, status, dry_run) VALUES (1, 'email', 'dry_run', 1)")
    check(db_migrations.current_revision(v2) == "0002_v2_schema" and "tailored_resumes" not in inspect(v2).get_table_names(),
          "Starting point is a V2 database without tailored_resumes")
    db_migrations.upgrade_database(v2)
    with v2.connect() as conn:
        job_row = conn.execute(text("SELECT title, score, approval_status, source_names FROM jobs")).fetchone()
        apps = conn.execute(text("SELECT count(*) FROM applications")).scalar()
    check(db_migrations.current_revision(v2) == HEAD, "V2 database upgraded to head")
    check(job_row[0] == "ML Engineer" and job_row[1] == 8.2 and job_row[2] == "approved" and "jooble" in job_row[3],
          "Existing V2 job (score, decision, merged sources) kept")
    check(apps == 1, "Existing application rows kept")
    check(_columns(v2, "tailored_resumes") == {c.name for c in models.TailoredResume.__table__.columns},
          "tailored_resumes columns match models.py")
    db_migrations.upgrade_database(v2)
    check(db_migrations.current_revision(v2) == HEAD, "Re-running the migrations is a no-op")
    session = sessionmaker(bind=v2)()
    session.add(models.TailoredResume(job_id=1, resume_id=1, resume_hash="h", status="not_needed", score_before=9.1))
    session.commit()
    check(session.query(models.TailoredResume).count() == 1, "ORM writes to the new table")
    session.close()
    v2.dispose()

    check.section("7. Copy of a real V2 database (optional, V2_DB_COPY)")
    real_copy = os.getenv("V2_DB_COPY")
    if real_copy and Path(real_copy).exists():
        copy = tmp / "real_v2_copy.db"
        shutil.copyfile(real_copy, copy)
        eng = create_engine(f"sqlite:///{copy}")
        tables = ("jobs", "resumes", "app_settings", "applications", "job_decisions")
        with eng.connect() as conn:
            before = {t: conn.execute(text(f"SELECT count(*) FROM {t}")).scalar() for t in tables}
        db_migrations.upgrade_database(eng)
        with eng.connect() as conn:
            after = {t: conn.execute(text(f"SELECT count(*) FROM {t}")).scalar() for t in tables}
        check(before == after and db_migrations.current_revision(eng) == HEAD,
              f"Real V2 copy upgraded to head with row counts unchanged ({after})")
        eng.dispose()
    else:
        print("  (skipped: set V2_DB_COPY to a COPY of a V2 database to run this check)")

    check.section("8. Existing single-user database (0003) with data -> accounts added, nothing lost")
    v3 = create_engine(f"sqlite:///{tmp / 'v3.db'}")
    with v3.begin() as conn:
        cfg.attributes["connection"] = conn
        command.upgrade(cfg, "0003_tailored_resumes")
    with v3.begin() as conn:
        conn.exec_driver_sql("INSERT INTO jobs (title, company, url, score) VALUES ('ML Engineer', 'Acme', 'https://x/1', 8.2)")
        conn.exec_driver_sql("INSERT INTO resumes (filename, target_role, extracted_text, file_path, is_active) "
                             "VALUES ('cv.pdf', 'AI/ML Engineer', 'Python', 'x', 1)")
        conn.exec_driver_sql("INSERT INTO app_settings (key, value) VALUES ('general_settings', '{\"min_match_score\": 7}')")
        conn.exec_driver_sql("INSERT INTO app_settings (key, value) VALUES ('sources', '{}')")
        conn.exec_driver_sql("INSERT INTO applications (job_id, method, status, dry_run) VALUES (1, 'assisted', 'ready_to_submit', 1)")
    check("users" not in inspect(v3).get_table_names() and "user_id" not in _columns(v3, "jobs"),
          "Starting point has no users table and no owner columns")
    db_migrations.upgrade_database(v3)
    check(db_migrations.current_revision(v3) == HEAD, "Single-user database upgraded to head")
    for name in ("users", "jobs", "resumes", "app_settings", "job_decisions", "applications", "candidate_profiles", "tailored_resumes"):
        check(_columns(v3, name) == {c.name for c in models.Base.metadata.tables[name].columns},
              f"'{name}' columns match models.py after the accounts migration")
    with v3.connect() as conn:
        job = conn.execute(text("SELECT title, score, user_id FROM jobs")).fetchone()
        settings = conn.execute(text("SELECT key, value, user_id FROM app_settings ORDER BY key")).fetchall()
        resume = conn.execute(text("SELECT filename, user_id FROM resumes")).fetchone()
        app_row = conn.execute(text("SELECT status, user_id FROM applications")).fetchone()
    check(job[0] == "ML Engineer" and job[1] == 8.2 and job[2] is None, "Existing job kept, owner NULL (claimed by the first account)")
    check(resume == ("cv.pdf", None) and app_row == ("ready_to_submit", None), "Resume and application rows kept")
    check([(k, u) for k, _, u in settings] == [("general_settings", None), ("sources", None)]
          and "min_match_score" in settings[0][1], "Settings copied into the per-user table, values intact")
    with v3.begin() as conn:
        conn.exec_driver_sql("INSERT INTO app_settings (user_id, key, value) VALUES (1, 'general_settings', '{}')")
        conn.exec_driver_sql("INSERT INTO app_settings (user_id, key, value) VALUES (2, 'general_settings', '{}')")
    try:
        with v3.begin() as conn:
            conn.exec_driver_sql("INSERT INTO app_settings (user_id, key, value) VALUES (1, 'general_settings', 'dup')")
        dup_blocked = False
    except Exception:
        dup_blocked = True
    check(dup_blocked, "The same setting twice for one user is rejected; the same key for two users is allowed")
    db_migrations.upgrade_database(v3)
    with v3.connect() as conn:
        check(conn.execute(text("SELECT count(*) FROM app_settings")).scalar() == 4, "Re-running the accounts migration changes nothing")
    session = sessionmaker(bind=v3)()
    session.add(models.User(email="a@example.com", password_hash="x"))
    session.commit()
    check(session.query(models.User).count() == 1, "ORM writes to the users table")
    session.close()
    v3.dispose()

    for e in (fresh, v1):
        e.dispose()
    shutil.rmtree(tmp, ignore_errors=True)
    check.done("MIGRATION")


if __name__ == "__main__":
    run()
