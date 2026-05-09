import os
import sys
import threading

from helpers.print_style import PrintStyle

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

def reload():
    global _reloading
    with _reload_lock:
        if _reloading:
            PrintStyle.hint("Reload already in progress; ignoring duplicate request.")
            return
        _reloading = True

    stop_server()
    restart_process()

def restart_process():
    PrintStyle.standard("Restarting process...")
    python = sys.executable
    os.execv(python, [python] + sys.argv)

def exit_process():
    PrintStyle.standard("Exiting process...")
    os._exit(0)