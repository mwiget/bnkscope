"""tmmscope orchestration endpoints.

Mostly reporting, with one exception: injection. `tmmscope up` is still a host
command, because starting Prometheus and Grafana needs the Docker socket. But
`tmmscope inject` is not — see
`D-036 <../../docs/adr/D-036-tmmscope-injection-in-bnkscope.md>`_. It needs
kubectl only because the Go CLI shells out; the operation itself is one
Kubernetes API call against a cluster bnkscope already holds a client for.

Injection is ephemeral-only and the exporter image is pinned server-side. Removal
recreates the TMM pods — it cannot be done in place — so it drops traffic, and
callers are expected to confirm before invoking it.
"""

import logging

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from core.errors import handle_route_errors
from database import get_db
from models import KubernetesCluster
from services import tmmscope_inject_service, tmmscope_service
from services.kubernetes_service import KubernetesService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/tmmscope", tags=["tmmscope"])


# ============================================================================
# Schemas
# ============================================================================


class TmmscopeDashboard(BaseModel):
    uid: str
    title: str
    description: str


class TmmscopeStatusResponse(BaseModel):
    """Response for GET /api/tmmscope/status."""

    # The discovery file exists and claims the stack is up.
    configured: bool = False
    # Grafana actually answered. `configured` without this is a stale file.
    running: bool = False
    grafana_url: str | None = None
    prometheus_url: str | None = None
    updated_at: str | None = None
    # cluster= label values Prometheus holds f5tmm_up series for. This, not the
    # discovery file, is what "injected" actually means.
    streaming_clusters: list[str] = Field(default_factory=list)
    dashboards: list[TmmscopeDashboard] = Field(default_factory=list)
    detail: str | None = None


class ClusterTelemetryResponse(BaseModel):
    """Response for GET /api/tmmscope/clusters/{cluster_id}."""

    cluster_id: int
    cluster_name: str
    context: str | None = None
    # Which tmmscope cluster= label this cluster's telemetry arrives under, if
    # any is currently streaming.
    streaming_as: str | None = None
    streaming: bool = False
    # True when `streaming_as` came from an operator's explicit binding rather
    # than a name match — the UI says so, because a pin that silently goes
    # stale is worse than one that is visible.
    label_pinned: bool = False
    # Every label Prometheus currently holds TMM series for. Lets the UI offer
    # a picker when the automatic match found nothing.
    available_labels: list[str] = Field(default_factory=list)
    # Embeddable, kiosk-mode, scoped to `streaming_as`.
    dashboard_url: str | None = None
    # Commands the operator runs on the host to start/stop streaming.
    inject_command: str
    eject_command: str


class BindLabelRequest(BaseModel):
    """Bind a bnkscope cluster to a tmmscope `cluster=` label.

    `tmmscope inject --cluster` names the label freely and operators commonly
    use the TMM namespace, which bnkscope has no way to derive from a kube
    context. Null clears the binding and returns to automatic matching.
    """

    label: str | None = Field(default=None, max_length=253)


# ============================================================================
# Routes
# ============================================================================


def _browser_host(request: Request) -> str | None:
    """The hostname the browser used to reach bnkscope.

    tmmscope's discovery file says "localhost", which is right for something on
    the same machine and wrong for a browser on another one. Everything handed
    to the browser is rebased onto this instead.
    """
    host = request.headers.get("x-forwarded-host") or request.headers.get("host")
    if not host:
        return None
    # Strip the port — only the hostname carries over; Grafana has its own.
    host = host.rsplit(":", 1)[0] if host.count(":") == 1 else host
    return host.strip("[]") or None


@router.get("/status", response_model=TmmscopeStatusResponse)
@handle_route_errors("tmmscope status")
def get_tmmscope_status(request: Request):
    """Whether tmmscope is up, where, and which clusters are streaming to it."""
    status = tmmscope_service.get_status().as_dict()
    host = _browser_host(request)
    status["grafana_url"] = tmmscope_service.rebase_to_browser_host(status["grafana_url"], host)
    status["prometheus_url"] = tmmscope_service.rebase_to_browser_host(
        status["prometheus_url"], host
    )
    return status


