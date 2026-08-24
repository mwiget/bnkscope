"""Inject the tmm-stat-exporter into f5-tmm pods, ephemerally.

Why this exists at all is [D-036](../../docs/adr/D-036-tmmscope-injection-in-bnkscope.md).
The short version: Phase 7 printed `tmmscope inject` as a host command because
it "needs kubectl", and it does not — kubectl is an implementation detail of the
Go CLI, not of the operation. The operation is one Kubernetes API call against a
cluster bnkscope already holds an authenticated client for.

**Ephemeral containers only.** `tmmscope inject` has three modes; the other two
(strategic-merge patch, and a mutating admission webhook) both *restart TMM*, and
the webhook additionally installs a cluster-scoped MutatingWebhookConfiguration
with a 10-year self-signed CA. Neither belongs behind a button in a
troubleshooting tool. The ephemeral path is tmmscope's own default precisely
because it leaves TMM running, and it is the one that works on operator-managed
BNK — the operator reconciles a patched Deployment back, but does not manage a
pod's ephemeralContainers list.

The trade, which callers must surface rather than hide:

  - transient: an ephemeral container is not restarted if it exits, and is gone
    when the pod is recreated. Nothing re-adds it.
  - it cannot be removed in place. Clearing one means recreating the pod, which
    drops dataplane traffic.
  - the subresource rejects `resources` and `ports`, so the exporter runs with no
    cpu/memory limit here.

The container spec is built here, from a pinned image. It is deliberately not
anything a caller can influence: accepting an image would turn this endpoint into
"run an arbitrary container inside TMM's pod with its tmstat segment mounted".
"""

import logging
from typing import Any

from kubernetes import client as k8s_client
from kubernetes.client.rest import ApiException

from services.bnk_pod_discovery import classify_f5_pods, discover_f5_pods

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# The sidecar, mirroring tmmscope's inject.SidecarSpec
# ---------------------------------------------------------------------------

#: Pinned, and not a parameter. See the module docstring.
EXPORTER_IMAGE = "ghcr.io/mwiget/tmm-stat-exporter:latest"

SIDECAR_NAME = "tmm-stat-exporter"

#: The shared tmstat segment, mounted read-only. Named by tmm's own pod spec.
TMSTAT_VOLUME = "f5tmstat"
TMSTAT_MOUNT = "/var/tmstat"

#: tmm's DSSM client cert. Mounted only when the pod already declares it, which
#: is what enables the iRule token counters to be read out of DSSM/Redis.
DSSM_CERT_VOLUME = "tls-tmm-mds-clt-volume"
DSSM_CERT_MOUNT = "/tls/tmm/mds/clt"


def _downward(name: str, field_path: str) -> dict[str, Any]:
    return {
        "name": name,
        "valueFrom": {"fieldRef": {"fieldPath": field_path}},
    }


def build_sidecar(
    cluster_label: str,
    remote_write_url: str,
    *,
    dssm_cert: bool = False,
) -> dict[str, Any]:
    """The ephemeral container spec.

    Identical to tmmscope's permanent sidecar except for `resources`, which the
    ephemeralcontainers subresource rejects.

    No readiness or liveness probe, and that is deliberate rather than an
    oversight: TMM hooks inbound TCP on its dataplane interfaces, so a kubelet
    probe to the pod IP cannot reach the sidecar and would wrongly mark the whole
    tmm pod NotReady. Telemetry must not gate tmm readiness.
    """
    labels = f"cluster={cluster_label},pod=$(POD_NAME),node=$(NODE_NAME)"

    mounts: list[dict[str, Any]] = [
        {"name": TMSTAT_VOLUME, "mountPath": TMSTAT_MOUNT, "readOnly": True},
    ]
    if dssm_cert:
        mounts.append(
            {"name": DSSM_CERT_VOLUME, "mountPath": DSSM_CERT_MOUNT, "readOnly": True}
        )

    return {
        "name": SIDECAR_NAME,
        "image": EXPORTER_IMAGE,
        "imagePullPolicy": "IfNotPresent",
        "env": [
            _downward("POD_NAME", "metadata.name"),
            _downward("NODE_NAME", "spec.nodeName"),
            {"name": "TMSTAT_REMOTE_WRITE_URL", "value": remote_write_url},
            {"name": "TMSTAT_EXTERNAL_LABELS", "value": labels},
        ],
        # Reads a shared segment read-only and pushes outbound. It needs nothing
        # else, so it is given nothing else.
        "securityContext": {
            "runAsUser": 65532,
            "runAsGroup": 65532,
            "runAsNonRoot": True,
            "readOnlyRootFilesystem": True,
            "allowPrivilegeEscalation": False,
            "capabilities": {"drop": ["ALL"]},
        },
        "volumeMounts": mounts,
    }


