"""Ephemeral injection of the tmm-stat exporter.

The two things worth guarding here are the ones that are silent when wrong:

  - **The sidecar spec.** It is built by us rather than taken from a caller, so
    the security properties are ours to keep. A test that only checks the
    container is named right would pass on a root, privileged container.
  - **The remote-write URL.** A wrong host injects an exporter that pushes
    nowhere, which looks exactly like an exporter that was never injected — the
    worst kind of failure for a troubleshooting tool.
"""

import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from kubernetes.client.rest import ApiException

from services import tmmscope_inject_service as inject_svc

# ---------------------------------------------------------------------------
# Fakes — enough of a V1Pod for the code under test
# ---------------------------------------------------------------------------


def make_pod(
    name="f5-tmm-abc123",
    namespace="dpf-operator-system",
    containers=("f5-tmm", "debug"),
    ephemeral=(),
    volumes=("f5tmstat",),
    annotations=None,
    node_name="node-1",
    pushing_to="http://172.18.0.1:9491/api/v1/write",
):
    def ec(cname):
        env = (
            [SimpleNamespace(name="TMSTAT_REMOTE_WRITE_URL", value=pushing_to)]
            if cname == "tmm-stat-exporter" and pushing_to
            else []
        )
        return SimpleNamespace(name=cname, env=env)

    return SimpleNamespace(
        metadata=SimpleNamespace(name=name, namespace=namespace, annotations=annotations or {}),
        spec=SimpleNamespace(
            containers=[SimpleNamespace(name=c) for c in containers],
            ephemeral_containers=[ec(c) for c in ephemeral] or None,
            init_containers=None,
            volumes=[SimpleNamespace(name=v) for v in volumes],
            node_name=node_name,
        ),
    )


def api_exception(status=403, reason="Forbidden"):
    exc = ApiException(status=status, reason=reason)
    return exc


class TestSidecarSpec:
    def test_is_locked_down(self):
        spec = inject_svc.build_sidecar("infra", "http://10.0.0.1:9491/api/v1/write")
        sc = spec["securityContext"]

        # Each of these is load-bearing: the exporter reads a shared memory
        # segment and pushes outbound, so it needs none of what it drops.
        assert sc["runAsNonRoot"] is True
        assert sc["runAsUser"] == 65532
        assert sc["readOnlyRootFilesystem"] is True
        assert sc["allowPrivilegeEscalation"] is False
        assert sc["capabilities"] == {"drop": ["ALL"]}

    def test_pins_the_image(self):
        spec = inject_svc.build_sidecar("infra", "http://h/w")
        assert spec["image"] == inject_svc.EXPORTER_IMAGE
        assert spec["image"].startswith("ghcr.io/mwiget/tmm-stat-exporter")

    def test_mounts_tmstat_read_only(self):
        spec = inject_svc.build_sidecar("infra", "http://h/w")
        mounts = {m["name"]: m for m in spec["volumeMounts"]}
        assert mounts[inject_svc.TMSTAT_VOLUME]["readOnly"] is True
        assert mounts[inject_svc.TMSTAT_VOLUME]["mountPath"] == "/var/tmstat"

    def test_omits_the_dssm_cert_unless_asked(self):
        without = inject_svc.build_sidecar("infra", "http://h/w")
        assert all(m["name"] != inject_svc.DSSM_CERT_VOLUME for m in without["volumeMounts"])

        with_cert = inject_svc.build_sidecar("infra", "http://h/w", dssm_cert=True)
        assert any(m["name"] == inject_svc.DSSM_CERT_VOLUME for m in with_cert["volumeMounts"])

    def test_carries_the_cluster_label_and_push_url(self):
        spec = inject_svc.build_sidecar("dpu-cplane-tenant1", "http://10.0.0.1:9491/api/v1/write")
        env = {e["name"]: e.get("value") for e in spec["env"]}

        assert env["TMSTAT_REMOTE_WRITE_URL"] == "http://10.0.0.1:9491/api/v1/write"
        assert "cluster=dpu-cplane-tenant1" in env["TMSTAT_EXTERNAL_LABELS"]

    def test_declares_no_resources(self):
        # The ephemeralcontainers subresource rejects `resources` and `ports`
        # outright — including them makes every injection fail with 422.
        spec = inject_svc.build_sidecar("infra", "http://h/w")
        assert "resources" not in spec
        assert "ports" not in spec

    def test_declares_no_probes(self):
        # TMM hooks inbound TCP on its dataplane interfaces, so a kubelet probe
        # cannot reach the sidecar and would mark the whole tmm pod NotReady.
        spec = inject_svc.build_sidecar("infra", "http://h/w")
        assert "readinessProbe" not in spec
        assert "livenessProbe" not in spec