@router.get("/clusters/{cluster_id}", response_model=ClusterTelemetryResponse)
@handle_route_errors("cluster telemetry status")
def get_cluster_telemetry(
    cluster_id: int,
    request: Request,
    theme: str = "dark",
    db: Session = Depends(get_db),
):
    """Whether one bnkscope cluster is streaming, and where to watch it."""
    from core.errors import NotFoundError

    cluster = db.query(KubernetesCluster).filter(KubernetesCluster.id == cluster_id).first()
    if cluster is None:
        raise NotFoundError("cluster", str(cluster_id))

    status = tmmscope_service.get_status()
    pinned = (cluster.meta_data or {}).get(_LABEL_KEY)
    streaming_as = _match_label(cluster, status.streaming_clusters)

    url = None
    if status.running and status.grafana_url and streaming_as:
        url = tmmscope_service.dashboard_url(
            status.grafana_url,
            tmmscope_service.DASHBOARDS[0]["uid"],
            streaming_as,
            # Grafana understands exactly two; anything else renders unstyled.
            # Only an explicit "light" opts out — the parameter's own default
            # is dark, so an unrecognised value must land there too.
            "light" if theme == "light" else "dark",
            _browser_host(request),
        )

    context = cluster.context or cluster.name
    return {
        "cluster_id": cluster.id,
        "cluster_name": cluster.name,
        "context": cluster.context,
        "streaming_as": streaming_as,
        "streaming": streaming_as is not None,
        "label_pinned": bool(pinned) and streaming_as == pinned,
        "available_labels": status.streaming_clusters,
        "dashboard_url": url,
        "inject_command": tmmscope_service.inject_command(context, cluster.name),
        "eject_command": tmmscope_service.eject_command(context),
    }


@router.put("/clusters/{cluster_id}/label", response_model=ClusterTelemetryResponse)
@handle_route_errors("bind tmmscope label")
def bind_cluster_label(
    cluster_id: int,
    body: BindLabelRequest,
    request: Request,
    theme: str = "dark",
    db: Session = Depends(get_db),
):
    """Bind this cluster to a tmmscope `cluster=` label, or clear the binding.

    Needed because there is no identifier the two tools share: `tmmscope
    inject --cluster` names the label whatever the operator wants, and
    namespace-derived names are common. One click beats guessing wrong.
    """
    from core.errors import NotFoundError

    cluster = db.query(KubernetesCluster).filter(KubernetesCluster.id == cluster_id).first()
    if cluster is None:
        raise NotFoundError("cluster", str(cluster_id))

    meta = dict(cluster.meta_data or {})
    if body.label:
        meta[_LABEL_KEY] = body.label
    else:
        meta.pop(_LABEL_KEY, None)
    cluster.meta_data = meta
    db.commit()

    return get_cluster_telemetry(cluster_id, request, theme=theme, db=db)


class InjectionPod(BaseModel):
    pod: str
    namespace: str
    injected: bool
    # The remote-write URL baked into the exporter. Immutable once injected.
    pushing_to: str | None = None
    stale: bool = False


class InjectionStateResponse(BaseModel):
    """Response for GET/POST/DELETE /api/tmmscope/clusters/{id}/injection."""

    ok: bool = True
    cluster_id: int
    tmm_pods: int = 0
    injected_pods: int = 0
    # True only when every running f5-tmm pod carries the exporter.
    injected: bool = False
    # Some but not all — a pod recreated after injection comes back clean.
    partial: bool = False
    pods: list[InjectionPod] = Field(default_factory=list)
    # Injected and running, but pushing at a port nothing is listening on any
    # more — indistinguishable from "never injected" without being told.
    stale: bool = False
    stale_pods: int = 0
    stale_target: str | None = None
    expected_port: int | None = None
    added: list[str] = Field(default_factory=list)
    skipped: list[str] = Field(default_factory=list)
    deleted: list[str] = Field(default_factory=list)
    failed: list[dict[str, str]] = Field(default_factory=list)
    remote_write_url: str | None = None
    # Which heuristic produced the remote-write host, for when it picks wrong.
    remote_write_derivation: str | None = None
    cluster_label: str | None = None
    detail: str | None = None


class InjectRequest(BaseModel):
    """Body for POST .../injection.

    Deliberately carries no image, command, mounts or security context. The
    sidecar spec is built server-side from a pinned image — see D-036. The only
    inputs are which label the series are tagged with, and where to push.
    """

    # Defaults to the tmmscope label bnkscope already matched for this cluster.
    cluster_label: str | None = None
    # Escape hatch for when the gateway heuristic cannot work it out.
    remote_write_url: str | None = None


def _cluster_client(cluster_id: int, db: Session):
    """(cluster, api_client) — KubernetesService raises NotFound for us."""
    k8s = KubernetesService(db)
    cluster = k8s.get_cluster(cluster_id)
    return cluster, k8s.load_kubeconfig(cluster)


@router.get("/clusters/{cluster_id}/injection", response_model=InjectionStateResponse)
@handle_route_errors("read tmmscope injection state")
def get_injection(cluster_id: int, db: Session = Depends(get_db)):
    """Which of this cluster's f5-tmm pods currently carry the exporter."""
    _cluster, api_client = _cluster_client(cluster_id, db)
    ingest = tmmscope_service.prometheus_ingest()
    state = tmmscope_inject_service.get_injection_state(
        api_client, expected_port=ingest[0] if ingest else None
    )
    return {"cluster_id": cluster_id, **state}


