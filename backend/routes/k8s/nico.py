"""
NVIDIA NICo (Infra Controller) routes.

Read-only endpoints for NICo detection, health, and inventory. The deployment
side is read through the cluster's kubeconfig like every other view here; the
tenant / VPC / load-balancer inventory comes from NICo's Forge gRPC API, which
is the only place it exists — NICo publishes no CRDs.

Frontend uses a shared React Query cache key so the NICo sub-views don't
re-fetch when you switch between them.
"""

import logging

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from core.errors import handle_route_errors
from database import get_db
from services.kubernetes_service import KubernetesService
from services.nico import analyze_nico_health, detect_nico, fetch_all_nico_data

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["k8s-nico"])


@router.get(
    "/k8s/clusters/{cluster_id}/nico/detect",
)
@handle_route_errors("detect NICo")
def get_nico_detect(
    cluster_id: int,
    db: Session = Depends(get_db),
):
    """
    Lightweight NICo detection — one labelled pod list, no Forge session.

    Cheap enough to run per cluster: gating the tab must not cost an mTLS
    handshake against an endpoint that may not be routable.
    """
    k8s_service = KubernetesService(db)
    return detect_nico(k8s_service, cluster_id)


@router.get(
    "/k8s/clusters/{cluster_id}/nico/data",
)
@handle_route_errors("fetch NICo data")
def get_nico_data(
    cluster_id: int,
    db: Session = Depends(get_db),
):
    """
    Unified NICo endpoint — the deployment, the endpoint, and the inventory.

    Returns health analysis alongside the full picture. Sections that could not
    be read report why in ``errors`` rather than failing the request: a NICo
    whose Forge endpoint is unroutable still has pods, a Service and a
    certificate worth showing.
    """
    k8s_service = KubernetesService(db)
    data = fetch_all_nico_data(k8s_service, cluster_id)
    return {**data, "health": analyze_nico_health(data)}


@router.get(
    "/k8s/clusters/{cluster_id}/nico/health",
)
@handle_route_errors("get NICo health")
def get_nico_health(
    cluster_id: int,
    db: Session = Depends(get_db),
):
    """NICo health summary — control plane, providers, tenants, load balancers."""
    k8s_service = KubernetesService(db)
    health = analyze_nico_health(fetch_all_nico_data(k8s_service, cluster_id))
    health["cluster_id"] = cluster_id
    return health
