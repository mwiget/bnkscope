"""
Unit tests for services.nico.fetch — the pure shaping helpers.

The I/O halves (Kubernetes reads, Forge calls) are exercised through stand-ins:
a fake CoreV1Api for the endpoint resolution, and a fake ForgeClient that
replays canned RPC payloads. No live cluster, no gRPC.
"""

from types import SimpleNamespace
from unittest.mock import patch

from services.nico.constants import PROVIDER_LOG_WINDOW_SEC
from services.nico.fetch import (
    _dependencies,
    _fetch_inventory,
    _fetch_load_balancers,
    _lifecycle_state,
    _recent_errors,
    _roll_up_tenants,
    _service_endpoints,
)


class FakeForge:
    """Replays canned Forge responses, keyed by method name.

    `absent` names RPCs this build does not declare — the vanilla case, where
    the whole LoadBalancerService family is missing. `denied` names RPCs the
    client certificate was refused. Both default to empty, so a test that does
    not care sees a build that declares everything and refuses nothing.
    """

    def __init__(self, responses, absent=(), denied=()):
        self.responses = responses
        self.calls = []
        self.absent = set(absent)
        self.denied = set(denied)

    def try_call(self, method, body=None):
        self.calls.append((method, body))
        value = self.responses.get(method, {})
        return value(body) if callable(value) else value

    def has_method(self, method):
        return method not in self.absent


# ---------------------------------------------------------------------------
# Endpoint resolution
# ---------------------------------------------------------------------------

_POD_LABELS = {"app.kubernetes.io/name": "nico-api", "app.kubernetes.io/component": "api"}


def _service(
    name="nico-api",
    kind="NodePort",
    port=1079,
    target_port=1079,
    node_port=31079,
    ingress=(),
    selector=None,
):
    return SimpleNamespace(
        metadata=SimpleNamespace(name=name),
        spec=SimpleNamespace(
            type=kind,
            selector=_POD_LABELS if selector is None else selector,
            ports=[
                SimpleNamespace(port=port, target_port=target_port, node_port=node_port)
            ],
        ),
        status=SimpleNamespace(
            load_balancer=SimpleNamespace(
                ingress=[SimpleNamespace(ip=ip, hostname=None) for ip in ingress]
            )
        ),
    )


class _Core:
    """Stand-in for CoreV1Api's Service list."""

    def __init__(self, *services):
        self._services = services

    def list_namespaced_service(self, **_kwargs):
        if self._services and isinstance(self._services[0], Exception):
            raise self._services[0]
        return SimpleNamespace(items=list(self._services))


def _resolve(core, api_server="https://192.168.68.66:6443", **kwargs):
    """`_service_endpoints` with the arguments every case shares."""
    return _service_endpoints(core, "nico-system", api_server, _POD_LABELS, **kwargs)