@router.post("/clusters/{cluster_id}/injection", response_model=InjectionStateResponse)
@handle_route_errors("inject the tmm-stat exporter")
def inject_exporter(
    cluster_id: int,
    body: InjectRequest | None = None,
    db: Session = Depends(get_db),
):
    """Add the exporter to every running f5-tmm pod, as an ephemeral container.

    Does not restart TMM. Idempotent — a pod already carrying it is skipped.
    """
    from core.errors import ValidationError

    cluster, api_client = _cluster_client(cluster_id, db)
    body = body or InjectRequest()

    ingest = tmmscope_service.prometheus_ingest()
    if ingest is None and not body.remote_write_url:
        raise ValidationError(
            "tmmscope's Prometheus is not discoverable, so there is nowhere to "
            "push. Run `tmmscope up` on the host, or supply a remote-write URL."
        )
    port, path = ingest or (9090, "/api/v1/write")

    # Default the series label to whatever this cluster already streams as, so
    # a re-injection lands on the same label rather than creating a second one.
    label = body.cluster_label
    if not label:
        status = tmmscope_service.get_status()
        label = _match_label(cluster, status.streaming_clusters) or (
            cluster.context or cluster.name
        )

    result = tmmscope_inject_service.inject(
        api_client,
        label,
        remote_write_url=body.remote_write_url,
        prometheus_port=port,
        remote_write_path=path,
    )
    state = tmmscope_inject_service.get_injection_state(
        api_client, expected_port=port
    )
    return {
        "cluster_id": cluster_id,
        **state,
        **result,
        "detail": (
            "Injected. Metrics appear in Grafana under cluster="
            f"{result['cluster_label']} within a few seconds. Ephemeral "
            "containers are transient — they do not survive a pod restart, and "
            "nothing re-adds them."
        ),
    }


@router.delete("/clusters/{cluster_id}/injection", response_model=InjectionStateResponse)
@handle_route_errors("remove the tmm-stat exporter")
def remove_exporter(cluster_id: int, db: Session = Depends(get_db)):
    """Clear the exporter by **recreating the f5-tmm pods**.

    An ephemeral container cannot be removed from a running pod, so this is the
    only way — and it drops dataplane traffic while the pods come back. The UI
    confirms explicitly before calling this.
    """
    _cluster, api_client = _cluster_client(cluster_id, db)
    result = tmmscope_inject_service.remove(api_client)
    ingest = tmmscope_service.prometheus_ingest()
    state = tmmscope_inject_service.get_injection_state(
        api_client, expected_port=ingest[0] if ingest else None
    )
    return {
        "cluster_id": cluster_id,
        **state,
        **result,
        "detail": (
            f"Recreated {len(result['deleted'])} f5-tmm pod(s) to clear the "
            "exporter."
            if result["deleted"]
            else "No f5-tmm pod was carrying the exporter; nothing was restarted."
        ),
    }


# Where an operator's explicit binding is remembered.
_LABEL_KEY = "tmmscope_cluster_label"


def _match_label(cluster: KubernetesCluster, labels: list[str]) -> str | None:
    """Find which tmmscope `cluster=` label belongs to this bnkscope cluster.

    There is no shared identifier to join on. `tmmscope inject` defaults the
    label to the *kube context* name, but `--cluster` overrides it freely, and
    in practice operators name it after the namespace the TMM pods live in. So:
    an explicit binding wins, then the candidates bnkscope actually knows, and
    otherwise None rather than a guess — a wrong match points the dashboard at
    another cluster's telemetry, which is worse than showing none.
    """
    available = {label.casefold(): label for label in labels}

    pinned = (cluster.meta_data or {}).get(_LABEL_KEY)
    if pinned:
        # A pin that no longer matches anything streaming is reported as not
        # streaming, not silently ignored — the operator needs to see that.
        return available.get(str(pinned).casefold())

    candidates = [cluster.context, cluster.name, cluster.default_namespace]
    # Kube contexts are conventionally `user@cluster`, and the cluster half is
    # what a human would call the cluster — `tmmscope inject --cluster` is
    # routinely given exactly that. Observed: context
    # `kubernetes-admin@dpu-cplane-tenant1` against label `dpu-cplane-tenant1`.
    if cluster.context and "@" in cluster.context:
        candidates.append(cluster.context.split("@", 1)[1])
    candidates += list(cluster.discovered_namespaces or [])

    for candidate in candidates:
        if candidate and candidate.casefold() in available:
            return available[candidate.casefold()]
    return None
