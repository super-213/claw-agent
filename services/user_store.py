"""File-backed user storage and password verification."""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import uuid
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any


class UserStore:
    """Persist users in a single JSON file with atomic writes."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()

    def list_users(self, *, include_password: bool = False) -> list[dict[str, Any]]:
        with self._lock:
            users = [
                user for user in self._read().get("users", [])
                if user.get("status") != "deleted"
            ]
        users.sort(key=lambda user: user.get("created_at") or "")
        if include_password:
            return users
        return [self._public_user(user) for user in users]

    def list_usernames(self) -> list[str]:
        return [
            user["username"]
            for user in self.list_users()
            if user.get("status") == "active"
        ]

    def has_admin(self) -> bool:
        return any(
            user.get("role") == "admin" and user.get("status") != "deleted"
            for user in self.list_users(include_password=True)
        )

    def get_user(self, user_id: str) -> dict[str, Any] | None:
        with self._lock:
            user = self._find_by_id(self._read().get("users", []), user_id)
        return self._public_user(user) if user else None

    def get_user_by_username(
        self,
        username: str,
        *,
        include_password: bool = False,
    ) -> dict[str, Any] | None:
        username_key = self._normalize_username(username)
        with self._lock:
            user = next(
                (
                    item
                    for item in self._read().get("users", [])
                    if self._normalize_username(item.get("username")) == username_key
                ),
                None,
            )
        if not user:
            return None
        return dict(user) if include_password else self._public_user(user)

    def create_user(
        self,
        *,
        username: str,
        password: str,
        display_name: str | None = None,
        role: str = "user",
        status: str = "active",
    ) -> dict[str, Any]:
        username = self._validate_username(username)
        self._validate_password(password)
        role = self._validate_role(role)
        status = self._validate_status(status)

        with self._lock:
            data = self._read()
            users = data.setdefault("users", [])
            if any(
                self._normalize_username(user.get("username")) == self._normalize_username(username)
                and user.get("status") != "deleted"
                for user in users
            ):
                raise ValueError("username_exists")
            now = self._now_iso()
            user = {
                "id": f"u_{uuid.uuid4().hex}",
                "username": username,
                "display_name": (display_name or username).strip() or username,
                "role": role,
                "password_hash": self.hash_password(password),
                "status": status,
                "created_at": now,
                "updated_at": now,
                "last_login_at": None,
            }
            users.append(user)
            self._write(data)
        return self._public_user(user)

    def update_user(
        self,
        user_id: str,
        *,
        username: str | None = None,
        display_name: str | None = None,
        role: str | None = None,
        status: str | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            data = self._read()
            users = data.setdefault("users", [])
            user = self._find_by_id(users, user_id)
            if not user or user.get("status") == "deleted":
                raise KeyError(user_id)

            if username is not None:
                username = self._validate_username(username)
                username_key = self._normalize_username(username)
                if any(
                    item.get("id") != user_id
                    and item.get("status") != "deleted"
                    and self._normalize_username(item.get("username")) == username_key
                    for item in users
                ):
                    raise ValueError("username_exists")
                user["username"] = username
            if display_name is not None:
                user["display_name"] = display_name.strip() or user.get("username")
            if role is not None:
                user["role"] = self._validate_role(role)
            if status is not None:
                user["status"] = self._validate_status(status)
            self._ensure_active_admin_remains(users)
            user["updated_at"] = self._now_iso()
            self._write(data)
        return self._public_user(user)

    def delete_user(self, user_id: str) -> None:
        with self._lock:
            data = self._read()
            user = self._find_by_id(data.setdefault("users", []), user_id)
            if not user or user.get("status") == "deleted":
                raise KeyError(user_id)
            user["status"] = "deleted"
            self._ensure_active_admin_remains(data["users"])
            user["updated_at"] = self._now_iso()
            self._write(data)

    def reset_password(self, user_id: str, password: str) -> dict[str, Any]:
        self._validate_password(password)
        with self._lock:
            data = self._read()
            user = self._find_by_id(data.setdefault("users", []), user_id)
            if not user or user.get("status") == "deleted":
                raise KeyError(user_id)
            user["password_hash"] = self.hash_password(password)
            user["updated_at"] = self._now_iso()
            self._write(data)
        return self._public_user(user)

    def verify_password(self, username: str, password: str) -> dict[str, Any] | None:
        user = self.get_user_by_username(username, include_password=True)
        if not user or user.get("status") != "active":
            return None
        if not self.check_password(password, user.get("password_hash", "")):
            return None
        return self._public_user(user)

    def mark_login(self, user_id: str) -> None:
        with self._lock:
            data = self._read()
            user = self._find_by_id(data.setdefault("users", []), user_id)
            if not user:
                return
            now = self._now_iso()
            user["last_login_at"] = now
            user["updated_at"] = now
            self._write(data)

    @staticmethod
    def hash_password(password: str) -> str:
        salt = secrets.token_hex(16)
        digest = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt.encode("utf-8"),
            240_000,
        ).hex()
        return f"pbkdf2_sha256$240000${salt}${digest}"

    @staticmethod
    def check_password(password: str, password_hash: str) -> bool:
        try:
            algorithm, iterations, salt, digest = password_hash.split("$", 3)
        except ValueError:
            return False
        if algorithm != "pbkdf2_sha256":
            return False
        candidate = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt.encode("utf-8"),
            int(iterations),
        ).hex()
        return hmac.compare_digest(candidate, digest)

    def _read(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"users": []}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return {"users": []}
        if not isinstance(data, dict):
            return {"users": []}
        users = data.get("users")
        if not isinstance(users, list):
            data["users"] = []
        return data

    def _write(self, data: dict[str, Any]) -> None:
        tmp_path = self.path.with_name(f".{self.path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
        tmp_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp_path, self.path)

    @staticmethod
    def _public_user(user: dict[str, Any]) -> dict[str, Any]:
        return {
            key: value
            for key, value in dict(user).items()
            if key != "password_hash"
        }

    @staticmethod
    def _find_by_id(users: list[dict[str, Any]], user_id: str) -> dict[str, Any] | None:
        return next((user for user in users if user.get("id") == user_id), None)

    @staticmethod
    def _ensure_active_admin_remains(users: list[dict[str, Any]]) -> None:
        active_admins = [
            user for user in users
            if user.get("role") == "admin" and user.get("status") == "active"
        ]
        if not active_admins:
            raise ValueError("last_admin")

    @staticmethod
    def _normalize_username(username: Any) -> str:
        return str(username or "").strip().casefold()

    @classmethod
    def _validate_username(cls, username: str) -> str:
        value = (username or "").strip()
        if len(value) < 2 or len(value) > 40:
            raise ValueError("invalid_username")
        if any(char.isspace() for char in value):
            raise ValueError("invalid_username")
        return value

    @staticmethod
    def _validate_password(password: str) -> None:
        if not password or len(password) < 6:
            raise ValueError("weak_password")

    @staticmethod
    def _validate_role(role: str) -> str:
        if role not in {"admin", "user"}:
            raise ValueError("invalid_role")
        return role

    @staticmethod
    def _validate_status(status: str) -> str:
        if status not in {"active", "disabled"}:
            raise ValueError("invalid_status")
        return status

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()
