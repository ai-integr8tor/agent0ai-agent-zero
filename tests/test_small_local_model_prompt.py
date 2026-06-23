import sys
import types
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import agent as agent_module
from agent import Agent, LoopData
from extensions.python.system_prompt import _10_small_local_model_prompt as small_prompt
from helpers import history
from helpers.llm_result import LLMResult


def test_small_local_prompt_detects_qwen_ollama():
    assert small_prompt.should_include_small_local_prompt(
        {
            "provider": "ollama",
            "name": "qwen3.5:9b",
            "api_base": "http://host.docker.internal:11434",
        }
    )


def test_small_local_prompt_detects_local_small_model_by_size():
    assert small_prompt.should_include_small_local_prompt(
        {
            "provider": "other",
            "name": "llama3.2:8b",
            "api_base": "http://127.0.0.1:1234/v1",
        }
    )


def test_small_local_prompt_ignores_cloud_and_large_local_models():
    assert not small_prompt.should_include_small_local_prompt(
        {
            "provider": "openrouter",
            "name": "qwen3.5:9b",
            "api_base": "",
        }
    )
    assert not small_prompt.should_include_small_local_prompt(
        {
            "provider": "ollama",
            "name": "llama3.3:70b",
            "api_base": "http://localhost:11434",
        }
    )


def test_small_local_prompt_forbids_visible_planning_fields():
    prompt = (PROJECT_ROOT / "prompts" / "agent.system.main.small_local_model.md").read_text(
        encoding="utf-8"
    )

    assert "Do not include `thoughts`, `headline`" in prompt
    assert "exactly the executable fields `tool_name` and `tool_args`" in prompt


@pytest.mark.asyncio
async def test_small_local_prompt_builds_from_model_config(monkeypatch):
    from plugins._model_config.helpers import model_config

    class DummyAgent:
        def read_prompt(self, file: str, **kwargs):
            return f"prompt:{file}"

    monkeypatch.setattr(
        model_config,
        "get_chat_model_config",
        lambda agent: {
            "provider": "ollama",
            "name": "qwen3.5:9b",
            "api_base": "http://host.docker.internal:11434",
        },
    )

    assert await small_prompt.build_prompt(DummyAgent()) == (
        "prompt:agent.system.main.small_local_model.md"
    )


def test_reasoning_only_guard_retries_then_fails(monkeypatch):
    monkeypatch.setattr(
        agent_module,
        "PrintStyle",
        lambda *args, **kwargs: types.SimpleNamespace(print=lambda message: None),
    )

    log_entries = []

    class DummyLog:
        def log(self, **kwargs):
            log_entries.append(kwargs)
            return types.SimpleNamespace(id=f"log-{len(log_entries)}")

    test_agent = object.__new__(Agent)
    test_agent.loop_data = LoopData()
    test_agent.context = types.SimpleNamespace(log=DummyLog())
    test_agent.agent_name = "A0"

    warnings = []

    def read_prompt(file: str, **kwargs):
        if file == "fw.msg_reasoning_only.md":
            return "repair tool request"
        if file == "fw.msg_reasoning_only_failed.md":
            return f"failed after {kwargs['attempts']}"
        return file

    def hist_add_warning(message: str):
        warnings.append(message)
        return types.SimpleNamespace(id=f"warn-{len(warnings)}")

    test_agent.read_prompt = read_prompt
    test_agent.hist_add_warning = hist_add_warning

    result = LLMResult.from_chat(response="", reasoning="thinking but no tool")

    assert Agent._handle_reasoning_only_result(test_agent, result) == (True, None)
    assert Agent._handle_reasoning_only_result(test_agent, result) == (True, None)
    assert Agent._handle_reasoning_only_result(test_agent, result) == (
        True,
        "failed after 2",
    )
    assert warnings == ["repair tool request", "repair tool request"]
    assert log_entries[-1]["type"] == "response"


def test_reasoning_only_guard_ignores_valid_response():
    test_agent = object.__new__(Agent)
    test_agent.loop_data = LoopData()

    result = LLMResult.from_chat(
        response='{"tool_name":"response","tool_args":{"text":"ok"}}',
        reasoning="thinking before valid response",
    )

    assert Agent._handle_reasoning_only_result(test_agent, result) == (False, None)


def test_repeated_response_guard_finalizes_completed_duplicate_tool_call(monkeypatch):
    monkeypatch.setattr(
        agent_module,
        "PrintStyle",
        lambda *args, **kwargs: types.SimpleNamespace(print=lambda message: None),
    )

    log_entries = []

    class DummyLog:
        def log(self, **kwargs):
            log_entries.append(kwargs)
            return types.SimpleNamespace(id=f"log-{len(log_entries)}")

    test_agent = object.__new__(Agent)
    test_agent.loop_data = LoopData()
    test_agent.context = types.SimpleNamespace(log=DummyLog())
    test_agent.agent_name = "A0"
    test_agent.history = history.History(test_agent)
    test_agent.history.add_message(
        False,
        {
            "tool_name": "text_editor",
            "tool_result": "/a0/usr/workdir/todos.md written 9 lines",
        },
    )

    warnings = []

    def read_prompt(file: str, **kwargs):
        if file == "fw.msg_repeat_completed.md":
            return f"completed: {kwargs['last_tool_result']}"
        if file == "fw.msg_repeat.md":
            return "repeat repair"
        if file == "fw.msg_repeat_failed.md":
            return f"failed after {kwargs['attempts']}: {kwargs['last_tool_result']}"
        return file

    def hist_add_warning(message: str):
        warnings.append(message)
        return types.SimpleNamespace(id=f"warn-{len(warnings)}")

    test_agent.read_prompt = read_prompt
    test_agent.hist_add_warning = hist_add_warning

    result = LLMResult.from_chat(
        response='{"tool_name":"text_editor","tool_args":{"action":"write"}}'
    )

    handled, final = Agent._handle_repeated_response_result(test_agent, result)

    assert handled is True
    assert final is not None
    assert "completed:" in final
    assert "text_editor: /a0/usr/workdir/todos.md written 9 lines" in final
    assert warnings == []
    assert log_entries[-1]["type"] == "response"


