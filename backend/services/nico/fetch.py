"""
NICo fetch — the only I/O module in the NICo service package.

Two halves, because NICo is two things:

* **the deployment** — nico-api, its Service, its mTLS Secret, the LB provider
  operators that consume it, and the Postgres/Vault it runs on. All Kubernetes
  objects, read through the same kubeconfig everything else here uses.
* **the inventory** — tenants, VPCs, VIP prefixes, network segments and load
  balancer services. None of that is a Kubernetes object; it lives behind the
  Forge gRPC API and comes back through [`services.nico.forge`].

The second half only runs if the first half found a routable endpoint and a
client cert. Everything is best-effort: a section that cannot be read reports
why in ``errors`` instead of failing the request.
"""

from __future__ import annotations

import base64
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

from core.cache import cache
from services.nico.constants import (
    ADMIN_CERT_SECRET,
    DEFAULT_NAMESPACE,
    DEPENDENCIES,
    ENDPOINT_PREFERENCE,
    FORGE_ENDPOINT_KEY,
    FORGE_TIMEOUT,
    NICO_API_LABEL,
    NICO_GRPC_PORT,
    NICO_SERVICE,
    PROVIDER_ENV_KEYS,
    PROVIDER_LABEL,
    TUNNEL_TIMEOUT,
    WEB_AUTH_ENV,
)
from services.nico.forge import ForgeClient, tcp_reachable
from services.nico.tunnel import TunnelError, forge_tunnel

logger = logging.getLogger(__name__)

# Bounded read of the deployment side. Discovery already walks unreachable
# clusters; this must fail fast rather than hold the request open.
_K8S_TIMEOUT = (3, 8)

# How many log lines of an LB provider to scan for its recent complaints, and
# how many of those to keep. The Logs tab is where a full read belongs — this
# is only here so "the operator has been failing for six days" is visible on
# the page that says the operator is Running.
_LOG_TAIL_LINES = 200
_MAX_RECENT_ERRORS = 5

# How long a resolved endpoint is reused. Long enough for the inventory request
# that follows a deployment request to skip the TCP screen, short enough that
# the next poll re-checks routability.
_ENDPOINT_TTL = 20

# The Rust operators colourise their logs even when stdout is not a terminal,
# so every line arrives wrapped in SGR escapes. They render as literal garbage
# in HTML.
_ANSI = re.compile(r"\x1b\[[0-9;]*m")


# ---------------------------------------------------------------------------
# Kubernetes side — how NICo is deployed
# ---------------------------------------------------------------------------

def _pod_summary(pod) -> dict[str, Any]:
    """One pod as the UI shows it: identity, readiness, restarts, age."""
    statuses = pod.status.container_statuses or []
    ready = sum(1 for c in statuses if c.ready)
    restarts = sum(c.restart_count or 0 for c in statuses)
    created = pod.metadata.creation_timestamp
    return {
        "name": pod.metadata.name,
        "namespace": pod.metadata.namespace,
        "phase": pod.status.phase,
        "ready": ready,
        "containers": len(statuses),
        "restarts": restarts,
        "node": pod.spec.node_name,
        "image": statuses[0].image if statuses else None,
        "createdAt": created.isoformat() if created else None,
    }


def _find_pods(core_api, label: str) -> list:
    """Running-or-not pods matching a label, in any namespace.

    Namespace-agnostic on purpose: nico-api's namespace is an install choice
    (`nico-system` by default), and hard-coding it would miss a lab that put it
    somewhere else. Completed Jobs carrying the same chart labels are dropped —
    `nico-api-migrate` is one, and it is not the API.
    """
    try:
        pods = core_api.list_pod_for_all_namespaces(
            label_selector=label, limit=50, _request_timeout=_K8S_TIMEOUT
        )
    except Exception as exc:  # noqa: BLE001 — a denied list is a soft failure
        logger.debug("NICo pod probe %r failed: %s", label, exc)
        return []
    return [p for p in pods.items if p.status.phase not in ("Succeeded", "Failed")]