class TestServiceEndpoints:
    def test_a_nodeport_resolves_against_the_kube_api_host(self):
        """The NodePort is on the node, and the kubeconfig's server URL is the
        only address we know reaches it."""
        with patch("services.nico.fetch.tcp_reachable", return_value=True):
            out = _resolve(_Core(_service()))
        assert out["reachable"] is True
        assert out["grpc"] == "192.168.68.66:31079"
        assert out["kind"] == "nodeport"
        assert out["webUi"] == "https://192.168.68.66:31079/admin/"

    def test_a_loadbalancer_address_is_preferred_over_the_nodeport(self):
        with patch("services.nico.fetch.tcp_reachable", return_value=True):
            out = _resolve(_Core(_service(kind="LoadBalancer", ingress=("10.1.1.5",))))
        assert out["grpc"] == "10.1.1.5:1079"
        assert out["kind"] == "loadbalancer"

    def test_a_second_service_on_the_same_pods_is_found_by_selector(self):
        """A vanilla site fronts nico-api twice: a ClusterIP named `nico-api`
        and a `nico-api-external` LoadBalancer. Only the second is routable,
        and looking up the canonical name would never see it."""
        with patch("services.nico.fetch.tcp_reachable", return_value=True):
            out = _resolve(
                _Core(
                    _service(kind="ClusterIP", node_port=None),
                    _service(
                        name="nico-api-external",
                        kind="LoadBalancer",
                        port=443,
                        node_port=31306,
                        ingress=("10.100.50.240",),
                    ),
                )
            )
        assert out["reachable"] is True
        assert out["grpc"] == "10.100.50.240:443"
        assert out["kind"] == "loadbalancer"

    def test_a_service_selecting_other_pods_is_not_a_candidate(self):
        """`nico-api-metrics` and friends share the namespace, not the pod."""
        out = _resolve(
            _Core(_service(name="somebody-else", selector={"app": "postgres"}))
        )
        assert out["candidates"] == []
        assert "selects the nico-api pod" in out["detail"]

    def test_an_unroutable_candidate_is_reported_not_claimed(self):
        """A Service can advertise an address on a subnet with no route to it —
        that resolves and prints fine and then answers nothing."""
        with patch("services.nico.fetch.tcp_reachable", return_value=False):
            out = _resolve(_Core(_service()))
        assert out["reachable"] is False
        assert out["grpc"] == "192.168.68.66:31079"
        assert "not routable" in out["detail"]

    def test_clusterip_only_falls_back_to_the_apiserver_tunnel(self):
        """The case the reference lab is in: no advertised address is routable,
        but the apiserver is — every other read on the page proves it."""
        out = _resolve(
            _Core(_service(kind="ClusterIP", node_port=None)), api_pod="nico-api-abc"
        )
        assert out["reachable"] is True
        assert out["kind"] == "portforward"
        assert out["tunnel"] == {"pod": "nico-api-abc", "port": 1079}
        assert out["host"] is None

    def test_the_tunnel_is_the_last_resort_not_the_first(self):
        """It costs an apiserver session per fetch; a direct address does not."""
        with patch("services.nico.fetch.tcp_reachable", return_value=True):
            out = _resolve(_Core(_service()), api_pod="nico-api-abc")
        assert out["kind"] == "nodeport"
        assert out["tunnel"] is None

    def test_an_unreachable_admin_ui_is_reported_but_not_offered_as_a_link(self):
        """bnkscope binds loopback, so the operator's browser is on this host.
        An address that failed our own TCP screen is dead for them too, and
        offering it as a link just sends them into a timeout."""
        with patch("services.nico.fetch.tcp_reachable", return_value=False):
            out = _resolve(
                _Core(_service(kind="LoadBalancer", ingress=("10.100.50.240",))),
                api_pod="nico-api-abc",
            )
        assert out["kind"] == "portforward"
        # Still reported — it is the documented address, and worth showing.
        assert out["webUi"] == "https://10.100.50.240:1079/admin/"
        assert out["webUiReachable"] is False

    def test_a_reachable_admin_ui_is_offered_as_a_link(self):
        with patch("services.nico.fetch.tcp_reachable", return_value=True):
            out = _resolve(_Core(_service(kind="LoadBalancer", ingress=("10.1.1.5",))))
        assert out["webUi"] == "https://10.1.1.5:1079/admin/"
        assert out["webUiReachable"] is True

    def test_a_port_forward_command_is_offered_when_nothing_answers(self):
        """The admin UI shares the gRPC listener, so the same forward that
        reaches Forge reaches the UI — and it is the one path that works when
        every advertised address is on an unrouted subnet."""
        with patch("services.nico.fetch.tcp_reachable", return_value=False):
            out = _resolve(
                _Core(_service(kind="LoadBalancer", ingress=("10.100.50.240",))),
                api_pod="nico-api-abc",
            )
        assert out["portForward"]["command"] == (
            "kubectl port-forward -n nico-system svc/nico-api 1079:1079"
        )
        assert out["portForward"]["webUi"] == "https://127.0.0.1:1079/admin/"

    def test_the_forward_targets_the_pod_when_no_service_exposes_the_grpc_port(self):
        """An external Service republishes 1079 as 443; forwarding to it would
        name a port that is not the one the UI is on."""
        with patch("services.nico.fetch.tcp_reachable", return_value=False):
            out = _resolve(
                _Core(
                    _service(name="nico-api-external", kind="LoadBalancer",
                             port=443, target_port=1079, ingress=("10.100.50.240",))
                ),
                api_pod="nico-api-abc",
            )
        assert "pod/nico-api-abc" in out["portForward"]["command"]

    def test_clusterip_only_without_a_tunnel_says_what_to_do(self):
        out = _resolve(_Core(_service(kind="ClusterIP", node_port=None)))
        assert out["reachable"] is False
        assert out["candidates"] == []
        assert "NodePort" in out["detail"]

    def test_an_override_outranks_every_discovered_candidate(self):
        with patch("services.nico.fetch.tcp_reachable", return_value=True):
            out = _resolve(
                _Core(_service(kind="LoadBalancer", ingress=("10.1.1.5",))),
                api_pod="nico-api-abc",
                override="127.0.0.1:11079",
            )
        assert out["kind"] == "override"
        assert out["grpc"] == "127.0.0.1:11079"

    def test_a_stale_override_falls_through_rather_than_dead_ending(self):
        """An override the operator forgot to tear down should not be the reason
        a reachable cluster reads as unreachable."""
        reachable = {("10.1.1.5", 1079)}
        with patch(
            "services.nico.fetch.tcp_reachable",
            side_effect=lambda h, p: (h, p) in reachable,
        ):
            out = _resolve(
                _Core(_service(kind="LoadBalancer", ingress=("10.1.1.5",))),
                override="127.0.0.1:11079",
            )
        assert out["kind"] == "loadbalancer"
        assert out["grpc"] == "10.1.1.5:1079"

    def test_the_grpc_port_is_matched_on_its_in_cluster_target(self):
        """An external Service republishes 1079 as 443; `port` alone would pick
        the wrong thing on a Service that exposes several."""
        svc = _service(kind="LoadBalancer", port=443, target_port=1079,
                       ingress=("10.100.50.240",))
        with patch("services.nico.fetch.tcp_reachable", return_value=True):
            out = _resolve(_Core(svc))
        assert out["grpc"] == "10.100.50.240:443"

    def test_a_malformed_override_is_ignored_not_fatal(self):
        """`meta_data` is a free-form JSON column, so a hand-edited value must
        not take the whole fetch down — the module never raises for a section
        it cannot read."""
        with patch("services.nico.fetch.tcp_reachable", return_value=True):
            out = _resolve(_Core(_service()), override="not-an-address")
        assert out["kind"] == "nodeport"
        assert [c["via"] for c in out["candidates"]] == ["nodeport"]

    def test_no_running_pod_says_so_rather_than_blaming_a_service(self):
        out = _service_endpoints(_Core(), "nico-system", "https://host:6443", {})
        assert out["reachable"] is False
        assert "no running nico-api pod" in out["detail"]

    def test_candidates_are_screened_concurrently(self):
        """Sequential screening cost one REACH_TIMEOUT per unroutable address —
        ~2.9s of the deployment read on the reference lab. Concurrently it is
        one timeout total, so the screens must overlap in time."""
        import threading
        import time

        lock = threading.Lock()
        live = 0
        peak = 0

        def slow_screen(_host, _port):
            nonlocal live, peak
            with lock:
                live += 1
                peak = max(peak, live)
            time.sleep(0.05)
            with lock:
                live -= 1
            return False

        with patch("services.nico.fetch.tcp_reachable", side_effect=slow_screen):
            out = _resolve(
                _Core(
                    _service(kind="LoadBalancer", ingress=("10.1.1.5",)),
                    _service(name="nico-api-external", kind="NodePort", node_port=31306),
                )
            )
        assert out["reachable"] is False
        assert peak > 1, f"screens ran one at a time (peak concurrency {peak})"

    def test_the_winner_is_the_best_ranked_not_the_first_to_answer(self):
        """A NodePort that answers instantly must not beat a LoadBalancer that
        answers a little later — the preference order is the point."""
        import time

        def screen(host, _port):
            if host == "10.1.1.5":  # the LoadBalancer: slower, but preferred
                time.sleep(0.1)
            return True

        with patch("services.nico.fetch.tcp_reachable", side_effect=screen):
            out = _resolve(
                _Core(
                    _service(kind="LoadBalancer", ingress=("10.1.1.5",)),
                    _service(name="nico-api-external", kind="NodePort", node_port=31306),
                )
            )
        assert out["kind"] == "loadbalancer"
        assert out["grpc"] == "10.1.1.5:1079"

    def test_an_unreadable_service_list_is_a_soft_failure(self):
        out = _resolve(_Core(RuntimeError("forbidden")))
        assert out["reachable"] is False
        assert out["candidates"] == []


