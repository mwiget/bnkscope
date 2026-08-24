"""Tests for the destructive-tool confirmation gate (#65).

`risk_class` was catalog metadata only: observability logged it, nothing checked
it. The 16 `destructive` tools forwarded straight to the backend DELETE/POST and
relied entirely on backend RBAC -- and because the `mcp` service account is
role=admin, an autonomous agent could delete real projects and clusters with a
single call and no second factor.

These tests pin that the gate is enforced at runtime, that it is discoverable in
the tool schema (an agent can only satisfy a gate it can see), and that it does
not touch non-destructive tools.
"""

from __future__ import annotations

import inspect
import json
import logging

import pytest

from bnk_forge_mcp.observability import (
    ObservabilityMCPProxy,
    require_confirmation,
)
from bnk_forge_mcp.tool_catalog import ToolRiskClass, get_high_risk_tool_catalog


class _RecordingMCP:
    """Minimal stand-in for the FastMCP registrar."""

    def __init__(self) -> None:
        self.registered: dict[str, object] = {}
        self.meta: dict[str, dict] = {}

    def tool(self, *args, **kwargs):
        meta = kwargs.get("meta") or {}

        def _decorator(fn):
            self.registered[fn.__name__] = fn
            self.meta[fn.__name__] = meta
            return fn

        return _decorator


@pytest.mark.asyncio
async def test_destructive_tool_refuses_without_confirm() -> None:
    called: list[int] = []

    async def _impl(project_id: int) -> str:
        called.append(project_id)
        return json.dumps({"success": True})

    gated = require_confirmation(_impl, "delete_project")
    result = json.loads(await gated(88))

    assert result["ok"] is False
    assert result["error"]["code"] == "CONFIRMATION_REQUIRED"
    assert result["error"]["retryable"] is False
    assert called == [], "the destructive operation executed despite no confirmation"


@pytest.mark.asyncio
async def test_destructive_tool_executes_with_confirm() -> None:
    called: list[int] = []

    async def _impl(project_id: int) -> str:
        called.append(project_id)
        return json.dumps({"success": True})

    gated = require_confirmation(_impl, "delete_project")
    result = json.loads(await gated(88, confirm=True))

    assert result["success"] is True
    assert called == [88]


@pytest.mark.asyncio
async def test_confirm_is_visible_in_the_tool_signature() -> None:
    """The gate must be discoverable: FastMCP builds the schema from the signature."""

    async def _impl(project_id: int, force: bool = False) -> str:
        return "{}"

    gated = require_confirmation(_impl, "delete_project")
    sig = inspect.signature(gated)

    assert "confirm" in sig.parameters
    assert sig.parameters["confirm"].default is False
    assert sig.parameters["confirm"].annotation is bool
    # Original parameters survive untouched.
    assert "project_id" in sig.parameters
    assert "force" in sig.parameters
    assert "confirm" in (gated.__doc__ or "")


@pytest.mark.asyncio
async def test_gate_preserves_var_keyword_ordering() -> None:
    """confirm must sit before **kwargs, or the signature is invalid."""

    async def _impl(project_id: int, **extra) -> str:
        return json.dumps({"extra": extra})

    gated = require_confirmation(_impl, "delete_project")
    kinds = [p.kind for p in inspect.signature(gated).parameters.values()]
    assert kinds[-1] is inspect.Parameter.VAR_KEYWORD
    assert kinds[-2] is inspect.Parameter.KEYWORD_ONLY

    result = json.loads(await gated(1, confirm=True, note="hi"))
    assert result["extra"] == {"note": "hi"}


@pytest.mark.asyncio
async def test_blocked_call_is_logged_for_audit(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger="bnk_forge_mcp.observability")

    async def _impl() -> str:
        return "{}"

    gated = require_confirmation(_impl, "delete_cluster")
    await gated()

    assert '"event":"tool_invocation_blocked"' in caplog.text
    assert '"tool_name":"delete_cluster"' in caplog.text
    assert '"reason":"confirmation_required"' in caplog.text


@pytest.mark.asyncio
async def test_env_escape_hatch_disables_the_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    called: list[bool] = []

    async def _impl() -> str:
        called.append(True)
        return json.dumps({"success": True})

    gated = require_confirmation(_impl, "delete_project")
    monkeypatch.setenv("BNK_FORGE_MCP_REQUIRE_CONFIRMATION", "false")
    await gated()
    assert called == [True]

    # Default (unset) is enforced.
    called.clear()
    monkeypatch.delenv("BNK_FORGE_MCP_REQUIRE_CONFIRMATION")
    result = json.loads(await gated())
    assert result["error"]["code"] == "CONFIRMATION_REQUIRED"
    assert called == []


@pytest.mark.asyncio
async def test_proxy_leaves_read_only_tools_alone() -> None:
    """Registration-time wiring: a read-only tool gains no confirm parameter.

    The other half of this pair — a destructive tool gaining one — cannot be
    written any more: the shipped surface is read-only, so the catalog marks
    nothing destructive. `require_confirmation` is still exercised directly
    above, so the machinery stays covered for whenever a destructive tool
    comes back.
    """
    mcp = _RecordingMCP()
    proxy = ObservabilityMCPProxy(mcp, "cluster_management")

    @proxy.tool()
    async def list_clusters() -> str:
        return json.dumps({"clusters": []})

    assert "confirm" not in inspect.signature(mcp.registered["list_clusters"]).parameters


@pytest.mark.asyncio
async def test_gate_survives_the_instrumentation_wrapper(caplog: pytest.LogCaptureFixture) -> None:
    """FastMCP introspects the OUTER callable, so the gate must survive both wraps.

    require_confirmation sets __signature__ on its wrapper; instrument_tool then
    wraps that with functools.wraps, which sets __wrapped__ but not __signature__.
    inspect.signature must therefore follow the chain and still surface `confirm`
    -- otherwise the parameter never reaches the published tool schema and an
    agent has no way to satisfy the gate.
    """
    from bnk_forge_mcp.observability import instrument_tool

    async def delete_project(project_id: int, force: bool = False) -> str:
        """Delete a project."""
        return json.dumps({"success": True})

    gated = require_confirmation(delete_project, "delete_project")
    final = instrument_tool(
        "iac_operations", gated, risk_class="destructive", auth_expectation="admin"
    )

    sig = inspect.signature(final)
    assert "confirm" in sig.parameters
    assert sig.parameters["confirm"].kind is inspect.Parameter.KEYWORD_ONLY
    assert final.__name__ == "delete_project"
    # The description an agent reads must carry the requirement.
    assert "confirm=True" in (final.__doc__ or "")

    # And a blocked call is still classified as a failure by the outer telemetry,
    # not silently logged as a success.
    caplog.set_level(logging.INFO, logger="bnk_forge_mcp.observability")
    await final(88)
    assert '"error_class":"confirmation_required"' in caplog.text
    assert '"success":false' in caplog.text


def test_the_shipped_catalog_marks_nothing_destructive() -> None:
    """The strongest form of the gate: there is nothing to gate.

    This used to assert the 16 destructive tools were all catalogued, which was
    the right test when delete_cluster, drain_node and delete_project shipped.
    They no longer do — every tool is a GET on a route the backend serves — and
    this is what keeps one from being added back without a decision.
    """
    risky = [
        e["tool_name"]
        for e in get_high_risk_tool_catalog()
        if e["risk_class"] == ToolRiskClass.DESTRUCTIVE.value
    ]
    assert risky == [], f"MCP is documented read-only, but these mutate: {risky}"