def test_repeated_response_guard_retries_then_stops_without_completed_tool(monkeypatch):
    monkeypatch.setattr(
        agent_module,
        "PrintStyle",
        lambda *args, **kwargs: types.SimpleNamespace(print=lambda message: None),
    )

    log_entries = []

    class DummyLog:
        def log(self, **kwargs):
            log_entries.append(kwargs)
            return types.SimpleNamespace(id=f"log-{len(log_entries)}")

    test_agent = object.__new__(Agent)
    test_agent.loop_data = LoopData()
    test_agent.context = types.SimpleNamespace(log=DummyLog())
    test_agent.agent_name = "A0"
    test_agent.history = history.History(test_agent)

    warnings = []

    def read_prompt(file: str, **kwargs):
        if file == "fw.msg_repeat.md":
            return "repeat repair"
        if file == "fw.msg_repeat_failed.md":
            return f"failed after {kwargs['attempts']}: {kwargs['last_tool_result']}"
        return file

    def hist_add_warning(message: str):
        warnings.append(message)
        return types.SimpleNamespace(id=f"warn-{len(warnings)}")

    test_agent.read_prompt = read_prompt
    test_agent.hist_add_warning = hist_add_warning

    result = LLMResult.from_chat(response="same non-tool text")

    assert Agent._handle_repeated_response_result(test_agent, result) == (True, None)
    assert Agent._handle_repeated_response_result(test_agent, result) == (True, None)
    handled, final = Agent._handle_repeated_response_result(test_agent, result)

    assert handled is True
    assert final is not None
    assert "failed after 2" in final
    assert "No successful tool result was available" in final
    assert warnings == ["repeat repair", "repeat repair"]
    assert log_entries[-1]["type"] == "response"


def test_successful_canvas_text_editor_write_records_semantic_duplicate(monkeypatch):
    monkeypatch.setattr(
        agent_module,
        "PrintStyle",
        lambda *args, **kwargs: types.SimpleNamespace(print=lambda message: None),
    )

    log_entries = []

    class DummyLog:
        def log(self, **kwargs):
            log_entries.append(kwargs)
            return types.SimpleNamespace(id=f"log-{len(log_entries)}")

    test_agent = object.__new__(Agent)
    test_agent.loop_data = LoopData()
    test_agent.context = types.SimpleNamespace(log=DummyLog())
    test_agent.agent_name = "A0"
    test_agent.history = history.History(test_agent)

    def read_prompt(file: str, **kwargs):
        if file == "fw.msg_repeat_completed.md":
            return f"completed: {kwargs['last_tool_result']}"
        if file == "fw.msg_tool_completed.md":
            return f"done: {kwargs['message']}"
        return file

    test_agent.read_prompt = read_prompt
    test_agent.get_data = lambda name: {}
    test_agent.set_data = lambda name, value: None

    original_args = {
        "action": "write",
        "path": "/a0/usr/workdir/TODO.md",
        "content": "# My Tasks\n",
        "open_in_canvas": True,
    }
    response = types.SimpleNamespace(
        message="/a0/usr/workdir/TODO.md written 1 lines",
        additional={
            "_tool_name": "text_editor",
            "action": "write",
            "path": "/a0/usr/workdir/TODO.md",
            "open_in_canvas": True,
        },
    )

    test_agent.history.add_message(
        False,
        {
            "tool_name": "text_editor",
            "tool_result": "/a0/usr/workdir/TODO.md written 1 lines",
        },
    )

    Agent._record_successful_tool_request(
        test_agent, "text_editor", original_args, response
    )

    repeated_args_with_different_content = {
        "action": "write",
        "path": "/a0/usr/workdir/TODO.md",
        "content": "# My Tasks\n\n- [ ] Different generated text\n",
        "open_in_canvas": True,
    }

    assert Agent._is_duplicate_completed_tool_request(
        test_agent, "text_editor", repeated_args_with_different_content
    )
    assert Agent._handle_duplicate_completed_tool_request(
        test_agent, "text_editor", repeated_args_with_different_content
    ) == "completed: Last completed tool result:\ntext_editor: /a0/usr/workdir/TODO.md written 1 lines"
    assert log_entries[-1]["heading"] == "A0: Duplicate tool action stopped"


def test_canvas_text_editor_completion_finalizes_turn(monkeypatch):
    monkeypatch.setattr(
        agent_module,
        "PrintStyle",
        lambda *args, **kwargs: types.SimpleNamespace(print=lambda message: None),
    )

    test_agent = object.__new__(Agent)
    test_agent.loop_data = LoopData()

    def read_prompt(file: str, **kwargs):
        if file == "fw.msg_tool_completed.md":
            return f"done: {kwargs['message']}"
        return file

    test_agent.read_prompt = read_prompt

    final = Agent._tool_completion_final_message(
        test_agent,
        "text_editor",
        {
            "action": "write",
            "path": "/a0/usr/workdir/TODO.md",
            "content": "# My Tasks\n",
            "open_in_canvas": True,
        },
        types.SimpleNamespace(
            additional={
                "action": "write",
                "path": "/a0/usr/workdir/TODO.md",
                "open_in_canvas": True,
            }
        ),
    )

    assert final == (
        "done: The document was saved and opened in the canvas: "
        "/a0/usr/workdir/TODO.md"
    )