def _deployment_env(apps_api, namespace: str, name: str) -> dict[str, str]:
    """Container-0 env of a Deployment, as a flat name→value map."""
    try:
        dep = apps_api.read_namespaced_deployment(
            name=name, namespace=namespace, _request_timeout=_K8S_TIMEOUT
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("read deployment %s/%s failed: %s", namespace, name, exc)
        return {}
    containers = dep.spec.template.spec.containers or []
    if not containers:
        return {}
    return {e.name: e.value for e in (containers[0].env or []) if e.value is not None}


def _recent_errors(core_api, namespace: str, pod_name: str) -> list[str]:
    """The last few WARN/ERROR lines from a pod's log tail.

    A provider that cannot reach NICo stays `Running` and `1/1 Ready` forever —
    the only symptom is in its log. Surfacing a handful of lines is the
    difference between "the operator is up" and "the operator is up and has not
    talked to NICo since Tuesday".
    """
    try:
        raw = core_api.read_namespaced_pod_log(
            name=pod_name,
            namespace=namespace,
            tail_lines=_LOG_TAIL_LINES,
            _request_timeout=_K8S_TIMEOUT,
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("log read %s/%s failed: %s", namespace, pod_name, exc)
        return []
    hits = [
        _ANSI.sub("", line).strip()
        for line in raw.splitlines()
        if "ERROR" in line or "WARN" in line
    ]
    return hits[-_MAX_RECENT_ERRORS:]


def _forge_services(core_api, namespace: str, pod_labels: dict[str, str]) -> list:
    """Services in `namespace` that select the nico-api pod, best-ranked first.

    By selector rather than by name, because the Service that carries a
    routable address is not necessarily the one called `nico-api` — a vanilla
    site adds a `nico-api-external` LoadBalancer alongside the ClusterIP, and
    only the second is reachable from outside the cluster.
    """
    try:
        services = core_api.list_namespaced_service(
            namespace=namespace, _request_timeout=_K8S_TIMEOUT
        )
    except Exception as exc:  # noqa: BLE001 — a denied list is a soft failure
        logger.debug("Service list in %s failed: %s", namespace, exc)
        return []

    matched = [
        svc
        for svc in services.items
        if (svc.spec.selector or {})
        and all(pod_labels.get(k) == v for k, v in svc.spec.selector.items())
    ]
    # LoadBalancer before NodePort before ClusterIP, then the canonically-named
    # Service first so the ordering is stable across reads.
    rank = {"LoadBalancer": 0, "NodePort": 1}
    return sorted(
        matched,
        key=lambda s: (
            rank.get(s.spec.type, 2),
            s.metadata.name != NICO_SERVICE,
            s.metadata.name,
        ),
    )


def _grpc_port(svc):
    """The port on `svc` that carries Forge, or None if it exposes none.

    Matched on the in-cluster target rather than the published port: an
    external Service commonly republishes 1079 as 443, so `port` alone
    identifies the wrong thing.
    """
    ports = svc.spec.ports or []
    for port in ports:
        if NICO_GRPC_PORT in (port.port, port.target_port):
            return port
    return ports[0] if ports else None


def _service_endpoints(
    core_api,
    namespace: str,
    api_server: str | None,
    pod_labels: dict[str, str] | None = None,
    api_pod: str | None = None,
    override: str | None = None,
) -> dict[str, Any]:
    """Where the Forge API can actually be dialled from here.

    Mirrors what `tmmlbctl` does, and for the same reason: the address a Service
    advertises is not always one this host can route to. Candidates are gathered
    from every Service that selects the nico-api pod, ranked by
    ``ENDPOINT_PREFERENCE``, TCP-screened, and the first that answers wins.

    Four kinds of candidate, in that ranked order:

    * ``override``    — an address the operator supplied. Screened like any
      other, because a stale one should say so rather than fail obscurely.
    * ``loadbalancer``/``nodeport`` — advertised addresses, direct dial.
    * ``portforward`` — the apiserver tunnel ([`services.nico.tunnel`]). Not
      screened: it is reachable exactly when the apiserver is, which every
      other read on this page has already proven. Carries no address of its own
      — ``tunnel`` names the pod, and the caller opens it around the session.

    ``webUi`` names the admin UI, which NICo serves on the same listener as
    gRPC. It is reported alongside ``webUiReachable``, and the distinction
    matters: an advertised address that failed its TCP screen is almost
    certainly dead for the operator's browser too — bnkscope binds loopback, so
    that browser is on this host — and offering it as a live link sends them
    into a timeout. When nothing is reachable, ``portForward`` carries the
    command that makes the UI reachable instead.
    """
    out: dict[str, Any] = {
        "kind": None,
        "host": None,
        "port": None,
        "reachable": False,
        "candidates": [],
        "grpc": None,
        "webUi": None,
        "webUiReachable": False,
        "portForward": None,
        "detail": None,
        "tunnel": None,
    }

    candidates: list[dict[str, Any]] = []
    if override:
        # The route validates the shape, but `meta_data` is a free-form JSON
        # column — a hand-edited or older value must not take the whole fetch
        # down with it.
        host, _, port = override.rpartition(":")
        if host and port.isdigit():
            candidates.append({"host": host, "port": int(port), "via": "override"})
        else:
            logger.info("ignoring malformed NICo endpoint override %r", override)

    services = _forge_services(core_api, namespace, pod_labels or {})
    if not services and not candidates:
        out["detail"] = (
            f"no Service in {namespace} selects the nico-api pod"
            if pod_labels
            else "no running nico-api pod to resolve a Service against"
        )

    # How to reach the admin UI by hand when no advertised address answers.
    # A Service outlives the pods behind it, so it is the better target; the
    # pod is the fallback for a Service that republishes the port.
    forward_target = next(
        (f"svc/{svc.metadata.name}" for svc in services
         if any(p.port == NICO_GRPC_PORT for p in (svc.spec.ports or []))),
        f"pod/{api_pod}" if api_pod else None,
    )
    if forward_target:
        out["portForward"] = {
            "command": (
                f"kubectl port-forward -n {namespace} {forward_target} "
                f"{NICO_GRPC_PORT}:{NICO_GRPC_PORT}"
            ),
            "webUi": f"https://127.0.0.1:{NICO_GRPC_PORT}/admin/",
            "endpoint": f"127.0.0.1:{NICO_GRPC_PORT}",
        }

    node = urlparse(api_server).hostname if api_server else None
    for svc in services:
        port = _grpc_port(svc)
        if port is None:
            continue
        ingress = (
            svc.status.load_balancer.ingress
            if svc.status and svc.status.load_balancer
            else None
        ) or []
        for ing in ingress:
            host = ing.ip or ing.hostname
            if host:
                candidates.append(
                    {"host": host, "port": port.port, "via": "loadbalancer",
                     "service": svc.metadata.name}
                )
        if port.node_port and node:
            candidates.append(
                {"host": node, "port": port.node_port, "via": "nodeport",
                 "service": svc.metadata.name}
            )

    # The tunnel needs a pod, not an address, so it is a candidate without a
    # host — ordered last and never TCP-screened.
    if api_pod:
        candidates.append(
            {"host": None, "port": NICO_GRPC_PORT, "via": "portforward",
             "pod": api_pod}
        )

    order = {via: i for i, via in enumerate(ENDPOINT_PREFERENCE)}
    candidates.sort(key=lambda c: order.get(c["via"], len(order)))
    out["candidates"] = candidates

    direct = [c for c in candidates if c["host"]]
    # The best advertised address, recorded whether or not it answers. Whether
    # it is offered as a link is decided below, by whether it screened.
    if direct:
        first = direct[0]
        out["webUi"] = f"https://{first['host']}:{first['port']}/admin/"

    # Screened concurrently, then picked by rank — not first-to-answer. An
    # unroutable address on a lab subnet black-holes for the full REACH_TIMEOUT
    # rather than refusing, so screening in sequence cost one timeout per
    # candidate: measured at ~2.9s of the deployment read for the two this lab
    # advertises, both of which time out. Concurrently it is one timeout total.
    winner = None
    if direct:
        with ThreadPoolExecutor(max_workers=len(direct)) as pool:
            reachable = list(
                pool.map(lambda c: tcp_reachable(c["host"], c["port"]), direct)
            )
        winner = next((c for c, ok in zip(direct, reachable) if ok), None)

    if winner is not None:
        out.update(
            host=winner["host"],
            port=winner["port"],
            kind=winner["via"],
            reachable=True,
            grpc=f"{winner['host']}:{winner['port']}",
            # The winner answered a TCP connect from this host, so the browser
            # on the same host can reach it too.
            webUi=f"https://{winner['host']}:{winner['port']}/admin/",
            webUiReachable=True,
        )
        return out

    # The tunnel is ranked last in ENDPOINT_PREFERENCE, so it is only reached
    # once every advertised address has failed its screen.
    tunnel = next((c for c in candidates if c["via"] == "portforward"), None)
    if tunnel is not None:
        out.update(
            kind="portforward",
            reachable=True,
            grpc=f"{namespace}/{tunnel['pod']}:{tunnel['port']} (apiserver tunnel)",
            tunnel={"pod": tunnel["pod"], "port": tunnel["port"]},
            detail=(
                "no advertised address is routable from here — dialling "
                "through the apiserver"
                if direct
                else "ClusterIP only — dialling through the apiserver"
            ),
        )
        return out

    if direct:
        first = direct[0]
        out.update(
            host=first["host"],
            port=first["port"],
            grpc=f"{first['host']}:{first['port']}",
            detail="advertised but not routable from here",
        )
    elif not out["detail"]:
        out["detail"] = (
            "ClusterIP only, and the apiserver tunnel is unavailable — expose "
            "nico-api on a NodePort, or set an endpoint override"
        )
    return out


def _client_certs(core_api, namespace: str) -> tuple[dict[str, bytes] | None, dict[str, Any]]:
    """The mTLS client cert for the Forge API, plus what it says about itself.

    Reported even when it parses cleanly: this is a cert-manager Secret with a
    finite lifetime, and an expired one turns every Forge call into a handshake
    failure with no other symptom.
    """
    info: dict[str, Any] = {"secret": ADMIN_CERT_SECRET, "present": False}
    try:
        secret = core_api.read_namespaced_secret(
            name=ADMIN_CERT_SECRET, namespace=namespace, _request_timeout=_K8S_TIMEOUT
        )
    except Exception as exc:  # noqa: BLE001
        info["detail"] = f"not readable: {exc}"
        return None, info

    data = secret.data or {}
    try:
        material = {k: base64.b64decode(data[k]) for k in ("ca.crt", "tls.crt", "tls.key")}
    except KeyError as exc:
        info["detail"] = f"missing key {exc} — was the cert minted?"
        return None, info

    info["present"] = True
    try:
        from cryptography import x509

        cert = x509.load_pem_x509_certificate(material["tls.crt"])
        not_after = cert.not_valid_after_utc
        info["subject"] = cert.subject.rfc4514_string()
        info["issuer"] = cert.issuer.rfc4514_string()
        info["notAfter"] = not_after.isoformat()
        info["daysLeft"] = (not_after - datetime.now(UTC)).days
    except Exception as exc:  # noqa: BLE001 — an unparseable cert still dials
        logger.debug("client cert parse failed: %s", exc)
        info["detail"] = f"certificate not parseable: {exc}"
    return material, info


def _version_banner(host: str, port: int) -> str | None:
    """nico-api's version, from the HTTP root the admin UI is served on.

    Same listener as gRPC and, deliberately, no client cert: the banner has to
    be readable even when the mTLS Secret is the thing that is broken. Two
    consequences of sharing that listener: TLS is self-signed by NICo's own
    local CA (`verify=False`), and the socket speaks HTTP/2 only — an
    HTTP/1.1 request gets an SSL error rather than a response.
    """
    import httpx

    try:
        with httpx.Client(verify=False, timeout=5.0, http2=True) as client:
            resp = client.get(f"https://{host}:{port}/")
        first = resp.text.splitlines()[0].strip() if resp.text else ""
        return first or None
    except Exception as exc:  # noqa: BLE001
        logger.debug("version banner from %s:%s failed: %s", host, port, exc)
        return None


def _dpu_counts(k8s_service, api_client, cluster_id: int) -> dict[str, int]:
    """DPUs on this cluster, from DPF's own CRs.

    NICo has a DPU inventory of its own and it is empty here: this lab
    provisions through DPF Zero-Touch, not NICo's fleet-provisioning pipeline.
    Showing DPF's count next to NICo's zero is what makes that read as a design
    choice rather than a fault.

    Runs on the calling thread, never the pool below: ``_safe_fetch`` resolves
    the CRD through the request-scoped SQLAlchemy Session, which is not
    thread-safe.
    """
    from services.dpf.fetch import _safe_fetch

    dpus = _safe_fetch(k8s_service, api_client, cluster_id, "dpu")
    ready = sum(
        1
        for d in dpus
        if str((d.get("status") or {}).get("phase", "")).lower() == "ready"
    )
    return {"total": len(dpus), "ready": ready}


# ---------------------------------------------------------------------------
# Forge side — what NICo holds
# ---------------------------------------------------------------------------

def _ids(payload: dict, key: str) -> list[dict]:
    """Forge id lists are `[{"value": "<uuid>"}]`; keep them in that shape.

    The paired `…ByIds` call wants exactly what the `Find…Ids` call returned,
    so unwrapping and rewrapping only creates a chance to get it wrong.
    """
    return [i for i in payload.get(key, []) if isinstance(i, dict)]


def _lifecycle_state(obj: dict) -> str | None:
    """The one readable state field out of Forge's three overlapping ones.

    Objects carry `state`, `status.tenantState` and a JSON-in-a-string
    `status.lifecycle.state`. The first two agree when both are set; the third
    is the fallback for objects that only fill the lifecycle block.
    """
    status = obj.get("status") or {}
    for value in (obj.get("state"), status.get("tenantState")):
        if value:
            return value
    raw = ((status.get("lifecycle") or {}).get("state")) or ""
    if raw.startswith("{"):
        import json

        try:
            return json.loads(raw).get("state")
        except ValueError:
            return None
    return raw or None


def _fetch_vpcs(client: ForgeClient) -> list[dict[str, Any]]:
    """Every VPC with its tenant, VNI and VIP prefixes.

    Three round trips per VPC set, not one: Forge pairs `FindVpcIds` with
    `FindVpcsByIds`, and the prefixes hang off a separate `SearchVpcPrefixes`
    that filters by VPC — `GetVpcPrefixes` takes prefix ids, so it cannot be
    called cold.
    """
    ids = _ids(client.try_call("FindVpcIds"), "vpcIds")
    if not ids:
        return []
    listed = client.try_call("FindVpcsByIds", {"vpcIds": ids})
    out = []
    for vpc in listed.get("vpcs", []):
        vpc_id = (vpc.get("id") or {}).get("value", "")
        config = vpc.get("config") or {}
        out.append(
            {
                "id": vpc_id,
                "tenant": config.get("tenantOrganizationId") or vpc.get("tenantOrganizationId") or "",
                "vni": (vpc.get("status") or {}).get("vni") or vpc.get("deprecatedVni"),
                "virtualizationType": config.get("networkVirtualizationType")
                or vpc.get("networkVirtualizationType"),
                "state": _lifecycle_state(vpc),
                "created": vpc.get("created"),
                "updated": vpc.get("updated"),
                "prefixes": _fetch_vpc_prefixes(client, vpc_id),
            }
        )
    return out


def _fetch_vpc_prefixes(client: ForgeClient, vpc_id: str) -> list[dict[str, Any]]:
    """One VPC's VIP prefixes — the range its load balancers allocate from."""
    if not vpc_id:
        return []
    found = client.try_call("SearchVpcPrefixes", {"vpcId": {"value": vpc_id}})
    ids = _ids(found, "vpcPrefixIds")
    if not ids:
        return []
    listed = client.try_call("GetVpcPrefixes", {"vpcPrefixIds": ids})
    out = []
    for pfx in listed.get("vpcPrefixes", []):
        status = pfx.get("status") or {}
        out.append(
            {
                "id": (pfx.get("id") or {}).get("value", ""),
                "prefix": pfx.get("prefix") or (pfx.get("config") or {}).get("prefix"),
                "total": status.get("total31Segments") or pfx.get("total31Segments"),
                "available": status.get("available31Segments") or pfx.get("available31Segments"),
                "state": _lifecycle_state(pfx),
            }
        )
    return out


def _fetch_segments(client: ForgeClient) -> list[dict[str, Any]]:
    """Network segments — the underlay/overlay networks NICo owns."""
    ids = _ids(client.try_call("FindNetworkSegmentIds"), "networkSegmentsIds")
    if not ids:
        return []
    listed = client.try_call("FindNetworkSegmentsByIds", {"networkSegmentsIds": ids})
    out = []
    for seg in listed.get("networkSegments", []):
        out.append(
            {
                "id": (seg.get("id") or {}).get("value", ""),
                "name": seg.get("name") or (seg.get("metadata") or {}).get("name"),
                "type": seg.get("segmentType"),
                "mtu": seg.get("mtu"),
                "flags": seg.get("flags") or [],
                "state": _lifecycle_state(seg),
                "prefixes": [
                    {
                        "prefix": p.get("prefix"),
                        "gateway": p.get("gateway"),
                        "reserveFirst": p.get("reserveFirst"),
                    }
                    for p in seg.get("prefixes", [])
                ],
            }
        )
    return out


def _fetch_load_balancers(client: ForgeClient) -> list[dict[str, Any]]:
    """Every tenant load balancer NICo has been asked for, config and status.

    This is the whole point of the tab: the VIP, what it fronts, whether the
    dataplane has actually been programmed with it, and on how many TMM pods.
    """
    ids = _ids(client.try_call("SearchLoadBalancerServices"), "loadBalancerServiceIds")
    if not ids:
        return []
    listed = client.try_call("GetLoadBalancerServices", {"loadBalancerServiceIds": ids})
    out = []
    for lb in listed.get("loadBalancerServices", []):
        config = lb.get("config") or {}
        status = lb.get("status") or {}
        meta = lb.get("metadata") or {}
        out.append(
            {
                "id": (lb.get("id") or {}).get("value", ""),
                "name": meta.get("name") or "",
                "description": meta.get("description"),
                "labels": {
                    lbl.get("key"): lbl.get("value") for lbl in meta.get("labels", [])
                },
                "tenant": config.get("tenantOrganizationId") or "",
                "vpcId": (config.get("vpcId") or {}).get("value"),
                "vipSegmentId": (config.get("vipSegmentId") or {}).get("value"),
                "provider": config.get("provider"),
                "vip": status.get("vipAddress") or config.get("vipAddress"),
                # LB_DEPLOYMENT_STATUS_READY reads as noise in a table; the enum
                # prefix is constant across every value it can take.
                "status": str(status.get("deploymentStatus") or "")
                .replace("LB_DEPLOYMENT_STATUS_", "") or None,
                "programmedPods": status.get("programmedPods"),
                "declTmmGeneration": status.get("declTmmGeneration"),
                "created": lb.get("created"),
                "updated": lb.get("updated"),
                "listeners": [
                    {
                        "name": ln.get("name"),
                        "port": ln.get("port"),
                        "protocol": str(ln.get("protocol") or "").replace("LB_PROTOCOL_", ""),
                        "poolName": ln.get("poolName"),
                    }
                    for ln in config.get("listeners", [])
                ],
                "pools": [
                    {
                        "name": pool.get("name"),
                        "lbMethod": str(pool.get("lbMethod") or "").replace("LB_METHOD_", ""),
                        "minActiveMembers": pool.get("minActiveMembers"),
                        "members": [
                            {"address": m.get("address"), "port": m.get("port")}
                            for m in pool.get("members", [])
                        ],
                        "monitors": [
                            {
                                "name": mon.get("name"),
                                "type": str(mon.get("type") or "").replace("LB_MONITOR_TYPE_", ""),
                                "intervalSec": mon.get("intervalSec"),
                                "timeoutSec": mon.get("timeoutSec"),
                                "send": mon.get("send"),
                                "recv": mon.get("recv"),
                            }
                            for mon in pool.get("monitors", [])
                        ],
                    }
                    for pool in config.get("pools", [])
                ],
            }
        )
    return out


def _roll_up_tenants(vpcs: list[dict], lbs: list[dict]) -> list[dict[str, Any]]:
    """Tenants, derived rather than listed.

    NICo's Tenant table is unused in this deployment — `provision-tenant` only
    creates VPCs — so `FindTenantOrganizationIds` comes back empty while three
    tenants plainly exist. The tenant is whatever owns a VPC or a load
    balancer, which is the same rule `tmmlbctl` applies.
    """
    names = sorted(
        {v["tenant"] for v in vpcs if v["tenant"]}
        | {lb["tenant"] for lb in lbs if lb["tenant"]}
    )
    out = []
    for name in names:
        mine = [v for v in vpcs if v["tenant"] == name]
        my_lbs = [lb for lb in lbs if lb["tenant"] == name]
        out.append(
            {
                "id": name,
                "vpcCount": len(mine),
                "vpcIds": [v["id"] for v in mine],
                "vnis": [v["vni"] for v in mine if v["vni"]],
                "vipPrefixes": [p["prefix"] for v in mine for p in v["prefixes"] if p["prefix"]],
                "lbCount": len(my_lbs),
                "vips": [lb["vip"] for lb in my_lbs if lb["vip"]],
                "lbsReady": sum(1 for lb in my_lbs if lb["status"] == "READY"),
            }
        )
    return out


def _fetch_inventory(client: ForgeClient) -> dict[str, Any]:
    """Everything NICo holds, in one session."""
    vpcs = _fetch_vpcs(client)
    lbs = _fetch_load_balancers(client)
    return {
        "tenants": _roll_up_tenants(vpcs, lbs),
        "vpcs": vpcs,
        "networkSegments": _fetch_segments(client),
        "loadBalancers": lbs,
        "domains": [
            {
                "id": (d.get("id") or {}).get("value", ""),
                "zone": d.get("zone"),
                "kind": d.get("kind"),
                "serial": d.get("serial"),
            }
            for d in client.try_call("GetAllDomains").get("result", [])
        ],
        "dpfServiceVersions": client.try_call("GetDPFServiceVersions").get("services", []),
        # NICo's fleet tables. Empty in a DPF Zero-Touch lab, and worth saying
        # so explicitly — an empty /admin/machine page otherwise reads as a bug.
        "fleet": {
            "machines": len(_ids(client.try_call("FindMachineIds"), "machineIds")),
            "switches": len(_ids(client.try_call("FindSwitchIds"), "switchIds")),
            "racks": len(_ids(client.try_call("FindRackIds"), "rackIds")),
            "instances": len(_ids(client.try_call("FindInstanceIds"), "instanceIds")),
        },
    }


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------

def detect_nico(k8s_service, cluster_id: int) -> dict[str, Any]:
    """Is NICo deployed on this cluster? One labelled pod list, nothing more.

    The counterpart of ``services.dpf.fetch.detect_dpf``'s cheap path: gating
    the tab must not cost a Forge session on every cluster in the list.
    """
    from kubernetes import client as k8s_client

    cluster = k8s_service.get_cluster(cluster_id)
    api_client = k8s_service.load_kubeconfig(cluster)
    core_api = k8s_client.CoreV1Api(api_client)

    pods = _find_pods(core_api, NICO_API_LABEL)
    providers = _find_pods(core_api, PROVIDER_LABEL)
    return {
        "detected": bool(pods),
        "namespace": pods[0].metadata.namespace if pods else None,
        "apiPods": len(pods),
        "providerPods": len(providers),
        "cluster_id": cluster_id,
    }


def _schema_key(pod) -> str | None:
    """The nico-api build whose Forge schema a session will read.

    The container's ``imageID`` — a digest — and deliberately not its ``image``.
    A NICo built from a moving tag rather than a release is normal, and keying a
    schema cache on the tag would keep serving the old descriptors across an
    in-place rebuild of that tag. No digest, no key, and the session walks
    reflection as before.

    ``pod`` is None when nothing is Running: an advertised endpoint can still
    be dialled in that state, so this is a real case and not a guard for an
    impossible one.
    """
    if pod is None:
        return None
    for status in pod.status.container_statuses or []:
        if status.image_id:
            return status.image_id
    return None


def _read_inventory(
    core_api,
    namespace: str,
    endpoint: dict[str, Any],
    material: dict[str, bytes],
    schema_key: str | None = None,
) -> dict[str, Any]:
    """Open one Forge session against the winning endpoint and read it dry.

    The two transports differ only in what address gets dialled, so the tunnel
    is opened around the same session rather than duplicating it. Its lifetime
    is this call: nothing stays open between polls.
    """

    def session(address: str, timeout: float) -> dict[str, Any]:
        with ForgeClient(
            address=address,
            # Whatever we dial, the cert is minted for the in-cluster name.
            server_name=f"{NICO_SERVICE}.{namespace}.svc.cluster.local",
            ca=material["ca.crt"],
            cert=material["tls.crt"],
            key=material["tls.key"],
            timeout=timeout,
            schema_key=schema_key,
        ) as client:
            return _fetch_inventory(client)

    tunnel = endpoint.get("tunnel")
    if not tunnel:
        return session(endpoint["grpc"], FORGE_TIMEOUT)
    with forge_tunnel(core_api, namespace, tunnel["pod"], tunnel["port"]) as address:
        return session(address, TUNNEL_TIMEOUT)


def _resolved_endpoint(
    core_api, cluster, namespace: str, pod_labels: dict, pod: str | None, override
) -> dict[str, Any]:
    """[`_service_endpoints`], memoized for a few seconds per nico-api pod.

    Resolution is the most expensive read on the deployment side — measured at
    ~2.9s on the reference lab, almost all of it TCP-screening two advertised
    addresses that time out. Both halves of the split fetch need the answer, so
    without this the inventory request would pay it a second time.

    Keyed on the pod, not just the cluster: a replaced nico-api invalidates the
    entry rather than leaving the tunnel pointed at a pod that no longer exists.
    The TTL is short enough that a routing change is picked up on the next poll.
    """
    key = f"nico:endpoint:{cluster.id}:{pod or '-'}"
    hit = cache.get(key)
    if hit is not None:
        return dict(hit)  # copied: callers flip `reachable` on a tunnel failure
    out = _service_endpoints(
        core_api, namespace, cluster.api_server, pod_labels, pod, override
    )
    cache.set(key, out, ttl_seconds=_ENDPOINT_TTL)
    return dict(out)


def fetch_nico_deployment(k8s_service, cluster_id: int) -> dict[str, Any]:
    """The Kubernetes half: how NICo is deployed, and where its API is.

    Split from the inventory because the two have very different costs. This
    side is ~6s and *stable* — a bounded set of Kubernetes reads. The Forge
    side swings from ~2s warm to ~30s on a cold descriptor cache or a bad VPN
    moment. Returning them separately means the page is usable at a predictable
    ~6s regardless of the Forge weather, instead of every render waiting on the
    slowest read.

    Never raises for a section it cannot read.
    """
    from kubernetes import client as k8s_client

    cluster = k8s_service.get_cluster(cluster_id)
    api_client = k8s_service.load_kubeconfig(cluster)
    core_api = k8s_client.CoreV1Api(api_client)
    apps_api = k8s_client.AppsV1Api(api_client)

    errors: list[str] = []
    api_pods = _find_pods(core_api, NICO_API_LABEL)
    provider_pods = _find_pods(core_api, PROVIDER_LABEL)
    namespace = api_pods[0].metadata.namespace if api_pods else DEFAULT_NAMESPACE

    # Only a Running pod can carry a tunnel, and only its labels can tell us
    # which Services front it.
    running = next((p for p in api_pods if p.status.phase == "Running"), None)
    pod_labels = dict(running.metadata.labels or {}) if running else {}
    override = (cluster.meta_data or {}).get(FORGE_ENDPOINT_KEY)

    # The Kubernetes reads are independent of each other and each costs a round
    # trip to a cluster that may be several hops away.
    with ThreadPoolExecutor(max_workers=5) as pool:
        endpoint_f = pool.submit(
            _resolved_endpoint,
            core_api,
            cluster,
            namespace,
            pod_labels,
            running.metadata.name if running else None,
            override,
        )
        certs_f = pool.submit(_client_certs, core_api, namespace)
        env_f = pool.submit(_deployment_env, apps_api, namespace, NICO_SERVICE)
        deps_f = pool.submit(_dependencies, core_api)
        providers_f = pool.submit(_providers, core_api, apps_api, provider_pods)

    # Not in the pool: this one resolves a CRD through the DB session.
    dpus = _dpu_counts(k8s_service, api_client, cluster_id)

    endpoint = endpoint_f.result()
    _material, cert_info = certs_f.result()
    api_env = env_f.result()

    control_plane = {
        "namespace": namespace,
        "pods": [_pod_summary(p) for p in api_pods],
        "webAuth": api_env.get(WEB_AUTH_ENV) or "none",
        "mtls": cert_info,
        "version": None,
    }
    if endpoint["reachable"] and endpoint["host"]:
        control_plane["version"] = _version_banner(endpoint["host"], endpoint["port"])

    if not api_pods:
        errors.append("nico-api is not running on this cluster")
    elif not endpoint["reachable"]:
        errors.append(
            f"Forge API not reachable: {endpoint.get('detail') or 'no routable endpoint'}"
        )

    return {
        "detected": bool(api_pods),
        "cluster_id": cluster_id,
        "controlPlane": control_plane,
        "endpoint": endpoint,
        "providers": providers_f.result(),
        "dependencies": deps_f.result(),
        "dpf": dpus,
        "errors": errors,
    }


def fetch_nico_inventory(k8s_service, cluster_id: int) -> dict[str, Any]:
    """The Forge half: everything NICo holds, and nothing about how it is run.

    Reads only what dialling needs — the pod (for the namespace, the tunnel
    target and the schema key), the endpoint (memoized by the deployment call
    that precedes it) and the client certificate. Deliberately *not* the
    dependencies, providers, Deployment env or DPU counts: those belong to the
    other half and re-reading them here would hand back the latency the split
    was made to remove.
    """
    from kubernetes import client as k8s_client

    cluster = k8s_service.get_cluster(cluster_id)
    api_client = k8s_service.load_kubeconfig(cluster)
    core_api = k8s_client.CoreV1Api(api_client)

    errors: list[str] = []
    api_pods = _find_pods(core_api, NICO_API_LABEL)
    if not api_pods:
        return {
            "cluster_id": cluster_id,
            "inventory": {},
            "errors": ["nico-api is not running on this cluster"],
        }

    namespace = api_pods[0].metadata.namespace
    running = next((p for p in api_pods if p.status.phase == "Running"), None)
    pod_labels = dict(running.metadata.labels or {}) if running else {}
    override = (cluster.meta_data or {}).get(FORGE_ENDPOINT_KEY)

    with ThreadPoolExecutor(max_workers=2) as pool:
        endpoint_f = pool.submit(
            _resolved_endpoint,
            core_api,
            cluster,
            namespace,
            pod_labels,
            running.metadata.name if running else None,
            override,
        )
        certs_f = pool.submit(_client_certs, core_api, namespace)

    endpoint = endpoint_f.result()
    material, cert_info = certs_f.result()

    inventory: dict[str, Any] = {}
    if not endpoint["reachable"]:
        errors.append(
            f"Forge API not reachable: {endpoint.get('detail') or 'no routable endpoint'}"
        )
    elif material is None:
        errors.append(
            f"no client certificate: {cert_info.get('detail', 'secret missing')}"
        )
    else:
        try:
            inventory = _read_inventory(
                core_api, namespace, endpoint, material, _schema_key(running)
            )
        except TunnelError as exc:
            # The listener could not be opened, or the apiserver refused the
            # portforward subresource — a restricted kubeconfig can lack it.
            logger.info("NICo tunnel unavailable on cluster %s: %s", cluster_id, exc)
            errors.append(f"Forge API not reachable: apiserver tunnel failed: {exc}")
        except Exception as exc:  # noqa: BLE001 — the deployment view still stands
            logger.info("NICo inventory unavailable on cluster %s: %s", cluster_id, exc)
            errors.append(f"Forge inventory unavailable: {exc}")

    return {"cluster_id": cluster_id, "inventory": inventory, "errors": errors}


def fetch_all_nico_data(k8s_service, cluster_id: int) -> dict[str, Any]:
    """Both halves in one response — the shape this endpoint has always had.

    Composed from the two rather than a third code path. It costs one extra pod
    list and certificate read over the old single pass, which is the right
    trade now that the UI drives the halves separately and this exists for
    callers that want the whole picture in one request.
    """
    deployment = fetch_nico_deployment(k8s_service, cluster_id)
    if not deployment["detected"]:
        return {**deployment, "inventory": {}}

    inventory = fetch_nico_inventory(k8s_service, cluster_id)
    endpoint = deployment["endpoint"]
    # A tunnel that failed to open is only discovered by the half that dials.
    if inventory["errors"] and not inventory["inventory"]:
        if any("not reachable" in e for e in inventory["errors"]):
            endpoint["reachable"] = False

    seen = set(deployment["errors"])
    return {
        **deployment,
        "inventory": inventory["inventory"],
        "errors": deployment["errors"] + [e for e in inventory["errors"] if e not in seen],
    }


def _dependencies(core_api) -> list[dict[str, Any]]:
    """The stores a NICo site runs on: its Postgres, its Vault, its workflows.

    Each entry reports which selector actually matched, so a dependency found
    by its fallback — or not found at all — says so rather than looking like a
    clean read of nothing.

    Probed concurrently: this is three labelled pod lists across the cluster
    (more, when a fallback fires), and run in sequence they cost ~3-4s over a
    VPN — enough to become the slowest thing in the deployment read.
    """
    with ThreadPoolExecutor(max_workers=len(DEPENDENCIES)) as pool:
        found = list(pool.map(lambda d: _dependency_pods(core_api, d), DEPENDENCIES))

    return [
        {
            "name": dep["name"],
            "namespace": dep["namespace"],
            "selector": selector,
            "pods": [
                {**_pod_summary(p), "labels": _kept_labels(p, dep["pod_labels"])}
                for p in pods
            ],
        }
        for dep, (pods, selector) in zip(DEPENDENCIES, found)
    ]


def _dependency_pods(core_api, dep: dict) -> tuple[list, str | None]:
    """First selector in `dep` that matches anything, and what it matched.

    Preferring the namespace the dependency is expected in: the same chart
    labels in another namespace are somebody else's Postgres, but a site that
    moved it is better served by the wrong namespace than by nothing.
    """
    for selector in dep["selectors"]:
        pods = _find_pods(core_api, selector)
        if not pods:
            continue
        mine = [p for p in pods if p.metadata.namespace == dep["namespace"]]
        return (mine or pods), selector
    return [], None


def _kept_labels(pod, wanted: tuple[str, ...]) -> dict[str, str]:
    """The few labels worth showing on a dependency pod, when present.

    Vault publishes `vault-sealed` / `vault-initialized` / `vault-active` and
    spilo publishes `spilo-role`. Those answer "is this store actually usable",
    which readiness alone does not: a sealed Vault can be Running and Ready and
    still hand NICo nothing.
    """
    labels = pod.metadata.labels or {}
    return {k: labels[k] for k in wanted if k in labels}


def _providers(core_api, apps_api, pods: list) -> list[dict[str, Any]]:
    """The LB provider operators: what they claim, and what they are saying."""
    out = []
    for pod in pods:
        namespace = pod.metadata.namespace
        # The Deployment name is the pod name minus the ReplicaSet and pod
        # suffixes Kubernetes appends.
        owner = (pod.metadata.labels or {}).get("app") or pod.metadata.name
        env = _deployment_env(apps_api, namespace, owner)
        out.append(
            {
                "name": owner,
                "pod": _pod_summary(pod),
                "config": {k: env[k] for k in PROVIDER_ENV_KEYS if k in env},
                "recentErrors": _recent_errors(core_api, namespace, pod.metadata.name),
            }
        )
    return out
