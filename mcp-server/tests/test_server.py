"""
Tests for MCP server creation and tool registration.

Verifies all tool modules are registered correctly with the expected tool names.
"""

from __future__ import annotations

import pytest

from bnk_forge_mcp.config import MCPConfig
from bnk_forge_mcp.observability import ObservabilityMCPProxy

pytest.importorskip("mcp", reason="mcp package not installed in this test environment")

from bnk_forge_mcp.server import create_server

@pytest.fixture
def config() -> MCPConfig:
    return MCPConfig(
        api_base_url="http://test:8000",
        api_timeout=5,
        verify_ssl=False,
    )

def test_server_creates_successfully(config: MCPConfig) -> None:
    """Server creates without error."""
    mcp = create_server(config)
    assert mcp is not None
    assert mcp.name == "BNK-Forge"

def test_server_has_instructions(config: MCPConfig) -> None:
    """Server has helpful instructions for AI assistants."""
    mcp = create_server(config)
    assert mcp.instructions is not None
    assert "BNK-Forge" in mcp.instructions
    assert "system_health" in mcp.instructions

def test_all_system_tools_registered(config: MCPConfig) -> None:
    """System tools are registered."""
    mcp = create_server(config)
    tool_names = {t.name for t in mcp._tool_manager.list_tools()}

    expected = {
        "system_health",
        "system_settings",
    }
    assert expected.issubset(tool_names), f"Missing system tools: {expected - tool_names}"

def test_all_cluster_tools_registered(config: MCPConfig) -> None:
    """Cluster management tools are registered."""
    mcp = create_server(config)
    tool_names = {t.name for t in mcp._tool_manager.list_tools()}

    expected = {
        "list_clusters",
        "get_cluster",
        "list_namespaces",
        "list_resources",
        "get_resource",
        "get_pod_logs",
        "describe_resource",
        "get_cluster_events",
        "get_node_metrics",
        "get_pod_metrics",
    }
    assert expected.issubset(tool_names), f"Missing cluster tools: {expected - tool_names}"

def test_all_bnk_tools_registered(config: MCPConfig) -> None:
    """BNK operations tools are registered."""
    mcp = create_server(config)
    tool_names = {t.name for t in mcp._tool_manager.list_tools()}

    expected = {
        "bnk_data",
        "bnk_gateway_topology",
        "bnk_health",
        "bnk_policy_associations",
        "a2a_discover_agents",
        "tmm_list_pods",
        "tmm_configview",
        "bnk_recovery_status",
    }
    assert expected.issubset(tool_names), f"Missing BNK tools: {expected - tool_names}"

def test_all_diagnostics_fleet_tools_registered(config: MCPConfig) -> None:
    """Diagnostics and fleet tools are registered."""
    mcp = create_server(config)
    tool_names = {t.name for t in mcp._tool_manager.list_tools()}

    expected = {
        "qkview_list",
        "qkview_status",
        "dpf_detect",
        "dpf_data",
        "dpf_health",
        "list_alert_channels",
    }
    assert expected.issubset(tool_names), f"Missing diagnostics tools: {expected - tool_names}"

def test_total_tool_count(config: MCPConfig) -> None:
    """Verify we have the expected number of tools registered."""
    mcp = create_server(config)
    tools = mcp._tool_manager.list_tools()
    tool_count = len(tools)

    # Read-only surface: every tool is a GET on a route the backend serves.
    # It was ~150 when the catalog still carried helm, IaC and cloud-auth
    # tools whose endpoints had already been deleted — 94 of them 404'd.
    # A range, not an exact count, so adding a read does not fail the suite.
    assert 25 <= tool_count <= 60, f"Expected 25-60 tools, got {tool_count}"

    # Print for visibility
    print(f"\nTotal MCP tools registered: {tool_count}")
    for t in sorted(tools, key=lambda t: t.name):
        print(f"  • {t.name}")

def test_observability_proxy_preserves_tool_names() -> None:
    class _FakeMCP:
        def __init__(self) -> None:
            self.tools: dict[str, object] = {}

        def tool(self, *args, **kwargs):
            def decorator(fn):
                self.tools[fn.__name__] = fn
                return fn

            return decorator

    mcp = _FakeMCP()
    proxy = ObservabilityMCPProxy(mcp, "system")

    @proxy.tool()
    async def sample_tool() -> str:
        return "ok"

    assert "sample_tool" in mcp.tools
