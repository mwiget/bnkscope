"""Query the collected logs.

A thin, deliberate layer over Loki. bnkscope owns the controls — cluster,
namespace, pod, container, level, free text — and Loki does the work, the same
split as TMM Live: the operator should not have to learn LogQL to answer "what
did this pod say in the last ten minutes", but should not be prevented from
writing LogQL when the question is harder than the filters allow.

The browser does not talk to Loki directly. Loki is published on loopback only,
so going through the API keeps the one bind boundary bnkscope has rather than
opening a second one.
"""

import logging
import os
from typing import Any
from urllib.parse import urljoin

import requests

logger = logging.getLogger(__name__)

LOKI_URL = os.getenv("BNKSCOPE_LOKI_URL", "http://127.0.0.1:3100")
_TIMEOUT = 20.0

#: Retention is 24h; a query for more than that returns nothing but costs the
#: same to run.
MAX_RANGE_HOURS = 24


class LokiUnavailableError(RuntimeError):
    """Loki is not answering — the telemetry profile is probably not running."""


def _get(path: str, params: dict[str, Any]) -> dict[str, Any]:
    url = urljoin(LOKI_URL.rstrip("/") + "/", path.lstrip("/"))
    try:
        resp = requests.get(url, params=params, timeout=_TIMEOUT)
    except requests.RequestException as exc:
        raise LokiUnavailableError(
            "The log store is not answering. It runs with the telemetry "
            "profile — check `bnkscope status`."
        ) from exc

    if resp.status_code >= 400:
        # Loki puts the useful part of a bad LogQL query in the body, and it is
        # the only thing that tells the operator what is wrong with what they
        # typed.
        detail = resp.text.strip()[:400] or f"HTTP {resp.status_code}"
        raise ValueError(detail)
    return resp.json()


def label_values(label: str, since_hours: int = MAX_RANGE_HOURS) -> list[str]:
    """Distinct values for a label — what populates the filter dropdowns."""
    import time

    end = int(time.time() * 1e9)
    start = end - int(min(since_hours, MAX_RANGE_HOURS) * 3600 * 1e9)
    try:
        doc = _get(
            f"/loki/api/v1/label/{label}/values", {"start": start, "end": end}
        )
    except (LokiUnavailableError, ValueError):
        return []
    return sorted(doc.get("data") or [])


def build_query(
    *,
    cluster: str | None = None,
    namespace: str | None = None,
    pod: str | None = None,
    container: str | None = None,
    level: str | None = None,
    search: str | None = None,
    logql: str | None = None,
) -> str:
    """Turn the filters into LogQL, or pass a hand-written query through.

    A stream selector cannot be empty in LogQL — `{}` is a syntax error, not
    "everything" — so with no filters at all we select on the label every line
    is guaranteed to carry.
    """
    if logql and logql.strip():
        return logql.strip()

    selectors: list[str] = []
    for label, value in (
        ("cluster", cluster),
        ("namespace", namespace),
        ("pod", pod),
        ("container", container),
        ("level", level),
    ):
        if value:
            # Escape the quotes and backslashes a label value could carry.
            escaped = value.replace("\\", "\\\\").replace('"', '\\"')
            selectors.append(f'{label}="{escaped}"')

    if not selectors:
        selectors.append('cluster=~".+"')

    query = "{" + ", ".join(selectors) + "}"

    if search and search.strip():
        # |= is a substring match, case-sensitive. Operators searching for an
        # F5 message id or an IP want exactly that; a regex here would make
        # dots and brackets behave surprisingly.
        needle = search.strip().replace("\\", "\\\\").replace('"', '\\"')
        query += f' |= "{needle}"'

    return query


def query_range(
    query: str,
    *,
    start_ns: int,
    end_ns: int,
    limit: int = 500,
    direction: str = "backward",
) -> dict[str, Any]:
    """Run a range query and flatten Loki's per-stream shape into lines.

    Loki returns one entry per stream, each with its own label set; a reader
    wants a single list in time order. The stream labels are folded onto each
    line so the UI can show where it came from without a second lookup.
    """
    doc = _get(
        "/loki/api/v1/query_range",
        {
            "query": query,
            "start": start_ns,
            "end": end_ns,
            "limit": limit,
            "direction": direction,
        },
    )

    entries: list[dict[str, Any]] = []
    for stream in (doc.get("data") or {}).get("result") or []:
        labels = stream.get("stream") or {}
        for value in stream.get("values") or []:
            ts_ns, line = value[0], value[1]
            entries.append(
                {
                    "timestamp": int(ts_ns),
                    "line": line,
                    "cluster": labels.get("cluster"),
                    "namespace": labels.get("namespace"),
                    "pod": labels.get("pod"),
                    "container": labels.get("container"),
                    "level": labels.get("level") or "unknown",
                }
            )

    # Newest first: an operator opening this page is asking "what just
    # happened", not "what happened first".
    entries.sort(key=lambda e: e["timestamp"], reverse=True)
    return {"entries": entries[:limit], "query": query, "count": len(entries)}


def is_available() -> bool:
    try:
        resp = requests.get(f"{LOKI_URL.rstrip('/')}/ready", timeout=3)
        return resp.status_code == 200
    except requests.RequestException:
        return False
