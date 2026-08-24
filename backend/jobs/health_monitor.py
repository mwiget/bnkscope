"""
Health monitoring background job.

Periodically checks BNK cluster health and fires alerts when status changes.
Runs every 60 seconds on the app scheduler.

Architecture:
  - Fetches health for each cluster with an active project
  - Compares current health against the last severity this process saw
  - If it changed (e.g. healthy → critical), fires an alert via alert_service

The previous severity used to live in Redis. Redis is not in requirements,
not installed, and REDIS_URL is not in the settings — so the import raised,
the client was always None, and two things followed: a severity *change* was
never announced at all (the comparison had nothing to compare against), and
the first-detection branch re-fired every single tick for every unhealthy
cluster, held back only by alert_service's 60s rate limit, which is the same
cadence as this job.

An in-process dict is the right store now: bnkscope runs one backend process,
and the state is a cache — losing it on restart costs one duplicate alert, not
correctness.
"""
import logging
from datetime import UTC, datetime
from typing import Any

from database import get_db_context
from models.enums import HealthSeverity

logger = logging.getLogger(__name__)

#: Last severity seen per cluster id, for this process. Not persisted: see
#: the note above on why Redis was the wrong home for it.
_LAST_SEVERITY: dict[int, str] = {}

def _get_cluster_health(cluster_id: int, db) -> dict[str, Any] | None:
    """
    Fetch current BNK health for a cluster.
    Reuses the same logic as the /f5bnk/health API endpoint.

    Uses kubeconfig_for_cluster context manager to guarantee temp file cleanup.
    """
    try:
        import kr8s

        from models import KubernetesCluster
        from services.cluster_utils import kubeconfig_for_cluster

        cluster = db.query(KubernetesCluster).filter(
            KubernetesCluster.id == cluster_id
        ).first()
        if not cluster:
            return None

        if not cluster.kubeconfig_encrypted:
            return None

        with kubeconfig_for_cluster(cluster, db) as kubeconfig_path:
            api = kr8s.api(kubeconfig=kubeconfig_path)

            # Quick health check — just look at key indicators
            health = {
                "cluster_id": cluster_id,
                "cluster_name": cluster.name,
                "timestamp": datetime.now(UTC).isoformat(),
                "components": {},
            }

            # Check FLO operator
            try:
                pods = api.get("pods", namespace="f5-operator", label_selector="app.kubernetes.io/name=f5-lifecycle-operator")
                running = sum(1 for p in pods if p.status.phase == "Running")
                health["components"]["flo"] = {
                    "total": len(pods),
                    "running": running,
                    "severity": HealthSeverity.HEALTHY if running > 0 else HealthSeverity.UNHEALTHY,
                }
            except Exception:
                health["components"]["flo"] = {"total": 0, "running": 0, "severity": HealthSeverity.UNKNOWN}

            # Check TMM pods
            try:
                pods = api.get("pods", namespace="*", label_selector="app=f5-tmm")
                running = sum(1 for p in pods if p.status.phase == "Running")
                total = len(pods)
                if total == 0:
                    sev = HealthSeverity.UNKNOWN
                elif running == total:
                    sev = HealthSeverity.HEALTHY
                elif running > 0:
                    sev = HealthSeverity.DEGRADED
                else:
                    sev = HealthSeverity.UNHEALTHY
                health["components"]["tmm"] = {
                    "total": total,
                    "running": running,
                    "severity": sev,
                }
            except Exception:
                health["components"]["tmm"] = {"total": 0, "running": 0, "severity": HealthSeverity.UNKNOWN}

            # Check Gateways
            try:
                gateways = api.get("gateways", namespace="*")
                programmed = sum(1 for g in gateways if any(
                    c.get("type") == "Programmed" and c.get("status") == "True"
                    for c in (g.status.get("conditions", []) if hasattr(g.status, 'get') else [])
                ))
                total = len(gateways)
                if total == 0:
                    sev = HealthSeverity.UNKNOWN
                elif programmed == total:
                    sev = HealthSeverity.HEALTHY
                elif programmed > 0:
                    sev = HealthSeverity.DEGRADED
                else:
                    sev = HealthSeverity.UNHEALTHY
                health["components"]["gateways"] = {
                    "total": total,
                    "programmed": programmed,
                    "severity": sev,
                }
            except Exception:
                health["components"]["gateways"] = {"total": 0, "programmed": 0, "severity": HealthSeverity.UNKNOWN}

            # Overall severity — worst component wins
            severities = [c["severity"] for c in health["components"].values()]
            if HealthSeverity.UNHEALTHY in severities:
                health["overall_severity"] = HealthSeverity.UNHEALTHY
            elif HealthSeverity.DEGRADED in severities:
                health["overall_severity"] = HealthSeverity.DEGRADED
            elif all(s == HealthSeverity.UNKNOWN for s in severities):
                health["overall_severity"] = HealthSeverity.UNKNOWN
            else:
                health["overall_severity"] = HealthSeverity.HEALTHY

            return health

    except Exception as e:
        logger.error(f"Failed to get health for cluster {cluster_id}: {e}")
        return None

