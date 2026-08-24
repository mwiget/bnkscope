"""tmmscope routes, and the label-matching that joins the two tools.

The hard part is not the HTTP: it is that bnkscope and tmmscope share no
identifier. `tmmscope inject --cluster` names the `cluster=` label whatever the
operator wants, so most of these tests are about matching it without guessing
wrong — a wrong match points the dashboard at a *different* cluster's
telemetry, which is worse than showing none.
"""

from unittest.mock import patch

import pytest

from models import KubernetesCluster
from routes.tmmscope import _LABEL_KEY, _match_label
from services.tmmscope_service import TmmscopeStatus

_STATUS = "routes.tmmscope.tmmscope_service.get_status"


def _cluster(**kwargs) -> KubernetesCluster:
    defaults = {
        "name": "lab-a",
        "context": "lab-a",
        "default_namespace": "default",
        "discovered_namespaces": None,
        "meta_data": None,
    }
    return KubernetesCluster(**{**defaults, **kwargs})


def _running(streaming: list[str]) -> TmmscopeStatus:
    return TmmscopeStatus(
        configured=True,
        running=True,
        grafana_url="http://localhost:3000",
        prometheus_url="http://localhost:9491",
        streaming_clusters=streaming,
    )


class TestMatchLabel:
    def test_matches_the_context_name(self):
        """tmmscope's own default for --cluster."""
        assert _match_label(_cluster(context="lab-a"), ["lab-a"]) == "lab-a"

    def test_matches_the_cluster_half_of_a_user_at_cluster_context(self):
        """Observed on a real Kamaji tenant cluster: the context is
        `kubernetes-admin@dpu-cplane-tenant1` and the label is the half after
        the @, which is what a human calls the cluster."""
        cluster = _cluster(name="dpu", context="kubernetes-admin@dpu-cplane-tenant1")
        assert _match_label(cluster, ["dpu-cplane-tenant1"]) == "dpu-cplane-tenant1"

    def test_matches_the_bnkscope_cluster_name(self):
        assert _match_label(_cluster(name="prod", context="ctx"), ["prod"]) == "prod"

    def test_matches_a_discovered_namespace(self):
        """Operators commonly label after the namespace TMM runs in."""
        cluster = _cluster(context="ctx", name="n", discovered_namespaces=["f5-bnk"])
        assert _match_label(cluster, ["f5-bnk"]) == "f5-bnk"

    def test_is_case_insensitive(self):
        assert _match_label(_cluster(context="Lab-A"), ["lab-a"]) == "lab-a"

    def test_returns_none_rather_than_guessing(self):
        """A wrong match shows another cluster's telemetry under this one's
        name. Showing nothing is the safer failure."""
        assert _match_label(_cluster(context="lab-a"), ["something-else"]) is None

    def test_no_streaming_labels_matches_nothing(self):
        assert _match_label(_cluster(), []) is None

    def test_an_explicit_binding_wins_over_every_convention(self):
        cluster = _cluster(context="lab-a", meta_data={_LABEL_KEY: "hand-picked"})
        assert _match_label(cluster, ["lab-a", "hand-picked"]) == "hand-picked"

    def test_a_binding_that_stopped_streaming_reports_nothing(self):
        """Not "fall back to a name match" — the operator pinned this on
        purpose and needs to see that it went away."""
        cluster = _cluster(context="lab-a", meta_data={_LABEL_KEY: "gone"})
        assert _match_label(cluster, ["lab-a"]) is None


class TestStatusRoute:
    def test_reports_a_running_stack(self, client):
        with patch(_STATUS, return_value=_running(["lab-a"])):
            response = client.get("/api/tmmscope/status")

        assert response.status_code == 200
        body = response.json()
        assert body["running"] is True
        assert body["streaming_clusters"] == ["lab-a"]
        assert [d["uid"] for d in body["dashboards"]] == ["tmm-realtime", "tmm-ai-tokens"]

    def test_reports_a_stack_that_was_never_started(self, client):
        with patch(_STATUS, return_value=TmmscopeStatus(detail="not started")):
            response = client.get("/api/tmmscope/status")

        assert response.status_code == 200
        assert response.json()["running"] is False


