"""The in-process cache that replaced Redis in Phase 4.

The public surface did not change when the storage did, so these tests are
written against that surface. The two behaviours worth pinning down are the
ones Redis used to provide for free: TTL expiry, and a bound on how large the
store can grow.
"""

import asyncio
import time

import pytest

from core import cache as cache_module
from core.cache import CacheService, cached, invalidate_cache


@pytest.fixture()
def svc():
    return CacheService()


@pytest.fixture(autouse=True)
def _clean_global_cache():
    cache_module.cache.clear_all()
    yield
    cache_module.cache.clear_all()


class TestGetSet:
    def test_round_trips_a_value(self, svc):
        svc.set("k", {"a": 1})
        assert svc.get("k") == {"a": 1}

    def test_missing_key_is_none(self, svc):
        assert svc.get("nope") is None

    def test_set_overwrites(self, svc):
        svc.set("k", "first")
        svc.set("k", "second")
        assert svc.get("k") == "second"

    def test_falsey_values_survive_the_round_trip(self, svc):
        """``get`` returns None for a miss, so a cached 0/""/[] must not read as one."""
        svc.set("zero", 0)
        svc.set("empty", [])
        assert svc.get("zero") == 0
        assert svc.get("empty") == []


class TestTTL:
    def test_entry_expires(self, svc):
        svc.set("k", "v", ttl_seconds=0.05)
        assert svc.get("k") == "v"
        time.sleep(0.1)
        assert svc.get("k") is None

    def test_an_expired_entry_is_dropped_not_just_hidden(self, svc):
        svc.set("k", "v", ttl_seconds=0.05)
        time.sleep(0.1)
        svc.get("k")
        assert "k" not in svc._store

    def test_re_setting_extends_the_life(self, svc):
        svc.set("k", "v", ttl_seconds=0.05)
        svc.set("k", "v", ttl_seconds=5)
        time.sleep(0.1)
        assert svc.get("k") == "v"


class TestDelete:
    def test_delete_reports_whether_it_removed_something(self, svc):
        svc.set("k", "v")
        assert svc.delete("k") is True
        assert svc.delete("k") is False

    def test_delete_pattern_matches_a_glob(self, svc):
        svc.set("cluster:1:nodes", "a")
        svc.set("cluster:2:nodes", "b")
        svc.set("settings:theme", "c")

        assert svc.delete_pattern("cluster:*") == 2
        assert svc.get("cluster:1:nodes") is None
        assert svc.get("settings:theme") == "c"

    def test_delete_pattern_matching_nothing_returns_zero(self, svc):
        svc.set("k", "v")
        assert svc.delete_pattern("other:*") == 0
        assert svc.get("k") == "v"

    def test_clear_all(self, svc):
        svc.set("a", 1)
        svc.set("b", 2)
        svc.clear_all()
        assert svc.get("a") is None
        assert svc.get("b") is None

    def test_invalidate_cache_helper_hits_the_module_singleton(self):
        cache_module.cache.set("modules:x", 1)
        cache_module.cache.set("modules:y", 2)
        assert invalidate_cache("modules:*") == 2
        assert cache_module.cache.get("modules:x") is None


class TestEviction:
    def test_the_store_is_bounded(self, svc, monkeypatch):
        """Redis had maxmemory; this has _MAX_ENTRIES. Something must bound it."""
        monkeypatch.setattr(cache_module, "_MAX_ENTRIES", 10)
        for i in range(50):
            svc.set(f"k{i}", i)
        assert len(svc._store) == 10

    def test_the_oldest_entries_go_first(self, svc, monkeypatch):
        monkeypatch.setattr(cache_module, "_MAX_ENTRIES", 3)
        svc.set("a", 1)
        svc.set("b", 2)
        svc.set("c", 3)
        svc.set("d", 4)
        assert svc.get("a") is None
        assert svc.get("d") == 4

    def test_a_read_keeps_an_entry_alive(self, svc, monkeypatch):
        monkeypatch.setattr(cache_module, "_MAX_ENTRIES", 3)
        svc.set("a", 1)
        svc.set("b", 2)
        svc.set("c", 3)
        svc.get("a")  # refresh 'a' — 'b' is now the oldest
        svc.set("d", 4)
        assert svc.get("a") == 1
        assert svc.get("b") is None


class TestCachedDecorator:
    def test_sync_function_is_called_once(self):
        calls = []

        @cached("test", ttl_seconds=60)
        def expensive(x):
            calls.append(x)
            return x * 2

        assert expensive(21) == 42
        assert expensive(21) == 42
        assert calls == [21]

    def test_different_args_are_different_keys(self):
        calls = []

        @cached("test", ttl_seconds=60)
        def expensive(x):
            calls.append(x)
            return x * 2

        expensive(1)
        expensive(2)
        assert calls == [1, 2]

    @pytest.mark.asyncio
    async def test_async_function_is_called_once(self):
        calls = []

        @cached("test_async", ttl_seconds=60)
        async def expensive(x):
            calls.append(x)
            await asyncio.sleep(0)
            return x * 2

        assert await expensive(21) == 42
        assert await expensive(21) == 42
        assert calls == [21]

    def test_an_explicit_key_function_is_used(self):
        @cached("modules", ttl_seconds=60, key=lambda project_id, **kw: f"project:{project_id}")
        def get_modules(project_id, db=None):
            return ["mod"]

        get_modules(7, db=object())
        assert cache_module.cache.get("modules:get_modules:project:7") == ["mod"]

    def test_unhashable_args_are_left_out_of_the_default_key(self):
        """A SQLAlchemy session as an argument must not end up in the key."""
        calls = []

        @cached("test", ttl_seconds=60)
        def with_session(cluster_id, db):
            calls.append(cluster_id)
            return "result"

        with_session(1, db=object())
        with_session(1, db=object())  # a different session object
        assert calls == [1]

    def test_the_ttl_is_honoured_through_the_decorator(self):
        calls = []

        @cached("test", ttl_seconds=0.05)
        def expensive():
            calls.append(1)
            return "v"

        expensive()
        time.sleep(0.1)
        expensive()
        assert len(calls) == 2