# ---------------------------------------------------------------------------
# Finding the targets
# ---------------------------------------------------------------------------


def find_tmm_pods(api_client: k8s_client.ApiClient) -> list[dict[str, Any]]:
    """Running f5-tmm pods, via the same discovery the rest of bnkscope uses."""
    tenant_pods, utils_pods = discover_f5_pods(api_client)
    classified = classify_f5_pods(tenant_pods, utils_pods)
    return [p for p in classified.get("tmm", []) if p.get("phase") == "Running"]


def _container_names(pod: Any) -> set[str]:
    names: set[str] = set()
    for attr in ("containers", "ephemeral_containers", "init_containers"):
        for c in getattr(pod.spec, attr, None) or []:
            names.add(c.name)
    return names


def _has_volume(pod: Any, volume_name: str) -> bool:
    return any(v.name == volume_name for v in (pod.spec.volumes or []))


def _pushing_to(pod: Any) -> str | None:
    """The remote-write URL the injected exporter is actually using.

    Baked in at injection time and **immutable** — an ephemeral container's spec
    cannot be edited. So when Prometheus moves, this is how a stale injection is
    recognised: the exporter is running, `f5tmm_up` is nowhere, and the only
    difference is a port number nobody can see.
    """
    for c in getattr(pod.spec, "ephemeral_containers", None) or []:
        if c.name != SIDECAR_NAME:
            continue
        for env in getattr(c, "env", None) or []:
            if env.name == "TMSTAT_REMOTE_WRITE_URL":
                return env.value
    return None


def _port_of(url: str | None) -> int | None:
    if not url:
        return None
    from urllib.parse import urlparse

    try:
        return urlparse(url).port
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Remote-write URL
# ---------------------------------------------------------------------------


def _gateway_of(ip: str) -> str | None:
    """The .1 of the /24 an IPv4 address sits in."""
    parts = ip.strip().split(".")
    if len(parts) != 4 or not all(p.isdigit() for p in parts):
        return None
    return f"{parts[0]}.{parts[1]}.{parts[2]}.1"


def derive_remote_write_host(
    core_v1: k8s_client.CoreV1Api, pod: Any
) -> tuple[str | None, str]:
    """Best-effort: the address at which the pod can reach *this* host.

    Mirrors tmmscope's `DeriveRemoteWriteURL`. The discriminator is whether the
    pod has a multus edge interface:

      - multus edge (e.g. tmmlite): the pod sits on a host-bridged multus
        network; the .1 of that subnet is the host.
      - no edge interface (FLO/BNK on plain pod networking, k3s-in-docker): the
        pod egresses via its node, whose docker-network gateway (.1) is the host.

    Returns (host, how) — `how` names which path produced it, or why neither did.
    This is a heuristic in tmmscope too. When it fails, say so: an exporter
    pushing to nowhere looks identical to one that was never injected.
    """
    annotations = (pod.metadata.annotations or {}) if pod.metadata else {}
    network_status = annotations.get("k8s.v1.cni.cncf.io/network-status")
    if network_status:
        import json

        try:
            for net in json.loads(network_status):
                if net.get("default") or not net.get("ips"):
                    continue
                gw = _gateway_of(net["ips"][0])
                if gw:
                    return gw, "multus edge interface"
        except (ValueError, KeyError, TypeError):
            logger.debug("Could not parse network-status annotation", exc_info=True)

    node_name = pod.spec.node_name if pod.spec else None
    if node_name:
        try:
            node = core_v1.read_node(name=node_name)
            for addr in node.status.addresses or []:
                if addr.type == "InternalIP":
                    gw = _gateway_of(addr.address)
                    if gw:
                        return gw, f"node {node_name} gateway"
        except ApiException:
            logger.debug("Could not read node %s", node_name, exc_info=True)

    return None, "no multus edge interface and no readable node InternalIP"


# ---------------------------------------------------------------------------
# Inject / remove
# ---------------------------------------------------------------------------


