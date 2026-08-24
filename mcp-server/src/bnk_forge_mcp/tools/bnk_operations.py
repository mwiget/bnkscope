"""
F5 BNK (BIG-IP Next for Kubernetes) operations tools.

The core domain — BNK health, gateway topology, TMM debug, upgrades, licensing.
Maps to: routes/k8s/f5bnk.py, routes/k8s/tmm_debug.py, routes/bnk_upgrade.py,
         routes/licensing.py, routes/k8s/recovery.py
"""

from __future__ import annotations

import json
from typing import Any

from mcp.server.fastmcp import FastMCP

from ..client import BNKForgeClient

def register(mcp: FastMCP, client: BNKForgeClient) -> None:
    """Register F5 BNK operations tools with the MCP server."""

    # ------------------------------------------------------------------
    # BNK Data & Topology
    # ------------------------------------------------------------------

    @mcp.tool()
    async def bnk_data(cluster_id: int, namespace: str = "") -> str:
        """Get comprehensive F5 BNK data for a cluster.

        Fetches all 16 CRD types (Gateways, HTTPRoutes, GatewayClasses, Policies, etc.)
        in a single call and returns health analysis, topology graph, backend analysis,
        and policy associations.

        This is the primary tool for understanding the BNK state on a cluster.

        Args:
            cluster_id: The cluster ID
            namespace: Filter by namespace (empty for all BNK namespaces)
        """
        params: dict[str, Any] = {}
        if namespace:
            params["namespace"] = namespace
        result = await client.get(f"/api/k8s/clusters/{cluster_id}/f5bnk/data", params=params)
        return json.dumps(result, indent=2)

    @mcp.tool()
    async def bnk_gateway_topology(cluster_id: int) -> str:
        """Get the gateway topology graph for a BNK cluster.

        Returns a structured graph of GatewayClass → Gateway → HTTPRoute → Backend
        relationships, including listener configurations and route rules.

        Args:
            cluster_id: The cluster ID
        """
        result = await client.get(f"/api/k8s/clusters/{cluster_id}/f5bnk/gateway-topology")
        return json.dumps(result, indent=2)

    @mcp.tool()
    async def bnk_health(cluster_id: int) -> str:
        """Get F5 BNK health analysis for a cluster.

        Returns health scores, status of key components (controller, TMM, FLO),
        and any issues or warnings detected.

        Args:
            cluster_id: The cluster ID
        """
        result = await client.get(f"/api/k8s/clusters/{cluster_id}/f5bnk/health")
        return json.dumps(result, indent=2)

    @mcp.tool()
    async def bnk_policy_associations(cluster_id: int) -> str:
        """Get policy-to-gateway associations for a BNK cluster.

        Shows which WAF, rate-limit, access-control, and other policies
        are attached to which Gateways and HTTPRoutes.

        Args:
            cluster_id: The cluster ID
        """
        result = await client.get(f"/api/k8s/clusters/{cluster_id}/f5bnk/policy-gateway-associations")
        return json.dumps(result, indent=2)

    # ------------------------------------------------------------------
    # A2A Protocol Discovery
    # ------------------------------------------------------------------

    @mcp.tool()
    async def a2a_discover_agents(cluster_id: int, probe: bool = False) -> str:
        """Discover A2A (Agent-to-Agent) protocol agents behind BNK HTTPRoutes.

        Scans HTTPRoutes for backend services and optionally probes each
        for the standard /.well-known/agent-card.json endpoint.

        Args:
            cluster_id: The cluster ID
            probe: If True, actively probe each service for agent cards (slower but more accurate)
        """
        params: dict[str, Any] = {}
        if probe:
            params["probe"] = "true"
        result = await client.get(f"/api/k8s/clusters/{cluster_id}/f5bnk/a2a/agents", params=params)
        return json.dumps(result, indent=2)

    # ------------------------------------------------------------------
    # TMM Debug
    # ------------------------------------------------------------------

    @mcp.tool()
    async def tmm_list_pods(cluster_id: int) -> str:
        """List all TMM (Traffic Management Microkernel) pods on a BNK cluster.

        Returns pod names, namespaces, status, and available debug commands.

        Args:
            cluster_id: The cluster ID
        """
        result = await client.get(f"/api/k8s/clusters/{cluster_id}/tmm-debug/pods")
        return json.dumps(result, indent=2)

    @mcp.tool()
    async def tmm_configview(
        cluster_id: int,
        pod_name: str,
        namespace: str = "",
    ) -> str:
        """Get the TMM configuration view (configview list) from a TMM pod.

        Shows all configured virtual servers, pools, and their UUIDs.

        Args:
            cluster_id: The cluster ID
            pod_name: TMM pod name
            namespace: Pod namespace (auto-detected if empty)
        """
        body: dict[str, Any] = {"pod_name": pod_name}
        if namespace:
            body["namespace"] = namespace
        result = await client.post(f"/api/k8s/clusters/{cluster_id}/tmm-debug/configview", json=body)
        return json.dumps(result, indent=2)

    # ------------------------------------------------------------------
    # BNK Upgrades
    # ------------------------------------------------------------------

    @mcp.tool()
    async def bnk_recovery_status(cluster_id: int) -> str:
        """Check the recovery status of a BNK cluster.

        Args:
            cluster_id: The cluster ID
        """
        result = await client.get(f"/api/k8s/clusters/{cluster_id}/recovery/status")
        return json.dumps(result, indent=2)
