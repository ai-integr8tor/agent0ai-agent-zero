from helpers import user_store


def get_credentials_hash():
    users = user_store.list_users()
    return "multi_user_login_enabled" if users else None


def is_login_required():
    return user_store.needs_bootstrap() or bool(user_store.list_users())


def is_authenticated_session(session) -> bool:
    if user_store.needs_bootstrap():
        return False
    users_hash = get_credentials_hash()
    if not users_hash:
        return False
    if session.get("authentication") != users_hash:
        return False
    user = user_store.find_user_by_id(session.get("user_id") or "") or user_store.find_user(session.get("username") or "")
    if not user or not user.get("enabled", True):
        return False
    return True
