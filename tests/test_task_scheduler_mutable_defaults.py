from __future__ import annotations

from datetime import datetime, timezone
import importlib.util
from pathlib import Path
import sys
import types

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = PROJECT_ROOT / "helpers" / "task_scheduler.py"


class _StubTimezone:
    def localize(self, value: datetime) -> datetime:
        return value.replace(tzinfo=timezone.utc)


class _StubLocalization:
    @staticmethod
    def get() -> "_StubLocalization":
        return _StubLocalization()

    def get_timezone(self) -> str:
        return "UTC"


class _StubPrintStyle:
    def __init__(self, *args, **kwargs):
        pass

    def print(self, *args, **kwargs):
        pass

    @staticmethod
    def error(*args, **kwargs):
        pass

    @staticmethod
    def warning(*args, **kwargs):
        pass

    @staticmethod
    def success(*args, **kwargs):
        pass

    @staticmethod
    def info(*args, **kwargs):
        pass


def _install_stub_modules(monkeypatch: pytest.MonkeyPatch) -> None:
    helpers_pkg = types.ModuleType("helpers")
    helpers_pkg.__path__ = []
    monkeypatch.setitem(sys.modules, "helpers", helpers_pkg)

    nest_asyncio = types.ModuleType("nest_asyncio")
    nest_asyncio.apply = lambda: None
    monkeypatch.setitem(sys.modules, "nest_asyncio", nest_asyncio)

    crontab = types.ModuleType("crontab")

    class _StubCronTab:
        def __init__(self, *args, **kwargs):
            pass

        def next(self, *args, **kwargs):
            return 0

    crontab.CronTab = _StubCronTab
    monkeypatch.setitem(sys.modules, "crontab", crontab)

    agent = types.ModuleType("agent")

    class Agent:
        pass

    class AgentContext:
        @staticmethod
        def get(*args, **kwargs):
            return types.SimpleNamespace()

    class UserMessage:
        pass

    agent.Agent = Agent
    agent.AgentContext = AgentContext
    agent.UserMessage = UserMessage
    monkeypatch.setitem(sys.modules, "agent", agent)

    initialize = types.ModuleType("initialize")
    initialize.initialize_agent = lambda *args, **kwargs: None
    monkeypatch.setitem(sys.modules, "initialize", initialize)

    persist_chat = types.ModuleType("helpers.persist_chat")
    persist_chat.save_tmp_chat = lambda *args, **kwargs: None
    monkeypatch.setitem(sys.modules, "helpers.persist_chat", persist_chat)

    print_style = types.ModuleType("helpers.print_style")
    print_style.PrintStyle = _StubPrintStyle
    monkeypatch.setitem(sys.modules, "helpers.print_style", print_style)

    defer = types.ModuleType("helpers.defer")

    class DeferredTask:
        pass

    defer.DeferredTask = DeferredTask
    monkeypatch.setitem(sys.modules, "helpers.defer", defer)

    files = types.ModuleType("helpers.files")
    files.get_abs_path = lambda *parts: str(Path(*parts))
    files.make_dirs = lambda *args, **kwargs: None
    files.read_file = lambda *args, **kwargs: ""
    files.write_file = lambda *args, **kwargs: None
    monkeypatch.setitem(sys.modules, "helpers.files", files)

    localization = types.ModuleType("helpers.localization")
    localization.Localization = _StubLocalization
    monkeypatch.setitem(sys.modules, "helpers.localization", localization)

    projects = types.ModuleType("helpers.projects")
    projects.activate_project = lambda *args, **kwargs: None
    monkeypatch.setitem(sys.modules, "helpers.projects", projects)

    guids = types.ModuleType("helpers.guids")
    guids.generate_id = lambda: "generated-id"
    monkeypatch.setitem(sys.modules, "helpers.guids", guids)

    helpers_pkg.projects = projects
    helpers_pkg.guids = guids

    pytz = types.ModuleType("pytz")
    pytz.timezone = lambda _name: _StubTimezone()
    monkeypatch.setitem(sys.modules, "pytz", pytz)


