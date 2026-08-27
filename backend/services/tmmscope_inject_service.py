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

import json
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
#:
#: The exporter's source now lives in this repository (`tmm-stat-exporter/`,
#: forked from tmmscope) and `docker-bake.hcl` publishes it as
#: `bnkscope-tmm-stat-exporter` alongside the other images. This still points at
#: the tmmscope-built image on purpose: it is the one that exists in GHCR today,
#: and repointing it before a release has pushed the new name would turn every
#: injection into an ImagePullBackOff. Flip it in the same change that follows
#: the first release publishing `bnkscope-tmm-stat-exporter`.
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


#: Where an exporter came from. `permanent` is a real container in the pod
#: template — what `tmmscope inject --permanent` and the cluster builders
#: (tmmlitectl/ocibnkctl, and DPF's own DPUService templates) install.
#: `ephemeral` is what bnkscope injects. Both are equally "installed"; only the
#: permanent one survives a pod restart, and only the ephemeral one can be
#: cleared by recreating the pod.
KIND_PERMANENT = "permanent"
KIND_EPHEMERAL = "ephemeral"


def _exporter_containers(pod: Any) -> list[tuple[str, Any]]:
    """(kind, container) for every exporter in the pod spec.

    Both lists are searched. Reading only `ephemeral_containers` was a bug with
    a wide blast radius: every permanently-injected cluster — which is all of
    DPF, where the exporter rides the DaemonSet's pod template — reported no
    push URL at all, so staleness could never be detected there and the exporter
    was invisible in every way except a name in a container list.
    """
    found: list[tuple[str, Any]] = []
    for kind, attr in ((KIND_PERMANENT, "containers"), (KIND_EPHEMERAL, "ephemeral_containers")):
        for c in getattr(pod.spec, attr, None) or []:
            if c.name == SIDECAR_NAME:
                found.append((kind, c))
    return found


def owner_of(apps_v1: k8s_client.AppsV1Api, pod: Any) -> str | None:
    """The workload whose pod template carries a permanent sidecar.

    "Remove it where it is defined" is only an instruction if something says
    where that is. It is never bnkscope — a permanent exporter comes from the
    cluster build (tmmlitectl/ocibnkctl, DPF's DPUService templates) or from
    `tmmscope inject --permanent` — so the honest answer is to name the owner
    and stop, rather than print a command for one of the several tools it
    might have been.

    A Deployment's pod is owned by a ReplicaSet, which is generated and not
    what anyone edits, so that hop is resolved. DaemonSets and StatefulSets own
    their pods directly.
    """
    refs = pod.metadata.owner_references or []
    ref = next((r for r in refs if r.controller), refs[0] if refs else None)
    if ref is None:
        return None
    if ref.kind == "ReplicaSet":
        try:
            rs = apps_v1.read_namespaced_replica_set(
                name=ref.name, namespace=pod.metadata.namespace
            )
        except ApiException:
            # The ReplicaSet name still locates the workload well enough to act on.
            return f"{ref.kind} {ref.name}"
        parent = next(
            (o for o in (rs.metadata.owner_references or []) if o.controller), None
        )
        if parent is not None:
            return f"{parent.kind} {parent.name}"
    return f"{ref.kind} {ref.name}"


def _pushing_to(pod: Any) -> str | None:
    """The remote-write URL the injected exporter is actually using.

    Baked in at injection time and **immutable** — neither an ephemeral
    container's spec nor a running container's env can be edited. So when
    Prometheus moves, this is how a stale injection is recognised: the exporter
    is running, `f5tmm_up` is nowhere, and the only difference is a port number
    nobody can see.
    """
    for _kind, c in _exporter_containers(pod):
        for env in getattr(c, "env", None) or []:
            if env.name == "TMSTAT_REMOTE_WRITE_URL":
                return env.value
    return None


def _exporter_kind(pod: Any) -> str | None:
    """Whether the exporter is part of the pod template or bolted on."""
    kinds = [kind for kind, _ in _exporter_containers(pod)]
    # A pod can carry both — someone injected ephemerally over a cluster that
    # already had the sidecar. The permanent one is the durable fact.
    return KIND_PERMANENT if KIND_PERMANENT in kinds else (kinds[0] if kinds else None)


def _exporter_started_at(pod: Any) -> Any:
    """When the exporter container last started running, or None.

    This is what bounds "settling". Without it, "injected but no metrics" is one
    state that means two very different things — five seconds after injection it
    is normal, and ten minutes after it is a fault — and the UI can only show
    the optimistic reading of both.
    """
    for attr in ("container_statuses", "ephemeral_container_statuses"):
        for cs in getattr(pod.status, attr, None) or []:
            if cs.name != SIDECAR_NAME:
                continue
            running = getattr(cs.state, "running", None) if cs.state else None
            if running is not None and running.started_at:
                return running.started_at
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


