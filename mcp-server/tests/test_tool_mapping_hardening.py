"""Tool mapping hardening tests for critical MCP tools."""

from __future__ import annotations

import json

import pytest

pytest.importorskip("mcp", reason="mcp package not installed in this test environment")

from bnkscope_mcp.tools.bnk_operations import register as register_bnk
from bnkscope_mcp.tools.cluster_management import register as register_cluster
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
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict]] = []

    async def get(self, path: str, params=None):
        self.calls.append(("GET", path, {"params": params}))
        return {"path": path, "params": params}

    async def post(self, path: str, json=None, params=None):
        self.calls.append(("POST", path, {"json": json, "params": params}))
        return {"path": path, "json": json, "params": params}

    async def put(self, path: str, json=None, params=None):
        self.calls.append(("PUT", path, {"json": json, "params": params}))
        return {"path": path, "json": json, "params": params}

    async def delete(self, path: str, params=None):
        self.calls.append(("DELETE", path, {"params": params}))
        return {"path": path, "params": params}
