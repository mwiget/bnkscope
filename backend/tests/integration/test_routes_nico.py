"""
Integration tests for NICo routes — /api/k8s/clusters/{cid}/nico/*.

Covers: detect, data, health. Uses FastAPI TestClient with the real SQLite DB;
the NICo service functions and KubernetesService are mocked, so nothing here
talks to a cluster or opens a gRPC channel.
"""

from unittest.mock import patch


def _detect(detected: bool = True) -> dict:
    return {
        "detected": detected,
        "namespace": "nico-system" if detected else None,
        "apiPods": 1 if detected else 0,
        "providerPods": 1 if detected else 0,
        "cluster_id": 1,
    }


def _data(errors=None) -> dict:
    return {
        "detected": True,
        "cluster_id": 1,
        "controlPlane": {
            "namespace": "nico-system",
            "pods": [{"name": "nico-api-abc", "namespace": "nico-system", "phase": "Running",
                      "ready": 1, "containers": 1, "restarts": 35, "node": "infra-cp1",
                      "image": "ghcr.io/example/nico-api:dev", "createdAt": None}],
            "webAuth": "none",
            "mtls": {"secret": "tmm-lb-admin-cert", "present": True, "daysLeft": 310},
            "version": "Forge v2.0.0",
        },
        "endpoint": {
            "kind": "nodeport", "host": "192.168.68.66", "port": 31079,
            "reachable": True, "candidates": [], "grpc": "192.168.68.66:31079",
            "webUi": "https://192.168.68.66:31079/admin/", "detail": None,
        },
        "providers": [],
        "dependencies": [],
        "dpf": {"total": 2, "ready": 2},
        "inventory": {
            "tenants": [{"id": "acme", "vpcCount": 1, "vpcIds": ["v1"], "vnis": [2024530],
                         "vipPrefixes": ["10.0.121.32/27"], "lbCount": 1,
                         "vips": ["10.0.121.33"], "lbsReady": 1}],
            "vpcs": [],
            "networkSegments": [],
            "loadBalancers": [{"id": "lb-1", "name": "web", "tenant": "acme",
                               "vip": "10.0.121.33", "status": "READY",
                               "programmedPods": 2, "pools": []}],
        },
        "errors": errors or [],
    }


class TestNicoDetect:
    """GET /api/k8s/clusters/{cluster_id}/nico/detect."""

    @patch("routes.k8s.nico.detect_nico")
    @patch("routes.k8s.nico.KubernetesService")
    def test_nico_installed(
        self, _mock_k8s_cls, mock_detect,
        client, viewer_headers, all_test_users, make_k8s_cluster,
    ):
        cluster = make_k8s_cluster(name="nico-detect-installed")
        mock_detect.return_value = _detect(True)

        response = client.get(
            f"/api/k8s/clusters/{cluster.id}/nico/detect", headers=viewer_headers
        )
        assert response.status_code == 200
        body = response.json()
        assert body["detected"] is True
        assert body["namespace"] == "nico-system"
        mock_detect.assert_called_once()

    @patch("routes.k8s.nico.detect_nico")
    @patch("routes.k8s.nico.KubernetesService")
    def test_nico_absent(
        self, _mock_k8s_cls, mock_detect,
        client, viewer_headers, all_test_users, make_k8s_cluster,
    ):
        cluster = make_k8s_cluster(name="nico-detect-none")
        mock_detect.return_value = _detect(False)

        response = client.get(
            f"/api/k8s/clusters/{cluster.id}/nico/detect", headers=viewer_headers
        )
        assert response.status_code == 200
        assert response.json()["detected"] is False


class TestNicoData:
    """GET /api/k8s/clusters/{cluster_id}/nico/data."""

    @patch("routes.k8s.nico.fetch_all_nico_data")
    @patch("routes.k8s.nico.KubernetesService")
    def test_returns_the_picture_and_a_health_rollup(
        self, _mock_k8s_cls, mock_fetch,
        client, viewer_headers, all_test_users, make_k8s_cluster,
    ):
        cluster = make_k8s_cluster(name="nico-data")
        mock_fetch.return_value = _data()

        response = client.get(
            f"/api/k8s/clusters/{cluster.id}/nico/data", headers=viewer_headers
        )
        assert response.status_code == 200
        body = response.json()
        assert body["health"]["status"] == "healthy"
        assert body["health"]["tenants"]["total"] == 1
        assert body["inventory"]["loadBalancers"][0]["vip"] == "10.0.121.33"
        assert body["endpoint"]["grpc"] == "192.168.68.66:31079"

    @patch("routes.k8s.nico.fetch_all_nico_data")
    @patch("routes.k8s.nico.KubernetesService")
    def test_a_soft_failure_is_reported_not_raised(
        self, _mock_k8s_cls, mock_fetch,
        client, viewer_headers, all_test_users, make_k8s_cluster,
    ):
        """A NICo whose Forge endpoint is unroutable still has pods, a Service
        and a certificate worth showing — the request must not fail."""
        cluster = make_k8s_cluster(name="nico-data-degraded")
        payload = _data(errors=["Forge API not reachable: not routable from here"])
        payload["endpoint"]["reachable"] = False
        payload["inventory"] = {}
        mock_fetch.return_value = payload

        response = client.get(
            f"/api/k8s/clusters/{cluster.id}/nico/data", headers=viewer_headers
        )
        assert response.status_code == 200
        body = response.json()
        assert body["health"]["status"] == "unreachable"
        assert body["errors"] == ["Forge API not reachable: not routable from here"]
        assert body["controlPlane"]["pods"][0]["name"] == "nico-api-abc"


class TestNicoHealth:
    """GET /api/k8s/clusters/{cluster_id}/nico/health."""

    @patch("routes.k8s.nico.fetch_all_nico_data")
    @patch("routes.k8s.nico.KubernetesService")
    def test_returns_the_summary_alone(
        self, _mock_k8s_cls, mock_fetch,
        client, viewer_headers, all_test_users, make_k8s_cluster,
    ):
        cluster = make_k8s_cluster(name="nico-health")
        mock_fetch.return_value = _data()

        response = client.get(
            f"/api/k8s/clusters/{cluster.id}/nico/health", headers=viewer_headers
        )
        assert response.status_code == 200
        body = response.json()
        assert body["cluster_id"] == cluster.id
        assert body["loadBalancers"]["ready"] == 1
        assert "inventory" not in body
