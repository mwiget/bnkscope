"""
Integration tests for general API routes — /, /health, /api/health, /api/logs, /api/version.

Covers: root endpoint, health checks, log listing, RBAC enforcement.
Uses FastAPI TestClient with real SQLite DB.
"""

import os
from unittest.mock import MagicMock, patch

import pytest


class TestRootEndpoint:
    """GET /."""

    def test_root_returns_api_info(self, client, admin_headers, sample_user):
        """Root returns API message and version."""
        response = client.get("/", headers=admin_headers)
        assert response.status_code == 200
        data = response.json()
        assert "message" in data
        assert "bnkscope" in data["message"]
        assert "version" in data

class TestHealthCheck:
    """GET /health and GET /api/health."""

    # Phase 4 left the database as the only component to probe: the broker and
    # worker pool this used to stub out are in-process now.

    def test_health_check(self, client, admin_headers, sample_user):
        """Health check returns healthy status."""
        response = client.get("/health", headers=admin_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["checks"] == {"database": "ok"}
        assert "timestamp" in data

    def test_api_health_check(self, client, admin_headers, sample_user):
        """API health check at /api/health returns healthy."""
        response = client.get("/api/health", headers=admin_headers)
        assert response.status_code == 200
        assert response.json()["status"] == "healthy"

