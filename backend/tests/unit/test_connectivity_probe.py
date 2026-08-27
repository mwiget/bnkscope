"""
Unit tests for services.connectivity_probe_service.

Tests the pure functions (parsing, diagnostics) and the probe logic
with mocked network calls. No database or external services needed.
"""

import pytest

from services.connectivity_probe_service import (
    _build_diagnostic_message,
    _parse_api_server,
)

# ---------------------------------------------------------------------------
# _parse_api_server
# ---------------------------------------------------------------------------

class TestParseApiServer:
    def test_standard_url(self):
        host, port = _parse_api_server("https://192.0.2.10:6443")
        assert host == "192.0.2.10"
        assert port == 6443

    def test_default_port_https(self):
        # https URL with no explicit port → 443 (RFC default for the scheme).
        # Pre-fix this returned 6443, which broke the probe for any EKS / GKE /
        # AKS public endpoint whose kubeconfig URL omits the port.
        host, port = _parse_api_server("https://k8s.example.com")
        assert host == "k8s.example.com"
        assert port == 443

    def test_default_port_http(self):
        host, port = _parse_api_server("http://k8s.example.com")
        assert host == "k8s.example.com"
        assert port == 80

    def test_custom_port(self):
        host, port = _parse_api_server("https://my-cluster:8443")
        assert host == "my-cluster"
        assert port == 8443

    def test_empty_string(self):
        host, port = _parse_api_server("")
        assert host is None
        assert port == 6443

    def test_none_input(self):
        host, port = _parse_api_server(None)
        assert host is None
        assert port == 6443

    def test_http_url(self):
        host, port = _parse_api_server("http://insecure:8080")
        assert host == "insecure"
        assert port == 8080


# ---------------------------------------------------------------------------
# _build_diagnostic_message
# ---------------------------------------------------------------------------

class TestBuildDiagnosticMessage:
    """Test the 5 canonical connectivity states: connected, reachable, partial, unreachable, unknown."""

    def test_connected_with_version(self):
        result = _build_diagnostic_message(
            host="10.0.0.1", port=6443,
            icmp={"reachable": True, "latency_ms": 1.5},
            tcp={"open": True},
            k8s_api={"accessible": True, "version": "1.30"},
        )
        assert result["status"] == "connected"
        assert "1.30" in result["message"]
        assert result["suggestion"] is None

    def test_connected_without_latency(self):
        result = _build_diagnostic_message(
            host="10.0.0.1", port=6443,
            icmp={"reachable": False, "latency_ms": None},
            tcp={"open": True},
            k8s_api={"accessible": True, "version": "1.28"},
        )
        assert result["status"] == "connected"
        assert "Latency" not in result["message"]

    def test_reachable_tcp_open_but_no_api(self):
        result = _build_diagnostic_message(
            host="10.0.0.1", port=6443,
            icmp={"reachable": True, "latency_ms": 5.0},
            tcp={"open": True},
            k8s_api={"accessible": False},
        )
        assert result["status"] == "reachable"
        assert "6443" in result["message"]
        assert result["suggestion"] is not None

    def test_partial_icmp_reachable_tcp_blocked(self):
        result = _build_diagnostic_message(
            host="192.0.2.10", port=6443,
            icmp={"reachable": True, "latency_ms": 170.0},
            tcp={"open": False},
            k8s_api={"accessible": False},
        )
        assert result["status"] == "partial"
        assert "170ms" in result["message"]
        assert "firewall" in result["suggestion"].lower()

    def test_unreachable(self):
        result = _build_diagnostic_message(
            host="10.0.0.99", port=6443,
            icmp={"reachable": False, "latency_ms": None},
            tcp={"open": False},
            k8s_api={"accessible": False},
        )
        assert result["status"] == "unreachable"
        assert "10.0.0.99" in result["message"]
        assert "10.0.0.99" in result["suggestion"]

    def test_unknown_no_host(self):
        result = _build_diagnostic_message(
            host=None, port=6443,
            icmp={"reachable": False},
            tcp={"open": False},
            k8s_api={"accessible": False},
        )
        assert result["status"] == "unknown"
        assert "No API server" in result["message"]


# ---------------------------------------------------------------------------
# _probe_icmp (mocked)
# ---------------------------------------------------------------------------

class TestProbeIcmpFallback:
    """Test that _probe_icmp tries multiple methods gracefully."""

    def test_subprocess_ping_success(self):
        """When subprocess ping works, should return reachable."""
        import subprocess
        from unittest.mock import MagicMock, patch

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "64 bytes from 10.0.0.1: icmp_seq=1 ttl=64 time=1.23 ms"

        with patch("services.connectivity_probe_service.subprocess.run", return_value=mock_result):
            from services.connectivity_probe_service import _probe_icmp
            result = _probe_icmp("10.0.0.1", timeout=2)
            assert result["reachable"] is True
            assert result["latency_ms"] == pytest.approx(1.23)

    def test_subprocess_ping_not_found_falls_through(self):
        """When ping binary not found, should try socket methods."""
        import subprocess
        from unittest.mock import patch

        with patch("services.connectivity_probe_service.subprocess.run", side_effect=FileNotFoundError):
            with patch("services.connectivity_probe_service.socket.socket") as mock_socket:
                # Make socket creation fail with PermissionError for both SOCK_DGRAM and SOCK_RAW
                mock_socket.side_effect = PermissionError("not allowed")
                from services.connectivity_probe_service import _probe_icmp
                result = _probe_icmp("10.0.0.1", timeout=1)
                # Falls through all methods — returns unreachable
                assert result["reachable"] is False


