"""Turning local kubeconfig contexts into registered clusters.

The probe is mocked here — it needs a live API server, and what these tests are
about is the decision made with the probe's answer: which contexts get
registered, which are reported and why, and that running twice does not produce
two rows. The kubeconfig parsing underneath has its own tests.
"""

from unittest.mock import patch

import pytest

from models import KubernetesCluster
from services.cluster_discovery_service import ClusterDiscoveryService
from services.kubeconfig_discovery import DiscoveredContext

_PROBE = "services.cluster_discovery_service.ClusterDiscoveryService._probe"
_CONTEXTS = "services.cluster_discovery_service.discover_contexts"


def _pod_list(entries, key="app", phase="Running"):
    """A fake list_pod_for_all_namespaces page from (app, namespace) pairs."""
    from unittest.mock import MagicMock

    page = MagicMock()
    page.items = []
    for app, namespace in entries:
        pod = MagicMock()
        pod.metadata.labels = {key: app}
        pod.metadata.namespace = namespace
        pod.status.phase = phase
        page.items.append(pod)
    return page


def _context(name="lab-a", **overrides):
    defaults = {
        "name": name,
        "api_server": "https://10.1.2.3:6443",
        "cloud_provider": "on-prem",
        "region": None,
        "namespace": "default",
        "auth_method": "token",
        "source_path": "/host/.kube/config",
        "kubeconfig": "apiVersion: v1\nkind: Config\n",
        "blockers": [],
    }
    return DiscoveredContext(**{**defaults, **overrides})


def _probe_result(reachable=True, has_bnk=False, has_dpf=False, has_nico=False,
                  version="1.29", namespaces=None, components=None, detail=None):
    return {
        "reachable": reachable,
        "has_bnk": has_bnk,
        "has_dpf": has_dpf,
        "has_nico": has_nico,
        "version": version,
        "namespaces": namespaces if namespaces is not None
        else (["dpf-operator-system"] if has_bnk else []),
        "components": components if components is not None
        else (["f5-tmm"] if has_bnk else []),
        "detail": detail,
    }


