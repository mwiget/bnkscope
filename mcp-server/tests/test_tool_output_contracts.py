"""Focused MCP output contract truthfulness tests for governed tools.

Slice 7 scope (bounded):
- system tools backed by typed Tier-1 routes
- cluster_management Tier-1 typed read/mutate tools
- selected helm typed routes commonly used by operators

These tests verify MCP tool outputs remain truthful passthroughs of backend
response shape (including structured error envelopes).
"""

from __future__ import annotations

import json

import pytest

pytest.importorskip("mcp", reason="mcp package not installed in this test environment")

from bnkscope_mcp.tools.cluster_management import register as register_cluster
from bnkscope_mcp.tools.diagnostics_fleet import register as register_diagnostics
from bnkscope_mcp.tools.system import register as register_system

class _FakeMCP:
    def __init__(self) -> None:
        self.tools: dict[str, object] = {}

    def tool(self):
        def decorator(fn):
            self.tools[fn.__name__] = fn
            return fn

        return decorator

class _StubClient:
    def __init__(self, result: dict) -> None:
        self.result = result

    async def get(self, path: str, params=None):
        return self.result

    async def post(self, path: str, json=None, params=None):
        return self.result

    async def put(self, path: str, json=None, params=None):
        return self.result

    async def delete(self, path: str, params=None):
        return self.result

def _parse_tool_json(result: str) -> dict:
    parsed = json.loads(result)
    assert isinstance(parsed, dict)
    return parsed

@pytest.mark.asyncio
async def test_system_health_output_preserves_typed_contract_shape() -> None:
    payload = {
        "services": {
            "database": {"status": "healthy", "response_time_ms": 12.5, "error": None},
            "redis": {"status": "healthy", "response_time_ms": 4.2, "error": None},
        },
        "timestamp": "2026-03-27T17:00:00Z",
    }

    mcp = _FakeMCP()
    register_system(mcp, _StubClient(payload))

    parsed = _parse_tool_json(await mcp.tools["system_health"]())
    assert parsed == payload
    assert {"services", "timestamp"}.issubset(parsed.keys())

@pytest.mark.asyncio
async def test_system_settings_output_preserves_nested_settings_entries() -> None:
    payload = {
        "settings": {
            "general": [
                {
                    "key": "feature_x",
                    "value": "true",
                    "value_type": "bool",
                    "description": "feature toggle",
                    "is_encrypted": False,
                }
            ]
        }
    }

    mcp = _FakeMCP()
    register_system(mcp, _StubClient(payload))

    parsed = _parse_tool_json(await mcp.tools["system_settings"]())
    assert parsed == payload
    assert "settings" in parsed and "general" in parsed["settings"]

@pytest.mark.asyncio
async def test_cluster_resource_tools_preserve_envelope_fields() -> None:
    resource_list_payload = {
        "resources": [{"name": "nginx", "namespace": "default", "kind": "Deployment"}],
        "count": 1,
        "resource_type": "deployments",
        "namespace": "default",
        "cluster_id": 7,
    }
    describe_payload = {
        "name": "nginx",
        "namespace": "default",
        "kind": "Deployment",
        "metadata": {"name": "nginx"},
        "spec": {"replicas": 2},
        "status": {"readyReplicas": 2},
        "conditions": [{"type": "Available", "status": "True"}],
        "events": [],
        "relationships": {},
        "cluster_id": 7,
        "resource_type": "deployments",
        "resource_name": "nginx",
    }

    mcp = _FakeMCP()
    register_cluster(mcp, _StubClient(resource_list_payload))
    parsed_list = _parse_tool_json(
        await mcp.tools["list_resources"](cluster_id=7, resource_type="deployments", namespace="default")
    )
    assert parsed_list == resource_list_payload
    assert {"resources", "count", "resource_type", "cluster_id"}.issubset(parsed_list.keys())

    mcp2 = _FakeMCP()
    register_cluster(mcp2, _StubClient(describe_payload))
    parsed_describe = _parse_tool_json(
        await mcp2.tools["describe_resource"](
            cluster_id=7,
            resource_type="deployments",
            name="nginx",
            namespace="default",
        )
    )
    assert parsed_describe == describe_payload
    assert {"metadata", "spec", "status", "conditions", "events"}.issubset(parsed_describe.keys())

@pytest.mark.asyncio
async def test_cluster_logs_metrics_and_events_outputs_remain_stable() -> None:
    pod_logs_payload = {
        "logs": "line-1\nline-2",
        "pod_name": "tmm-0",
        "namespace": "f5-bnk",
        "cluster_id": 7,
        "container": "tmm",
    }
    events_payload = {
        "events": [{"type": "Warning", "reason": "BackOff", "message": "retrying"}],
        "count": 1,
        "cluster_id": 7,
        "namespace": "f5-bnk",
        "resource_type": None,
        "resource_name": None,
        "event_type": "Warning",
    }
    node_top_payload = {
        "available": True,
        "metrics": [{"name": "node-a", "cpu_millicores": 500}],
        "error": None,
        "cluster_id": 7,
        "sort_by": "cpu",
    }
    pod_top_payload = {
        "available": True,
        "metrics": [{"name": "pod-a", "namespace": "f5-bnk", "cpu_millicores": 10}],
        "error": None,
        "cluster_id": 7,
        "namespace": "f5-bnk",
        "sort_by": None,
    }

    for tool_name, kwargs, payload, required_keys in [
        ("get_pod_logs", {"cluster_id": 7, "pod_name": "tmm-0", "namespace": "f5-bnk"}, pod_logs_payload, {"logs", "pod_name", "namespace", "cluster_id"}),
        ("get_cluster_events", {"cluster_id": 7, "namespace": "f5-bnk", "limit": 50}, events_payload, {"events", "count", "cluster_id"}),
        ("get_node_metrics", {"cluster_id": 7}, node_top_payload, {"available", "metrics", "cluster_id"}),
        ("get_pod_metrics", {"cluster_id": 7, "namespace": "f5-bnk"}, pod_top_payload, {"available", "metrics", "cluster_id"}),
    ]:
        mcp = _FakeMCP()
        register_cluster(mcp, _StubClient(payload))
        parsed = _parse_tool_json(await mcp.tools[tool_name](**kwargs))
        assert parsed == payload
        assert required_keys.issubset(parsed.keys())

# ---------------------------------------------------------------------------
# Issue 2 — Normalized registration envelopes (breaking change, coordinated
# with awsbnkctl client). Both tools now return {success, <entity>, message?}
# instead of the prior inconsistent flat/bare shapes.
# ---------------------------------------------------------------------------