def check_cluster_health():
    """
    Periodic task: check the health of every registered cluster.
    Fires alerts when health severity changes.
    """

    with get_db_context() as db:
        try:
            from models import KubernetesCluster

            # Clusters are no longer scoped by project (bnkscope Phase 1) —
            # every registered cluster is monitored.
            clusters = db.query(KubernetesCluster).all()

            if not clusters:
                return {"checked": 0, "alerts_fired": 0}

            alerts_fired = 0

            for cluster in clusters:
                try:
                    current_health = _get_cluster_health(cluster.id, db)
                    if not current_health:
                        continue

                    current_severity = current_health.get("overall_severity", "unknown")

                    previous_severity = _LAST_SEVERITY.get(cluster.id)
                    _LAST_SEVERITY[cluster.id] = current_severity

                    # Fire alert if severity changed
                    if previous_severity and current_severity != previous_severity:
                        _fire_health_alert(
                            db, cluster, current_health, current_severity, previous_severity
                        )
                        db.commit()
                        alerts_fired += 1

                    # Also alert if unhealthy (even if not changed) — first detection
                    elif previous_severity is None and current_severity == HealthSeverity.UNHEALTHY:
                        _fire_health_alert(
                            db, cluster, current_health, current_severity, "unknown"
                        )
                        db.commit()
                        alerts_fired += 1

                except Exception as e:
                    logger.error(f"Health check failed for cluster {cluster.id} ({cluster.name}): {e}")

            return {"checked": len(clusters), "alerts_fired": alerts_fired}

        except Exception as e:
            logger.error(f"Health monitor task failed: {e}")
            return {"error": str(e)}

def _fire_health_alert(
    db,
    cluster,
    health: dict[str, Any],
    current_severity: str,
    previous_severity: str,
):
    """Fire an alert for a health severity change."""
    from services.alert_service import fire_alert

    # Map HealthSeverity members to alert notification severity strings
    severity_map = {
        HealthSeverity.UNHEALTHY: "critical",
        HealthSeverity.DEGRADED: "warning",
        HealthSeverity.HEALTHY: "info",
        HealthSeverity.UNKNOWN: "warning",
    }

    # Build component details for the alert
    components_detail = []
    for name, comp in health.get("components", {}).items():
        if comp.get("severity") in (HealthSeverity.UNHEALTHY, HealthSeverity.DEGRADED):
            components_detail.append(f"{name}: {comp.get('running', '?')}/{comp.get('total', '?')}")

    message = f"Cluster '{cluster.name}' health changed: {previous_severity} -> {current_severity}"
    if components_detail:
        message += f"\nAffected: {', '.join(components_detail)}"

    fire_alert(
        db=db,
        event_type="health_change",
        severity=severity_map.get(current_severity, "warning"),
        title=f"Health {current_severity.upper()}: {cluster.name}",
        message=message,
        project_id=cluster.project_id,
        cluster_id=cluster.id,
        extra={
            "cluster_name": cluster.name,
            "previous_severity": previous_severity,
            "current_severity": current_severity,
            "components": health.get("components", {}),
        },
    )
