"""
Startup initialization steps for bnkscope.

Each function is a self-contained startup step that can succeed or fail
independently. They are called in order by the lifespan manager in main.py.
"""

import logging
import os

logger = logging.getLogger(__name__)


def init_database_step():
    """Verify database connectivity. Fatal if this fails."""
    from database import init_database
    init_database()


def seed_defaults_step():
    """Seed system defaults into the database."""
    from database import get_db_context
    from services.defaults_service import seed_defaults
    with get_db_context() as db:
        seeded_count = seed_defaults(db)
        db.commit()
    if seeded_count > 0:
        logger.info(f"  Seeded {seeded_count} system defaults")
    else:
        logger.info("  System defaults already configured")


def discover_clusters_step():
    """Register BNK clusters found in the operator's own kubeconfig.

    Fire-and-forget on the background pool: probing a dozen contexts, some of
    them behind a VPN that is currently down, takes seconds, and the API has to
    be answering before that finishes. The sweep runs again on demand from the
    UI, so a boot that races an interface coming up is not a lasting problem.
    """
    from services.cluster_discovery_service import discover_in_background

    discover_in_background()


def publish_log_collector_step():
    """Hand the log collector the credentials and config it needs.

    Alloy reads this file on boot and cannot discover clusters on its own — its
    view of your estate is entirely what bnkscope writes here. Best-effort like
    the rest: a failure means logs are missing, not that the API cannot serve.
    """
    if os.getenv("BNKSCOPE_TELEMETRY", "off") != "on":
        return

    from database import SessionLocal
    from services import log_collector_service

    db = SessionLocal()
    try:
        result = log_collector_service.publish(db)
        logger.info(
            "Log collector: %d cluster(s), changed=%s",
            result["clusters"],
            result["changed"],
        )
    finally:
        db.close()


def start_scheduler_step(scheduler):
    """Register the periodic jobs and start the scheduler.

    These were Celery beat entries until Phase 4. APScheduler runs them on a
    background thread inside this process; each job owns its own DB session.
    """
    from apscheduler.triggers.interval import IntervalTrigger

    from jobs.health_monitor import check_cluster_health
    from jobs.log_collector import republish_log_collector
    from jobs.notification_retention import purge_old_notifications
    from services.cluster_discovery_service import discover_in_background

    jobs = [
        # Fires alerts when a cluster's BNK health severity changes.
        (check_cluster_health, IntervalTrigger(minutes=1), "health_monitor",
         "BNK cluster health monitor"),
        # Picks up contexts added to ~/.kube/config since boot, and refreshes
        # the stored kubeconfig of ones already registered so a rotated cert on
        # the host does not go stale here.
        (discover_in_background, IntervalTrigger(minutes=10), "cluster_discovery",
         "Local kubeconfig discovery"),
        (purge_old_notifications, IntervalTrigger(hours=24),
         "notification_retention", "Notification retention purge"),
        # Republishes the collector's kubeconfigs and config. Picks up a
        # newly-registered cluster, and rewrites credentials that expire —
        # an EKS token minted at boot is worthless to Alloy an hour later.
        (republish_log_collector, IntervalTrigger(minutes=10),
         "log_collector_publish", "Log collector config"),
    ]
    for func, trigger, job_id, name in jobs:
        scheduler.add_job(
            func=func, trigger=trigger, id=job_id, name=name, replace_existing=True,
        )

    scheduler.start()
    for _, _, job_id, name in jobs:
        logger.info("  %s (%s)", name, job_id)