class TestRemoteWriteDerivation:
    def test_prefers_a_multus_edge_interface(self):
        pod = make_pod(
            annotations={
                "k8s.v1.cni.cncf.io/network-status": json.dumps(
                    [
                        {"interface": "eth0", "default": True, "ips": ["10.244.1.5"]},
                        {"interface": "net1", "ips": ["192.168.60.7"]},
                    ]
                )
            }
        )
        host, how = inject_svc.derive_remote_write_host(MagicMock(), pod)

        # The .1 of the *edge* subnet, not the default pod network.
        assert host == "192.168.60.1"
        assert "multus" in how

    def test_falls_back_to_the_node_gateway(self):
        core = MagicMock()
        core.read_node.return_value = SimpleNamespace(
            status=SimpleNamespace(
                addresses=[
                    SimpleNamespace(type="Hostname", address="node-1"),
                    SimpleNamespace(type="InternalIP", address="172.18.0.4"),
                ]
            )
        )
        host, how = inject_svc.derive_remote_write_host(core, make_pod())

        assert host == "172.18.0.1"
        assert "node-1" in how

    def test_says_why_when_it_cannot(self):
        core = MagicMock()
        core.read_node.side_effect = api_exception(404, "Not Found")
        host, how = inject_svc.derive_remote_write_host(core, make_pod())

        # Not an exception and not a plausible-looking guess — a reason.
        assert host is None
        assert how

    def test_survives_a_malformed_annotation(self):
        core = MagicMock()
        core.read_node.return_value = SimpleNamespace(
            status=SimpleNamespace(
                addresses=[SimpleNamespace(type="InternalIP", address="172.18.0.4")]
            )
        )
        pod = make_pod(annotations={"k8s.v1.cni.cncf.io/network-status": "not json"})

        host, _ = inject_svc.derive_remote_write_host(core, pod)
        assert host == "172.18.0.1"

    @pytest.mark.parametrize("bad", ["", "10.0.0", "not.an.ip.here", "::1"])
    def test_rejects_addresses_it_cannot_parse(self, bad):
        assert inject_svc._gateway_of(bad) is None


class TestInject:
    @pytest.fixture()
    def patched(self, monkeypatch):
        core = MagicMock()
        monkeypatch.setattr(inject_svc.k8s_client, "CoreV1Api", lambda _c: core)
        return core

    def _targets(self, monkeypatch, *pods):
        monkeypatch.setattr(
            inject_svc,
            "find_tmm_pods",
            lambda _c: [
                {"name": p.metadata.name, "namespace": p.metadata.namespace, "phase": "Running"}
                for p in pods
            ],
        )

    def test_refuses_when_there_are_no_tmm_pods(self, patched, monkeypatch):
        self._targets(monkeypatch)
        with pytest.raises(ValueError, match="No running f5-tmm pods"):
            inject_svc.inject(MagicMock(), "infra")

    def test_patches_the_ephemeralcontainers_subresource(self, patched, monkeypatch):
        pod = make_pod()
        self._targets(monkeypatch, pod)
        patched.read_namespaced_pod.return_value = pod

        result = inject_svc.inject(
            MagicMock(), "infra", remote_write_url="http://10.0.0.1:9491/api/v1/write"
        )

        assert result["added"] == [pod.metadata.name]
        call = patched.patch_namespaced_pod_ephemeralcontainers.call_args
        body = call.kwargs["body"]
        assert list(body["spec"].keys()) == ["ephemeralContainers"]
        assert body["spec"]["ephemeralContainers"][0]["name"] == inject_svc.SIDECAR_NAME

    def test_is_idempotent(self, patched, monkeypatch):
        # Already carrying the exporter — inject again and it must not be added
        # twice, which would fail the patch and look like a broken cluster.
        pod = make_pod(ephemeral=("tmm-stat-exporter",))
        self._targets(monkeypatch, pod)
        patched.read_namespaced_pod.return_value = pod

        result = inject_svc.inject(MagicMock(), "infra", remote_write_url="http://h/w")

        assert result["skipped"] == [pod.metadata.name]
        assert result["added"] == []
        patched.patch_namespaced_pod_ephemeralcontainers.assert_not_called()

    def test_mounts_the_dssm_cert_when_the_pod_has_it(self, patched, monkeypatch):
        pod = make_pod(volumes=("f5tmstat", inject_svc.DSSM_CERT_VOLUME))
        self._targets(monkeypatch, pod)
        patched.read_namespaced_pod.return_value = pod

        inject_svc.inject(MagicMock(), "infra", remote_write_url="http://h/w")

        spec = patched.patch_namespaced_pod_ephemeralcontainers.call_args.kwargs["body"][
            "spec"
        ]["ephemeralContainers"][0]
        assert any(m["name"] == inject_svc.DSSM_CERT_VOLUME for m in spec["volumeMounts"])

    def test_builds_the_url_from_the_discovered_port_and_path(self, patched, monkeypatch):
        pod = make_pod()
        self._targets(monkeypatch, pod)
        patched.read_namespaced_pod.return_value = pod
        patched.read_node.return_value = SimpleNamespace(
            status=SimpleNamespace(
                addresses=[SimpleNamespace(type="InternalIP", address="172.18.0.4")]
            )
        )

        result = inject_svc.inject(
            MagicMock(), "infra", prometheus_port=9491, remote_write_path="/api/v1/write"
        )

        # 9491, not 9090 — tmmscope's Prometheus moves when its port is taken,
        # which is the entire reason the discovery file exists.
        assert result["remote_write_url"] == "http://172.18.0.1:9491/api/v1/write"

    def test_reports_a_pod_that_failed_without_abandoning_the_rest(
        self, patched, monkeypatch
    ):
        good, bad = make_pod(name="f5-tmm-good"), make_pod(name="f5-tmm-bad")
        self._targets(monkeypatch, bad, good)
        patched.read_namespaced_pod.side_effect = lambda name, namespace: (
            bad if name == "f5-tmm-bad" else good
        )
        patched.patch_namespaced_pod_ephemeralcontainers.side_effect = [
            api_exception(403, "Forbidden"),
            None,
        ]

        result = inject_svc.inject(MagicMock(), "infra", remote_write_url="http://h/w")

        assert result["added"] == ["f5-tmm-good"]
        assert [f["pod"] for f in result["failed"]] == ["f5-tmm-bad"]

    def test_refuses_rather_than_pushing_nowhere(self, patched, monkeypatch):
        pod = make_pod(node_name=None)
        self._targets(monkeypatch, pod)
        patched.read_namespaced_pod.return_value = pod

        # No URL given and none derivable: injecting anyway would produce an
        # exporter that silently pushes into the void.
        with pytest.raises(ValueError, match="reaches your Prometheus"):
            inject_svc.inject(MagicMock(), "infra")


