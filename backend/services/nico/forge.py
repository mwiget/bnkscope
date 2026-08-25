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

The pool is private to this module — never protobuf's global default pool — so
nothing here can collide with the descriptors any other part of the backend
registers.

Two things bought the walk down from "every read" to "once per NICo build",
because measured over a VPN through the apiserver tunnel it cost ~13s of a 25s
fetch and was re-paid on every 30s poll:

* **The pool is cached** under the nico-api container's image ID. That is the
  invalidation a cache here needs: the digest changes when and only when the
  schema can have changed, so an upgrade re-walks and nothing else does. No
  key, no caching — an unidentifiable server is walked every time.
* **A failed walk fails the session, once.** Reflection is the expensive part,
  so retrying it per RPC turned one slow timeout into fifteen and left the
  inventory silently empty. The first failure is recorded and re-raised.
"""

from __future__ import annotations

import logging
import socket
from typing import Any

from core.cache import cache
from services.nico.constants import FORGE_TIMEOUT, REACH_TIMEOUT

logger = logging.getLogger(__name__)

FORGE_SERVICE = "forge.Forge"

# A NICo build's descriptors do not change under it, so the only reason this
# expires at all is to bound memory in a process that outlives many upgrades.
_SCHEMA_TTL = 24 * 60 * 60


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
        schema_key: str | None = None,
    ):
        import grpc

        self.address = address
        self.timeout = timeout
        # Identifies the *build* whose schema this session will read — the
        # nico-api image ID. None means "do not cache", which is the safe
        # default for a server we cannot pin to a version.
        self.schema_key = schema_key
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
        # Set once if reflection fails, and re-raised thereafter. See the
        # module docstring on why this is not retried per call.
        self._schema_error: ForgeError | None = None
        # Methods this session's certificate was refused. Recorded because a
        # refusal and an empty result are different answers, and `try_call`
        # returns the same `{}` for both.
        self.denied: set[str] = set()

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

    def _ensure_schema(self) -> None:
        """Make ``self._service`` usable, from cache if we can, once either way.

        Three outcomes, and the middle one is the point: a session that has
        already failed to reflect does not try again. Reflection is the
        expensive half of a Forge read, so retrying it on each of the ~15
        inventory RPCs turned one timeout into a minute of them and reported
        the result as an empty inventory rather than as a failure.
        """
        if self._service is not None:
            return
        if self._schema_error is not None:
            raise self._schema_error

        try:
            if self.schema_key:
                cached_pool = cache.get(f"nico:forge:schema:{self.schema_key}")
                if cached_pool is not None:
                    # Read-only from here: the pool is shared with every other
                    # session on this NICo build.
                    self._pool = cached_pool
                    self._service = cached_pool.FindServiceByName(FORGE_SERVICE)
                    return

            pool = self._reflect_pool()
            self._pool = pool
            self._service = pool.FindServiceByName(FORGE_SERVICE)
            if self.schema_key:
                cache.set(
                    f"nico:forge:schema:{self.schema_key}", pool, ttl_seconds=_SCHEMA_TTL
                )
        except Exception as exc:  # noqa: BLE001 — recorded, then re-raised
            self._schema_error = (
                exc if isinstance(exc, ForgeError) else ForgeError(f"schema: {exc}")
            )
            raise self._schema_error from exc

    def _reflect_pool(self):
        """Pull forge.Forge's descriptors over reflection into a private pool.

        Walks the dependency closure: the first response carries the file that
        declares the service, and each file names the ones it imports. On this
        lab that settles at 13 files — under a second on the LAN, ~13s over a
        VPN through the apiserver tunnel, which is why the result is cached.

        The walk and the build deliberately happen outside any lock: two
        sessions racing on the same key duplicate work but cannot corrupt
        anything, and holding a lock across ~13s of I/O would stall every other
        cluster instead.
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

        logger.debug("Forge schema: %d descriptor files for %s", len(files), self.address)
        return pool

    # ── calls ─────────────────────────────────────────────────────────────

    def call(self, method: str, body: dict | None = None) -> dict:
        """Invoke one unary Forge RPC. Dict in, dict (camelCase JSON) out."""
        from google.protobuf import json_format, message_factory

        self._ensure_schema()

        try:
            desc = self._service.FindMethodByName(method)
        except KeyError as exc:
            # protobuf raises rather than returning None. Worth naming as its
            # own failure: a method absent from this build is a fact about the
            # build (vanilla NICo has no LoadBalancerService RPCs at all), not
            # a transport error.
            raise ForgeError(f"no such Forge method: {method}") from exc
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

        The empty dict it returns is therefore ambiguous by design, which is why
        a refusal is *also* recorded in [`denied`]: a caller that needs to tell
        "nothing there" from "not allowed to look" has [`has_method`] and
        [`denied`] to ask.
        """
        try:
            return self.call(method, body)
        except Exception as exc:  # noqa: BLE001 — best-effort by definition
            if _is_denied(exc):
                self.denied.add(method)
            logger.debug("Forge %s failed: %s", method, exc)
            return {}

    def has_method(self, method: str) -> bool:
        """Does this NICo build declare `method` at all?

        Free once the schema is loaded, and answerable without calling: an RPC
        absent from the descriptors is absent from the build. Vanilla NICo has
        no LoadBalancerService methods whatsoever — that is a fact about the
        build, and reporting it as "zero load balancers" claims something about
        the deployment that was never established.
        """
        self._ensure_schema()
        try:
            self._service.FindMethodByName(method)
            return True
        except KeyError:
            return False


def _is_denied(exc: Exception) -> bool:
    """Was this refused rather than merely failed?

    Forge authorizes per method against the client certificate, so a cert that
    reads VPCs happily can still be refused `GetAllDomains`. Two shapes: a
    proper PERMISSION_DENIED status, and a bare HTTP 403 on the stream, which
    grpc surfaces without a status code.
    """
    code = getattr(exc, "code", None)
    if callable(code):
        try:
            if getattr(code(), "name", "") == "PERMISSION_DENIED":
                return True
        except Exception:  # noqa: BLE001
            pass
    return "403" in _grpc_reason(exc)


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
