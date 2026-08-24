"""
Integration tests for system routes — /api/system.

Covers: health (public), version, database stats, defaults, RBAC,
errors, database cleanup/vacuum, workspace management, container
management, defaults CRUD, and upgrade endpoints.
Uses FastAPI TestClient with real SQLite DB.
"""

from unittest.mock import MagicMock, patch

import pytest


class TestSystemHealth:
    """GET /api/system/health — public endpoint."""

    def test_health_no_auth(self, client, db):
        """Health endpoint works without authentication."""
        mock_health = {
            "services": {
                "backend": {"status": "healthy", "response_time_ms": 1.0},
                "database": {"status": "healthy", "response_time_ms": 2.0},
            },
            "timestamp": "2026-02-24T00:00:00",
        }
        with patch("routes.system.SystemService") as MockService:
            MockService.return_value.get_health.return_value = mock_health
            response = client.get("/api/system/health")

        assert response.status_code == 200
        data = response.json()
        assert "services" in data
        assert data["services"]["backend"]["status"] == "healthy"

class TestSystemAdmin:
    """Admin-only system endpoints."""

    def test_version_admin_allowed(self, client, admin_headers, sample_user):
        """Admin can access version endpoint."""
        with patch("routes.system.SystemService") as MockService:
            MockService.return_value.get_system_version.return_value = {
                "version": "2.10.49",
                "build": "test",
            }
            MockService.return_value.get_upgrade_readiness.return_value = {
                "ready": True,
            }
            response = client.get("/api/system/version", headers=admin_headers)

        assert response.status_code == 200

    def test_defaults_get(self, client, admin_headers, sample_user):
        """Get system defaults."""
        with patch("services.defaults_service.get_all_defaults") as mock_get:
            mock_get.return_value = {"aws_region": "us-east-1"}
            response = client.get("/api/system/defaults", headers=admin_headers)

        assert response.status_code == 200

    def test_performance_metrics(self, client, admin_headers, sample_user):
        """Performance metrics endpoint returns stats."""
        with patch("routes.system.SystemService") as MockService:
            MockService.return_value.get_performance_metrics.return_value = {
                "avg_response_ms": 50,
                "p95_response_ms": 200,
            }
            response = client.get("/api/system/performance", headers=admin_headers)

        assert response.status_code == 200

# ============================================================================
# Recent Errors
# ============================================================================

class TestRecentErrors:
    """GET /api/system/errors."""

    def test_returns_errors(self, client, admin_headers, sample_user):
        """Admin can retrieve recent errors."""
        mock_errors = {
            "errors": [
                {"id": 1, "message": "Task failed", "timestamp": "2026-01-01T00:00:00"},
            ],
            "count": 1,
        }
        with patch("routes.system.SystemService") as MockService:
            MockService.return_value.get_recent_errors.return_value = mock_errors
            response = client.get("/api/system/errors", headers=admin_headers)

        assert response.status_code == 200
        data = response.json()
        assert data["count"] == 1

    def test_respects_limit_param(self, client, admin_headers, sample_user):
        """Limit query parameter is forwarded to service."""
        with patch("routes.system.SystemService") as MockService:
            MockService.return_value.get_recent_errors.return_value = {"errors": [], "count": 0}
            response = client.get("/api/system/errors?limit=5", headers=admin_headers)

        assert response.status_code == 200
        MockService.return_value.get_recent_errors.assert_called_once_with(limit=5)

# ============================================================================
# Database Cleanup & Vacuum
# ============================================================================

class TestDatabaseVacuum:
    """POST /api/system/database/vacuum."""

    def test_vacuum_success(self, client, admin_headers, sample_user):
        """Admin can trigger database vacuum."""
        mock_result = {"status": "completed", "duration_ms": 120}
        with patch("routes.system.SystemService") as MockService:
            MockService.return_value.vacuum_database.return_value = mock_result
            response = client.post("/api/system/database/vacuum", headers=admin_headers)

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "completed"

# ============================================================================
# Defaults Status & Updates
# ============================================================================

class TestDefaultsStatus:
    """GET /api/system/defaults/status."""

    def test_returns_status(self, client, admin_headers, sample_user):
        """Admin can check defaults configuration status."""
        mock_status = {"all_configured": True, "missing": []}
        with patch("services.defaults_service.check_required_configured") as mock_check:
            mock_check.return_value = mock_status
            response = client.get("/api/system/defaults/status", headers=admin_headers)

        assert response.status_code == 200
        data = response.json()
        assert data["all_configured"] is True

