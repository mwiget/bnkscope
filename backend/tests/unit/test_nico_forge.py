"""
Unit tests for services.nico.forge — schema caching and fail-once semantics.

No gRPC: `ForgeClient` is built without touching `__init__` (which opens a
channel), and reflection is stood in for by a fake `_reflect_pool`. What is
under test is the bookkeeping around the walk, not the walk itself.
"""

import pytest

from core.cache import cache
from services.nico.forge import FORGE_SERVICE, ForgeClient, ForgeError


class FakePool:
    """Stands in for a DescriptorPool: only the service lookup is exercised."""

    def __init__(self, tag="pool"):
        self.tag = tag
        self.lookups = 0

    def FindServiceByName(self, name):  # noqa: N802 — protobuf's spelling
        assert name == FORGE_SERVICE
        self.lookups += 1
        return f"service-of-{self.tag}"


def _client(schema_key=None, pool=None, fail=None):
    """A ForgeClient with its channel-opening __init__ bypassed."""
    client = ForgeClient.__new__(ForgeClient)
    client.address = "127.0.0.1:1079"
    client.timeout = 5.0
    client.schema_key = schema_key
    client._channel = None
    client._pool = None
    client._service = None
    client._schema_error = None
    client.walks = 0

    def reflect():
        client.walks += 1
        if fail:
            raise fail
        return pool or FakePool()

    client._reflect_pool = reflect
    return client


@pytest.fixture(autouse=True)
def _clean_cache():
    cache.clear_all()
    yield
    cache.clear_all()


class TestSchemaCache:
    def test_a_second_session_on_the_same_build_skips_the_walk(self):
        """The walk is ~13s over a VPN and was re-paid on every 30s poll."""
        first = _client(schema_key="sha256:abc")
        first._ensure_schema()
        assert first.walks == 1

        second = _client(schema_key="sha256:abc")
        second._ensure_schema()
        assert second.walks == 0
        assert second._service == first._service

    def test_a_new_build_re_walks(self):
        """The digest changes when and only when the schema can have changed —
        that is the whole reason it is the key."""
        _client(schema_key="sha256:old")._ensure_schema()
        upgraded = _client(schema_key="sha256:new")
        upgraded._ensure_schema()
        assert upgraded.walks == 1

    def test_without_a_key_nothing_is_cached(self):
        """An unpinnable server is walked every time rather than risking a
        stale schema — a mutable tag is not an identity."""
        _client()._ensure_schema()
        second = _client()
        second._ensure_schema()
        assert second.walks == 1

    def test_a_cached_schema_is_not_re_resolved_within_a_session(self):
        client = _client(schema_key="sha256:abc")
        client._ensure_schema()
        client._ensure_schema()
        assert client.walks == 1


class TestFailOnce:
    def test_a_failed_walk_is_not_retried(self):
        """Retrying per RPC turned one timeout into ~15, and reported the
        result as an empty inventory rather than as a failure."""
        client = _client(fail=ForgeError("deadline exceeded"))
        for _ in range(5):
            with pytest.raises(ForgeError, match="deadline exceeded"):
                client._ensure_schema()
        assert client.walks == 1

    def test_a_non_forge_failure_is_wrapped_not_leaked(self):
        client = _client(fail=RuntimeError("connection reset"))
        with pytest.raises(ForgeError, match="schema: connection reset"):
            client._ensure_schema()

    def test_a_failure_is_not_cached_across_sessions(self):
        """A transient timeout must not poison the next poll — only the walk's
        *success* is shared."""
        _client(schema_key="sha256:abc", fail=ForgeError("timeout"))
        client = _client(schema_key="sha256:abc", fail=ForgeError("timeout"))
        with pytest.raises(ForgeError):
            client._ensure_schema()

        recovered = _client(schema_key="sha256:abc")
        recovered._ensure_schema()
        assert recovered.walks == 1
        assert recovered._service == "service-of-pool"

    def test_a_method_absent_from_this_build_is_named_as_such(self):
        """protobuf raises KeyError rather than returning None, so the guard
        that was there never fired. Vanilla NICo has no LoadBalancerService
        RPCs at all, which is a fact about the build, not a transport error."""

        class NoSuchMethod:
            def FindMethodByName(self, name):  # noqa: N802 — protobuf's spelling
                raise KeyError(f"Couldn't find method {name}")

        client = _client()
        client._service = NoSuchMethod()
        with pytest.raises(ForgeError, match="no such Forge method: SearchLoadBalancerServices"):
            client.call("SearchLoadBalancerServices")

    def test_try_call_still_swallows_a_dead_schema(self):
        """Most of the inventory is optional; one unreadable section must not
        blank the tab."""
        client = _client(fail=ForgeError("deadline exceeded"))
        assert client.try_call("FindVpcIds") == {}
        assert client.walks == 1
