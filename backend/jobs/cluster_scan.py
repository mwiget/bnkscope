"""
Best-effort background cluster scan triggered after register/update.

Submitted at the commit boundary (route handler) after a new KubernetesCluster
row is committed. The job acquires its own DB session so it never races with
the API commit that created the row.

Fire-and-forget: scanner failures are swallowed and logged at WARNING.
The existing UI Rescan button is the user's escape hatch for persistent failures.
"""

import logging

from database import get_db_context
from services.cluster_scanner import ClusterScanner

logger = logging.getLogger(__name__)


def scan_cluster_async(cluster_id: int) -> None:
    """Best-effort background footprint probe + scan after cluster register/update.

    Acquires its own DB session rather than receiving one: the caller's
    session belongs to a request that has already returned.
    No autoretry: scanner failures (bad kubeconfig, unreachable tunnel,
    missing creds) are not transient. Task always returns normally.

    The footprint probe runs first and commits on its own. It is what writes
    ``meta_data.has_dpf`` — the flag that gates the DPF tab — and a
    hand-registered cluster has no other way to get it: the discovery sweep
    matches on context name, and a hand-added cluster's context is by
    definition not in the operator's own kubeconfig. Committed separately so a
    scan failure (the common case on a cluster with no BNK on it) does not take
    the footprint answer down with it.
    """
    try:
        with get_db_context() as db:
            _probe_footprint(db, cluster_id)
    except Exception as exc:  # noqa: BLE001 — best-effort
        logger.warning("footprint probe failed for cluster_id=%s: %s", cluster_id, exc)

    try:
        with get_db_context() as db:
            ClusterScanner(db).scan(cluster_id)
            db.commit()
    except Exception as exc:  # noqa: BLE001 — best-effort
        logger.warning("scan_cluster_async failed for cluster_id=%s: %s", cluster_id, exc)


def _probe_footprint(db, cluster_id: int) -> None:
    """Record which BNK / DPF components run on the cluster."""
    from models import KubernetesCluster
    from services.cluster_discovery_service import refresh_cluster_footprint

    cluster = db.get(KubernetesCluster, cluster_id)
    if cluster is None:
        return
    refresh_cluster_footprint(db, cluster)
    db.commit()


def enqueue_cluster_scan(cluster_id: int) -> None:
    """Fire-and-forget background scan after register/update.

    Runs on the in-process pool; failures are logged there, never raised into
    the API request that triggered the scan.
    """
    from core.background import submit

    submit(scan_cluster_async, cluster_id)
