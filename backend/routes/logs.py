"""Log search.

The browser never reaches Loki directly: Loki is published on loopback only, so
routing through here keeps bnkscope's single bind boundary rather than opening a
second one that would need its own reasoning.
"""

import logging
import time

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from core.errors import handle_route_errors
from services import logs_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/logs", tags=["logs"])


class LogEntry(BaseModel):
    #: Nanoseconds since the epoch, as Loki stores them. Not a string: the UI
    #: sorts and groups on this, and a formatted timestamp cannot be compared.
    timestamp: int
    line: str
    cluster: str | None = None
    namespace: str | None = None
    pod: str | None = None
    container: str | None = None
    level: str = "unknown"


class LogSearchResponse(BaseModel):
    ok: bool = True
    entries: list[LogEntry] = Field(default_factory=list)
    #: The LogQL actually executed — shown in the UI so the filters teach the
    #: query language rather than hiding it.
    query: str = ""
    count: int = 0
    available: bool = True
    detail: str | None = None


class LogFiltersResponse(BaseModel):
    ok: bool = True
    available: bool = True
    clusters: list[str] = Field(default_factory=list)
    namespaces: list[str] = Field(default_factory=list)
    containers: list[str] = Field(default_factory=list)
    levels: list[str] = Field(default_factory=list)
    detail: str | None = None


@router.get("/filters", response_model=LogFiltersResponse)
@handle_route_errors("read log filters")
def get_filters():
    """The values each filter can take, from what has actually been collected."""
    if not logs_service.is_available():
        return {
            "ok": True,
            "available": False,
            "detail": (
                "The log store is not running. It starts with the telemetry "
                "profile — `bnkscope up` brings it up by default."
            ),
        }
    return {
        "ok": True,
        "available": True,
        "clusters": logs_service.label_values("cluster"),
        "namespaces": logs_service.label_values("namespace"),
        "containers": logs_service.label_values("container"),
        "levels": logs_service.label_values("level"),
    }


@router.get("/search", response_model=LogSearchResponse)
@handle_route_errors("search logs")
def search_logs(
    cluster: str | None = None,
    namespace: str | None = None,
    pod: str | None = None,
    container: str | None = None,
    level: str | None = None,
    search: str | None = None,
    logql: str | None = None,
    minutes: int = Query(default=60, ge=1, le=1440),
    limit: int = Query(default=500, ge=1, le=5000),
):
    """Search the collected logs.

    Filters compose into LogQL; `logql` overrides them entirely for the
    questions the filters cannot ask.
    """
    if not logs_service.is_available():
        return {
            "ok": True,
            "available": False,
            "detail": (
                "The log store is not running. It starts with the telemetry "
                "profile — `bnkscope up` brings it up by default."
            ),
        }

    query = logs_service.build_query(
        cluster=cluster,
        namespace=namespace,
        pod=pod,
        container=container,
        level=level,
        search=search,
        logql=logql,
    )

    end_ns = int(time.time() * 1e9)
    start_ns = end_ns - int(minutes * 60 * 1e9)

    try:
        result = logs_service.query_range(
            query, start_ns=start_ns, end_ns=end_ns, limit=limit
        )
    except ValueError as exc:
        # A bad hand-written LogQL is the operator's typo, not a server fault:
        # hand back what Loki said so it can be corrected.
        return {
            "ok": False,
            "available": True,
            "query": query,
            "detail": str(exc),
        }

    return {"ok": True, "available": True, **result}