class TestUpdateDefaults:
    """PUT /api/system/defaults."""

    def test_update_batch(self, client, admin_headers, sample_user):
        """Admin can update multiple defaults at once."""
        with patch("services.defaults_service.set_defaults_batch") as mock_batch:
            mock_batch.return_value = {"aws_region": True, "default_env": True}
            response = client.put(
                "/api/system/defaults",
                json={"updates": {"aws_region": "us-west-2", "default_env": "staging"}},
                headers=admin_headers,
            )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"

    def test_update_batch_partial_failure(self, client, admin_headers, sample_user):
        """Partial failure returns status='partial' with failed keys."""
        with patch("services.defaults_service.set_defaults_batch") as mock_batch:
            mock_batch.return_value = {"aws_region": True, "bad_key": False}
            response = client.put(
                "/api/system/defaults",
                json={"updates": {"aws_region": "us-west-2", "bad_key": "x"}},
                headers=admin_headers,
            )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "partial"
        assert "bad_key" in data["failed"]

class TestUpdateSingleDefault:
    """PUT /api/system/defaults/{key}."""

    def test_update_single_key(self, client, admin_headers, sample_user):
        """Admin can update a single default."""
        with patch("services.defaults_service.set_default") as mock_set:
            mock_set.return_value = True
            response = client.put(
                "/api/system/defaults/aws_region?value=eu-west-1",
                headers=admin_headers,
            )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert data["key"] == "aws_region"

    def test_invalid_key_returns_400(self, client, admin_headers, sample_user):
        """Invalid setting key returns 400."""
        with patch("services.defaults_service.set_default") as mock_set:
            mock_set.return_value = False
            response = client.put(
                "/api/system/defaults/nonexistent_key?value=whatever",
                headers=admin_headers,
            )

        assert response.status_code == 400

# ============================================================================
# Upgrade Endpoints
# ============================================================================

class TestUpgradeStatus:
    """GET /api/system/upgrade/status."""

    def test_no_upgrade_state(self, client, admin_headers, sample_user):
        """Returns status='none' when no upgrade has been run."""
        with patch("routes.system.SystemService") as MockService:
            MockService.return_value.get_upgrade_state.return_value = None
            response = client.get("/api/system/upgrade/status", headers=admin_headers)

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "none"

    def test_completed_upgrade(self, client, admin_headers, sample_user):
        """Returns completed upgrade state from DB."""
        mock_state = {
            "status": "completed",
            "old_version": "2.10.70",
            "new_version": "2.10.75",
            "started_at": "2026-03-01T00:00:00",
            "completed_at": "2026-03-01T00:05:00",
            "current_phase": "complete",
            "phase_label": "Upgrade completed",
            "pre_upgrade_commit": "abc123",
            "log": ["Pulling latest...", "Build complete"],
        }
        with patch("routes.system.SystemService") as MockService:
            MockService.return_value.get_upgrade_state.return_value = mock_state
            response = client.get("/api/system/upgrade/status", headers=admin_headers)

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "completed"
        assert data["old_version"] == "2.10.70"

    def test_interrupted_upgrade_detection(self, client, admin_headers, sample_user):
        """Detects interrupted upgrade when DB says in_progress but no class-level flag."""
        mock_state = {
            "status": "in_progress",
            "current_phase": "build",
            "phase_label": "Building containers...",
        }
        with patch("routes.system.SystemService") as MockService:
            MockService.return_value.get_upgrade_state.return_value = mock_state
            MockService.is_upgrade_in_progress.return_value = False
            response = client.get("/api/system/upgrade/status", headers=admin_headers)

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "interrupted"

class TestUpgradeVerify:
    """GET /api/system/upgrade/verify."""

    def test_verify_post_upgrade(self, client, admin_headers, sample_user):
        """Admin can run post-upgrade verification."""
        mock_result = {
            "healthy": True,
            "services": {"backend": "ok", "database": "ok"},
            "version_changed": True,
        }
        with patch("routes.system.SystemService") as MockService:
            MockService.return_value.verify_post_upgrade.return_value = mock_result
            response = client.get("/api/system/upgrade/verify", headers=admin_headers)

        assert response.status_code == 200
        data = response.json()
        assert data["healthy"] is True

class TestTriggerUpgrade:
    """POST /api/system/upgrade."""

    def test_trigger_upgrade(self, client, admin_headers, sample_user):
        """Admin can trigger a system upgrade."""
        mock_result = {"status": "started", "message": "Upgrade initiated"}
        with patch("routes.system.SystemService") as MockService:
            MockService.return_value.trigger_upgrade.return_value = mock_result
            response = client.post("/api/system/upgrade", headers=admin_headers)

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "started"
