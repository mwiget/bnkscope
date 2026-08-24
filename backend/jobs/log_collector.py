"""Keep the log collector's credentials current.

Alloy holds no cluster knowledge of its own: bnkscope writes it one kubeconfig
per registered cluster plus a generated config, and Alloy reads them. Two things
make that go stale — a cluster registered (or removed) since the last write, and
a credential that expires.

The second is the one that bites quietly. An EKS or GKE kubeconfig carries a
minted bearer token good for roughly an hour; the collector keeps using it,
starts getting 401s on the log endpoint, and the symptom is simply that logs
stop. Rewriting on a schedule is what stops that, so this runs whether or not
the cluster list changed.
"""

import logging
import os

logger = logging.getLogger(__name__)


def republish_log_collector() -> None:
    if os.getenv("BNKSCOPE_TELEMETRY", "off") != "on":
        return

    from database import SessionLocal
    from services import log_collector_service

    db = SessionLocal()
    try:
        result = log_collector_service.publish(db)
        if result["changed"]:
            logger.info(
                "Log collector config rewritten for %d cluster(s) (reloaded=%s)",
                result["clusters"],
                result["reloaded"],
            )
    except Exception:  # noqa: BLE001 — a scheduled job must not kill the scheduler
        logger.exception("Could not republish the log collector config")
    finally:
        db.close()
