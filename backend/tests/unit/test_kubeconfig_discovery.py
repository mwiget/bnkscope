"""Reading the operator's kubeconfig and splitting it into candidates.

Everything here works on real files in a tmp_path, because what this module
does IS file handling: resolving relative paths, reading certs off disk,
deciding what to do when one is missing. Mocking the filesystem would test the
mock.
"""

import base64
import os

import pytest
import yaml

from services import kubeconfig_discovery
from services.kubeconfig_discovery import (
    MINTABLE_EXEC_COMMANDS,
    discover_contexts,
    kubeconfig_paths,
)


def _kubeconfig(contexts, clusters=None, users=None, current=None):
    """Minimal kubeconfig doc. Each arg is a list of (name, body) pairs."""
    doc = {
        "apiVersion": "v1",
        "kind": "Config",
        "contexts": [{"name": n, "context": b} for n, b in contexts],
        "clusters": [{"name": n, "cluster": b} for n, b in (clusters or [])],
        "users": [{"name": n, "user": b} for n, b in (users or [])],
    }
    if current:
        doc["current-context"] = current
    return doc


def _write(path, doc):
    path.write_text(yaml.dump(doc))
    return path


@pytest.fixture()
def kubeconfig_at(tmp_path, monkeypatch):
    """Point discovery at a kubeconfig written into tmp_path."""

    def _make(doc, name="config"):
        path = _write(tmp_path / name, doc)
        monkeypatch.setenv("KUBECONFIG", str(path))
        return path

    return _make


@pytest.fixture(autouse=True)
def _no_ambient_kubeconfig(monkeypatch):
    monkeypatch.delenv("KUBECONFIG", raising=False)
    monkeypatch.delenv("BNKSCOPE_KUBECONFIG", raising=False)


class TestKubeconfigPaths:
    def test_kubeconfig_env_wins(self, tmp_path, monkeypatch):
        a, b = tmp_path / "a", tmp_path / "b"
        a.write_text("{}")
        b.write_text("{}")
        monkeypatch.setenv("KUBECONFIG", f"{a}{os.pathsep}{b}")
        assert kubeconfig_paths() == [a, b]

    def test_nonexistent_entries_are_dropped(self, tmp_path, monkeypatch):
        """$KUBECONFIG routinely lists files that are not there."""
        real = tmp_path / "real"
        real.write_text("{}")
        monkeypatch.setenv("KUBECONFIG", f"{tmp_path / 'ghost'}{os.pathsep}{real}")
        assert kubeconfig_paths() == [real]

    def test_falls_back_to_the_mounted_default(self, monkeypatch):
        monkeypatch.setattr(kubeconfig_discovery, "DEFAULT_KUBECONFIG_PATH", "/nope/config")
        assert kubeconfig_paths() == []

    def test_bnkscope_override_is_honoured(self, tmp_path, monkeypatch):
        path = tmp_path / "custom"
        path.write_text("{}")
        monkeypatch.setenv("BNKSCOPE_KUBECONFIG", str(path))
        assert kubeconfig_paths() == [path]


