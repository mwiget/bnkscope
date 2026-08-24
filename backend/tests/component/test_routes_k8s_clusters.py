"""
Component tests verifying that cluster register/update/refresh routes
enqueue a background scan after committing the cluster row.

Pattern mirrors test_project_module_service.py:685-721:
  patch enqueue_cluster_scan, hit the route via TestClient, assert it was called.

These tests use the existing `client`, `admin_headers`, `sample_user`,
and `sample_project` fixtures from conftest.py.
"""

from unittest.mock import MagicMock, patch

import pytest

_SCAN_ENQUEUE = "routes.k8s.clusters.enqueue_cluster_scan"


class TestClusterRouteEnqueuesScans:
    """Routes enqueue scan_cluster_async after committing a cluster row."""

    def test_add_cluster_enqueues_scan(self, client, admin_headers, sample_user):
        """POST /api/k8s/clusters enqueues a scan with the new cluster id."""
        mock_result = {
            "id": 7,
            "name": "ocp-cluster",
            "context": "ocp-context",
            "status": "pending",
            "project_id": None,
        }

        with patch("routes.k8s.clusters.ClusterManagementService") as MockService, \
             patch(_SCAN_ENQUEUE) as mock_enqueue:
            MockService.return_value.create_cluster.return_value = mock_result

            response = client.post(
                "/api/k8s/clusters",
                json={"name": "ocp-cluster", "context": "ocp-context", "kubeconfig": "apiVersion: v1"},
                headers=admin_headers,
            )

        assert response.status_code == 200, response.text
        mock_enqueue.assert_called_once_with(7)

    def test_update_cluster_enqueues_scan(
        self, client, admin_headers, sample_user, make_k8s_cluster
    ):
        """PUT /api/k8s/clusters/{id} enqueues a scan with the cluster id."""
        cluster = make_k8s_cluster(name="update-cluster")

        mock_result = {
            "id": cluster.id,
            "name": "update-cluster",
            "context": "new-context",
            "status": "active",
        }

        with patch("routes.k8s.clusters.ClusterManagementService") as MockService, \
             patch(_SCAN_ENQUEUE) as mock_enqueue:
            MockService.return_value.update_cluster.return_value = mock_result

            response = client.put(
                f"/api/k8s/clusters/{cluster.id}",
                json={"name": "update-cluster", "context": "new-context"},
                headers=admin_headers,
            )

        assert response.status_code == 200, response.text
        mock_enqueue.assert_called_once_with(cluster.id)

    def test_adopting_a_context_enqueues_scan(self, client, admin_headers, sample_user):
        """POST /api/k8s/discovery/adopt enqueues a scan for the new cluster.

        Replaces the refresh-kubeconfig test: that endpoint shelled out to
        `aws eks update-kubeconfig`, which cannot run in an image with no CLI
        tools, and a discovered cluster re-reads its kubeconfig every sweep.
        """
        adopted = {
            "context": "lab-a",
            "api_server": "https://10.1.2.3:6443",
            "cloud_provider": "on-prem",
            "auth_method": "client-certificate",
            "source_path": "/host/.kube/config",
            "state": "reachable",
            "registered": True,
            "cluster_id": 42,
            "has_bnk": False,
            "version": "1.29",
            "detail": None,
        }

        with patch("routes.k8s.clusters.ClusterDiscoveryService") as MockService, \
             patch(_SCAN_ENQUEUE) as mock_enqueue:
            MockService.return_value.adopt.return_value = adopted

            response = client.post(
                "/api/k8s/discovery/adopt",
                json={"context": "lab-a"},
                headers=admin_headers,
            )

        assert response.status_code == 200, response.text
        mock_enqueue.assert_called_once_with(42)

    def test_adopting_a_context_that_did_not_register_enqueues_nothing(
        self, client, admin_headers, sample_user
    ):
        """No cluster id means no scan to run — enqueueing None would 500 later."""
        adopted = {
            "context": "lab-a",
            "api_server": "https://10.1.2.3:6443",
            "cloud_provider": "on-prem",
            "auth_method": "client-certificate",
            "source_path": "/host/.kube/config",
            "state": "unreachable",
            "registered": False,
            "cluster_id": None,
            "has_bnk": False,
            "version": None,
            "detail": "Timed out reaching the API server",
        }

        with patch("routes.k8s.clusters.ClusterDiscoveryService") as MockService, \
             patch(_SCAN_ENQUEUE) as mock_enqueue:
            MockService.return_value.adopt.return_value = adopted

            response = client.post(
                "/api/k8s/discovery/adopt",
                json={"context": "lab-a"},
                headers=admin_headers,
            )

        assert response.status_code == 200, response.text
        mock_enqueue.assert_not_called()
