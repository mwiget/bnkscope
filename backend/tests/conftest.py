"""
Shared test fixtures for bnkscope backend integration tests.

Provides:
- SQLite in-memory database with all tables created
- FastAPI TestClient with dependency overrides
- Sample data fixtures

Usage:
    def test_example(client):
        response = client.get("/api/k8s/clusters")
        assert response.status_code == 200
"""

import os
import sys
import tempfile

# ---------------------------------------------------------------------------
# Environment setup — MUST happen before any backend imports
# ---------------------------------------------------------------------------

# Settings-level DATABASE_URL. The engine fixture below builds its own
# in-memory engine; this one exists for the code that reads settings rather
# than the session — ``backup_service._database_path()`` in particular, which
# needs a real path. It must not be ``sqlite:///file::memory:...``: SQLAlchemy
# has no ``uri=True`` here, so that form creates a junk file named
# ``file::memory:`` in the working directory.
os.environ["DATABASE_URL"] = f"sqlite:///{tempfile.mkdtemp()}/bnkscope-settings.db"
os.environ["ENVIRONMENT"] = "development"
# Force inline (single-threaded) discovery so tests run synchronously against the test session.

# Create a temporary encryption key file so core.encryption doesn't fail
_tmp_key_dir = tempfile.mkdtemp()
_encryption_key_file = os.path.join(_tmp_key_dir, "encryption.key")
os.environ["ENCRYPTION_KEY_FILE"] = _encryption_key_file

# Ensure backend package is importable
backend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if backend_path not in sys.path:
    sys.path.insert(0, backend_path)

# ---------------------------------------------------------------------------
# Imports (after env setup)
# ---------------------------------------------------------------------------

from concurrent.futures import Future
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

# Import ALL models so Base.metadata knows about every table
import models  # noqa: F401 — triggers barrel imports in models/__init__.py
from database import Base, get_db

# ---------------------------------------------------------------------------
# Database fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def engine():
    """Create a shared SQLite in-memory engine for the entire test session."""
    eng = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    # Enable WAL-like behaviour: allow nested transactions
    @event.listens_for(eng, "connect")
    def _set_sqlite_pragma(dbapi_conn, _connection_record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    # Create all tables once
    Base.metadata.create_all(bind=eng)
    yield eng
    Base.metadata.drop_all(bind=eng)
    eng.dispose()


@pytest.fixture(autouse=True)
def _reset_reachability_breakers():
    """Isolate the reachability circuit-breaker registry between tests (#55).

    Autouse -- NOT tied to the ``db`` fixture -- because a unit test can trip a
    breaker without touching the database, and the next test would inherit it.
    The registry is a process-global singleton keyed by (target_type,
    target_id); a breaker tripped OPEN by one test otherwise short-circuits
    every later test reusing that id with BreakerOpenError. Order-dependent
    failures that only appear in a monolithic ``pytest tests/`` run, never in
    CI's per-suite processes -- which is exactly why they went unnoticed.

    Reset before AND after: before, so a test never inherits state from a
    predecessor that failed mid-way; after, so a test's own trips don't
    outlive it even if a later fixture errors.
    """
    from services.reachability.registry import registry

    registry.reset_breaker_state()
    yield
    registry.reset_breaker_state()


@pytest.fixture()
def db(engine):
    """
    Provide a transactional database session that rolls back after each test.

    This keeps tests isolated without paying the cost of table recreation.
    """
    connection = engine.connect()
    transaction = connection.begin()
    TestingSessionLocal = sessionmaker(bind=connection)
    session = TestingSessionLocal()

    # Code that runs outside FastAPI's dependency injection opens its own
    # session via database.SessionLocal (e.g. AuthMiddleware verifying an API
    # token). Point that factory at the test connection so it sees this test's
    # data instead of trying to reach the real database.
    import database
    real_session_local = database.SessionLocal
    database.SessionLocal = TestingSessionLocal

    # Fire-and-forget work must not run against this connection. `submit` hands
    # the job to a thread pool, the job opens its own session via the factory
    # patched just above -- so it lands on the very connection this fixture is
    # about to roll back, and a SQLAlchemy connection is not thread-safe. That
    # race produced three different CI failures from one cause: an
    # InvalidRequestError surfacing as a 500 when the job overlapped the
    # request, a row surviving the rollback (the job's commit ended the
    # fixture's transaction) so the next test saw a duplicate, and a later
    # test's own rows vanishing with that same stray commit. Timing-dependent,
    # so it passed locally and failed on the slower CI runner.
    #
    # Tests that care about the enqueue itself patch `submit` and assert on the
    # mock; nothing wants a real background scan against a test database.
    import core.background
    real_submit = core.background.submit

    def _dropped_background_job(fn, *args, **kwargs):
        fut: Future = Future()
        fut.set_result(None)
        return fut

    core.background.submit = _dropped_background_job

    yield session

    core.background.submit = real_submit
    database.SessionLocal = real_session_local
    session.close()
    transaction.rollback()
    connection.close()


# ---------------------------------------------------------------------------
# Mock heavy services that aren't needed for route-level tests
# ---------------------------------------------------------------------------

def _noop_cache():
    """Return a mock CacheService that always misses."""
    mock = MagicMock()
    mock.get.return_value = None
    mock.set.return_value = True
    mock.delete.return_value = True
    mock.delete_pattern.return_value = 0
    mock.redis = None
    return mock


@pytest.fixture()
def client(db):
    """
    FastAPI TestClient with DB override and mocked external services.

    The TestClient uses `raise_server_exceptions=False` so that our custom
    error handlers (AppError -> JSONResponse) work as they do in production.
    """
    from main import app

    # Override get_db so every route receives our test session
    def _override_get_db():
        try:
            yield db
        finally:
            pass  # session cleanup handled by the `db` fixture

    app.dependency_overrides[get_db] = _override_get_db

    # Patch the cache to avoid needing Redis
    with patch("core.cache.cache", _noop_cache()):
        yield TestClient(app, raise_server_exceptions=False)

    # Cleanup overrides after each test
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Auth token helpers
# ---------------------------------------------------------------------------

# bnkscope has no authentication (Phase 3). These fixtures survive as no-ops
# so route tests keep their existing signatures — headers are empty and the
# "user" objects are None.


@pytest.fixture()
def admin_headers() -> dict:
    return {}


@pytest.fixture()
def operator_headers() -> dict:
    return {}


@pytest.fixture()
def viewer_headers() -> dict:
    return {}


@pytest.fixture()
def sample_user() -> None:
    return None


@pytest.fixture()
def sample_operator_user() -> None:
    return None


@pytest.fixture()
def sample_viewer_user() -> None:
    return None


@pytest.fixture()
def all_test_users() -> dict:
    return {}


@pytest.fixture()
def make_k8s_cluster(db):
    """Factory fixture: returns a callable that creates K8s clusters."""
    from tests.factories import KubernetesClusterFactory
    return lambda **kwargs: KubernetesClusterFactory(db, **kwargs)


@pytest.fixture()
def make_proxy_deployment(db):
    """Factory fixture: returns a callable that creates ProxyDeployment rows."""
    from tests.factories import ProxyDeploymentFactory
    return lambda **kwargs: ProxyDeploymentFactory(db, **kwargs)


# ---------------------------------------------------------------------------
# Mock service fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def mock_cache():
    """Provide a standalone MockCacheService for tests that need explicit cache control."""
    from tests.mocks.cache_mock import MockCacheService
    return MockCacheService()