class TestDiscoverContexts:
    def test_finds_a_context(self, kubeconfig_at):
        kubeconfig_at(
            _kubeconfig(
                contexts=[("lab-a", {"cluster": "c1", "user": "u1"})],
                clusters=[("c1", {"server": "https://10.1.2.3:6443"})],
                users=[("u1", {"token": "sha256~abc"})],
            )
        )
        found = discover_contexts()
        assert len(found) == 1
        assert found[0].name == "lab-a"
        assert found[0].api_server == "https://10.1.2.3:6443"
        assert found[0].auth_method == "token"
        assert found[0].adoptable

    def test_missing_file_is_not_an_error(self, monkeypatch):
        """Discovery runs at startup; an absent kubeconfig must not stop boot."""
        monkeypatch.setattr(kubeconfig_discovery, "DEFAULT_KUBECONFIG_PATH", "/nope/config")
        assert discover_contexts() == []

    def test_unparseable_file_is_skipped_not_raised(self, tmp_path, monkeypatch):
        bad = tmp_path / "config"
        bad.write_text("{{{ not yaml")
        monkeypatch.setenv("KUBECONFIG", str(bad))
        assert discover_contexts() == []

    def test_a_non_mapping_file_is_skipped(self, tmp_path, monkeypatch):
        bad = tmp_path / "config"
        bad.write_text("- just\n- a list\n")
        monkeypatch.setenv("KUBECONFIG", str(bad))
        assert discover_contexts() == []

    def test_first_file_wins_on_duplicate_names(self, tmp_path, monkeypatch):
        """kubectl's merge rule, and operators really do have colliding names."""
        first = _write(
            tmp_path / "first",
            _kubeconfig(
                contexts=[("shared", {"cluster": "c1", "user": "u1"})],
                clusters=[("c1", {"server": "https://first:6443"})],
                users=[("u1", {"token": "t"})],
            ),
        )
        second = _write(
            tmp_path / "second",
            _kubeconfig(
                contexts=[("shared", {"cluster": "c2", "user": "u2"})],
                clusters=[("c2", {"server": "https://second:6443"})],
                users=[("u2", {"token": "t"})],
            ),
        )
        monkeypatch.setenv("KUBECONFIG", f"{first}{os.pathsep}{second}")

        found = discover_contexts()
        assert len(found) == 1
        assert found[0].api_server == "https://first:6443"

    def test_reports_which_file_a_context_came_from(self, kubeconfig_at):
        """A laptop has several kubeconfigs; 'which one' is a real question."""
        path = kubeconfig_at(
            _kubeconfig(
                contexts=[("lab-a", {"cluster": "c1", "user": "u1"})],
                clusters=[("c1", {"server": "https://h:6443"})],
                users=[("u1", {"token": "t"})],
            )
        )
        assert discover_contexts()[0].source_path == str(path)

    def test_context_namespace_is_carried_over(self, kubeconfig_at):
        kubeconfig_at(
            _kubeconfig(
                contexts=[("lab-a", {"cluster": "c1", "user": "u1", "namespace": "f5-bnk"})],
                clusters=[("c1", {"server": "https://h:6443"})],
                users=[("u1", {"token": "t"})],
            )
        )
        assert discover_contexts()[0].namespace == "f5-bnk"

    def test_context_without_a_namespace_defaults(self, kubeconfig_at):
        kubeconfig_at(
            _kubeconfig(
                contexts=[("lab-a", {"cluster": "c1", "user": "u1"})],
                clusters=[("c1", {"server": "https://h:6443"})],
                users=[("u1", {"token": "t"})],
            )
        )
        assert discover_contexts()[0].namespace == "default"

    def test_a_dangling_cluster_reference_is_a_blocker_not_a_crash(self, kubeconfig_at):
        kubeconfig_at(
            _kubeconfig(
                contexts=[("orphan", {"cluster": "missing", "user": "u1"})],
                users=[("u1", {"token": "t"})],
            )
        )
        found = discover_contexts()
        assert len(found) == 1
        assert not found[0].adoptable
        assert "missing" in found[0].blockers[0]


