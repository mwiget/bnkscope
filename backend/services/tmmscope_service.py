"""Where the telemetry stack is, and what is actually streaming to it.

The stack is bnkscope's own: `bnkscope up` starts Prometheus and Grafana from
`telemetry/` and passes their negotiated ports in as environment. That is the
only source for *where* — there used to be a second one, tmmscope's
``~/.config/tmmscope/endpoints.json``, read when bnkscope found no stack of its
own. It was removed once nothing else here needed tmmscope (see D-040): a
fallback nobody exercises is a second code path that can only rot.

Everything here is **read-only**. The interesting source is the Prometheus HTTP
API, and it stayed interesting for the same reason it always was: "is this
cluster injected?" has an exact answer — does Prometheus hold `f5tmm_up` series
carrying its `cluster` label — and getting it needs no binary, no kubectl and no
Docker socket. A config that says the stack is up is only a claim; series
arriving in the last minute are evidence.

Ports are discovered, never assumed. `bnkscope up` prefers 9491/3000 but walks
upward when they are taken and persists the choice, so hard-coding either is a
bug that only shows up on a busy machine.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any

import requests

logger = logging.getLogger(__name__)

# The stack runs on the operator's machine. Under `network_mode: host` the
# backend shares that network namespace, so loopback reaches it directly.
#
# Under the macOS/WSL2 bridge overlay it does not: "localhost" is the container.
# There the compose overlay sets this to `host.docker.internal`, and it is
# substituted when *probing* only — the URL handed to the browser keeps saying
# localhost, which is what the browser needs.
_PROBE_HOST_OVERRIDE = "BNKSCOPE_TELEMETRY_PROBE_HOST"
_PROBE_TIMEOUT = 2.0

# The dashboards provisioned from `telemetry/grafana/dashboards/`. uid is stable;
# the title is what the operator sees in Grafana's own UI, so keeping them in
# step avoids a confusing mismatch.
DASHBOARDS: tuple[dict[str, str], ...] = (
    {
        "uid": "tmm-realtime",
        "title": "TMM Real-Time",
        "description": "CPU, throughput, connections and per-pool-member load",
    },
    {
        "uid": "tmm-ai-tokens",
        "title": "TMM AI Token Usage",
        "description": "iRule table token counters read out of DSSM",
    },
)


@dataclass
class TmmscopeStatus:
    """What bnkscope can say about the telemetry stack."""

    # The stack is enabled and its ports are known.
    configured: bool = False
    # Grafana actually answered. `configured` without this means the containers
    # were stopped out from under a backend that is still running.
    running: bool = False
    grafana_url: str | None = None
    prometheus_url: str | None = None
    updated_at: str | None = None
    # cluster= label values Prometheus currently holds f5tmm_up series for.
    streaming_clusters: list[str] = field(default_factory=list)
    # cluster= label -> seconds since its last f5tmm_up sample, over the last
    # few hours. Includes labels that have stopped, which the instant query
    # above cannot: five minutes after a cluster goes quiet it drops out of
    # `streaming_clusters` and looks exactly like one that never streamed.
    last_seen: dict[str, float] = field(default_factory=dict)
    detail: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "configured": self.configured,
            "running": self.running,
            "grafana_url": self.grafana_url,
            "prometheus_url": self.prometheus_url,
            "updated_at": self.updated_at,
            "streaming_clusters": self.streaming_clusters,
            "last_seen": dict(self.last_seen),
            "dashboards": [dict(d) for d in DASHBOARDS],
            "detail": self.detail,
        }


def _telemetry_host() -> str:
    """A host that reaches the published telemetry ports, from here and from a
    browser.

    Grafana is published on `$BNKSCOPE_UI_BIND` only, so a *specific* bind
    (`--listen 192.168.1.10`) does not answer on loopback — and the backend
    shares the host's network namespace, so probing "localhost" reported the
    whole stack down while Grafana was running and reachable. A wildcard bind
    does include loopback, and loopback is loopback, so both keep the name the
    browser-host rewrite downstream knows how to replace.

    Prometheus is not affected: it always publishes on 0.0.0.0, because the
    clusters push to it.
    """
    bind = os.getenv("BNKSCOPE_UI_BIND", "").strip()
    if bind in ("", "0.0.0.0", "::", "127.0.0.1", "localhost"):
        return "localhost"
    return bind


def read_endpoints() -> dict[str, Any] | None:
    """Where the telemetry stack is, or None when there isn't one.

    Set by `bnkscope up`, which negotiates the ports and passes them in. Never
    raises: this is read on every status poll, and an operator who ran
    `--no-telemetry` is a normal case, not an error.

    The shape is the one tmmscope's discovery file used to have, and it is kept
    because everything downstream — dashboards, streaming detection, injection's
    remote-write URL — already reads it without a second code path. See D-040.
    """
    if os.getenv("BNKSCOPE_TELEMETRY", "off") != "on":
        return None
    try:
        prom = int(os.environ["BNKSCOPE_PROMETHEUS_PORT"])
        graf = int(os.environ["BNKSCOPE_GRAFANA_PORT"])
    except (KeyError, ValueError):
        logger.warning(
            "BNKSCOPE_TELEMETRY is on but the Prometheus/Grafana ports are not "
            "set — treating the telemetry stack as absent"
        )
        return None
    host = _telemetry_host()
    return {
        "running": True,
        "source": "bnkscope",
        "prometheus": {
            "port": prom,
            "url": f"http://localhost:{prom}",
            "remote_write_url": f"http://localhost:{prom}/api/v1/write",
            "remote_write_path": "/api/v1/write",
        },
        "grafana": {
            "port": graf,
            "url": f"http://{host}:{graf}",
            "dashboard_url": f"http://{host}:{graf}/d/tmm-realtime",
        },
    }


def get_status() -> TmmscopeStatus:
    """Whether tmmscope is up, where, and which clusters are streaming to it."""
    doc = read_endpoints()
    if doc is None:
        return TmmscopeStatus(
            detail=(
                "No telemetry stack is running. Start it on the host with "
                "`bnkscope up --telemetry`. It cannot be started from in here: "
                "that needs the Docker socket."
            )
        )

    grafana = doc.get("grafana") or {}
    prometheus = doc.get("prometheus") or {}
    status = TmmscopeStatus(
        configured=bool(doc.get("running")),
        grafana_url=grafana.get("url"),
        prometheus_url=prometheus.get("url"),
        updated_at=doc.get("updated_at"),
    )

    if not status.grafana_url:
        status.detail = "The telemetry stack is up but names no Grafana URL."
        return status

    status.running = _grafana_healthy(status.grafana_url)
    if not status.running:
        status.detail = (
            f"A telemetry stack is recorded at {status.grafana_url}, but nothing "
            "answered there. It was most likely stopped out from under this "
            "backend — try `bnkscope up --telemetry` on the host."
        )
        return status

    if status.prometheus_url:
        status.streaming_clusters = _streaming_clusters(status.prometheus_url)
        status.last_seen = last_seen_ages(status.prometheus_url)
        if not status.streaming_clusters:
            stopped = sorted(status.last_seen)
            status.detail = (
                "The telemetry stack is up, but nothing is streaming to it right "
                f"now. {', '.join(stopped)} last delivered "
                f"{_ago(min(status.last_seen.values()))} ago."
                if stopped
                else "The telemetry stack is up, but no cluster is streaming to "
                "it yet. Add the exporter to a cluster's TMM pods below."
            )

    return status


def _ago(seconds: float) -> str:
    """A duration a human reads at a glance. Coarse on purpose."""
    if seconds < 90:
        return f"{int(seconds)}s"
    if seconds < 5400:
        return f"{int(seconds // 60)}m"
    return f"{seconds / 3600:.1f}h"


def prometheus_ingest() -> tuple[int, str] | None:
    """Where the exporter should push: (port, remote_write_path).

    From the negotiated ports rather than a default — Prometheus does not run on
    9491 when 9491 was taken, which is the whole reason they are discovered. The
    port is the *host* port; the address to reach that host from inside the
    cluster is derived per-pod at injection time.
    """
    doc = read_endpoints()
    if doc is None:
        return None
    prometheus = doc.get("prometheus") or {}
    port = prometheus.get("port")
    if not isinstance(port, int):
        return None
    path = prometheus.get("remote_write_path") or "/api/v1/write"
    return port, path


def dashboard_url(
    grafana_url: str,
    uid: str,
    cluster: str | None,
    theme: str,
    browser_host: str | None = None,
) -> str:
    """Embeddable URL for one dashboard, scoped to a cluster.

    ``kiosk`` strips Grafana's own chrome — inside an iframe its nav bar is
    duplicate furniture. ``var-cluster`` drives the dashboard's own template
    variable, which is how tmmscope scopes every panel.

    ``browser_host`` is the host the *browser* used to reach bnkscope, and it
    replaces the ``localhost`` tmmscope writes into its discovery file. That
    file is written for a producer sitting on the same machine; a browser on
    another machine reading "localhost" is told to look at itself, which is why
    the link silently did nothing when bnkscope was opened over the network.
    Only the hostname moves — the port is whatever tmmscope negotiated, and
    Grafana publishes it on all interfaces.
    """
    from urllib.parse import quote, urlparse, urlunparse

    base = grafana_url.rstrip("/")
    if browser_host:
        parsed = urlparse(base)
        if parsed.hostname in ("localhost", "127.0.0.1", "::1"):
            netloc = f"{browser_host}:{parsed.port}" if parsed.port else browser_host
            base = urlunparse(parsed._replace(netloc=netloc)).rstrip("/")

    params = [f"theme={quote(theme)}", "kiosk"]
    if cluster:
        params.insert(0, f"var-cluster={quote(cluster)}")
    return f"{base}/d/{quote(uid)}?{'&'.join(params)}"


def rebase_to_browser_host(url: str | None, browser_host: str | None) -> str | None:
    """Same loopback→browser-host swap, for a plain link rather than a dashboard."""
    if not url or not browser_host:
        return url
    from urllib.parse import urlparse, urlunparse

    parsed = urlparse(url)
    if parsed.hostname not in ("localhost", "127.0.0.1", "::1"):
        return url
    netloc = f"{browser_host}:{parsed.port}" if parsed.port else browser_host
    return urlunparse(parsed._replace(netloc=netloc))


# ---------------------------------------------------------------------------
# Probes
# ---------------------------------------------------------------------------


def _probe_url(url: str) -> str:
    """Rewrite a discovery-file URL so *this process* can reach it.

    Only the host is swapped; the port is whatever tmmscope negotiated and is
    published on the host either way.
    """
    host = os.getenv(_PROBE_HOST_OVERRIDE)
    if not host:
        return url
    from urllib.parse import urlparse, urlunparse

    parsed = urlparse(url)
    netloc = f"{host}:{parsed.port}" if parsed.port else host
    return urlunparse(parsed._replace(netloc=netloc))


def _grafana_healthy(url: str) -> bool:
    try:
        resp = requests.get(f"{_probe_url(url).rstrip('/')}/api/health", timeout=_PROBE_TIMEOUT)
    except requests.RequestException as exc:
        logger.debug("tmmscope Grafana probe failed: %s", exc)
        return False
    return resp.status_code == 200


#: Clusters streaming *now*. An instant query only returns series Prometheus
#: considers live — anything not scraped or pushed inside its staleness window
#: (5m by default) drops out on its own, which is the whole point.
#:
#: The label-values endpoint was the obvious thing to reach for and is wrong
#: here: with no time range it answers over the entire retention window, so a
#: cluster that stopped streaming ten hours ago still counted as streaming for
#: the rest of the day. `count by (cluster)` rather than the raw series keeps
#: the response one row per cluster instead of one per TMM pod.
_STREAMING_QUERY = "count by (cluster) (f5tmm_up)"


def _streaming_clusters(prometheus_url: str) -> list[str]:
    """Clusters with live f5tmm_up series, right now.

    Scoped to ``f5tmm_up`` rather than every ``cluster`` label value, so an
    unrelated series carrying the same label name cannot make a cluster look
    like it is streaming TMM telemetry when it is not.
    """
    names = {
        (row.get("metric") or {}).get("cluster")
        for row in _query(prometheus_url, _STREAMING_QUERY)
    }
    return sorted(n for n in names if isinstance(n, str) and n)


def _query(prometheus_url: str, query: str) -> list[dict[str, Any]]:
    """One instant query, never raising — an empty result reads as "nothing"."""
    try:
        resp = requests.get(
            f"{_probe_url(prometheus_url).rstrip('/')}/api/v1/query",
            params={"query": query},
            timeout=_PROBE_TIMEOUT,
        )
        resp.raise_for_status()
        payload = resp.json()
    except (requests.RequestException, ValueError) as exc:
        logger.debug("tmmscope Prometheus query failed: %s", exc)
        return []

    if payload.get("status") != "success":
        return []
    return (payload.get("data") or {}).get("result") or []


#: How far back "when did this last stream?" looks. An instant query cannot
#: answer it: Prometheus drops a series from the instant vector once nothing has
#: arrived for its staleness window, so five minutes after a cluster stops it
#: becomes indistinguishable from one that never streamed at all. That is the
#: exact gap that let a dead exporter read as "waiting for the first metrics".
_LAST_SEEN_WINDOW = "6h"

#: `timestamp()` inside a subquery returns the *sample's* timestamp at each
#: step, so the max over the window is when the last sample actually landed.
#: `timestamp(last_over_time(...))` looks like the obvious spelling and is
#: wrong — it returns the evaluation time, which is always now.
_WINDOW_AGE_QUERY = (
    f"time() - max by (cluster) (max_over_time(timestamp(f5tmm_up)[{_LAST_SEEN_WINDOW}:1m]))"
)

#: The same question with no subquery, and so no step quantisation. Needed
#: because a subquery evaluates on absolute step boundaries: a stream that
#: started after the last boundary is invisible to it, and the answer falls
#: back to the *previous* stream's last sample. Observed exactly that — a TMM
#: pod recreated a minute earlier and pushing happily reported as "last
#: delivered 29m ago", which is the same lie as the one this exists to fix,
#: pointed the other way. This one sees anything inside Prometheus's staleness
#: window; the subquery covers everything older.
_LIVE_AGE_QUERY = "time() - max by (cluster) (timestamp(f5tmm_up))"


def last_seen_ages(prometheus_url: str) -> dict[str, float]:
    """cluster label -> seconds since its most recent `f5tmm_up` sample.

    Covers clusters that have stopped as well as those still streaming, which is
    what turns "not streaming" into "stopped streaming nine minutes ago".

    Two queries, smaller age wins: neither one alone answers for both a live
    stream and a long-dead one. PromQL has no element-wise max between two
    vectors, so the combining happens here.
    """
    ages: dict[str, float] = {}
    for query in (_WINDOW_AGE_QUERY, _LIVE_AGE_QUERY):
        for row in _query(prometheus_url, query):
            name = (row.get("metric") or {}).get("cluster")
            try:
                age = max(0.0, float((row.get("value") or [None, None])[1]))
            except (TypeError, ValueError):
                continue
            if isinstance(name, str) and name:
                ages[name] = min(ages.get(name, age), age)
    return ages


def streaming_pods(prometheus_url: str, cluster_label: str) -> set[str]:
    """Pod names under `cluster_label` with live `f5tmm_up` series.

    Delivery is a per-pod fact. A cluster with several TMM pods keeps streaming
    when one of them stops, so a cluster-level answer reports everything as fine
    while one node has gone silent — which is precisely what a reinstalled DPU
    looks like.
    """
    escaped = cluster_label.replace("\\", "\\\\").replace('"', '\\"')
    payload = _query(prometheus_url, f'count by (pod) (f5tmm_up{{cluster="{escaped}"}})')
    return {
        pod
        for row in payload
        if isinstance(pod := (row.get("metric") or {}).get("pod"), str) and pod
    }
