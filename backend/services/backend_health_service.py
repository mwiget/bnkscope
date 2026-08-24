"""
Backend health — read-through cached llmtop scrape.

The heavy work (analyzer walk + llmtop subprocess) lives in
``jobs.backend_health.fetch_backend_health``. It runs off the request thread
because it forks a subprocess and talks to the cluster, either of which can
block for seconds. This module only:

  1. Returns a fresh-enough cached value if present (5s TTL).
  2. Otherwise runs the scrape on the background pool and waits, with a timeout.
  3. Caches the result under a per-(cluster, ns, name) key.

Concurrent panel renders for the same analyzer therefore coalesce to one scrape
per ~5s rather than each one forking llmtop.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any, cast

from sqlalchemy.orm import Session

from core.cache import cache

logger = logging.getLogger(__name__)

CACHE_TTL_SECONDS = 5
TASK_TIMEOUT_SECONDS = 20


def get_backend_health(
    db: Session,  # noqa: ARG001 — kept for route-handler symmetry; the job opens its own session
    cluster_id: int,
    namespace: str,
    name: str,
) -> dict[str, Any]:
    """Read-through cached dispatch to the backend-health scrape.

    The operator-pushed snapshot path went with the operator agent (bnkscope
    Phase 2); the scrape cache is the only source now.
    """
    cache_key = f"backend_health:{cluster_id}:{namespace}:{name}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cast(dict[str, Any], cached)

    # Cache miss — run the scrape off the request thread and wait for it.
    from core.background import run_sync
    from jobs.backend_health import fetch_backend_health

    try:
        result = cast(
            dict[str, Any],
            run_sync(fetch_backend_health, cluster_id, namespace, name,
                     timeout=TASK_TIMEOUT_SECONDS),
        )
    except TimeoutError:
        return {
            "available": False,
            "reason": f"backend-health scrape timed out after {TASK_TIMEOUT_SECONDS}s",
            "backends": [],
            "errors": {},
            "updated_at": datetime.now(UTC).isoformat(),
        }
    except Exception as e:  # noqa: BLE001 — surface scrape errors to the UI rather than 500
        logger.exception("backend-health dispatch failed")
        return {
            "available": False,
            "reason": f"backend-health dispatch failed: {e}",
            "backends": [],
            "errors": {},
            "updated_at": datetime.now(UTC).isoformat(),
        }

    cache.set(cache_key, result, CACHE_TTL_SECONDS)
    return result
