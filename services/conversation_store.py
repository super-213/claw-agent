"""文件级对话持久化（非数据库）"""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Dict, List, Any

from .token_usage import TokenUsageEstimator


@dataclass
class SessionMeta:
    id: str
    title: str
    created_at: str
    updated_at: str
    token_usage: Dict[str, Any] | None = None


class ConversationStore:
    """基于 JSON 文件的对话存储"""

    def __init__(
        self,
        root_dir: str | Path,
        token_estimator: TokenUsageEstimator | None = None,
    ):
        self.root_dir = Path(root_dir)
        self.root_dir.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()
        self.token_estimator = token_estimator or TokenUsageEstimator()

    def list_sessions(self) -> List[SessionMeta]:
        sessions: List[SessionMeta] = []
        for path in self.root_dir.glob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            session_id = data.get("id") or path.stem
            sessions.append(
                SessionMeta(
                    id=session_id,
                    title=data.get("title", "新对话"),
                    created_at=data.get("created_at", ""),
                    updated_at=data.get("updated_at", ""),
                    token_usage=data.get("token_usage"),
                )
            )
        sessions.sort(key=lambda s: s.updated_at or s.created_at, reverse=True)
        return sessions

    def create_session(self, system_prompt: str, title: str | None = None) -> Dict[str, Any]:
        session_id = uuid.uuid4().hex
        now = self._now_iso()
        session = {
            "id": session_id,
            "title": title or "新对话",
            "created_at": now,
            "updated_at": now,
            "messages": [
                {"role": "system", "content": system_prompt, "ts": now},
            ],
            "summary": "",
            "summarized_until": 1,
        }
        self._annotate_session_usage(session)
        self._write_session(session_id, session)
        return session

    def load_session(self, session_id: str) -> Dict[str, Any]:
        path = self._path(session_id)
        if not path.exists():
            raise KeyError(f"Session not found: {session_id}")
        data = json.loads(path.read_text(encoding="utf-8"))
        return self._with_usage(data)

    def delete_session(self, session_id: str) -> None:
        with self._lock:
            path = self._path(session_id)
            if not path.exists():
                raise KeyError(f"Session not found: {session_id}")
            path.unlink()

    def clone_session(self, session_id: str) -> Dict[str, Any]:
        with self._lock:
            source = self.load_session(session_id)
            new_id = uuid.uuid4().hex
            now = self._now_iso()
            cloned = {
                **source,
                "id": new_id,
                "title": f"{source.get('title') or '新对话'} 副本",
                "created_at": now,
                "updated_at": now,
                "messages": [
                    {**message, "ts": message.get("ts", now)}
                    for message in source.get("messages", [])
                ],
                "summary": source.get("summary", ""),
                "summarized_until": source.get("summarized_until", 1),
            }
            self._annotate_session_usage(cloned)
            self._write_session(new_id, cloned)
            return cloned

    def save_messages(
        self,
        session_id: str,
        messages: List[Dict[str, str]],
        summary: str | None = None,
        summarized_until: int | None = None,
    ) -> Dict[str, Any]:
        with self._lock:
            data = self.load_session(session_id)
            stored = data.get("messages", [])
            now = self._now_iso()
            new_messages: List[Dict[str, Any]] = []

            for idx, msg in enumerate(messages):
                if (
                    idx < len(stored)
                    and stored[idx].get("role") == msg.get("role")
                    and stored[idx].get("content") == msg.get("content")
                ):
                    stored_message = {
                        key: value
                        for key, value in stored[idx].items()
                        if key != "usage"
                    }
                    new_messages.append(stored_message)
                else:
                    new_messages.append(
                        {
                            "role": msg.get("role", ""),
                            "content": msg.get("content", ""),
                            "ts": now,
                        }
                    )

            data["messages"] = new_messages
            if summary is not None:
                data["summary"] = summary
            if summarized_until is not None:
                data["summarized_until"] = max(1, min(summarized_until, len(new_messages)))
            data["updated_at"] = now

            if (not data.get("title") or data["title"] == "新对话"):
                first_user = next(
                    (m for m in new_messages if m.get("role") == "user"),
                    None,
                )
                if first_user and first_user.get("content"):
                    data["title"] = first_user["content"].strip()[:20]

            self._annotate_session_usage(data)
            self._write_session(session_id, data)
            return data

    def refresh_usage(self) -> List[str]:
        """为已有会话文件补齐 token 用量，返回更新过的 session id"""
        updated: List[str] = []
        with self._lock:
            for path in self.root_dir.glob("*.json"):
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                except Exception:
                    continue
                session_id = data.get("id") or path.stem
                self._annotate_session_usage(data)
                self._write_session(session_id, data)
                updated.append(session_id)
        return updated

    def _path(self, session_id: str) -> Path:
        return self.root_dir / f"{session_id}.json"

    def _write_session(self, session_id: str, data: Dict[str, Any]):
        path = self._path(session_id)
        path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _with_usage(self, data: Dict[str, Any]) -> Dict[str, Any]:
        if not data.get("messages"):
            data["messages"] = []
        self._annotate_session_usage(data)
        return data

    def _annotate_session_usage(self, data: Dict[str, Any]) -> None:
        messages = data.get("messages", [])
        annotated = self.token_estimator.annotate_messages(messages)
        data["messages"] = annotated
        data["token_usage"] = self.token_estimator.summarize_session(
            annotated,
            summary=data.get("summary", ""),
        )

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()
