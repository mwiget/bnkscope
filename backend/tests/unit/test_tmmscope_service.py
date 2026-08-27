"""Reading the telemetry stack's contract.

Two stacks can supply it: tmmscope's, discovered through its file, and
bnkscope's own under `up --telemetry`. Both publish the same shape on purpose,
so what is tested is the reading — the discovery, the Prometheus probe, the URLs
built from both, and which one wins when both are up.

The recurring theme is that a *file* saying the stack is up is only a claim; the
tests pin the distinction between "configured" and "running".
"""

import json

import pytest
import requests

from services import tmmscope_service as svc


@pytest.fixture()
def endpoints_at(tmp_path, monkeypatch):
    """Point the service at a discovery file written into tmp_path."""

    def _write(doc):
        path = tmp_path / "endpoints.json"
        path.write_text(json.dumps(doc) if not isinstance(doc, str) else doc)
        monkeypatch.setenv("BNKSCOPE_TMMSCOPE_ENDPOINTS", str(path))
        return path

    return _write


@pytest.fixture(autouse=True)
def _no_ambient_config(monkeypatch):
    monkeypatch.delenv("BNKSCOPE_TMMSCOPE_ENDPOINTS", raising=False)
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.delenv(svc._PROBE_HOST_OVERRIDE, raising=False)
    # bnkscope's own telemetry stack, when `up --telemetry` started one. Cleared
    # here so a test that sets it cannot leak into the rest of the file.
    for var in ("BNKSCOPE_TELEMETRY", "BNKSCOPE_PROMETHEUS_PORT", "BNKSCOPE_GRAFANA_PORT"):
        monkeypatch.delenv(var, raising=False)


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    """No test here may reach a real Prometheus.

    Not hypothetical: these run on the same machine as the stack they describe,
    so an unpatched probe quietly answered from the operator's *live* telemetry
    and a test asserting "nothing is streaming" failed with a real cluster name
    in the message. A test that passes only when the host is idle is not a test.
    """

    def _refuse(*args, **kwargs):
        raise requests.ConnectionError("no network in tests")

    monkeypatch.setattr(svc.requests, "get", _refuse)


def _live_doc(grafana_port=3000, prometheus_port=9491):
    """The shape `tmmscope up` writes."""
    return {
        "running": True,
        "prometheus": {
            "port": prometheus_port,
            "url": f"http://localhost:{prometheus_port}",
            "remote_write_url": f"http://localhost:{prometheus_port}/api/v1/write",
        },
        "grafana": {
            "port": grafana_port,
            "url": f"http://localhost:{grafana_port}",
            "dashboard_url": f"http://localhost:{grafana_port}/d/tmm-realtime",
        },
        "updated_at": "2026-08-23T00:00:00Z",
    }