class TestFileReferences:
    def test_absolute_cert_paths_are_inlined(self, tmp_path, kubeconfig_at):
        ca = tmp_path / "ca.crt"
        ca.write_bytes(b"-----BEGIN CERTIFICATE-----")
        kubeconfig_at(
            _kubeconfig(
                contexts=[("lab-a", {"cluster": "c1", "user": "u1"})],
                clusters=[("c1", {"server": "https://h:6443", "certificate-authority": str(ca)})],
                users=[("u1", {"token": "t"})],
            )
        )
        found = discover_contexts()[0]
        assert found.adoptable

        doc = yaml.safe_load(found.kubeconfig)
        cluster = doc["clusters"][0]["cluster"]
        assert "certificate-authority" not in cluster
        assert base64.b64decode(cluster["certificate-authority-data"]) == b"-----BEGIN CERTIFICATE-----"

    def test_relative_paths_resolve_against_the_kubeconfig_dir(self, tmp_path, kubeconfig_at):
        """How kubectl resolves them, and minikube writes them this way."""
        (tmp_path / "ca.crt").write_bytes(b"CA")
        kubeconfig_at(
            _kubeconfig(
                contexts=[("lab-a", {"cluster": "c1", "user": "u1"})],
                clusters=[("c1", {"server": "https://h:6443", "certificate-authority": "ca.crt"})],
                users=[("u1", {"token": "t"})],
            )
        )
        found = discover_contexts()[0]
        assert found.adoptable
        doc = yaml.safe_load(found.kubeconfig)
        assert base64.b64decode(doc["clusters"][0]["cluster"]["certificate-authority-data"]) == b"CA"

    def test_client_cert_and_key_are_both_inlined(self, tmp_path, kubeconfig_at):
        (tmp_path / "client.crt").write_bytes(b"CRT")
        (tmp_path / "client.key").write_bytes(b"KEY")
        kubeconfig_at(
            _kubeconfig(
                contexts=[("lab-a", {"cluster": "c1", "user": "u1"})],
                clusters=[("c1", {"server": "https://h:6443"})],
                users=[
                    (
                        "u1",
                        {
                            "client-certificate": str(tmp_path / "client.crt"),
                            "client-key": str(tmp_path / "client.key"),
                        },
                    )
                ],
            )
        )
        found = discover_contexts()[0]
        assert found.adoptable
        assert found.auth_method == "client-certificate"
        user = yaml.safe_load(found.kubeconfig)["users"][0]["user"]
        assert base64.b64decode(user["client-certificate-data"]) == b"CRT"
        assert base64.b64decode(user["client-key-data"]) == b"KEY"

    def test_token_file_becomes_an_inline_token(self, tmp_path, kubeconfig_at):
        """tokenFile holds the token itself — not base64 of it."""
        (tmp_path / "tok").write_text("sha256~secret\n")
        kubeconfig_at(
            _kubeconfig(
                contexts=[("lab-a", {"cluster": "c1", "user": "u1"})],
                clusters=[("c1", {"server": "https://h:6443"})],
                users=[("u1", {"tokenFile": str(tmp_path / "tok")})],
            )
        )
        found = discover_contexts()[0]
        user = yaml.safe_load(found.kubeconfig)["users"][0]["user"]
        assert user["token"] == "sha256~secret"
        assert "tokenFile" not in user

    def test_unreadable_path_becomes_a_blocker_with_the_path_in_it(self, kubeconfig_at):
        """The minikube case: certs live outside anything bnkscope mounts."""
        kubeconfig_at(
            _kubeconfig(
                contexts=[("minikube", {"cluster": "c1", "user": "u1"})],
                clusters=[("c1", {"server": "https://h:6443"})],
                users=[("u1", {"client-key": "/home/someone/.minikube/client.key"})],
            )
        )
        found = discover_contexts()[0]
        assert not found.adoptable
        assert "/home/someone/.minikube/client.key" in found.blockers[0]
        assert "--flatten" in found.blockers[0]

    def test_inline_data_wins_over_a_path(self, kubeconfig_at):
        """Same precedence the normalizer uses; the dead path is just dropped."""
        kubeconfig_at(
            _kubeconfig(
                contexts=[("lab-a", {"cluster": "c1", "user": "u1"})],
                clusters=[
                    (
                        "c1",
                        {
                            "server": "https://h:6443",
                            "certificate-authority": "/gone/ca.crt",
                            "certificate-authority-data": base64.b64encode(b"CA").decode(),
                        },
                    )
                ],
                users=[("u1", {"token": "t"})],
            )
        )
        found = discover_contexts()[0]
        assert found.adoptable
        cluster = yaml.safe_load(found.kubeconfig)["clusters"][0]["cluster"]
        assert "certificate-authority" not in cluster


