"""
Kubernetes cluster management tools.

Tools for managing clusters, browsing resources, and K8s operations.
Maps to: routes/k8s/clusters.py, routes/k8s/resources.py, routes/k8s/tunnels.py
"""

from __future__ import annotations

import json
from typing import Any

from mcp.server.fastmcp import FastMCP

from ..client import BNKForgeClient

def register(mcp: FastMCP, client: BNKForgeClient) -> None:
    """Register cluster management tools with the MCP server."""

    # ------------------------------------------------------------------
    # Cluster CRUD
    # ------------------------------------------------------------------

    @mcp.tool()
    async def list_clusters() -> str:
        """List all Kubernetes clusters registered in BNK-Forge.

        Returns cluster names, IDs, connectivity status, and BNK installation status.
        """
        result = await client.get("/api/k8s/clusters")
        return json.dumps(result, indent=2)

    @mcp.tool()
    async def get_cluster(cluster_id: int) -> str:
        """Get detailed information about a specific Kubernetes cluster.

        Args:
            cluster_id: The cluster ID
        """
        result = await client.get(f"/api/k8s/clusters/{cluster_id}")
        return json.dumps(result, indent=2)

    @mcp.tool()
    async def list_namespaces(cluster_id: int) -> str:
        """List all namespaces in a Kubernetes cluster.

        Args:
            cluster_id: The cluster ID
        """
        result = await client.get(f"/api/k8s/clusters/{cluster_id}/namespaces")
        return json.dumps(result, indent=2)

    # ------------------------------------------------------------------
    # K8s Resources (generic)
    # ------------------------------------------------------------------

    @mcp.tool()
    async def list_resources(
        cluster_id: int,
        resource_type: str,
        namespace: str = "",
    ) -> str:
        """List Kubernetes resources of a given type.

        Supports any K8s resource type: pods, deployments, services, configmaps,
        secrets, gateways, httproutes, etc.

        Args:
            cluster_id: The cluster ID
            resource_type: K8s resource type (e.g. "pods", "deployments", "services", "gateways", "httproutes")
            namespace: Namespace to filter by (empty for all namespaces)
        """
        params: dict[str, Any] = {}
        if namespace:
            params["namespace"] = namespace
        result = await client.get(f"/api/k8s/clusters/{cluster_id}/resources/{resource_type}", params=params)
        return json.dumps(result, indent=2)

    @mcp.tool()
    async def get_resource(
        cluster_id: int,
        resource_type: str,
        name: str,
        namespace: str = "default",
    ) -> str:
        """Get a specific Kubernetes resource by name.

        Args:
            cluster_id: The cluster ID
            resource_type: K8s resource type (e.g. "pods", "deployments", "services")
            name: Resource name
            namespace: Resource namespace (default: "default")
        """
        params: dict[str, Any] = {"namespace": namespace}
        result = await client.get(f"/api/k8s/clusters/{cluster_id}/resources/{resource_type}/{name}/describe", params=params)
        return json.dumps(result, indent=2)

    @mcp.tool()
    async def get_pod_logs(
        cluster_id: int,
        pod_name: str,
        namespace: str = "default",
        container: str = "",
        tail_lines: int = 100,
    ) -> str:
        """Get logs from a Kubernetes pod.

        Args:
            cluster_id: The cluster ID
            pod_name: Name of the pod
            namespace: Pod namespace (default: "default")
            container: Specific container name (empty for default container)
            tail_lines: Number of lines from the end (default 100)
        """
        params: dict[str, Any] = {
            "namespace": namespace,
            "tail_lines": tail_lines,
        }
        if container:
            params["container"] = container
        result = await client.get(f"/api/k8s/clusters/{cluster_id}/pods/{pod_name}/logs", params=params)
        return json.dumps(result, indent=2)

    @mcp.tool()
    async def describe_resource(
        cluster_id: int,
        resource_type: str,
        name: str,
        namespace: str = "default",
    ) -> str:
        """Describe a Kubernetes resource (similar to kubectl describe).

        Returns detailed information including events, conditions, and status.

        Args:
            cluster_id: The cluster ID
            resource_type: K8s resource type
            name: Resource name
            namespace: Resource namespace (default: "default")
        """
        params: dict[str, Any] = {"namespace": namespace}
        result = await client.get(f"/api/k8s/clusters/{cluster_id}/resources/{resource_type}/{name}/describe", params=params)
        return json.dumps(result, indent=2)

    @mcp.tool()
    async def get_cluster_events(
        cluster_id: int,
        namespace: str = "",
        limit: int = 50,
    ) -> str:
        """Get recent events from a Kubernetes cluster.

        Useful for troubleshooting — shows warnings, errors, and state changes.

        Args:
            cluster_id: The cluster ID
            namespace: Filter by namespace (empty for all)
            limit: Maximum number of events (default 50)
        """
        params: dict[str, Any] = {"limit": limit}
        if namespace:
            params["namespace"] = namespace
        result = await client.get(f"/api/k8s/clusters/{cluster_id}/events", params=params)
        return json.dumps(result, indent=2)

    @mcp.tool()
    async def get_node_metrics(cluster_id: int) -> str:
        """Get node resource usage (CPU, memory) for a cluster.

        Equivalent to 'kubectl top nodes'. Requires metrics-server installed.

        Args:
            cluster_id: The cluster ID
        """
        result = await client.get(f"/api/k8s/clusters/{cluster_id}/top/nodes")
        return json.dumps(result, indent=2)

    @mcp.tool()
    async def get_pod_metrics(
        cluster_id: int,
        namespace: str = "",
    ) -> str:
        """Get pod resource usage (CPU, memory) for a cluster.

        Equivalent to 'kubectl top pods'. Requires metrics-server installed.

        Args:
            cluster_id: The cluster ID
            namespace: Filter by namespace (empty for all)
        """
        params: dict[str, Any] = {}
        if namespace:
            params["namespace"] = namespace
        result = await client.get(f"/api/k8s/clusters/{cluster_id}/top/pods", params=params)
        return json.dumps(result, indent=2)

    @mcp.tool()
    async def rollout_history(
        cluster_id: int,
        deployment_name: str,
        namespace: str = "default",
    ) -> str:
        """Get the revision history of a deployment (kubectl rollout history).

        Args:
            cluster_id: Target cluster.
            deployment_name: Deployment name.
            namespace: Deployment namespace (default "default").
        """
        result = await client.get(
            f"/api/k8s/clusters/{cluster_id}/deployments/{deployment_name}/rollout/history",
            params={"namespace": namespace},
        )
        return json.dumps(result, indent=2)

    @mcp.tool()
    async def rollout_status(
        cluster_id: int,
        deployment_name: str,
        namespace: str = "default",
    ) -> str:
        """Check rollout status for a deployment (kubectl rollout status).

        Returns whether the deployment is progressing, complete, or stuck.

        Args:
            cluster_id: Target cluster.
            deployment_name: Deployment name.
            namespace: Deployment namespace (default "default").
        """
        result = await client.get(
            f"/api/k8s/clusters/{cluster_id}/deployments/{deployment_name}/rollout/status",
            params={"namespace": namespace},
        )
        return json.dumps(result, indent=2)