class TestClusterTelemetryRoute:
    @pytest.fixture()
    def cluster(self, db):
        row = KubernetesCluster(
            name="dpu-cplane-tenant1",
            context="kubernetes-admin@dpu-cplane-tenant1",
            default_namespace="default",
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return row

    def test_builds_an_embeddable_url_for_a_streaming_cluster(self, client, cluster):
        with patch(_STATUS, return_value=_running(["dpu-cplane-tenant1"])):
            response = client.get(f"/api/tmmscope/clusters/{cluster.id}")

        body = response.json()
        assert body["streaming"] is True
        assert body["streaming_as"] == "dpu-cplane-tenant1"
        assert "var-cluster=dpu-cplane-tenant1" in body["dashboard_url"]
        assert "kiosk" in body["dashboard_url"]

    def test_no_dashboard_url_when_nothing_is_streaming(self, client, cluster):
        with patch(_STATUS, return_value=_running([])):
            response = client.get(f"/api/tmmscope/clusters/{cluster.id}")

        body = response.json()
        assert body["streaming"] is False
        assert body["dashboard_url"] is None
        # The command to fix it is still offered.
        assert "tmmscope inject" in body["inject_command"]

    def test_no_dashboard_url_when_the_stack_is_down(self, client, cluster):
        with patch(_STATUS, return_value=TmmscopeStatus(configured=True, running=False)):
            response = client.get(f"/api/tmmscope/clusters/{cluster.id}")
        assert response.json()["dashboard_url"] is None

    def test_offers_the_labels_that_are_streaming(self, client, cluster):
        """So the UI can let the operator bind the right one."""
        with patch(_STATUS, return_value=_running(["someone-elses-cluster"])):
            response = client.get(f"/api/tmmscope/clusters/{cluster.id}")

        assert response.json()["available_labels"] == ["someone-elses-cluster"]

    def test_the_theme_reaches_grafana(self, client, cluster):
        with patch(_STATUS, return_value=_running(["dpu-cplane-tenant1"])):
            response = client.get(f"/api/tmmscope/clusters/{cluster.id}?theme=light")
        assert "theme=light" in response.json()["dashboard_url"]

    def test_an_unknown_theme_falls_back_to_dark(self, client, cluster):
        """Grafana understands two; anything else renders unstyled."""
        with patch(_STATUS, return_value=_running(["dpu-cplane-tenant1"])):
            response = client.get(f"/api/tmmscope/clusters/{cluster.id}?theme=neon")
        assert "theme=dark" in response.json()["dashboard_url"]

    def test_unknown_cluster_is_404(self, client):
        with patch(_STATUS, return_value=_running([])):
            response = client.get("/api/tmmscope/clusters/9999")
        assert response.status_code == 404


class TestBindLabel:
    @pytest.fixture()
    def cluster(self, db):
        row = KubernetesCluster(name="lab-a", context="lab-a", default_namespace="default")
        db.add(row)
        db.commit()
        db.refresh(row)
        return row

    def test_binding_makes_a_mismatched_label_stream(self, client, db, cluster):
        with patch(_STATUS, return_value=_running(["totally-different"])):
            response = client.put(
                f"/api/tmmscope/clusters/{cluster.id}/label",
                json={"label": "totally-different"},
            )

        body = response.json()
        assert body["streaming"] is True
        assert body["streaming_as"] == "totally-different"
        assert body["label_pinned"] is True

        db.refresh(cluster)
        assert cluster.meta_data[_LABEL_KEY] == "totally-different"

    def test_clearing_returns_to_name_matching(self, client, db, cluster):
        cluster.meta_data = {_LABEL_KEY: "totally-different"}
        db.commit()

        with patch(_STATUS, return_value=_running(["lab-a"])):
            response = client.put(
                f"/api/tmmscope/clusters/{cluster.id}/label", json={"label": None}
            )

        body = response.json()
        assert body["streaming_as"] == "lab-a"
        assert body["label_pinned"] is False

        db.refresh(cluster)
        assert _LABEL_KEY not in (cluster.meta_data or {})

    def test_binding_leaves_other_metadata_alone(self, client, db, cluster):
        cluster.meta_data = {"discovered": True, "auth_method": "token"}
        db.commit()

        with patch(_STATUS, return_value=_running(["lab-a"])):
            client.put(f"/api/tmmscope/clusters/{cluster.id}/label", json={"label": "lab-a"})

        db.refresh(cluster)
        assert cluster.meta_data["discovered"] is True
        assert cluster.meta_data["auth_method"] == "token"

    def test_unknown_cluster_is_404(self, client):
        response = client.put("/api/tmmscope/clusters/9999/label", json={"label": "x"})
        assert response.status_code == 404
