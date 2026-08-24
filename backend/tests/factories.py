"""
Factory Boy factories for bnkscope backend models.

Provides consistent, composable test data factories for all major models.
Each factory creates minimal valid objects with sensible defaults.
Use factory traits or explicit overrides for specific test scenarios.

Usage:
    from tests.factories import KubernetesClusterFactory

    cluster = KubernetesClusterFactory(db, name="prod")
"""

from datetime import datetime, timezone

from models import KubernetesCluster

# ---------------------------------------------------------------------------
# Sequence counters for unique values
# ---------------------------------------------------------------------------

_counters: dict[str, int] = {}


def _next_seq(name: str) -> int:
    """Thread-unsafe sequence counter (fine for tests)."""
    _counters[name] = _counters.get(name, 0) + 1
    return _counters[name]


def reset_sequences():
    """Reset all sequence counters. Call between test sessions if needed."""
    _counters.clear()


# ---------------------------------------------------------------------------
# User Factory
# ---------------------------------------------------------------------------
# Project Factory
# ---------------------------------------------------------------------------
# KubernetesCluster Factory
# ---------------------------------------------------------------------------

def KubernetesClusterFactory(
    db,
    *,
    name: str | None = None,
    context: str | None = None,
    api_server: str | None = None,
    cluster_type: str = "generic",
    status: str = "active",
    version: str = "1.28",
    **kwargs,
) -> KubernetesCluster:
    """Create a KubernetesCluster."""
    n = _next_seq("k8s_cluster")
    cluster = KubernetesCluster(
        name=name or f"test-cluster-{n}",
        context=context or f"test-context-{n}",
        api_server=api_server or f"https://k8s-{n}.example.com:6443",
        status=status,
        version=version,
        **kwargs,
    )
    db.add(cluster)
    db.flush()
    return cluster


# ---------------------------------------------------------------------------
# BenchmarkTarget Factory
# ---------------------------------------------------------------------------
# ProxyDeployment Factory (Phase 1.6 — includes lock columns at defaults)
# ---------------------------------------------------------------------------
# BnkUpgrade Factory (Phase 1.6 — includes lock columns at defaults)
