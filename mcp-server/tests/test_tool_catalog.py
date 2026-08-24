"""Tests for machine-readable MCP governance tool catalog."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

# NOTE: `test_governed_auth_expectations_align_with_known_backend_dependencies`
# lived here. It asserted `require_admin` / `require_viewer` /
# `require_cluster_owner` decorators against a dozen backend route files —
# both the decorators and most of the files went with authentication in
# Phase 3, so the test was asserting bnk-forge's RBAC model on a tool that
# deliberately has none.
from bnk_forge_mcp.tool_catalog import (
    ALLOWED_AUTH_EXPECTATIONS,
    ALLOWED_TOOL_STABILITY,
    GOVERNED_MODULES,
    ToolRiskClass,
    get_high_risk_tool_catalog,
)

class _FakeMCP:
    def __init__(self) -> None:
        self.tools: dict[str, object] = {}

    def tool(self):
        def decorator(fn):
            self.tools[fn.__name__] = fn
            return fn

        return decorator

class _NoopClient:
    async def get(self, path: str, params=None):
        return {"path": path, "params": params}

    async def post(self, path: str, json=None, params=None):
        return {"path": path, "json": json, "params": params}

    async def put(self, path: str, json=None, params=None):
        return {"path": path, "json": json, "params": params}

    async def delete(self, path: str, params=None):
        return {"path": path, "params": params}

def _collect_registered_tools_by_module() -> dict[str, set[str]]:
    from bnk_forge_mcp.tools import (
        register_bnk_operations,
        register_cluster_management,
        register_diagnostics_fleet,
        register_system,
    )

    module_registrars = {
        "system": register_system,
        "cluster_management": register_cluster_management,
        "bnk_operations": register_bnk_operations,
        "diagnostics_fleet": register_diagnostics_fleet,
    }

    mcp = _FakeMCP()
    client = _NoopClient()
    by_module: dict[str, set[str]] = {}

    for module_name, registrar in module_registrars.items():
        before = set(mcp.tools.keys())
        registrar(mcp, client)
        after = set(mcp.tools.keys())
        by_module[module_name] = after - before

    return by_module

def _load_json_catalog() -> list[dict[str, object]]:
    catalog_path = Path(__file__).resolve().parents[1] / "tools" / "mcp_tool_catalog.json"
    return json.loads(catalog_path.read_text())

def test_catalog_json_matches_python_catalog() -> None:
    assert _load_json_catalog() == get_high_risk_tool_catalog()

def test_catalog_uses_allowed_risk_classes() -> None:
    allowed = {risk.value for risk in ToolRiskClass}
    catalog = _load_json_catalog()

    for entry in catalog:
        assert entry["risk_class"] in allowed

def test_catalog_uses_allowed_auth_expectations() -> None:
    allowed = set(ALLOWED_AUTH_EXPECTATIONS)
    catalog = _load_json_catalog()

    for entry in catalog:
        assert entry["auth_expectation"] in allowed

def test_catalog_uses_allowed_stability_values() -> None:
    allowed = set(ALLOWED_TOOL_STABILITY)
    catalog = _load_json_catalog()

    for entry in catalog:
        assert entry["stability"] in allowed

def test_catalog_entries_include_lifecycle_metadata() -> None:
    catalog = _load_json_catalog()

    for entry in catalog:
        assert str(entry.get("since_version", "")).strip(), (
            f"Catalog entry missing since_version: {entry['tool_name']}"
        )
        assert isinstance(entry.get("deprecated"), bool), (
            f"Catalog entry deprecated flag must be bool: {entry['tool_name']}"
        )
        replacement_tool = entry.get("replacement_tool")
        assert replacement_tool is None or isinstance(replacement_tool, str), (
            f"Catalog entry replacement_tool must be string|null: {entry['tool_name']}"
        )

def test_deprecated_entries_require_replacement_or_justification() -> None:
    catalog = _load_json_catalog()

    for entry in catalog:
        if entry.get("deprecated") is not True:
            continue
        replacement_tool = str(entry.get("replacement_tool") or "").strip()
        notes = str(entry.get("notes") or "").strip().lower()
        has_justification = "deprecated" in notes or "sunset" in notes
        assert replacement_tool or has_justification, (
            "Deprecated catalog entry must define replacement_tool or include "
            f"deprecation justification in notes: {entry['tool_name']}"
        )

def test_replacement_tool_semantics_are_coherent() -> None:
    """Replacement metadata must be actionable and internally consistent."""
    catalog = _load_json_catalog()
    tool_names = {str(entry["tool_name"]) for entry in catalog}

    for entry in catalog:
        tool_name = str(entry["tool_name"])
        deprecated = bool(entry.get("deprecated"))
        replacement_tool = str(entry.get("replacement_tool") or "").strip()

        if replacement_tool:
            assert replacement_tool in tool_names, (
                f"replacement_tool must reference a real catalog tool: {tool_name} -> {replacement_tool}"
            )
            assert replacement_tool != tool_name, (
                f"replacement_tool cannot point to itself: {tool_name}"
            )

        if not deprecated:
            assert not replacement_tool, (
                "Non-deprecated catalog entries must not define replacement_tool: "
                f"{tool_name}"
            )

def test_deprecated_entries_include_compatibility_guidance() -> None:
    """Deprecated entries should communicate compatibility/sunset expectations in notes."""
    catalog = _load_json_catalog()

    for entry in catalog:
        if entry.get("deprecated") is not True:
            continue

        notes = str(entry.get("notes") or "").strip().lower()
        replacement_tool = str(entry.get("replacement_tool") or "").strip().lower()

        assert "deprecated" in notes, (
            "Deprecated catalog notes must explicitly say deprecated: "
            f"{entry['tool_name']}"
        )

        has_window_language = any(token in notes for token in ("compatibility", "sunset", "removal"))
        has_replacement_mention = replacement_tool and replacement_tool in notes

        assert has_window_language or has_replacement_mention, (
            "Deprecated catalog notes must include compatibility/sunset guidance "
            "or explicitly mention replacement tool: "
            f"{entry['tool_name']}"
        )

def test_catalog_tools_are_registered_in_mcp_modules() -> None:
    pytest.importorskip("mcp", reason="mcp package not installed in this test environment")
    registered_by_module = _collect_registered_tools_by_module()
    registered = set().union(*registered_by_module.values())
    catalog_tools = {entry["tool_name"] for entry in _load_json_catalog()}
    missing = catalog_tools - registered
    assert not missing, f"Catalog includes unknown/unregistered tools: {missing}"

def test_governed_modules_have_full_catalog_coverage() -> None:
    """Governed modules must be fully represented in the catalog."""
    pytest.importorskip("mcp", reason="mcp package not installed in this test environment")

    registered_by_module = _collect_registered_tools_by_module()
    catalog = _load_json_catalog()

    for module_name in GOVERNED_MODULES:
        assert module_name in registered_by_module, f"Unknown governed module: {module_name}"

        catalog_tools_for_module = {
            str(entry["tool_name"]) for entry in catalog if str(entry["module"]) == module_name
        }
        registered_tools_for_module = registered_by_module[module_name]

        missing_from_catalog = registered_tools_for_module - catalog_tools_for_module
        assert not missing_from_catalog, (
            f"Governed module '{module_name}' has tools missing from catalog: "
            f"{sorted(missing_from_catalog)}"
        )

def test_governed_modules_have_non_empty_auth_expectations() -> None:
    catalog = _load_json_catalog()

    for entry in catalog:
        if str(entry["module"]) not in GOVERNED_MODULES:
            continue
        assert str(entry["auth_expectation"]).strip(), (
            "Governed-module entry has empty auth_expectation: "
            f"{entry['tool_name']} ({entry['module']})"
        )

def test_catalog_subset_aligns_with_url_audit_ground_truth() -> None:
    pytest.importorskip(
        "tests.test_url_audit",
        reason="url audit module unavailable in this test environment",
    )
    from tests.test_url_audit import EXPECTED_TOOLS

    for entry in _load_json_catalog():
        tool_name = str(entry["tool_name"])
        method = str(entry["http_method"])
        path = str(entry["backend_path_template"])

        assert tool_name in EXPECTED_TOOLS, f"Catalog tool missing from URL audit list: {tool_name}"
        expected_method, expected_path = EXPECTED_TOOLS[tool_name]
        assert method == expected_method
        assert path == expected_path