class TestRegistrationRule:
    """Probe everything; register what has BNK on it."""

    def test_a_context_with_bnk_is_registered(self, db):
        with patch(_CONTEXTS, return_value=[_context("bnk-lab")]), \
             patch(_PROBE, return_value=_probe_result(has_bnk=True)):
            result = ClusterDiscoveryService(db).run()

        assert result["registered"] == 1
        cluster = db.query(KubernetesCluster).filter_by(context="bnk-lab").one()
        assert cluster.status == "active"
        assert cluster.version == "1.29"
        assert cluster.discovered_namespaces == ["dpf-operator-system"]
        assert cluster.meta_data["bnk_components"] == ["f5-tmm"]

    def test_a_reachable_context_without_bnk_is_only_reported(self, db):
        """A laptop has a dozen contexts. bnkscope is for the BNK ones."""
        with patch(_CONTEXTS, return_value=[_context("someones-demo")]), \
             patch(_PROBE, return_value=_probe_result(has_bnk=False)):
            result = ClusterDiscoveryService(db).run()

        assert result["registered"] == 0
        assert db.query(KubernetesCluster).count() == 0

        candidate = result["candidates"][0]
        assert candidate["state"] == "reachable"
        assert candidate["registered"] is False
        assert "no BNK, DPF or NICo pods found" in candidate["detail"]

    def test_an_unreachable_context_is_reported_not_registered(self, db):
        with patch(_CONTEXTS, return_value=[_context("vpn-only")]), \
             patch(_PROBE, return_value=_probe_result(reachable=False, version=None,
                                                      detail="Timed out")):
            result = ClusterDiscoveryService(db).run()

        assert db.query(KubernetesCluster).count() == 0
        assert result["candidates"][0]["state"] == "unreachable"
        assert result["candidates"][0]["detail"] == "Timed out"

    def test_an_unusable_context_is_never_probed(self, db):
        """No point dialling a context whose credentials we cannot even assemble."""
        blocked = _context("minikube", blockers=["Cannot read `client-key: /gone`"])
        with patch(_CONTEXTS, return_value=[blocked]), patch(_PROBE) as probe:
            result = ClusterDiscoveryService(db).run()

        probe.assert_not_called()
        candidate = result["candidates"][0]
        assert candidate["state"] == "unusable"
        assert "/gone" in candidate["detail"]

    def test_a_dpf_only_cluster_is_registered_without_adopt_all(self, db):
        with patch(_CONTEXTS, return_value=[_context("infra")]), \
             patch(_PROBE, return_value=_probe_result(has_dpf=True,
                                                      components=["dpf-operator"],
                                                      namespaces=["dpf-operator-system"])):
            result = ClusterDiscoveryService(db).run()

        assert result["registered"] == 1
        cluster = db.query(KubernetesCluster).filter_by(context="infra").one()
        assert cluster.meta_data["has_dpf"] is True

    def test_adopt_all_registers_a_reachable_context_without_bnk(self, db):
        with patch(_CONTEXTS, return_value=[_context("fresh-cluster")]), \
             patch(_PROBE, return_value=_probe_result(has_bnk=False)):
            result = ClusterDiscoveryService(db).run(adopt_all=True)

        assert result["registered"] == 1
        assert db.query(KubernetesCluster).filter_by(context="fresh-cluster").count() == 1

    def test_adopt_all_still_will_not_register_an_unreachable_context(self, db):
        with patch(_CONTEXTS, return_value=[_context("gone")]), \
             patch(_PROBE, return_value=_probe_result(reachable=False)):
            result = ClusterDiscoveryService(db).run(adopt_all=True)

        assert result["registered"] == 0

    def test_mixed_sweep_counts(self, db):
        contexts = [_context("a"), _context("b"), _context("c")]
        probes = [
            _probe_result(has_bnk=True),
            _probe_result(has_bnk=False),
            _probe_result(reachable=False),
        ]
        with patch(_CONTEXTS, return_value=contexts), patch(_PROBE, side_effect=probes):
            result = ClusterDiscoveryService(db).run()

        assert result["found"] == 3
        assert result["registered"] == 1

    def test_no_contexts_is_not_an_error(self, db):
        with patch(_CONTEXTS, return_value=[]):
            assert ClusterDiscoveryService(db).run() == {
                "candidates": [],
                "registered": 0,
                "found": 0,
            }


