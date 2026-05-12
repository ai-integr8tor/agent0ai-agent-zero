import asyncio
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from helpers import fasta2a_server


class FakeStorage:
    def __init__(self):
        self.updates = []

    async def update_task(self, **kwargs):
        self.updates.append(kwargs)
        return kwargs


class FakeLog:
    def log(self, **kwargs):
        pass


class FakeHistory:
    def __init__(self):
        self.messages = []

    def output(self):
        return list(self.messages)


class FakeAgent:
    def __init__(self):
        self.history = FakeHistory()


class FakeContext:
    removed = []
    reset_count = 0
    latest = None

    def __init__(self, cfg, type):
        self.id = "ctx-test"
        self.log = FakeLog()
        self.agent0 = FakeAgent()
        FakeContext.latest = self

    def reset(self):
        FakeContext.reset_count += 1

    def communicate(self, message):
        raise NotImplementedError

    @staticmethod
    def remove(context_id):
        FakeContext.removed.append(context_id)


class HangingTask:
    async def result(self):
        await asyncio.Event().wait()


class FailingTask:
    async def result(self):
        raise RuntimeError("boom\nwith details")


class CompletedTask:
    async def result(self):
        return "final response"


def _params():
    return {
        "id": "task-123",
        "message": {
            "role": "user",
            "parts": [{"kind": "text", "text": "hello"}],
        },
    }


@pytest.fixture(autouse=True)
def patch_runtime(monkeypatch):
    FakeContext.removed = []
    FakeContext.reset_count = 0
    FakeContext.latest = None
    monkeypatch.delenv(fasta2a_server.A2A_TASK_RESULT_TIMEOUT_ENV, raising=False)
    monkeypatch.setattr(fasta2a_server, "AgentContext", FakeContext)
    monkeypatch.setattr(fasta2a_server, "initialize_agent", lambda: object())
    monkeypatch.setattr(fasta2a_server, "remove_chat", lambda context_id: None)


@pytest.mark.asyncio
async def test_run_task_timeout_marks_task_failed(monkeypatch):
    monkeypatch.setenv(fasta2a_server.A2A_TASK_RESULT_TIMEOUT_ENV, "0.01")
    storage = FakeStorage()
    worker = fasta2a_server.AgentZeroWorker(broker=None, storage=storage)
    monkeypatch.setattr(FakeContext, "communicate", lambda self, message: HangingTask())

    await worker.run_task(_params())

    assert storage.updates[-1]["task_id"] == "task-123"
    assert storage.updates[-1]["state"] == "failed"
    text = storage.updates[-1]["new_messages"][0]["parts"][0]["text"]
    assert "timed out" in text
    assert FakeContext.reset_count == 1
    assert FakeContext.removed == ["ctx-test"]


@pytest.mark.asyncio
async def test_run_task_timeout_after_tool_output_completes_with_artifact(monkeypatch):
    monkeypatch.setenv(fasta2a_server.A2A_TASK_RESULT_TIMEOUT_ENV, "0.01")
    storage = FakeStorage()
    worker = fasta2a_server.AgentZeroWorker(broker=None, storage=storage)

    def communicate(self, message):
        self.agent0.history.messages.append({
            "ai": False,
            "content": {
                "tool_name": "code_execution_tool",
                "tool_result": "connected\n",
            },
        })
        return HangingTask()

    monkeypatch.setattr(FakeContext, "communicate", communicate)

    await worker.run_task(_params())

    assert storage.updates[-1]["task_id"] == "task-123"
    assert storage.updates[-1]["state"] == "completed"
    artifact = storage.updates[-1]["new_artifacts"][0]
    assert artifact["name"] == "captured_tool_output"
    assert artifact["metadata"]["tool_name"] == "code_execution_tool"
    assert artifact["parts"] == [{"kind": "text", "text": "connected"}]
    assert "new_messages" not in storage.updates[-1]
    assert FakeContext.reset_count == 1
    assert FakeContext.removed == ["ctx-test"]


@pytest.mark.asyncio
async def test_run_task_result_exception_marks_task_failed(monkeypatch):
    monkeypatch.setenv(fasta2a_server.A2A_TASK_RESULT_TIMEOUT_ENV, "0.01")
    storage = FakeStorage()
    worker = fasta2a_server.AgentZeroWorker(broker=None, storage=storage)
    monkeypatch.setattr(FakeContext, "communicate", lambda self, message: FailingTask())

    await worker.run_task(_params())

    assert storage.updates[-1]["task_id"] == "task-123"
    assert storage.updates[-1]["state"] == "failed"
    text = storage.updates[-1]["new_messages"][0]["parts"][0]["text"]
    assert "RuntimeError" in text
    assert "\n" not in text
    assert FakeContext.reset_count == 1
    assert FakeContext.removed == ["ctx-test"]


@pytest.mark.asyncio
async def test_run_task_final_response_completes_normally(monkeypatch):
    monkeypatch.setenv(fasta2a_server.A2A_TASK_RESULT_TIMEOUT_ENV, "0.01")
    storage = FakeStorage()
    worker = fasta2a_server.AgentZeroWorker(broker=None, storage=storage)
    monkeypatch.setattr(FakeContext, "communicate", lambda self, message: CompletedTask())

    await worker.run_task(_params())

    assert storage.updates[-1]["task_id"] == "task-123"
    assert storage.updates[-1]["state"] == "completed"
    message = storage.updates[-1]["new_messages"][0]
    assert message["role"] == "agent"
    assert message["parts"] == [{"kind": "text", "text": "final response"}]
    assert "new_artifacts" not in storage.updates[-1]
    assert FakeContext.reset_count == 1
    assert FakeContext.removed == ["ctx-test"]


def test_task_result_timeout_uses_env_and_clamps(monkeypatch):
    monkeypatch.delenv(fasta2a_server.A2A_TASK_RESULT_TIMEOUT_ENV, raising=False)
    assert fasta2a_server._task_result_timeout_seconds() == 30.0

    monkeypatch.setenv(fasta2a_server.A2A_TASK_RESULT_TIMEOUT_ENV, "120")
    assert fasta2a_server._task_result_timeout_seconds() == 120.0

    monkeypatch.setenv(fasta2a_server.A2A_TASK_RESULT_TIMEOUT_ENV, "999")
    assert fasta2a_server._task_result_timeout_seconds() == 120.0

    monkeypatch.setenv(fasta2a_server.A2A_TASK_RESULT_TIMEOUT_ENV, "0")
    assert fasta2a_server._task_result_timeout_seconds() == 1.0

    monkeypatch.setenv(fasta2a_server.A2A_TASK_RESULT_TIMEOUT_ENV, "not-a-number")
    assert fasta2a_server._task_result_timeout_seconds() == 30.0
