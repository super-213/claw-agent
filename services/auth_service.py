"""Cookie session helpers for the web UI."""
from __future__ import annotations

import hashlib
import json
import os
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Lock
from typing import Any


class AuthSessionStore:
    """Session table keyed by hashed opaque cookie tokens."""

    def __init__(self, ttl_hours: int = 72, remember_ttl_days: int = 30, path: str | Path | None = None):
        self.ttl_seconds = int(timedelta(hours=ttl_hours).total_seconds())
        self.remember_ttl_seconds = int(timedelta(days=remember_ttl_days).total_seconds())
        self.path = Path(path) if path else None
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()
        self._sessions: dict[str, dict[str, Any]] = {}
        self._load_persisted()

    def create(self, user_id: str, *, remember_me: bool = False) -> str:
        token = secrets.token_urlsafe(32)
        token_hash = self._hash_token(token)
        now = self._now()
        ttl_seconds = self.remember_ttl_seconds if remember_me else self.ttl_seconds
        with self._lock:
            self._sessions[token_hash] = {
                "user_id": user_id,
                "created_at": now,
                "expires_at": now + timedelta(seconds=ttl_seconds),
                "ttl_seconds": ttl_seconds,
                "remember_me": remember_me,
            }
            self._persist_locked()
        return token

    def get_user_id(self, token: str | None) -> str | None:
        if not token:
            return None
        now = self._now()
        token_hash = self._hash_token(token)
        with self._lock:
            session = self._sessions.get(token_hash)
            if not session:
                return None
            if session["expires_at"] <= now:
                self._sessions.pop(token_hash, None)
                self._persist_locked()
                return None
            ttl_seconds = int(session.get("ttl_seconds") or self.ttl_seconds)
            session["expires_at"] = now + timedelta(seconds=ttl_seconds)
            self._persist_locked()
            return str(session["user_id"])

    def delete(self, token: str | None) -> None:
        if not token:
            return
        with self._lock:
            self._sessions.pop(self._hash_token(token), None)
            self._persist_locked()

    def max_age_seconds(self, *, remember_me: bool = False) -> int:
        return self.remember_ttl_seconds if remember_me else self.ttl_seconds

    def should_refresh_cookie(self, token: str | None) -> bool:
        if not token:
            return False
        with self._lock:
            session = self._sessions.get(self._hash_token(token))
            return bool(session and session.get("remember_me"))

    def _load_persisted(self) -> None:
        if not self.path or not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return
        if not isinstance(data, dict):
            return

        now = self._now()
        sessions = data.get("sessions")
        if not isinstance(sessions, dict):
            return
        for token_hash, session in sessions.items():
            if not isinstance(token_hash, str) or not isinstance(session, dict):
                continue
            if not session.get("remember_me"):
                continue
            try:
                expires_at = datetime.fromisoformat(str(session.get("expires_at")))
                created_at = datetime.fromisoformat(str(session.get("created_at")))
            except ValueError:
                continue
            if expires_at <= now:
                continue
            self._sessions[token_hash] = {
                "user_id": str(session.get("user_id") or ""),
                "created_at": created_at,
                "expires_at": expires_at,
                "ttl_seconds": int(session.get("ttl_seconds") or self.remember_ttl_seconds),
                "remember_me": True,
            }

    def _persist_locked(self) -> None:
        if not self.path:
            return
        now = self._now()
        sessions = {
            token_hash: {
                "user_id": session["user_id"],
                "created_at": session["created_at"].isoformat(),
                "expires_at": session["expires_at"].isoformat(),
                "ttl_seconds": int(session.get("ttl_seconds") or self.remember_ttl_seconds),
                "remember_me": True,
            }
            for token_hash, session in self._sessions.items()
            if session.get("remember_me") and session["expires_at"] > now
        }
        tmp_path = self.path.with_name(f".{self.path.name}.{os.getpid()}.{secrets.token_hex(8)}.tmp")
        tmp_path.write_text(json.dumps({"sessions": sessions}, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp_path, self.path)

    @staticmethod
    def _hash_token(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    @staticmethod
    def _now() -> datetime:
        return datetime.now(timezone.utc)