# ---------------------------------------------------------------------------
# Forge shaping
# ---------------------------------------------------------------------------

_LB_PAYLOAD = {
    "loadBalancerServices": [
        {
            "id": {"value": "lb-1"},
            "metadata": {
                "name": "web",
                "description": "tenant web ingress",
                "labels": [{"key": "env", "value": "prod"}],
            },
            "config": {
                "tenantOrganizationId": "acme",
                "vpcId": {"value": "vpc-1"},
                "vipSegmentId": {"value": "seg-1"},
                "provider": "tmm",
                "listeners": [
                    {"name": "http", "port": 80,
                     "protocol": "LB_PROTOCOL_TCP", "poolName": "origins"}
                ],
                "pools": [
                    {
                        "name": "origins",
                        "lbMethod": "LB_METHOD_ROUND_ROBIN",
                        "minActiveMembers": 1,
                        "members": [{"address": "192.168.100.9", "port": 80}],
                        "monitors": [
                            {"name": "http-health", "type": "LB_MONITOR_TYPE_HTTP",
                             "intervalSec": 5, "timeoutSec": 16, "recv": "HTTP/1."}
                        ],
                    }
                ],
            },
            "status": {
                "vipAddress": "10.0.121.33",
                "deploymentStatus": "LB_DEPLOYMENT_STATUS_READY",
                "programmedPods": 2,
                "declTmmGeneration": "2",
            },
            "updated": "2026-08-25T12:26:42Z",
        }
    ]
}


