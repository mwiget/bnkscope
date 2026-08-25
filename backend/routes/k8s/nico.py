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
import re

from fastapi import APIRouter, Depends
from pydantic import BaseModel, field_validator
from sqlalchemy.orm import Session

from core.errors import NotFoundError, handle_route_errors
from database import get_db
from models.kubernetes import KubernetesCluster
from services.kubernetes_service import KubernetesService
from services.nico import (
    analyze_nico_health,
    detect_nico,
    fetch_all_nico_data,
    fetch_nico_deployment,
    fetch_nico_inventory,
    inventory_counts,
)
from services.nico.constants import FORGE_ENDPOINT_KEY

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
    "/k8s/clusters/{cluster_id}/nico/deployment",
)
@handle_route_errors("fetch NICo deployment")
def get_nico_deployment(
    cluster_id: int,
    db: Session = Depends(get_db),
):
    """The Kubernetes half — pods, Service, certificate, dependencies, DPUs.

    The fast, predictable half of the pair the UI drives. ``health`` here is
    scoped to what was actually read: it carries ``inventoryPending: true`` and
    omits the tenant / VPC / load-balancer counts, so the page can paint a true
    header before the Forge side lands rather than showing zeros it has not
    verified.
    """
    k8s_service = KubernetesService(db)
    data = fetch_nico_deployment(k8s_service, cluster_id)
    return {**data, "health": analyze_nico_health(data, inventory_read=False)}


@router.get(
    "/k8s/clusters/{cluster_id}/nico/inventory",
)
@handle_route_errors("fetch NICo inventory")
def get_nico_inventory(
    cluster_id: int,
    db: Session = Depends(get_db),
):
    """The Forge half — tenants, VPCs, network segments, load balancers.

    Returns the counts alongside the inventory so the caller can complete the
    header the deployment request painted without recomputing them.
    """
    k8s_service = KubernetesService(db)
    data = fetch_nico_inventory(k8s_service, cluster_id)
    return {**data, "counts": inventory_counts(data["inventory"])}


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


# `host:port`, where host is a hostname or a bare IPv4 literal. Deliberately
# not a URL: this is a gRPC dial target, and a scheme here would be silently
# dropped by the channel rather than rejected.
_ENDPOINT = re.compile(r"^[A-Za-z0-9._-]+:\d{1,5}$")


class ForgeEndpointRequest(BaseModel):
    """An operator-supplied Forge address, or null to clear it."""

    endpoint: str | None = None

    @field_validator("endpoint")
    @classmethod
    def _well_formed(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        value = value.strip()
        if not _ENDPOINT.match(value):
            raise ValueError("expected host:port, e.g. 127.0.0.1:11079")
        if not 0 < int(value.rpartition(":")[2]) < 65536:
            raise ValueError("port out of range")
        return value


@router.put(
    "/k8s/clusters/{cluster_id}/nico/endpoint",
)
@handle_route_errors("set NICo Forge endpoint")
def put_nico_endpoint(
    cluster_id: int,
    body: ForgeEndpointRequest,
    db: Session = Depends(get_db),
):
    """Pin the address bnkscope dials for the Forge API, or clear the pin.

    The escape hatch for the two cases automatic discovery cannot cover: a
    tunnel the operator already runs themselves (`ssh -L`, `kubectl
    port-forward`), and a kubeconfig whose RBAC denies `pods/portforward`. An
    override outranks every discovered candidate but is still TCP-screened, so
    a stale one reports itself instead of failing obscurely.

    Stored on `cluster.meta_data` rather than a column — one optional string is
    not worth a migration, and the tmmscope label binding set that precedent.
    """
    cluster = (
        db.query(KubernetesCluster).filter(KubernetesCluster.id == cluster_id).first()
    )
    if cluster is None:
        raise NotFoundError("cluster", str(cluster_id))

    # Rebound rather than mutated in place: SQLAlchemy does not track reaching
    # into a JSON column, and discovery merges into this same dict.
    meta = dict(cluster.meta_data or {})
    if body.endpoint:
        meta[FORGE_ENDPOINT_KEY] = body.endpoint
    else:
        meta.pop(FORGE_ENDPOINT_KEY, None)
    cluster.meta_data = meta
    db.commit()

    return {"cluster_id": cluster_id, "endpoint": body.endpoint}
