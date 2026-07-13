"""
Cross-Thread Awareness: Inject shared state into agent context.

At the start of every message loop, this extension reads the shared
cross-thread state and injects a summary into the agent's context,
giving every chat turn visibility into what other threads are doing.
"""
from helpers.extension import Extension
import json
import os

STATE_FILE = os.path.join(os.path.expanduser("~"), ".a0_cross_thread_state.json")


class InjectCrossThreadState(Extension):
    def execute(self, **kwargs):
        if not self.agent or self.agent.number != 0:
            return
        try:
            if not os.path.exists(STATE_FILE):
                return
            with open(STATE_FILE, "r") as f:
                state = json.load(f)

            chat_id = self.agent.context.id if hasattr(self.agent.context, 'id') else ""
            lines = ["[CROSS-THREAD STATE]"]

            threads = state.get("chat_threads", [])
            other = [t for t in threads if isinstance(t, dict) and t.get("chat_id") != chat_id]
            if other:
                lines.append(f"Other active chats: {len(other)}")
                for t in other[-3:]:
                    lines.append(f"  - {t.get('name', '?')} (last: {t.get('last_active', '?')[:19]})")

            changes = state.get("recent_changes", [])
            if changes:
                lines.append(f"Recent changes: {len(changes)}")
                for c in changes[-3:]:
                    lines.append(f"  - [{c.get('chat', '?')}] {c.get('action', '?')[:60]}")

            issues = state.get("open_issues", [])
            if issues:
                lines.append(f"Open issues: {len(issues)}")
                for i in issues[:3]:
                    lines.append(f"  - [{i.get('severity', '?')}] {i.get('description', '?')[:50]}")

            if len(lines) > 1:
                summary = "\n".join(lines)
                if hasattr(self.agent.context, 'log'):
                    self.agent.context.log.log(type="info", content=summary, update_progress="none")
        except Exception:
            pass
