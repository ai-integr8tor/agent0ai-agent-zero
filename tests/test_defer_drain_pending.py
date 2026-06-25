"""Regression tests for ``helpers/defer.py`` task-drain on shutdown.

The container logs used to emit lines like::

    Task was destroyed but it is pending!
    task:  wait_for=>

whenever a coroutine scheduled with ``asyncio.create_task`` (e.g. the memory
recall task in ``_50_recall_memories.py``) was still pending while the
``EventLoopThread`` was being torn down. The drain helper used to schedule
itself with ``asyncio.run_coroutine_threadsafe`` and then list itself in the
pending set, which cancelled the drain before it could await the actual
target tasks.

These tests exercise the public ``EventLoopThread.terminate`` flow with a
pending ``asyncio.wait_for`` task and assert the loop shuts down cleanly.

Note: asyncio surfaces the "Task was destroyed but it is pending!" warning
through its own ``logger.warning`` call, NOT through the standard
``warnings`` module. We therefore capture stderr (where the asyncio logger
writes by default) instead of relying on ``pytest.warns``.
"""

from __future__ import annotations

import asyncio
import contextlib
import io
import logging
import sys
import time
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from helpers.defer import EventLoopThread  # noqa: E402


DESTROYED_PENDING_MARKER = "Task was destroyed but it is pending"


@contextlib.contextmanager
def _capture_asyncio_warnings():
    """Capture stderr writes that originate from the asyncio logger."""

    buf = io.StringIO()
    handler = logging.StreamHandler(buf)
    handler.setLevel(logging.WARNING)
    handler.setFormatter(logging.Formatter("%(message)s"))

    asyncio_logger = logging.getLogger("asyncio")
    original_level = asyncio_logger.level
    asyncio_logger.setLevel(logging.WARNING)
    asyncio_logger.addHandler(handler)
    try:
        yield buf
    finally:
        asyncio_logger.removeHandler(handler)
        asyncio_logger.setLevel(original_level)


def _has_destroyed_pending_warning(buf: io.StringIO) -> bool:
    return DESTROYED_PENDING_MARKER in buf.getvalue()


@pytest.fixture
def fresh_event_loop_thread():
    """Yield a fresh ``EventLoopThread`` and tear it down afterwards.

    ``EventLoopThread`` is a process-wide singleton keyed by ``thread_name``,
    so each test uses a unique name to avoid cross-test pollution.
    """

    name = f"DeferDrainTest-{time.time_ns()}"
    elt = EventLoopThread(thread_name=name)
    yield elt
    try:
        if elt.loop is not None and not elt.loop.is_closed():
            elt.terminate()
    except Exception:
        pass


def test_terminate_cancels_pending_wait_for_task(fresh_event_loop_thread):
    """``asyncio.wait_for`` task left pending after the parent returns.

    This mirrors the recall-memories task: ``asyncio.create_task`` is
    scheduled from inside the agent's monologue, then the monologue returns
    without awaiting it. When the agent is killed the drain must cancel it
    instead of letting asyncio emit "Task was destroyed but it is pending!".
    """

    async def slow():
        await asyncio.sleep(60)

    async def main_coro():
        # Create but DO NOT await. Same pattern as the recall extension.
        asyncio.create_task(asyncio.wait_for(slow(), timeout=30))
        await asyncio.sleep(0.05)  # let the inner task actually start

    elt = fresh_event_loop_thread
    elt.run_coroutine(main_coro()).result()

    with _capture_asyncio_warnings() as buf:
        elt.terminate()

    assert not _has_destroyed_pending_warning(buf), (
        "Pending wait_for task should be drained on terminate, "
        f"but asyncio emitted:\n{buf.getvalue()}"
    )


def test_terminate_handles_many_pending_tasks(fresh_event_loop_thread):
    """Multiple ``create_task`` calls should all be drained in one pass."""

    async def slow():
        await asyncio.sleep(60)

    async def main_coro():
        for _ in range(5):
            asyncio.create_task(asyncio.wait_for(slow(), timeout=30))
        await asyncio.sleep(0.05)

    elt = fresh_event_loop_thread
    elt.run_coroutine(main_coro()).result()

    with _capture_asyncio_warnings() as buf:
        elt.terminate()

    assert not _has_destroyed_pending_warning(buf), (
        "All pending tasks should be cancelled, "
        f"but asyncio emitted:\n{buf.getvalue()}"
    )


def test_terminate_with_no_pending_tasks_is_clean(fresh_event_loop_thread):
    """No pending tasks -> no warnings, drain is a no-op."""

    async def main_coro():
        await asyncio.sleep(0.05)

    elt = fresh_event_loop_thread
    elt.run_coroutine(main_coro()).result()

    with _capture_asyncio_warnings() as buf:
        elt.terminate()

    assert not _has_destroyed_pending_warning(buf)