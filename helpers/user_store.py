from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


from helpers import dotenv

USERS_PATH = Path("/a0/usr/users.json")
ROLES = {"admin", "user"}
USERNAME_RE = re.compile(r"^[A-Za-z0-9_.@-]{3,64}$")
MIN_PASSWORD_LENGTH = 8


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_username(username: str) -> str:
    return (username or "").strip()


def validate_username(username: str) -> None:
    username = normalize_username(username)
    if not USERNAME_RE.match(username):
        raise ValueError("Username must be 3-64 characters using letters, numbers, dot, underscore, hyphen, or @")


def validate_role(role: str) -> str:
    role = (role or "user").strip().lower()
    if role not in ROLES:
        raise ValueError("Invalid role")
    return role


def validate_password(password: str, *, allow_empty: bool = False) -> None:
    if allow_empty and not password:
        return
    if not password or len(password) < MIN_PASSWORD_LENGTH:
        raise ValueError(f"Password must be at least {MIN_PASSWORD_LENGTH} characters")


def _legacy_hash_password(username: str, password: str) -> str:
    import hashlib
    from helpers import runtime

    runtime_id = runtime.get_runtime_id()
    return hashlib.sha256(f"{runtime_id}:{username}:{password}".encode()).hexdigest()


def _hash_password(password: str) -> str:
    iterations = 600_000
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return "pbkdf2_sha256${}${}${}".format(
        iterations,
        base64.b64encode(salt).decode("ascii"),
        base64.b64encode(digest).decode("ascii"),
    )


def _check_password(password_hash: str, password: str) -> bool:
    try:
        algorithm, iterations_s, salt_b64, digest_b64 = password_hash.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        iterations = int(iterations_s)
        salt = base64.b64decode(salt_b64.encode("ascii"))
        expected = base64.b64decode(digest_b64.encode("ascii"))
        actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
        return hmac.compare_digest(actual, expected)
    except Exception:
        return False


def _default_admin_user() -> dict[str, Any] | None:
    username = normalize_username(dotenv.get_dotenv_value(dotenv.KEY_AUTH_LOGIN) or "")
    password = dotenv.get_dotenv_value(dotenv.KEY_AUTH_PASSWORD) or ""
    if not username or not password:
        return None
    validate_username(username)
    validate_password(password)
    now = _now()
    return {
        "user_id": username,
        "username": username,
        "password_hash": _hash_password(password),
        "role": "admin",
        "enabled": True,
        "created_at": now,
        "updated_at": now,
    }


def _read_raw_users() -> list[dict[str, Any]]:
    if USERS_PATH.exists():
        try:
            data = json.loads(USERS_PATH.read_text())
            if isinstance(data, list):
                return [u for u in data if isinstance(u, dict)]
        except Exception:
            return []
    return []


def load_users() -> list[dict[str, Any]]:
    users = _read_raw_users()
    if users:
        return users
    seed = _default_admin_user()
    if seed:
        save_users([seed])
        return [seed]
    return []