class TestExecAuth:
    @pytest.mark.parametrize("command", sorted(MINTABLE_EXEC_COMMANDS))
    def test_mintable_plugins_are_adoptable(self, command, kubeconfig_at):
        """bnkscope mints these itself — the binary is never invoked."""
        kubeconfig_at(
            _kubeconfig(
                contexts=[("lab-a", {"cluster": "c1", "user": "u1"})],
                clusters=[("c1", {"server": "https://h:6443"})],
                users=[("u1", {"exec": {"command": command, "args": []}})],
            )
        )
        found = discover_contexts()[0]
        assert found.adoptable
        assert found.auth_method == f"exec:{command}"

    def test_kubelogin_is_reported_with_a_way_out(self, kubeconfig_at):
        kubeconfig_at(
            _kubeconfig(
                contexts=[("aks-prod", {"cluster": "c1", "user": "u1"})],
                clusters=[("c1", {"server": "https://x.hcp.westeurope.azmk8s.io:443"})],
                users=[("u1", {"exec": {"command": "kubelogin"}})],
            )
        )
        found = discover_contexts()[0]
        assert not found.adoptable
        assert "kubelogin" in found.blockers[0]
        assert "kubectl create token" in found.blockers[0]

    def test_a_plugin_given_by_absolute_path_is_still_that_plugin(self, kubeconfig_at):
        """`command: /usr/local/bin/aws` is as mintable as `command: aws`."""
        kubeconfig_at(
            _kubeconfig(
                contexts=[("eks", {"cluster": "c1", "user": "u1"})],
                clusters=[("c1", {"server": "https://h:6443"})],
                users=[("u1", {"exec": {"command": "/usr/local/bin/aws"}})],
            )
        )
        found = discover_contexts()[0]
        assert found.adoptable
        assert found.auth_method == "exec:aws"


class TestProviderAndRegion:
    def test_eks_region_from_the_exec_region_flag(self, kubeconfig_at):
        """What `aws eks update-kubeconfig` writes."""
        kubeconfig_at(
            _kubeconfig(
                contexts=[("eks", {"cluster": "c1", "user": "u1"})],
                clusters=[("c1", {"server": "https://ABC.gr7.eu-central-1.eks.amazonaws.com"})],
                users=[
                    (
                        "u1",
                        {
                            "exec": {
                                "command": "aws",
                                "args": ["--region", "eu-west-2", "eks", "get-token"],
                            }
                        },
                    )
                ],
            )
        )
        found = discover_contexts()[0]
        assert found.cloud_provider == "eks"
        # The explicit flag wins over the hostname — it is what the CLI would use.
        assert found.region == "eu-west-2"

    def test_eks_region_falls_back_to_the_hostname(self, kubeconfig_at):
        kubeconfig_at(
            _kubeconfig(
                contexts=[("eks", {"cluster": "c1", "user": "u1"})],
                clusters=[("c1", {"server": "https://ABC.gr7.eu-central-1.eks.amazonaws.com"})],
                users=[("u1", {"token": "t"})],
            )
        )
        found = discover_contexts()[0]
        assert found.cloud_provider == "eks"
        assert found.region == "eu-central-1"

    def test_eks_region_from_the_exec_env_block(self, kubeconfig_at):
        kubeconfig_at(
            _kubeconfig(
                contexts=[("eks", {"cluster": "c1", "user": "u1"})],
                clusters=[("c1", {"server": "https://h:6443"})],
                users=[
                    (
                        "u1",
                        {
                            "exec": {
                                "command": "aws",
                                "args": ["eks", "get-token"],
                                "env": [{"name": "AWS_REGION", "value": "ap-south-1"}],
                            }
                        },
                    )
                ],
            )
        )
        assert discover_contexts()[0].region == "ap-south-1"

    def test_region_equals_form_is_understood(self, kubeconfig_at):
        kubeconfig_at(
            _kubeconfig(
                contexts=[("eks", {"cluster": "c1", "user": "u1"})],
                clusters=[("c1", {"server": "https://h:6443"})],
                users=[
                    ("u1", {"exec": {"command": "aws", "args": ["--region=us-east-2"]}}),
                ],
            )
        )
        assert discover_contexts()[0].region == "us-east-2"

    @pytest.mark.parametrize(
        ("server", "provider"),
        [
            ("https://x.hcp.westeurope.azmk8s.io:443", "aks"),
            ("https://x.europe-west1.gke.goog", "gke"),
            ("https://10.1.2.3:6443", "on-prem"),
        ],
    )
    def test_provider_inferred_from_the_server_hostname(self, server, provider, kubeconfig_at):
        kubeconfig_at(
            _kubeconfig(
                contexts=[("ctx", {"cluster": "c1", "user": "u1"})],
                clusters=[("c1", {"server": server})],
                users=[("u1", {"token": "t"})],
            )
        )
        assert discover_contexts()[0].cloud_provider == provider

    def test_on_prem_has_no_region(self, kubeconfig_at):
        kubeconfig_at(
            _kubeconfig(
                contexts=[("lab", {"cluster": "c1", "user": "u1"})],
                clusters=[("c1", {"server": "https://10.1.2.3:6443"})],
                users=[("u1", {"token": "t"})],
            )
        )
        assert discover_contexts()[0].region is None


