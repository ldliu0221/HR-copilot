import hashlib
import hmac
import secrets

from app.core.constants import *
from app.core.storage import append_event, read_json, write_json, now_iso

def load_users():
    return read_json(USERS_FILE, [])


def save_users(users):
    write_json(USERS_FILE, users)


def hash_password(password, salt=None):
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 120000).hex()
    return salt, digest


def public_user(user):
    from app.collection.service import public_collection_source, normalize_user_collection_sources

    return {
        "id": user.get("id"),
        "username": user.get("username"),
        "role": user.get("role"),
        "display_name": user.get("display_name") or user.get("username"),
        "avatar_url": user.get("avatar_url", ""),
        "avatar_color": user.get("avatar_color", "#126b61"),
        "department": user.get("department", ""),
        "title": user.get("title", ""),
        "phone": user.get("phone", ""),
        "email": user.get("email", ""),
        "bio": user.get("bio", ""),
        "collection_sources": [public_collection_source(s) for s in normalize_user_collection_sources(user)],
        "created_at": user.get("created_at"),
        "last_login": user.get("last_login", ""),
    }


def create_user(username, password, role="hr", display_name="", manager_code=""):
    from app.config.service import load_app_config
    from app.data.service import normalize_legacy_status

    username = normalize_legacy_status(username)
    role = role if role in ["hr", "manager"] else "hr"
    if not username or len(username) < 2:
        raise ValueError("用户名至少 2 个字符")
    if not password or len(password) < 6:
        raise ValueError("密码至少 6 位")
    if role == "manager" and manager_code != load_app_config().get("manager_register_code"):
        raise ValueError("管理者注册码不正确")
    users = load_users()
    if any(u.get("username") == username for u in users):
        raise ValueError("用户名已存在")
    salt, digest = hash_password(password)
    user = {
        "id": secrets.token_hex(8),
        "username": username,
        "display_name": display_name or username,
        "role": role,
        "salt": salt,
        "password_hash": digest,
        "created_at": now_iso(),
        "last_login": "",
    }
    users.append(user)
    save_users(users)
    append_event("user_registered", None, {"username": username, "role": role}, actor=username)
    return public_user(user)


def verify_user(username, password):
    for user in load_users():
        if user.get("username") == username:
            _, digest = hash_password(password, user.get("salt"))
            if hmac.compare_digest(digest, user.get("password_hash", "")):
                user["last_login"] = now_iso()
                users = load_users()
                for item in users:
                    if item.get("id") == user.get("id"):
                        item["last_login"] = user["last_login"]
                save_users(users)
                return user
    return None


def update_user_account(user_id, payload):
    from app.collection.service import normalize_collection_sources, normalize_user_collection_sources
    from app.data.service import normalize_legacy_status

    users = load_users()
    idx = next((i for i, item in enumerate(users) if item.get("id") == user_id), None)
    if idx is None:
        raise ValueError("用户不存在")
    user = users[idx]
    username = normalize_legacy_status(payload.get("username", user.get("username", ""))).strip()
    if not username or len(username) < 2:
        raise ValueError("用户名至少 2 个字符")
    if any(item.get("id") != user_id and item.get("username") == username for item in users):
        raise ValueError("用户名已存在")
    user["username"] = username
    for key in ["display_name", "avatar_url", "avatar_color", "department", "title", "phone", "email", "bio"]:
        if key in payload:
            user[key] = str(payload.get(key) or "").strip()
    if isinstance(payload.get("collection_sources"), list):
        old_sources = {s.get("id"): s for s in normalize_user_collection_sources(user)}
        sources = []
        for item in payload["collection_sources"]:
            sid = str(item.get("id") or secrets.token_hex(4)).strip()
            source = {
                "id": sid,
                "name": item.get("name") or sid,
                "enabled": bool(item.get("enabled", True)),
                "api_url": item.get("api_url") or "",
                "method": (item.get("method") or "POST").upper(),
                "api_key": item.get("api_key") or "",
                "headers": item.get("headers") or "",
                "request_body": item.get("request_body") or "{}",
            }
            old = old_sources.get(sid)
            if old and not source["api_key"]:
                source["api_key"] = old.get("api_key", "")
            sources.append(source)
        user["collection_sources"] = normalize_collection_sources(sources)
    old_password = payload.get("old_password", "")
    new_password = payload.get("new_password", "")
    if new_password:
        if len(new_password) < 6:
            raise ValueError("新密码至少 6 位")
        _, old_digest = hash_password(old_password, user.get("salt"))
        if not hmac.compare_digest(old_digest, user.get("password_hash", "")):
            raise ValueError("原密码不正确")
        salt, digest = hash_password(new_password)
        user["salt"] = salt
        user["password_hash"] = digest
    users[idx] = user
    save_users(users)
    append_event("account_updated", None, {"username": user.get("username")}, actor=user.get("username"))
    return public_user(user)


def load_sessions():
    return read_json(SESSIONS_FILE, {})


def save_sessions(sessions):
    write_json(SESSIONS_FILE, sessions)


def create_session(user):
    token = secrets.token_urlsafe(32)
    sessions = load_sessions()
    sessions[token] = {"user_id": user.get("id"), "created_at": now_iso()}
    save_sessions(sessions)
    append_event("user_login", None, {"username": user.get("username")}, actor=user.get("username"))
    return token


def clear_session(token):
    sessions = load_sessions()
    if token in sessions:
        del sessions[token]
        save_sessions(sessions)


def get_user_by_session(token):
    if not token:
        return None
    session = load_sessions().get(token)
    if not session:
        return None
    for user in load_users():
        if user.get("id") == session.get("user_id"):
            return user
    return None

