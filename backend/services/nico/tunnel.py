"""
Port-forward transport — reaching Forge when only the apiserver is routable.

The addresses a Service advertises are frequently on a subnet bnkscope's host
has no route to: a MetalLB VIP and the node IPs behind a NodePort both live on
the lab underlay, while the kubeconfig points at an apiserver reachable from
the operator's desk. On such a cluster there is exactly one open door, and it
is the one bnkscope already walks through for every other read.

So this dials Forge through the apiserver's ``pods/portforward`` subresource —
the same primitive ``kubectl port-forward`` uses, over the same authenticated
HTTPS connection the kubeconfig already provides. No kubectl binary, no stored
credentials, no jumphost: the kubeconfig-only reachability model
``BNKSCOPE_PLAN.md`` decision 2 settled on, not a return of the SSH tunnels it
deleted.

``pods/portforward`` speaks raw TCP but yields a socket object, not a listening
address, and gRPC needs an address to dial. So a loopback listener sits in
front of it and relays bytes, and [`forge_tunnel`] hands back the
``127.0.0.1:<ephemeral>`` that names it. The listener lives exactly as long as
the ``with`` block — one short-lived tunnel per fetch, nothing held open
between polls.

Note for the read-only posture: ``pods/portforward`` is reached with the
``create`` verb, so a restricted kubeconfig can be denied it. It creates no
Kubernetes object and mutates nothing — the verb names opening a connection.
"""

from __future__ import annotations

import logging
import socket
import threading
from collections.abc import Iterator
from contextlib import contextmanager

logger = logging.getLogger(__name__)

# Bytes moved per relay hop. One gRPC message is usually far smaller; this only
# bounds a single read.
_CHUNK = 65536

# Backlog on the loopback listener. HTTP/2 multiplexes onto one connection, so
# in practice one is used — but a reconnect must not be refused.
_BACKLOG = 8

# How often the accept loop checks whether the block has exited. Small enough
# that teardown is not perceptible, large enough to cost nothing while idle.
_POLL = 0.1


class TunnelError(RuntimeError):
    """The port-forward could not be opened."""


@contextmanager
def forge_tunnel(core_api, namespace: str, pod: str, port: int) -> Iterator[str]:
    """Expose ``pod:port`` as a loopback address for the life of the block.

    Yields ``"127.0.0.1:<ephemeral>"``. Raises [`TunnelError`] if the listener
    cannot be opened; a *denied* portforward surfaces later, on the first dial,
    because the apiserver is not contacted until a connection arrives.
    """
    try:
        from kubernetes.stream import portforward
    except ImportError as exc:  # pragma: no cover — the client is a hard dep
        raise TunnelError(f"kubernetes.stream unavailable: {exc}") from exc

    listener = socket.socket()
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        listener.bind(("127.0.0.1", 0))
        listener.listen(_BACKLOG)
    except OSError as exc:
        listener.close()
        raise TunnelError(f"could not open a loopback listener: {exc}") from exc

    local_port = listener.getsockname()[1]
    stop = threading.Event()

    # Poll rather than block forever in accept(): closing a socket from another
    # thread does not abort a blocked accept() on Linux, and while that syscall
    # is in flight the kernel keeps the listener alive — the port would go on
    # accepting connections after the block exited. A timeout lets `serve` see
    # `stop` and leave accept() on its own, so the close below is the real end.
    listener.settimeout(_POLL)

    def serve() -> None:
        while not stop.is_set():
            try:
                conn, _ = listener.accept()
            except TimeoutError:
                continue
            except OSError:
                return  # listener closed — the block exited
            # One portforward session per connection: a session carries a
            # single stream per port, so a second connection needs its own.
            threading.Thread(
                target=_bridge,
                args=(portforward, core_api, namespace, pod, port, conn),
                daemon=True,
            ).start()

    accepter = threading.Thread(target=serve, daemon=True)
    accepter.start()
    logger.debug(
        "Forge tunnel 127.0.0.1:%d -> %s/%s:%d", local_port, namespace, pod, port
    )
    try:
        yield f"127.0.0.1:{local_port}"
    finally:
        stop.set()
        # Join before closing: once `serve` has left accept() nothing holds the
        # listener open, so close() actually retires the port.
        accepter.join(timeout=_POLL * 10)
        try:
            listener.close()
        except OSError:
            pass


def _bridge(portforward, core_api, namespace: str, pod: str, port: int, conn) -> None:
    """Pump one accepted connection through a fresh portforward session."""
    try:
        session = portforward(
            core_api.connect_get_namespaced_pod_portforward,
            pod,
            namespace,
            ports=str(port),
        )
        upstream = session.socket(port)
    except Exception as exc:  # noqa: BLE001 — a denied or dead portforward
        logger.info("Forge tunnel to %s/%s:%d failed: %s", namespace, pod, port, exc)
        _close(conn)
        return

    # Both directions run to completion; closing either end ends both pumps.
    outbound = threading.Thread(
        target=_pump, args=(conn, upstream), daemon=True
    )
    outbound.start()
    _pump(upstream, conn)
    _close(conn)
    _close(upstream)


def _pump(src, dst) -> None:
    """Copy until either side is done. Never raises — both ends may vanish."""
    try:
        while True:
            chunk = src.recv(_CHUNK)
            if not chunk:
                return
            dst.sendall(chunk)
    except Exception:  # noqa: BLE001 — a half-closed relay is the normal exit
        return


def _close(sock) -> None:
    try:
        sock.close()
    except Exception:  # noqa: BLE001
        pass