#: How long an exporter may run without its metrics arriving before that stops
#: being "settling" and becomes a fault. Injection to first sample is a couple
#: of seconds; the exporter's own push interval is 2s and its retry backoff is
#: ~10s, so a minute and a half is generous by an order of magnitude.
SETTLE_SECONDS = 90

#: Verdicts. Exactly one holds for a cluster, and each names a different action.
VERDICT_NO_TMM = "no_tmm"
VERDICT_NOT_INSTALLED = "not_installed"
VERDICT_SETTLING = "settling"
VERDICT_STREAMING = "streaming"
VERDICT_PARTIAL_DELIVERY = "partial_delivery"
VERDICT_STALE_TARGET = "stale_target"
VERDICT_NOT_DELIVERING = "not_delivering"
#: The pods are on nodes Kubernetes reports NotReady. Nothing about the exporter
#: explains the silence, and nothing about the exporter fixes it.
VERDICT_NODE_NOT_READY = "node_not_ready"


def _running_for(started_at: Any, now: Any) -> float | None:
    if started_at is None:
        return None
    try:
        return max(0.0, (now - started_at).total_seconds())
    except TypeError:  # pragma: no cover - naive/aware mismatch
        return None


def node_readiness(core_v1: k8s_client.CoreV1Api) -> dict[str, bool]:
    """node name -> whether Kubernetes currently reports it Ready.

    A pod on a node that has stopped answering stays `Running` in the API for a
    long time — the control plane cannot know the container died, only that the
    kubelet went quiet. So "the exporter is running and nothing arrives" reads
    identically for a broken network path and for a machine that is switched
    off, and the page said "the pod cannot reach it" for both. One of those two
    has nothing to do with the exporter.

    One list call, not one read per pod: several f5-tmm pods usually sit on the
    same handful of nodes.

    Empty when the nodes cannot be listed — an unknown readiness must not be
    reported as a fault, so callers treat a missing entry as "no reason to
    doubt it".
    """
    try:
        nodes = core_v1.list_node()
    except ApiException:
        logger.debug("Could not list nodes for readiness", exc_info=True)
        return {}

    ready: dict[str, bool] = {}
    for node in nodes.items or []:
        conditions = (node.status.conditions or []) if node.status else []
        status = next((c.status for c in conditions if c.type == "Ready"), None)
        # "True" / "False" / "Unknown" — and Unknown is what a node whose
        # kubelet stopped reporting becomes, which is exactly this case.
        ready[node.metadata.name] = status == "True"
    return ready


def _api_error_detail(exc: ApiException) -> str:
    """The sentence in an ApiException, not its HTTP reason phrase.

    `exc.reason` for a failed pod-log read is "Internal Server Error", which
    says nothing — the apiserver puts the useful line in the body\'s `message`,
    and for an unreachable node that line is
    `dial tcp 10.0.0.1:10250: connect: no route to host`. Reporting the reason
    phrase would have been a longer way of saying nothing.
    """
    try:
        message = json.loads(exc.body or "{}").get("message")
    except (ValueError, TypeError):
        message = None
    detail = (message or exc.reason or str(exc.status) or "unknown error").strip()
    return detail[:300]


def _last_push_error(
    core_v1: k8s_client.CoreV1Api, name: str, namespace: str
) -> tuple[str | None, str | None]:
    """(the exporter's own last complaint, why it could not be read).

    The exporter logs every failed `remote_write` with the reason — "connection
    refused", "context deadline exceeded", a 4xx from Prometheus. That one line
    separates the three things that otherwise look identical from outside the
    pod: wrong address, no route, and a collector that is rejecting the write.
    Read only when something is actually wrong, because it is a log request per
    pod and the answer is uninteresting when metrics are arriving.

    The second half exists because the read goes through the *kubelet*, so the
    one failure it cannot describe is the one where the node is gone: the log
    request fails for the same reason the metrics stopped, and returning None
    made that indistinguishable from an exporter with nothing to complain
    about. Silence about a failed read is the worst of the three answers.
    """
    try:
        log = core_v1.read_namespaced_pod_log(
            name=name,
            namespace=namespace,
            container=SIDECAR_NAME,
            tail_lines=20,
            timestamps=False,
        )
    except ApiException as exc:
        logger.debug("Could not read exporter log from %s", name, exc_info=True)
        return None, _api_error_detail(exc)
    for line in reversed((log or "").splitlines()):
        if "remote_write" in line:
            return line.strip()[:500], None
    return None, None


