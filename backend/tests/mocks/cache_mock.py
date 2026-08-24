"""
Cache mock object for testing.

Provides a mock for:
- CacheService (our cache abstraction layer)

Nothing here talks to a network service.
"""

from unittest.mock import MagicMock


class MockCacheService:
    """
    Mock of core/cache.py CacheService.

    Provides an in-memory cache with the same interface as the real
    CacheService but without Redis dependency.

    Usage:
        with patch("core.cache.cache", MockCacheService()):
            ...
    """

    def __init__(self):
        self._store: dict[str, str] = {}
        self.redis = None  # Match real CacheService interface

    def get(self, key: str) -> str | None:
        return self._store.get(key)

    def set(self, key: str, value: str, ttl: int | None = None) -> bool:
        self._store[key] = value
        return True

    def delete(self, key: str) -> bool:
        if key in self._store:
            del self._store[key]
            return True
        return False

    def delete_pattern(self, pattern: str) -> int:
        """Delete keys matching a glob-like pattern (supports trailing * only)."""
        if pattern.endswith("*"):
            prefix = pattern[:-1]
            keys_to_delete = [k for k in self._store if k.startswith(prefix)]
        else:
            keys_to_delete = [k for k in self._store if k == pattern]

        for key in keys_to_delete:
            del self._store[key]
        return len(keys_to_delete)

    def clear(self):
        """Clear all cached entries."""
        self._store.clear()
