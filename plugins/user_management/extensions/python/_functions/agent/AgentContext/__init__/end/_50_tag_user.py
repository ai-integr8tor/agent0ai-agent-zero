"""Backup tagger: try to tag context at creation time.

This fires on AgentContext.__init__ end. Flask session is usually NOT
available here (contexts are created from WS events or startup loading),
so this is a best-effort backup. The primary tagging happens in
communicate/start/_50_tag_context.py.

Also checks DB for previously recorded ownership (handles contexts
loaded from disk that were tagged in a previous session).
"""
from __future__ import annotations

from helpers.extension import Extension
from helpers.print_style import PrintStyle


class TagUser(Extension):

    def execute(self, **kwargs):
        try:
            data = kwargs.get("data", {})
            args = data.get("args", ())
            if not args:
                return

            context = args[0]  # AgentContext being initialized

            # Already tagged via persisted data? Great, just ensure DB ownership.
            if context.data.get("um_user_id"):
                self._ensure_db_ownership(context)
                return

            # Strategy 1: Try Flask session (works if created from HTTP context)
            user_id, username = self._try_flask_session()
            if user_id:
                context.data["um_user_id"] = user_id
                context.data["um_username"] = username
                self._ensure_db_ownership(context)
                PrintStyle.debug(
                    f"[user_management] tag_user __init__: tagged {context.id[:8]}... "
                    f"from session (user={username})"
                )
                return

            # Strategy 2: Check DB for existing ownership
            user_id, username = self._try_db_lookup(context.id)
            if user_id:
                context.data["um_user_id"] = user_id
                context.data["um_username"] = username
                PrintStyle.debug(
                    f"[user_management] tag_user __init__: tagged {context.id[:8]}... "
                    f"from DB (user={username})"
                )
                return

            # No user info available — will be tagged at communicate() time

        except Exception as e:
            PrintStyle.debug(f"[user_management] tag_user: {e}")

    @staticmethod
    def _try_flask_session():
        try:
            from flask import session as flask_session, has_request_context
            if not has_request_context():
                return None, None
            return flask_session.get("um_user_id"), flask_session.get("um_username")
        except Exception:
            return None, None

    @staticmethod
    def _try_db_lookup(context_id):
        try:
            from usr.plugins.user_management.helpers.db import execute_query
            rows = execute_query(
                "SELECT co.user_id, u.username "
                "FROM um_context_ownership co "
                "LEFT JOIN um_users u ON co.user_id = u.id "
                "WHERE co.context_id = %s LIMIT 1",
                (context_id,),
            )
            if rows:
                return rows[0]["user_id"], rows[0].get("username", "unknown")
        except Exception:
            pass
        return None, None

    @staticmethod
    def _ensure_db_ownership(context):
        try:
            user_id = context.data.get("um_user_id")
            if not user_id:
                return
            from usr.plugins.user_management.helpers.db import execute_write
            execute_write(
                "INSERT INTO um_context_ownership (context_id, user_id) "
                "VALUES (%s, %s) ON CONFLICT (context_id) DO NOTHING",
                (context.id, user_id),
            )
        except Exception:
            pass
