"""
System & authentication tools.

Tools for checking system health, version info, and managing the connection.
Maps to: routes/system.py, routes/api.py, routes/auth.py
"""

from __future__ import annotations

import json

from mcp.server.fastmcp import FastMCP

from ..client import BnkscopeClient

def register(mcp: FastMCP, client: BnkscopeClient) -> None:
    """Register system tools with the MCP server."""

    @mcp.tool()
    async def system_health() -> str:
        """Get bnkscope system health status.

        Returns the health of all services (database, Redis, Celery workers),
        resource counts, and system version information.
        """
        result = await client.get("/api/system/health")
        return json.dumps(result, indent=2)

    @mcp.tool()
    async def system_settings() -> str:
        """Get current bnkscope system settings.

        Returns all configurable settings including defaults, feature flags,
        and environment configuration.
        """
        result = await client.get("/api/settings")
        return json.dumps(result, indent=2)
