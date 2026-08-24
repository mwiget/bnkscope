"""
F5 BNK (BIG-IP Next for Kubernetes) routes.

All insight views (Health, Topology, Policy Map) are powered by a single
unified data fetch via bnk_data_service. The /f5bnk/data endpoint fetches
all 16 CRD types + pods once, then each view applies its own analysis.

Frontend uses a shared React Query cache key so switching tabs doesn't
re-fetch from the cluster.
"""

import logging

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from core.errors import handle_route_errors
from database import get_db
from services.analyzer_metrics_service import get_analyzer_runtime_metrics
from services.backend_health_service import get_backend_health
from services.bnk.a2a_discovery import discover_a2a_agents
from services.bnk_data_service import (
    analyze_backends,
    analyze_health,
    analyze_policy_associations,
    analyze_topology,
    extract_palette_data,
    fetch_all_bnk_data,
)
from services.kubernetes_service import KubernetesService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["k8s-f5bnk"])


# ============================================================================
# Unified BNK Data Endpoint
# ============================================================================

@router.get("/k8s/clusters/{cluster_id}/f5bnk/data")
@handle_route_errors("fetch BNK data")
def get_bnk_data(
    cluster_id: int,
    namespace: str | None = None,
    db: Session = Depends(get_db),
):
    """
    Unified BNK data endpoint — fetches all 16 CRD types + pods once.

    Returns health analysis, topology graph, and policy associations
    in a single response. The frontend caches this under one query key
    so switching between Health, Topology, and Policy Map tabs is instant.
    """
    k8s_service = KubernetesService(db)
    data = fetch_all_bnk_data(k8s_service, cluster_id, namespace)

    health = analyze_health(data)
    topo = analyze_topology(data)
    policy = analyze_policy_associations(data)
    backends = analyze_backends(data, topo["topology"])
    palette = extract_palette_data(data)

    return {
        "health": health,
        "topology": topo["topology"],
        "dataPlane": topo["dataPlane"],
        "referenceGrants": topo.get("referenceGrants", []),
        "topologyCounts": topo["counts"],
        "policyAssociations": policy["associations"],
        "policyCount": policy["count"],
        "backends": backends,
        "palette": palette,
        "cluster_id": cluster_id,
        "namespace": namespace,
    }


# ============================================================================
# Individual endpoints (kept for backward compatibility / direct access)
# These now delegate to the shared data service.
# ============================================================================

@router.get("/k8s/clusters/{cluster_id}/f5bnk/health")
@handle_route_errors("get BNK health")
def get_bnk_health(
    cluster_id: int,
    namespace: str | None = None,
    db: Session = Depends(get_db),
):
    """BNK health dashboard — delegates to shared data service."""
    k8s_service = KubernetesService(db)
    data = fetch_all_bnk_data(k8s_service, cluster_id, namespace)
    result = analyze_health(data)
    result["cluster_id"] = cluster_id
    return result


@router.get("/k8s/clusters/{cluster_id}/f5bnk/gateway-topology")
@handle_route_errors("get gateway topology")
def get_gateway_topology(
    cluster_id: int,
    namespace: str | None = None,
    db: Session = Depends(get_db),
):
    """Gateway topology graph — delegates to shared data service."""
    k8s_service = KubernetesService(db)
    data = fetch_all_bnk_data(k8s_service, cluster_id, namespace)
    result = analyze_topology(data)
    result["cluster_id"] = cluster_id
    result["namespace"] = namespace
    return result


@router.get("/k8s/clusters/{cluster_id}/f5bnk/policy-gateway-associations")
@handle_route_errors("get policy-gateway associations")
def get_policy_gateway_associations(
    cluster_id: int,
    namespace: str | None = None,
    db: Session = Depends(get_db),
):
    """Policy-gateway associations — delegates to shared data service."""
    k8s_service = KubernetesService(db)
    data = fetch_all_bnk_data(k8s_service, cluster_id, namespace)
    result = analyze_policy_associations(data)
    result["cluster_id"] = cluster_id
    result["namespace"] = namespace
    return result


# ============================================================================
# F5BigAnalyzer runtime metrics (Prometheus proxy)
# ============================================================================

@router.get(
    "/k8s/clusters/{cluster_id}/analyzers/{namespace}/{name}/runtime-metrics",
)
@handle_route_errors("fetch analyzer runtime metrics")
def get_analyzer_metrics(
    cluster_id: int,
    namespace: str,
    name: str,
    db: Session = Depends(get_db),
):
    """
    Runtime metrics for one F5BigAnalyzer, sourced from the Prometheus
    endpoint declared on its ``spec.dataSources[]``. Queries are proxied
    through the K8s API-server service-proxy so Prometheus doesn't need
    external exposure.

    Response shape is fixed even on error — frontend renders gracefully
    when ``available: false``.
    """
    return get_analyzer_runtime_metrics(db, cluster_id, namespace, name)


@router.get(
    "/k8s/clusters/{cluster_id}/analyzers/{namespace}/{name}/backend-health",
)
@handle_route_errors("fetch analyzer backend health")
def get_backend_health_route(
    cluster_id: int,
    namespace: str,
    name: str,
    db: Session = Depends(get_db),
):
    """
    Per-pod inference-backend health for one F5BigAnalyzer's monitored apps.

    Walks ``spec.applications[]`` → HTTPRoute → backendRefs[] → matching
    Services, then subprocesses ``llmtop --once --output json`` scoped to
    those pods. Returns one row per pod with KV cache, queue depth, latency
    percentiles, and token throughput. GPU fields are null until a DCGM
    exporter is wired (intentional — Bedrock shims have no GPU).
    """
    return get_backend_health(db, cluster_id, namespace, name)


# ============================================================================
# A2A Protocol
# ============================================================================

@router.get("/k8s/clusters/{cluster_id}/f5bnk/a2a/agents")
@handle_route_errors("discover A2A agents")
def get_a2a_agents(
    cluster_id: int,
    namespace: str | None = None,
    probe: bool = False,
    db: Session = Depends(get_db),
):
    """
    Discover A2A agent candidates behind BNK Gateways.

    Scans HTTPRoute backends for services that could be A2A agents.
    With ``probe=true``, attempts to fetch ``/.well-known/agent-card.json``
    from each backend service via the K8s service proxy API.

    Reuses the shared BNK data fetch + topology analysis — no extra
    K8s API calls for the candidate list (probe adds one call per service).
    """
    k8s_service = KubernetesService(db)
    cluster = k8s_service.get_cluster(cluster_id)
    api_client = k8s_service.load_kubeconfig(cluster) if probe else None

    data = fetch_all_bnk_data(k8s_service, cluster_id, namespace)
    topo = analyze_topology(data)

    agents = discover_a2a_agents(
        data, topo["topology"],
        api_client=api_client,
        probe=probe,
    )

    return {
        "agents": agents,
        "count": len(agents),
        "probed": probe,
        "cluster_id": cluster_id,
        "namespace": namespace,
    }
