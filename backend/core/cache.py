"""In-process TTL cache.

Redis went with Celery in bnkscope Phase 4. A single-process, single-user tool
does not need a shared cache server — it needs the API not to re-scrape a
cluster on every render. This is that, and nothing more.

Consequences worth knowing, since they differ from Redis:
  - the cache is per-process and dies with it (fine: nothing here is truth)
  - it is bounded by ``_MAX_ENTRIES`` and evicts the oldest entries, so a
    pathological key space cannot grow without limit
  - values are stored by reference, not serialized, so **callers must not
    mutate what they get back**

The public surface (``cache.get/set/delete/delete_pattern/clear_all`` and the
``@cached`` decorator) is unchanged, so call sites did not move.
"""

import fnmatch
import logging
import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from functools import wraps
from typing import Any

logger = logging.getLogger(__name__)

# Enough for the scan/health/metrics results this actually holds; the cap only
# exists so a bug in key construction cannot leak memory indefinitely.
_MAX_ENTRIES = 2048


class CacheService:
    """Thread-safe in-process cache with per-entry TTL and LRU-ish eviction."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._store: OrderedDict[str, tuple[float, Any]] = OrderedDict()

    def get(self, key: str) -> Any | None:
        now = time.monotonic()
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            expires_at, value = entry
            if expires_at <= now:
                del self._store[key]
                return None
            self._store.move_to_end(key)
            return value

    def set(self, key: str, value: Any, ttl_seconds: int = 300) -> bool:
        with self._lock:
            self._store[key] = (time.monotonic() + ttl_seconds, value)
            self._store.move_to_end(key)
            while len(self._store) > _MAX_ENTRIES:
                self._store.popitem(last=False)
        return True

    def delete(self, key: str) -> bool:
        with self._lock:
            return self._store.pop(key, None) is not None

    def delete_pattern(self, pattern: str) -> int:
        """Delete every key matching a glob pattern (e.g. ``"cluster:*"``)."""
        with self._lock:
            doomed = [k for k in self._store if fnmatch.fnmatchcase(k, pattern)]
            for k in doomed:
                del self._store[k]
        return len(doomed)

    def clear_all(self) -> bool:
        with self._lock:
            self._store.clear()
        return True


cache = CacheService()


def _build_cache_key(key_prefix: str, func_name: str, args: tuple[Any, ...], kwargs: dict[str, Any], key_fn: Callable[..., str] | None = None) -> str:
    """
    Build a deterministic cache key.

    If `key_fn` is provided, it is called with (*args, **kwargs) minus any
    'self' first argument; it must return a string suffix.

    Otherwise a best-effort key is built by filtering out non-hashable objects
    (like SQLAlchemy sessions) and sorting kwargs for determinism.
    """
    if key_fn is not None:
        # Skip 'self' if present (bound method)
        clean_args = args[1:] if args and hasattr(args[0], '__dict__') else args
        suffix = key_fn(*clean_args, **{k: v for k, v in kwargs.items() if k not in ('db', 'session')})
        return f"{key_prefix}:{func_name}:{suffix}"

    base = f"{key_prefix}:{func_name}"

    # Filter args: keep only simple hashable types (int, str, float, bool, None)
    filtered_args = [str(arg) for arg in args if isinstance(arg, (int, str, float, bool, type(None)))]
    if filtered_args:
        base += f":{':'.join(filtered_args)}"

    # Filter kwargs: skip db/session, sort for determinism
    filtered_kwargs = {k: v for k, v in kwargs.items() if k not in ('db', 'session')}
    if filtered_kwargs:
        base += f":{':'.join(f'{k}={v}' for k, v in sorted(filtered_kwargs.items()))}"

    return base


def cached(key_prefix: str, ttl_seconds: int = 300, key: Callable[..., str] | None = None) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """
    Decorator for caching function results.

    Usage:
        @cached("module_library", ttl_seconds=900)
        def get_modules():
            return expensive_query()

        # Explicit key function for safer cache keys:
        @cached("modules", key=lambda project_id, **kw: f"project:{project_id}")
        def get_modules(project_id: int, db: Session):
            ...

    Args:
        key_prefix: Prefix for cache key (function args will be appended)
        ttl_seconds: Time to live in seconds (default: 5 minutes)
        key: Optional callable(*args, **kwargs) -> str for explicit cache key suffix.
             Receives the function's args/kwargs minus 'self' and 'db'.
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            cache_key = _build_cache_key(key_prefix, func.__name__, args, kwargs, key)

            cached_result = cache.get(cache_key)
            if cached_result is not None:
                logger.debug(f"Cache HIT: {cache_key}")
                return cached_result

            logger.debug(f"Cache MISS: {cache_key}")
            result = await func(*args, **kwargs)
            cache.set(cache_key, result, ttl_seconds)
            return result

        @wraps(func)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            cache_key = _build_cache_key(key_prefix, func.__name__, args, kwargs, key)

            cached_result = cache.get(cache_key)
            if cached_result is not None:
                logger.debug(f"Cache HIT: {cache_key}")
                return cached_result

            logger.debug(f"Cache MISS: {cache_key}")
            result = func(*args, **kwargs)
            cache.set(cache_key, result, ttl_seconds)
            return result

        # Return appropriate wrapper based on function type
        import asyncio
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        else:
            return sync_wrapper

    return decorator


def invalidate_cache(pattern: str) -> int:
    """
    Helper to invalidate cache for a specific pattern

    Usage:
        invalidate_cache("module_library:*")
        invalidate_cache("projects:*")
    """
    count = cache.delete_pattern(pattern)
    if count > 0:
        logger.info(f"🗑️  Invalidated {count} cache entries: {pattern}")
    return count
