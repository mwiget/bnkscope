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

from services.nico.constants import (
    ADMIN_CERT_SECRET,
    DEFAULT_NAMESPACE,
    DEPENDENCY_PODS,
    NICO_API_LABEL,
    NICO_GRPC_PORT,
    NICO_SERVICE,
    PROVIDER_ENV_KEYS,
    PROVIDER_LABEL,
    WEB_AUTH_ENV,
)
from services.nico.forge import ForgeClient, tcp_reachable

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


def _service_endpoints(core_api, namespace: str, api_server: str | None) -> dict[str, Any]:
    """Where the Forge API can actually be dialled from here.

    Mirrors what `tmmlbctl` does, and for the same reason: the address a Service
    advertises is not always one this host can route to. Candidates are ordered
    LoadBalancer-then-NodePort, TCP-screened, and the first that answers wins.
    A ClusterIP-only Service has no candidate at all — `tmmlbctl` falls back to
    a `kubectl port-forward` there, which a container with no kubectl cannot do,
    so that case is reported rather than worked around.
    """
    out: dict[str, Any] = {
        "kind": None,
        "host": None,
        "port": None,
        "reachable": False,
        "candidates": [],
        "grpc": None,
        "webUi": None,
        "detail": None,
    }
    try:
        svc = core_api.read_namespaced_service(
            name=NICO_SERVICE, namespace=namespace, _request_timeout=_K8S_TIMEOUT
        )
    except Exception as exc:  # noqa: BLE001
        out["detail"] = f"Service {namespace}/{NICO_SERVICE} not readable: {exc}"
        return out

    out["kind"] = svc.spec.type
    ports = svc.spec.ports or []
    grpc_port = next(
        (p for p in ports if p.port == NICO_GRPC_PORT), ports[0] if ports else None
    )
    if grpc_port is None:
        out["detail"] = f"Service {NICO_SERVICE} exposes no ports"
        return out

    candidates: list[tuple[str, int, str]] = []
    ingress = (svc.status.load_balancer.ingress if svc.status and svc.status.load_balancer else None) or []
    for ing in ingress:
        host = ing.ip or ing.hostname
        if host:
            candidates.append((host, grpc_port.port, "loadbalancer"))
    if grpc_port.node_port and api_server:
        node = urlparse(api_server).hostname
        if node:
            candidates.append((node, grpc_port.node_port, "nodeport"))

    out["candidates"] = [{"host": h, "port": p, "via": v} for h, p, v in candidates]
    if not candidates:
        out["detail"] = (
            f"{svc.spec.type} Service with no address reachable from here — "
            "expose nico-api on a NodePort to read the inventory"
        )
        return out

    for host, port, via in candidates:
        if tcp_reachable(host, port):
            out.update(
                host=host,
                port=port,
                kind=via,
                reachable=True,
                grpc=f"{host}:{port}",
                webUi=f"https://{host}:{port}/admin/",
            )
            return out

    first = candidates[0]
    out.update(
        host=first[0],
        port=first[1],
        grpc=f"{first[0]}:{first[1]}",
        webUi=f"https://{first[0]}:{first[1]}/admin/",
        detail="advertised but not routable from here",
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


def fetch_all_nico_data(k8s_service, cluster_id: int) -> dict[str, Any]:
    """The whole NICo picture: deployment from Kubernetes, inventory from Forge.

    Never raises for a section it cannot read. A NICo whose endpoint is
    unroutable still renders its pods, its Service and its certificate — with
    the reason the inventory is missing sitting next to them.
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

    # The Kubernetes reads are independent of each other and each costs a round
    # trip to a cluster that may be several hops away.
    with ThreadPoolExecutor(max_workers=5) as pool:
        endpoint_f = pool.submit(_service_endpoints, core_api, namespace, cluster.api_server)
        certs_f = pool.submit(_client_certs, core_api, namespace)
        env_f = pool.submit(_deployment_env, apps_api, namespace, NICO_SERVICE)
        deps_f = pool.submit(_dependencies, core_api)
        providers_f = pool.submit(_providers, core_api, apps_api, provider_pods)

    # Not in the pool: this one resolves a CRD through the DB session.
    dpus = _dpu_counts(k8s_service, api_client, cluster_id)

    endpoint = endpoint_f.result()
    material, cert_info = certs_f.result()
    api_env = env_f.result()

    control_plane = {
        "namespace": namespace,
        "pods": [_pod_summary(p) for p in api_pods],
        "webAuth": api_env.get(WEB_AUTH_ENV) or "none",
        "mtls": cert_info,
        "version": None,
    }
    if endpoint["reachable"]:
        control_plane["version"] = _version_banner(endpoint["host"], endpoint["port"])

    inventory: dict[str, Any] = {}
    if not api_pods:
        errors.append("nico-api is not running on this cluster")
    elif not endpoint["reachable"]:
        errors.append(
            f"Forge API not reachable: {endpoint.get('detail') or 'no routable endpoint'}"
        )
    elif material is None:
        errors.append(
            f"no client certificate: {cert_info.get('detail', 'secret missing')}"
        )
    else:
        try:
            with ForgeClient(
                address=endpoint["grpc"],
                server_name=f"{NICO_SERVICE}.{namespace}.svc.cluster.local",
                ca=material["ca.crt"],
                cert=material["tls.crt"],
                key=material["tls.key"],
            ) as client:
                inventory = _fetch_inventory(client)
        except Exception as exc:  # noqa: BLE001 — the deployment view still stands
            logger.info("NICo inventory unavailable on cluster %s: %s", cluster_id, exc)
            errors.append(f"Forge inventory unavailable: {exc}")

    return {
        "detected": bool(api_pods),
        "cluster_id": cluster_id,
        "controlPlane": control_plane,
        "endpoint": endpoint,
        "providers": providers_f.result(),
        "dependencies": deps_f.result(),
        "dpf": dpus,
        "inventory": inventory,
        "errors": errors,
    }


def _dependencies(core_api) -> list[dict[str, Any]]:
    """Postgres and Vault — NICo's datastore and its secret store."""
    out = []
    for name, namespace, label in DEPENDENCY_PODS:
        pods = _find_pods(core_api, label)
        # Same label in another namespace is somebody else's Postgres.
        mine = [p for p in pods if p.metadata.namespace == namespace] or pods
        out.append(
            {
                "name": name,
                "namespace": namespace,
                "pods": [_pod_summary(p) for p in mine],
            }
        )
    return out


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
