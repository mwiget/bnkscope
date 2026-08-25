"""
Integration tests for NICo routes — /api/k8s/clusters/{cid}/nico/*.

Covers: detect, data, health, endpoint override. Uses FastAPI TestClient with
the real SQLite DB; the NICo service functions and KubernetesService are
mocked, so nothing here talks to a cluster or opens a gRPC channel.
"""

from unittest.mock import patch

from services.nico.constants import FORGE_ENDPOINT_KEY


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


class TestNicoEndpointOverride:
    """PUT /api/k8s/clusters/{cluster_id}/nico/endpoint."""

    def _put(self, client, cluster_id, headers, endpoint):
        return client.put(
            f"/api/k8s/clusters/{cluster_id}/nico/endpoint",
            json={"endpoint": endpoint},
            headers=headers,
        )

    def test_an_override_is_stored_on_the_cluster(
        self, client, admin_headers, all_test_users, make_k8s_cluster, db
    ):
        cluster = make_k8s_cluster(name="nico-endpoint-set")
        response = self._put(client, cluster.id, admin_headers, "127.0.0.1:11079")
        assert response.status_code == 200
        assert response.json()["endpoint"] == "127.0.0.1:11079"

        db.refresh(cluster)
        assert cluster.meta_data[FORGE_ENDPOINT_KEY] == "127.0.0.1:11079"

    def test_clearing_it_leaves_the_rest_of_meta_data_alone(
        self, client, admin_headers, all_test_users, make_k8s_cluster, db
    ):
        """Discovery writes has_dpf/has_nico into the same dict; clearing one
        key must not take the flags that gate the tabs with it."""
        cluster = make_k8s_cluster(name="nico-endpoint-clear")
        cluster.meta_data = {"has_nico": True, FORGE_ENDPOINT_KEY: "10.0.0.1:1079"}
        db.commit()

        assert self._put(client, cluster.id, admin_headers, None).status_code == 200
        db.refresh(cluster)
        assert FORGE_ENDPOINT_KEY not in cluster.meta_data
        assert cluster.meta_data["has_nico"] is True

    def test_a_url_is_rejected_rather_than_silently_dropped(
        self, client, admin_headers, all_test_users, make_k8s_cluster
    ):
        """A scheme would be swallowed by the gRPC channel, not honoured."""
        cluster = make_k8s_cluster(name="nico-endpoint-url")
        response = self._put(
            client, cluster.id, admin_headers, "https://10.0.0.1:1079"
        )
        assert response.status_code == 422

    def test_a_bare_host_is_rejected(
        self, client, admin_headers, all_test_users, make_k8s_cluster
    ):
        cluster = make_k8s_cluster(name="nico-endpoint-noport")
        assert self._put(client, cluster.id, admin_headers, "10.0.0.1").status_code == 422

    def test_an_unknown_cluster_is_a_404(self, client, admin_headers, all_test_users):
        assert self._put(client, 999999, admin_headers, "10.0.0.1:1079").status_code == 404


def _deployment_half() -> dict:
    """What `fetch_nico_deployment` returns: `_data()` minus the Forge half.

    No `health` — the route computes that, and whether it scopes it correctly
    is exactly what these tests check.
    """
    return {k: v for k, v in _data().items() if k != "inventory"}


class TestNicoSplitFetch:
    """GET /nico/deployment and GET /nico/inventory."""

    @patch("routes.k8s.nico.fetch_nico_deployment")
    @patch("routes.k8s.nico.KubernetesService")
    def test_the_deployment_half_omits_the_inventory_counts(
        self, _k8s, mock_fetch, client, viewer_headers, all_test_users, make_k8s_cluster
    ):
        """A count of zero and a count not yet read are different answers; the
        UI renders them differently, so the payload must distinguish them."""
        cluster = make_k8s_cluster(name="nico-split-deployment")
        mock_fetch.return_value = _deployment_half()

        response = client.get(
            f"/api/k8s/clusters/{cluster.id}/nico/deployment", headers=viewer_headers
        )
        assert response.status_code == 200
        body = response.json()
        assert "inventory" not in body
        assert body["health"]["inventoryPending"] is True
        for absent in ("tenants", "vpcs", "loadBalancers", "networkSegments"):
            assert absent not in body["health"]
        # The half that *was* read is fully reported.
        assert body["controlPlane"]["pods"][0]["name"] == "nico-api-abc"
        assert body["health"]["dpus"] == {"total": 2, "ready": 2}

    @patch("routes.k8s.nico.fetch_nico_deployment")
    @patch("routes.k8s.nico.KubernetesService")
    def test_an_unread_inventory_is_not_called_unreachable(
        self, _k8s, mock_fetch, client, viewer_headers, all_test_users, make_k8s_cluster
    ):
        """The old ladder treated a missing inventory as proof the endpoint was
        unreachable. On this half it only means we have not looked yet."""
        cluster = make_k8s_cluster(name="nico-split-not-unreachable")
        mock_fetch.return_value = _deployment_half()

        body = client.get(
            f"/api/k8s/clusters/{cluster.id}/nico/deployment", headers=viewer_headers
        ).json()
        assert body["health"]["status"] != "unreachable"

    @patch("routes.k8s.nico.fetch_nico_inventory")
    @patch("routes.k8s.nico.KubernetesService")
    def test_the_inventory_half_carries_the_counts_to_merge(
        self, _k8s, mock_fetch, client, viewer_headers, all_test_users, make_k8s_cluster
    ):
        cluster = make_k8s_cluster(name="nico-split-inventory")
        mock_fetch.return_value = {
            "cluster_id": cluster.id,
            "inventory": _data()["inventory"],
            "errors": [],
        }

        response = client.get(
            f"/api/k8s/clusters/{cluster.id}/nico/inventory", headers=viewer_headers
        )
        assert response.status_code == 200
        body = response.json()
        assert body["counts"]["tenants"] == {"total": 1}
        assert body["counts"]["loadBalancers"]["total"] == 1
        assert body["counts"]["loadBalancers"]["ready"] == 1
        assert body["counts"]["loadBalancers"]["programmedPods"] == 2
        assert body["inventory"]["tenants"][0]["id"] == "acme"

    @patch("routes.k8s.nico.fetch_nico_inventory")
    @patch("routes.k8s.nico.KubernetesService")
    def test_a_soft_failure_still_reports_zeroed_counts(
        self, _k8s, mock_fetch, client, viewer_headers, all_test_users, make_k8s_cluster
    ):
        """Here the zeros are the truth: the read happened and found nothing."""
        cluster = make_k8s_cluster(name="nico-split-inventory-fail")
        mock_fetch.return_value = {
            "cluster_id": cluster.id,
            "inventory": {},
            "errors": ["Forge inventory unavailable: deadline exceeded"],
        }

        body = client.get(
            f"/api/k8s/clusters/{cluster.id}/nico/inventory", headers=viewer_headers
        ).json()
        assert body["counts"]["tenants"] == {"total": 0}
        assert "deadline exceeded" in body["errors"][0]