class TestLoadBalancers:
    def test_enum_prefixes_are_stripped(self):
        """`LB_DEPLOYMENT_STATUS_READY` in a status column is noise; the prefix
        is constant across every value the enum can take."""
        forge = FakeForge({
            "SearchLoadBalancerServices": {"loadBalancerServiceIds": [{"value": "lb-1"}]},
            "GetLoadBalancerServices": _LB_PAYLOAD,
        })
        [lb] = _fetch_load_balancers(forge)
        assert lb["status"] == "READY"
        assert lb["listeners"][0]["protocol"] == "TCP"
        assert lb["pools"][0]["lbMethod"] == "ROUND_ROBIN"
        assert lb["pools"][0]["monitors"][0]["type"] == "HTTP"

    def test_the_whole_pool_survives_the_shaping(self):
        forge = FakeForge({
            "SearchLoadBalancerServices": {"loadBalancerServiceIds": [{"value": "lb-1"}]},
            "GetLoadBalancerServices": _LB_PAYLOAD,
        })
        [lb] = _fetch_load_balancers(forge)
        assert lb["vip"] == "10.0.121.33"
        assert lb["programmedPods"] == 2
        assert lb["labels"] == {"env": "prod"}
        assert lb["pools"][0]["members"] == [{"address": "192.168.100.9", "port": 80}]

    def test_no_services_skips_the_second_call(self):
        """`GetLoadBalancerServices` with an empty id list is a wasted round
        trip against a lab that may be several hops away."""
        forge = FakeForge({"SearchLoadBalancerServices": {}})
        assert _fetch_load_balancers(forge) == []
        assert [m for m, _ in forge.calls] == ["SearchLoadBalancerServices"]


