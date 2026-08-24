"""The in-process job primitives that replaced Celery in Phase 4.

What matters here is the contract the call sites depend on: ``submit`` never
raises into the caller (it stands in for ``.delay()``, which didn't either), and
``run_sync`` raises a plain ``TimeoutError`` rather than the concurrent.futures
one (it stands in for ``.apply_async().get(timeout=...)``).
"""

import logging
import threading
import time

import pytest

from core import background


@pytest.fixture(autouse=True)
def _fresh_pool():
    """Each test gets its own executor; a shutdown in one must not leak."""
    background.shutdown(wait=True)
    yield
    background.shutdown(wait=True)


class TestSubmit:
    def test_runs_the_function_off_the_calling_thread(self):
        seen: list[str] = []
        done = threading.Event()

        def job():
            seen.append(threading.current_thread().name)
            done.set()

        background.submit(job)
        assert done.wait(timeout=5)
        assert seen[0].startswith("bnkscope-bg")
        assert seen[0] != threading.current_thread().name

    def test_passes_args_and_kwargs_through(self):
        fut = background.submit(lambda a, b, c=0: a + b + c, 1, 2, c=3)
        assert fut.result(timeout=5) == 6

    def test_a_failing_job_does_not_raise_into_the_caller(self):
        def boom():
            raise RuntimeError("job exploded")

        fut = background.submit(boom)  # must not raise here
        # The failure is still observable on the future itself.
        assert isinstance(fut.exception(timeout=5), RuntimeError)

    def test_a_failing_job_is_logged(self, caplog):
        def boom():
            raise RuntimeError("job exploded")

        with caplog.at_level(logging.WARNING, logger="core.background"):
            background.submit(boom).exception(timeout=5)
            # The done-callback runs just after the future completes.
            for _ in range(50):
                if any("background job boom failed" in r.getMessage() for r in caplog.records):
                    break
                time.sleep(0.01)

        messages = [r.getMessage() for r in caplog.records]
        assert any("background job boom failed" in m and "job exploded" in m for m in messages)

    def test_one_failure_does_not_poison_the_pool(self):
        def boom():
            raise RuntimeError("job exploded")

        background.submit(boom).exception(timeout=5)
        assert background.submit(lambda: "still here").result(timeout=5) == "still here"


class TestRunSync:
    def test_returns_the_job_result(self):
        assert background.run_sync(lambda x: x * 2, 21) == 42

    def test_propagates_the_job_exception(self):
        def boom():
            raise ValueError("bad input")

        with pytest.raises(ValueError, match="bad input"):
            background.run_sync(boom)

    def test_raises_builtin_timeout_error(self):
        """Callers catch ``TimeoutError``; the futures one is not a subclass of it."""
        with pytest.raises(TimeoutError) as exc:
            background.run_sync(time.sleep, 5, timeout=0.05)
        assert "timed out after 0.05s" in str(exc.value)

    def test_a_timeout_leaves_the_pool_usable(self):
        with pytest.raises(TimeoutError):
            background.run_sync(time.sleep, 0.3, timeout=0.05)
        assert background.run_sync(lambda: "ok", timeout=5) == "ok"


class TestExecutorLifecycle:
    def test_the_executor_is_reused_across_calls(self):
        first = background.get_executor()
        background.submit(lambda: None).result(timeout=5)
        assert background.get_executor() is first

    def test_shutdown_then_submit_builds_a_new_pool(self):
        first = background.get_executor()
        background.shutdown(wait=True)
        assert background.submit(lambda: "ok").result(timeout=5) == "ok"
        assert background.get_executor() is not first

    def test_shutdown_is_idempotent(self):
        background.get_executor()
        background.shutdown(wait=True)
        background.shutdown(wait=True)  # must not raise

    def test_shutdown_waits_for_running_work_when_asked(self):
        finished = threading.Event()
        background.submit(lambda: (time.sleep(0.1), finished.set()))
        background.shutdown(wait=True)
        assert finished.is_set()

    def test_concurrency_is_capped_at_max_workers(self):
        """More threads would mean more concurrent load on a cluster, not more throughput."""
        lock = threading.Lock()
        live = 0
        peak = 0
        release = threading.Event()

        def job():
            nonlocal live, peak
            with lock:
                live += 1
                peak = max(peak, live)
            release.wait(timeout=5)
            with lock:
                live -= 1

        futures = [background.submit(job) for _ in range(background._MAX_WORKERS * 3)]
        time.sleep(0.2)  # let the pool saturate
        with lock:
            observed = peak
        release.set()
        for f in futures:
            f.result(timeout=5)

        assert observed == background._MAX_WORKERS