class TestEndpointsPath:
    def test_explicit_override_wins(self, tmp_path, monkeypatch):
        monkeypatch.setenv("BNKSCOPE_TMMSCOPE_ENDPOINTS", str(tmp_path / "x.json"))
        assert svc.endpoints_path() == tmp_path / "x.json"

    def test_xdg_config_home_is_honoured(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        assert svc.endpoints_path() == tmp_path / "tmmscope" / "endpoints.json"

    def test_falls_back_to_the_mount(self):
        assert str(svc.endpoints_path()) == svc.DEFAULT_ENDPOINTS_PATH


class TestReadEndpoints:
    def test_absent_file_is_not_an_error(self):
        """An operator who has never run tmmscope is the normal case."""
        assert svc.read_endpoints() is None

    def test_malformed_json_is_not_an_error(self, endpoints_at):
        endpoints_at("{{{ not json")
        assert svc.read_endpoints() is None

    def test_a_non_mapping_document_is_rejected(self, endpoints_at):
        endpoints_at("[1, 2, 3]")
        assert svc.read_endpoints() is None


class TestGetStatus:
    def test_no_file_says_how_to_start_it(self):
        status = svc.get_status()
        assert status.configured is False
        assert status.running is False
        assert "tmmscope up" in status.detail

    def test_reports_running_when_grafana_answers(self, endpoints_at, monkeypatch):
        endpoints_at(_live_doc())
        monkeypatch.setattr(svc, "_grafana_healthy", lambda url: True)
        monkeypatch.setattr(svc, "_streaming_clusters", lambda url: ["lab-a"])
        monkeypatch.setattr(svc, "last_seen_ages", lambda url: {"lab-a": 2.0})

        status = svc.get_status()
        assert status.configured is True
        assert status.running is True
        assert status.grafana_url == "http://localhost:3000"
        assert status.streaming_clusters == ["lab-a"]
        assert status.detail is None

    def test_a_stale_file_is_configured_but_not_running(self, endpoints_at, monkeypatch):
        """The stack was stopped without rewriting the file. Saying "running"
        on the strength of a file would send the operator hunting the wrong
        thing."""
        endpoints_at(_live_doc())
        monkeypatch.setattr(svc, "_grafana_healthy", lambda url: False)

        status = svc.get_status()
        assert status.configured is True
        assert status.running is False
        assert "nothing answered" in status.detail

    def test_up_but_nothing_streaming_points_at_the_button(self, endpoints_at, monkeypatch):
        # Since D-036 injection is a control on the page, not a command to go
        # and type, so the detail must not send the operator to a terminal.
        endpoints_at(_live_doc())
        monkeypatch.setattr(svc, "_grafana_healthy", lambda url: True)
        monkeypatch.setattr(svc, "_streaming_clusters", lambda url: [])
        monkeypatch.setattr(svc, "last_seen_ages", lambda url: {})

        status = svc.get_status()
        assert status.running is True
        assert status.streaming_clusters == []
        assert "no cluster is streaming" in status.detail
        assert "tmmscope inject" not in status.detail

    def test_negotiated_ports_are_read_not_assumed(self, endpoints_at, monkeypatch):
        """tmmscope walks upward when 3000/9491 are taken and persists the
        choice, so hard-coding either is a bug that only bites on a busy box."""
        endpoints_at(_live_doc(grafana_port=3005, prometheus_port=9495))
        monkeypatch.setattr(svc, "_grafana_healthy", lambda url: True)
        monkeypatch.setattr(svc, "_streaming_clusters", lambda url: [])
        monkeypatch.setattr(svc, "last_seen_ages", lambda url: {})

        status = svc.get_status()
        assert status.grafana_url == "http://localhost:3005"
        assert status.prometheus_url == "http://localhost:9495"

    def test_a_file_with_no_grafana_url_says_so(self, endpoints_at):
        endpoints_at({"running": True, "grafana": {}})
        status = svc.get_status()
        assert status.running is False
        assert "no Grafana URL" in status.detail

    def test_status_serialises_the_dashboards(self, endpoints_at, monkeypatch):
        endpoints_at(_live_doc())
        monkeypatch.setattr(svc, "_grafana_healthy", lambda url: True)
        monkeypatch.setattr(svc, "_streaming_clusters", lambda url: ["lab-a"])
        monkeypatch.setattr(svc, "last_seen_ages", lambda url: {"lab-a": 2.0})

        payload = svc.get_status().as_dict()
        assert [d["uid"] for d in payload["dashboards"]] == ["tmm-realtime", "tmm-ai-tokens"]


class TestDashboardUrl:
    def test_scopes_to_the_cluster_and_hides_grafana_chrome(self):
        url = svc.dashboard_url("http://localhost:3000", "tmm-realtime", "lab-a", "dark")
        assert url.startswith("http://localhost:3000/d/tmm-realtime?")
        assert "var-cluster=lab-a" in url
        assert "theme=dark" in url
        # Inside an iframe Grafana's own nav is duplicate furniture.
        assert "kiosk" in url

    def test_omits_the_scope_when_there_is_none(self):
        url = svc.dashboard_url("http://localhost:3000", "tmm-realtime", None, "light")
        assert "var-cluster" not in url
        assert "theme=light" in url

    def test_escapes_a_cluster_name_with_url_characters(self):
        url = svc.dashboard_url("http://localhost:3000", "tmm-realtime", "a&b c", "dark")
        assert "a%26b%20c" in url

    def test_tolerates_a_trailing_slash_on_the_base(self):
        url = svc.dashboard_url("http://localhost:3000/", "tmm-realtime", None, "dark")
        assert "3000/d/tmm-realtime" in url


class TestProbeHostOverride:
    """Under the macOS/WSL2 bridge overlay 'localhost' is the container."""

    def test_no_override_leaves_the_url_alone(self):
        assert svc._probe_url("http://localhost:3000") == "http://localhost:3000"

    def test_the_host_is_swapped_and_the_port_kept(self, monkeypatch):
        monkeypatch.setenv(svc._PROBE_HOST_OVERRIDE, "host.docker.internal")
        assert svc._probe_url("http://localhost:9491") == "http://host.docker.internal:9491"

    def test_only_the_probe_is_rewritten_never_the_browser_url(self, monkeypatch):
        """The dashboard URL goes to the browser, which *is* on the host."""
        monkeypatch.setenv(svc._PROBE_HOST_OVERRIDE, "host.docker.internal")
        url = svc.dashboard_url("http://localhost:3000", "tmm-realtime", "lab-a", "dark")
        assert "localhost:3000" in url


def _query_result(*clusters):
    """A Prometheus instant-query body naming these clusters."""
    return {
        "status": "success",
        "data": {
            "resultType": "vector",
            "result": [
                {"metric": {"cluster": c}, "value": [1787559770.6, "1"]}
                for c in clusters
            ],
        },
    }


class TestStreamingClusters:
    def test_returns_sorted_cluster_names(self, monkeypatch):
        class _Resp:
            status_code = 200

            def raise_for_status(self):
                pass

            def json(self):
                return _query_result("zeta", "alpha")

        monkeypatch.setattr(svc.requests, "get", lambda *a, **k: _Resp())
        assert svc._streaming_clusters("http://localhost:9491") == ["alpha", "zeta"]

    def test_asks_what_is_live_now_not_what_ever_was(self, monkeypatch):
        """The label-values endpoint answers over the whole retention window
        with no time range, so a cluster that stopped streaming hours ago went
        on being reported as streaming for the rest of the day — while its
        dashboards showed nothing. An instant query drops a series as soon as
        it goes stale, which is what the page claims to be showing."""
        seen = {}

        class _Resp:
            status_code = 200

            def raise_for_status(self):
                pass

            def json(self):
                return _query_result()

        def _get(url, params=None, timeout=None):
            seen["url"], seen["params"] = url, params
            return _Resp()

        monkeypatch.setattr(svc.requests, "get", _get)
        svc._streaming_clusters("http://localhost:9491")

        assert seen["url"].endswith("/api/v1/query")
        # Scoped to f5tmm_up so an unrelated series carrying a `cluster` label
        # cannot make a cluster look like it is streaming TMM telemetry.
        assert "f5tmm_up" in seen["params"]["query"]

    def test_one_row_per_cluster_not_per_pod(self, monkeypatch):
        # A cluster runs several TMMs; the raw series would name it once each.
        class _Resp:
            status_code = 200

            def raise_for_status(self):
                pass

            def json(self):
                return _query_result("scope", "scope", "scope")

        monkeypatch.setattr(svc.requests, "get", lambda *a, **k: _Resp())
        assert svc._streaming_clusters("http://localhost:9491") == ["scope"]

    def test_a_series_without_a_cluster_label_is_skipped(self, monkeypatch):
        class _Resp:
            status_code = 200

            def raise_for_status(self):
                pass

            def json(self):
                body = _query_result("scope")
                body["data"]["result"].append({"metric": {}, "value": [0, "1"]})
                return body

        monkeypatch.setattr(svc.requests, "get", lambda *a, **k: _Resp())
        assert svc._streaming_clusters("http://localhost:9491") == ["scope"]

    def test_an_unreachable_prometheus_is_empty_not_an_exception(self, monkeypatch):
        def _boom(*a, **k):
            raise requests.ConnectionError("refused")

        monkeypatch.setattr(svc.requests, "get", _boom)
        assert svc._streaming_clusters("http://localhost:9491") == []


class TestLastSeen:
    """When a cluster last delivered, as opposed to whether it is delivering.

    Prometheus drops a series from the instant vector once nothing has arrived
    for its staleness window, so five minutes after a cluster stops it becomes
    indistinguishable from one that never streamed at all. That gap is what let
    a dead exporter read as "waiting for the first metrics".
    """

    @staticmethod
    def _serve(monkeypatch, by_query):
        """Answer each of the two queries with its own result rows."""
        seen = []

        class _Resp:
            def __init__(self, body):
                self.status_code = 200
                self._body = body

            def raise_for_status(self):
                pass

            def json(self):
                return {"status": "success", "data": {"result": self._body}}

        def _get(url, params=None, timeout=None):
            query = params["query"]
            seen.append(query)
            rows = next(
                (v for k, v in by_query.items() if k in query),
                [],
            )
            return _Resp(rows)

        monkeypatch.setattr(svc.requests, "get", _get)
        return seen

    def test_reports_age_per_cluster(self, monkeypatch):
        rows = [
            {"metric": {"cluster": "lab-a"}, "value": [0, "543.2"]},
            {"metric": {"cluster": "lab-b"}, "value": [0, "2.1"]},
        ]
        self._serve(monkeypatch, {"max_over_time": rows, "timestamp(f5tmm_up))": rows})

        ages = svc.last_seen_ages("http://localhost:9491")
        assert round(ages["lab-a"]) == 543
        assert round(ages["lab-b"]) == 2

    def test_asks_over_a_window_not_an_instant(self, monkeypatch):
        """`timestamp(last_over_time(...))` is the obvious spelling and returns
        the *evaluation* time — always now, for every cluster. The subquery is
        the one that answers when the sample actually landed."""
        seen = self._serve(monkeypatch, {})
        svc.last_seen_ages("http://localhost:9491")

        assert any("max_over_time(timestamp(f5tmm_up)" in q for q in seen)
        assert not any("last_over_time" in q for q in seen)

    def test_a_stream_that_just_restarted_is_not_reported_as_long_dead(
        self, monkeypatch
    ):
        """A subquery evaluates on absolute step boundaries, so a stream that
        started after the last boundary is invisible to it and the answer falls
        back to the *previous* stream's last sample. Observed live: a TMM pod
        recreated a minute earlier and pushing happily reported as "last
        delivered 29m ago" — the same lie this exists to fix, pointed the other
        way."""
        self._serve(
            monkeypatch,
            {
                # The subquery still sees only the dead predecessor.
                "max_over_time": [
                    {"metric": {"cluster": "lab-a"}, "value": [0, "1741"]}
                ],
                # The instant query, with no step to fall between, sees the new one.
                "timestamp(f5tmm_up))": [
                    {"metric": {"cluster": "lab-a"}, "value": [0, "2.1"]}
                ],
            },
        )

        assert round(svc.last_seen_ages("http://localhost:9491")["lab-a"]) == 2

    def test_a_cluster_only_the_window_can_see_still_gets_an_age(self, monkeypatch):
        """The converse: stopped hours ago, so the instant query has dropped it
        entirely. The window is the only thing that still knows when."""
        self._serve(
            monkeypatch,
            {
                "max_over_time": [
                    {"metric": {"cluster": "lab-a"}, "value": [0, "9000"]}
                ],
                "timestamp(f5tmm_up))": [],
            },
        )

        assert round(svc.last_seen_ages("http://localhost:9491")["lab-a"]) == 9000

    def test_an_unreachable_prometheus_is_empty_not_an_exception(self, monkeypatch):
        def _boom(*a, **k):
            raise requests.ConnectionError("refused")

        monkeypatch.setattr(svc.requests, "get", _boom)
        assert svc.last_seen_ages("http://localhost:9491") == {}


class TestStreamingPods:
    """Delivery is a per-pod fact.

    A cluster with several TMM pods keeps streaming when one of them stops, so
    the cluster-level answer stays green while one node delivers nothing —
    which is exactly what a reinstalled DPU looks like.
    """

    def test_returns_the_pods_delivering_under_that_label(self, monkeypatch):
        class _Resp:
            status_code = 200

            def raise_for_status(self):
                pass

            def json(self):
                return {
                    "status": "success",
                    "data": {
                        "result": [
                            {"metric": {"pod": "tmm-a"}, "value": [0, "1"]},
                            {"metric": {"pod": "tmm-b"}, "value": [0, "1"]},
                        ]
                    },
                }

        monkeypatch.setattr(svc.requests, "get", lambda *a, **k: _Resp())
        assert svc.streaming_pods("http://localhost:9491", "lab-a") == {
            "tmm-a",
            "tmm-b",
        }

    def test_scopes_the_query_to_the_cluster_label(self, monkeypatch):
        seen = {}

        class _Resp:
            status_code = 200

            def raise_for_status(self):
                pass

            def json(self):
                return {"status": "success", "data": {"result": []}}

        def _get(url, params=None, timeout=None):
            seen["query"] = params["query"]
            return _Resp()

        monkeypatch.setattr(svc.requests, "get", _get)
        svc.streaming_pods("http://localhost:9491", "lab-a")

        assert seen["query"] == 'count by (pod) (f5tmm_up{cluster="lab-a"})'

    def test_a_quote_in_the_label_cannot_break_out_of_the_matcher(self, monkeypatch):
        """`tmmscope inject --cluster` names the label freely, so it reaches
        here as operator input."""
        seen = {}

        class _Resp:
            status_code = 200

            def raise_for_status(self):
                pass

            def json(self):
                return {"status": "success", "data": {"result": []}}

        def _get(url, params=None, timeout=None):
            seen["query"] = params["query"]
            return _Resp()

        monkeypatch.setattr(svc.requests, "get", _get)
        svc.streaming_pods("http://localhost:9491", 'lab"a')

        assert seen["query"] == r'count by (pod) (f5tmm_up{cluster="lab\"a"})'


class TestOwnStackPreference:
    """bnkscope running its own Prometheus + Grafana (`up --telemetry`).

    The stack is discovered through the same shape tmmscope publishes, so
    nothing downstream needs a second code path. What is worth pinning is the
    precedence: when both are up, the one this process started is the one its
    own UI must point at — otherwise `--telemetry` appears to do nothing.
    """

    def test_prefers_its_own_over_tmmscopes_file(self, monkeypatch, endpoints_at):
        endpoints_at(_live_doc(grafana_port=3000, prometheus_port=9491))
        monkeypatch.setenv("BNKSCOPE_TELEMETRY", "on")
        monkeypatch.setenv("BNKSCOPE_PROMETHEUS_PORT", "19491")
        monkeypatch.setenv("BNKSCOPE_GRAFANA_PORT", "13000")

        doc = svc.read_endpoints()

        assert doc["source"] == "bnkscope"
        assert doc["prometheus"]["port"] == 19491
        assert doc["grafana"]["port"] == 13000

    def test_falls_back_to_tmmscope_when_its_own_is_off(self, monkeypatch, endpoints_at):
        endpoints_at(_live_doc(grafana_port=3000, prometheus_port=9491))
        monkeypatch.setenv("BNKSCOPE_TELEMETRY", "off")
        monkeypatch.setenv("BNKSCOPE_PROMETHEUS_PORT", "19491")

        doc = svc.read_endpoints()

        assert doc.get("source") != "bnkscope"
        assert doc["prometheus"]["port"] == 9491

    def test_falls_back_when_the_ports_are_missing(self, monkeypatch, endpoints_at):
        # `on` without ports is a broken launch, not a reason to report no
        # stack at all when tmmscope's is sitting right there.
        endpoints_at(_live_doc(prometheus_port=9491))
        monkeypatch.setenv("BNKSCOPE_TELEMETRY", "on")
        monkeypatch.delenv("BNKSCOPE_PROMETHEUS_PORT", raising=False)
        monkeypatch.delenv("BNKSCOPE_GRAFANA_PORT", raising=False)

        doc = svc.read_endpoints()

        assert doc["prometheus"]["port"] == 9491

    def test_publishes_the_remote_write_path_injection_needs(self, monkeypatch):
        monkeypatch.setenv("BNKSCOPE_TELEMETRY", "on")
        monkeypatch.setenv("BNKSCOPE_PROMETHEUS_PORT", "9491")
        monkeypatch.setenv("BNKSCOPE_GRAFANA_PORT", "3000")

        assert svc.prometheus_ingest() == (9491, "/api/v1/write")

    def test_no_stack_at_all_is_not_an_error(self, monkeypatch, tmp_path):
        monkeypatch.setenv("BNKSCOPE_TELEMETRY", "off")
        monkeypatch.setenv("BNKSCOPE_TMMSCOPE_ENDPOINTS", str(tmp_path / "absent.json"))

        assert svc.read_endpoints() is None
        assert svc.prometheus_ingest() is None


class TestTelemetryHost:
    """Which host the backend probes and advertises for Grafana.

    Grafana is published on `$BNKSCOPE_UI_BIND` alone. When that is a specific
    address, loopback does not answer — and the backend, sharing the host's
    network namespace, reported "nothing answered there" for a stack that was
    running and reachable from every browser on the network. TMM Live went
    blank the moment anyone ran `bnkscope up --listen <lan-ip>`, which is the
    exact situation the page exists for.
    """

    @pytest.mark.parametrize(
        "bind, expected",
        [
            # Loopback and the wildcards all answer on loopback, and keeping
            # the name is what lets the browser-host rewrite downstream send a
            # remote browser to itself rather than to the operator's laptop.
            ("127.0.0.1", "localhost"),
            ("localhost", "localhost"),
            ("0.0.0.0", "localhost"),
            ("::", "localhost"),
            ("", "localhost"),
            # A specific bind does not answer on loopback. The broken case.
            ("192.168.68.113", "192.168.68.113"),
            ("100.112.205.85", "100.112.205.85"),
        ],
    )
    def test_picks_a_host_that_answers(self, bind, expected, monkeypatch):
        monkeypatch.setenv("BNKSCOPE_UI_BIND", bind)
        assert svc._telemetry_host() == expected

    def test_unset_is_loopback(self, monkeypatch):
        monkeypatch.delenv("BNKSCOPE_UI_BIND", raising=False)
        assert svc._telemetry_host() == "localhost"

    def test_the_stack_it_publishes_uses_that_host(self, monkeypatch):
        monkeypatch.setenv("BNKSCOPE_TELEMETRY", "on")
        monkeypatch.setenv("BNKSCOPE_PROMETHEUS_PORT", "9491")
        monkeypatch.setenv("BNKSCOPE_GRAFANA_PORT", "3000")
        monkeypatch.setenv("BNKSCOPE_UI_BIND", "192.168.68.113")

        doc = svc.read_endpoints()

        assert doc["grafana"]["url"] == "http://192.168.68.113:3000"
        assert (
            doc["grafana"]["dashboard_url"]
            == "http://192.168.68.113:3000/d/tmm-realtime"
        )

    def test_prometheus_stays_on_loopback(self, monkeypatch):
        # It publishes on 0.0.0.0 whatever the bind is — the clusters push to
        # it — so loopback always reaches it, and moving it would only make the
        # remote-write URL handed to an exporter worse.
        monkeypatch.setenv("BNKSCOPE_TELEMETRY", "on")
        monkeypatch.setenv("BNKSCOPE_PROMETHEUS_PORT", "9491")
        monkeypatch.setenv("BNKSCOPE_GRAFANA_PORT", "3000")
        monkeypatch.setenv("BNKSCOPE_UI_BIND", "192.168.68.113")

        doc = svc.read_endpoints()

        assert doc["prometheus"]["url"] == "http://localhost:9491"
        assert doc["prometheus"]["remote_write_url"] == (
            "http://localhost:9491/api/v1/write"
        )
