import asyncio

from api import restart
from api.health import HealthCheck
from api.restart import Restart


class FakeThread:
    created = []

    def __init__(self, *, target, daemon, name):
        self.target = target
        self.daemon = daemon
        self.name = name
        self.started = False
        self.created.append(self)

    def start(self):
        self.started = True


def test_restart_returns_before_reloading(monkeypatch):
    FakeThread.created = []
    monkeypatch.setattr(restart.threading, "Thread", FakeThread)

    handler = Restart(app=None, thread_lock=None)
    response = asyncio.run(handler.process({}, request=None))

    assert response == {"success": True, "message": "Restart scheduled."}
    assert len(FakeThread.created) == 1
    thread = FakeThread.created[0]
    assert thread.name == "UiRestartExit"
    assert thread.daemon is True
    assert thread.started is True


def test_restart_thread_runs_delayed_reload(monkeypatch):
    called = False

    def reload():
        nonlocal called
        called = True

    monkeypatch.setattr(restart.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(restart.process, "reload", reload)
    monkeypatch.setattr(restart.threading, "Thread", FakeThread)

    FakeThread.created = []
    handler = Restart(app=None, thread_lock=None)
    asyncio.run(handler.process({}, request=None))

    FakeThread.created[0].target()
    assert called is True


def test_health_allows_head_probes():
    assert "HEAD" in HealthCheck.get_methods()
