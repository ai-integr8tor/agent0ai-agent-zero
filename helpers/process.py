import os
import subprocess
import sys
import threading
from pathlib import Path

from helpers.print_style import PrintStyle

SELF_UPDATE_TRIGGER_PATH = Path("/exe/a0-self-update.yaml")
SYSTEMD_MARKER_PATH = Path("/run/systemd/system")
SYSTEMD_SERVICE_NAME = os.environ.get("A0_SYSTEMD_SERVICE", "agent-zero.service")

_server = None
_reload_lock = threading.Lock()
_reloading = False

def set_server(server):
    global _server
    _server = server

def get_server(server):
    global _server
    return _server

def stop_server():
    global _server
    if _server:
        _server.shutdown()
        _server = None

def has_pending_self_update():
    return SELF_UPDATE_TRIGGER_PATH.exists()

def request_systemd_restart_for_self_update():
    if not SYSTEMD_MARKER_PATH.exists():
        return False

    try:
        active = subprocess.run(
            ["systemctl", "is-active", "--quiet", SYSTEMD_SERVICE_NAME],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=5,
            check=False,
        )
    except Exception as exc:
        PrintStyle.warning(f"Could not check systemd service state: {exc}")
        return False

    if active.returncode != 0:
        return False

    try:
        subprocess.Popen(
            ["systemctl", "restart", "--no-block", SYSTEMD_SERVICE_NAME],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except Exception as exc:
        PrintStyle.warning(f"Could not request systemd restart: {exc}")
        return False

    return True

def reload():
    global _reloading
    with _reload_lock:
        if _reloading:
            PrintStyle.hint("Reload already in progress; ignoring duplicate request.")
            return
        _reloading = True

    stop_server()

    if has_pending_self_update():
        PrintStyle.standard(
            "Pending self-update detected; handing restart back to the native supervisor..."
        )
        if request_systemd_restart_for_self_update():
            PrintStyle.standard("Systemd restart requested for self-update handoff.")
        else:
            PrintStyle.hint(
                "Systemd restart was not available; exiting for the native supervisor handoff."
            )
        exit_process()

    restart_process()

def restart_process():
    PrintStyle.standard("Restarting process...")
    python = sys.executable
    os.execv(python, [python] + sys.argv)

def exit_process():
    PrintStyle.standard("Exiting process...")
    os._exit(0)