class TestRenderedKubeconfig:
    def test_holds_exactly_one_context(self, kubeconfig_at):
        """Stored per cluster, so an unrelated edit on the host cannot break it."""
        kubeconfig_at(
            _kubeconfig(
                contexts=[
                    ("keep", {"cluster": "c1", "user": "u1"}),
                    ("drop", {"cluster": "c2", "user": "u2"}),
                ],
                clusters=[
                    ("c1", {"server": "https://keep:6443"}),
                    ("c2", {"server": "https://drop:6443"}),
                ],
                users=[("u1", {"token": "t1"}), ("u2", {"token": "t2"})],
            )
        )
        keep = next(c for c in discover_contexts() if c.name == "keep")
        doc = yaml.safe_load(keep.kubeconfig)

        assert [c["name"] for c in doc["contexts"]] == ["keep"]
        assert [c["name"] for c in doc["clusters"]] == ["c1"]
        assert [u["name"] for u in doc["users"]] == ["u1"]
        assert doc["current-context"] == "keep"
        assert "t2" not in keep.kubeconfig

    def test_is_loadable_by_the_kubernetes_client(self, tmp_path, kubeconfig_at):
        """The real consumer. A doc the client rejects is worse than no doc."""
        from kubernetes import config as k8s_config

        kubeconfig_at(
            _kubeconfig(
                contexts=[("lab-a", {"cluster": "c1", "user": "u1"})],
                clusters=[("c1", {"server": "https://10.1.2.3:6443", "insecure-skip-tls-verify": True})],
                users=[("u1", {"token": "sha256~abc"})],
            )
        )
        rendered = tmp_path / "rendered.yaml"
        rendered.write_text(discover_contexts()[0].kubeconfig)

        loader = k8s_config.kube_config.KubeConfigLoader(
            config_dict=yaml.safe_load(rendered.read_text())
        )
        assert loader.current_context["name"] == "lab-a"

    def test_a_context_with_no_user_still_renders(self, kubeconfig_at):
        """Anonymous access to an unauthenticated API server is legal."""
        kubeconfig_at(
            _kubeconfig(
                contexts=[("anon", {"cluster": "c1"})],
                clusters=[("c1", {"server": "https://h:6443"})],
            )
        )
        found = discover_contexts()[0]
        assert found.auth_method == "anonymous"
        assert found.adoptable
        assert yaml.safe_load(found.kubeconfig)["users"] == []
