"""
Diagnostics and fleet management tools.

QKView diagnostics, fleet health, drift detection, snapshots, and runbooks.
Maps to: routes/qkview.py, routes/operators/fleet.py, routes/drift.py,
         routes/snapshots.py, routes/runbooks.py, routes/k8s/dpf.py
"""

from __future__ import annotations

import json
from typing import Any

from mcp.server.fastmcp import FastMCP

from ..client import BnkscopeClient

def register(mcp: FastMCP, client: BnkscopeClient) -> None:
    """Register diagnostics and fleet tools with the MCP server."""

    def _augment_fleet_platform_guidance(result: dict) -> dict:
        """Add MCP-side guidance from backend fleet platform context."""
        if not isinstance(result, dict):
            return result

        platform_context = result.get("platform_context")
        if not isinstance(platform_context, dict):
            return result

        if platform_context.get("mixed_platform_profiles") is True:
            guidance = list(result.get("mcp_guidance", [])) if isinstance(result.get("mcp_guidance"), list) else []
            caveats = platform_context.get("comparison_caveats")
            if isinstance(caveats, list) and caveats:
                guidance.append(caveats[0])
            guidance.append(
                "Fleet summaries span mixed platform profiles; treat status comparisons as platform-context-aware, not universally equivalent."
            )
            result["mcp_guidance"] = guidance

        return result

    # ------------------------------------------------------------------
    # QKView Diagnostics
    # ------------------------------------------------------------------

    @mcp.tool()
    async def qkview_list(cluster_id: int) -> str:
        """List available QKView diagnostic files for a cluster.

        Args:
            cluster_id: The cluster ID
        """
        result = await client.get("/api/qkview/list", params={"cluster_id": cluster_id})
        return json.dumps(result, indent=2)

    @mcp.tool()
    async def qkview_status(cluster_id: int, qkview_id: int) -> str:
        """Check the status of a specific QKView operation.

        Shows if the QKView is being created, completed, or failed.

        Args:
            cluster_id: The cluster ID
            qkview_id: The QKView ID (from qkview_create)
        """
        result = await client.get(f"/api/qkview/{qkview_id}/status", params={"cluster_id": cluster_id})
        return json.dumps(result, indent=2)

    @mcp.tool()
    async def cluster_connectivity(cluster_id: int) -> str:
        """Probe network connectivity to a Kubernetes cluster.

        Tests ICMP (ping), TCP port reachability, and K8s API accessibility.
        Returns a diagnostic status with actionable suggestions.

        Status values: healthy, reachable, port_blocked, unreachable, unknown.

        Args:
            cluster_id: The cluster ID to probe
        """
        result = await client.get(f"/api/k8s/clusters/{cluster_id}/connectivity")
        return json.dumps(result, indent=2)

    @mcp.tool()
    async def cluster_connectivity_batch() -> str:
        """Probe connectivity to all registered clusters in parallel.

        Returns per-cluster connectivity status plus a summary.
        Useful for quickly identifying unreachable or firewall-blocked clusters.
        """
        result = await client.get("/api/k8s/clusters/connectivity")
        return json.dumps(result, indent=2)

    # ------------------------------------------------------------------
    # Drift Detection
    # ------------------------------------------------------------------

    @mcp.tool()
    async def dpf_detect(cluster_id: int) -> str:
        """Detect NVIDIA DPF (DPU Framework) CRDs on a cluster.

        Checks for DPF installation and available DPU resources.

        Args:
            cluster_id: The cluster ID
        """
        result = await client.get(f"/api/k8s/clusters/{cluster_id}/dpf/detect")
        return json.dumps(result, indent=2)

    @mcp.tool()
    async def dpf_data(cluster_id: int) -> str:
        """Get DPF data including DPU devices, clusters, and services.

        Args:
            cluster_id: The cluster ID
        """
        result = await client.get(f"/api/k8s/clusters/{cluster_id}/dpf/data")
        return json.dumps(result, indent=2)

    @mcp.tool()
    async def dpf_health(cluster_id: int) -> str:
        """Get DPF health status for a cluster.

        Args:
            cluster_id: The cluster ID
        """
        result = await client.get(f"/api/k8s/clusters/{cluster_id}/dpf/health")
        return json.dumps(result, indent=2)

    # ------------------------------------------------------------------
    # Alert Channels
    # ------------------------------------------------------------------

    @mcp.tool()
    async def list_alert_channels() -> str:
        """List configured alert channels (Slack, email, webhook)."""
        result = await client.get("/api/alert-channels")
        return json.dumps(result, indent=2)