# ---------------------------------------------------------------------------
# _probe_tcp (mocked)
# ---------------------------------------------------------------------------

class TestProbeTcp:
    def test_tcp_open(self):
        from unittest.mock import MagicMock, patch
        mock_sock = MagicMock()
        mock_sock.connect_ex.return_value = 0

        with patch("services.connectivity_probe_service.socket.socket", return_value=mock_sock):
            from services.connectivity_probe_service import _probe_tcp
            result = _probe_tcp("10.0.0.1", 6443, timeout=2)
            assert result["open"] is True
            assert result["connect_ms"] is not None

    def test_tcp_closed(self):
        from unittest.mock import MagicMock, patch
        mock_sock = MagicMock()
        mock_sock.connect_ex.return_value = 111  # ECONNREFUSED

        with patch("services.connectivity_probe_service.socket.socket", return_value=mock_sock):
            from services.connectivity_probe_service import _probe_tcp
            result = _probe_tcp("10.0.0.1", 6443, timeout=2)
            assert result["open"] is False

    def test_tcp_timeout(self):
        import socket
        from unittest.mock import patch

        with patch("services.connectivity_probe_service.socket.socket") as mock_socket:
            mock_socket.return_value.connect_ex.side_effect = socket.timeout
            from services.connectivity_probe_service import _probe_tcp
            result = _probe_tcp("10.0.0.1", 6443, timeout=1)
            assert result["open"] is False


# ---------------------------------------------------------------------------
# _probe_k8s_api (mocked)
# ---------------------------------------------------------------------------

class TestProbeK8sApi:
    def test_api_accessible_200(self):
        from unittest.mock import MagicMock, patch

        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.read.return_value = b'{"major":"1","minor":"30"}'

        mock_conn = MagicMock()
        mock_conn.getresponse.return_value = mock_response

        with patch("http.client.HTTPSConnection", return_value=mock_conn):
            from services.connectivity_probe_service import _probe_k8s_api
            result = _probe_k8s_api("10.0.0.1", 6443)
            assert result["accessible"] is True
            assert result["version"] == "1.30"
            assert result["status_code"] == 200

    def test_api_accessible_401(self):
        """401 means the API is there but needs auth — still accessible."""
        from unittest.mock import MagicMock, patch

        mock_response = MagicMock()
        mock_response.status = 401

        mock_conn = MagicMock()
        mock_conn.getresponse.return_value = mock_response

        with patch("http.client.HTTPSConnection", return_value=mock_conn):
            from services.connectivity_probe_service import _probe_k8s_api
            result = _probe_k8s_api("10.0.0.1", 6443)
            assert result["accessible"] is True
            assert result["status_code"] == 401

    def test_api_connection_error(self):
        from unittest.mock import patch

        with patch("http.client.HTTPSConnection") as mock_cls:
            mock_cls.return_value.request.side_effect = ConnectionRefusedError
            from services.connectivity_probe_service import _probe_k8s_api
            result = _probe_k8s_api("10.0.0.1", 6443)
            assert result["accessible"] is False


# ---------------------------------------------------------------------------
# _probe_cluster_obj — against a REAL model instance
# ---------------------------------------------------------------------------

class TestProbeClusterObj:
    """The probe must run against the KubernetesCluster model as it actually is.

    Every test above builds the diagnostic from plain kwargs, so all of them
    stayed green while the live endpoint returned
    `Probe error: 'KubernetesCluster' object has no attribute
    'ssh_tunnel_enabled'` for every cluster — the probe read a column that the
    SSH-tunnel removal had deleted. A real (unsaved) model instance is what
    catches that class of drift; a MagicMock answers to any attribute and would
    not.
    """

    def _service(self):
        from unittest.mock import MagicMock

        from services.connectivity_probe_service import ConnectivityProbeService

        return ConnectivityProbeService(MagicMock())

    def _cluster(self, api_server: str | None):
        from models import KubernetesCluster

        return KubernetesCluster(id=1, name="infra", context="infra", api_server=api_server)

    def test_probe_real_model_no_api_server(self):
        result = self._service()._probe_cluster_obj(self._cluster(None))
        assert result["status"] == "unknown"
        assert result["cluster_name"] == "infra"

    def test_probe_real_model_unreachable(self):
        from unittest.mock import patch

        with patch(
            "services.connectivity_probe_service._probe_icmp",
            return_value={"reachable": False, "latency_ms": None},
        ), patch(
            "services.connectivity_probe_service._probe_tcp",
            return_value={"open": False, "connect_ms": None},
        ):
            result = self._service()._probe_cluster_obj(self._cluster("https://10.0.0.99:6443"))

        assert result["status"] == "unreachable"
        assert result["api_server"] == "https://10.0.0.99:6443"

    def test_probe_real_model_connected(self):
        from unittest.mock import patch

        with patch(
            "services.connectivity_probe_service._probe_icmp",
            return_value={"reachable": True, "latency_ms": 1.0},
        ), patch(
            "services.connectivity_probe_service._probe_tcp",
            return_value={"open": True, "connect_ms": 2.0},
        ), patch(
            "services.connectivity_probe_service._probe_k8s_api",
            return_value={"accessible": True, "version": "1.31", "status_code": 200},
        ):
            result = self._service()._probe_cluster_obj(self._cluster("https://10.0.0.1:6443"))

        assert result["status"] == "connected"
        assert result["k8s_api"]["version"] == "1.31"
        assert result["tcp"]["port"] == 6443