class TestRemove:
    @pytest.fixture()
    def patched(self, monkeypatch):
        core = MagicMock()
        monkeypatch.setattr(inject_svc.k8s_client, "CoreV1Api", lambda _c: core)
        return core

    def _targets(self, monkeypatch, *pods):
        monkeypatch.setattr(
            inject_svc,
            "find_tmm_pods",
            lambda _c: [
                {"name": p.metadata.name, "namespace": p.metadata.namespace, "phase": "Running"}
                for p in pods
            ],
        )

    def test_deletes_only_the_pods_carrying_it(self, patched, monkeypatch):
        carrying = make_pod(name="f5-tmm-1", ephemeral=("tmm-stat-exporter",))
        clean = make_pod(name="f5-tmm-2")
        self._targets(monkeypatch, carrying, clean)
        patched.read_namespaced_pod.side_effect = lambda name, namespace: (
            carrying if name == "f5-tmm-1" else clean
        )

        result = inject_svc.remove(MagicMock())

        # Restarting a clean pod would drop traffic for no reason at all.
        assert result["deleted"] == ["f5-tmm-1"]
        assert patched.delete_namespaced_pod.call_count == 1

    def test_restarts_nothing_when_nothing_is_injected(self, patched, monkeypatch):
        self._targets(monkeypatch, make_pod())
        patched.read_namespaced_pod.return_value = make_pod()

        result = inject_svc.remove(MagicMock())

        assert result["deleted"] == []
        patched.delete_namespaced_pod.assert_not_called()


class TestInjectionState:
    @pytest.fixture()
    def patched(self, monkeypatch):
        core = MagicMock()
        monkeypatch.setattr(inject_svc.k8s_client, "CoreV1Api", lambda _c: core)
        return core

    def _targets(self, monkeypatch, *pods):
        monkeypatch.setattr(
            inject_svc,
            "find_tmm_pods",
            lambda _c: [
                {"name": p.metadata.name, "namespace": p.metadata.namespace, "phase": "Running"}
                for p in pods
            ],
        )

    def test_reports_partial_injection(self, patched, monkeypatch):
        # The state a pod restart leaves behind: one sibling clean, one not.
        one = make_pod(name="f5-tmm-1", ephemeral=("tmm-stat-exporter",))
        two = make_pod(name="f5-tmm-2")
        self._targets(monkeypatch, one, two)
        patched.read_namespaced_pod.side_effect = lambda name, namespace: (
            one if name == "f5-tmm-1" else two
        )

        state = inject_svc.get_injection_state(MagicMock())

        assert state["injected"] is False
        assert state["partial"] is True
        assert (state["injected_pods"], state["tmm_pods"]) == (1, 2)

    def test_injected_means_every_pod(self, patched, monkeypatch):
        pods = [make_pod(name=f"f5-tmm-{i}", ephemeral=("tmm-stat-exporter",)) for i in (1, 2)]
        self._targets(monkeypatch, *pods)
        patched.read_namespaced_pod.side_effect = lambda name, namespace: next(
            p for p in pods if p.metadata.name == name
        )

        state = inject_svc.get_injection_state(MagicMock())

        assert state["injected"] is True
        assert state["partial"] is False

    def test_no_tmm_pods_is_not_injected(self, patched, monkeypatch):
        self._targets(monkeypatch)
        state = inject_svc.get_injection_state(MagicMock())

        assert state["injected"] is False
        assert state["partial"] is False
        assert state["tmm_pods"] == 0


