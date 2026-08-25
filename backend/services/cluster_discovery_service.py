"""Turn local kubeconfig contexts into registered clusters.

The rule, settled in the plan: **probe everything, register what has an F5/BNK
footprint.** A developer laptop has a dozen contexts — a kind cluster, two
staging clusters, somebody's demo — and bnkscope is a tool for looking at BNK.
Registering all twelve would bury the two that matter. So every context is
probed and reported, but only one with an F5 namespace on it is adopted
automatically. The rest are listed as candidates with a one-click add, and the
ones that cannot be adopted at all say why.

Discovery is idempotent and safe to re-run: a context already registered is
matched by its context name and refreshed in place, never duplicated. It runs
once at startup and on demand from the UI.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from core.background import submit
from core.encryption import encrypt_value
from models import KubernetesCluster
from services.kubeconfig_discovery import DiscoveredContext, discover_contexts

logger = logging.getLogger(__name__)

# What counts as "BNK lives here": the pods, found by label, in any namespace.
#
# Namespace names were the obvious first answer and the wrong one. They vary by
# install shape, and on a real DPF tenant cluster the f5-tmm pods sit in
# `dpf-operator-system` while `f5-cne-core` / `f5-utils` hold the control plane
# — so any namespace list is either too narrow (misses the install) or too
# broad (`dpf-operator-system` exists on DPF clusters with no BNK at all).
#
# The labels below come from `bnk_pod_discovery._LABEL_HINTS`, which sources
# them from the F5 charts themselves. One label selector, every namespace, and
# the answer is the component that is actually running.
#
# Grouped by label key so the whole check is a couple of API calls rather than
# one per component: a Kubernetes selector can OR values within one key, never
# across keys.
#
# DPF earns a place next to BNK because bnkscope has a DPF panel — an infra
# cluster running the DPF operator is a thing this tool is for, even though it
# carries no BNK itself. On a real deployment the two live on *different*
# clusters: the DPF operator on the infra cluster, BNK on the Kamaji tenant it
# provisions. Registering only the BNK half left the DPF panel unreachable.
BNK_POD_SELECTORS: tuple[str, ...] = (
    # TMM (the data plane), FLO (lifecycle), and the ingress controller.
    "app in (f5-tmm,flo,f5-cne-controller,f5ingress-f5ingress)",
    # The same components on charts that use the standard label, plus the DPF
    # operator itself.
    "app.kubernetes.io/name in (f5-lifecycle-operator,f5ingress,dpf-operator)",
)

# Which of the above mean "DPF", so the report can say which kind of cluster
# this is rather than a bare yes.
DPF_COMPONENTS: frozenset[str] = frozenset({"dpf-operator"})

# Per-context budget for the whole probe (connect, read). Discovery walks every
# context in the file, including ones behind a VPN that is currently down, so
# an unreachable context must fail fast rather than hold the sweep.
_PROBE_TIMEOUT = (3, 8)


def _find_bnk_pods(core_api: Any) -> list[tuple[str, str]]:
    """(app, namespace) for every BNK pod on the cluster.

    ``limit`` is deliberately generous rather than 1: knowing *which*
    components are present is what lets the UI say "TMM and FLO found"
    instead of a bare yes, and it costs one page of a filtered list.
    """
    found: list[tuple[str, str]] = []
    for selector in BNK_POD_SELECTORS:
        try:
            pods = core_api.list_pod_for_all_namespaces(
                label_selector=selector,
                limit=50,
                _request_timeout=_PROBE_TIMEOUT,
            )
        except Exception as exc:  # noqa: BLE001 — a denied list must not fail the probe
            logger.debug("BNK pod probe with selector %r failed: %s", selector, exc)
            continue
        for pod in pods.items:
            labels = pod.metadata.labels or {}
            app = labels.get("app") or labels.get("app.kubernetes.io/name") or "unknown"
            found.append((app, pod.metadata.namespace))
    return found


def classify_cluster_components(api_client: Any) -> dict[str, Any]:
    """Which BNK / DPF components are running, from pod labels.

    The single definition of ``has_dpf``, the flag that gates the DPF tab.
    Shared by the discovery sweep and the manual "Add cluster" path so a
    hand-registered infra cluster gets the same answer a discovered one does.

    Deliberately pod-based rather than API-group based. A DPF *tenant* cluster
    carries `svc.dpu.nvidia.com` without running the operator, so the group
    check in ``services/scanner/fetch.py`` — right for gating CRD fetches —
    would light the DPF tab on a cluster that has no DPUs to show. Only the
    operator's own pod means "this is the infrastructure cluster".

    Raises whatever the API client raises; callers decide whether a failed
    probe is fatal.
    """
    from kubernetes import client as k8s_client

    found = _find_bnk_pods(k8s_client.CoreV1Api(api_client))
    components = sorted({app for app, _ns in found})
    return {
        "components": components,
        "namespaces": sorted({ns for _app, ns in found}),
        "has_bnk": bool(set(components) - DPF_COMPONENTS),
        "has_dpf": bool(set(components) & DPF_COMPONENTS),
    }


def refresh_cluster_footprint(db: Session, cluster: KubernetesCluster) -> bool:
    """Probe an already-registered cluster and record what runs on it.

    The manual "Add cluster" path used to skip this, so ``meta_data.has_dpf``
    stayed NULL and the DPF tab never appeared on an infra cluster added by
    hand. The discovery sweep could not repair it after the fact either — it
    matches on context name, and a hand-added cluster's context is by
    definition not in the operator's own kubeconfig.

    Never raises. Registering a cluster whose API server is unreachable is a
    supported workflow (watching an install come up, VPN down), so a failed
    probe records why and leaves ``has_dpf`` *unset* rather than writing a
    confident ``False`` that a later probe could not tell from a real negative.

    Returns whether the probe succeeded. Does not commit.
    """
    from services.kubernetes_service import KubernetesService

    meta = dict(cluster.meta_data or {})
    try:
        api_client = KubernetesService(db).load_kubeconfig(cluster)
        probe = classify_cluster_components(api_client)
    except Exception as exc:  # noqa: BLE001 — an unreachable cluster still registers
        logger.info(
            "Footprint probe of cluster '%s' failed; has_dpf left unset: %s",
            cluster.name, exc,
        )
        meta["probe_error"] = _readable_probe_error(exc)
        cluster.meta_data = meta
        return False

    meta.pop("probe_error", None)
    meta["has_dpf"] = probe["has_dpf"]
    if probe["components"]:
        meta["bnk_components"] = probe["components"]
    cluster.meta_data = meta
    if probe["namespaces"]:
        cluster.discovered_namespaces = probe["namespaces"]
    cluster.last_synced_at = datetime.now(UTC)
    return True


@dataclass
class CandidateReport:
    """What discovery found for one context, and what it did about it."""

    context: str
    api_server: str | None
    cloud_provider: str
    auth_method: str
    source_path: str
    # reachable | unreachable | unusable — unusable means we never got to try
    state: str
    registered: bool
    cluster_id: int | None = None
    has_bnk: bool = False
    # The DPF operator is here. On a real deployment this is a *different*
    # cluster from the BNK one — the infra cluster that provisions the tenant.
    has_dpf: bool = False
    components: list[str] = field(default_factory=list)
    version: str | None = None
    detail: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "context": self.context,
            "api_server": self.api_server,
            "cloud_provider": self.cloud_provider,
            "auth_method": self.auth_method,
            "source_path": self.source_path,
            "state": self.state,
            "registered": self.registered,
            "cluster_id": self.cluster_id,
            "has_bnk": self.has_bnk,
            "has_dpf": self.has_dpf,
            "components": self.components,
            "version": self.version,
            "detail": self.detail,
        }


class ClusterDiscoveryService:
    """Probe local kubeconfig contexts and register the BNK ones."""

    def __init__(self, db: Session):
        self.db = db

    # ------------------------------------------------------------------
    # Entry points
    # ------------------------------------------------------------------

    def run(self, *, adopt_all: bool = False) -> dict[str, Any]:
        """Probe every local context; register the ones carrying BNK.

        ``adopt_all`` registers every reachable context regardless of footprint.
        It backs the "add anyway" path for a cluster where BNK is not installed
        yet — the case where someone is watching an install happen.
        """
        self.backfill_footprints()

        candidates = discover_contexts()
        if not candidates:
            logger.info("No kubeconfig contexts found — nothing to discover")
            self.db.commit()
            return {"candidates": [], "registered": 0, "found": 0}

        reports = [self._process(c, adopt_all=adopt_all) for c in candidates]
        self.db.commit()

        registered = sum(1 for r in reports if r.registered)
        logger.info(
            "Discovery: %d context(s), %d reachable, %d with BNK, %d with DPF, %d registered",
            len(reports),
            sum(1 for r in reports if r.state == "reachable"),
            sum(1 for r in reports if r.has_bnk),
            sum(1 for r in reports if r.has_dpf),
            registered,
        )
        return {
            "candidates": [r.as_dict() for r in reports],
            "registered": registered,
            "found": len(reports),
        }

    def backfill_footprints(self) -> int:
        """Probe registered clusters that have never had a footprint recorded.

        The sweep below can only ever reach clusters whose context is in the
        operator's kubeconfig. A hand-added cluster is by definition not, so
        one registered before the manual path probed — or while its API server
        was unreachable — would stay ``has_dpf``-less forever, and its DPF tab
        would never come back, however many times discovery ran.

        Keyed on the *absence* of the key rather than a falsy value, so a
        cluster genuinely without DPF is not re-probed on every sweep.
        """
        stale = [
            c for c in self.db.query(KubernetesCluster).all()
            if "has_dpf" not in (c.meta_data or {})
        ]
        if not stale:
            return 0

        probed = sum(1 for c in stale if refresh_cluster_footprint(self.db, c))
        logger.info(
            "Discovery: backfilled footprint for %d of %d cluster(s) with none recorded",
            probed, len(stale),
        )
        return probed

    def adopt(self, context_name: str) -> dict[str, Any]:
        """Register one named context regardless of whether BNK is on it.

        This is the one-click add behind a candidate row. It re-reads the
        kubeconfig rather than trusting a value posted by the client: the
        request carries a context *name*, never a kubeconfig.
        """
        from core.errors import BadRequestError, NotFoundError

        match = next((c for c in discover_contexts() if c.name == context_name), None)
        if match is None:
            raise NotFoundError("kube_context", context_name)
        if not match.adoptable:
            raise BadRequestError(
                "; ".join(match.blockers) or f"Context '{context_name}' cannot be used",
                code="CONTEXT_NOT_ADOPTABLE",
            )

        report = self._process(match, adopt_all=True)
        self.db.commit()
        return report.as_dict()

    # ------------------------------------------------------------------
    # Per-context work
    # ------------------------------------------------------------------

    def _process(self, candidate: DiscoveredContext, *, adopt_all: bool) -> CandidateReport:
        report = CandidateReport(
            context=candidate.name,
            api_server=candidate.api_server,
            cloud_provider=candidate.cloud_provider,
            auth_method=candidate.auth_method,
            source_path=candidate.source_path,
            state="unusable",
            registered=False,
        )

        existing = self._existing(candidate.name)
        if not candidate.adoptable:
            report.detail = "; ".join(candidate.blockers)
            return report

        probe = self._probe(candidate)
        report.state = "reachable" if probe["reachable"] else "unreachable"
        report.has_bnk = probe["has_bnk"]
        report.has_dpf = probe.get("has_dpf", False)
        report.components = probe.get("components", [])
        report.version = probe["version"]
        report.detail = probe["detail"]

        if existing is not None:
            # Already known: refresh what the probe just learned and stop. The
            # kubeconfig is refreshed too, so a rotated cert on the host reaches
            # bnkscope on the next sweep instead of going stale silently.
            self._apply(existing, candidate, probe)
            report.registered = True
            report.cluster_id = existing.id
            return report

        if not probe["reachable"]:
            return report
        if not (probe["has_bnk"] or probe.get("has_dpf") or adopt_all):
            report.detail = (
                "Reachable, but no BNK or DPF pods found. Add it manually if you "
                "are watching an install in progress."
            )
            return report

        cluster = KubernetesCluster(name=self._unique_name(candidate.name))
        self._apply(cluster, candidate, probe)
        self.db.add(cluster)
        self.db.flush()

        report.registered = True
        report.cluster_id = cluster.id
        logger.info("Discovered and registered cluster '%s'", cluster.name)
        return report

    def _probe(self, candidate: DiscoveredContext) -> dict[str, Any]:
        """Connect with the candidate's own credentials; look for BNK.

        Runs through ``KubernetesService.load_kubeconfig`` on a *transient*
        cluster object rather than reimplementing the connection: that is where
        the native EKS (boto3 STS) and GKE (google-auth) token minting lives,
        and discovery needs exactly the same treatment a registered cluster gets.
        """
        from kubernetes import client as k8s_client

        from services.kubernetes_service import KubernetesService

        result: dict[str, Any] = {
            "reachable": False,
            "has_bnk": False,
            "has_dpf": False,
            "version": None,
            "namespaces": [],
            "components": [],
            "detail": None,
        }

        transient = KubernetesCluster(
            name=candidate.name,
            context=candidate.name,
            api_server=candidate.api_server,
            kubeconfig_encrypted=encrypt_value(candidate.kubeconfig),
            cloud_provider=candidate.cloud_provider,
            region=candidate.region,
        )

        try:
            api_client = KubernetesService(self.db).load_kubeconfig(transient)
            version = k8s_client.VersionApi(api_client).get_code(_request_timeout=_PROBE_TIMEOUT)
            result["version"] = f"{version.major}.{version.minor}"
            result["reachable"] = True

            result.update(classify_cluster_components(api_client))
        except Exception as exc:  # noqa: BLE001 — one bad context must not stop the sweep
            result["detail"] = _readable_probe_error(exc)
            logger.debug("Probe of context '%s' failed: %s", candidate.name, exc)

        return result

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _existing(self, context_name: str) -> KubernetesCluster | None:
        """Match on context name — the stable identity of a local context.

        Not on cluster name: the operator can rename a cluster in bnkscope, and
        a rename must not cause the next sweep to register a duplicate.
        """
        return (
            self.db.query(KubernetesCluster)
            .filter(KubernetesCluster.context == context_name)
            .first()
        )

    def _unique_name(self, context_name: str) -> str:
        """A display name free of collisions with manually-added clusters."""
        base = context_name
        if not self.db.query(KubernetesCluster).filter(KubernetesCluster.name == base).first():
            return base
        for suffix in range(2, 100):
            candidate = f"{base}-{suffix}"
            if not self.db.query(KubernetesCluster).filter(
                KubernetesCluster.name == candidate
            ).first():
                return candidate
        return f"{base}-{id(self)}"

    def _apply(
        self, cluster: KubernetesCluster, candidate: DiscoveredContext, probe: dict
    ) -> None:
        """Write the discovered state onto a cluster row."""
        cluster.context = candidate.name
        cluster.api_server = candidate.api_server
        cluster.kubeconfig_encrypted = encrypt_value(candidate.kubeconfig)
        cluster.cloud_provider = candidate.cloud_provider
        cluster.region = candidate.region
        cluster.default_namespace = candidate.namespace
        cluster.status = "active" if probe["reachable"] else "unreachable"
        if probe["version"]:
            cluster.version = probe["version"]
        if probe["namespaces"]:
            cluster.discovered_namespaces = probe["namespaces"]
        if probe["reachable"]:
            cluster.last_synced_at = datetime.now(UTC)

        meta = dict(cluster.meta_data or {})
        meta.update(
            {
                "discovered": True,
                "kubeconfig_source": candidate.source_path,
                "auth_method": candidate.auth_method,
            }
        )
        if probe.get("components"):
            meta["bnk_components"] = probe["components"]
        meta["has_dpf"] = bool(probe.get("has_dpf"))
        cluster.meta_data = meta


def _readable_probe_error(exc: Exception) -> str:
    """Turn a connection failure into something an operator can act on.

    The raw exceptions here are long and mostly urllib3 internals; what the
    operator needs is which of the three usual causes it was.
    """
    from kubernetes.client.exceptions import ApiException

    if isinstance(exc, ApiException):
        if exc.status in (401, 403):
            return (
                f"The API server answered but rejected the credentials ({exc.status}). "
                "The context may need a re-login on the host."
            )
        return f"Kubernetes API error {exc.status}: {exc.reason}"

    text = str(exc)
    if "timed out" in text.lower() or "timeout" in text.lower():
        return "Timed out reaching the API server — VPN down, or the cluster is gone."
    if "name or service not known" in text.lower() or "nodename nor servname" in text.lower():
        return "The API server hostname does not resolve from inside bnkscope."
    if "connection refused" in text.lower():
        return "Connection refused by the API server."
    return text.splitlines()[0][:300] if text else exc.__class__.__name__


def discover_in_background() -> None:
    """Kick off a discovery sweep off the caller's thread.

    Used at startup: probing a dozen contexts, some of them unreachable, takes
    seconds, and the API must be answering before that finishes.
    """

    def _sweep() -> None:
        from database import get_db_context

        with get_db_context() as db:
            ClusterDiscoveryService(db).run()

    submit(_sweep)
