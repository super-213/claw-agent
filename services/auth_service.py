"""Cookie session helpers for the web UI."""
from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from threading import Lock
from typing import Any


class AuthSessionStore:
    """Small in-memory session table keyed by opaque cookie token."""

    def __init__(self, ttl_hours: int = 72):
        self.ttl = timedelta(hours=ttl_hours)
        self._lock = Lock()
        self._sessions: dict[str, dict[str, Any]] = {}

    def create(self, user_id: str) -> str:
        token = secrets.token_urlsafe(32)
        now = self._now()
        with self._lock:
            self._sessions[token] = {
                "user_id": user_id,
                "created_at": now,
                "expires_at": now + self.ttl,
            }
        return token

    def get_user_id(self, token: str | None) -> str | None:
        if not token:
            return None
        now = self._now()
        with self._lock:
            session = self._sessions.get(token)
            if not session:
                return None
            if session["expires_at"] <= now:
                self._sessions.pop(token, None)
                return None
            session["expires_at"] = now + self.ttl
            return str(session["user_id"])

    def delete(self, token: str | None) -> None:
        if not token:
            return
        with self._lock:
            self._sessions.pop(token, None)

    @staticmethod
    def _now() -> datetime:
        return datetime.now(timezone.utc)
