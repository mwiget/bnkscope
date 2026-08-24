"""ClusterProbe — reachability probe for Kubernetes clusters.

Data-plane-aligned (Argo CD / Rancher / SRE Book Ch.6: "probe the path you
serve traffic on"): a direct ``GET /version`` against the API server, wrapping
``connectivity_probe_service`` rather than reimplementing the socket dance.
Fast, and doesn't need a full kubeconfig load.

The operator-heartbeat probe mode went with the operator agent (bnkscope
Phase 2) — every cluster is now probed directly over its kubeconfig.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from models import KubernetesCluster

logger = logging.getLogger(__name__)
from services.reachability.probe import (
    ErrorCategory,
    Probe,
    ProbeResult,
    ReachabilityState,
)


class ClusterProbe(Probe):
    target_type = "cluster"
    probe_interval_seconds = 30
    slow_threshold_ms = 5000
    breaker_failure_threshold = 5
    breaker_sleep_window_seconds = 30

    def __init__(self, db_session_factory: Any) -> None:
        # Stored as a callable so we can open a fresh short-lived session per probe.
        self._session_factory = db_session_factory

    # ------------------------------------------------------------------
    # Probe ABC
    # ------------------------------------------------------------------

    def list_targets(self, db: Session) -> list[int]:
        rows = db.query(KubernetesCluster.id).all()
        return [r[0] for r in rows]

    async def probe(self, target_id: int) -> ProbeResult:
        # Use a fresh session for each probe — long-running sessions across
        # 30s ticks will rot and lose connection on idle DBs.
        db = self._session_factory()
        try:
            cluster = db.query(KubernetesCluster).filter(KubernetesCluster.id == target_id).first()
            if cluster is None:
                return ProbeResult(
                    state=ReachabilityState.UNKNOWN,
                    checked_at=datetime.now(UTC),
                    error_context={
                        "target_name": f"cluster:{target_id}",
                        "suggested_action": "Cluster row was deleted; will stop probing on next cycle.",
                    },
                )
            return await self._probe_direct(cluster)
        finally:
            try:
                db.close()
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Direct probe (KubernetesEngine)
    # ------------------------------------------------------------------

    async def _probe_direct(self, cluster: KubernetesCluster) -> ProbeResult:
        """Wrap connectivity_probe_service for the synchronous path.

        That service already does ICMP/TCP/GET-/version and produces a rich
        diagnostic. We map its status into our 3-state model and re-shape
        the message into ``error_context``.

        Tighter timeouts than the underlying service's defaults (3s TCP,
        5s K8s read) — RFC mandates fast probes; the broader 5s/8s is
        only used at higher levels.
        """
        from services.connectivity_probe_service import _parse_api_server, _probe_k8s_api, _probe_tcp

        host, port = _parse_api_server(cluster.api_server)
        if not host:
            return ProbeResult(
                state=ReachabilityState.UNKNOWN,
                checked_at=datetime.now(UTC),
                error_context={
                    "target_name": cluster.name,
                    "suggested_action": "No API server URL configured for this cluster.",
                },
            )

        # Run the (sync) probes off the event loop so we don't block other probes.
        def _do_probe() -> tuple[dict[str, Any], dict[str, Any], float]:
            import time as _t
            start = _t.monotonic()
            tcp = _probe_tcp(host, port, timeout=3)
            k8s_api: dict[str, Any] = {"accessible": False, "version": None, "status_code": None}
            if tcp.get("open"):
                k8s_api = _probe_k8s_api(host, port, timeout=5)
            latency_ms = (_t.monotonic() - start) * 1000
            return tcp, k8s_api, latency_ms

        tcp, k8s_api, latency_ms = await asyncio.to_thread(_do_probe)
        now = datetime.now(UTC)

        if k8s_api.get("accessible"):
            return ProbeResult(
                state=ReachabilityState.REACHABLE,
                checked_at=now,
                latency_ms=latency_ms,
                error_context={"target_name": cluster.name},
            )
        if tcp.get("open"):
            # Port open but K8s API not responding — likely auth/wrong port,
            # not a network problem. Don't trip the breaker hard.
            return ProbeResult(
                state=ReachabilityState.UNREACHABLE,
                checked_at=now,
                latency_ms=latency_ms,
                error_category=ErrorCategory.TARGET,
                error_context={
                    "target_name": cluster.name,
                    "suggested_action": (
                        f"Port {port} on {host} accepts connections but the Kubernetes "
                        f"API did not respond. Verify the API server URL and port."
                    ),
                },
            )
        return ProbeResult(
            state=ReachabilityState.UNREACHABLE,
            checked_at=now,
            latency_ms=latency_ms,
            error_category=ErrorCategory.NETWORK,
            error_context={
                "target_name": cluster.name,
                "suggested_action": (
                    f"Cannot reach {host}:{port}. "
                    f"Check VPN connection or whether the API server is online."
                ),
            },
        )