def get_injection_state(
    api_client: k8s_client.ApiClient,
    expected_port: int | None = None,
    *,
    streaming_pods: set[str] | None = None,
    cluster_streaming: bool | None = None,
) -> dict[str, Any]:
    """Which f5-tmm pods carry the exporter, and whether it is actually working.

    `expected_port` is the Prometheus port bnkscope is listening on now. An
    exporter injected when Prometheus was somewhere else keeps running and keeps
    pushing into a closed socket — from the outside that is indistinguishable
    from never having injected at all, so it is called out rather than counted
    as working.

    `streaming_pods` is the set of pod names Prometheus holds live `f5tmm_up`
    series for. Installed and delivering are different facts, and the difference
    is per pod, not per cluster: re-install one DPU of several and the cluster
    keeps streaming from its siblings while that one silently stops. A
    cluster-level answer cannot see that, so this takes the pod-level one.
    """
    from datetime import UTC, datetime

    core_v1 = k8s_client.CoreV1Api(api_client)
    apps_v1 = k8s_client.AppsV1Api(api_client)
    pods = find_tmm_pods(api_client)
    now = datetime.now(UTC)
    live = streaming_pods if streaming_pods is not None else set()
    ready_nodes = node_readiness(core_v1)

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
        kind = _exporter_kind(pod)
        # Only for the permanent case, which is the only one where the owner is
        # the answer — and the only one worth a second API call per pod.
        owner = owner_of(apps_v1, pod) if kind == KIND_PERMANENT else None
        url = _pushing_to(pod) if is_injected else None
        started_at = _exporter_started_at(pod) if is_injected else None
        stale = bool(
            is_injected
            and expected_port is not None
            and _port_of(url) is not None
            and _port_of(url) != expected_port
        )
        node = getattr(pod.spec, "node_name", None)
        entries.append(
            {
                "pod": meta["name"],
                "namespace": meta["namespace"],
                "injected": is_injected,
                "kind": kind,
                "owner": owner,
                # None when the node's readiness is unknown — which must not
                # read as "not ready".
                "node": node,
                "node_ready": ready_nodes.get(node) if node else None,
                "pushing_to": url,
                "stale": stale,
                "started_at": started_at.isoformat() if started_at else None,
                "running_for": _running_for(started_at, now),
                # Only meaningful when the caller supplied the live set; with no
                # Prometheus to ask, nothing is known to be streaming.
                "streaming": meta["name"] in live,
                "last_push_error": None,
                "log_unavailable": None,
            }
        )

    injected = [e for e in entries if e["injected"]]
    stale = [e for e in entries if e["stale"]]
    permanent = [e for e in injected if e["kind"] == KIND_PERMANENT]
    not_ready = [e for e in entries if e["node_ready"] is False]
    silent = [e for e in injected if not e["streaming"]] if streaming_pods is not None else []

    # The oldest exporter that is not delivering. Oldest, not newest: one pod
    # injected ten seconds ago does not excuse a sibling that has been failing
    # for an hour, and that sibling is the whole point of asking.
    oldest_silent = max(
        (e["running_for"] for e in silent if e["running_for"] is not None),
        default=None,
    )

    verdict, detail = _verdict(
        entries=entries,
        injected=injected,
        stale=stale,
        silent=silent,
        oldest_silent=oldest_silent,
        cluster_streaming=cluster_streaming,
        streaming_known=streaming_pods is not None,
        not_ready=not_ready,
    )

    # Only when something is wrong, and only for the pods that are wrong.
    if verdict in (
        VERDICT_NOT_DELIVERING,
        VERDICT_PARTIAL_DELIVERY,
        VERDICT_STALE_TARGET,
        VERDICT_NODE_NOT_READY,
    ):
        for entry in silent or stale:
            entry["last_push_error"], entry["log_unavailable"] = _last_push_error(
                core_v1, entry["pod"], entry["namespace"]
            )

    return {
        "pods": entries,
        "tmm_pods": len(entries),
        "injected_pods": len(injected),
        # Partial is a real state: a pod recreated after injection comes back
        # clean while its siblings still carry the exporter.
        "injected": bool(injected) and len(injected) == len(entries),
        "partial": bool(injected) and len(injected) != len(entries),
        # Pods whose node Kubernetes reports NotReady. Not a telemetry fault,
        # and the one cause the exporter's own log cannot describe.
        "not_ready_pods": len(not_ready),
        "not_ready_nodes": sorted({e["node"] for e in not_ready if e["node"]}),
        # A permanent sidecar is not bnkscope's to remove: deleting the pod just
        # brings it back, because it is in the template. The owner is what the
        # operator has to edit, so it is named rather than left to be guessed.
        "permanent_pods": len(permanent),
        "permanent_owner": next(
            (e["owner"] for e in permanent if e["owner"]), None
        ),
        "streaming_pods": sum(1 for e in entries if e["streaming"]),
        "silent_pods": len(silent),
        "stale_pods": len(stale),
        # Injected, running, and pushing at a port that is no longer listening.
        "stale": bool(stale),
        "stale_target": stale[0]["pushing_to"] if stale else None,
        "expected_port": expected_port,
        "verdict": verdict,
        "verdict_detail": detail,
        "settle_seconds": SETTLE_SECONDS,
    }


