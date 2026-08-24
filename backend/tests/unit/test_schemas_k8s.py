"""
BU-015: Unit tests for schemas.k8s module.

Tests all K8s response schemas — clusters, namespaces, resources,
scan, resource types, and tunnels. Real Pydantic validation, no mocks.
"""

import pytest

from schemas.k8s import (
    ClusterConnectionTestResponse,
    ClusterDetailResponse,
    ClusterListResponse,
    ClusterOperationResponse,
    ClusterSummary,
    CreateMigrationRequest,
    NamespaceInfo,
    NamespaceListResponse,
    NodeCountResponse,
)

# ── Cluster schemas ──────────────────────────────────────────────────

class TestClusterSummary:
    def test_minimal(self):
        c = ClusterSummary(id=1, name="dev-cluster")
        assert c.id == 1
        assert c.name == "dev-cluster"
        assert c.status == "active"  # default
        assert c.default_namespace == "default"

    def test_full(self):
        c = ClusterSummary(
            id=2,
            name="prod-cluster",
            context="arn:aws:eks:us-west-2:123:cluster/prod",
            api_server="https://eks.us-west-2.amazonaws.com",
            version="1.28",
            status="active",
            cloud_provider="aws",
            region="us-west-2",
            default_namespace="production",
            node_count=10,
            created_at="2026-01-01T00:00:00",
            updated_at="2026-02-01T00:00:00",
        )
        assert c.cloud_provider == "aws"
        assert c.node_count == 10

    def test_project_and_ssh_fields_are_gone(self):
        """Both concepts were removed (Phases 1-3); the schema outlived them.

        Pydantic ignores unknown kwargs by default, so a stale field here is
        silently accepted forever and keeps showing up in the generated
        TypeScript. Assert they no longer exist.
        """
        for dead in (
            "project_id",
            "ssh_tunnel_enabled",
            "ssh_remote_k8s_host",
            "ssh_remote_k8s_port",
            "ssh_credential_id",
            "ssh_host_override",
        ):
            assert dead not in ClusterSummary.model_fields

class TestClusterListResponse:
    def test_empty_list(self):
        r = ClusterListResponse(clusters=[])
        assert r.clusters == []

    def test_with_clusters(self):
        r = ClusterListResponse(
            clusters=[
                ClusterSummary(id=1, name="dev"),
                ClusterSummary(id=2, name="prod"),
            ]
        )
        assert len(r.clusters) == 2

class TestClusterDetailResponse:
    def test_full_detail(self):
        d = ClusterDetailResponse(
            id=1,
            name="prod",
            context="prod-context",
            api_server="https://k8s.example.com",
            version="1.28",
            status="active",
            region="us-west-2",
            meta_data={"provider": "aws", "tags": ["production"]},
        )
        assert d.region == "us-west-2"
        assert d.meta_data["provider"] == "aws"

class TestClusterOperationResponse:
    def test_success(self):
        r = ClusterOperationResponse(message="Cluster created", cluster_id=5)
        assert r.success is True
        assert r.cluster_id == 5

    def test_without_cluster_id(self):
        r = ClusterOperationResponse(message="Deleted")
        assert r.cluster_id is None

class TestClusterConnectionTestResponse:
    def test_success(self):
        r = ClusterConnectionTestResponse(
            success=True,
            message="Connection successful",
            cluster_name="prod-cluster",
            version="1.28.3",
            api_server="https://k8s.example.com",
            cloud_provider="aws",
            region="us-west-2",
        )
        assert r.success is True
        assert r.version == "1.28.3"
        assert r.cluster_name == "prod-cluster"

    def test_failure(self):
        r = ClusterConnectionTestResponse(
            success=False,
            message="Connection refused",
            status_code=403,
        )
        assert r.success is False
        assert r.version is None
        assert r.status_code == 403

# ── Namespace / Node schemas ─────────────────────────────────────────

class TestNamespaceInfo:
    def test_minimal(self):
        n = NamespaceInfo(name="default")
        assert n.name == "default"
        assert n.status is None

    def test_full(self):
        n = NamespaceInfo(
            name="production",
            status="Active",
            labels={"env": "prod"},
            created_at="2026-01-01T00:00:00",
        )
        assert n.labels["env"] == "prod"

class TestNamespaceListResponse:
    def test_with_namespaces(self):
        r = NamespaceListResponse(
            namespaces=[NamespaceInfo(name="default"), NamespaceInfo(name="kube-system")],
            cluster_id=1,
        )
        assert len(r.namespaces) == 2
        assert r.cluster_id == 1

class TestNodeCountResponse:
    def test_node_count(self):
        r = NodeCountResponse(node_count=5, cluster_id=1)
        assert r.node_count == 5

# ── Resource schemas ─────────────────────────────────────────────────

# ── Scan / Resource Type / Tunnel schemas ────────────────────────────

# ── CreateMigrationRequest — kubectl_resources validation (mwiget audit) ──────

MINIMAL_MIGRATION = {
    "source_descriptor": {"proxy_type": "cis-bigip", "class_name": "my-vs", "namespace": "default"},
    "combined_yaml": "apiVersion: v1\nkind: Namespace\nmetadata:\n  name: test\n",
}

class TestCreateMigrationRequestKubectlResources:
    """Validate that kubectl_resources elements are safe 'kind/name [namespace]' strings.

    Regression for mwiget audit finding: operator-supplied strings were passed
    toward kubectl delete with no format validation, allowing flag injection
    (e.g. '--all' would cause unintended mass deletion).
    """

    def test_valid_resources_accepted(self):
        """Well-formed 'kind/name' and 'kind/name namespace' strings pass."""
        req = CreateMigrationRequest(
            **MINIMAL_MIGRATION,
            teardown_info={
                "kubectl_resources": [
                    "virtualserver/my-vs",
                    "ingressclass/nginx default",
                    "crd.group.io/my-name kube-system",
                ],
            },
        )
        resources = req.teardown_info["kubectl_resources"]
        assert len(resources) == 3

    def test_none_teardown_info_accepted(self):
        """No teardown_info → no validation (optional field)."""
        req = CreateMigrationRequest(**MINIMAL_MIGRATION, teardown_info=None)
        assert req.teardown_info is None

    def test_teardown_info_without_kubectl_resources_accepted(self):
        """teardown_info with helm_release but no kubectl_resources → accepted."""
        req = CreateMigrationRequest(
            **MINIMAL_MIGRATION,
            teardown_info={"helm_release": "my-release", "helm_namespace": "default"},
        )
        assert req.teardown_info["helm_release"] == "my-release"

    @pytest.mark.parametrize("bad_item", [
        "--all",
        "-n default",
        "--delete-all",
        "",
        "kind/name; rm -rf /",
        "kind/name\nnewline",
        "kind/name extra extra",
    ])
    def test_malformed_resource_rejected(self, bad_item: str):
        """Malformed kubectl_resources element is rejected at schema boundary."""
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            CreateMigrationRequest(
                **MINIMAL_MIGRATION,
                teardown_info={"kubectl_resources": [bad_item]},
            )