@pytest.fixture()
def task_scheduler_module(monkeypatch: pytest.MonkeyPatch):
    _install_stub_modules(monkeypatch)

    spec = importlib.util.spec_from_file_location("task_scheduler_under_test", MODULE_PATH)
    assert spec is not None
    assert spec.loader is not None

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    ("factory_name", "factory_kwargs"),
    [
        (
            "AdHocTask",
            {
                "name": "adhoc",
                "system_prompt": "system",
                "prompt": "prompt",
                "token": "token-1",
            },
        ),
        (
            "ScheduledTask",
            {
                "name": "scheduled",
                "system_prompt": "system",
                "prompt": "prompt",
                "schedule": {
                    "minute": "0",
                    "hour": "*",
                    "day": "*",
                    "month": "*",
                    "weekday": "*",
                },
            },
        ),
        (
            "PlannedTask",
            {
                "name": "planned",
                "system_prompt": "system",
                "prompt": "prompt",
                "plan": {},
            },
        ),
    ],
)
def test_task_factories_use_fresh_attachment_lists(task_scheduler_module, factory_name, factory_kwargs):
    factory_owner = getattr(task_scheduler_module, factory_name)
    create = factory_owner.create

    if factory_name == "ScheduledTask":
        factory_kwargs = dict(factory_kwargs)
        factory_kwargs["schedule"] = task_scheduler_module.TaskSchedule(**factory_kwargs["schedule"])
    elif factory_name == "PlannedTask":
        factory_kwargs = dict(factory_kwargs)
        factory_kwargs["plan"] = task_scheduler_module.TaskPlan.create(**factory_kwargs["plan"])

    first_task = create(**factory_kwargs)
    second_task = create(**factory_kwargs)

    first_task.attachments.append("first.txt")

    assert second_task.attachments == []
    assert first_task.attachments is not second_task.attachments


@pytest.mark.parametrize(
    ("factory_name", "factory_kwargs"),
    [
        (
            "AdHocTask",
            {
                "name": "adhoc",
                "system_prompt": "system",
                "prompt": "prompt",
                "token": "token-1",
            },
        ),
        (
            "ScheduledTask",
            {
                "name": "scheduled",
                "system_prompt": "system",
                "prompt": "prompt",
                "schedule": {
                    "minute": "0",
                    "hour": "*",
                    "day": "*",
                    "month": "*",
                    "weekday": "*",
                },
            },
        ),
        (
            "PlannedTask",
            {
                "name": "planned",
                "system_prompt": "system",
                "prompt": "prompt",
                "plan": {},
            },
        ),
    ],
)
def test_task_factories_copy_attachment_inputs(task_scheduler_module, factory_name, factory_kwargs):
    attachments = ["original.txt"]
    factory_owner = getattr(task_scheduler_module, factory_name)
    create = factory_owner.create

    if factory_name == "ScheduledTask":
        factory_kwargs = dict(factory_kwargs)
        factory_kwargs["schedule"] = task_scheduler_module.TaskSchedule(**factory_kwargs["schedule"])
    elif factory_name == "PlannedTask":
        factory_kwargs = dict(factory_kwargs)
        factory_kwargs["plan"] = task_scheduler_module.TaskPlan.create(**factory_kwargs["plan"])

    task = create(**factory_kwargs, attachments=attachments)
    attachments.append("mutated-after-create.txt")

    assert task.attachments == ["original.txt"]
    assert task.attachments is not attachments


def test_task_plan_create_uses_fresh_default_lists(task_scheduler_module):
    first_plan = task_scheduler_module.TaskPlan.create()
    second_plan = task_scheduler_module.TaskPlan.create()

    first_plan.todo.append(datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc))
    first_plan.done.append(datetime(2024, 1, 2, 12, 0, 0, tzinfo=timezone.utc))

    assert second_plan.todo == []
    assert second_plan.done == []
    assert first_plan.todo is not second_plan.todo
    assert first_plan.done is not second_plan.done


def test_task_plan_create_copies_and_localizes_input_lists(task_scheduler_module):
    todo = [datetime(2024, 1, 1, 12, 0, 0)]
    done = [datetime(2024, 1, 2, 12, 0, 0)]

    plan = task_scheduler_module.TaskPlan.create(todo=todo, done=done)

    assert todo[0].tzinfo is None
    assert done[0].tzinfo is None
    assert plan.todo is not todo
    assert plan.done is not done
    assert plan.todo[0].tzinfo is timezone.utc
    assert plan.done[0].tzinfo is timezone.utc
