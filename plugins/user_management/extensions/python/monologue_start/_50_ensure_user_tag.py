"""Belt-and-suspenders: ensure context is tagged before monologue.

Runs at the start of each agent monologue loop. If context.data still
doesn't have um_user_id (e.g. communicate/start was missed), check
the DB for a recorded ownership.

This runs inside DeferredTask (no Flask session), so it can only
recover from DB records — it cannot discover the user from session.
"""
from __future__ import annotations

from helpers.extension import Extension
from helpers.print_style import PrintStyle
from agent import LoopData


class EnsureUserTag(Extension):

    async def execute(self, loop_data: LoopData = LoopData(), **kwargs):
        try:
            if not self.agent or self.agent.number != 0:
                return  # Only track top-level agent

            context = self.agent.context

            # Already tagged?
            if context.data.get("um_user_id"):
                return

            # Try DB lookup (only source available in async context)
            try:
                from usr.plugins.user_management.helpers.db import execute_query
                rows = execute_query(
                    "SELECT co.user_id, u.username "
                    "FROM um_context_ownership co "
                    "LEFT JOIN um_users u ON co.user_id = u.id "
                    "WHERE co.context_id = %s LIMIT 1",
                    (context.id,),
                )
                if rows:
                    context.data["um_user_id"] = rows[0]["user_id"]
                    context.data["um_username"] = rows[0].get("username", "unknown")
                    PrintStyle.debug(
                        f"[user_management] monologue_start: recovered tag for "
                        f"{context.id[:8]}... from DB"
                    )
            except Exception:
                pass

        except Exception as e:
            PrintStyle.debug(f"[user_management] ensure_user_tag: {e}")