def get_injection_state(
    api_client: k8s_client.ApiClient, expected_port: int | None = None
) -> dict[str, Any]:
    """Which f5-tmm pods carry the exporter, and whether it can still reach us.

    `expected_port` is the Prometheus port bnkscope is listening on now. An
    exporter injected when Prometheus was somewhere else keeps running and keeps
    pushing into a closed socket — from the outside that is indistinguishable
    from never having injected at all, so it is called out rather than counted
    as working.
    """
    core_v1 = k8s_client.CoreV1Api(api_client)
    pods = find_tmm_pods(api_client)

    entries: list[dict[str, Any]] = []
    for meta in pods:
        try:
            pod = core_v1.read_namespaced_pod(
                name=meta["name"], namespace=meta["namespace"]
            )
        except ApiException:
            logger.debug("Could not read pod %s", meta["name"], exc_info=True)
            continue
        is_injected = SIDECAR_NAME in _container_names(pod)
        url = _pushing_to(pod) if is_injected else None
        stale = bool(
            is_injected
            and expected_port is not None
            and _port_of(url) is not None
            and _port_of(url) != expected_port
        )
        entries.append(
            {
                "pod": meta["name"],
                "namespace": meta["namespace"],
                "injected": is_injected,
                "pushing_to": url,
                "stale": stale,
            }
        )

    injected = [e for e in entries if e["injected"]]
    stale = [e for e in entries if e["stale"]]
    return {
        "pods": entries,
        "tmm_pods": len(entries),
        "injected_pods": len(injected),
        # Partial is a real state: a pod recreated after injection comes back
        # clean while its siblings still carry the exporter.
        "injected": bool(injected) and len(injected) == len(entries),
        "partial": bool(injected) and len(injected) != len(entries),
        "stale_pods": len(stale),
        # Injected, running, and pushing at a port that is no longer listening.
        "stale": bool(stale),
        "stale_target": stale[0]["pushing_to"] if stale else None,
        "expected_port": expected_port,
    }


def inject(
    api_client: k8s_client.ApiClient,
    cluster_label: str,
    *,
    remote_write_url: str | None = None,
    prometheus_port: int = 9090,
    remote_write_path: str = "/api/v1/write",
) -> dict[str, Any]:
    """Add the exporter as an ephemeral container to every running f5-tmm pod.

    Idempotent: a pod already carrying it is skipped rather than duplicated.
    """
    core_v1 = k8s_client.CoreV1Api(api_client)
    targets = find_tmm_pods(api_client)

    if not targets:
        raise ValueError(
            "No running f5-tmm pods found. Ephemeral injection needs live pods — "
            "is TMM running on this cluster?"
        )

    added: list[str] = []
    skipped: list[str] = []
    failed: list[dict[str, str]] = []
    derivation: str | None = None
    url = remote_write_url

    for meta in targets:
        name, namespace = meta["name"], meta["namespace"]
        try:
            pod = core_v1.read_namespaced_pod(name=name, namespace=namespace)
        except ApiException as exc:
            failed.append({"pod": name, "error": f"could not read pod: {exc.reason}"})
            continue

        if SIDECAR_NAME in _container_names(pod):
            skipped.append(name)
            continue

        if not url:
            host, how = derive_remote_write_host(core_v1, pod)
            if not host:
                raise ValueError(
                    "Could not work out how this cluster reaches your Prometheus "
                    f"({how}). Supply a remote-write URL explicitly."
                )
            url = f"http://{host}:{prometheus_port}{remote_write_path}"
            derivation = how

        spec = build_sidecar(
            cluster_label,
            url,
            dssm_cert=_has_volume(pod, DSSM_CERT_VOLUME),
        )
        try:
            core_v1.patch_namespaced_pod_ephemeralcontainers(
                name=name,
                namespace=namespace,
                body={"spec": {"ephemeralContainers": [spec]}},
            )
            added.append(name)
        except ApiException as exc:
            failed.append({"pod": name, "error": exc.reason or str(exc.status)})
            logger.warning("Ephemeral injection failed on %s: %s", name, exc)

    return {
        "added": added,
        "skipped": skipped,
        "failed": failed,
        "remote_write_url": url,
        "remote_write_derivation": derivation,
        "cluster_label": cluster_label,
    }


def remove(api_client: k8s_client.ApiClient) -> dict[str, Any]:
    """Clear an ephemeral injection by recreating the f5-tmm pods.

    **This drops dataplane traffic.** An ephemeral container cannot be removed
    from a running pod — recreating it is the only way, and the pod comes back
    clean because the exporter was never part of the template.

    Callers must confirm before reaching here; see D-036 on why inject and remove
    are deliberately asymmetric.
    """
    core_v1 = k8s_client.CoreV1Api(api_client)
    targets = find_tmm_pods(api_client)

    deleted: list[str] = []
    failed: list[dict[str, str]] = []
    for meta in targets:
        name, namespace = meta["name"], meta["namespace"]
        try:
            pod = core_v1.read_namespaced_pod(name=name, namespace=namespace)
        except ApiException as exc:
            failed.append({"pod": name, "error": f"could not read pod: {exc.reason}"})
            continue

        # Only disturb pods that actually carry it.
        if SIDECAR_NAME not in _container_names(pod):
            continue

        try:
            core_v1.delete_namespaced_pod(name=name, namespace=namespace)
            deleted.append(name)
        except ApiException as exc:
            failed.append({"pod": name, "error": exc.reason or str(exc.status)})
            logger.warning("Could not delete pod %s: %s", name, exc)

    return {"deleted": deleted, "failed": failed}
