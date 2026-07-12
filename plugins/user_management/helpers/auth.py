import bcrypt
from usr.plugins.user_management.helpers.db import execute_query, execute_write


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))


def create_user(username: str, password: str, role: str = "user"):
    pw_hash = hash_password(password)
    return execute_write(
        "INSERT INTO um_users (username, password_hash, role) "
        "VALUES (%s, %s, %s) RETURNING id, username, role, created_at",
        (username, pw_hash, role),
        returning=True,
    )


def verify_user(username: str, password: str):
    rows = execute_query(
        "SELECT id, username, password_hash, role FROM um_users WHERE username = %s",
        (username,),
    )
    if not rows:
        return None
    user = rows[0]
    if verify_password(password, user["password_hash"]):
        return {"id": user["id"], "username": user["username"], "role": user["role"]}
    return None


def get_user(user_id: int):
    rows = execute_query(
        "SELECT id, username, role, created_at FROM um_users WHERE id = %s",
        (user_id,),
    )
    return rows[0] if rows else None


def list_users():
    return execute_query(
        "SELECT id, username, role, created_at FROM um_users ORDER BY id"
    )


def delete_user(user_id: int):
    execute_write("DELETE FROM um_users WHERE id = %s", (user_id,))


def update_user(user_id: int, username=None, password=None, role=None):
    parts, params = [], []
    if username is not None:
        parts.append("username = %s")
        params.append(username)
    if password is not None:
        parts.append("password_hash = %s")
        params.append(hash_password(password))
    if role is not None:
        parts.append("role = %s")
        params.append(role)
    if not parts:
        return get_user(user_id)
    params.append(user_id)
    execute_write(
        "UPDATE um_users SET " + ", ".join(parts) + " WHERE id = %s",
        params,
    )
    return get_user(user_id)


def get_current_user_from_session():
    """Get current user from Flask session (safe for non-request contexts)."""
    try:
        from flask import session, has_request_context
        if not has_request_context():
            return None
        user_id = session.get("um_user_id")
        if not user_id:
            return None
        return get_user(user_id)
    except Exception:
        return None


def set_session_user(user: dict):
    from flask import session
    session["um_user_id"] = user["id"]
    session["um_username"] = user["username"]
    session["um_role"] = user["role"]


def clear_session_user():
    from flask import session
    for key in ("um_user_id", "um_username", "um_role"):
        session.pop(key, None)


def ensure_admin_user():
    """Create the initial admin account if it does not exist."""
    admin_username = "admin"
    admin_password = "admin123"
    try:
        from helpers.plugins import get_plugin_config
        config = get_plugin_config("user_management")
        if config:
            admin_username = config.get("admin_username", admin_username)
            admin_password = config.get("admin_default_password", admin_password)
    except Exception:
        pass

    existing = execute_query(
        "SELECT id FROM um_users WHERE username = %s", (admin_username,)
    )
    if not existing:
        create_user(admin_username, admin_password, role="admin")
