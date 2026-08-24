"""Database connection and session management.

bnkscope runs on SQLite in a single file (Phase 4). The engine is still
URL-driven, so pointing DATABASE_URL at Postgres works, but nothing here
assumes a server any more.

SQLite needs two things to survive concurrent access from the request thread
and core/background.py's worker threads:

  WAL journaling   readers do not block the writer
  busy_timeout     a writer waits instead of failing "database is locked"

Both are set per-connection below; without them the background jobs would
intermittently lose writes to a concurrent request.
"""

from collections.abc import Generator
from contextlib import contextmanager

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

# Database configuration — sourced from Pydantic Settings (core.config)
# This ensures DATABASE_URL is validated and consistent with .env loading
from core.config import settings

DATABASE_URL = settings.DATABASE_URL

# Create engine with connection pooling
# PERFORMANCE OPTIMIZATION (ADR-019):
# Added explicit pool configuration to handle concurrent requests better
# For SQLite: check_same_thread=False allows usage across threads
# For PostgreSQL: uses connection pooling with proper settings
IS_SQLITE = DATABASE_URL.startswith("sqlite")

if IS_SQLITE:
    # check_same_thread=False: sessions are handed to background threads.
    engine = create_engine(
        DATABASE_URL,
        connect_args={"check_same_thread": False, "timeout": 30},
        echo=False,
    )

    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_connection, _connection_record):
        """WAL + busy timeout + enforced foreign keys on every connection."""
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA busy_timeout=30000")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA synchronous=NORMAL")
        finally:
            cursor.close()
else:
    # PostgreSQL with connection pooling
    engine = create_engine(
        DATABASE_URL,
        pool_size=10,           # Base number of connections to keep
        max_overflow=20,        # Allow up to 20 additional connections under load
        pool_recycle=3600,      # Recycle connections after 1 hour (prevents stale connections)
        pool_pre_ping=True,     # Test connections before use (handles dropped connections)
        pool_timeout=30,        # Timeout for getting connection from pool
        echo=False,             # Set to True for SQL query logging during development
    )

# Create session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Create base class for declarative models (SQLAlchemy 2.0+ style)
class Base(DeclarativeBase):
    pass


def get_db() -> Generator[Session, None, None]:
    """
    Dependency function for FastAPI to get database session.

    BE-002: Auto-rollback on exception — if the route raises any exception
    (including AppError), uncommitted changes are rolled back before the
    session is closed. This eliminates the need for manual db.rollback()
    in every except block.

    Routes should call db.commit() on success. If they don't commit and
    no exception is raised, changes are NOT auto-committed (safe default).

    Usage:
        @app.get("/endpoint")
        def my_endpoint(db: Session = Depends(get_db)):
            ...
    """
    db = SessionLocal()
    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


@contextmanager
def get_db_context():
    """
    Context manager for database session in non-FastAPI code.
    Usage:
        with get_db_context() as db:
            result = db.query(Model).all()
    """
    db = SessionLocal()
    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def init_database():
    """Create the schema if it is missing, then verify the connection.

    Alembic is gone (Phase 4): there is no upgrade path from bnk-forge, and a
    single-file local database does not need 152 migrations to reach its
    current shape. The schema is whatever the ORM models say it is.

    ``create_all`` is additive — it creates missing tables and is a no-op for
    existing ones. It does NOT alter a table whose columns have changed, so
    when a model changes shape during development, delete the file and let it
    be recreated. Nothing in bnkscope is a system of record; every row is
    either configuration you can re-enter or an observation that will be
    re-observed on the next scan.
    """
    import os
    from pathlib import Path

    if IS_SQLITE:
        # sqlite:////abs/path.db  →  /abs/path.db
        db_path = DATABASE_URL.split("sqlite:///", 1)[-1]
        if db_path and db_path != ":memory:":
            Path(os.path.dirname(db_path) or ".").mkdir(parents=True, exist_ok=True)

    # Import for the side effect of registering every mapper on Base.metadata.
    import models  # noqa: F401

    Base.metadata.create_all(bind=engine)

    db = SessionLocal()
    try:
        db.execute(text("SELECT 1"))
    finally:
        db.close()