def save_users(users: list[dict[str, Any]]) -> None:
    USERS_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(users, indent=2, ensure_ascii=False)
    fd, tmp_path = tempfile.mkstemp(prefix="users.", suffix=".tmp", dir=str(USERS_PATH.parent))
    try:
        with os.fdopen(fd, "w") as tmp:
            tmp.write(payload)
            tmp.flush()
            os.fsync(tmp.fileno())
        os.chmod(tmp_path, 0o600)
        os.replace(tmp_path, USERS_PATH)
        try:
            dir_fd = os.open(str(USERS_PATH.parent), os.O_DIRECTORY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
        except Exception:
            pass
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


def has_users() -> bool:
    return bool(load_users())


def enabled_admins(users: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    users = load_users() if users is None else users
    return [u for u in users if u.get("enabled", True) and u.get("role") == "admin"]


def has_admin() -> bool:
    return bool(enabled_admins())


def needs_bootstrap() -> bool:
    return not has_admin()


def find_user(username: str) -> dict[str, Any] | None:
    username = normalize_username(username)
    for user in load_users():
        if normalize_username(str(user.get("username", ""))).lower() == username.lower():
            return user
    return None


def find_user_by_id(user_id: str) -> dict[str, Any] | None:
    user_id = str(user_id or "").strip()
    for user in load_users():
        if str(user.get("user_id") or "").strip() == user_id:
            return user
    return None


def authenticate(username: str, password: str) -> dict[str, Any] | None:
    user = find_user(username)
    if not user or not user.get("enabled", True):
        return None
    stored_hash = str(user.get("password_hash") or "")
    ok = False
    if stored_hash.startswith("pbkdf2_sha256$"):
        ok = _check_password(stored_hash, password)
    else:
        # One-time compatibility for legacy sha256 users.
        ok = stored_hash == _legacy_hash_password(str(user.get("username") or username), password)
        if ok:
            user["password_hash"] = _hash_password(password)
            user["updated_at"] = _now()
            users = load_users()
            for idx, existing in enumerate(users):
                if normalize_username(str(existing.get("username", ""))).lower() == normalize_username(username).lower():
                    users[idx] = user
                    save_users(users)
                    break
    return user if ok else None


def list_users() -> list[dict[str, Any]]:
    return load_users()


def _sanitize_user(user: dict[str, Any]) -> dict[str, Any]:
    return {
        "user_id": user.get("user_id"),
        "username": user.get("username"),
        "role": user.get("role", "user"),
        "enabled": bool(user.get("enabled", True)),
        "created_at": user.get("created_at"),
        "updated_at": user.get("updated_at"),
    }


def sanitize_user(user: dict[str, Any]) -> dict[str, Any]:
    return _sanitize_user(user)


def create_first_admin(username: str, password: str) -> dict[str, Any]:
    if has_admin():
        raise ValueError("Admin user already exists")
    return upsert_user(username=username, password=password, role="admin", enabled=True, require_existing=False)


def upsert_user(
    username: str,
    password: str = "",
    role: str = "user",
    enabled: bool = True,
    *,
    require_existing: bool | None = None,
) -> dict[str, Any]:
    users = load_users()
    username = normalize_username(username)
    validate_username(username)
    role = validate_role(role)

    existing_index = None
    existing = None
    for idx, user in enumerate(users):
        if normalize_username(str(user.get("username", ""))).lower() == username.lower():
            existing_index = idx
            existing = user
            break

    if require_existing is True and existing is None:
        raise ValueError("User does not exist")
    if require_existing is False and existing is not None:
        raise ValueError("Username already exists")

    if existing is None:
        validate_password(password)
        now = _now()
        user = {
            "user_id": username,
            "username": username,
            "password_hash": _hash_password(password),
            "role": role,
            "enabled": bool(enabled),
            "created_at": now,
            "updated_at": now,
        }
        users.append(user)
    else:
        validate_password(password, allow_empty=True)
        user = dict(existing)
        before_admin_count = len(enabled_admins(users))
        was_enabled_admin = user.get("enabled", True) and user.get("role") == "admin"
        will_enabled_admin = bool(enabled) and role == "admin"
        if was_enabled_admin and not will_enabled_admin and before_admin_count <= 1:
            raise ValueError("Cannot disable or demote the last enabled admin")
        user.update({"username": username, "role": role, "enabled": bool(enabled), "updated_at": _now()})
        if password:
            user["password_hash"] = _hash_password(password)
        users[existing_index] = user  # type: ignore[index]

    save_users(users)
    return user


def delete_user(username: str) -> None:
    users = load_users()
    username = normalize_username(username)
    remaining: list[dict[str, Any]] = []
    removed = None
    for user in users:
        if normalize_username(str(user.get("username", ""))).lower() == username.lower():
            removed = user
        else:
            remaining.append(user)
    if removed is None:
        raise ValueError("User does not exist")
    if removed.get("enabled", True) and removed.get("role") == "admin" and not enabled_admins(remaining):
        raise ValueError("Cannot delete the last enabled admin")
    save_users(remaining)
