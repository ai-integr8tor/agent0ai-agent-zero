"""Regression test for DeferredTask.result() cancellation propagation.

Without the CancelledError handling in result(), cancelling the outer
asyncio task does NOT propagate into the thread-pool worker running
inside _get_result. The worker stays parked in
self._future.result(timeout) until the underlying future finishes
naturally, leaking one worker thread per cancellation. After enough
cancelled dispatches the default ThreadPoolExecutor saturates and new
result() calls block indefinitely.

This test asserts that after the outer awaiter is cancelled, the
underlying concurrent.futures.Future reaches `done()` within a short
bound — meaning the worker has been released, not parked.
"""

from __future__ import annotations

import asyncio
import os
import sys

import pytest

# Make `helpers/` importable when tests are run from the repo root.
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from helpers.defer import DeferredTask


async def _slow_work() -> str:
    # Long enough that the test would never reach this naturally.
    await asyncio.sleep(60)
    return "should-never-return-in-test"


@pytest.mark.asyncio
async def test_result_cancellation_releases_future() -> None:
    """Cancelling result() must cancel the underlying future too.

    Bound: 500 ms after the awaiter is cancelled, the underlying
    self._future should be `done()` (cancelled). Without the fix this
    never happens and the worker thread is leaked.
    """
    task = DeferredTask().start_task(_slow_work)

    # Give the background event loop a moment to schedule _slow_work
    # and the executor a moment to start _get_result.
    await asyncio.sleep(0.05)

    # Start awaiting the result, then cancel that awaiter.
    waiter = asyncio.create_task(task.result(timeout=60.0))
    await asyncio.sleep(0.05)
    waiter.cancel()

    with pytest.raises(asyncio.CancelledError):
        await waiter

    # Poll for the underlying future to become done, up to 500 ms.
    # Without the fix this polling exhausts and the assertion below fails.
    for _ in range(50):
        if task._future is not None and task._future.done():
            break
        await asyncio.sleep(0.01)

    assert task._future is not None, "task._future is None after start_task"
    assert task._future.done(), (
        "Underlying future did not reach done() within 500 ms of "
        "result() cancellation. The thread-pool worker is leaked."
    )
