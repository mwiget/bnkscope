"""
URL audit tests for MCP tool endpoints.

Ensures every MCP tool URL maps to a real backend route.
When adding new MCP tools, add the expected METHOD + URL here.
When adding new backend routes, consider adding an MCP tool.

Run: pytest tests/test_url_audit.py -v
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Ground truth: every MCP tool → (METHOD, URL_PATTERN)
# Update this whenever you add/modify MCP tools.
# ---------------------------------------------------------------------------

EXPECTED_TOOLS: dict[str, tuple[str, str]] = {
    # system.py
    "system_health": ("GET", "/api/system/health"),
    "system_settings": ("GET", "/api/settings"),
    # cluster_management.py
    "list_clusters": ("GET", "/api/k8s/clusters"),
    "get_cluster": ("GET", "/api/k8s/clusters/{cluster_id}"),
    "list_namespaces": ("GET", "/api/k8s/clusters/{cluster_id}/namespaces"),
    "rollout_history": ("GET", "/api/k8s/clusters/{cluster_id}/deployments/{deployment_name}/rollout/history"),
    "rollout_status": ("GET", "/api/k8s/clusters/{cluster_id}/deployments/{deployment_name}/rollout/status"),
    "list_resources": ("GET", "/api/k8s/clusters/{cluster_id}/resources/{resource_type}"),
    "get_resource": ("GET", "/api/k8s/clusters/{cluster_id}/resources/{resource_type}/{name}/describe"),
    "get_pod_logs": ("GET", "/api/k8s/clusters/{cluster_id}/pods/{pod_name}/logs"),
    "describe_resource": ("GET", "/api/k8s/clusters/{cluster_id}/resources/{resource_type}/{name}/describe"),
    "get_cluster_events": ("GET", "/api/k8s/clusters/{cluster_id}/events"),
    "get_node_metrics": ("GET", "/api/k8s/clusters/{cluster_id}/top/nodes"),
    "get_pod_metrics": ("GET", "/api/k8s/clusters/{cluster_id}/top/pods"),
    # bnk_operations.py
    "bnk_data": ("GET", "/api/k8s/clusters/{cluster_id}/f5bnk/data"),
    "bnk_gateway_topology": ("GET", "/api/k8s/clusters/{cluster_id}/f5bnk/gateway-topology"),
    "bnk_health": ("GET", "/api/k8s/clusters/{cluster_id}/f5bnk/health"),
    "bnk_policy_associations": ("GET", "/api/k8s/clusters/{cluster_id}/f5bnk/policy-gateway-associations"),
    "a2a_discover_agents": ("GET", "/api/k8s/clusters/{cluster_id}/f5bnk/a2a/agents"),
    "tmm_list_pods": ("GET", "/api/k8s/clusters/{cluster_id}/tmm-debug/pods"),
    "tmm_configview": ("POST", "/api/k8s/clusters/{cluster_id}/tmm-debug/configview"),
    "bnk_recovery_status": ("GET", "/api/k8s/clusters/{cluster_id}/recovery/status"),
    # diagnostics_fleet.py
    "qkview_list": ("GET", "/api/qkview/list"),
    "qkview_status": ("GET", "/api/qkview/{qkview_id}/status"),
    "cluster_connectivity": ("GET", "/api/k8s/clusters/{cluster_id}/connectivity"),
    "cluster_connectivity_batch": ("GET", "/api/k8s/clusters/connectivity"),
    "dpf_detect": ("GET", "/api/k8s/clusters/{cluster_id}/dpf/detect"),
    "dpf_data": ("GET", "/api/k8s/clusters/{cluster_id}/dpf/data"),
    "dpf_health": ("GET", "/api/k8s/clusters/{cluster_id}/dpf/health"),
    "list_alert_channels": ("GET", "/api/alert-channels"),
    # config_management.py
}


def _normalize_path(path: str) -> str:
    """Replace {param_name} with {X} for comparison."""
    return re.sub(r"\{[^}]+\}", "{X}", path)


def _extract_backend_routes() -> set[tuple[str, str]]:
    """
    Parse all backend/routes/**/*.py files and return (METHOD, normalized_path) tuples.

    Handles:
    - Routes with prefix in APIRouter(prefix="...")
    - Routes with empty string "" or "/" meaning "the prefix itself"
    - Multiple routers in same file (router, public_router, ws_router, etc.)
    - Nested packages where sub-router files have no prefix but
      the parent __init__.py assembles them under a shared prefix
      (e.g. operators/__init__.py → prefix="/api/operators", sub-files have no prefix)
    """
    # Match any `foo = APIRouter(...)` declaration
    prefix_pat = re.compile(r"(\w+)\s*=\s*APIRouter\s*\(([^)]*)\)")
    prefix_val_pat = re.compile(r"prefix\s*=\s*[\"']([^\"']*)[\"']")
    # Match @foo.get("/path"), @foo.post("/path"), etc.
    route_pat = re.compile(
        r"@(\w+)\.(get|post|put|delete|patch)\s*\(\s*[\"']([^\"']*)[\"']",
        re.IGNORECASE,
    )

    backend_root = Path(__file__).resolve().parents[2] / "backend" / "routes"
    routes: set[tuple[str, str]] = set()

    # ---------------------------------------------------------------
    # Phase 1: Discover package-level prefixes from __init__.py files
    # e.g. operators/__init__.py defines router = APIRouter(prefix="/api/operators")
    # and include_router(crud_router), so crud.py routes inherit that prefix.
    # ---------------------------------------------------------------
    package_prefixes: dict[str, str] = {}  # dir path str → prefix
    for init_file in backend_root.rglob("__init__.py"):
        content = init_file.read_text()
        for m in prefix_pat.finditer(content):
            args = m.group(2)
            pv = prefix_val_pat.search(args)
            if pv and pv.group(1):
                # This package assembles sub-routers under this prefix
                package_prefixes[str(init_file.parent)] = pv.group(1)

    # ---------------------------------------------------------------
    # Phase 2: Extract routes from every .py file (skip __init__.py, __pycache__)
    # ---------------------------------------------------------------
    for py_file in backend_root.rglob("*.py"):
        if py_file.name.startswith("__"):
            continue
        content = py_file.read_text()

        # Build map of router_name -> prefix for this file
        router_prefixes: dict[str, str] = {}
        for m in prefix_pat.finditer(content):
            router_name = m.group(1).lower()
            args = m.group(2)
            pv = prefix_val_pat.search(args)
            router_prefixes[router_name] = pv.group(1) if pv else ""

        # Determine package-level prefix for sub-router files
        # (applies when the file's own router has no prefix)
        pkg_prefix = package_prefixes.get(str(py_file.parent), "")

        for m in route_pat.finditer(content):
            router_name = m.group(1).lower()
            method = m.group(2).upper()
            path = m.group(3)

            # Get prefix for this specific router variable
            file_prefix = router_prefixes.get(router_name, "")

            # If the file's router has no prefix, inherit package prefix
            prefix = file_prefix if file_prefix else pkg_prefix

            # Resolve full path
            if path in ("", "/"):
                full = prefix if prefix else "/"
            elif path.startswith("/api"):
                # Absolute path already includes /api — use as-is
                full = path
            else:
                full = prefix + path

            # Clean up
            full = full.replace("//", "/")
            if full and not full.startswith("/"):
                full = "/" + full

            if full and full != "/":  # Skip root-only routes
                routes.add((method, _normalize_path(full)))

    return routes


# Cache backend routes for the whole test session
_BACKEND_ROUTES: set[tuple[str, str]] | None = None


def get_backend_routes() -> set[tuple[str, str]]:
    global _BACKEND_ROUTES
    if _BACKEND_ROUTES is None:
        _BACKEND_ROUTES = _extract_backend_routes()
    return _BACKEND_ROUTES


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestMCPToolURLs:
    """Verify every MCP tool URL matches a real backend route."""

    @pytest.fixture(autouse=True)
    def _load_routes(self) -> None:
        self.backend = get_backend_routes()

    @pytest.mark.parametrize("tool_name", sorted(EXPECTED_TOOLS.keys()))
    def test_tool_url_exists_in_backend(self, tool_name: str) -> None:
        """Each MCP tool must map to an actual backend route."""
        method, url = EXPECTED_TOOLS[tool_name]
        norm = _normalize_path(url)
        assert (method, norm) in self.backend, (
            f"MCP tool '{tool_name}' points to {method} {url} "
            f"which does NOT exist in backend routes"
        )

    def test_no_duplicate_tool_urls(self) -> None:
        """No two MCP tools should call the exact same endpoint (except describe/get_resource)."""
        seen: dict[tuple[str, str], str] = {}
        duplicates: list[str] = []
        # Known intentional duplicates
        known_dupes = {("GET", "/api/k8s/clusters/{X}/resources/{X}/{X}/describe")}

        for tool_name, (method, url) in EXPECTED_TOOLS.items():
            key = (method, _normalize_path(url))
            if key in seen and key not in known_dupes:
                duplicates.append(f"  {tool_name} and {seen[key]} both use {method} {url}")
            seen[key] = tool_name

        assert not duplicates, f"Duplicate tool URLs found:\n" + "\n".join(duplicates)

    def test_tool_count_matches_registered(self) -> None:
        """The audit list should match the number of tools actually registered."""
        pytest.importorskip("bnkscope_mcp", reason="bnkscope_mcp not installed (requires Python >=3.11)")
        pytest.importorskip("mcp", reason="mcp package not installed in this test environment")
        from bnkscope_mcp.config import MCPConfig
        from bnkscope_mcp.server import create_server

        config = MCPConfig(
            api_base_url="http://test:8000",
            api_timeout=5,
            verify_ssl=False,
        )
        mcp = create_server(config)
        registered = {t.name for t in mcp._tool_manager.list_tools()}
        audit = set(EXPECTED_TOOLS.keys())

        missing_from_audit = registered - audit
        extra_in_audit = audit - registered

        assert not missing_from_audit, f"Tools registered but NOT in audit: {missing_from_audit}"
        assert not extra_in_audit, f"Tools in audit but NOT registered: {extra_in_audit}"

    def test_backend_route_extraction_works(self) -> None:
        """Sanity check: we can extract backend routes."""
        assert len(self.backend) > 100, f"Expected >100 backend routes, got {len(self.backend)}"
