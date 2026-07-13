"""
Cross-Thread Awareness: Log each turn to shared state.

At the end of every message loop, this extension records what the
agent did so other concurrent threads can see the activity.
"""
from helpers.extension import Extension
import json
import os
import fcntl
from datetime import datetime

STATE_FILE = os.path.join(os.path.expanduser("~"), ".a0_cross_thread_state.json")
MAX_CHANGES = 50


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


class LogCrossThreadTurn(Extension):
    def execute(self, **kwargs):
        if not self.agent or self.agent.number != 0:
            return
        try:
            context = self.agent.context
            if not context or not hasattr(context, 'id'):
                return
            chat_id = context.id

            last_msg = ""
            if hasattr(context, 'log') and hasattr(context.log, 'logs'):
                for entry in reversed(context.log.logs):
                    if hasattr(entry, 'type') and entry.type == 'user':
                        content = getattr(entry, 'content', '') or ''
                        last_msg = content[:60]
                        break

            if not last_msg.strip():
                return

            state = _load_state()
            changes = state.get("recent_changes", [])
            changes.append({
                "chat": chat_id[:8],
                "action": f"Turn: {last_msg}",
                "timestamp": datetime.now().isoformat()
            })
            if len(changes) > MAX_CHANGES:
                changes = changes[-MAX_CHANGES:]
            state["recent_changes"] = changes

            for t in state.get("chat_threads", []):
                if isinstance(t, dict) and t.get("chat_id") == chat_id:
                    t["last_active"] = datetime.now().isoformat()

            _save_state(state)
        except Exception:
            pass