class TestTenantRollup:
    def test_tenants_are_derived_from_what_owns_a_vpc_or_an_lb(self):
        """NICo's Tenant table is unused in this deployment — `provision-tenant`
        only creates VPCs — so a tenant is whatever owns something."""
        vpcs = [
            {"id": "v1", "tenant": "acme", "vni": 2024530,
             "prefixes": [{"prefix": "10.0.121.32/27"}]},
            {"id": "v2", "tenant": "bravo", "vni": 2024500, "prefixes": []},
        ]
        lbs = [
            {"tenant": "acme", "vip": "10.0.121.33", "status": "READY"},
            {"tenant": "charlie", "vip": "10.0.123.33", "status": "PENDING"},
        ]
        rolled = {t["id"]: t for t in _roll_up_tenants(vpcs, lbs)}

        assert sorted(rolled) == ["acme", "bravo", "charlie"]
        assert rolled["acme"]["vipPrefixes"] == ["10.0.121.32/27"]
        assert rolled["acme"]["lbsReady"] == 1
        # A tenant with a load balancer but no VPC is still a tenant.
        assert rolled["charlie"]["vpcCount"] == 0
        assert rolled["charlie"]["lbsReady"] == 0


class TestLifecycleState:
    def test_the_plain_state_field_wins(self):
        assert _lifecycle_state({"state": "READY"}) == "READY"

    def test_tenant_state_is_the_next_source(self):
        assert _lifecycle_state({"status": {"tenantState": "READY"}}) == "READY"

    def test_the_json_in_a_string_lifecycle_is_the_fallback(self):
        obj = {"status": {"lifecycle": {"state": '{"state":"ready"}'}}}
        assert _lifecycle_state(obj) == "ready"

    def test_an_object_with_no_state_at_all_is_none(self):
        assert _lifecycle_state({"status": {}}) is None


class TestInventory:
    def test_one_failing_rpc_does_not_blank_the_rest(self):
        """Most of the inventory is optional: a DPF Zero-Touch lab legitimately
        has no machines, and some of those RPCs are not wired up at all."""
        forge = FakeForge({
            "SearchLoadBalancerServices": {"loadBalancerServiceIds": [{"value": "lb-1"}]},
            "GetLoadBalancerServices": _LB_PAYLOAD,
        })
        inventory = _fetch_inventory(forge)
        assert len(inventory["loadBalancers"]) == 1
        assert inventory["tenants"][0]["id"] == "acme"
        assert inventory["vpcs"] == []
        assert inventory["fleet"] == {
            "machines": 0, "switches": 0, "racks": 0, "instances": 0,
        }


class TestProviderLogs:
    def test_the_read_is_bounded_to_a_recent_window(self):
        """The reconciler logs a failed poll and nothing on recovery, so one
        transient cold-start error stays the last line of an otherwise silent
        log for the life of the pod. Read by tail alone that is
        indistinguishable from an outage still in progress — which degraded a
        cluster whose load balancers were all READY and reprogramming every
        30 seconds.
        """
        seen = {}

        class Core:
            def read_namespaced_pod_log(self, **kwargs):
                seen.update(kwargs)
                return ""

        _recent_errors(Core(), "nico-system", "provider-1")
        assert seen["since_seconds"] == PROVIDER_LOG_WINDOW_SEC
        assert seen["tail_lines"] > 0

    def test_a_quiet_window_reports_nothing(self):
        """An operator that failed days ago and has been fine since has no
        current complaint to make."""
        class Core:
            def read_namespaced_pod_log(self, **_kwargs):
                return ""

        assert _recent_errors(Core(), "nico-system", "provider-1") == []

    def test_ansi_escapes_are_stripped(self):
        """The Rust operators colourise even when stdout is not a terminal, and
        raw SGR escapes render as literal garbage in HTML."""
        class Core:
            def read_namespaced_pod_log(self, **_kwargs):
                return (
                    "\x1b[2m2026-08-19T04:11:59Z\x1b[0m \x1b[31mERROR\x1b[0m poll failed\n"
                    "\x1b[2m2026-08-19T04:12:00Z\x1b[0m INFO all good\n"
                )

        assert _recent_errors(Core(), "nico-system", "provider-1") == [
            "2026-08-19T04:11:59Z ERROR poll failed"
        ]

    def test_an_unreadable_log_is_empty_not_fatal(self):
        class Core:
            def read_namespaced_pod_log(self, **_kwargs):
                raise RuntimeError("container not found")

        assert _recent_errors(Core(), "nico-system", "provider-1") == []


