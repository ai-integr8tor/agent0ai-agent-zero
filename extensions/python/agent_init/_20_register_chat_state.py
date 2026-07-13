"""
Cross-Thread Awareness: Register chat thread in shared state on agent init.

When a new agent context is created (main agent, not subordinates),
this extension automatically registers the chat thread in a shared
state file so other concurrent threads can see it.
"""
from helpers.extension import Extension
import json
import os
import fcntl
from datetime import datetime

STATE_FILE = os.path.join(os.path.expanduser("~"), ".a0_cross_thread_state.json")


def _load_state():
    if not os.path.exists(STATE_FILE):
        return {"version": "1.0", "chat_threads": [], "recent_changes": [],
                "open_issues": [], "last_updated": datetime.now().isoformat()}
    try:
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return {"version": "1.0", "chat_threads": [], "recent_changes": [],
                "open_issues": [], "last_updated": datetime.now().isoformat()}


def _save_state(state):
    state["last_updated"] = datetime.now().isoformat()
    tmp = STATE_FILE + ".tmp"
    try:
        with open(tmp, "w") as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            json.dump(state, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)
        os.replace(tmp, STATE_FILE)
    except Exception:
        if os.path.exists(tmp):
            os.remove(tmp)


class RegisterChatState(Extension):
    def execute(self, **kwargs):
        if not self.agent:
            return
        if self.agent.number != 0:
            return
        try:
            context = self.agent.context
            if not context or not hasattr(context, 'id'):
                return
            chat_id = context.id
            state = _load_state()
            threads = state.get("chat_threads", [])
            existing = [t.get("chat_id") for t in threads if isinstance(t, dict)]
            if chat_id not in existing:
                threads.append({
                    "chat_id": chat_id,
                    "name": f"Chat {chat_id[:8]}",
                    "started_at": datetime.now().isoformat(),
                    "last_active": datetime.now().isoformat()
                })
            else:
                for t in threads:
                    if isinstance(t, dict) and t.get("chat_id") == chat_id:
                        t["last_active"] = datetime.now().isoformat()
            state["chat_threads"] = threads
            _save_state(state)
        except Exception:
            pass
