"""
Unit tests for services.nico.tunnel — the apiserver port-forward transport.

The apiserver is stood in for: `portforward` is a fake that hands back a pair
of connected sockets, so a real TCP client can talk through the relay and see
its bytes come back. No cluster, no websocket.
"""

import socket
import threading

import pytest

from services.nico.tunnel import TunnelError, forge_tunnel


class _FakeCore:
    """Only the attribute `forge_tunnel` reads off CoreV1Api."""

    def connect_get_namespaced_pod_portforward(self, *_a, **_kw):  # pragma: no cover
        raise AssertionError("called through the fake portforward, never directly")


class _FakeSession:
    """What `kubernetes.stream.portforward` returns: a `.socket(port)` factory."""

    def __init__(self, upstream):
        self._upstream = upstream

    def socket(self, _port):
        return self._upstream


def _echo_portforward(calls):
    """A `portforward` stand-in whose upstream echoes back what it receives."""

    def factory(_api_method, pod, namespace, ports=None):
        calls.append((namespace, pod, ports))
        near, far = socket.socketpair()

        def echo():
            try:
                while True:
                    data = far.recv(65536)
                    if not data:
                        return
                    far.sendall(data)
            except OSError:
                return
            finally:
                far.close()

        threading.Thread(target=echo, daemon=True).start()
        return _FakeSession(near)

    return factory


def _dial(address: str, payload: bytes, expect: int) -> bytes:
    host, _, port = address.rpartition(":")
    with socket.create_connection((host, int(port)), timeout=5) as sock:
        sock.sendall(payload)
        out = b""
        while len(out) < expect:
            chunk = sock.recv(65536)
            if not chunk:
                break
            out += chunk
        return out


class TestForgeTunnel:
    def test_bytes_reach_the_pod_and_come_back(self, monkeypatch):
        calls = []
        monkeypatch.setattr(
            "kubernetes.stream.portforward", _echo_portforward(calls), raising=False
        )
        with forge_tunnel(_FakeCore(), "nico-system", "nico-api-abc", 1079) as address:
            assert address.startswith("127.0.0.1:")
            assert _dial(address, b"hello forge", 11) == b"hello forge"
        assert calls == [("nico-system", "nico-api-abc", "1079")]

    def test_each_connection_gets_its_own_portforward_session(self, monkeypatch):
        """A session carries one stream per port, so a second connection cannot
        share the first — gRPC reconnecting must not hang."""
        calls = []
        monkeypatch.setattr(
            "kubernetes.stream.portforward", _echo_portforward(calls), raising=False
        )
        with forge_tunnel(_FakeCore(), "nico-system", "nico-api-abc", 1079) as address:
            assert _dial(address, b"one", 3) == b"one"
            assert _dial(address, b"two", 3) == b"two"
        assert len(calls) == 2

    def test_the_listener_does_not_outlive_the_block(self, monkeypatch):
        """One short-lived tunnel per fetch — nothing held open between polls."""
        monkeypatch.setattr(
            "kubernetes.stream.portforward", _echo_portforward([]), raising=False
        )
        with forge_tunnel(_FakeCore(), "nico-system", "nico-api-abc", 1079) as address:
            pass
        host, _, port = address.rpartition(":")
        with pytest.raises(OSError):
            socket.create_connection((host, int(port)), timeout=2).close()

    def test_a_denied_portforward_closes_the_connection_not_the_tunnel(
        self, monkeypatch
    ):
        """`pods/portforward` is reached with the `create` verb, so a restricted
        kubeconfig can be refused it. The apiserver is not contacted until a
        connection arrives, so that surfaces here as a dead dial."""

        def refuse(*_a, **_kw):
            raise RuntimeError("pods/portforward is forbidden")

        monkeypatch.setattr("kubernetes.stream.portforward", refuse, raising=False)
        with forge_tunnel(_FakeCore(), "nico-system", "nico-api-abc", 1079) as address:
            # The relay closes with the request still unsent, so the peer sees
            # either a reset or a clean EOF depending on timing. Both say the
            # dial is dead, which is all gRPC needs to report UNAVAILABLE.
            try:
                assert _dial(address, b"anyone home", 1) == b""
            except ConnectionResetError:
                pass

    def test_a_missing_client_library_is_a_tunnel_error(self, monkeypatch):
        """Reported as TunnelError so `fetch` can name the transport that failed
        rather than blaming the inventory."""
        import builtins

        real_import = builtins.__import__

        def no_stream(name, *args, **kwargs):
            if name == "kubernetes.stream":
                raise ImportError("no module named kubernetes.stream")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", no_stream)
        with pytest.raises(TunnelError, match="kubernetes.stream unavailable"):
            with forge_tunnel(_FakeCore(), "nico-system", "nico-api-abc", 1079):
                pass  # pragma: no cover