def _verdict(
    *,
    entries: list[dict[str, Any]],
    injected: list[dict[str, Any]],
    stale: list[dict[str, Any]],
    silent: list[dict[str, Any]],
    oldest_silent: float | None,
    cluster_streaming: bool | None,
    streaming_known: bool,
    not_ready: list[dict[str, Any]],
) -> tuple[str, str]:
    """One verdict per cluster, ordered so the most actionable answer wins.

    The ordering matters more than the individual cases. "Installed but no
    metrics" used to be a single optimistic state that read "waiting for the
    first metrics, this takes a few seconds" forever; splitting it by *why*
    is the whole point, because only one of the reasons is fixed by
    re-installing the exporter.
    """
    if not entries:
        return VERDICT_NO_TMM, "No running f5-tmm pods on this cluster."

    if not injected:
        return (
            VERDICT_NOT_INSTALLED,
            f"None of the {len(entries)} f5-tmm pod(s) carry the exporter.",
        )

    if stale:
        target = stale[0]["pushing_to"]
        return (
            VERDICT_STALE_TARGET,
            f"The exporter is pushing to {target}, which is not where Prometheus "
            "is listening any more. The address is fixed when the exporter is "
            "installed, so this one does need re-installing.",
        )

    if not streaming_known:
        # No Prometheus to ask. Say what is installed and claim nothing else.
        return (
            VERDICT_SETTLING,
            "The exporter is installed, but there is no Prometheus to check "
            "whether its metrics are arriving.",
        )

    if not silent:
        return (
            VERDICT_STREAMING,
            f"All {len(injected)} exporter(s) are delivering.",
        )

    # Ranked above every remaining answer, and below `streaming`: a node that
    # stopped reporting explains silence at any age, but a pod still delivering
    # from one is not a problem to shout about.
    #
    # `all`, not `any`: one silent pod on a healthy node is a delivery fault
    # that deserves its own sentence, and the node answer would bury it.
    if silent and all(e["node_ready"] is False for e in silent):
        nodes = sorted({e["node"] for e in silent if e["node"]})
        where = ", ".join(nodes) if nodes else "their node(s)"
        return (
            VERDICT_NODE_NOT_READY,
            f"The {len(silent)} silent exporter(s) are on {where}, which "
            "Kubernetes reports NotReady. A pod keeps its Running status long "
            "after its node stops answering, so the exporter looks healthy from "
            "here — but nothing is running to push. This is a cluster problem, "
            "and re-installing the exporter cannot touch it.",
        )

    if oldest_silent is not None and oldest_silent < SETTLE_SECONDS:
        return (
            VERDICT_SETTLING,
            f"The exporter started {int(oldest_silent)}s ago and its first "
            "metrics have not arrived yet. This takes a few seconds.",
        )

    where = silent[0].get("pushing_to") or "its configured collector"
    age = f"{int(oldest_silent // 60)}m" if oldest_silent else "some time"
    if cluster_streaming:
        return (
            VERDICT_PARTIAL_DELIVERY,
            f"{len(silent)} of {len(injected)} exporter(s) stopped delivering "
            f"— the rest of the cluster is still streaming. The silent one(s) "
            f"have been running {age} and are pushing to {where}, so the "
            "exporter is installed and the path to it is what broke.",
        )
    return (
        VERDICT_NOT_DELIVERING,
        f"The exporter has been running {age} and pushing to {where}, and "
        "nothing has arrived. The address matches where Prometheus is "
        "listening, so re-installing will not change anything — the pod cannot "
        "reach it.",
    )


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
    apps_v1 = k8s_client.AppsV1Api(api_client)
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

        # A permanent sidecar is in the pod template. Deleting the pod drops
        # dataplane traffic and the exporter comes straight back with the
        # replacement — all cost, no effect. Removing that one means editing
        # whatever owns the template, which is not bnkscope's to do.
        if _exporter_kind(pod) == KIND_PERMANENT:
            owner = owner_of(apps_v1, pod)
            where = f" — see {owner}" if owner else ""
            failed.append(
                {
                    "pod": name,
                    "error": (
                        "the exporter is a permanent sidecar in this pod's "
                        "template — recreating the pod would bring it back. "
                        f"Remove it where the template is defined{where}."
                    ),
                }
            )
            continue

        try:
            core_v1.delete_namespaced_pod(name=name, namespace=namespace)
            deleted.append(name)
        except ApiException as exc:
            failed.append({"pod": name, "error": exc.reason or str(exc.status)})
            logger.warning("Could not delete pod %s: %s", name, exc)

    return {"deleted": deleted, "failed": failed}
