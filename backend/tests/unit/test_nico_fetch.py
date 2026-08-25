"""
Unit tests for services.nico.fetch — the pure shaping helpers.

The I/O halves (Kubernetes reads, Forge calls) are exercised through stand-ins:
a fake CoreV1Api for the endpoint resolution, and a fake ForgeClient that
replays canned RPC payloads. No live cluster, no gRPC.
"""

from types import SimpleNamespace
from unittest.mock import patch

from services.nico.fetch import (
    _fetch_inventory,
    _fetch_load_balancers,
    _lifecycle_state,
    _recent_errors,
    _roll_up_tenants,
    _service_endpoints,
)


class FakeForge:
    """Replays canned Forge responses, keyed by method name."""

    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def try_call(self, method, body=None):
        self.calls.append((method, body))
        value = self.responses.get(method, {})
        return value(body) if callable(value) else value


# ---------------------------------------------------------------------------
# Endpoint resolution
# ---------------------------------------------------------------------------

def _service(kind="NodePort", node_port=31079, ingress=()):
    return SimpleNamespace(
        spec=SimpleNamespace(
            type=kind,
            ports=[SimpleNamespace(port=1079, node_port=node_port)],
        ),
        status=SimpleNamespace(
            load_balancer=SimpleNamespace(
                ingress=[SimpleNamespace(ip=ip, hostname=None) for ip in ingress]
            )
        ),
    )


class _Core:
    def __init__(self, service):
        self._service = service

    def read_namespaced_service(self, **_kwargs):
        if isinstance(self._service, Exception):
            raise self._service
        return self._service


class TestServiceEndpoints:
    def test_a_nodeport_resolves_against_the_kube_api_host(self):
        """The NodePort is on the node, and the kubeconfig's server URL is the
        only address we know reaches it."""
        with patch("services.nico.fetch.tcp_reachable", return_value=True):
            out = _service_endpoints(
                _Core(_service()), "nico-system", "https://192.168.68.66:6443"
            )
        assert out["reachable"] is True
        assert out["grpc"] == "192.168.68.66:31079"
        assert out["kind"] == "nodeport"
        assert out["webUi"] == "https://192.168.68.66:31079/admin/"

    def test_a_loadbalancer_address_is_preferred_over_the_nodeport(self):
        with patch("services.nico.fetch.tcp_reachable", return_value=True):
            out = _service_endpoints(
                _Core(_service(kind="LoadBalancer", ingress=("10.1.1.5",))),
                "nico-system",
                "https://192.168.68.66:6443",
            )
        assert out["grpc"] == "10.1.1.5:1079"
        assert out["kind"] == "loadbalancer"

    def test_an_unroutable_candidate_is_reported_not_claimed(self):
        """A Service can advertise an address on a subnet with no route to it —
        that resolves and prints fine and then answers nothing."""
        with patch("services.nico.fetch.tcp_reachable", return_value=False):
            out = _service_endpoints(
                _Core(_service()), "nico-system", "https://192.168.68.66:6443"
            )
        assert out["reachable"] is False
        assert out["grpc"] == "192.168.68.66:31079"
        assert "not routable" in out["detail"]

    def test_clusterip_only_has_no_candidate_at_all(self):
        out = _service_endpoints(
            _Core(_service(kind="ClusterIP", node_port=None)),
            "nico-system",
            "https://192.168.68.66:6443",
        )
        assert out["reachable"] is False
        assert out["candidates"] == []
        assert "NodePort" in out["detail"]

    def test_an_unreadable_service_is_a_soft_failure(self):
        out = _service_endpoints(
            _Core(RuntimeError("forbidden")), "nico-system", "https://host:6443"
        )
        assert out["reachable"] is False
        assert "not readable" in out["detail"]


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
