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
    """Create all tables, then add any columns that exist on the models but
    not yet in the real database (a lightweight substitute for Alembic,
    intentional for now per the Phase 1 decision to defer real migrations
    until the schema stabilizes - see README). SQLAlchemy's create_all()
    only creates missing TABLES, it never alters existing ones, so without
    this step every time a model gains a new column (like risk_assessment,
    or the next agent's own columns), it would silently never reach a
    database that already has that table - exactly what happened here.
    Safe to call repeatedly."""
    import bonaid.models  # noqa: F401  (ensures models are registered on Base)
    from sqlalchemy import inspect, text

    Base.metadata.create_all(bind=engine)

    inspector = inspect(engine)
    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            if not inspector.has_table(table.name):
                continue  # just created above, definitely has every column
            existing_columns = {c["name"] for c in inspector.get_columns(table.name)}
            for column in table.columns:
                if column.name not in existing_columns:
                    col_type = column.type.compile(dialect=engine.dialect)
                    nullable = "" if column.nullable else " NOT NULL"
                    ddl = f'ALTER TABLE {table.name} ADD COLUMN {column.name} {col_type}{nullable}'
                    print(f"[init-db] Adding missing column: {table.name}.{column.name}")
                    conn.execute(text(ddl))