class TestIdempotence:
    def test_running_twice_does_not_duplicate(self, db):
        with patch(_CONTEXTS, return_value=[_context("bnk-lab")]), \
             patch(_PROBE, return_value=_probe_result(has_bnk=True)):
            svc = ClusterDiscoveryService(db)
            svc.run()
            svc.run()

        assert db.query(KubernetesCluster).filter_by(context="bnk-lab").count() == 1

    def test_a_renamed_cluster_is_matched_by_context_not_name(self, db):
        """Renaming in the UI must not make the next sweep register a duplicate."""
        with patch(_CONTEXTS, return_value=[_context("bnk-lab")]), \
             patch(_PROBE, return_value=_probe_result(has_bnk=True)):
            svc = ClusterDiscoveryService(db)
            svc.run()

            cluster = db.query(KubernetesCluster).filter_by(context="bnk-lab").one()
            cluster.name = "Production (Frankfurt)"
            db.commit()

            svc.run()

        assert db.query(KubernetesCluster).count() == 1
        assert db.query(KubernetesCluster).one().name == "Production (Frankfurt)"

    def test_a_rotated_kubeconfig_is_picked_up(self, db):
        """The host's cert rotated; bnkscope must not keep using the stale one."""
        first = _context("bnk-lab", kubeconfig="apiVersion: v1\n# old\n")
        second = _context("bnk-lab", kubeconfig="apiVersion: v1\n# new\n")

        with patch(_CONTEXTS, return_value=[first]), \
             patch(_PROBE, return_value=_probe_result(has_bnk=True)):
            ClusterDiscoveryService(db).run()
        with patch(_CONTEXTS, return_value=[second]), \
             patch(_PROBE, return_value=_probe_result(has_bnk=True)):
            ClusterDiscoveryService(db).run()

        from core.encryption import decrypt_value

        cluster = db.query(KubernetesCluster).filter_by(context="bnk-lab").one()
        assert "# new" in decrypt_value(cluster.kubeconfig_encrypted)

    def test_a_known_cluster_that_went_unreachable_is_marked_not_deleted(self, db):
        """VPN down is not the same as cluster gone. Losing the row loses history."""
        with patch(_CONTEXTS, return_value=[_context("bnk-lab")]), \
             patch(_PROBE, return_value=_probe_result(has_bnk=True)):
            ClusterDiscoveryService(db).run()
        with patch(_CONTEXTS, return_value=[_context("bnk-lab")]), \
             patch(_PROBE, return_value=_probe_result(reachable=False, version=None)):
            result = ClusterDiscoveryService(db).run()

        cluster = db.query(KubernetesCluster).filter_by(context="bnk-lab").one()
        assert cluster.status == "unreachable"
        assert cluster.version == "1.29"  # last known, not wiped
        assert result["candidates"][0]["registered"] is True

    def test_a_name_collision_with_a_manual_cluster_is_suffixed(self, db):
        db.add(KubernetesCluster(name="bnk-lab", context="added-by-hand"))
        db.commit()

        with patch(_CONTEXTS, return_value=[_context("bnk-lab")]), \
             patch(_PROBE, return_value=_probe_result(has_bnk=True)):
            ClusterDiscoveryService(db).run()

        names = {c.name for c in db.query(KubernetesCluster).all()}
        assert names == {"bnk-lab", "bnk-lab-2"}


class TestStoredState:
    def test_meta_data_records_where_the_cluster_came_from(self, db):
        with patch(_CONTEXTS, return_value=[_context("bnk-lab", auth_method="exec:aws")]), \
             patch(_PROBE, return_value=_probe_result(has_bnk=True)):
            ClusterDiscoveryService(db).run()

        meta = db.query(KubernetesCluster).one().meta_data
        assert meta["discovered"] is True
        assert meta["kubeconfig_source"] == "/host/.kube/config"
        assert meta["auth_method"] == "exec:aws"

    def test_region_and_provider_are_stored(self, db):
        """The region is load-bearing: an EKS token is signed per-region."""
        eks = _context("eks-prod", cloud_provider="eks", region="eu-west-2")
        with patch(_CONTEXTS, return_value=[eks]), \
             patch(_PROBE, return_value=_probe_result(has_bnk=True)):
            ClusterDiscoveryService(db).run()

        cluster = db.query(KubernetesCluster).one()
        assert cluster.cloud_provider == "eks"
        assert cluster.region == "eu-west-2"

    def test_the_context_namespace_becomes_the_default_namespace(self, db):
        ctx = _context("bnk-lab", namespace="f5-bnk")
        with patch(_CONTEXTS, return_value=[ctx]), \
             patch(_PROBE, return_value=_probe_result(has_bnk=True)):
            ClusterDiscoveryService(db).run()

        assert db.query(KubernetesCluster).one().default_namespace == "f5-bnk"

    def test_last_synced_at_is_only_touched_when_the_probe_succeeded(self, db):
        """A failed sweep must not make a stale cluster look freshly seen."""
        with patch(_CONTEXTS, return_value=[_context("bnk-lab")]), \
             patch(_PROBE, return_value=_probe_result(has_bnk=True)):
            ClusterDiscoveryService(db).run()

        cluster = db.query(KubernetesCluster).one()
        first_seen = cluster.last_synced_at
        assert first_seen is not None

        with patch(_CONTEXTS, return_value=[_context("bnk-lab")]), \
             patch(_PROBE, return_value=_probe_result(reachable=False, version=None)):
            ClusterDiscoveryService(db).run()

        db.refresh(cluster)
        assert cluster.last_synced_at == first_seen


