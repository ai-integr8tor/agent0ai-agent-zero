"""Clear um_* session vars when a user logs out via the A0 native logout."""
from __future__ import annotations

from helpers.extension import Extension
from helpers.print_style import PrintStyle


class UmLogout(Extension):

    async def execute(self, **kwargs):
        try:
            from flask import session
            username = session.get("um_username", "unknown")
            for key in ("um_user_id", "um_username", "um_role"):
                session.pop(key, None)
            PrintStyle.standard(f"[user_management] User '{username}' logged out.")
        except Exception as e:
            PrintStyle.debug(f"[user_management] logout extension error: {e}")
