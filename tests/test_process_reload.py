import subprocess

import pytest

from helpers import process


@pytest.fixture(autouse=True)
def reset_reload_state():
    process._reloading = False
    yield
    process._reloading = False


def test_reload_restarts_process_when_no_self_update(monkeypatch):
    called = {"stop": False, "restart": False, "exit": False, "systemd": False}

    monkeypatch.setattr(process, "stop_server", lambda: called.__setitem__("stop", True))
    monkeypatch.setattr(process, "restart_process", lambda: called.__setitem__("restart", True))
    monkeypatch.setattr(process, "has_pending_self_update", lambda: False)
    monkeypatch.setattr(
        process,
        "request_systemd_restart_for_self_update",
        lambda: called.__setitem__("systemd", True),
    )
    monkeypatch.setattr(process.os, "_exit", lambda code: called.__setitem__("exit", True))

    process.reload()

    assert called == {"stop": True, "restart": True, "exit": False, "systemd": False}


def test_reload_exits_for_native_handoff_when_self_update_pending_without_systemd(monkeypatch):
    called = {"stop": False, "restart": False, "systemd": False, "exit_code": None}

    def fake_exit(code):
        called["exit_code"] = code
        raise SystemExit(code)

    def fake_systemd_restart():
        called["systemd"] = True
        return False

    monkeypatch.setattr(process, "stop_server", lambda: called.__setitem__("stop", True))
    monkeypatch.setattr(process, "restart_process", lambda: called.__setitem__("restart", True))
    monkeypatch.setattr(process, "has_pending_self_update", lambda: True)
    monkeypatch.setattr(process, "request_systemd_restart_for_self_update", fake_systemd_restart)
    monkeypatch.setattr(process.os, "_exit", fake_exit)

    with pytest.raises(SystemExit) as exc_info:
        process.reload()

    assert exc_info.value.code == 0
    assert called == {"stop": True, "restart": False, "systemd": True, "exit_code": 0}


def test_reload_requests_systemd_restart_when_self_update_pending(monkeypatch):
    called = {"stop": False, "restart": False, "systemd": False, "exit_code": None}

    def fake_exit(code):
        called["exit_code"] = code
        raise SystemExit(code)

    def fake_systemd_restart():
        called["systemd"] = True
        return True

    monkeypatch.setattr(process, "stop_server", lambda: called.__setitem__("stop", True))
    monkeypatch.setattr(process, "restart_process", lambda: called.__setitem__("restart", True))
    monkeypatch.setattr(process, "has_pending_self_update", lambda: True)
    monkeypatch.setattr(process, "request_systemd_restart_for_self_update", fake_systemd_restart)
    monkeypatch.setattr(process.os, "_exit", fake_exit)

    with pytest.raises(SystemExit) as exc_info:
        process.reload()

    assert exc_info.value.code == 0
    assert called == {"stop": True, "restart": False, "systemd": True, "exit_code": 0}


def test_reload_ignores_duplicate_request(monkeypatch):
    process._reloading = True
    called = {"stop": False, "restart": False, "exit": False}

    monkeypatch.setattr(process, "stop_server", lambda: called.__setitem__("stop", True))
    monkeypatch.setattr(process, "restart_process", lambda: called.__setitem__("restart", True))
    monkeypatch.setattr(process.os, "_exit", lambda code: called.__setitem__("exit", True))

    process.reload()

    assert called == {"stop": False, "restart": False, "exit": False}


def test_has_pending_self_update_checks_trigger_path(monkeypatch):
    monkeypatch.setattr(
        process,
        "SELF_UPDATE_TRIGGER_PATH",
        type("Trigger", (), {"exists": staticmethod(lambda: True)})(),
    )

    assert process.has_pending_self_update() is True


def test_request_systemd_restart_returns_false_without_systemd(monkeypatch):
    monkeypatch.setattr(
        process,
        "SYSTEMD_MARKER_PATH",
        type("Marker", (), {"exists": staticmethod(lambda: False)})(),
    )

    assert process.request_systemd_restart_for_self_update() is False


def test_request_systemd_restart_starts_unit_when_active(monkeypatch):
    calls = {"run": None, "popen": None}

    class Completed:
        returncode = 0

    def fake_run(args, **kwargs):
        calls["run"] = args
        return Completed()

    def fake_popen(args, **kwargs):
        calls["popen"] = args
        return object()

    monkeypatch.setattr(
        process,
        "SYSTEMD_MARKER_PATH",
        type("Marker", (), {"exists": staticmethod(lambda: True)})(),
    )
    monkeypatch.setattr(process.subprocess, "run", fake_run)
    monkeypatch.setattr(process.subprocess, "Popen", fake_popen)

    assert process.request_systemd_restart_for_self_update() is True
    assert calls["run"] == ["systemctl", "is-active", "--quiet", "agent-zero.service"]
    assert calls["popen"] == ["systemctl", "restart", "--no-block", "agent-zero.service"]


def test_request_systemd_restart_returns_false_when_unit_inactive(monkeypatch):
    calls = {"popen": False}

    class Completed:
        returncode = 3

    monkeypatch.setattr(
        process,
        "SYSTEMD_MARKER_PATH",
        type("Marker", (), {"exists": staticmethod(lambda: True)})(),
    )
    monkeypatch.setattr(process.subprocess, "run", lambda *a, **kw: Completed())
    monkeypatch.setattr(process.subprocess, "Popen", lambda *a, **kw: calls.__setitem__("popen", True))

    assert process.request_systemd_restart_for_self_update() is False
    assert calls["popen"] is False


def test_request_systemd_restart_returns_false_on_systemctl_error(monkeypatch):
    monkeypatch.setattr(
        process,
        "SYSTEMD_MARKER_PATH",
        type("Marker", (), {"exists": staticmethod(lambda: True)})(),
    )

    def fake_run(*args, **kwargs):
        raise subprocess.TimeoutExpired(args=args, timeout=5)

    monkeypatch.setattr(process.subprocess, "run", fake_run)

    assert process.request_systemd_restart_for_self_update() is False
