"""
Tests for the factory system itself.

Verifies that all factories create valid model instances
that pass database constraints and can be used in further queries.
"""

import pytest


class TestK8sClusterFactory:
    """Test KubernetesClusterFactory creates valid clusters."""

    def test_creates_cluster(self, make_k8s_cluster):
        cluster = make_k8s_cluster()
        assert cluster.id is not None
        assert cluster.name.startswith("test-cluster-")
        assert cluster.context.startswith("test-context-")

    def test_cluster_names_are_unique(self, make_k8s_cluster):
        a = make_k8s_cluster()
        b = make_k8s_cluster()
        assert a.name != b.name
