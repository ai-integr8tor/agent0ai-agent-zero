from helpers.api import ApiHandler, Input, Output, Request, Response
from flask import session
from usr.plugins.user_management.helpers.auth import (
    create_user,
    list_users,
    get_user,
    delete_user,
    update_user,
)


class Users(ApiHandler):
    """CRUD operations for users (admin only)."""

    async def process(self, input: Input, request: Request) -> Output:
        # Admin check
        role = session.get("um_role")
        if role != "admin":
            return Response("Admin access required", 403)

        action = str(input.get("action", "")).strip().lower()

        if action == "list":
            users = list_users()
            # Serialize datetimes
            for u in users:
                if u.get("created_at"):
                    u["created_at"] = str(u["created_at"])
            return {"ok": True, "users": users}

        elif action == "get":
            user_id = input.get("user_id")
            if not user_id:
                return Response("Missing user_id", 400)
            user = get_user(int(user_id))
            if not user:
                return Response("User not found", 404)
            if user.get("created_at"):
                user["created_at"] = str(user["created_at"])
            return {"ok": True, "user": user}

        elif action == "create":
            username = str(input.get("username", "")).strip()
            password = str(input.get("password", "")).strip()
            role_val = str(input.get("role", "user")).strip()
            if not username or not password:
                return Response("Missing username or password", 400)
            if role_val not in ("admin", "user"):
                return Response("Invalid role", 400)
            try:
                user = create_user(username, password, role_val)
                if user and user.get("created_at"):
                    user["created_at"] = str(user["created_at"])
                return {"ok": True, "user": user}
            except Exception as e:
                if "duplicate" in str(e).lower() or "unique" in str(e).lower():
                    return Response("Username already exists", 409)
                raise

        elif action == "update":
            user_id = input.get("user_id")
            if not user_id:
                return Response("Missing user_id", 400)
            user = update_user(
                int(user_id),
                username=input.get("username"),
                password=input.get("password"),
                role=input.get("role"),
            )
            if user and user.get("created_at"):
                user["created_at"] = str(user["created_at"])
            return {"ok": True, "user": user}

        elif action == "delete":
            user_id = input.get("user_id")
            if not user_id:
                return Response("Missing user_id", 400)
            # Prevent self-deletion
            if int(user_id) == session.get("um_user_id"):
                return Response("Cannot delete your own account", 400)
            delete_user(int(user_id))
            return {"ok": True}

        return Response("Unknown action", 400)
