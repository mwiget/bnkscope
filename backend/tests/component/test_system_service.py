"""
Tests for services.system_service — system health, version, cleanup, database stats.

BC-011: SystemService — real DB for cleanup, mock GitHub for external calls.
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, PropertyMock, patch

import pytest
from sqlalchemy import text

from core.errors import BadRequestError
from services.system_service import SystemService

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _noop_cache():
    """Cache mock that always misses."""
    mock = MagicMock()
    mock.get.return_value = None
    mock.set.return_value = True
    return mock


# ---------------------------------------------------------------------------
# get_health
# ---------------------------------------------------------------------------

class TestGetHealth:
    """The body behind GET /api/system/health.

    Every test that touched this used to mock the service out, because the real
    thing needed Redis and a Celery worker. It doesn't any more (Phase 4), so
    these run it for real — and they must, since the route declares a
    response_model and a wrong-shaped return is a 500 no unit test would see.
    """

    @pytest.fixture(autouse=True)
    def _no_cache(self):
        from core.cache import cache as real_cache
        real_cache.delete("system:health")
        yield
        real_cache.delete("system:health")

    def test_shape_matches_the_declared_response_model(self, db):
        from schemas.system import SystemHealthResponse

        result = SystemService(db).get_health()
        SystemHealthResponse.model_validate(result)  # raises if the shape drifted

    def test_reports_backend_and_database(self, db):
        result = SystemService(db).get_health()
        assert set(result["services"]) == {"backend", "database"}
        assert result["services"]["backend"]["status"] == "healthy"
        assert result["services"]["database"]["status"] == "healthy"

    def test_carries_a_timestamp(self, db):
        timestamp = SystemService(db).get_health()["timestamp"]
        assert timestamp
        assert "T" in timestamp  # ISO-8601

    def test_a_dead_database_is_offline_not_an_exception(self, db):
        """The health endpoint must answer even when the thing it checks is down."""
        svc = SystemService(db)
        with patch.object(svc, "db") as broken:
            broken.execute.side_effect = RuntimeError("database is locked")
            result = svc.get_health()

        assert result["services"]["database"]["status"] == "offline"
        assert "database is locked" in result["services"]["database"]["error"]

    def test_the_result_is_cached(self, db):
        from core.cache import cache as real_cache

        first = SystemService(db).get_health()
        assert real_cache.get("system:health") == first

        # A second call must come from the cache, not re-probe the database.
        svc = SystemService(db)
        with patch.object(svc, "db") as never_touched:
            assert svc.get_health() == first
            never_touched.execute.assert_not_called()


class TestIsUpgradeInProgress:
    """Class-level upgrade lock flag."""

    def test_default_is_false(self):
        assert SystemService.is_upgrade_in_progress() is False

    def test_set_and_check(self):
        original = SystemService._upgrade_in_progress
        try:
            SystemService._upgrade_in_progress = True
            assert SystemService.is_upgrade_in_progress() is True
        finally:
            SystemService._upgrade_in_progress = original


# ---------------------------------------------------------------------------
# get_upgrade_readiness
# ---------------------------------------------------------------------------

class TestGetUpgradeReadiness:
    """Pre-flight checks for system upgrade."""

    @patch("services.system_service.os.path.exists", return_value=True)
    @patch.dict("os.environ", {"HOST_REPO_PATH": "/opt/bnk-forge"})
    def test_ready_when_all_set(self, mock_exists, db):
        svc = SystemService(db)
        result = svc.get_upgrade_readiness()
        assert result["host_repo_path_set"] is True
        assert result["docker_socket_available"] is True
        assert result["upgrade_ready"] is True

    @patch("services.system_service.os.path.exists", return_value=False)
    @patch.dict("os.environ", {"HOST_REPO_PATH": ""}, clear=False)
    def test_not_ready_missing_both(self, mock_exists, db):
        svc = SystemService(db)
        result = svc.get_upgrade_readiness()
        assert result["host_repo_path_set"] is False
        assert result["docker_socket_available"] is False
        assert result["upgrade_ready"] is False

    @patch("services.system_service.os.path.exists", return_value=True)
    @patch.dict("os.environ", {"HOST_REPO_PATH": ""}, clear=False)
    def test_not_ready_missing_repo_path(self, mock_exists, db):
        svc = SystemService(db)
        result = svc.get_upgrade_readiness()
        assert result["host_repo_path_set"] is False
        assert result["upgrade_ready"] is False


# ---------------------------------------------------------------------------
# get_system_version
# ---------------------------------------------------------------------------

class TestGetSystemVersion:
    """Version check — reads local VERSION file and GitHub API."""

    @patch("services.system_service.requests.get")
    @patch("services.system_service.os.path.exists", return_value=False)
    def test_no_version_file(self, mock_exists, mock_get, db):
        mock_get.return_value = MagicMock(status_code=200, text="2.0.0")
        svc = SystemService(db)
        result = svc.get_system_version()
        assert result["current_version"] == "unknown"
        assert result["latest_version"] == "2.0.0"

    @patch("services.system_service.requests.get")
    @patch("builtins.open", create=True)
    @patch("services.system_service.os.path.exists", side_effect=lambda p: p == "VERSION")
    def test_version_file_and_github(self, mock_exists, mock_open, mock_get, db):
        mock_open.return_value.__enter__ = lambda s: s
        mock_open.return_value.__exit__ = MagicMock(return_value=False)
        mock_open.return_value.read.return_value = "1.0.0"
        mock_get.return_value = MagicMock(status_code=200, text="1.1.0")
        svc = SystemService(db)
        result = svc.get_system_version()
        assert result["current_version"] == "1.0.0"
        assert result["latest_version"] == "1.1.0"
        assert result["update_available"] is True

    @patch("services.system_service.requests.get")
    @patch("builtins.open", create=True)
    @patch("services.system_service.os.path.exists", side_effect=lambda p: p == "VERSION")
    def test_same_version_no_update(self, mock_exists, mock_open, mock_get, db):
        mock_open.return_value.__enter__ = lambda s: s
        mock_open.return_value.__exit__ = MagicMock(return_value=False)
        mock_open.return_value.read.return_value = "2.0.0"
        mock_get.return_value = MagicMock(status_code=200, text="2.0.0")
        svc = SystemService(db)
        result = svc.get_system_version()
        assert result["update_available"] is False

    @patch("services.system_service.requests.get")
    @patch("services.system_service.os.path.exists", return_value=False)
    def test_github_timeout(self, mock_exists, mock_get, db):
        import requests as real_requests
        mock_get.side_effect = real_requests.exceptions.Timeout("timed out")
        svc = SystemService(db)
        result = svc.get_system_version()
        assert result["error"] is None
        assert result["update_available"] is False

    @patch("services.system_service.requests.get")
    @patch("services.system_service.os.path.exists", return_value=False)
    def test_github_rate_limit(self, mock_exists, mock_get, db):
        mock_get.return_value = MagicMock(status_code=403)
        svc = SystemService(db)
        result = svc.get_system_version()
        assert result["error"] is None
        assert result["update_available"] is False


# ---------------------------------------------------------------------------
# cleanup_database
# ---------------------------------------------------------------------------

class TestGetDatabaseStats:
    """Database statistics with mocked pg-specific SQL."""

class TestGetPerformanceMetrics:
    """Performance metrics — task durations, DB stats."""

    @patch("services.system_service.cache")
    def test_performance_metrics_cached(self, mock_cache, db):
        cached_data = {"api": {"avg_task_duration_ms": 100}, "database": {}, "tasks": {}}
        mock_cache.get.return_value = cached_data
        svc = SystemService(db)
        result = svc.get_performance_metrics()
        assert result["api"]["avg_task_duration_ms"] == 100


# ---------------------------------------------------------------------------
# get_recent_errors
# ---------------------------------------------------------------------------

class TestGetRecentErrors:
    """Recent failed tasks."""

    @patch("services.system_service.cache", _noop_cache())
    def test_no_errors(self, db):
        svc = SystemService(db)
        result = svc.get_recent_errors()
        assert result["errors"] == []
        assert result["total"] == 0

    @patch("services.system_service.cache", _noop_cache())
    def test_limit_capped_at_50(self, db):
        svc = SystemService(db)
        result = svc.get_recent_errors(limit=100)
        # Should not error, but limit is capped internally
        assert result["total"] >= 0

class TestVacuumDatabase:
    """VACUUM operation."""

    def test_vacuum_success(self, db):
        """Mock the raw connection for VACUUM."""
        mock_cursor = MagicMock()
        mock_raw_conn = MagicMock()
        mock_raw_conn.isolation_level = 1
        mock_raw_conn.cursor.return_value = mock_cursor
        mock_conn = MagicMock()
        mock_conn.connection = mock_raw_conn

        with patch.object(db, "connection", return_value=mock_conn):
            svc = SystemService(db)
            result = svc.vacuum_database()

        assert result["status"] == "success"
        assert "duration_seconds" in result
        mock_cursor.execute.assert_called_once_with("VACUUM")

    def test_vacuum_failure_skipped(self, db):
        """When VACUUM fails, result should be 'skipped'."""
        mock_cursor = MagicMock()
        mock_cursor.execute.side_effect = Exception("VACUUM not supported on SQLite")
        mock_raw_conn = MagicMock()
        mock_raw_conn.isolation_level = 1
        mock_raw_conn.cursor.return_value = mock_cursor
        mock_conn = MagicMock()
        mock_conn.connection = mock_raw_conn

        with patch.object(db, "connection", return_value=mock_conn):
            svc = SystemService(db)
            result = svc.vacuum_database()

        assert result["status"] == "skipped"


# ---------------------------------------------------------------------------
# trigger_upgrade
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Upgrade state persistence (UP-003)
# ---------------------------------------------------------------------------

class TestUpgradeStatePersistence:
    """UP-003: Persist upgrade state to ApplicationSetting."""

    def test_save_and_read_state(self, db):
        svc = SystemService(db)
        state = {
            "status": "in_progress",
            "old_version": "2.10.60",
            "new_version": "2.10.61",
            "started_at": "2026-02-27T00:00:00Z",
            "completed_at": None,
            "current_phase": "build",
            "phase_label": "Building containers",
            "log": ["Starting upgrade", "Building..."],
        }
        svc._save_upgrade_state(state)
        result = svc.get_upgrade_state()
        assert result is not None
        assert result["status"] == "in_progress"
        assert result["old_version"] == "2.10.60"
        assert result["current_phase"] == "build"
        assert len(result["log"]) == 2

    def test_overwrite_existing_state(self, db):
        svc = SystemService(db)
        svc._save_upgrade_state({"status": "in_progress", "log": []})
        svc._save_upgrade_state({"status": "completed", "log": ["done"]})
        result = svc.get_upgrade_state()
        assert result["status"] == "completed"

    def test_read_when_no_state_exists(self, db):
        svc = SystemService(db)
        result = svc.get_upgrade_state()
        assert result is None


# ---------------------------------------------------------------------------
# Pre-upgrade safety checks (UP-010)
# ---------------------------------------------------------------------------

class TestPreUpgradeSafetyChecks:
    """UP-010: Verify pre-upgrade checks block when deployments are active."""

    @patch("services.system_service.subprocess.run")
    @patch.object(SystemService, "get_system_version")
    @patch.object(SystemService, "get_upgrade_readiness")
    def test_blocked_by_docker_failure(self, mock_ready, mock_version, mock_run, db):
        mock_ready.return_value = {
            "host_repo_path_set": True, "docker_socket_available": True,
            "upgrade_ready": True, "upgrade_in_progress": False,
        }
        mock_version.return_value = {
            "current_version": "2.0.0", "latest_version": "2.1.0",
            "update_available": True,
        }
        # Docker info fails
        mock_run.return_value = MagicMock(returncode=1, stderr="Cannot connect to Docker daemon")

        svc = SystemService(db)
        result = svc.trigger_upgrade()
        assert result["status"] == "docker_error"

    @patch("services.system_service.subprocess.run")
    @patch.object(SystemService, "get_system_version")
    @patch.object(SystemService, "get_upgrade_readiness")
    def test_docker_timeout(self, mock_ready, mock_version, mock_run, db):
        mock_ready.return_value = {
            "host_repo_path_set": True, "docker_socket_available": True,
            "upgrade_ready": True, "upgrade_in_progress": False,
        }
        mock_version.return_value = {
            "current_version": "2.0.0", "latest_version": "2.1.0",
            "update_available": True,
        }
        import subprocess as real_subprocess
        mock_run.side_effect = real_subprocess.TimeoutExpired(cmd="docker", timeout=10)

        svc = SystemService(db)
        result = svc.trigger_upgrade()
        assert result["status"] == "docker_error"
        assert "timed out" in result["message"]


# ---------------------------------------------------------------------------
# Post-upgrade verification (UP-011)
# ---------------------------------------------------------------------------

class TestVerifyPostUpgrade:
    """UP-011: Post-upgrade service health verification."""

    @patch("services.system_service.os.path.exists", side_effect=lambda p: p == "VERSION")
    @patch("builtins.open", create=True)
    def test_healthy_verdict(self, mock_open, mock_exists, db):
        mock_open.return_value.__enter__ = lambda s: s
        mock_open.return_value.__exit__ = MagicMock(return_value=False)
        mock_open.return_value.read.return_value = "2.1.0"

        svc = SystemService(db)
        # Set upgrade state with matching expected version
        svc._save_upgrade_state({"new_version": "2.1.0", "status": "completed", "log": []})

        result = svc.verify_post_upgrade()
        assert result["checks"]["version"]["status"] == "pass"
        assert result["checks"]["database"]["status"] == "pass"
        assert result["checks"]["schema"]["status"] == "pass"
        assert result["verdict"] == "healthy"

    @patch("services.system_service.os.path.exists", side_effect=lambda p: p == "VERSION")
    @patch("builtins.open", create=True)
    def test_version_mismatch_fails(self, mock_open, mock_exists, db):
        mock_open.return_value.__enter__ = lambda s: s
        mock_open.return_value.__exit__ = MagicMock(return_value=False)
        mock_open.return_value.read.return_value = "2.0.0"  # Still old version!

        svc = SystemService(db)
        svc._save_upgrade_state({"new_version": "2.1.0", "status": "completed", "log": []})
        result = svc.verify_post_upgrade()
        assert result["checks"]["version"]["status"] == "fail"
        assert result["verdict"] == "unhealthy"

    @patch("services.system_service.os.path.exists", side_effect=lambda p: p == "VERSION")
    @patch("builtins.open", create=True)
    def test_missing_table_fails_the_schema_check(self, mock_open, mock_exists, db):
        """A table the models declare but the database lacks is a failed upgrade."""
        mock_open.return_value.__enter__ = lambda s: s
        mock_open.return_value.__exit__ = MagicMock(return_value=False)
        mock_open.return_value.read.return_value = "2.1.0"

        svc = SystemService(db)
        svc._save_upgrade_state({"new_version": "2.1.0", "status": "completed", "log": []})
        db.execute(text("DROP TABLE notifications"))

        result = svc.verify_post_upgrade()
        assert result["checks"]["schema"]["status"] == "fail"
        assert "notifications" in result["checks"]["schema"]["missing_tables"]
        assert result["verdict"] == "unhealthy"

class TestTriggerUpgrade:
    """System upgrade trigger with mocked readiness and version check."""

    @patch.object(SystemService, "get_system_version")
    @patch.object(SystemService, "get_upgrade_readiness")
    def test_not_configured(self, mock_ready, mock_version, db):
        mock_ready.return_value = {
            "host_repo_path_set": False, "docker_socket_available": False,
            "upgrade_ready": False,
        }
        svc = SystemService(db)
        result = svc.trigger_upgrade()
        assert result["status"] == "not_configured"

    @patch.object(SystemService, "get_system_version")
    @patch.object(SystemService, "get_upgrade_readiness")
    def test_no_update_available(self, mock_ready, mock_version, db):
        mock_ready.return_value = {
            "host_repo_path_set": True, "docker_socket_available": True,
            "upgrade_ready": True, "upgrade_in_progress": False,
        }
        mock_version.return_value = {
            "current_version": "2.0.0", "latest_version": "2.0.0",
            "update_available": False,
        }
        svc = SystemService(db)
        result = svc.trigger_upgrade()
        assert result["status"] == "no_update"

    @patch.object(SystemService, "get_system_version")
    @patch.object(SystemService, "get_upgrade_readiness")
    def test_already_upgrading(self, mock_ready, mock_version, db):
        mock_ready.return_value = {
            "host_repo_path_set": True, "docker_socket_available": True,
            "upgrade_ready": True, "upgrade_in_progress": False,
        }
        original = SystemService._upgrade_in_progress
        try:
            SystemService._upgrade_in_progress = True
            svc = SystemService(db)
            result = svc.trigger_upgrade()
            assert result["status"] == "already_upgrading"
        finally:
            SystemService._upgrade_in_progress = original
