"""In-process background work.

bnkscope replaced Celery + Redis with this (Phase 4). A local single-user tool
watching a handful of clusters does not need a broker, a result backend, or
worker processes — it needs a way to run a short job off the request thread and
a way to run something periodically.

Two primitives:

  ``submit(fn, *args)``    fire-and-forget on a small thread pool
  ``run_sync(fn, *args)``  run on the pool and wait, with a timeout

Both are deliberately unsupervised: a job that fails logs and is gone. Nothing
here is a durable queue, and nothing should be written assuming it is — if work
must survive a restart, persist it in the database and re-derive it on boot.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from typing import Any, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")

# Small on purpose. These jobs are almost all network-bound calls to a cluster's
# API server; more threads means more concurrent load on the cluster, not more
# throughput here.
_MAX_WORKERS = 4

_executor: ThreadPoolExecutor | None = None


def get_executor() -> ThreadPoolExecutor:
    global _executor
    if _executor is None:
        _executor = ThreadPoolExecutor(max_workers=_MAX_WORKERS, thread_name_prefix="bnkscope-bg")
    return _executor


def _log_failure(name: str, fut: Future) -> None:
    exc = fut.exception()
    if exc is not None:
        logger.warning("background job %s failed: %s", name, exc)


def submit(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Future:
    """Run ``fn`` off the caller's thread. Fire-and-forget.

    Never raises into the caller: a job that fails logs a warning. Use this
    where the old code called ``.delay()``.
    """
    name = getattr(fn, "__name__", repr(fn))
    fut = get_executor().submit(fn, *args, **kwargs)
    fut.add_done_callback(lambda f: _log_failure(name, f))
    return fut


def run_sync(fn: Callable[..., T], *args: Any, timeout: float = 30.0, **kwargs: Any) -> T:
    """Run ``fn`` on the pool and wait for its result.

    Raises ``TimeoutError`` if it does not finish in ``timeout`` seconds, and
    propagates whatever the job raised otherwise. Use this where the old code
    called ``.apply_async(...).get(timeout=...)``.
    """
    fut = get_executor().submit(fn, *args, **kwargs)
    try:
        return fut.result(timeout=timeout)
    except FutureTimeout as exc:
        raise TimeoutError(
            f"background job {getattr(fn, '__name__', fn)} timed out after {timeout}s"
        ) from exc


def shutdown(wait: bool = False) -> None:
    """Stop the pool. Called from the app's lifespan shutdown."""
    global _executor
    if _executor is not None:
        _executor.shutdown(wait=wait, cancel_futures=not wait)
        _executor = None