class TestStaleInjection:
    """An exporter left pushing at a Prometheus port that has moved.

    This is the failure that produced the report "many graphs say no data": the
    exporters were injected while Prometheus was on 9492, the port later moved
    back to 9491, and every one of them kept running and kept pushing into a
    closed socket. Nothing in the UI could tell that apart from never having
    injected — which is exactly why it has to be detected and named.

    The port is baked into an ephemeral container's env and cannot be edited, so
    the only repair is recreating the pods. The cure for the *cause* is in the
    CLI: bnkscope's Prometheus port no longer auto-reverts.
    """

    @pytest.fixture()
    def patched(self, monkeypatch):
        core = MagicMock()
        monkeypatch.setattr(inject_svc.k8s_client, "CoreV1Api", lambda _c: core)
        return core

    def _targets(self, monkeypatch, *pods):
        monkeypatch.setattr(
            inject_svc,
            "find_tmm_pods",
            lambda _c: [
                {"name": p.metadata.name, "namespace": p.metadata.namespace, "phase": "Running"}
                for p in pods
            ],
        )

    def test_flags_an_exporter_pushing_at_the_wrong_port(self, patched, monkeypatch):
        pod = make_pod(
            ephemeral=("tmm-stat-exporter",),
            pushing_to="http://192.168.99.1:9492/api/v1/write",
        )
        self._targets(monkeypatch, pod)
        patched.read_namespaced_pod.return_value = pod

        state = inject_svc.get_injection_state(MagicMock(), expected_port=9491)

        assert state["stale"] is True
        assert state["stale_pods"] == 1
        assert state["stale_target"] == "http://192.168.99.1:9492/api/v1/write"
        # Still injected — the container is there and running. It just cannot
        # reach anything, and saying otherwise would hide the real problem.
        assert state["injected"] is True

    def test_matching_port_is_not_stale(self, patched, monkeypatch):
        pod = make_pod(
            ephemeral=("tmm-stat-exporter",),
            pushing_to="http://172.18.0.1:9491/api/v1/write",
        )
        self._targets(monkeypatch, pod)
        patched.read_namespaced_pod.return_value = pod

        state = inject_svc.get_injection_state(MagicMock(), expected_port=9491)

        assert state["stale"] is False
        assert state["stale_target"] is None

    def test_a_different_host_on_the_right_port_is_not_stale(self, patched, monkeypatch):
        # The host is derived per pod — multus gateway here, node gateway there.
        # Only the port says which Prometheus it was aimed at.
        pod = make_pod(
            ephemeral=("tmm-stat-exporter",),
            pushing_to="http://10.244.0.1:9491/api/v1/write",
        )
        self._targets(monkeypatch, pod)
        patched.read_namespaced_pod.return_value = pod

        assert inject_svc.get_injection_state(MagicMock(), expected_port=9491)["stale"] is False

    def test_claims_nothing_when_the_expected_port_is_unknown(self, patched, monkeypatch):
        # No telemetry stack running: we cannot say a port is wrong, so we don't.
        pod = make_pod(ephemeral=("tmm-stat-exporter",), pushing_to="http://h:9492/w")
        self._targets(monkeypatch, pod)
        patched.read_namespaced_pod.return_value = pod

        state = inject_svc.get_injection_state(MagicMock(), expected_port=None)

        assert state["stale"] is False
        assert state["expected_port"] is None

    def test_reports_where_each_pod_is_pushing(self, patched, monkeypatch):
        pod = make_pod(ephemeral=("tmm-stat-exporter",), pushing_to="http://h:9492/w")
        self._targets(monkeypatch, pod)
        patched.read_namespaced_pod.return_value = pod

        state = inject_svc.get_injection_state(MagicMock(), expected_port=9491)

        assert state["pods"][0]["pushing_to"] == "http://h:9492/w"
        assert state["pods"][0]["stale"] is True

    def test_an_uninjected_pod_is_never_stale(self, patched, monkeypatch):
        self._targets(monkeypatch, make_pod())
        patched.read_namespaced_pod.return_value = make_pod()

        state = inject_svc.get_injection_state(MagicMock(), expected_port=9491)

        assert state["stale"] is False
        assert state["pods"][0]["pushing_to"] is None