# ---------------------------------------------------------------------------
# Dependency probes
# ---------------------------------------------------------------------------

def _dep_pod(name, namespace, labels, ready=True):
    return SimpleNamespace(
        metadata=SimpleNamespace(name=name, namespace=namespace, labels=labels,
                                 creation_timestamp=None),
        spec=SimpleNamespace(node_name="cp1"),
        status=SimpleNamespace(
            phase="Running",
            container_statuses=[
                SimpleNamespace(ready=ready, restart_count=0, image="postgres:14")
            ],
        ),
    )


class _PodCore:
    """Stand-in for CoreV1Api's labelled pod list, keyed by selector."""

    def __init__(self, by_selector):
        self.by_selector = by_selector
        self.queried = []

    def list_pod_for_all_namespaces(self, label_selector=None, **_kwargs):
        self.queried.append(label_selector)
        return SimpleNamespace(items=self.by_selector.get(label_selector, []))


class TestDependencies:
    def test_nicos_postgres_is_the_spilo_cluster_not_the_standalone_one(self):
        """A vanilla site runs both. `nico-system.nico.nico-pg-cluster.credentials`
        is what nico-api's DATASTORE_* reads, so the spilo cluster is NICo's —
        the previous `app=postgres` probe reported the unrelated one."""
        core = _PodCore({
            "application=spilo": [
                _dep_pod("nico-pg-cluster-0", "postgres",
                         {"application": "spilo", "cluster-name": "nico-pg-cluster",
                          "spilo-role": "master"}),
            ],
            "app=postgres": [_dep_pod("postgres-0", "postgres", {"app": "postgres"})],
        })
        pg = next(d for d in _dependencies(core) if d["name"] == "postgres")
        assert [p["name"] for p in pg["pods"]] == ["nico-pg-cluster-0"]
        assert pg["selector"] == "application=spilo"
        assert pg["pods"][0]["labels"]["spilo-role"] == "master"

    def test_the_standalone_postgres_is_still_the_fallback(self):
        """An install with no operator has only the plain StatefulSet."""
        core = _PodCore({
            "app=postgres": [_dep_pod("postgres-0", "postgres", {"app": "postgres"})],
        })
        pg = next(d for d in _dependencies(core) if d["name"] == "postgres")
        assert [p["name"] for p in pg["pods"]] == ["postgres-0"]
        assert pg["selector"] == "app=postgres"

    def test_vault_is_found_by_its_helm_label(self):
        """`app=vault` matched nothing, so a Vault with an unready member
        reported as a healthy dependency with zero pods."""
        core = _PodCore({
            "app.kubernetes.io/name=vault": [
                _dep_pod("vault-0", "vault",
                         {"app.kubernetes.io/name": "vault", "vault-active": "true",
                          "vault-sealed": "false", "vault-version": "1.14.0"}),
                _dep_pod("vault-2", "vault",
                         {"app.kubernetes.io/name": "vault", "vault-sealed": "true"},
                         ready=False),
            ],
        })
        vault = next(d for d in _dependencies(core) if d["name"] == "vault")
        assert [p["name"] for p in vault["pods"]] == ["vault-0", "vault-2"]
        assert vault["selector"] == "app.kubernetes.io/name=vault"

    def test_vaults_seal_state_is_surfaced_because_readiness_hides_it(self):
        """A sealed Vault can be Running and Ready and still hand NICo nothing."""
        core = _PodCore({
            "app.kubernetes.io/name=vault": [
                _dep_pod("vault-0", "vault",
                         {"app.kubernetes.io/name": "vault", "vault-sealed": "true",
                          "vault-initialized": "true"}),
            ],
        })
        vault = next(d for d in _dependencies(core) if d["name"] == "vault")
        assert vault["pods"][0]["labels"] == {
            "vault-initialized": "true", "vault-sealed": "true"
        }

    def test_a_dependency_that_is_absent_reports_no_selector(self):
        """Distinguishes "looked and found nothing" from "matched by fallback"."""
        dep = next(d for d in _dependencies(_PodCore({})) if d["name"] == "vault")
        assert dep["pods"] == []
        assert dep["selector"] is None

    def test_the_same_labels_in_another_namespace_are_somebody_elses(self):
        core = _PodCore({
            "application=spilo": [
                _dep_pod("nico-pg-cluster-0", "postgres", {"application": "spilo"}),
                _dep_pod("other-pg-0", "someone-else", {"application": "spilo"}),
            ],
        })
        pg = next(d for d in _dependencies(core) if d["name"] == "postgres")
        assert [p["name"] for p in pg["pods"]] == ["nico-pg-cluster-0"]

    def test_temporal_is_probed_too(self):
        core = _PodCore({
            "app.kubernetes.io/name=temporal": [
                _dep_pod("temporal-frontend-abc", "temporal",
                         {"app.kubernetes.io/name": "temporal",
                          "app.kubernetes.io/component": "frontend"}),
            ],
        })
        names = [d["name"] for d in _dependencies(core)]
        assert names == ["postgres", "vault", "temporal"]
        temporal = next(d for d in _dependencies(core) if d["name"] == "temporal")
        assert temporal["pods"][0]["labels"] == {"app.kubernetes.io/component": "frontend"}


