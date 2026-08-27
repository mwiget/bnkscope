"""
Tests for MCP server configuration.
"""

from __future__ import annotations

from bnkscope_mcp.config import MCPConfig, load_config

def test_default_config() -> None:
    """A default config is enough to reach the backend.

    It was not: the client opened every request with a JWT gate, and a default
    config had no token, so all 30 tools answered
    `401 No token or credentials configured` before anything left the process.
    bnkscope has no authentication for them to satisfy.
    """
    config = MCPConfig()
    assert "8000" in config.api_base_url
    assert not hasattr(config, "api_token")
    assert not hasattr(config, "api_password")
    assert config.port == 8081
    # Loopback by default; compose overrides it where a published port
    # needs 0.0.0.0 inside the container.
    assert config.host == "127.0.0.1"
    assert config.log_level == "INFO"

def test_config_from_env(monkeypatch) -> None:
    """Config reads from environment variables."""
    monkeypatch.setenv("BNKSCOPE_API_URL", "http://custom:9000")
    monkeypatch.setenv("MCP_PORT", "9999")
    monkeypatch.setenv("MCP_LOG_LEVEL", "DEBUG")

    config = MCPConfig()

    assert config.api_base_url == "http://custom:9000"
    assert config.port == 9999
    assert config.log_level == "DEBUG"

def test_load_config() -> None:
    """load_config returns a valid MCPConfig."""
    config = load_config()
    assert isinstance(config, MCPConfig)
