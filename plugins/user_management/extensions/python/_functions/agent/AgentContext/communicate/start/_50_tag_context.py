"""Tag AgentContext with user info at communicate() time.

Primary tagger — Flask session IS available here.
"""
from __future__ import annotations
import datetime

from helpers.extension import Extension
from helpers.print_style import PrintStyle

DEBUG_LOG = "/a0/tmp/um_debug.log"

def _dbg(msg):
    try:
        ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        line = f"[{ts}] [tag_context] {msg}\n"
        PrintStyle.standard(line.strip())
        with open(DEBUG_LOG, "a") as f:
            f.write(line)
    except Exception:
        pass


class TagContext(Extension):

    def execute(self, **kwargs):
        try:
            _dbg(">>> communicate/start hook FIRED")

            data = kwargs.get("data", {})
            args = data.get("args", ())
            if not args:
                _dbg("no args in data")
                return

            context = args[0]  # AgentContext instance
            _dbg(f"context id={context.id[:12]}... existing um_user_id={context.data.get('um_user_id', 'NOT SET')}")

            # Already tagged? Skip.
            if context.data.get("um_user_id"):
                _dbg("already tagged, skipping")
                return

            # Try Flask session
            try:
                from flask import session as flask_session, has_request_context
                has_ctx = has_request_context()
                _dbg(f"has_request_context={has_ctx}")
                if not has_ctx:
                    return

                user_id = flask_session.get("um_user_id")
                username = flask_session.get("um_username")
                _dbg(f"session um_user_id={user_id} um_username={username}")
                _dbg(f"session keys={list(flask_session.keys())}")

                if not user_id:
                    _dbg("no um_user_id in session - NOT TAGGED")
                    return
            except Exception as e:
                _dbg(f"session read error: {e}")
                return

            # Tag context data
            context.data["um_user_id"] = user_id
            context.data["um_username"] = username
            _dbg(f"SUCCESS: tagged context with user_id={user_id} username={username}")

            # Persist ownership in DB
            try:
                from usr.plugins.user_management.helpers.db import execute_write
                execute_write(
                    "INSERT INTO um_context_ownership (context_id, user_id) "
                    "VALUES (%s, %s) ON CONFLICT (context_id) DO NOTHING",
                    (context.id, user_id),
                )
                _dbg("DB ownership recorded")
            except Exception as e:
                _dbg(f"DB write error: {e}")

        except Exception as e:
            _dbg(f"EXCEPTION: {e}")