class TestProbe:
    """The real probe path — mocked at the Kubernetes client, not above it."""

    def test_probes_through_load_kubeconfig_so_eks_tokens_get_minted(self, db):
        """Discovery must get the same token-minting a registered cluster gets.

        `load_kubeconfig` is where the boto3 STS presign and the google-auth
        path live. A probe that built its own client would silently skip both
        and report every EKS context as unreachable.
        """
        candidate = _context("eks-prod", cloud_provider="eks", region="eu-west-2")

        with patch("services.kubernetes_service.KubernetesService.load_kubeconfig") as load, \
             patch("kubernetes.client.VersionApi") as version_api, \
             patch("kubernetes.client.CoreV1Api") as core_api:
            version_api.return_value.get_code.return_value.major = "1"
            version_api.return_value.get_code.return_value.minor = "29"
            core_api.return_value.list_namespace.return_value.items = []

            result = ClusterDiscoveryService(db)._probe(candidate)

        assert result["reachable"] is True
        assert result["version"] == "1.29"

        transient = load.call_args.args[0]
        assert transient.cloud_provider == "eks"
        assert transient.region == "eu-west-2"
        assert transient.context == "eks-prod"

    def test_the_transient_cluster_is_never_persisted(self, db):
        """It exists only to carry a kubeconfig into load_kubeconfig."""
        with patch("services.kubernetes_service.KubernetesService.load_kubeconfig"), \
             patch("kubernetes.client.VersionApi"), \
             patch("kubernetes.client.CoreV1Api") as core_api:
            core_api.return_value.list_namespace.return_value.items = []
            ClusterDiscoveryService(db)._probe(_context("lab-a"))

        assert db.query(KubernetesCluster).count() == 0

    def test_bnk_is_detected_from_the_pods_not_the_namespace_names(self, db):
        """The shape observed on a real DPF tenant cluster: TMM and the ingress
        controller both in `dpf-operator-system`, a namespace that also exists
        on DPF clusters carrying no BNK at all."""
        with patch("services.kubernetes_service.KubernetesService.load_kubeconfig"), \
             patch("kubernetes.client.VersionApi"), \
             patch("kubernetes.client.CoreV1Api") as core_api:
            core_api.return_value.list_pod_for_all_namespaces.side_effect = [
                _pod_list([("f5-tmm", "dpf-operator-system"),
                           ("f5-tmm", "dpf-operator-system"),
                           ("f5ingress-f5ingress", "dpf-operator-system")]),
                _pod_list([]),
            ]
            result = ClusterDiscoveryService(db)._probe(_context("lab-a"))

        assert result["has_bnk"] is True
        assert result["components"] == ["f5-tmm", "f5ingress-f5ingress"]
        assert result["namespaces"] == ["dpf-operator-system"]

    def test_a_cluster_with_no_bnk_pods_is_not_a_footprint(self, db):
        """The `infra` cluster case — Kubernetes, cert-manager, no BNK."""
        with patch("services.kubernetes_service.KubernetesService.load_kubeconfig"), \
             patch("kubernetes.client.VersionApi"), \
             patch("kubernetes.client.CoreV1Api") as core_api:
            core_api.return_value.list_pod_for_all_namespaces.return_value = _pod_list([])
            result = ClusterDiscoveryService(db)._probe(_context("lab-a"))

        assert result["has_bnk"] is False
        assert result["components"] == []

    def test_a_dpf_infra_cluster_registers_too(self, db):
        """The DPF operator runs on the *infra* cluster, which carries no BNK
        at all — and bnkscope has a DPF panel, so it is a cluster this tool is
        for. Observed on a real deployment: DPF operator on `infra`, BNK on the
        Kamaji tenant it provisions."""
        with patch("services.kubernetes_service.KubernetesService.load_kubeconfig"), \
             patch("kubernetes.client.VersionApi"), \
             patch("kubernetes.client.CoreV1Api") as core_api:
            core_api.return_value.list_pod_for_all_namespaces.side_effect = [
                _pod_list([]),
                _pod_list([("dpf-operator", "dpf-operator-system")],
                          key="app.kubernetes.io/name"),
            ]
            result = ClusterDiscoveryService(db)._probe(_context("infra"))

        assert result["has_dpf"] is True
        assert result["has_bnk"] is False
        assert result["components"] == ["dpf-operator"]

    def test_a_nico_infra_cluster_registers_without_claiming_bnk(self, db):
        """nico-api sits on the same infra cluster DPF does and carries no BNK.

        The subtraction in ``classify_cluster_components`` is what keeps that
        true: without excluding the NICo components, finding nico-api would set
        ``has_bnk`` and light the BNK readiness Dashboard for a deployment that
        belongs on the Kamaji tenant cluster.
        """
        with patch("services.kubernetes_service.KubernetesService.load_kubeconfig"), \
             patch("kubernetes.client.VersionApi"), \
             patch("kubernetes.client.CoreV1Api") as core_api:
            core_api.return_value.list_pod_for_all_namespaces.side_effect = [
                _pod_list([("nico-lb-provider-tmm", "nico-system")]),
                _pod_list([("dpf-operator", "dpf-operator-system"),
                           ("nico-api", "nico-system")],
                          key="app.kubernetes.io/name"),
            ]
            result = ClusterDiscoveryService(db)._probe(_context("infra"))

        assert result["has_nico"] is True
        assert result["has_dpf"] is True
        assert result["has_bnk"] is False

    def test_the_lb_provider_alone_does_not_gate_the_nico_tab(self, db):
        """The tab is a view of the control plane; a provider on its own has
        nothing to show."""
        with patch("services.kubernetes_service.KubernetesService.load_kubeconfig"), \
             patch("kubernetes.client.VersionApi"), \
             patch("kubernetes.client.CoreV1Api") as core_api:
            core_api.return_value.list_pod_for_all_namespaces.side_effect = [
                _pod_list([("nico-lb-provider-tmm", "nico-system")]),
                _pod_list([]),
            ]
            result = ClusterDiscoveryService(db)._probe(_context("infra"))

        assert result["has_nico"] is False
        assert result["has_bnk"] is False

    def test_a_completed_migration_job_is_not_a_component(self, db):
        """nico-api's chart ships a `nico-api-migrate` Job carrying the same
        `app.kubernetes.io/name` as the API. Its own `app` label wins the
        component lookup, so a Completed migration read as an unrecognised
        component — and, being neither DPF nor NICo, set has_bnk on an infra
        cluster that carries no BNK at all.
        """
        with patch("services.kubernetes_service.KubernetesService.load_kubeconfig"), \
             patch("kubernetes.client.VersionApi"), \
             patch("kubernetes.client.CoreV1Api") as core_api:
            core_api.return_value.list_pod_for_all_namespaces.side_effect = [
                _pod_list([("nico-api-migrate", "nico-system")], phase="Succeeded"),
                _pod_list([("nico-api", "nico-system")], key="app.kubernetes.io/name"),
            ]
            result = ClusterDiscoveryService(db)._probe(_context("infra"))

        assert result["components"] == ["nico-api"]
        assert result["has_nico"] is True
        assert result["has_bnk"] is False

    def test_the_standard_label_variant_is_also_matched(self, db):
        """Charts that use app.kubernetes.io/name instead of app."""
        with patch("services.kubernetes_service.KubernetesService.load_kubeconfig"), \
             patch("kubernetes.client.VersionApi"), \
             patch("kubernetes.client.CoreV1Api") as core_api:
            core_api.return_value.list_pod_for_all_namespaces.side_effect = [
                _pod_list([]),
                _pod_list([("f5-lifecycle-operator", "f5-bnk")], key="app.kubernetes.io/name"),
            ]
            result = ClusterDiscoveryService(db)._probe(_context("lab-a"))

        assert result["has_bnk"] is True
        assert result["components"] == ["f5-lifecycle-operator"]

    def test_one_denied_selector_does_not_lose_the_other(self, db):
        """A cluster whose RBAC blocks one list must not read as BNK-free."""
        with patch("services.kubernetes_service.KubernetesService.load_kubeconfig"), \
             patch("kubernetes.client.VersionApi"), \
             patch("kubernetes.client.CoreV1Api") as core_api:
            core_api.return_value.list_pod_for_all_namespaces.side_effect = [
                RuntimeError("forbidden"),
                _pod_list([("f5ingress", "f5-bnk")], key="app.kubernetes.io/name"),
            ]
            result = ClusterDiscoveryService(db)._probe(_context("lab-a"))

        assert result["has_bnk"] is True

    def test_a_failing_probe_returns_a_reason_rather_than_raising(self, db):
        """One bad context must not stop the sweep."""
        with patch(
            "services.kubernetes_service.KubernetesService.load_kubeconfig",
            side_effect=RuntimeError("connection refused"),
        ):
            result = ClusterDiscoveryService(db)._probe(_context("lab-a"))

        assert result["reachable"] is False
        assert "refused" in result["detail"]


