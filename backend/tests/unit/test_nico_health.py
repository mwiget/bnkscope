"""
Unit tests for services.nico.health — NICo health analysis.

Pure function (dict in → dict out), no mocking needed.
"""

from services.nico.health import analyze_nico_health


def _pod(ready=1, containers=1, phase="Running"):
    return {
        "name": "nico-api-abc",
        "namespace": "nico-system",
        "phase": phase,
        "ready": ready,
        "containers": containers,
        "restarts": 0,
        "node": "infra-cp1",
        "image": "ghcr.io/example/nico-api:dev",
        "createdAt": "2026-07-02T10:20:38+00:00",
    }


def _lb(status="READY", tenant="acme", programmed=2):
    return {
        "id": "lb-1",
        "name": "web",
        "tenant": tenant,
        "vip": "10.0.121.33",
        "status": status,
        "programmedPods": programmed,
        "pools": [{"name": "origins", "members": [{"address": "10.0.0.1", "port": 80}] * 2}],
    }


def _data(**overrides):
    base = {
        "detected": True,
        "controlPlane": {
            "namespace": "nico-system",
            "pods": [_pod()],
            "webAuth": "none",
            "mtls": {"secret": "tmm-lb-admin-cert", "present": True, "daysLeft": 310},
            "version": "Forge v2.0.0",
        },
        "endpoint": {"reachable": True, "grpc": "10.0.0.1:31079"},
        "providers": [{"name": "nico-lb-provider-tmm", "pod": _pod(), "config": {}, "recentErrors": []}],
        "dependencies": [
            {"name": "postgres", "namespace": "postgres", "pods": [_pod()]},
            {"name": "vault", "namespace": "vault", "pods": [_pod()]},
        ],
        "dpf": {"total": 2, "ready": 2},
        "inventory": {
            "tenants": [{"id": "acme"}],
            "vpcs": [{"id": "vpc-1"}],
            "networkSegments": [{"id": "seg-1"}],
            "loadBalancers": [_lb()],
        },
        "errors": [],
    }
    base.update(overrides)
    return base


class TestStatus:
    def test_everything_up_is_healthy(self):
        assert analyze_nico_health(_data())["status"] == "healthy"

    def test_no_nico_is_not_installed(self):
        health = analyze_nico_health(_data(detected=False))
        assert health["status"] == "not_installed"

    def test_an_unroutable_endpoint_is_unreachable_not_degraded(self):
        """The deployment view is still true — only the inventory is missing.

        Reporting this as `degraded` would say the wrong thing: nothing on the
        cluster is unhealthy, we just cannot dial it from here.
        """
        health = analyze_nico_health(
            _data(endpoint={"reachable": False, "grpc": None}, inventory={})
        )
        assert health["status"] == "unreachable"

    def test_an_empty_inventory_over_a_live_endpoint_is_still_unreachable(self):
        """A Forge session that returned nothing at all did not succeed."""
        health = analyze_nico_health(_data(inventory={}))
        assert health["status"] == "unreachable"

    def test_a_pending_load_balancer_degrades(self):
        data = _data()
        data["inventory"]["loadBalancers"] = [_lb(status="PENDING")]
        health = analyze_nico_health(data)
        assert health["status"] == "degraded"
        assert health["loadBalancers"] == {
            "total": 1, "ready": 0, "programmedPods": 2, "pools": 1, "members": 2,
        }

    def test_a_provider_logging_errors_degrades(self):
        """A provider that cannot reach NICo stays Running and Ready forever."""
        data = _data()
        data["providers"][0]["recentErrors"] = ["ERROR poll failed"]
        health = analyze_nico_health(data)
        assert health["status"] == "degraded"
        assert health["providers"]["withErrors"] == 1

    def test_a_down_dependency_degrades(self):
        data = _data()
        data["dependencies"][0]["pods"] = [_pod(ready=0, phase="CrashLoopBackOff")]
        assert analyze_nico_health(data)["status"] == "degraded"

    def test_a_certificate_near_expiry_degrades(self):
        """cert-manager renews long before this, so <30d means renewal is not
        happening — while calls still work, which is the whole problem."""
        data = _data()
        data["controlPlane"]["mtls"]["daysLeft"] = 12
        health = analyze_nico_health(data)
        assert health["status"] == "degraded"
        assert health["certExpiring"] is True


class TestRollups:
    def test_counts_come_from_the_inventory(self):
        health = analyze_nico_health(_data())
        assert health["tenants"]["total"] == 1
        assert health["vpcs"]["total"] == 1
        assert health["networkSegments"]["total"] == 1
        assert health["api"] == {"total": 1, "ready": 1}
        assert health["dependencies"] == {"total": 2, "ready": 2}

    def test_dpu_counts_are_carried_through_from_dpf(self):
        assert analyze_nico_health(_data())["dpus"] == {"total": 2, "ready": 2}

    def test_missing_sections_do_not_raise(self):
        health = analyze_nico_health({"detected": True})
        assert health["status"] == "unreachable"
        assert health["loadBalancers"]["total"] == 0
