from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import os
from dotenv import load_dotenv
from fastapi import Request

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./jobs.db")

if DATABASE_URL.startswith("sqlite"):
    engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
else:
    # Fail fast (instead of hanging) when a hosted database is unreachable or paused,
    # and drop dead pooled connections automatically.
    engine = create_engine(DATABASE_URL, connect_args={"connect_timeout": 10}, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

def get_db(request: Request = None):
    """
    One database session per request. When the sign-in check (auth.authenticate) identified the user, the
    session is scoped to that user: every query on user data is filtered to them (see tenancy.py).
    """
    db = SessionLocal()
    try:
        state = getattr(request, "state", None)
        if state is not None and getattr(state, "tenant_set", False):
            import tenancy
            tenancy.set_tenant(db, state.tenant)
        yield db
    finally:
        db.close()
