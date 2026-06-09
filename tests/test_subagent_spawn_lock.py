from __future__ import annotations

import asyncio
import importlib
import sys
import types
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


@dataclass
class _FakeResponse:
    message: str
    break_loop: bool
    additional: dict | None = None


class _FakeTool:
    def __init__(
        self,
        agent,
        name: str,
        method: str | None,
        args: dict | None,
        message: str,
        loop_data=None,
        **kwargs,
    ) -> None:
        self.agent = agent
        self.name = name
        self.method = method
        self.args = args or {}
        self.message = message
        self.loop_data = loop_data


class _FakeAgentClass:
    DATA_NAME_SUBORDINATE = "_subordinate"
    DATA_NAME_SUPERIOR = "_superior"


class _FakeAgent:
    def __init__(self) -> None:
        self._data: dict = {}
        self.number = 0
        self.context = types.SimpleNamespace(id="ctx", log=None)

    def get_data(self, key: str):
        return self._data.get(key)

    def set_data(self, key: str, value) -> None:
        self._data[key] = value


def _install_call_subordinate_stubs(monkeypatch, *, locked: bool) -> None:
    agent_stub = types.ModuleType("agent")
    agent_stub.Agent = _FakeAgentClass

    class _UserMessage:
        def __init__(self, message: str = "", attachments=None) -> None:
            self.message = message
            self.attachments = attachments or []

    agent_stub.UserMessage = _UserMessage
    monkeypatch.setitem(sys.modules, "agent", agent_stub)

    tool_stub = types.ModuleType("helpers.tool")
    tool_stub.Tool = _FakeTool
    tool_stub.Response = _FakeResponse
    monkeypatch.setitem(sys.modules, "helpers.tool", tool_stub)

    initialize_stub = types.ModuleType("initialize")
    initialize_stub.initialize_agent = lambda: types.SimpleNamespace(profile="")
    monkeypatch.setitem(sys.modules, "initialize", initialize_stub)

    ext_pkg = types.ModuleType("extensions")
    monkeypatch.setitem(sys.modules, "extensions", ext_pkg)
    ext_py = types.ModuleType("extensions.python")
    monkeypatch.setitem(sys.modules, "extensions.python", ext_py)
    hist_stub = types.ModuleType("extensions.python.hist_add_tool_result")
    hist_stub._90_save_tool_call_file = types.SimpleNamespace(LEN_MIN=10**9)
    monkeypatch.setitem(
        sys.modules, "extensions.python.hist_add_tool_result", hist_stub
    )

    settings_stub = types.ModuleType("helpers.settings")
    settings_stub.get_settings = lambda: {"subagent_spawn_locked": locked}
    monkeypatch.setitem(sys.modules, "helpers.settings", settings_stub)

    # ensure a fresh import of the tool module with the active stubs
    sys.modules.pop("tools.call_subordinate", None)


def _make_delegation(monkeypatch, *, locked: bool):
    _install_call_subordinate_stubs(monkeypatch, locked=locked)
    module = importlib.import_module("tools.call_subordinate")
    tool = module.Delegation(
        _FakeAgent(),
        "call_subordinate",
        None,
        {"message": "hello", "reset": "true"},
        "",
        None,
    )
    return module, tool


def test_call_subordinate_is_blocked_when_subagent_spawn_locked(monkeypatch):
    module, tool = _make_delegation(monkeypatch, locked=True)

    response = asyncio.run(tool.execute(**tool.args))

    assert isinstance(response, module.Response)
    assert response.break_loop is False
    assert "locked" in response.message.lower()
    # no subordinate must have been created on the agent
    assert tool.agent.get_data(_FakeAgentClass.DATA_NAME_SUBORDINATE) is None


def test_call_subordinate_does_not_short_circuit_when_unlocked(monkeypatch):
    module, tool = _make_delegation(monkeypatch, locked=False)

    # When unlocked, the tool must walk past the gate and try to construct
    # a subordinate Agent. Our fake Agent class is not constructible, so we
    # detect "did not short-circuit" by observing the resulting TypeError.
    try:
        asyncio.run(tool.execute(**tool.args))
    except TypeError as exc:
        assert "_FakeAgentClass() takes no arguments" in str(exc)
    else:  # pragma: no cover - defensive
        raise AssertionError(
            "Lock unexpectedly short-circuited when subagent_spawn_locked=False"
        )


def test_subagent_spawn_locked_default_is_false_in_settings_source():
    """The setting must default to False so existing installs are unaffected."""
    settings_src = (PROJECT_ROOT / "helpers" / "settings.py").read_text(
        encoding="utf-8"
    )
    assert "subagent_spawn_locked: bool" in settings_src
    assert 'get_default_value("subagent_spawn_locked", False)' in settings_src
