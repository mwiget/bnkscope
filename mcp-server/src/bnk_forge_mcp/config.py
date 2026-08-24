"""
Configuration for the bnkscope MCP server.

Reads from environment variables with sensible defaults for Docker Compose deployment.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

@dataclass(frozen=True)
class MCPConfig:
    """MCP server configuration — all sourced from environment variables."""

    # bnkscope API connection. No credentials: the backend has no auth.
    api_base_url: str = field(default_factory=lambda: os.getenv("BNK_FORGE_API_URL", "http://127.0.0.1:8000"))
    api_timeout: int = field(default_factory=lambda: int(os.getenv("BNK_FORGE_API_TIMEOUT", "30")))
    verify_ssl: bool = field(default_factory=lambda: os.getenv("BNK_FORGE_VERIFY_SSL", "false").lower() == "true")

    # MCP server settings
    # Loopback by default. Compose overrides it where a published port needs
    # 0.0.0.0 inside the container; a bare default of 0.0.0.0 meant an
    # unauthenticated tool server on every interface if anyone ran it directly.
    host: str = field(default_factory=lambda: os.getenv("MCP_HOST", "127.0.0.1"))
    port: int = field(default_factory=lambda: int(os.getenv("MCP_PORT", "8081")))
    log_level: str = field(default_factory=lambda: os.getenv("MCP_LOG_LEVEL", "INFO"))

def load_config() -> MCPConfig:
    """Load configuration from environment."""
    return MCPConfig()