class TestCapabilities:
    """Absent, forbidden and empty are three different answers."""

    def _inventory(self, **kwargs):
        return _fetch_inventory(FakeForge({}, **kwargs))

    def test_a_build_without_the_lb_api_says_so_rather_than_reporting_zero(self):
        """Vanilla NICo has no LoadBalancerService RPCs at all — the family is
        an F5 extension. "0 load balancers" states something about the
        deployment that was never established."""
        inv = self._inventory(absent=("SearchLoadBalancerServices",
                                      "GetLoadBalancerServices"))
        assert inv["capabilities"]["loadBalancers"] == "absent"
        assert inv["loadBalancers"] == []

    def test_an_absent_lb_api_is_not_even_asked(self):
        """Asking a build that does not declare the method is a guaranteed
        miss, and over a tunnel it is a guaranteed slow one."""
        forge = FakeForge({}, absent=("SearchLoadBalancerServices",
                                      "GetLoadBalancerServices"))
        _fetch_inventory(forge)
        assert "SearchLoadBalancerServices" not in [m for m, _ in forge.calls]

    def test_a_refused_method_is_forbidden_not_empty(self):
        """Forge authorizes per method against the client cert, so GetAllDomains
        can be refused on a session that reads VPCs happily. The zones may well
        exist — we were not allowed to look."""
        inv = self._inventory(denied=("GetAllDomains",))
        assert inv["capabilities"]["domains"] == "forbidden"
        assert inv["domains"] == []

    def test_a_refusal_is_caught_however_late_the_call_is_made(self):
        """`forbidden` is only learnable by being refused, so the capability map
        cannot be settled before the calls that populate it — an earlier
        version reported every late-called section as available because nothing
        had asked it yet."""
        # These are issued last in the session, after the map is first built.
        inv = self._inventory(denied=("FindMachineIds", "GetDPFServiceVersions"))
        assert inv["capabilities"]["fleet"] == "forbidden"
        assert inv["capabilities"]["dpfServiceVersions"] == "forbidden"

    def test_a_section_that_answered_is_available_and_its_zero_is_real(self):
        inv = self._inventory()
        assert inv["capabilities"]["domains"] == "available"
        assert inv["capabilities"]["loadBalancers"] == "available"

    def test_absent_outranks_forbidden(self):
        """A method the build does not declare cannot have refused us."""
        inv = self._inventory(absent=("GetAllDomains",), denied=("GetAllDomains",))
        assert inv["capabilities"]["domains"] == "absent"

    def test_the_counts_carry_the_capabilities_to_the_ui(self):
        """The UI needs to know which zeros it is allowed to state."""
        from services.nico.health import inventory_counts

        counts = inventory_counts(self._inventory(absent=("SearchLoadBalancerServices",
                                                          "GetLoadBalancerServices")))
        assert counts["capabilities"]["loadBalancers"] == "absent"
        assert counts["loadBalancers"]["total"] == 0
