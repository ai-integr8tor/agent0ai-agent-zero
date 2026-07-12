from helpers.api import ApiHandler, Input, Output, Request, Response
from usr.plugins.user_management.helpers.auth import (
    verify_user,
    set_session_user,
    clear_session_user,
    get_current_user_from_session,
)
from usr.plugins.user_management.helpers.db import execute_query


class Login(ApiHandler):
    """Handle user login and logout."""

    @classmethod
    def requires_auth(cls) -> bool:
        # Login endpoint must be accessible without existing auth
        return False

    @classmethod
    def requires_csrf(cls) -> bool:
        return False

    async def process(self, input: Input, request: Request) -> Output:
        action = str(input.get("action", "login")).strip().lower()

        if action == "login":
            username = str(input.get("username", "")).strip()
            password = str(input.get("password", "")).strip()
            if not username or not password:
                return Response("Missing username or password", 400)

            user = verify_user(username, password)
            if not user:
                return Response("Invalid credentials", 401)

            set_session_user(user)
            return {
                "ok": True,
                "user": {
                    "id": user["id"],
                    "username": user["username"],
                    "role": user["role"],
                },
            }

        elif action == "logout":
            clear_session_user()
            return {"ok": True}

        elif action == "status":
            user = get_current_user_from_session()
            if user:
                return {
                    "ok": True,
                    "logged_in": True,
                    "user": {
                        "id": user["id"],
                        "username": user["username"],
                        "role": user["role"],
                    },
                }
            return {"ok": True, "logged_in": False, "user": None}

        elif action == "owned_contexts":
            from flask import session
            user_id = session.get("um_user_id")
            role = session.get("um_role")
            if not user_id:
                return {"ok": True, "context_ids": []}
            # Admins see all - no filtering needed
            if role == "admin":
                return {"ok": True, "context_ids": [], "is_admin": True}
            rows = execute_query(
                "SELECT context_id FROM um_context_ownership WHERE user_id = %s",
                (user_id,),
            )
            return {"ok": True, "context_ids": [r["context_id"] for r in rows]}

        return Response("Unknown action", 400)