class TestAdopt:
    def test_adopts_a_named_context(self, db):
        with patch(_CONTEXTS, return_value=[_context("no-bnk-yet")]), \
             patch(_PROBE, return_value=_probe_result(has_bnk=False)):
            result = ClusterDiscoveryService(db).adopt("no-bnk-yet")

        assert result["registered"] is True
        assert db.query(KubernetesCluster).filter_by(context="no-bnk-yet").count() == 1

    def test_unknown_context_is_a_404(self, db):
        from core.errors import NotFoundError

        with patch(_CONTEXTS, return_value=[_context("lab-a")]):
            with pytest.raises(NotFoundError):
                ClusterDiscoveryService(db).adopt("does-not-exist")

    def test_an_unadoptable_context_says_why(self, db):
        from core.errors import BadRequestError

        blocked = _context("aks-prod", blockers=["kubelogin cannot run here"])
        with patch(_CONTEXTS, return_value=[blocked]):
            with pytest.raises(BadRequestError) as exc:
                ClusterDiscoveryService(db).adopt("aks-prod")

        assert "kubelogin" in str(exc.value)

    def test_adopt_re_reads_the_kubeconfig_rather_than_trusting_the_caller(self, db):
        """The request carries a name; credentials always come from the host file."""
        with patch(_CONTEXTS, return_value=[_context("lab-a")]) as contexts, \
             patch(_PROBE, return_value=_probe_result()):
            ClusterDiscoveryService(db).adopt("lab-a")

        contexts.assert_called_once_with()


