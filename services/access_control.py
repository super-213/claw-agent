"""Authorization helpers for user-scoped sessions."""
from __future__ import annotations

from typing import Any


def is_admin(user: dict[str, Any] | None) -> bool:
    return bool(user and user.get("role") == "admin" and user.get("status") == "active")


def session_owner_id(session: dict[str, Any] | None) -> str | None:
    return str((session or {}).get("owner_user_id") or "") or None


def can_read_session(user: dict[str, Any] | None, session: dict[str, Any] | None) -> bool:
    if not user or user.get("status") != "active" or not session:
        return False
    if is_admin(user):
        return True
    user_id = user.get("id")
    if session_owner_id(session) == user_id:
        return True
    sharing = session.get("sharing") or {}
    scope = sharing.get("scope") or "private"
    if scope == "all":
        return True
    if scope == "selected":
        return user_id in set(sharing.get("user_ids") or [])
    return False


def can_write_session(user: dict[str, Any] | None, session: dict[str, Any] | None) -> bool:
    if not can_read_session(user, session):
        return False
    if is_admin(user) or session_owner_id(session) == user.get("id"):
        return True
    sharing = session.get("sharing") or {}
    return (sharing.get("permission") or "write") == "write"


def can_delete_session(user: dict[str, Any] | None, session: dict[str, Any] | None) -> bool:
    if not user or not session:
        return False
    return is_admin(user) or session_owner_id(session) == user.get("id")


def can_manage_users(user: dict[str, Any] | None) -> bool:
    return is_admin(user)


def normalize_sharing(payload: dict[str, Any] | None) -> dict[str, Any]:
    payload = payload or {}
    scope = payload.get("scope") or "private"
    if scope not in {"private", "all", "selected"}:
        raise ValueError("invalid_scope")
    permission = payload.get("permission") or "write"
    if permission not in {"read", "write"}:
        raise ValueError("invalid_permission")
    user_ids = payload.get("user_ids") or []
    if not isinstance(user_ids, list):
        raise ValueError("invalid_user_ids")
    cleaned_user_ids = []
    for user_id in user_ids:
        value = str(user_id or "").strip()
        if value and value not in cleaned_user_ids:
            cleaned_user_ids.append(value)
    if scope != "selected":
        cleaned_user_ids = []
    return {
        "scope": scope,
        "user_ids": cleaned_user_ids,
        "permission": permission,
    }
