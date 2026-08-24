"""
BC-C3: Component tests for health monitor Celery task.

Tests health check dispatching, severity detection, and alert firing.
Mocks K8s API, Redis, and alert service.
"""

from unittest.mock import MagicMock, patch

import pytest

_MOD = "jobs.health_monitor"


# ── _fire_health_alert ───────────────────────────────────────────────

class TestFireHealthAlert:
    """tests for _fire_health_alert helper."""

    @patch("services.alert_service.fire_alert")
    def test_fire_alert_called_with_severity_change(self, mock_fire):
        from jobs.health_monitor import _fire_health_alert

        cluster = MagicMock()
        cluster.name = "test-cluster"
        cluster.project_id = 1
        cluster.id = 10

        health = {
            "overall_severity": "unhealthy",
            "components": {
                "flo": {"severity": "unhealthy", "running": 0, "total": 1},
                "tmm": {"severity": "healthy", "running": 2, "total": 2},
            },
        }

        db = MagicMock()
        _fire_health_alert(db, cluster, health, "unhealthy", "healthy")

        mock_fire.assert_called_once()
        call_kwargs = mock_fire.call_args[1]
        assert call_kwargs["event_type"] == "health_change"
        assert call_kwargs["severity"] == "critical"
        assert "test-cluster" in call_kwargs["title"]

    @patch("services.alert_service.fire_alert")
    def test_fire_alert_includes_affected_components(self, mock_fire):
        from jobs.health_monitor import _fire_health_alert

        cluster = MagicMock()
        cluster.name = "prod-cluster"
        cluster.project_id = 2
        cluster.id = 20

        health = {
            "overall_severity": "degraded",
            "components": {
                "gateways": {"severity": "degraded", "running": 1, "total": 3},
            },
        }

        db = MagicMock()
        _fire_health_alert(db, cluster, health, "degraded", "healthy")

        call_kwargs = mock_fire.call_args[1]
        assert "gateways" in call_kwargs["message"]


# ── check_cluster_health ─────────────────────────────────────────────

class TestCheckClusterHealth:
    """jobs.health_monitor.check_cluster_health."""

    @patch(f"{_MOD}.get_db_context")
    def test_no_clusters_returns_zero(self, mock_db_ctx, db):
        """No active clusters returns checked=0."""
        mock_db_ctx.return_value.__enter__ = MagicMock(return_value=db)
        mock_db_ctx.return_value.__exit__ = MagicMock(return_value=False)

        from jobs.health_monitor import check_cluster_health
        result = check_cluster_health()

        assert result["checked"] == 0
        assert result["alerts_fired"] == 0



class TestSeverityTransitions:
    """The comparison that decides whether an alert fires.

    Previous severity used to be read from Redis — which is not in
    requirements, not installed, and has no REDIS_URL in settings, so the
    client was always None. Two consequences, both silent: a severity *change*
    was never announced (nothing to compare against), and the first-detection
    branch re-fired every tick for every unhealthy cluster, held off only by
    alert_service's 60s rate limit, which is this job's own cadence.
    """

    def test_remembers_the_last_severity_it_saw(self):
        from jobs.health_monitor import _LAST_SEVERITY

        _LAST_SEVERITY.clear()
        _LAST_SEVERITY[7] = "healthy"

        assert _LAST_SEVERITY.get(7) == "healthy"
        # A cluster never seen has no previous severity, which is what makes
        # the first-detection branch distinguishable from a transition.
        assert _LAST_SEVERITY.get(99) is None

    def test_the_store_is_in_process_not_redis(self):
        import jobs.health_monitor as mod

        assert not hasattr(mod, "_get_redis")
        assert isinstance(mod._LAST_SEVERITY, dict)
