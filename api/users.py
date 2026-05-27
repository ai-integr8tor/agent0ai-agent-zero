from flask import Request, session

from helpers.api import ApiHandler
from helpers import user_store


class Users(ApiHandler):
    @classmethod
    def requires_auth(cls) -> bool:
        return True

    async def process(self, input: dict, request: Request) -> dict:
        current_user = user_store.find_user_by_id(session.get("user_id") or "") or user_store.find_user(session.get("username") or "")
        if not current_user or not current_user.get("enabled", True):
            return {"ok": False, "error": "Authentication required"}

        current_username = session.get("username") or session.get("user_id") or ""
        current_role = current_user.get("role") or "user"
        action = (input.get("action") or "list").lower()

        try:
            if action == "list":
                if current_role == "admin":
                    safe_users = [user_store.sanitize_user(u) for u in user_store.list_users()]
                else:
                    safe_users = [user_store.sanitize_user(current_user)]
                return {
                    "ok": True,
                    "data": safe_users,
                    "current_username": current_username,
                    "current_role": current_role,
                }

            if action == "create":
                if current_role != "admin":
                    return {"ok": False, "error": "Admin only"}
                username = (input.get("username") or "").strip()
                password = input.get("password") or ""
                role = input.get("role") or "user"
                enabled = bool(input.get("enabled", True))
                user = user_store.upsert_user(
                    username=username,
                    password=password,
                    role=role,
                    enabled=enabled,
                    require_existing=False,
                )
                return {"ok": True, "data": user_store.sanitize_user(user)}

            if action == "update":
                username = (input.get("username") or "").strip()
                password = input.get("password") or ""
                role = input.get("role") or "user"
                enabled = bool(input.get("enabled", True))

                if current_role != "admin" and username != current_username:
                    return {"ok": False, "error": "You can only edit your own account"}

                if current_role != "admin":
                    # regular users can only change their own password
                    role = current_user.get("role", "user")
                    enabled = bool(current_user.get("enabled", True))
                    if not password:
                        return {"ok": False, "error": "Password required"}
                    user = user_store.upsert_user(
                        username=username,
                        password=password,
                        role=role,
                        enabled=enabled,
                        require_existing=True,
                    )
                else:
                    user = user_store.upsert_user(
                        username=username,
                        password=password,
                        role=role,
                        enabled=enabled,
                        require_existing=True,
                    )
                if username == (session.get("username") or ""):
                    session["role"] = user.get("role", "user")
                return {"ok": True, "data": user_store.sanitize_user(user)}

            if action == "delete":
                if current_role != "admin":
                    return {"ok": False, "error": "Admin only"}
                username = (input.get("username") or "").strip()
                if username == (session.get("username") or ""):
                    return {"ok": False, "error": "Cannot delete the currently logged-in admin"}
                user_store.delete_user(username)
                return {"ok": True}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

        return {"ok": False, "error": f"Unknown action: {action}"}
