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
from datetime import UTC, datetime, timedelta
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
    started_ago=None,
    owner=("DaemonSet", "f5-tmm"),
):
    """Enough of a V1Pod for the code under test.

    ``containers`` may name the exporter too — that is a *permanent* sidecar,
    which is what the cluster builders install and what every DPF cluster runs.
    ``started_ago`` gives it a running container status that many seconds old,
    which is what bounds "settling". ``owner`` is the controller reference every
    pod under a workload carries; None makes it a bare pod, which has none.
    """

    def ec(cname):
        env = (
            [SimpleNamespace(name="TMSTAT_REMOTE_WRITE_URL", value=pushing_to)]
            if cname == inject_svc.SIDECAR_NAME and pushing_to
            else []
        )
        return SimpleNamespace(name=cname, env=env)

    statuses = []
    if started_ago is not None:
        statuses.append(
            SimpleNamespace(
                name=inject_svc.SIDECAR_NAME,
                state=SimpleNamespace(
                    running=SimpleNamespace(
                        started_at=datetime.now(UTC) - timedelta(seconds=started_ago)
                    )
                ),
            )
        )

    return SimpleNamespace(
        metadata=SimpleNamespace(
            name=name,
            namespace=namespace,
            annotations=annotations or {},
            owner_references=(
                [SimpleNamespace(kind=owner[0], name=owner[1], controller=True)]
                if owner
                else None
            ),
        ),
        spec=SimpleNamespace(
            containers=[ec(c) for c in containers],
            ephemeral_containers=[ec(c) for c in ephemeral] or None,
            init_containers=None,
            volumes=[SimpleNamespace(name=v) for v in volumes],
            node_name=node_name,
        ),
        status=SimpleNamespace(
            container_statuses=statuses, ephemeral_container_statuses=[]
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
        # The one bnkscope builds and publishes, not the one from the archived
        # repository it was forked out of.
        assert spec["image"].startswith("ghcr.io/mwiget/bnkscope-tmm-stat-exporter")

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


class TestPermanentSidecar:
    """The exporter that is part of the pod template.

    ``_pushing_to`` read only ``ephemeral_containers``, so every permanently
    injected cluster — which is all of DPF, where the exporter rides the
    DaemonSet's pod template — reported no push target at all. It could never be
    judged stale, and it was invisible in every way except a name in a container
    list.
    """

    def test_its_push_url_is_readable(self):
        pod = make_pod(containers=("f5-tmm", inject_svc.SIDECAR_NAME))
        assert inject_svc._pushing_to(pod) == "http://172.18.0.1:9491/api/v1/write"
        assert inject_svc._exporter_kind(pod) == inject_svc.KIND_PERMANENT

    def test_an_ephemeral_one_still_reads(self):
        pod = make_pod(ephemeral=(inject_svc.SIDECAR_NAME,))
        assert inject_svc._pushing_to(pod) == "http://172.18.0.1:9491/api/v1/write"
        assert inject_svc._exporter_kind(pod) == inject_svc.KIND_EPHEMERAL

    def test_carrying_both_reports_the_durable_one(self):
        # Injected over a cluster that already had the sidecar. The permanent
        # one is the fact that outlives the pod.
        pod = make_pod(
            containers=("f5-tmm", inject_svc.SIDECAR_NAME),
            ephemeral=(inject_svc.SIDECAR_NAME,),
        )
        assert inject_svc._exporter_kind(pod) == inject_svc.KIND_PERMANENT

    def test_no_exporter_reads_as_nothing(self):
        pod = make_pod()
        assert inject_svc._pushing_to(pod) is None
        assert inject_svc._exporter_kind(pod) is None

    def test_started_at_comes_from_the_container_status(self):
        pod = make_pod(containers=("f5-tmm", inject_svc.SIDECAR_NAME), started_ago=120)
        started = inject_svc._exporter_started_at(pod)
        assert 119 <= (datetime.now(UTC) - started).total_seconds() <= 130


class TestVerdict:
    """Why nothing is arriving, not just that nothing is.

    "Injected but not streaming" was one state, rendered as "waiting for the
    first metrics — this takes a few seconds", forever. It is at least four
    states, and only one of them is fixed by re-installing the exporter, so the
    ordering below is what decides whether an operator is sent to the right
    repair or the wrong one.
    """

    @staticmethod
    def _entry(**kwargs):
        base = {
            "pod": "f5-tmm-1",
            "namespace": "ns",
            "injected": True,
            "kind": inject_svc.KIND_PERMANENT,
            "pushing_to": "http://192.168.68.113:9491/api/v1/write",
            "stale": False,
            "started_at": None,
            "running_for": 600.0,
            "streaming": False,
            "last_push_error": None,
            "log_unavailable": None,
            "node": "node-1",
            # The common case, and the one that must not be inferred from
            # absence: a node nobody asked about is not a node that is down.
            "node_ready": True,
        }
        base.update(kwargs)
        return base

    def _verdict(self, entries, *, cluster_streaming=False, streaming_known=True):
        injected = [e for e in entries if e["injected"]]
        stale = [e for e in entries if e["stale"]]
        silent = [e for e in injected if not e["streaming"]] if streaming_known else []
        oldest = max(
            (e["running_for"] for e in silent if e["running_for"] is not None),
            default=None,
        )
        return inject_svc._verdict(
            entries=entries,
            injected=injected,
            stale=stale,
            silent=silent,
            oldest_silent=oldest,
            cluster_streaming=cluster_streaming,
            streaming_known=streaming_known,
            not_ready=[e for e in entries if e["node_ready"] is False],
        )

    def test_no_tmm_pods_at_all(self):
        assert self._verdict([])[0] == inject_svc.VERDICT_NO_TMM

    def test_pods_without_the_exporter(self):
        entries = [self._entry(injected=False, kind=None)]
        assert self._verdict(entries)[0] == inject_svc.VERDICT_NOT_INSTALLED

    def test_delivering(self):
        entries = [self._entry(streaming=True)]
        assert self._verdict(entries)[0] == inject_svc.VERDICT_STREAMING

    def test_freshly_started_is_settling_not_broken(self):
        entries = [self._entry(running_for=10.0)]
        assert self._verdict(entries)[0] == inject_svc.VERDICT_SETTLING

    def test_running_past_the_settle_window_is_a_fault(self):
        """The whole point. Ten minutes in, "a few seconds" is a lie."""
        entries = [self._entry(running_for=inject_svc.SETTLE_SECONDS + 1)]
        verdict, detail = self._verdict(entries)
        assert verdict == inject_svc.VERDICT_NOT_DELIVERING
        # And says so, rather than sending the operator round the loop again.
        assert "re-installing will not change anything" in detail

    def test_a_moved_target_outranks_a_settle_window_that_has_not_elapsed(self):
        # The only verdict re-installing actually fixes, so it must win.
        entries = [self._entry(stale=True, running_for=5.0)]
        assert self._verdict(entries)[0] == inject_svc.VERDICT_STALE_TARGET

    def test_one_silent_pod_among_streaming_siblings(self):
        """A reinstalled node. The cluster keeps streaming from the others, so
        a cluster-level answer reports everything as fine while one node
        delivers nothing — and the dashboard is simply missing a line."""
        entries = [
            self._entry(pod="f5-tmm-1", streaming=True),
            self._entry(pod="f5-tmm-2", streaming=False, running_for=600.0),
        ]
        verdict, _ = self._verdict(entries, cluster_streaming=True)
        assert verdict == inject_svc.VERDICT_PARTIAL_DELIVERY

    def test_the_oldest_silent_exporter_decides_not_the_newest(self):
        # One pod injected seconds ago does not excuse a sibling that has been
        # failing for an hour — and that sibling is the reason for asking.
        entries = [
            self._entry(pod="f5-tmm-1", running_for=5.0),
            self._entry(pod="f5-tmm-2", running_for=3600.0),
        ]
        assert self._verdict(entries)[0] == inject_svc.VERDICT_NOT_DELIVERING

    def test_a_not_ready_node_outranks_not_delivering(self):
        """Observed on 2026-08-27: the machine hosting both DPUs was switched
        off. Both exporters kept reporting Running — the control plane cannot
        know a container died, only that the kubelet went quiet — so the page
        said "the pod cannot reach it", which sends an operator to hunt a
        network path when the answer is that the node is gone."""
        entries = [
            self._entry(pod="f5-tmm-1", node="dpu-node-a", node_ready=False),
            self._entry(pod="f5-tmm-2", node="dpu-node-a", node_ready=False),
        ]
        verdict, detail = self._verdict(entries)
        assert verdict == inject_svc.VERDICT_NODE_NOT_READY
        assert "dpu-node-a" in detail
        assert "NotReady" in detail

    def test_one_silent_pod_on_a_healthy_node_still_reports_delivery(self):
        """`all`, not `any`. A genuine delivery fault on a working node must
        not be buried under a sibling whose node happens to be down."""
        entries = [
            self._entry(pod="f5-tmm-1", node="dpu-node-a", node_ready=False),
            self._entry(pod="f5-tmm-2", node="dpu-node-b", node_ready=True),
        ]
        assert self._verdict(entries)[0] == inject_svc.VERDICT_NOT_DELIVERING

    def test_delivering_from_a_not_ready_node_is_not_a_complaint(self):
        """Readiness lags reality in both directions. Metrics arriving is the
        stronger evidence, so it wins."""
        entries = [self._entry(streaming=True, node_ready=False)]
        assert self._verdict(entries)[0] == inject_svc.VERDICT_STREAMING

    def test_unknown_readiness_is_not_a_fault(self):
        """Nodes could not be listed. Absence of an answer must not become an
        accusation — fall through to the delivery verdicts."""
        entries = [self._entry(node_ready=None)]
        assert self._verdict(entries)[0] == inject_svc.VERDICT_NOT_DELIVERING

    def test_no_prometheus_claims_nothing(self):
        # With no collector to ask, a working exporter and a broken one look
        # identical. "Not delivering" there would be a guess.
        entries = [self._entry(running_for=9999.0)]
        verdict, _ = self._verdict(entries, streaming_known=False)
        assert verdict == inject_svc.VERDICT_SETTLING


class TestDeliveryState:
    """get_injection_state, with Prometheus's per-pod answer folded in."""

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

    def test_a_permanent_sidecar_at_the_right_port_is_not_stale_but_is_broken(
        self, patched, monkeypatch
    ):
        # The live case: installed, running, correct address, nothing arriving.
        pod = make_pod(containers=("f5-tmm", inject_svc.SIDECAR_NAME), started_ago=600)
        self._targets(monkeypatch, pod)
        patched.read_namespaced_pod.return_value = pod

        state = inject_svc.get_injection_state(
            MagicMock(), expected_port=9491, streaming_pods=set()
        )

        assert state["injected_pods"] == 1
        assert state["permanent_pods"] == 1
        assert state["pods"][0]["pushing_to"] == "http://172.18.0.1:9491/api/v1/write"
        assert state["stale"] is False
        assert state["verdict"] == inject_svc.VERDICT_NOT_DELIVERING

    def test_reads_the_exporter_log_when_something_is_wrong(self, patched, monkeypatch):
        # Every symptom of this lives inside the pod, and the exporter logs the
        # reason on every failed push. That line is worth more than anything
        # bnkscope can infer from outside.
        pod = make_pod(containers=("f5-tmm", inject_svc.SIDECAR_NAME), started_ago=600)
        self._targets(monkeypatch, pod)
        patched.read_namespaced_pod.return_value = pod
        patched.read_namespaced_pod_log.return_value = (
            "2026/08/26 08:32:40 remote_write: Post \"http://h:9491/api/v1/write\": "
            "dial tcp: connect: connection refused\n"
        )

        state = inject_svc.get_injection_state(
            MagicMock(), expected_port=9491, streaming_pods=set()
        )

        assert "connection refused" in state["pods"][0]["last_push_error"]

    def test_a_working_exporter_costs_no_log_request(self, patched, monkeypatch):
        pod = make_pod(containers=("f5-tmm", inject_svc.SIDECAR_NAME), started_ago=600)
        self._targets(monkeypatch, pod)
        patched.read_namespaced_pod.return_value = pod

        state = inject_svc.get_injection_state(
            MagicMock(),
            expected_port=9491,
            streaming_pods={pod.metadata.name},
            cluster_streaming=True,
        )

        assert state["verdict"] == inject_svc.VERDICT_STREAMING
        patched.read_namespaced_pod_log.assert_not_called()

    def test_counts_delivery_per_pod(self, patched, monkeypatch):
        pods = [
            make_pod(
                name=f"f5-tmm-{i}",
                containers=("f5-tmm", inject_svc.SIDECAR_NAME),
                started_ago=600,
            )
            for i in (1, 2)
        ]
        self._targets(monkeypatch, *pods)
        patched.read_namespaced_pod.side_effect = lambda name, namespace: next(
            p for p in pods if p.metadata.name == name
        )

        state = inject_svc.get_injection_state(
            MagicMock(),
            expected_port=9491,
            streaming_pods={"f5-tmm-1"},
            cluster_streaming=True,
        )

        assert (state["streaming_pods"], state["silent_pods"]) == (1, 1)
        assert state["verdict"] == inject_svc.VERDICT_PARTIAL_DELIVERY


class TestApiErrorDetail:
    """What bnkscope says when it cannot read the exporter's log.

    Live on 2026-08-27, against a cluster whose DPU host was powered off: the
    reason phrase was "Internal Server Error", while the body carried
    `dial tcp 192.168.68.71:10250: connect: no route to host` — the actual
    answer, and the only one that names the node.
    """

    def test_prefers_the_body_message_over_the_reason_phrase(self):
        exc = ApiException(status=500, reason="Internal Server Error")
        exc.body = json.dumps(
            {
                "kind": "Status",
                "message": (
                    'Get "https://192.168.68.71:10250/containerLogs/ns/pod/c": '
                    "dial tcp 192.168.68.71:10250: connect: no route to host"
                ),
            }
        )
        detail = inject_svc._api_error_detail(exc)
        assert "no route to host" in detail
        assert detail != "Internal Server Error"

    def test_falls_back_to_the_reason_when_there_is_no_body(self):
        exc = ApiException(status=403, reason="Forbidden")
        exc.body = None
        assert inject_svc._api_error_detail(exc) == "Forbidden"

    def test_a_body_that_is_not_json_is_not_an_error(self):
        exc = ApiException(status=500, reason="Internal Server Error")
        exc.body = "<html>gateway timeout</html>"
        assert inject_svc._api_error_detail(exc) == "Internal Server Error"


class TestRemovePermanent:
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

    def test_refuses_to_recreate_pods_for_a_sidecar_in_the_template(
        self, patched, monkeypatch
    ):
        """Recreating the pod drops dataplane traffic and the exporter comes
        back with the replacement — all cost, no effect."""
        pod = make_pod(containers=("f5-tmm", inject_svc.SIDECAR_NAME))
        self._targets(monkeypatch, pod)
        patched.read_namespaced_pod.return_value = pod

        result = inject_svc.remove(MagicMock())

        patched.delete_namespaced_pod.assert_not_called()
        assert result["deleted"] == []
        error = result["failed"][0]["error"]
        assert "permanent sidecar" in error
        # "Remove it where it is defined" is not an instruction unless it says
        # where. It used to say `tmmscope eject`, which only undoes `tmmscope
        # inject --permanent` — not the sidecar a cluster builder shipped.
        assert "DaemonSet f5-tmm" in error
        assert "tmmscope" not in error

    def test_names_the_deployment_rather_than_its_generated_replicaset(
        self, patched, monkeypatch
    ):
        """Nobody edits a ReplicaSet: it is generated, and the next rollout
        replaces it. The Deployment above it is the thing to open."""
        pod = make_pod(
            containers=("f5-tmm", inject_svc.SIDECAR_NAME),
            owner=("ReplicaSet", "f5-tmm-7d9f"),
        )
        self._targets(monkeypatch, pod)
        patched.read_namespaced_pod.return_value = pod

        apps = MagicMock()
        apps.read_namespaced_replica_set.return_value = SimpleNamespace(
            metadata=SimpleNamespace(
                owner_references=[
                    SimpleNamespace(kind="Deployment", name="f5-tmm", controller=True)
                ]
            )
        )
        monkeypatch.setattr(inject_svc.k8s_client, "AppsV1Api", lambda _c: apps)

        result = inject_svc.remove(MagicMock())

        assert "Deployment f5-tmm" in result["failed"][0]["error"]

    def test_still_recreates_for_an_ephemeral_one(self, patched, monkeypatch):
        pod = make_pod(ephemeral=(inject_svc.SIDECAR_NAME,))
        self._targets(monkeypatch, pod)
        patched.read_namespaced_pod.return_value = pod

        result = inject_svc.remove(MagicMock())

        patched.delete_namespaced_pod.assert_called_once()
        assert result["deleted"] == [pod.metadata.name]
