"""
bonaid/db.py
PostgreSQL connectivity via SQLAlchemy 2.x. Provides a session factory used
by every agent/module that needs to persist state (positions, signals,
decisions, logs). Tables are defined in bonaid/models/.
"""
from contextlib import contextmanager
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

from bonaid.config import settings

Base = declarative_base()

# pool_pre_ping avoids "stale connection" errors after Postgres/network hiccups,
# which matters a lot for a system meant to run unattended for long periods.
engine = create_engine(settings.postgres_url, pool_pre_ping=True, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


@contextmanager
def get_session():
    """Usage: with get_session() as session: ..."""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def init_db():
    """Create all tables. Safe to call repeatedly (no-op if tables exist)."""
    import bonaid.models  # noqa: F401  (ensures models are registered on Base)
    Base.metadata.create_all(bind=engine)