class TestProbeErrorMessages:
    """A failure an operator cannot act on is just noise."""

    def test_a_401_says_the_credentials_were_rejected(self):
        from kubernetes.client.exceptions import ApiException

        from services.cluster_discovery_service import _readable_probe_error

        message = _readable_probe_error(ApiException(status=401, reason="Unauthorized"))
        assert "rejected the credentials" in message
        assert "401" in message

    def test_a_timeout_names_the_usual_cause(self):
        from services.cluster_discovery_service import _readable_probe_error

        assert "VPN" in _readable_probe_error(TimeoutError("connection timed out"))

    def test_dns_failure_is_named(self):
        from services.cluster_discovery_service import _readable_probe_error

        message = _readable_probe_error(OSError("Name or service not known"))
        assert "does not resolve" in message

    def test_an_unknown_error_is_truncated_to_one_line(self):
        from services.cluster_discovery_service import _readable_probe_error

        message = _readable_probe_error(RuntimeError("boom\nstack\nframes\n"))
        assert message == "boom"


class TestFootprintBackfill:
    """`meta_data.has_dpf` for clusters the sweep can never reach.

    A cluster added by hand carries a context that is by definition not in the
    operator's own kubeconfig, so `_existing()` never matches it and the sweep
    walks straight past. Before the backfill it kept `has_dpf` unset forever
    and its DPF tab never appeared, however many times discovery ran.
    """

    _CLASSIFY = "services.cluster_discovery_service.classify_cluster_components"
    _LOAD = "services.kubernetes_service.KubernetesService.load_kubeconfig"

    def _hand_added(self, db, name="infra", meta=None):
        from core.encryption import encrypt_value

        cluster = KubernetesCluster(
            name=name,
            context="kubernetes-admin@kubernetes",
            api_server="https://192.168.68.66:6443",
            kubeconfig_encrypted=encrypt_value("apiVersion: v1\nkind: Config\n"),
            meta_data=meta,
            status="active",
        )
        db.add(cluster)
        db.commit()
        return cluster

    def _found(self, components):
        return {
            "components": components,
            "namespaces": ["dpf-operator-system"],
            "has_bnk": bool(set(components) - {"dpf-operator", "nico-api"}),
            "has_dpf": "dpf-operator" in components,
            "has_nico": "nico-api" in components,
        }

    def test_a_hand_added_infra_cluster_gets_its_dpf_flag(self, db):
        """The reported bug: 3 clusters, DPF operator on `infra`, no DPF tab."""
        cluster = self._hand_added(db)

        with patch(_CONTEXTS, return_value=[]), \
             patch(self._LOAD), \
             patch(self._CLASSIFY, return_value=self._found(["dpf-operator"])):
            ClusterDiscoveryService(db).run()

        db.refresh(cluster)
        assert cluster.meta_data["has_dpf"] is True
        assert cluster.meta_data["bnk_components"] == ["dpf-operator"]
        assert cluster.last_synced_at is not None

    def test_a_cluster_without_dpf_records_a_real_negative(self, db):
        cluster = self._hand_added(db, name="tenant")

        with patch(_CONTEXTS, return_value=[]), \
             patch(self._LOAD), \
             patch(self._CLASSIFY, return_value=self._found(["f5-tmm"])):
            ClusterDiscoveryService(db).run()

        db.refresh(cluster)
        assert cluster.meta_data["has_dpf"] is False

    def test_a_recorded_answer_is_not_probed_again(self, db):
        """Keyed on the key's absence, not its truth — otherwise every sweep
        re-probes every non-DPF cluster forever."""
        self._hand_added(db, name="tenant")

        with patch(_CONTEXTS, return_value=[]), \
             patch(self._LOAD), \
             patch(self._CLASSIFY, return_value=self._found(["f5-tmm"])) as classify:
            svc = ClusterDiscoveryService(db)
            svc.run()
            svc.run()

        assert classify.call_count == 1

    def test_an_unreachable_cluster_leaves_has_dpf_unset(self, db):
        """Not a confident False: a later sweep must be able to tell "never
        answered" from "answered no"."""
        cluster = self._hand_added(db)

        with patch(_CONTEXTS, return_value=[]), \
             patch(self._LOAD, side_effect=TimeoutError("connection timed out")):
            ClusterDiscoveryService(db).run()

        db.refresh(cluster)
        assert "has_dpf" not in cluster.meta_data
        assert "VPN" in cluster.meta_data["probe_error"]

    def test_an_unreachable_cluster_is_retried_next_sweep(self, db):
        cluster = self._hand_added(db)

        with patch(_CONTEXTS, return_value=[]), \
             patch(self._LOAD, side_effect=TimeoutError("connection timed out")):
            ClusterDiscoveryService(db).run()
        with patch(_CONTEXTS, return_value=[]), \
             patch(self._LOAD), \
             patch(self._CLASSIFY, return_value=self._found(["dpf-operator"])):
            ClusterDiscoveryService(db).run()

        db.refresh(cluster)
        assert cluster.meta_data["has_dpf"] is True
        assert "probe_error" not in cluster.meta_data

    def test_a_discovered_cluster_is_left_alone(self, db):
        """The sweep already answered for it; the backfill must not re-probe."""
        with patch(_CONTEXTS, return_value=[_context("bnk-lab")]), \
             patch(_PROBE, return_value=_probe_result(has_bnk=True)):
            ClusterDiscoveryService(db).run()

        with patch(_CONTEXTS, return_value=[]), \
             patch(self._LOAD), \
             patch(self._CLASSIFY) as classify:
            ClusterDiscoveryService(db).run()

        classify.assert_not_called()
