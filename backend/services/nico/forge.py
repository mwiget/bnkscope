"""
Forge gRPC client — NICo's API, reached without a vendored proto.

NICo's ``forge.Forge`` service has ~460 methods and its `.proto` ships in
NVIDIA's infra-controller repo, not here. Vendoring generated stubs would tie
bnkscope to one NICo build and go stale the first time the lab moves forward.

So this reads the schema off the server itself: gRPC **server reflection**
returns the FileDescriptorProtos, they go into a private DescriptorPool, and
request/response classes are built from that at call time. Requests are plain
dicts in, plain dicts out — the same JSON shape ``grpcurl`` prints, which is
what ``tmmlbctl`` uses and what the frontend expects.

The pool is per-client and private, so nothing here can collide with the
protobuf descriptors any other part of the backend registers globally.
"""

from __future__ import annotations

import logging
import socket
from typing import Any

from services.nico.constants import FORGE_TIMEOUT, REACH_TIMEOUT

logger = logging.getLogger(__name__)

FORGE_SERVICE = "forge.Forge"


class ForgeError(RuntimeError):
    """A Forge call, or the session that carries it, failed."""


def tcp_reachable(host: str, port: int, timeout: float = REACH_TIMEOUT) -> bool:
    """Can we open a TCP connection to host:port inside `timeout` seconds?

    Screens endpoint candidates before paying for an mTLS handshake: a Service
    can advertise an address on a subnet this host has no route to, and that
    black-holes rather than refuses.
    """
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


class ForgeClient:
    """A live mTLS session to nico-api's Forge API.

    Use as a context manager; the channel is closed on exit.
    """

    def __init__(
        self,
        address: str,
        server_name: str,
        ca: bytes,
        cert: bytes,
        key: bytes,
        timeout: float = FORGE_TIMEOUT,
    ):
        import grpc

        self.address = address
        self.timeout = timeout
        creds = grpc.ssl_channel_credentials(
            root_certificates=ca, private_key=key, certificate_chain=cert
        )
        # The cert is minted for the in-cluster Service name; we dial a NodePort
        # or LoadBalancer address. Override the TLS name, not the dial target.
        self._channel = grpc.secure_channel(
            address,
            creds,
            options=[("grpc.ssl_target_name_override", server_name)],
        )
        self._pool = None
        self._service = None

    def __enter__(self) -> ForgeClient:
        return self

    def __exit__(self, *_exc) -> None:
        self.close()

    def close(self) -> None:
        try:
            self._channel.close()
        except Exception:  # noqa: BLE001 — closing a dead channel must not raise
            pass

    # ── schema ────────────────────────────────────────────────────────────

    def _load_schema(self) -> None:
        """Pull forge.Forge's descriptors over reflection into a private pool.

        Walks the dependency closure: the first response carries the file that
        declares the service, and each file names the ones it imports. On this
        lab that settles at 13 files in well under a second, so it is done per
        session rather than cached — a cache would have to be invalidated on
        every NICo upgrade to buy that back.
        """
        from google.protobuf import descriptor_pb2, descriptor_pool
        from grpc_reflection.v1alpha import reflection_pb2, reflection_pb2_grpc

        stub = reflection_pb2_grpc.ServerReflectionStub(self._channel)

        def ask(requests):
            out = []
            for resp in stub.ServerReflectionInfo(iter(requests), timeout=self.timeout):
                if resp.HasField("error_response"):
                    raise ForgeError(
                        f"reflection: {resp.error_response.error_message}"
                    )
                out.extend(resp.file_descriptor_response.file_descriptor_proto)
            return out

        files: dict[str, Any] = {}
        pending = [
            reflection_pb2.ServerReflectionRequest(file_containing_symbol=FORGE_SERVICE)
        ]
        while pending:
            for raw in ask(pending):
                fdp = descriptor_pb2.FileDescriptorProto()
                fdp.ParseFromString(raw)
                files[fdp.name] = fdp
            missing = [
                dep
                for f in files.values()
                for dep in f.dependency
                if dep not in files
            ]
            pending = [
                reflection_pb2.ServerReflectionRequest(file_by_filename=name)
                for name in dict.fromkeys(missing)
            ]

        pool = descriptor_pool.DescriptorPool()
        added: set[str] = set()

        def add(name: str) -> None:
            # Dependencies must be in the pool before the file that imports
            # them, and the reflection response has no guaranteed order.
            if name in added or name not in files:
                return
            added.add(name)
            for dep in files[name].dependency:
                add(dep)
            pool.Add(files[name])

        for name in list(files):
            add(name)

        self._pool = pool
        self._service = pool.FindServiceByName(FORGE_SERVICE)

    # ── calls ─────────────────────────────────────────────────────────────

    def call(self, method: str, body: dict | None = None) -> dict:
        """Invoke one unary Forge RPC. Dict in, dict (camelCase JSON) out."""
        from google.protobuf import json_format, message_factory

        if self._service is None:
            self._load_schema()

        desc = self._service.FindMethodByName(method)
        if desc is None:
            raise ForgeError(f"no such Forge method: {method}")
        request_cls = message_factory.GetMessageClass(desc.input_type)
        response_cls = message_factory.GetMessageClass(desc.output_type)

        try:
            request = json_format.ParseDict(body or {}, request_cls())
        except json_format.ParseError as exc:
            raise ForgeError(f"{method}: bad request body: {exc}") from exc

        callable_ = self._channel.unary_unary(
            f"/{FORGE_SERVICE}/{method}",
            request_serializer=request_cls.SerializeToString,
            response_deserializer=response_cls.FromString,
        )
        try:
            reply = callable_(request, timeout=self.timeout)
        except Exception as exc:  # noqa: BLE001 — grpc.RpcError and friends
            raise ForgeError(f"{method}: {_grpc_reason(exc)}") from exc
        return json_format.MessageToDict(reply)

    def try_call(self, method: str, body: dict | None = None) -> dict:
        """Like [`call`], but a failure is an empty result rather than a raise.

        Most of the inventory is optional: this lab drives DPU lifecycle through
        DPF, so NICo's machine/switch/rack tables are legitimately empty and some
        of their RPCs are not wired up at all. One of those must not blank the
        whole tab.
        """
        try:
            return self.call(method, body)
        except Exception as exc:  # noqa: BLE001 — best-effort by definition
            logger.debug("Forge %s failed: %s", method, exc)
            return {}


def _grpc_reason(exc: Exception) -> str:
    """The useful half of a grpc.RpcError — its status detail, not its repr."""
    details = getattr(exc, "details", None)
    if callable(details):
        try:
            text = details()
            if text:
                return str(text)
        except Exception:  # noqa: BLE001
            pass
    return str(exc)
